"""Settlement-triggered, category-independent, resumable retrospective queue."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from .collectors import ContractError, unpack
from .normalization import market, trade, digest, now, timestamp
from .research_archive import read_tape, coverage
from .leadlag import analyze, VERSION
from .review_policy import evaluate, exclude

BASE = 'https://external-api.kalshi.com/trade-api/v2'


def final(m):
    return (m['source_status'] in ('resolved','settled','finalized')
            and m.get('resolved_outcome') in m['outcomes'] and not m.get('is_combo') and not m.get('is_provisional'))


async def register(c, m, raw, settings):
    """One review per distinct rules/result revision; no category/volume selection."""
    previous=await (await c.execute('SELECT id,status,document FROM surveillance_retrospectives WHERE venue=%s AND market_id=%s ORDER BY known_at DESC,id DESC LIMIT 1',
        (m['venue'],m['condition_id'] or m['id']))).fetchone()
    policy=evaluate(m)
    if not policy['eligible']:
        if previous:await exclude(c,previous['id'],policy)
        return None
    if not final(m):
        if previous:
            await c.execute("UPDATE surveillance_retrospectives SET status='superseded' WHERE venue=%s AND market_id=%s AND status NOT IN ('superseded','excluded')",(m['venue'],m['condition_id'] or m['id']))
        return None
    signature=digest([m['rules_hash'],m['resolved_outcome'],m['source_status']])
    if previous and previous['status']=='no_observed_trades' and previous['document'].get('signature')==signature:
        if float(m.get('volume') or 0)<=float(previous['document']['market'].get('volume') or 0):
            return previous['id']
    if previous and previous['status'] not in ('superseded','excluded','no_observed_trades') and previous['document'].get('signature')==signature:
        return previous['id']
    try:
        end=min(datetime.fromisoformat(timestamp(m.get('settled_at') or m['end_time'])),datetime.fromisoformat(raw['received_at']))
    except (ValueError,TypeError):
        end=datetime.fromisoformat(raw['received_at'])
    if end < datetime.now(timezone.utc)-timedelta(days=settings.research_retention_days):
        return None
    opened=m.get('opened_at')
    try:opened=timestamp(opened) if opened else None
    except (ValueError,TypeError):opened=None
    start=max(datetime.fromisoformat(timestamp(opened)) if opened else end-timedelta(days=settings.review_lookback_days),
              end-timedelta(days=settings.review_lookback_days))
    if start>=end:
        return None
    key=digest([m['venue'],m['condition_id'] or m['id'],signature,raw['received_at'],VERSION])
    document=dict(review_policy=policy,signature=signature,market=m,raw_id=raw['id'],raw_sha256=raw['sha256'],source=raw['source'],
        requested_start=start.isoformat(),requested_end=end.isoformat(),
        scope='bounded_lookback',earlier_history_excluded=not opened or datetime.fromisoformat(timestamp(opened))<start,
        analysis_mode='retrospective',detector_version=VERSION,
        reason='final settlement observed; all event categories eligible')
    inserted=await (await c.execute('''INSERT INTO surveillance_retrospectives(id,venue,market_id,status,document)
        VALUES(%s,%s,%s,'pending',%s) ON CONFLICT DO NOTHING RETURNING id''',
        (key,m['venue'],m['condition_id'] or m['id'],Jsonb(document)))).fetchone()
    if inserted:
        await c.execute('''UPDATE surveillance_retrospectives SET status='superseded'
            WHERE venue=%s AND market_id=%s AND id<>%s AND status NOT IN ('superseded','excluded') ''',
            (m['venue'],m['condition_id'] or m['id'],key))
    return key


async def discover(worker, job):
    cp=dict(job['checkpoint']); venue=job['venue']; archive=job['payload'].get('archive',False)
    params={'limit':100}
    if venue=='polymarket':
        url='https://gamma-api.polymarket.com/markets/keyset'
        params.update(closed='true',order='id',ascending='false')
        cursor_key='after_cursor'
        # Full closed walk includes early closures whose scheduled end is future.
    else:
        url=BASE+('/historical/markets' if archive else '/markets')
        params['mve_filter']='exclude'
        if not archive:params['status']='settled'
        cursor_key='cursor'
    if cp.get('cursor') and not job['payload'].get('head'):params[cursor_key]=cp['cursor']
    raw,body=await worker.collector.get(venue,url,params)
    rows,cursor=unpack(venue,'catalog',body)
    if job['payload'].get('head'):cursor=None
    seen=cp.get('seen',[]); hashed=digest(cursor) if cursor else None
    if hashed and (cursor==cp.get('cursor') or hashed in seen):raise ContractError('Settlement cursor cycle')
    normalized=[market(venue,row,raw['received_at']) for row in rows]
    retained=[]
    for m in normalized:
        try:recent=datetime.fromisoformat(timestamp(m.get('settled_at') or m['end_time']))>=datetime.now(timezone.utc)-timedelta(days=worker.settings.research_retention_days)
        except (ValueError,TypeError):recent=True
        if recent:
            m['review_policy']=evaluate(m)
            retained.append(m)
    checkpoint=dict(cursor=cursor,pages=cp.get('pages',0)+1,seen=(seen+[hashed])[-1000:] if hashed else [],
        observed=cp.get('observed',0)+len(rows),outside_retention=cp.get('outside_retention',0)+len(rows)-len(retained),
        scope='first 100 only; catch-up cursor runs separately' if job['payload'].get('head') else 'all categories; bounded retention; traversal pending' if cursor else 'completed requested catalog walk',
        completed_at=None if cursor else raw['received_at'])
    # Same catalog table as live discovery; no competing closed-market catalog.
    await worker.store.commit_page(job,raw,checkpoint,markets=retained,detailed=True,retrospective_settings=worker.settings)
    if not cursor:
        await worker.store.checkpoint(job,dict(checkpoint,cursor=None,seen=[],pages=0,observed=0,outside_retention=0,last_walk=checkpoint))
    return 300 if cursor or job['payload'].get('head') else 21600


async def dispatch(worker, job):
    from .research_archive import maintain
    result=await maintain(worker.store,worker.settings)
    measured=worker.capacity.result
    if 'database_bytes' not in measured:
        from .capacity import usage
        measured=await usage(worker.store,worker.settings)
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        from .review_policy import sweep
        result['review_policy']=await sweep(c)
        count=(await (await c.execute("SELECT count(*) AS n FROM surveillance_jobs WHERE enabled AND kind='retrospective'")).fetchone())['n']
        rows=[]
        active=await (await c.execute("SELECT venue,count(*) AS n FROM surveillance_jobs WHERE enabled AND kind='retrospective' GROUP BY venue")).fetchall()
        counts={r['venue']:r['n'] for r in active}
        from .admission import slots
        result['admission']=slots(worker.settings,measured,result['logical_budget_bytes']['tape'],count)
        for _ in range(result['admission']['slots']):
            chosen=None
            for venue in sorted(('polymarket','kalshi'),key=lambda v:(counts.get(v,0),v)):
                chosen=await (await c.execute("SELECT id,venue,market_id FROM surveillance_retrospectives WHERE status='pending' AND venue=%s AND NOT (COALESCE((document->'market'->>'volume_reported')::boolean,false) AND (document->'market'->>'volume')::numeric=0) ORDER BY CASE WHEN (document->'market'->>'volume')::numeric>0 THEN 0 ELSE 1 END,known_at,id LIMIT 1 FOR UPDATE SKIP LOCKED",(venue,))).fetchone()
                if chosen:break
            if not chosen:break
            r=chosen;rows.append(r);counts[r['venue']]=counts.get(r['venue'],0)+1
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload)
                VALUES(%s,'retrospective',%s,%s) ON CONFLICT(id) DO UPDATE SET enabled=true,due_at=now(),checkpoint='{}'""",
                ('retrospective:'+r['id'],r['venue'],Jsonb(dict(review_id=r['id'],market_id=r['market_id']))))
            await c.execute("UPDATE surveillance_retrospectives SET status='collecting',document=document||jsonb_build_object('continuity_required',true) WHERE id=%s",(r['id'],))
    await worker.store.checkpoint(job,dict(result,admitted=len(rows)))
    return 5


