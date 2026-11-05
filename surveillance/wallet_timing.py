"""All-trade retrospective markouts with same-bin, same-direction peer controls."""
from bisect import bisect_left
from collections import defaultdict
from statistics import median

from psycopg.types.json import Jsonb

from .leadlag import BIN, epoch


def measure(trades, start, end, horizon=3600):
    groups = defaultdict(list)
    for trade in trades:
        groups[trade.get('token_id') or trade['outcome']].append(trade)
    totals = defaultdict(lambda: dict(eligible=0, observed=0, positive=0, negative=0,
                                      price_change_sum=0., excess_sum=0., controlled=0))
    for rows in groups.values():
        buckets = defaultdict(list)
        for trade in rows:
            buckets[int(epoch(trade['event_time']) // BIN) * BIN].append(float(trade['price']))
        times = sorted(buckets)
        prices = [median(buckets[t]) for t in times]
        observations = []
        peers = defaultdict(lambda: defaultdict(list))
        for trade in rows:
            wallet = (trade.get('wallet') or '').lower()
            direction = trade.get('direction')
            when = epoch(trade['event_time'])
            if not wallet or direction not in (-1, 1) or trade.get('is_block_trade') or not epoch(start) <= when < epoch(end):
                continue
            totals[wallet]['eligible'] += 1
            index = bisect_left(times, when + horizon)
            if index == len(times) or times[index] > when + horizon + BIN:
                continue
            value = direction * (prices[index] - float(trade['price']))
            key = (int(when // BIN), direction)
            peers[key][wallet].append(value)
            observations.append((wallet, key, value))
        peer_totals = {key: (sum(sum(values) for values in owners.values()),
                             sum(len(values) for values in owners.values()))
                       for key, owners in peers.items()}
        own_totals = {(key, wallet): (sum(values), len(values))
                      for key, owners in peers.items() for wallet, values in owners.items()}
        for wallet, key, value in observations:
            row = totals[wallet]
            row['observed'] += 1
            row['positive'] += int(value > 0)
            row['negative'] += int(value < 0)
            row['price_change_sum'] += value
            total, count = peer_totals[key]
            own_sum, own_count = own_totals[key, wallet]
            other_count = count-own_count
            if other_count:
                row['controlled'] += 1
                row['excess_sum'] += value-(total-own_sum)/other_count
    return [dict(wallet=wallet, **values) for wallet, values in sorted(totals.items())]


async def persist(c, slice_id, trades, start, end):
    by_wallet = {}
    for horizon in (300, 900, 3600):
        for row in measure(trades, start, end, horizon):
            wallet = row['wallet']
            by_wallet.setdefault(wallet, {})[str(horizon)] = row
    metrics = [dict(values['3600'], version=2, horizons=values) for values in by_wallet.values()]
    if metrics:
        async with c.cursor() as cursor:
            await cursor.executemany('''INSERT INTO surveillance_wallet_timing(slice_id,wallet,document)
                VALUES(%s,%s,%s) ON CONFLICT(slice_id,wallet) DO UPDATE SET document=EXCLUDED.document
                WHERE surveillance_wallet_timing.document IS DISTINCT FROM EXCLUDED.document''',
                [(slice_id, row['wallet'], Jsonb(row)) for row in metrics])


async def patterns(store, wallet, horizon=3600):
    rows = await store.fetch('''SELECT w.document,r.document->'market'->'event_ids' AS events,
        r.id AS review_id,s.id AS slice_id FROM surveillance_wallet_timing w
        JOIN surveillance_review_slices s ON s.id=w.slice_id
        JOIN surveillance_retrospectives r ON r.id=s.review_id
        WHERE w.wallet=%s AND r.status IN ('complete_observed','complete_with_gaps')
        AND r.document->'continuity'->>'status'='verified_api_interval'
        ORDER BY r.known_at,r.id,s.lower_time LIMIT 5001''', (wallet,))
    if len(rows) > 5000:
        raise ValueError('Wallet query exceeds 5000 slices')
    events = defaultdict(list)
    unmapped = 0
    for row in rows:
        ids = row['events'] or []
        if len(set(ids)) != 1:
            unmapped += 1
            continue
        events[ids[0]].append(row)
    results = []
    for event, members in events.items():
        documents = [m['document'].get('horizons', {}).get(str(horizon),
                     m['document'] if horizon == 3600 else None) for m in members]
        documents = [d for d in documents if d is not None]
        observed = sum(d['observed'] for d in documents)
        controlled = sum(d['controlled'] for d in documents)
        unavailable = len(members)-len(documents)
        results.append(dict(unavailable_horizon_slices=unavailable,event_id=event, reviews=len({m['review_id'] for m in members}),
            observed=observed, eligible=sum(d['eligible'] for d in documents),
            mean_price_change=sum(d['price_change_sum'] for d in documents)/observed if observed else None,
            controlled=controlled, mean_peer_excess=sum(d['excess_sum'] for d in documents)/controlled if controlled else None))
    positive = sum(r['mean_peer_excess'] is not None and r['mean_peer_excess'] > 0 for r in results)
    negative = sum(r['mean_peer_excess'] is not None and r['mean_peer_excess'] < 0 for r in results)
    return dict(wallet=wallet, horizon_seconds=horizon, events=results, independent_native_events=len(results),
        positive_peer_events=positive, negative_peer_events=negative, unmapped_slices=unmapped,
        sample_status='insufficient' if positive+negative < 5 else 'descriptive_sample',
        scope='All observed attributable trades in retained completed review slices, including adverse markouts',
        limitations=['Native event IDs can still describe correlated real-world events',
            'Peers share a five-minute entry bucket and direction; risk and execution differences remain',
            'Trade-weighted markouts are price changes; archive and review coverage bound the sample',
            'Repeated performance requires forward validation and multiple-testing calibration'])


async def backfill(worker, job):
    from .research_archive import read_tape
    rows = await worker.store.fetch('''SELECT s.*,r.venue,r.market_id FROM surveillance_review_slices s
        JOIN surveillance_retrospectives r ON r.id=s.review_id WHERE s.id>%s
        AND r.venue='polymarket' ORDER BY s.id LIMIT 1''', (job['checkpoint'].get('after',''),))
    if not rows:
        async with worker.store.connection() as c:
            await worker.store.fence(c,job)
            await c.execute('UPDATE surveillance_jobs SET enabled=false WHERE id=%s',(job['id'],))
        return 3600
    row = rows[0]
    document = row['document']
    try:
        trades, _ = await read_tape(worker.store,row['venue'],row['market_id'],document['context_start'],
            document.get('data_end',document['end']),worker.settings.replay_max_trades,
            known_at=document.get('archive_cutoff'))
        from .leadlag import analyze
        current = analyze(trades,document['start'],document['end'],observation_end=document.get('data_end'))
        valid = current['input_digest']==document.get('input_digest')
    except ValueError:
        trades=[]
        valid=False
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        if valid:
            await persist(c,row['id'],trades,document['start'],document['end'])
        from .normalization import now
        await c.execute('UPDATE surveillance_jobs SET checkpoint=%s WHERE id=%s',
            (Jsonb(dict(after=row['id'],last_input_verified=valid,updated_at=now())),job['id']))
    return 15
