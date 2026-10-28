"""Versioned event-time windows using only observations received by the cutoff."""
from datetime import datetime, timedelta
from statistics import median

VERSION = "surveillance-v1.0"
WINDOWS = (60, 300, 3600)
BASELINE_WINDOWS = 12


def evaluate(trades, as_of):
    cutoff = datetime.fromisoformat(as_of)
    eligible = sorted((t for t in trades if datetime.fromisoformat(t["event_time"]) <= cutoff
                       and datetime.fromisoformat(t["received_at"]) <= cutoff),
                      key=lambda t: (t["event_time"], t["id"]))
    results = []
    for seconds in WINDOWS:
        start = cutoff - timedelta(seconds=seconds)
        current = [t for t in eligible if datetime.fromisoformat(t["event_time"]) > start]
        if not current:
            continue
        buckets = []
        for offset in range(1, BASELINE_WINDOWS + 1):
            hi = start - timedelta(seconds=seconds * (offset - 1))
            lo = hi - timedelta(seconds=seconds)
            buckets.append(sum(float(t["quantity"]) for t in eligible if lo < datetime.fromisoformat(t["event_time"]) <= hi))
        volume = sum(float(t["quantity"]) for t in current)
        baseline = median(buckets)
        mad = median(abs(x - baseline) for x in buckets)
        robust_z = (volume - baseline) / max(1, 1.4826 * mad)
        signed = [t for t in current if t["direction"] is not None and not t.get("is_block_trade")]
        signed_volume = sum(float(t["quantity"]) for t in signed)
        imbalance = sum(t["direction"] * float(t["quantity"]) for t in signed) / signed_volume if signed_volume else None
        # Public feeds may lack within-second ordering: compare timestamp cohorts,
        # never sort opaque trade IDs to invent an execution sequence.
        prices_by_time = {}
        for t in current:
            prices_by_time.setdefault(t["event_time"], []).append(float(t["price"]))
        times = sorted(prices_by_time)
        impact = median(prices_by_time[times[-1]]) - median(prices_by_time[times[0]]) if len(times) >= 2 else None
        sufficient = sum(x > 0 for x in buckets) >= 6
        spike = min(1, max(0, robust_z) / 10) if sufficient else 0
        direction_signal = abs(imbalance) if imbalance is not None and len(signed) >= 5 else 0
        price_signal = min(1, abs(impact) / 0.1) if impact is not None and len(current) >= 5 else 0
        score = round(100 * (0.5 * spike + 0.3 * direction_signal + 0.2 * price_signal), 2)
        results.append(dict(window_seconds=seconds, window_start=start.isoformat(), as_of=as_of,
                            volume_shares=volume, baseline_median_shares=baseline, robust_z=robust_z,
                            baseline_sufficient=sufficient, signed_imbalance=imbalance, price_change=impact,
                            trade_count=len(current), anomaly_score=score,
                            trade_ids=[t["id"] for t in current], detector_version=VERSION,
                            limitations=["REST sampling; no historical executable depth", "No peer-market calibration yet",
                                         "Price change is not a demonstrated sweep or sustained impact"] +
                                         ([] if sufficient else ["Insufficient nonempty historical baseline windows"])))
    return results
