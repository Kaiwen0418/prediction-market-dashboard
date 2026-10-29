"""Bounded first-pass detection outside the deep pool; no automatic trading."""
from psycopg.types.json import Jsonb
from .discovery import theme,event_key


async def scan(store,venue,limit=20):
    candidates=await store.fetch('''SELECT market_id,sum(cash) AS cash FROM surveillance_scout
        WHERE venue=%s AND bucket>=now()-interval '15 minutes' GROUP BY market_id
        HAVING sum(cash)>=1000 ORDER BY sum(cash) DESC,market_id LIMIT 5001''',(venue,))
    budget_exceeded=len(candidates)>5000
    candidates=candidates[:5000]
    keys=[r['market_id'] for r in candidates]
    metadata=await store.fetch('''SELECT document FROM surveillance_markets WHERE venue=%s
        AND (id=ANY(%s) OR condition_id=ANY(%s))''',(venue,keys,keys)) if keys else []
    markets={r['document'].get('condition_id') or r['document']['id']:r['document'] for r in metadata}
    active=await store.fetch("SELECT payload->>'market_id' AS id FROM surveillance_jobs WHERE venue=%s AND ((enabled AND kind='detect') OR (kind='scout_detect' AND (enabled OR updated_at>now()-interval '5 minutes')))",(venue,))
    already={r['id'] for r in active};chosen=[];events={}
    ranked=sorted(candidates,key=lambda r:({'information':0,'sports':0,'civic':1,'other':2}.get(theme(markets[r['market_id']]),2) if r['market_id'] in markets else 3,-float(r['cash']),r['market_id']))
    for row in ranked:
        key=row['market_id'];m=markets.get(key)
        if key in already or not m or m['closed'] or m.get('settled') or m.get('is_combo') or not m.get('tradable',True) or len(m.get('event_ids',[]))!=1:continue
        group=event_key(m)
        if events.get(group,0)>=2:continue
        chosen.append((key,m));events[group]=events.get(group,0)+1
        if len(chosen)>=limit:break
    async with store.connection() as c:
        pending=(await (await c.execute("SELECT count(*) AS n FROM surveillance_jobs WHERE venue=%s AND kind='scout_detect' AND enabled",(venue,))).fetchone())['n']
        for key,m in chosen[:max(0,limit-pending)]:
            await c.execute('''INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'scout_detect',%s,%s)
                ON CONFLICT(id) DO UPDATE SET enabled=true,due_at=now(),payload=EXCLUDED.payload
                WHERE surveillance_jobs.updated_at<now()-interval '5 minutes' ''',
                ('scout-detect:'+venue+':'+key,venue,Jsonb(dict(market_id=key,catalog_id=m['id'],trigger='wide_first_pass'))))
    return dict(candidate_budget_exceeded=budget_exceeded,candidates=len(candidates),admitted=min(len(chosen),max(0,limit-pending)),active_limit=limit,
                scope='Outside deep selection; sampled activity, not an insider classification')
