"""Versioned event-time windows using only observations received by the cutoff."""
from datetime import datetime, timedelta
from statistics import median

VERSION = "surveillance-v1.1"
WINDOWS = (60, 300, 3600)
BASELINE_WINDOWS = 12


def evaluate(trades, as_of):
    cutoff = datetime.fromisoformat(as_of)
    eligible = sorted(((t, datetime.fromisoformat(t["event_time"]), float(t["quantity"])) for t in trades
                       if datetime.fromisoformat(t["event_time"]) <= cutoff
                       and datetime.fromisoformat(t["received_at"]) <= cutoff), key=lambda e: (e[1], e[0]["id"]))
    results = []
    for seconds in WINDOWS:
        start = cutoff - timedelta(seconds=seconds)
        current_entries = []
        buckets = [0.0] * BASELINE_WINDOWS
        for t, event_time, quantity in eligible:
            age = (cutoff - event_time).total_seconds()
            if age < seconds:
                current_entries.append((t, quantity))
            else:
                index = int(age // seconds) - 1
                if index < BASELINE_WINDOWS:
                    buckets[index] += quantity
        current = [t for t, _ in current_entries]
        if not current:
            continue
        volume = sum(q for _, q in current_entries)
        cash = sum(q * float(t["price"]) for t, q in current_entries)
        buy_cash = sum(q * float(t["price"]) for t, q in current_entries if t["direction"] == 1)
        sell_cash = sum(q * float(t["price"]) for t, q in current_entries if t["direction"] == -1)
        wallet_buys = {}
        for t, q in current_entries:
            if t.get("wallet") and t["direction"] == 1:
                wallet_buys[t["wallet"]] = wallet_buys.get(t["wallet"], 0) + q * float(t["price"])
        attributed = sum(wallet_buys.values())
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
                            volume_shares=volume, cash_notional_usd=cash, buy_cash_usd=buy_cash, sell_cash_usd=sell_cash,
                            largest_public_wallet_buy_share=max(wallet_buys.values()) / attributed if attributed else None,
                            attributed_buy_cash_usd=attributed, wallet_scope="Observed taker wallets only; no clustering or maker attribution",
                            flow_direction="buy" if imbalance is not None and imbalance >= .6 else "sell" if imbalance is not None and imbalance <= -.6 else "mixed_or_unknown",
                            baseline_median_shares=baseline, robust_z=robust_z,
                            baseline_sufficient=sufficient, signed_imbalance=imbalance, price_change=impact,
                            trade_count=len(current), anomaly_score=score,
                            trade_ids=[t["id"] for t in current], detector_version=VERSION,
                            limitations=["REST sampling; no historical executable depth", "No peer-market calibration yet",
                                         "Price change is not a demonstrated sweep or sustained impact"] +
                                         ([] if sufficient else ["Insufficient nonempty historical baseline windows"])))
    return results


def automatic_candidate(signal, minimum_cash=1000, minimum_trades=5, large_single_cash=10000):
    """Cost floor for automatic dossiers, independent of score or eventual result.

    Keep sell/NO signals too. A large individual fill need not have five fills.
    This policy is not an insider classifier or an empirically calibrated model.
    """
    cash = signal["cash_notional_usd"]
    return cash >= minimum_cash and (signal["trade_count"] >= minimum_trades or cash >= large_single_cash)
