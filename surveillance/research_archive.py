"""Compact normalized tape, independently bounded and explicitly not raw evidence."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb
from psycopg import sql

from .normalization import digest, now

TABLES = ('surveillance_research_tape','surveillance_research_walks',
          'surveillance_retrospectives','surveillance_review_slices')
FIELDS = ('id','event_time','received_at','outcome','token_id','price','quantity',
          'direction','wallet','cash_price','cash_notional','is_block_trade')


async def capture(c, trades, raw):
    groups = defaultdict(list)
    for t in trades:
        groups[t['market_id']].append(t)
    records=[]
    for key, fills in groups.items():
        # Repeated wallet/outcome strings are compressed by PostgreSQL TOAST;
        # column names and venue/market identifiers are stored once per fragment.
        document=dict(format=1,fields=FIELDS,rows=[[t.get(k) for k in FIELDS] for t in fills],
                      source=raw['source'],raw_sha256=raw['sha256'])
        times=[t['event_time'] for t in fills]
        records.append((digest([raw['id'],key]),raw['venue'],key,min(times),max(times),
                        now(),raw['id'],len(fills),Jsonb(document)))
    if records:
        async with c.cursor() as cur:
            await cur.executemany('INSERT INTO surveillance_research_tape VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',records)


async def capture_walk(c, job, walk):
    if not walk.get('source_upper') or walk['source_upper']<=walk['lower_time']:
        return
    await c.execute('INSERT INTO surveillance_research_walks VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
        (digest([job['id'],walk]),job['venue'],None if job['kind']=='wide' else job['payload']['market_id'],
         walk['lower_time'],walk['source_upper'],now(),Jsonb(dict(refs_complete=walk['refs_complete'],
         raw_ids=walk['raw_ids'],meaning='Completed REST walk at collection time; not exchange completeness'))))


async def read_tape(store, venue, market_id, start, end, limit=50000, known_at=None):
    result={}; references={}; scanned=0
    async with store.connection() as c:
        async with c.cursor(name='research_tape') as cur:
            cur.itersize=32
            await cur.execute('''SELECT * FROM surveillance_research_tape WHERE venue=%s AND market_id=%s
                AND lower_time<%s AND upper_time>=%s AND known_at<=%s ORDER BY lower_time,id''',(venue,market_id,end,start,known_at or now()))
            async for r in cur:
                scanned+=r['fills']
                if scanned>limit*4:
                    raise ValueError('fragment_scan_budget')
                references[r['raw_id']]=dict(raw_id=r['raw_id'],sha256=r['document']['raw_sha256'],source=r['document']['source'])
                if len(references)>4096:raise ValueError('receipt_reference_budget')
                for values in r['document']['rows']:
                    t=dict(zip(r['document']['fields'],values))
                    if start<=t['event_time']<end:
                        t.update(venue=venue,market_id=market_id)
                        old=result.get(t['id'])
                        if old is None or t['received_at']<old['received_at']:
                            result[t['id']]=t
                        if len(result)>limit:
                            raise ValueError('fill_budget')
    return list(result.values()),list(references.values())


async def coverage(store,venue,market_id,start,end):
    from .observation import merge
    rows=await store.fetch('''SELECT lower_time,upper_time FROM surveillance_research_walks
        WHERE venue=%s AND (market_id=%s OR market_id IS NULL) AND lower_time<%s AND upper_time>%s
        AND document->>'refs_complete'='true' ORDER BY lower_time LIMIT 20001''',(venue,market_id,end,start))
    if len(rows)>20000:
        return dict(sampled_fraction=None,status='coverage_query_budget',gaps=[])
    lo,hi=datetime.fromisoformat(start),datetime.fromisoformat(end)
    intervals=merge([(max(lo,r['lower_time']),min(hi,r['upper_time'])) for r in rows])
    cursor=lo; gaps=[]
    for a,b in intervals:
        if a>cursor:gaps.append([cursor.isoformat(),a.isoformat()])
        cursor=max(cursor,b)
    if cursor<hi:gaps.append([cursor.isoformat(),hi.isoformat()])
    return dict(sampled_fraction=sum((b-a).total_seconds() for a,b in intervals)/(hi-lo).total_seconds(),
                status='sampled' if not gaps else 'partial_or_unknown',gaps=gaps[:100],gaps_omitted=max(0,len(gaps)-100),
                meaning='Historical REST walk coverage; archive eviction checked separately')


async def maintain(store,settings,force=False):
    """Bound recorded tuple bytes plus 256 bytes/row allowance; global physical budget remains."""
    cutoff=datetime.now(timezone.utc)-timedelta(days=settings.research_retention_days)
    removed={}
    async with store.connection() as c:
        counters=await (await c.execute('SELECT name,logical_bytes FROM surveillance_research_budget')).fetchall()
        usage={r['name']:r['logical_bytes'] for r in counters}
        sizes=dict(tape=usage.get('surveillance_research_tape',0),summaries=sum(v for k,v in usage.items() if k!='surveillance_research_tape'))
        for table in ('surveillance_research_tape','surveillance_research_walks','surveillance_retrospectives'):
            over=force or (sizes['tape']>=settings.research_tape_max_bytes if table=='surveillance_research_tape'
                          else sizes['summaries']>=settings.research_summary_max_bytes)
            query=sql.SQL('DELETE FROM {} WHERE id IN(SELECT id FROM {} WHERE {} ORDER BY known_at,id LIMIT 500) RETURNING ' + ('id,venue,market_id,lower_time,upper_time' if table=='surveillance_research_tape' else 'id')).format(
                sql.Identifier(table),sql.Identifier(table),sql.SQL('true') if over else sql.SQL('known_at<%s'))
            expired=await (await c.execute(query,() if over else (cutoff,))).fetchall()
            removed[table]=len(expired)
            if table=='surveillance_research_tape' and expired:
                # Archived walk coverage cannot survive loss of its normalized tape.
                ranges={}
                for r in expired:
                    key=(r['venue'],r['market_id']); old=ranges.get(key,(r['lower_time'],r['upper_time']))
                    ranges[key]=(min(old[0],r['lower_time']),max(old[1],r['upper_time']))
                for (venue,market_id),(lo,hi) in ranges.items():
                    await c.execute('''DELETE FROM surveillance_research_walks WHERE venue=%s
                        AND (market_id=%s OR market_id IS NULL) AND lower_time<=%s AND upper_time>=%s''',
                        (venue,market_id,hi,lo))
        if any(removed.values()):
            await c.execute("INSERT INTO surveillance_coverage(venue,kind,document) VALUES('system','research_archive_eviction',%s)",
                (Jsonb(dict(removed=removed,reason='capacity' if force else 'archive_budget_or_age',
                            retrospective_coverage_may_be_incomplete=True)),))
    return dict(logical_budget_bytes=sizes,removed=removed,retention_days=settings.research_retention_days)


async def bootstrap(worker,job):
    """Copy retained hot inputs once, newest first; never resurrect expired trades."""
    cp=job['checkpoint']; before=cp.get('before_time',now()); after_id=cp.get('before_id','~')
    rows=await worker.store.fetch('''SELECT r.* FROM surveillance_raw r
        WHERE (r.received_at,r.id)<(%s::timestamptz,%s)
        AND EXISTS(SELECT 1 FROM surveillance_trades t WHERE t.raw_id=r.id)
        ORDER BY r.received_at DESC,r.id DESC LIMIT 10''',(before,after_id))
    async with worker.store.connection() as c:
        await worker.store.fence(c,job)
        copied=0
        for r in rows:
            ts=await (await c.execute('SELECT document FROM surveillance_trades WHERE raw_id=%s LIMIT 50001',(r['id'],))).fetchall()
            if len(ts)>50000:
                await c.execute("INSERT INTO surveillance_coverage(venue,kind,document) VALUES(%s,'research_bootstrap_budget',%s)",
                    (r['venue'],Jsonb(dict(raw_id=r['id'],reason='receipt exceeds 50000 fills; not copied'))))
            else:
                await capture(c,[t['document'] for t in ts],dict(r,received_at=r['received_at'].isoformat()))
                copied+=len(ts)
        next_cp=dict(copied_fills=cp.get('copied_fills',0)+copied,scope='retained hot inputs only; expired history unknown')
        if rows:next_cp.update(before_time=rows[-1]['received_at'].isoformat(),before_id=rows[-1]['id'])
        else:next_cp['completed_at']=now()
        await c.execute('UPDATE surveillance_jobs SET checkpoint=%s,enabled=%s WHERE id=%s',(Jsonb(next_cp),bool(rows),job['id']))
    return 5
