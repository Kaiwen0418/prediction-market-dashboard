"""Budgeted selection over an unfiltered catalog, with rotating exploration."""
from datetime import datetime, timezone
import math

from .normalization import digest


P0 = ("appoint", "nomina", "resign", "approval", "fda", "regulat", "announce", "award", "policy", "coach",
      "injur", "lineup", "roster", "withdraw", "sports", "esport", "match", " win ")
P1 = ("election", "president", "vote", "ceasefire", "war", "military")


def tier(m):
    text = " ".join(str(m.get(k, "")) for k in ("title", "category", "tags")).lower()
    return 0 if any(k in text for k in P0) else 1 if any(k in text for k in P1) else 2


def select(markets, budget=100, exploration_fraction=0.2, at=None):
    at = at or datetime.now(timezone.utc)
    eligible = [m for m in markets if not m["closed"] and (m["venue"] != "polymarket" or m["condition_id"])]
    def rank(m):
        urgency = 0
        if m.get("end_time"):
            try:
                hours = (datetime.fromisoformat(m["end_time"].replace("Z", "+00:00")) - at).total_seconds() / 3600
                urgency = 1 / (1 + max(hours, 0))
            except ValueError:
                pass
        # Volume is a small availability proxy; it cannot remove quiet markets.
        return (2 - tier(m)) * 10 + urgency + min(math.log1p(float(m["volume"])) / 100, 1)
    exploration = min(max(1, round(budget * exploration_fraction)), budget)
    deep = sorted(eligible, key=lambda m: (-rank(m), m["id"]))[:budget - exploration]
    selected = {m["id"] for m in deep}
    # Hourly rotation is stable across restarts and independent of volume.
    epoch = at.strftime("%Y-%m-%dT%H")
    remainder = sorted((m for m in eligible if m["id"] not in selected), key=lambda m: digest([epoch, m["id"]]))
    return deep + remainder[:budget - len(deep)]
