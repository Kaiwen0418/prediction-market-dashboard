from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest

from surveillance.collectors import unpack, ContractError
from surveillance.detectors import evaluate
from surveillance.discovery import select
from surveillance.normalization import trade, market, timestamp
from surveillance.storage import RawArchive


T = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def poly(**updates):
    return dict(condition_id="c1", token_id="yes-token", price=0.6, size=10, timestamp=int(T.timestamp()),
                outcome="Yes", side="BUY", proxy_wallet="wallet", transaction_hash="tx", **updates)


def kalshi(**updates):
    row = dict(ticker="K1", trade_id="kt1", yes_price_dollars="0.6", count_fp="10.50",
               created_time=T.isoformat(), taker_outcome_side="yes", taker_book_side="bid")
    row.update(updates)
    return row


class CoreTests(unittest.TestCase):
    def test_kalshi_direction_and_anonymity(self):
        t = trade("kalshi", kalshi(taker_outcome_side="no", taker_book_side="ask"), T.isoformat())
        self.assertEqual(t["direction"], -1)
        self.assertEqual(t["price"], "0.6")
        self.assertIsNone(t["wallet"])
        self.assertEqual(t["quantity"], "10.50")
        with self.assertRaises(ValueError):
            trade("kalshi", kalshi(taker_book_side="ask"), T.isoformat())

    def test_polymarket_execution_identity(self):
        a = trade("polymarket", poly(), T.isoformat())
        b = trade("polymarket", dict(poly(), token_id="no-token", outcome="No"), T.isoformat())
        self.assertNotEqual(a["identity"], b["identity"])
        self.assertEqual(b["direction"], 1)
        self.assertEqual(b["outcome"], "No")

    def test_unknown_and_invalid_values(self):
        for value in (None, "NaN", "Infinity", -1, 1.1):
            with self.assertRaises(Exception):
                trade("polymarket", dict(poly(), price=value), T.isoformat())
        with self.assertRaises(ValueError):
            timestamp("2026-10-28T12:00:00")

    def test_v2_follows_empty_page_cursor(self):
        self.assertEqual(unpack("polymarket", "trades", {"data": [], "pagination": {"has_more": True, "next_cursor": "next"}}), ([], "next"))
        for body in ([], {"data": []}, {"data": [], "pagination": {"has_more": True, "next_cursor": None}}):
            with self.assertRaises(ContractError):
                unpack("polymarket", "trades", body)

    def test_all_catalog_outcomes_and_rules(self):
        m = market("polymarket", {"id": "p1", "conditionId": "c1", "outcomes": '["A","B","C"]',
                   "clobTokenIds": '["1","2","3"]', "description": "rules", "events": [{"id": 8}]}, T.isoformat())
        self.assertEqual(len(m["outcomes"]), 3)
        self.assertEqual(m["event_ids"], ["8"])
        updated = market("polymarket", {"id": "p1", "description": "changed"}, T.isoformat())
        self.assertNotEqual(m["rules_hash"], updated["rules_hash"])

    def test_budget_includes_quiet_exploration(self):
        markets = [dict(id=str(i), venue="kalshi", condition_id=None, closed=False, title="Policy announcement" if i < 100 else "quiet",
                        volume="100000" if i < 100 else "0") for i in range(200)]
        chosen = select(markets, 20, 0.2, T)
        self.assertEqual(len(chosen), 20)
        self.assertEqual(len({m["id"] for m in chosen}), 20)
        # Exploration candidates include low-volume contracts; rank cannot exclude them.
        self.assertTrue(any(m["volume"] == "0" for m in chosen))
        self.assertEqual(chosen, select(markets, 20, 0.2, T))

    def test_raw_archive_retains_exact_bytes_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = RawArchive(folder)
            r = archive.write("kalshi", "https://example.test", {}, 200, b'{ "exact": 1 }')
            self.assertEqual(archive.read(r), b'{ "exact": 1 }')
            with self.assertRaises(ValueError):
                archive.read(dict(r, sha256="bad"))
            self.assertEqual(list(Path(folder).rglob("*.tmp")), [])

    def test_detection_has_no_future_or_late_observation_leakage(self):
        rows = []
        for i in range(12):
            t = trade("polymarket", dict(poly(), timestamp=int((T - timedelta(seconds=90 + i * 60)).timestamp())), T.isoformat())
            rows.append(dict(t, id=f"baseline{i}"))
        for i in range(10):
            t = trade("polymarket", dict(poly(), size=100, price=0.4 + i * 0.02,
                      timestamp=int((T - timedelta(seconds=30 - i)).timestamp())), T.isoformat())
            rows.append(dict(t, id=f"current{i}"))
        score = evaluate(rows, T.isoformat())[0]
        self.assertGreater(score["anomaly_score"], 90)
        future = dict(rows[-1], id="future", event_time=(T + timedelta(seconds=1)).isoformat())
        late = dict(rows[-1], id="late", received_at=(T + timedelta(seconds=1)).isoformat())
        self.assertEqual(evaluate(rows + [future, late], T.isoformat())[0], score)
        self.assertEqual(evaluate(rows, T.isoformat())[0], score)

    def test_block_trades_excluded_from_order_flow_imbalance(self):
        t = trade("kalshi", kalshi(is_block_trade=True), T.isoformat())
        signal = evaluate([dict(t, id="block")], T.isoformat())[0]
        self.assertIsNone(signal["signed_imbalance"])

    def test_no_invented_price_sequence_for_same_timestamp(self):
        trades = [dict(trade("polymarket", dict(poly(), price=p), T.isoformat()), id=str(i))
                  for i, p in enumerate([0.1, 0.2, 0.3, 0.8, 0.9])]
        self.assertIsNone(evaluate(trades, T.isoformat())[0]["price_change"])
