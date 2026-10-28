"""Explicit units and outcome semantics. Unknown direction stays unknown."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, minimum=0, maximum=None):
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < minimum or (maximum is not None and parsed > maximum):
        raise ValueError(f"Invalid numeric field: {value}")
    return str(parsed)


def array(value):
    return json.loads(value) if isinstance(value, str) else (value or [])


def market(venue, row, received_at):
    if venue == "polymarket":
        key = str(row["id"])
        outcomes, tokens = array(row.get("outcomes")), array(row.get("clobTokenIds"))
        rules = {"description": row.get("description"), "resolution_source": row.get("resolutionSource"),
                 "outcomes": outcomes, "tokens": tokens, "end_date": row.get("endDate")}
        result = dict(id=key, condition_id=row.get("conditionId"), title=row.get("question", ""),
                      event_ids=[str(e["id"]) for e in row.get("events", [])],
                      outcomes=outcomes, tokens=tokens, closed=bool(row.get("closed")),
                      category=row.get("category"), tags=row.get("tags", []),
                      volume=number(row.get("volumeNum") or row.get("volume") or 0),
                      end_time=row.get("endDate"))
    else:
        key = row["ticker"]
        rules = {k: row.get(k) for k in ("rules_primary", "rules_secondary", "close_time", "expiration_time",
                                        "yes_sub_title", "no_sub_title", "settlement_timer_seconds")}
        result = dict(id=key, condition_id=None, title=row.get("title", ""),
                      event_ids=[row["event_ticker"]], outcomes=["yes", "no"], tokens=[],
                      closed=row.get("status") not in ("open", "active", "initialized"),
                      category=row.get("category"), tags=[], volume=number(row.get("volume_fp") or 0),
                      end_time=row.get("close_time"))
    return dict(result, venue=venue, rules=rules, rules_hash=digest(rules), observed_at=received_at)


def trade(venue, row, received_at):
    if venue == "polymarket":
        side = row["side"].upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("Unknown Polymarket side")
        outcome = str(row["outcome"])
        result = dict(market_id=row["condition_id"], outcome=outcome, token_id=str(row["token_id"]),
                      price=number(row["price"], maximum=1), quantity=number(row["size"]),
                      event_time=timestamp(row["timestamp"]), wallet=row.get("proxy_wallet") or None,
                      direction=1 if side == "BUY" else -1, transaction_hash=row["transaction_hash"],
                      identity_quality="execution_fingerprint_with_scan_multiplicity")
        # Public v2 rows lack a fill id: transaction hash alone is NOT unique.
        identity = digest({k: result[k] for k in ("market_id", "token_id", "price", "quantity", "event_time",
                                                 "wallet", "direction", "transaction_hash")})
    else:
        outcome = row.get("taker_outcome_side") or row.get("taker_side")
        if outcome not in ("yes", "no", None):
            raise ValueError("Unknown Kalshi outcome")
        book_side = row.get("taker_book_side")
        # These are the SAME directional bit, not independent buy/sell axes.
        if book_side not in (None, "bid", "ask"):
            raise ValueError("Unknown Kalshi book side")
        book_outcome = {"bid": "yes", "ask": "no"}.get(book_side)
        if outcome and book_outcome and outcome != book_outcome:
            raise ValueError("Inconsistent Kalshi direction fields")
        outcome = outcome or book_outcome
        result = dict(market_id=row["ticker"], outcome="yes", token_id=None,
                      price=number(row["yes_price_dollars"], maximum=1), quantity=number(row["count_fp"]),
                      event_time=timestamp(row["created_time"]), wallet=None,
                      direction=(1 if outcome == "yes" else -1) if outcome else None,
                      transaction_hash=None, identity_quality="venue_trade_id",
                      is_block_trade=bool(row.get("is_block_trade", False)))
        identity = str(row["trade_id"])
    return dict(result, venue=venue, identity=identity, received_at=received_at, first_seen_at=received_at)