async def finish(worker,job,cp,status):
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        await c.execute("UPDATE surveillance_retrospectives SET status=%s,document=document||%s WHERE id=%s AND status NOT IN ('superseded','excluded')",
            (status,Jsonb(dict(completion=cp)),job['payload']['review_id']))
        await c.execute("UPDATE surveillance_jobs SET checkpoint=%s,enabled=false,updated_at=now() WHERE id=%s",(Jsonb(cp),job['id']))
    return 3600


async def handoff(worker,job,cp):
    """Release collection and create durable analysis work in one transaction."""
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        inserted=await (await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload,checkpoint)
            VALUES(%s,'retrospective_analysis',%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
            ('analysis:'+job['payload']['review_id'],job['venue'],Jsonb(job['payload']),Jsonb(cp)))).fetchone()
        if inserted:
            await c.execute("UPDATE surveillance_retrospectives SET status='analysis_pending' WHERE id=%s AND status NOT IN ('excluded','superseded')",(job['payload']['review_id'],))
        await c.execute('UPDATE surveillance_jobs SET enabled=false,checkpoint=%s,updated_at=now() WHERE id=%s',(Jsonb(cp),job['id']))
    return 3600


async def collect_page(worker,job,review,cp):
    venue=job['venue']; doc=review['document']; start=doc['requested_start']; end=doc['requested_end']
    phases=['current','historical'] if venue=='kalshi' else ['current']
    cp.setdefault('continuity_version',1)
    cp.setdefault('pass',1)
    phase=cp.get('phase',0)
    if phase>=len(phases):
        if cp['pass']==1:
            checkpoint=dict(continuity_version=1,stage='collect',pass_number=2,
                first_digest=cp.get('content_digest'),first_fills=cp.get('fills',0),
                next_end=end,phase=0,pages=0,fills=0)
            checkpoint['pass']=checkpoint.pop('pass_number')
            await worker.store.checkpoint(job,checkpoint)
            return 60
        stable=(cp.get('content_digest')==cp.get('first_digest') and cp.get('fills',0)==cp.get('first_fills'))
        if not stable and cp['pass']<4:
            checkpoint=dict(continuity_version=1,stage='collect',phase=0,pages=0,fills=0,
                first_digest=cp.get('content_digest'),first_fills=cp.get('fills',0),next_end=end)
            checkpoint['pass']=cp['pass']+1
            await worker.store.checkpoint(job,checkpoint)
            return 60
        if not stable:
            cp.update(continuity_status='source_changed_between_walks')
            return await finish(worker,job,cp,'continuity_unresolved')
        cp.update(stage='analyze',backfill_status='two_walks_verified',continuity_status='verified_api_interval',next_end=end)
        async with worker.store.connection() as c:
            await worker.store.fence(c,job)
            await c.execute('UPDATE surveillance_retrospectives SET document=document||%s WHERE id=%s',
                (Jsonb(dict(continuity=dict(version=1,status='verified_api_interval',start=start,end=end,
                    fills_per_walk=cp.get('fills',0),verified_at=now(),scope='Two complete matching API traversals; upstream omissions remain unobservable'))),review['id']))
            await c.execute('UPDATE surveillance_jobs SET checkpoint=%s WHERE id=%s',(Jsonb(cp),job['id']))
        if cp.get('fills',0)==0:
            return await finish(worker,job,cp,'no_observed_trades')
        return await handoff(worker,job,cp)
    params={'limit':1000}
    if venue=='polymarket':
        url='https://data-api.polymarket.com/v2/trades'
        params.update(condition=job['payload']['market_id'],taker_only='true')
    else:
        url=BASE+('/markets/trades' if phases[phase]=='current' else '/historical/trades')
        params.update(ticker=job['payload']['market_id'],min_ts=int(datetime.fromisoformat(start).timestamp())-1,
                      max_ts=int(datetime.fromisoformat(end).timestamp())+1)
    if cp.get('cursor'):params['cursor']=cp['cursor']
    raw,body=await worker.collector.get(venue,url,params)
    rows,cursor=unpack(venue,'trades',body)
    hashed=digest(cursor) if cursor else None
    if hashed and (hashed in cp.get('seen',[]) or cursor==cp.get('cursor')):raise ContractError('Review trade cursor cycle')
    counts=Counter(cp.get('counts',{})); previous=cp.get('last_time'); accepted=[]; crossed=False
    for row in rows:
        t=trade(venue,row,raw['received_at']); ts=t['event_time']
        if t['market_id']!=job['payload']['market_id']:raise ContractError('Review trade belongs to another market')
        if previous and ts>previous:raise ContractError('Review feed not newest first')
        if ts<start:crossed=True;break
        if ts!=previous:counts.clear()
        previous=ts;counts[t['identity']]+=1
        t['id']=t['identity']+(f":{counts[t['identity']]}" if venue=='polymarket' else '')
        if ts<end:
            t.update(raw_id=raw['id'],collection_scope='retrospective');accepted.append(t)
    cp['page_phase']=phase
    cp['content_digest']=digest([cp.get('content_digest'),sorted((t['id'],t['price'],t['quantity'],t['direction'],t.get('wallet')) for t in accepted)])
    cp.update(cursor=cursor,counts=dict(counts),last_time=previous,pages=cp.get('pages',0)+1,
        seen=(cp.get('seen',[])+[hashed])[-1000:] if hashed else [],
        fills=cp.get('fills',0)+len(accepted))
    if crossed or not cursor:
        cp.update(phase=phase+1,cursor=None,counts={},last_time=None,seen=[])
    await worker.store.commit_page(job,raw,cp,trades=accepted,retrospective_settings=worker.settings)
    return 1


