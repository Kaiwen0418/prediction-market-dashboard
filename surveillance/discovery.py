"""Bounded-memory selection over an unfiltered catalog, with rotating exploration."""
from bisect import insort
from datetime import datetime, timezone
import math

from .normalization import digest


P0 = ("appoint", "nomina", "resign", "approval", "fda", "regulat", "announce", "award", "policy", "coach",
      "injur", "lineup", "roster", "withdraw", "sports", "esport", "match", " win ")
P1 = ("election", "president", "vote", "ceasefire", "war", "military")


def tier(m):
    text = " ".join(str(m.get(k, "")) for k in ("title", "category", "tags")).lower()
    return 0 if any(k in text for k in P0) else 1 if any(k in text for k in P1) else 2


class Selector:
    """Keep at most 2*budget documents while scanning any catalog size."""
    def __init__(self, budget=100, exploration_fraction=0.2, at=None, end_grace_hours=6):
        self.at = at or datetime.now(timezone.utc)
        self.end_grace_hours = end_grace_hours
        self.budget = budget
        self.exploration = min(max(1, round(budget * exploration_fraction)), budget)
        self.deep, self.explore = [], []
        self.epoch = self.at.strftime("%Y-%m-%dT%H")

    def rank(self, m):
        urgency = 0
        if m.get("end_time"):
            try:
                hours = (datetime.fromisoformat(m["end_time"].replace("Z", "+00:00")) - self.at).total_seconds() / 3600
                urgency = 1 / (1 + hours) if hours >= 0 else 0
            except ValueError:
                pass
        return (2 - tier(m)) * 10 + urgency + min(math.log1p(float(m["volume"])) / 100, 1)

    @staticmethod
    def keep(pool, key, m, size):
        if size and (len(pool) < size or key < pool[-1][0]):
            insort(pool, (key, m))
            if len(pool) > size:
                pool.pop()

    def add(self, m):
        if m["closed"] or m.get("settled") or m.get("is_combo") or not m.get("tradable", True) or (m["venue"] == "polymarket" and not m["condition_id"]):
            return
        if m.get("end_time"):
            try:
                end = datetime.fromisoformat(m["end_time"].replace("Z", "+00:00"))
                if end.tzinfo is None or (self.at - end).total_seconds() > self.end_grace_hours * 3600:
                    return  # Not a settlement assertion: stale schedule metadata is ineligible for deep sampling.
            except ValueError:
                return
        self.keep(self.deep, (-self.rank(m), m["id"]), m, self.budget - self.exploration)
        # Keep budget random candidates so removing all deep picks still leaves enough.
        self.keep(self.explore, (digest([self.epoch, m["id"]]), m["id"]), m, self.budget)

    def result(self):
        deep = [m for _, m in self.deep]
        selected = {m["id"] for m in deep}
        return deep + [m for _, m in self.explore if m["id"] not in selected][:self.budget - len(deep)]


def select(markets, budget=100, exploration_fraction=0.2, at=None):
    selector = Selector(budget, exploration_fraction, at)
    for m in markets:
        selector.add(m)
    return selector.result()
