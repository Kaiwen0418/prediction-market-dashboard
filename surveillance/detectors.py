"""Coverage-aware cash-flow signals. Alert knowledge time is never backdated."""
from datetime import datetime,timedelta
from statistics import median

from .money import cash
from .observation import merge,covered

VERSION='surveillance-v2.0'
WINDOWS=(60,300,3600)
BASELINE_WINDOWS=12


def evaluate(trades,as_of,*,knowledge_cutoff=None,coverage=()):
    cutoff=datetime.fromisoformat(as_of)
    known=datetime.fromisoformat(knowledge_cutoff or as_of)
    if cutoff.tzinfo is None or known.tzinfo is None or cutoff>known:raise ValueError('Aware event cutoff <= knowledge cutoff required')
    observations=merge(coverage)
    eligible=sorted((t for t in trades if datetime.fromisoformat(t['event_time'])<=cutoff
        and datetime.fromisoformat(t['received_at'])<=known),key=lambda t:(t['event_time'],t['id']))
    stamps={t['id']:datetime.fromisoformat(t['event_time']) for t in eligible}
    premiums={t['id']:cash(t) for t in eligible}
    results=[]
    for seconds in WINDOWS:
        start=cutoff-timedelta(seconds=seconds)
        current=[];historical=[[] for _ in range(BASELINE_WINDOWS)]
        for t in eligible:
            age=(cutoff-stamps[t['id']]).total_seconds()
            if age<seconds:current.append(t)
            else:
                index=int(age//seconds)-1
                if index<BASELINE_WINDOWS:historical[index].append(t)
        if not current:continue
        buckets=[];observed=[]
        for i in range(BASELINE_WINDOWS):
            hi=start-timedelta(seconds=i*seconds);lo=hi-timedelta(seconds=seconds)
            complete=covered(observations,lo,hi)
            rows=historical[i]
            amounts=[premiums[t['id']] for t in rows]
            usable=complete and all(v is not None for v in amounts)
            buckets.append(float(sum(amounts)) if usable else None)
            observed.append(usable)
        amounts=[premiums[t['id']] for t in current]
        money_known=all(v is not None for v in amounts)
        value=float(sum(v for v in amounts if v is not None))
        baseline_values=[v for v in buckets if v is not None]
        baseline=median(baseline_values) if baseline_values else None
        mad=median(abs(v-baseline) for v in baseline_values) if baseline_values else None
        sufficient=len(baseline_values)>=6
        z=(value-baseline)/max(1,1.4826*mad) if sufficient and money_known else None
        signed=[t for t in current if t['direction'] is not None and not t.get('is_block_trade') and cash(t) is not None]
        signed_cash=sum(float(cash(t)) for t in signed)
        imbalance=sum(t['direction']*float(cash(t)) for t in signed)/signed_cash if signed_cash else None
        prices={}
        for t in current:prices.setdefault(t['event_time'],[]).append(float(t['price']))
        times=sorted(prices)
        impact=median(prices[times[-1]])-median(prices[times[0]]) if len(times)>=2 else None
        # Direction and price must agree, and the second half must sustain the move.
        midpoint=start+timedelta(seconds=seconds/2)
        late=[float(t['price']) for t in current if datetime.fromisoformat(t['event_time'])>midpoint]
        agrees=bool(impact and imbalance and impact*imbalance>0)
        sustained=bool(agrees and late and (median(late)-median(prices[times[0]]))*impact>0
                       and abs(median(late)-median(prices[times[0]]))+1e-12>=abs(impact)*.5)
        spike=min(1,max(0,z)/10) if z is not None else 0
        direction=abs(imbalance) if imbalance is not None and len(signed)>=5 else 0
        price=min(1,abs(impact)/.1) if impact is not None and len(current)>=5 and sustained else 0
        score=round(100*(.5*spike+.3*direction+.2*price),2)
        current_covered=covered(observations,start,cutoff)
        wallets={}
        for t in current:
            if t.get('wallet') and t['direction']==1 and cash(t) is not None:
                wallets[t['wallet']]=wallets.get(t['wallet'],0)+float(cash(t))
        attributed=sum(wallets.values())
        results.append(dict(window_seconds=seconds,window_start=start.isoformat(),as_of=cutoff.isoformat(),
            knowledge_cutoff=known.isoformat(),detected_with_delay_seconds=max(0,(known-cutoff).total_seconds()),
            volume_shares=sum(float(t['quantity']) for t in current),cash_notional_usd=value,
            cash_complete=money_known,current_fully_observed=current_covered,
            buy_cash_usd=sum(float(cash(t)) for t in signed if t['direction']==1),
            sell_cash_usd=sum(float(cash(t)) for t in signed if t['direction']==-1),
            largest_public_wallet_buy_share=max(wallets.values())/attributed if attributed else None,
            attributed_buy_cash_usd=attributed,wallet_scope='Observed taker wallets only; no clustering',
            baseline_cash_buckets=buckets,baseline_observed_windows=sum(observed),
            baseline_median_cash=baseline,robust_z=z,baseline_sufficient=sufficient,
            signed_imbalance=imbalance,price_change=impact,price_direction_agrees=agrees,price_move_sustained=sustained,
            flow_direction='buy' if imbalance is not None and imbalance>=.6 else 'sell' if imbalance is not None and imbalance<=-.6 else 'mixed_or_unknown',
            trade_count=len(current),anomaly_score=score,trade_ids=[t['id'] for t in current],detector_version=VERSION,
            limitations=['Sampled API coverage is not exchange completeness','No calibrated insider probability',
                'Unknown observation intervals are excluded, never replaced with zero',
                'Price persistence is a trade-price proxy, not historical executable depth']+
                ([] if sufficient else ['Insufficient observed historical baseline windows'])+
                ([] if current_covered else ['Current window not fully sampled'])))
    return results


def automatic_candidate(signal,minimum_cash=1000,minimum_trades=5,large_single_cash=10000):
    # Legacy dossiers remain readable, but new production admission requires coverage.
    return bool(signal.get('current_fully_observed') and signal.get('cash_complete') and
        signal['cash_notional_usd']>=minimum_cash and
        (signal['trade_count']>=minimum_trades or signal['cash_notional_usd']>=large_single_cash))
