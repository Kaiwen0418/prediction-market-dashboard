"""Bounded multi-day wallet observations and verified-event settlement comparisons."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from collections import defaultdict
import re

from psycopg.types.json import Jsonb

from .normalization import digest,now
from .money import cash

DAILY_LIMIT=200000


async def ingest_daily(c,trades,raw_id=None):
    rows=[t for t in trades if t['venue']=='polymarket' and re.fullmatch(r'0x[0-9a-fA-F]{40}',t.get('wallet') or '') and
          datetime.now(timezone.utc)-timedelta(days=7)<=datetime.fromisoformat(t['event_time'])<=datetime.now(timezone.utc)]
    if not rows:return
    existing=(await (await c.execute('SELECT count(*) AS n FROM surveillance_wallet_daily')).fetchone())['n']
    allowance=max(0,DAILY_LIMIT-existing)
    # SQL groups a page before admission; only new fills enter this transaction.
    await c.execute('''WITH grouped AS (
        SELECT lower(t->>'wallet') AS wallet,t->>'market_id' AS market_id,
            COALESCE(NULLIF(t->>'token_id',''),t->>'outcome') AS outcome,min(t->>'outcome') AS label,
            ((t->>'event_time')::timestamptz AT TIME ZONE 'UTC')::date AS day,
            min((t->>'event_time')::timestamptz) AS first_event,max((t->>'event_time')::timestamptz) AS last_event,
            count(*) AS fills,
            COALESCE(sum((t->>'price')::numeric*(t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='1'),0) AS buys,
            COALESCE(sum((t->>'price')::numeric*(t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='-1'),0) AS sells,
            COALESCE(sum((t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='1'),0) AS buy_shares,
            COALESCE(sum((t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='-1'),0) AS sell_shares,
            max((t->>'price')::numeric*(t->>'quantity')::numeric) AS max_cash
        FROM jsonb_array_elements(%s) t GROUP BY 1,2,3,5
    ), admitted AS (
        SELECT g.*,old.wallet IS NOT NULL AS known,
            sum(CASE WHEN old.wallet IS NULL THEN 1 ELSE 0 END) OVER(ORDER BY md5(g.wallet||g.market_id||g.outcome||g.day::text)) AS admission_index
        FROM grouped g LEFT JOIN surveillance_wallet_daily old USING(wallet,market_id,outcome,day)
    ) INSERT INTO surveillance_wallet_daily
        SELECT wallet,market_id,outcome,label,day,now(),first_event,last_event,fills,buys,sells,buy_shares,sell_shares,max_cash,ARRAY[%s]::text[],true
        FROM admitted WHERE known OR admission_index<=%s
        ON CONFLICT(wallet,market_id,outcome,day) DO UPDATE SET
            known_at=now(),first_event=LEAST(surveillance_wallet_daily.first_event,EXCLUDED.first_event),
            last_event=GREATEST(surveillance_wallet_daily.last_event,EXCLUDED.last_event),
            fills=surveillance_wallet_daily.fills+EXCLUDED.fills,
            buy_cash=surveillance_wallet_daily.buy_cash+EXCLUDED.buy_cash,sell_cash=surveillance_wallet_daily.sell_cash+EXCLUDED.sell_cash,
            buy_shares=surveillance_wallet_daily.buy_shares+EXCLUDED.buy_shares,sell_shares=surveillance_wallet_daily.sell_shares+EXCLUDED.sell_shares,
            max_fill_cash=GREATEST(surveillance_wallet_daily.max_fill_cash,EXCLUDED.max_fill_cash),
            refs_complete=surveillance_wallet_daily.refs_complete AND
                (%s=ANY(surveillance_wallet_daily.raw_ids) OR cardinality(surveillance_wallet_daily.raw_ids)<64),
            raw_ids=ARRAY(SELECT DISTINCT rid FROM unnest(surveillance_wallet_daily.raw_ids||EXCLUDED.raw_ids) rid ORDER BY rid LIMIT 64)
        ''',(Jsonb(rows),raw_id,allowance,raw_id))
    if not allowance:
        # A bounded telemetry row per hour, not one per rejected fill/page.
        await c.execute('''INSERT INTO surveillance_coverage(venue,kind,document)
            SELECT 'polymarket','wallet_rollup_capacity',%s WHERE NOT EXISTS(
                SELECT 1 FROM surveillance_coverage WHERE kind='wallet_rollup_capacity' AND observed_at>now()-interval '1 hour')''',
            (Jsonb(dict(row_limit=DAILY_LIMIT,meaning='New wallet/day cells skipped; existing tracked cells continue; no claim of complete wallet coverage')),))


async def find_accumulations(store,limit=20):
    candidates=await store.fetch('''SELECT wallet,market_id,outcome,min(outcome_label) AS label,
        min(first_event) AS first_event,max(last_event) AS last_event,
        count(DISTINCT day) AS observed_days,sum(fills) AS fills,sum(buy_cash) AS buy_cash,sum(sell_cash) AS sell_cash,
        sum(buy_shares) AS buy_shares,sum(sell_shares) AS sell_shares,max(max_fill_cash) AS max_fill_cash,
        bool_and(refs_complete) AS refs_complete FROM surveillance_wallet_daily
        WHERE day>=(now() AT TIME ZONE 'UTC')::date-6 GROUP BY wallet,market_id,outcome
        HAVING count(DISTINCT day)>=2 AND max(last_event)-min(first_event)>=interval '6 hours'
            AND sum(fills)>=3 AND sum(buy_cash)>=1000 AND sum(buy_shares)>0
            AND sum(buy_shares)-sum(sell_shares)>=.8*sum(buy_shares)
        ORDER BY sum(buy_cash) DESC,wallet,market_id LIMIT %s''',(limit,))
    count=0
    for r in candidates:
        refs=await store.fetch('''SELECT DISTINCT unnest(raw_ids) AS id FROM surveillance_wallet_daily
            WHERE wallet=%s AND market_id=%s AND outcome=%s AND day>=(now() AT TIME ZONE 'UTC')::date-6''',(r['wallet'],r['market_id'],r['outcome']))
        key=digest(['slow-wallet-v1',r['wallet'],r['market_id'],r['outcome'],r['last_event'].date().isoformat()])
        old=await store.fetch('SELECT created_at,document FROM surveillance_cases WHERE id=%s',(key,))
        facts={k:(str(v) if isinstance(v,Decimal) else v.isoformat() if isinstance(v,datetime) else v) for k,v in r.items()}
        doc=dict(id=key,kind='slow_accumulation',venue='polymarket',market_id=r['market_id'],wallet=r['wallet'],
            outcome_key=r['outcome'],status='candidate',observations=facts,knowledge_cutoff=now(),
            detected_at=old[0]['created_at'].isoformat() if old else now(),
            anomaly_score=None,evidence_quality=None,investigation_priority=None,
            replay_raw_ids=[x['id'] for x in refs if x['id']],
            score_meaning='Descriptive multi-day accumulation candidate, not an insider probability or realized position',
            limitations=['Observed buys less observed sells only; transfers/splits and unseen activity are unknown',
                'Wallet/day admission and raw retention are bounded; history may be partial',
                'One wallet address does not establish beneficial ownership or coordination'])
        await store.update_dossier(doc);count+=1
    return dict(candidates=count,row_limit=DAILY_LIMIT,scope='Seven retained UTC dates; at least six hours and two observed dates')


async def record_event(store,information_id,as_of,max_rows=50000,refresh_resolution=False):
    """Descriptive outcome match, including losses and hedges; no lookahead scoring."""
    from .event_review import family,dt
    cutoff=dt(as_of)
    info=await store.fetch("SELECT * FROM surveillance_information WHERE id=%s AND first_seen_at<=%s AND document->>'publication_time_verified'='true'",(information_id,cutoff))
    if not info:return dict(status='unverified_or_unavailable')
    i=info[0]
    if i['venue']!='polymarket':return dict(status='wallet_identity_unavailable')
    anchor=dt(i['document']['published_at'])
    if anchor>cutoff:return dict(status='publication_in_future')
    group,members,metadata_refs=await family(store,'polymarket',i['market_id'],cutoff)
    if not group.startswith('native-event:'):return dict(status='native_event_mapping_required')
    markets=await store.fetch('SELECT document,raw_id FROM surveillance_markets WHERE venue=%s AND (id=ANY(%s) OR condition_id=ANY(%s)) AND observed_at<=%s',('polymarket',members,members,cutoff))
    resolution={r['document'].get('condition_id') or r['document']['id']:r for r in markets}
    if refresh_resolution:
        await queue_resolution(store,[r['document'] for r in markets])
    earlier=await store.fetch('''SELECT document FROM surveillance_wallet_events WHERE event_key=%s
        AND document->>'publication_anchor'<%s LIMIT 1''',(group,anchor.isoformat()))
    if earlier:return dict(status='earlier_verified_anchor_already_recorded')
    rows=await store.fetch('''SELECT document,raw_id,received_at FROM surveillance_trades WHERE venue='polymarket'
        AND market_id=ANY(%s) AND event_time>=%s AND event_time<%s AND received_at<=%s
        ORDER BY event_time,id LIMIT %s''',(members,anchor-timedelta(days=7),anchor,cutoff,max_rows+1))
    if len(rows)>max_rows:return dict(status='row_budget_exceeded',limit=max_rows)
    wallets=defaultdict(list)
    for r in rows:
        if re.fullmatch(r'0x[0-9a-fA-F]{40}',r['document'].get('wallet') or ''):wallets[r['document']['wallet'].lower()].append(r)
    ranked=sorted(wallets,key=lambda w:sum(float(cash(r['document']) or 0) for r in wallets[w]),reverse=True)[:50]
    updated=0
    for wallet in ranked:
        activity=wallets[wallet];positions=defaultdict(Decimal);labels={}
        refs=set(metadata_refs+[i['raw_id']]);gross=Decimal(0)
        for row in activity:
            t=row['document'];key=(t['market_id'],t['token_id'] or t['outcome'])
            if t['direction'] is not None:positions[key]+=Decimal(t['quantity'])*t['direction']
            labels[key]=t['outcome']
            refs.add(row['raw_id']);gross+=cash(t) or 0
        positive=[k for k,v in positions.items() if v>0]
        if any(r['document']['direction'] is None for r in activity):status='unknown_direction'
        elif len(positive)>1:status='mixed_or_hedged'
        elif not positive:status='no_observed_positive_exposure'
        else:
            k=positive[0];m=resolution.get(k[0]);winner=m['document'].get('resolved_outcome') if m else None
            status='unknown_resolution' if winner is None else ('settlement_match' if labels[k].lower()==str(winner).lower() else 'settlement_mismatch')
            if m:refs.add(m['raw_id'])
        alerts=await store.fetch('''SELECT min(created_at) AS first_alert FROM surveillance_cases
            WHERE venue='polymarket' AND market_id=ANY(%s) AND created_at<%s AND
            (document->>'wallet'=%s OR document->'wallet_observations' @> %s::jsonb)''',
            (members,anchor,wallet,Jsonb([dict(wallet=wallet)])))
        doc=dict(wallet=wallet,event_key=group,information_id=information_id,publication_anchor=anchor.isoformat(),market_ids=members,
            status=status,positive_observed_outcomes=len(positive),observed_fills=len(activity),gross_cash=str(gross),
            all_receipts_before_anchor=all(r['received_at']<=anchor for r in activity),
            actual_alert_before_anchor=alerts[0]['first_alert'].isoformat() if alerts[0]['first_alert'] else None,
            meaning='Observed pre-anchor exposure versus final outcome; not actual profit, identity or insider trading',
            limitations=['Only retained public fills; external inventory and missing history unknown',
                'Anchor is manually verified, not proof of earliest public availability',
                'Multiple positive outcomes are mixed; one native event counts once, including losses/unknowns',
                'Top 50 observed wallets only; selected sample, not a population success rate'])
        checksum=digest([doc,sorted(refs)])
        old=await store.fetch('SELECT document FROM surveillance_wallet_events WHERE wallet=%s AND event_key=%s ORDER BY known_at DESC LIMIT 1',(wallet,group))
        if old and old[0]['document'].get('content_hash')==checksum:continue
        doc.update(content_hash=checksum,knowledge_cutoff=cutoff.isoformat())
        async with store.connection() as c:
            await c.execute('INSERT INTO surveillance_wallet_events VALUES(%s,%s,%s,%s,%s)',(wallet,group,now(),Jsonb(doc),sorted(r for r in refs if r)))
        updated+=1
    return dict(status='recorded',updated=updated,observed_wallets=len(wallets),wallet_limit=50)


async def wallet_patterns(store,wallet,as_of=None):
    cutoff=as_of or now()
    records=await store.fetch('''SELECT DISTINCT ON(event_key) document,known_at,raw_ids FROM surveillance_wallet_events
        WHERE wallet=%s AND known_at<=%s ORDER BY event_key,known_at DESC LIMIT 201''',(wallet.lower(),cutoff))
    if len(records)>200:raise ValueError('Wallet event query exceeds 200 events')
    counts=defaultdict(int)
    for r in records:counts[r['document']['status']]+=1
    evaluable=counts['settlement_match']+counts['settlement_mismatch']
    return dict(wallet=wallet.lower(),knowledge_cutoff=cutoff,independent_events=len(records),
        evaluable_events=evaluable,matches=counts['settlement_match'],mismatches=counts['settlement_mismatch'],
        mixed=counts['mixed_or_hedged'],unknown=sum(v for k,v in counts.items() if k not in ('settlement_match','settlement_mismatch','mixed_or_hedged')),
        repeated_pattern_review_ready=evaluable>=3,repeated_settlement_matches=counts['settlement_match']>=3,events=records,
        meaning='Selected observed event sample; not a win probability, actual PnL or an insider classifier')


async def refresh_pattern_cases(store,limit=20):
    wallets=await store.fetch('SELECT wallet,max(known_at) AS last FROM surveillance_wallet_events GROUP BY wallet ORDER BY max(known_at) DESC LIMIT %s',(limit,))
    created=0
    for r in wallets:
        summary=await wallet_patterns(store,r['wallet'])
        if not summary['repeated_settlement_matches']:continue
        refs=sorted({rid for e in summary['events'] for rid in e['raw_ids']})
        if len(refs)>4096:continue  # Explicit API summary remains available; no unpinned auto dossier.
        first=summary['events'][0]['document']
        key=digest(['wallet-repeat-v1',r['wallet']])
        old=await store.fetch('SELECT document FROM surveillance_cases WHERE id=%s',(key,))
        doc=dict(id=key,kind='repeated_pre_anchor_matches',venue='polymarket',wallet=r['wallet'],
            market_id=first['market_ids'][0],status='candidate',summary={k:v for k,v in summary.items() if k!='events'},
            events=[e['document'] for e in summary['events']],replay_raw_ids=refs,
            detected_at=old[0]['document']['detected_at'] if old else now(),
            anomaly_score=None,evidence_quality=None,investigation_priority=None,
            score_meaning='At least three selected, distinct native events with observed exposure matching settlement; no calibrated probability',
            limitations=['Retrospectively known outcomes never change original trading alert scores',
                'Includes mismatch/mixed/unknown counts; sample is selected and history may be partial',
                'Pre-anchor event times are distinct from real alerts or receipts before publication'])
        checksum=digest([doc['events'],refs,doc['summary']['matches'],doc['summary']['mismatches']])
        if old and old[0]['document'].get('content_hash')==checksum:continue
        doc['content_hash']=checksum
        await store.update_dossier(doc);created+=1
    return dict(pattern_candidates=created,examined_wallets=len(wallets))


async def queue_resolution(store,markets):
    """At most 20 pending one-off lookups; hourly retry, three source failures stop."""
    async with store.connection() as c:
        pending=(await (await c.execute("SELECT count(*) AS n FROM surveillance_jobs WHERE enabled AND payload->>'reason'='verified event settlement refresh'")).fetchone())['n']
        for m in markets:
            if pending>=20:break
            if m.get('resolved_outcome') is not None:continue
            result=await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload)
                VALUES(%s,'details','polymarket',%s) ON CONFLICT(id) DO UPDATE SET
                enabled=true,due_at=now(),checkpoint='{}'::jsonb
                WHERE NOT surveillance_jobs.enabled AND surveillance_jobs.failures<3
                AND surveillance_jobs.updated_at<now()-interval '1 hour' RETURNING id""",
                ('resolution:polymarket:'+m['id'],Jsonb(dict(market_id=m['id'],manual=True,reason='verified event settlement refresh'))))
            if result.rowcount:pending+=1
    return dict(pending=pending,pending_limit=20)
