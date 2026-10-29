"""Budgeted Polymarket self-history enrichment; never changes the alert score."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
from statistics import median

from psycopg.types.json import Jsonb

from .collectors import ContractError
from .normalization import digest, now, trade


def self_baseline(rows, start, cutoff, complete):
    baseline = [r for r in rows if r['event_time']<start]
    current = [r for r in rows if start<=r['event_time']<=cutoff]
    cash = lambda r: float(Decimal(r['price'])*Decimal(r['quantity']))
    samples = sorted(cash(r) for r in baseline)
    days = len({r['event_time'][:10] for r in baseline})
    sufficient = complete and len(samples)>=20 and days>=2 and bool(current)
    p95 = samples[max(0,(95*len(samples)+99)//100-1)] if samples else None
    current_median = median(cash(r) for r in current) if current else None
    by_market = {}
    for r in rows:
        by_market[r['market_id']] = by_market.get(r['market_id'],0)+cash(r)
    total = sum(by_market.values())
    return dict(baseline_fills=len(baseline),baseline_observed_days=days,current_fills=len(current),
        baseline_median_cash=median(samples) if samples else None,baseline_p95_cash=p95,
        current_median_cash=current_median,baseline_sufficient=sufficient,
        current_to_own_p95=current_median/p95 if sufficient and p95 else None,
        observed_largest_contract_cash_share=max(by_market.values())/total if total else None,
        earliest_indexed_trade=min((r['event_time'] for r in rows),default=None),
        history_complete_within_request=complete,
        meaning='Observed gross fills, not net positions, account age, profit or an insider classification')


async def admit_profile(store, case):
    if case['venue']!='polymarket' or not case.get('wallet_observations'):
        return None
    # Rank by cash rather than shares in low-price outcomes.
    wallet = max(case['wallet_observations'],key=lambda w:w.get('cash_usd',0))['wallet'].lower()
    if not re.fullmatch(r'0x[0-9a-f]{40}',wallet):
        return None
    cutoff = case['signal']['as_of']
    start = (datetime.fromisoformat(cutoff)-timedelta(seconds=case['signal']['window_seconds'])).isoformat()
    payload = dict(case_id=case['id'],wallet=wallet,cutoff=cutoff,start=start,
        since=(datetime.fromisoformat(start)-timedelta(days=7)).isoformat())
    key = digest([case['id'],wallet,'wallet-v1'])
    async with store.connection() as c:
        await c.execute('SELECT pg_advisory_xact_lock(81724006)')
        n = (await (await c.execute("SELECT count(*) AS n FROM surveillance_wallet_profiles WHERE admitted_at>now()-interval '1 hour'")).fetchone())['n']
        if n>=4:
            return None
        inserted = await (await c.execute('''INSERT INTO surveillance_wallet_profiles(id,case_id,wallet,document)
            VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id''',
            (key,case['id'],wallet,Jsonb(dict(status='queued',**payload))))).fetchone()
        if inserted:
            await c.execute("INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'wallet','polymarket',%s)", ('wallet:'+key,Jsonb(dict(payload,profile_id=key))))
    return key if inserted else None


async def collect_profile(worker, job):
    store, cp, payload = worker.store, dict(job['checkpoint']),job['payload']
    target = await store.fetch('SELECT document FROM surveillance_cases WHERE id=%s', (payload['case_id'],))
    if not target:
        async with store.connection() as c:
            await store.fence(c,job)
            await c.execute('DELETE FROM surveillance_wallet_profiles WHERE id=%s', (payload['profile_id'],))
            await c.execute('UPDATE surveillance_jobs SET enabled=false WHERE id=%s', (job['id'],))
        return 3600
    raw, rows, cursor = await worker.collector.page(job)
    cursor_hash = digest(cursor) if cursor else None
    if cursor_hash and cursor_hash in cp.get('seen_cursors',[]):
        raise ContractError('Wallet cursor cycle')
    normalized = []
    previous = cp.get('last_time')
    for row in rows:
        t = trade('polymarket',row,raw['received_at'])
        if not t['wallet'] or t['wallet'].lower()!=payload['wallet']:
            raise ContractError('Wallet response attribution mismatch')
        if not payload['since']<=t['event_time']<=payload['cutoff']:
            raise ContractError('Wallet response outside requested time range')
        if previous and t['event_time']>previous:
            raise ContractError('Wallet feed not newest-first')
        previous=t['event_time']
        normalized.append({k:t[k] for k in ('price','quantity','event_time','market_id','direction')})
    samples = cp.get('samples',[])+normalized
    if len(samples)>1000:
        raise ContractError('Wallet response exceeds 1000-fill budget')
    pages = cp.get('pages',0)+1
    raw_ids = cp.get('raw_ids',[])+[raw['id']]
    cp.update(pages=pages,cursor=cursor,samples=samples,raw_ids=raw_ids,last_time=previous,
              seen_cursors=cp.get('seen_cursors',[])+([cursor_hash] if cursor_hash else []))
    if cursor and pages<2:
        await store.checkpoint(job,cp)
        return 1
    summary = self_baseline(samples,payload['start'],payload['cutoff'],not cursor)
    document = dict(id=payload['profile_id'],wallet=payload['wallet'],case_id=payload['case_id'],
        status='complete' if not cursor else 'truncated',known_at=now(),trade_cutoff=payload['cutoff'],
        requested_since=payload['since'],pages=pages,summary=summary,raw_ids=raw_ids,
        limitations=['Post-alert enrichment; unavailable at original alert',
            'Seven-day public indexed history; at most two pages / 1000 fills',
            'Same wallet does not establish a real-world identity or linked-account relationship'])
    # Atomic profile, case enrichment and job completion; restart cannot lose the attachment.
    async with store.connection() as c:
        await store.fence(c,job)
        case = await (await c.execute('SELECT * FROM surveillance_cases WHERE id=%s FOR UPDATE', (payload['case_id'],))).fetchone()
        if case:
            dossier=dict(case['document'])
            profiles=[p for p in dossier.get('wallet_profiles',[]) if p['id']!=document['id']]+[document]
            dossier.update(wallet_profiles=profiles,replay_raw_ids=sorted(set(dossier.get('replay_raw_ids',[])+raw_ids)))
            await c.execute('UPDATE surveillance_cases SET document=%s WHERE id=%s', (Jsonb(dossier),payload['case_id']))
            await c.execute('''INSERT INTO surveillance_case_versions(case_id,version,document)
                SELECT %s,COALESCE(max(version),0)+1,%s FROM surveillance_case_versions WHERE case_id=%s''',
                (payload['case_id'],Jsonb(dossier),payload['case_id']))
        await c.execute('UPDATE surveillance_wallet_profiles SET known_at=%s,document=%s,raw_ids=%s WHERE id=%s',
                        (document['known_at'],Jsonb(document),raw_ids,document['id']))
        await c.execute('UPDATE surveillance_jobs SET checkpoint=%s,enabled=false WHERE id=%s',
                        (Jsonb(dict(completed_at=now(),pages=pages,truncated=bool(cursor))),job['id']))
    return 3600
