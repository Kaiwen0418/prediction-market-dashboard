"""Retrospective price leadership. These measurements are not online alerts or PnL."""
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

from .money import cash
from .normalization import digest

VERSION = 'leadlag-v1'
BIN = 300


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def analyze(trades, start, end, max_episodes=40, observation_end=None):
    """Bounded input; separate outcomes, never forward-fill prices across gaps.

    A confirmed shift needs two consecutive populated bins. We report an onset
    interval, not an invented exact public-information timestamp. All future
    observations are intentionally retrospective and bounded by the supplied end.
    """
    lower, upper = epoch(start), epoch(end)
    groups = defaultdict(list)
    for t in trades:
        ts = epoch(t['event_time'])
        if ts < epoch(observation_end or end):
            groups[t.get('token_id') or t['outcome']].append((ts, t))
    episodes, summaries = [], []
    evaluated = 0
    for outcome, rows in sorted(groups.items()):
        rows.sort(key=lambda x: (x[0], x[1]['id']))
        buckets = defaultdict(list)
        for ts, t in rows:
            buckets[int(ts // BIN) * BIN].append(t)
        bars = []
        for at, fills in sorted(buckets.items()):
            prices = [float(t['price']) for t in fills]
            bars.append(dict(at=at, price=median(prices), fills=len(fills)))
        summaries.append(dict(outcome=outcome, bins=bars))
        occupied_until = float('-inf')
        for i in range(6, len(bars)-1):
            b, after = bars[i], bars[i+1]
            if b['at'] >= upper or b['at'] <= occupied_until:
                continue
            if after['at'] != b['at']+BIN or min(b['fills'], after['fills']) < 3:
                continue
            # Multiple past horizons catch abrupt and gradual changes. A horizon
            # crossing a gap is rejected, even if endpoints look far apart.
            choices = []
            for width in (1, 6, 24):
                base_index = i-width
                if base_index < 5:
                    continue
                segment = bars[base_index-5:i+2]
                if any(y['at']-x['at'] != BIN for x, y in zip(segment, segment[1:])):
                    continue
                baseline = bars[base_index-5:base_index+1]
                if any(x['fills'] < 3 for x in baseline):
                    continue
                reference = median(x['price'] for x in baseline)
                noise = median(abs(x['price']-reference) for x in baseline)
                move = b['price']-reference
                threshold = max(.10, 6*noise)
                if abs(move) < threshold or (after['price']-reference)*move <= 0:
                    continue
                if abs(after['price']-reference) < abs(move)*.7:
                    continue
                direction = 1 if move > 0 else -1
                # Earliest observable departure, rather than the threshold-crossing time.
                departure = next((j for j in range(base_index+1, i+1)
                    if direction*(bars[j]['price']-reference) >= max(.02, 3*noise)), i)
                lo, hi = bars[departure-1]['at'], bars[departure]['at']+BIN
                if lo <= occupied_until:
                    continue
                choices.append((abs(move), lo, hi, direction, reference))
            if not choices:
                continue
            _, onset_lo, onset_hi, direction, reference = max(choices)
            occupied_until = after['at']+BIN
            if b['at'] < lower:
                continue
            evaluated += 1
            if len(episodes) >= max_episodes:
                continue
            begin = onset_lo-3600
            before = [(ts,t) for ts,t in rows if begin <= ts < onset_lo]
            during = [(ts,t) for ts,t in rows if onset_lo <= ts < occupied_until]
            wallets = defaultdict(list)
            for ts,t in before:
                if t.get('wallet') and t.get('direction') in (-1,1) and not t.get('is_block_trade'):
                    wallets[t['wallet']].append((ts,t))
            bar_times = [x['at'] for x in bars]
            candidates = []
            for wallet, fills in wallets.items():
                aligned = [(ts,t) for ts,t in fills if t['direction'] == direction]
                if not aligned:
                    continue
                buy = sum(float(cash(t) or 0) for _,t in fills if t['direction']==1)
                sell = sum(float(cash(t) or 0) for _,t in fills if t['direction']==-1)
                ahead = sum(float(cash(t) or 0) for _,t in aligned)
                following = sum(float(cash(t) or 0) for _,t in during
                    if t.get('wallet')==wallet and t.get('direction')==direction)
                whole = sum(float(cash(t) or 0) for _,t in during)
                own = sum(float(cash(t) or 0) for _,t in during if t.get('wallet')==wallet)
                markouts = {}
                for horizon in (300, 3600):
                    values = []
                    for ts,t in fills:
                        j = bisect_left(bar_times, ts+horizon)
                        # Future bin must be close to the requested horizon; never
                        # substitute settlement payout or a far-away stale print.
                        if j < len(bars) and bars[j]['at']-(ts+horizon) <= BIN:
                            values.append(t['direction']*(bars[j]['price']-float(t['price'])))
                    markouts[str(horizon)] = dict(mean_price_change=sum(values)/len(values) if values else None,
                                                  observed=len(values), eligible=len(fills))
                candidates.append(dict(wallet=wallet, action='buy_before_rise' if direction==1 else 'sell_before_fall',
                    first_trade_at=iso(aligned[0][0]), lead_seconds_min=onset_lo-aligned[0][0],
                    lead_seconds_max=onset_hi-aligned[0][0], buy_cash=buy, sell_cash=sell,
                    aligned_pre_move_cash=ahead, pre_move_cash_fraction=ahead/(ahead+following) if ahead+following else None,
                    move_cash_share=own/whole if whole else None,
                    own_impact_unresolved=not whole or own/whole >= .25,
                    markouts=markouts, trade_ids=[t['id'] for _,t in fills[:5]],
                    trade_refs_truncated=len(fills)>5, observed_fills=len(fills)))
            candidates.sort(key=lambda x:(-x['aligned_pre_move_cash'],x['wallet']))
            episodes.append(dict(id=digest([VERSION,outcome,onset_lo,onset_hi]),outcome=outcome,
                onset_interval=[iso(onset_lo),iso(onset_hi)], confirmed_at=iso(occupied_until),
                price_before=reference, price_after=after['price'], price_change=after['price']-reference,
                market_pre_move_fills=len(before), market_move_fills=len(during),
                eligible_wallets=len(wallets), candidate_wallets=len(candidates), wallets=candidates[:20],
                wallets_omitted=max(0,len(candidates)-20),
                explanation_checks=['public_information_unknown','cross_market_arbitrage_unchecked',
                    'self_impact_not_causally_identified','historical_executable_depth_unavailable']))
    return dict(version=VERSION, analysis_mode='retrospective', input_fills=len(trades),
        input_digest=digest([[t.get(k) for k in ('id','event_time','received_at','outcome','token_id','price','quantity','direction','wallet','cash_price','cash_notional','is_block_trade')] for t in sorted(trades,key=lambda t:t['id'])]), summary_bins=summaries,
        episodes=episodes, episodes_detected=evaluated, episodes_omitted=max(0,evaluated-len(episodes)),
        anomaly_score=None,evidence_quality=None,investigation_priority=None,
        limitations=['Future prices used; not an as-of alert or insider probability',
            'Trade-price medians, not executable quotes; markouts are not profit',
            'Five-minute onset interval; missing bins break detection',
            'Wallets cover observed attributable takers only; no identity or complete inventory',
            'One-hour pre-move cohort; not lifetime wallet performance'])