async def run(worker,job):
    rows=await worker.store.fetch('SELECT * FROM surveillance_retrospectives WHERE id=%s',(job['payload']['review_id'],))
    cp=dict(job['checkpoint'])
    if not rows or rows[0]['status'] in ('superseded','excluded'):return await finish(worker,job,cp,'expired')
    review=rows[0]; doc=review['document']; start=doc['requested_start']; end=doc['requested_end']
    if job['kind']=='retrospective_analysis' and (cp.get('continuity_version')!=1 or cp.get('stage')!='analyze'):
        raise ValueError('Analysis requires verified collection checkpoint')
    if cp.get('continuity_version')!=1:
        cp=dict(continuity_version=1,stage='collect',phase=0,pages=0,fills=0,next_end=end)
        cp['pass']=1
        await worker.store.checkpoint(job,cp)
    if cp['stage']=='collect':return await collect_page(worker,job,review,cp)
    if job['kind']=='retrospective':return await handoff(worker,job,cp)
    hi=datetime.fromisoformat(cp['next_end']); beginning=datetime.fromisoformat(start)
    if hi<=beginning:
        cp['completed_at']=now()
        return await finish(worker,job,cp,'complete_with_gaps' if cp.get('incomplete_slices') else 'complete_observed')
    hours=cp.get('slice_hours',24); lo=max(beginning,hi-timedelta(hours=hours))
    # Four-hour overlap supports a 2h trend, 30m baseline and 1h precursor.
    context=max(beginning,lo-timedelta(hours=4))
    data_end=min(datetime.fromisoformat(end),hi+timedelta(hours=1))
    archive_cutoff=now()
    try:
        trades,refs=await read_tape(worker.store,job['venue'],job['payload']['market_id'],context.isoformat(),data_end.isoformat(),worker.settings.replay_max_trades,known_at=archive_cutoff)
    except ValueError as exc:
        if hours>1:
            cp['slice_hours']=max(1,hours/2);await worker.store.checkpoint(job,cp);return 1
        return await finish(worker,job,dict(cp,capacity_reason=str(exc)),'needs_analysis_capacity')
    else:unavailable=None
    report=analyze(trades,lo.isoformat(),hi.isoformat(),observation_end=data_end.isoformat()) if trades else dict(episodes=[],summary_bins=[],input_fills=0)
    cov=dict(sampled_fraction=1,status='verified_api_interval',gaps=[],meaning='Two matching complete API traversals of the frozen interval')
    # Completed HTTP traversal is not proof that every historical trade still
    # exists upstream or locally. Preserve its distinct provenance and gaps.
    report.update(analysis_mode='retrospective',version=VERSION,start=lo.isoformat(),end=hi.isoformat(),
        archive_cutoff=archive_cutoff,context_start=context.isoformat(),data_end=data_end.isoformat(),coverage=cov,backfill_status=cp.get('backfill_status','not_needed'),
        input_status='budget_exceeded' if unavailable else 'observed_inputs' if trades else 'no_observed_inputs',
        unavailable_reason=unavailable,raw_references=refs,normalized_replay_available=bool(trades),
        full_history_claim=False,settlement_version=review['id'])
    key=digest([review['id'],lo.isoformat(),hi.isoformat(),VERSION])
    cp.update(next_end=lo.isoformat(),slice_hours=24,slices=cp.get('slices',0)+1,
        episodes=cp.get('episodes',0)+len(report['episodes']),
        incomplete_slices=cp.get('incomplete_slices',0)+int(bool(unavailable) or cov['sampled_fraction']!=1))
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        await c.execute('''INSERT INTO surveillance_review_slices(id,review_id,lower_time,upper_time,document)
            VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(key,review['id'],lo,hi,Jsonb(report)))
        from .wallet_timing import persist
        await persist(c,key,trades,lo.isoformat(),hi.isoformat())
        await c.execute("UPDATE surveillance_retrospectives SET status='analyzing' WHERE id=%s AND status NOT IN ('excluded','superseded')",(review['id'],))
        await c.execute('UPDATE surveillance_jobs SET checkpoint=%s WHERE id=%s',(Jsonb(cp),job['id']))
    return 1
