"""Bounded public-tape studies with peer/quiet controls and explicit time assumptions.

python -m surveillance.research.study --config study.json --data-dir /path --fetch
No database writes, trades or future outcome labels enter the detector.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from surveillance.research.legacy_detector import evaluate, automatic_candidate, VERSION
from surveillance.normalization import trade


def request(url):
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": "MarketSurveillanceResearch/1.1"}), timeout=30) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def fetch_market(folder, market_id, earliest, page_cap=100):
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "manifest.json").exists():
        manifest = json.loads((folder / "manifest.json").read_text())
        if datetime.fromisoformat(manifest["oldest"]) <= earliest:
            market = json.loads((folder / "market.json").read_text())
            if str(market["id"]) != str(market_id):
                raise ValueError("Cached dataset belongs to another contract")
            return
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    body = request(url)
    (folder / "market-response.json").write_bytes(body)
    market = json.loads(body)
    if str(market["id"]) != str(market_id):
        raise ValueError("Wrong market detail response")
    (folder / "market.json").write_text(json.dumps(market, indent=2))
    pages, seen, cursor, previous = [], set(), None, None
    complete = False
    for page in range(page_cap):
        params = {"condition": market["conditionId"], "taker_only": "true", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        url = "https://data-api.polymarket.com/v2/trades?" + urlencode(params)
        body = request(url)
        received = datetime.now(timezone.utc).isoformat()
        target = folder / f"trades-{page:03d}.json"
        target.write_bytes(body)
        data = json.loads(body)
        rows = data["data"]
        for row in rows:
            if row["condition_id"] != market["conditionId"]:
                raise ValueError("Wrong market in trade feed")
            if previous is not None and row["timestamp"] > previous:
                raise ValueError("Trade feed is not newest-first")
            previous = row["timestamp"]
        pages.append({"path": target.name, "sha256": hashlib.sha256(body).hexdigest(),
                      "received_at": received, "url": url, "rows": len(rows)})
        cursor = data["pagination"].get("next_cursor")
        if bool(cursor) != data["pagination"]["has_more"]:
            raise ValueError("Inconsistent pagination")
        if not cursor or (rows and rows[-1]["timestamp"] < earliest.timestamp()):
            complete = True
            break
        if cursor in seen:
            raise ValueError("Pagination cycle")
        seen.add(cursor)
        time.sleep(.65)
    manifest = {"market_id": str(market_id), "condition_id": market["conditionId"], "pages": pages,
                "walk_reached_lower_boundary_or_end": complete, "page_cap": page_cap,
                "oldest": datetime.fromtimestamp(previous or 0, timezone.utc).isoformat(),
                "note": "Retrospective API retrieval; historical delivery times are unknown"}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if not complete:
        raise ValueError("Page cap reached; no complete-window claim or study score")


def load_tape(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    tape, counts = [], Counter()
    if not manifest["walk_reached_lower_boundary_or_end"]:
        raise ValueError("Incomplete historical walk")
    previous = None
    for page in manifest["pages"]:
        body = (folder / page["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != page["sha256"]:
            raise ValueError("Evidence checksum mismatch")
        for row in json.loads(body)["data"]:
            if row["condition_id"] != manifest["condition_id"]:
                raise ValueError("Unexpected contract in archived tape")
            if previous is not None and row["timestamp"] > previous:
                raise ValueError("Nonmonotonic archived walk")
            previous = row["timestamp"]
            t = trade("polymarket", row, page["received_at"])
            counts[t["identity"]] += 1
            t["id"] = f"{t['identity']}:{counts[t['identity']]}"
            tape.append(t)
    return sorted(tape, key=lambda t: (t["event_time"], t["id"]))


def run_case(case, tape):
    start, end = map(datetime.fromisoformat, (case["start"], case["end"]))
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("A timezone-aware increasing study interval is required")
    times_all = [datetime.fromisoformat(t["event_time"]) for t in tape]
    if not times_all or min(times_all) > start - timedelta(hours=13):
        raise ValueError("Missing 13-hour baseline boundary")
    yes = sorted((t for t in tape if t["outcome"].lower() == "yes"), key=lambda t: (t["event_time"],t["id"]))
    times = [datetime.fromisoformat(t["event_time"]) for t in yes]
    raw, floor, research = [], [], []
    rejected = 0
    at = start
    while at < end:
        lo, hi = bisect_left(times, at-timedelta(hours=13)), bisect_right(times, at)
        if hi-lo > 50000:
            rejected += 1
            at += timedelta(minutes=1)
            continue
        # Hypothetical zero-latency study only. Original receipts remain untouched.
        simulated = [dict(t, received_at=t["event_time"]) for t in yes[lo:hi]]
        for signal in evaluate(simulated, at.isoformat()):
            if signal["anomaly_score"] < 35:
                continue
            compact = {k: v for k, v in signal.items() if k not in ("trade_ids", "limitations")}
            raw.append(compact)
            if automatic_candidate(signal):
                floor.append(compact)
            if (signal["anomaly_score"] >= 70 and signal["trade_count"] >= 5
                    and (signal["signed_imbalance"] or 0) >= .6 and signal["cash_notional_usd"] >= 1000):
                research.append(compact)
        at += timedelta(minutes=1)
    def summary(rows):
        return {"minute_windows": len(rows), "distinct_minutes": len({s["as_of"] for s in rows}),
                "first": rows[0] if rows else None,
                "peak": max(rows, key=lambda s: s["anomaly_score"]) if rows else None}
    return {**case, "detector_version": VERSION, "rejected_over_capacity_minutes": rejected,
            "raw_threshold_35": summary(raw), "automatic_cash_floor": summary(floor),
            "research_buy_gate": summary(research)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(args.config.read_text())["cases"]
    groups = {}
    for case in cases:
        groups.setdefault(case["dataset"], []).append(case)
    tapes = {}
    for dataset, members in groups.items():
        ids = {str(c["market_id"]) for c in members}
        if len(ids) != 1:
            raise ValueError("Conflicting market IDs for dataset")
        folder = args.data_dir / dataset
        if args.fetch:
            earliest = min(datetime.fromisoformat(c["start"]) for c in members) - timedelta(hours=13)
            fetch_market(folder, ids.pop(), earliest)
        tapes[dataset] = load_tape(folder)
        stored = json.loads((folder / "market.json").read_text())
        if str(stored["id"]) != str(members[0]["market_id"]):
            raise ValueError("Study config and evidence contract differ")
    results = [run_case(c, tapes[c["dataset"]]) for c in cases]
    output = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "source_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                (Path(__file__).parent/"legacy_detector.py", Path(__file__).parent.parent/"normalization.py", Path(__file__))},
              "assumptions": ["Retrospective selected reported cases; no accuracy estimate",
                              "Historical delivery unknown; event_time used as hypothetical receipt time in memory",
                              "Peers can have legitimate correlated event information; not certified clean negatives",
                              "Research buy gate is not deployed or calibrated; automatic floor is a cost policy",
                              "No known outcomes, profits, current rules or later wallet history enter scores"],
              "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    for r in results:
        print(json.dumps({"case": r["name"], "role": r["role"], "raw_minutes": r["raw_threshold_35"]["distinct_minutes"],
                          "cash_floor_minutes": r["automatic_cash_floor"]["distinct_minutes"],
                          "buy_gate_minutes": r["research_buy_gate"]["distinct_minutes"]}))


if __name__ == "__main__":
    main()
