"""Bounded multi-day wallet observations and verified-event settlement comparisons."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from collections import defaultdict
import re
import time

from psycopg.types.json import Jsonb

from .normalization import digest,now
from .money import cash

ROLLUP_VERSION=6


async def ingest_daily(c,trades,raw_id):
    """Only newly inserted fills reach this path; each receipt is applied once."""
    poly=[t for t in trades if t['venue']=='polymarket']
    if not poly:return dict(eligible_fills=0)
    return await receipt_parts(c,raw_id,poly)


async def receipt_parts(c,raw_id,trades=None):
    inserted=await (await c.execute('''INSERT INTO surveillance_wallet_daily_receipts(raw_id) VALUES(%s)
        ON CONFLICT DO NOTHING RETURNING raw_id''',(raw_id,))).fetchone()
    if not inserted:return dict(duplicate=True,eligible_fills=0)
    source='SELECT value AS t FROM jsonb_array_elements(%s)' if trades is not None else "SELECT document AS t FROM surveillance_trades WHERE venue='polymarket' AND raw_id=%s"
    param=Jsonb(trades) if trades is not None else raw_id
    rows=await (await c.execute(f'''WITH source AS ({source}),eligible AS (
        SELECT t FROM source WHERE t->>'wallet' ~ '^0x[0-9a-fA-F]{{40}}$'
        AND ((t->>'event_time')::timestamptz AT TIME ZONE 'UTC')::date>=(now() AT TIME ZONE 'UTC')::date-6
    ) INSERT INTO surveillance_wallet_daily_parts
        SELECT %s,lower(t->>'wallet'),t->>'market_id',COALESCE(NULLIF(t->>'token_id',''),t->>'outcome'),
        min(t->>'outcome'),((t->>'event_time')::timestamptz AT TIME ZONE 'UTC')::date,now(),
        min((t->>'event_time')::timestamptz),max((t->>'event_time')::timestamptz),count(*),
        COALESCE(sum((t->>'price')::numeric*(t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='1'),0),
        COALESCE(sum((t->>'price')::numeric*(t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='-1'),0),
        COALESCE(sum((t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='1'),0),
        COALESCE(sum((t->>'quantity')::numeric) FILTER(WHERE t->>'direction'='-1'),0),
        max((t->>'price')::numeric*(t->>'quantity')::numeric)
        FROM eligible GROUP BY 1,2,3,4,6 RETURNING fills''',(param,raw_id))).fetchall()
    total=sum(r['fills'] for r in rows)
    await c.execute('UPDATE surveillance_wallet_daily_receipts SET eligible_fills=%s WHERE raw_id=%s',(total,raw_id))
    return dict(eligible_fills=total,contributions=len(rows))


async def backfill_daily(store,job,limit=50,work_seconds=2):
    """Newest receipts first; live receipts are atomic and already marked processed."""
    cp=job['checkpoint'];processed=0;fills=0;last=None;started=time.monotonic()
    async with store.connection() as c:
        await store.fence(c,job)
        candidates=await (await c.execute('''SELECT r.id,r.received_at FROM surveillance_raw r
            WHERE r.venue='polymarket' AND (r.received_at,r.id)<(%s::timestamptz,%s)
            AND EXISTS(SELECT 1 FROM surveillance_trades t WHERE t.raw_id=r.id AND t.venue='polymarket')
            AND NOT EXISTS(SELECT 1 FROM surveillance_wallet_daily_receipts d WHERE d.raw_id=r.id)
            ORDER BY r.received_at DESC,r.id DESC LIMIT %s''',(cp.get('before_time','9999-01-01T00:00:00Z'),cp.get('before_id','~'),limit))).fetchall()
        for raw in candidates:
            if processed and time.monotonic()-started>=work_seconds:break
            result=await receipt_parts(c,raw['id']);processed+=1;fills+=result['eligible_fills'];last=raw
        done=len(candidates)<limit and processed==len(candidates)
        checkpoint=dict(processed_receipts=cp.get('processed_receipts',0)+processed,
            eligible_fills=cp.get('eligible_fills',0)+fills,done=done,version=ROLLUP_VERSION,
            scope='All eligible retained receipt fills; source expiry/feed gaps remain')
        if last:checkpoint.update(before_time=last['received_at'].isoformat(),before_id=last['id'])
        elif cp.get('before_time'):checkpoint.update(before_time=cp['before_time'],before_id=cp['before_id'])
        await c.execute("UPDATE surveillance_jobs SET checkpoint=%s,enabled=%s WHERE id=%s",(Jsonb(checkpoint),not done,job['id']))
        if done:await c.execute("UPDATE surveillance_jobs SET due_at=now() WHERE kind='slow_wallets'")
    return dict(checkpoint,processed_this_pass=processed)


async def find_accumulations(store,limit=20):
    rebuilding=await store.fetch("SELECT EXISTS(SELECT 1 FROM surveillance_jobs WHERE kind='wallet_rollup_backfill' AND enabled) AS pending")
    if rebuilding[0]['pending']:return dict(status='rebuilding_retained_receipts',candidates=0,version=ROLLUP_VERSION)
    candidates=await store.fetch('''SELECT wallet,market_id,outcome,min(outcome_label) AS label,
        min(first_event) AS first_event,max(last_event) AS last_event,
        count(DISTINCT day) AS observed_days,sum(fills) AS fills,sum(buy_cash) AS buy_cash,sum(sell_cash) AS sell_cash,
        sum(buy_shares) AS buy_shares,sum(sell_shares) AS sell_shares,max(max_fill_cash) AS max_fill_cash,
        true AS refs_complete FROM surveillance_wallet_daily_parts
        WHERE day>=(now() AT TIME ZONE 'UTC')::date-6 GROUP BY wallet,market_id,outcome
        HAVING max(last_event)<=now() AND count(DISTINCT day)>=2 AND max(last_event)-min(first_event)>=interval '6 hours'
            AND sum(fills)>=3 AND sum(buy_cash)>=1000 AND sum(buy_shares)>0
            AND sum(buy_shares)-sum(sell_shares)>=.8*sum(buy_shares)
        ORDER BY sum(buy_cash) DESC,wallet,market_id LIMIT %s''',(limit,))
    count=0
    for r in candidates:
        refs=await store.fetch('''SELECT DISTINCT raw_id AS id FROM surveillance_wallet_daily_parts
            WHERE wallet=%s AND market_id=%s AND outcome=%s AND day>=(now() AT TIME ZONE 'UTC')::date-6''',(r['wallet'],r['market_id'],r['outcome']))
        if len(refs)>4096:
            await store.coverage('polymarket','wallet_case_reference_budget',dict(wallet=r['wallet'],market_id=r['market_id'],references=len(refs),limit=4096))
            continue
        key=digest(['slow-wallet-v1',r['wallet'],r['market_id'],r['outcome'],r['last_event'].date().isoformat()])
        old=await store.fetch('SELECT created_at,document FROM surveillance_cases WHERE id=%s',(key,))
        facts={k:(str(v) if isinstance(v,Decimal) else v.isoformat() if isinstance(v,datetime) else v) for k,v in r.items()}
        doc=dict(id=key,kind='slow_accumulation',venue='polymarket',market_id=r['market_id'],wallet=r['wallet'],
            outcome_key=r['outcome'],status='candidate',observations=facts,knowledge_cutoff=now(),
            rollup_version=ROLLUP_VERSION,rollup_superseded=False,
            detected_at=old[0]['created_at'].isoformat() if old else now(),
            anomaly_score=None,evidence_quality=None,investigation_priority=None,
            replay_raw_ids=[x['id'] for x in refs if x['id']],
            score_meaning='Descriptive multi-day accumulation candidate, not an insider probability or realized position',
            limitations=['Observed buys less observed sells only; transfers/splits and unseen activity are unknown',
                'All retained eligible receipts included; expired/unobserved sources remain unknown',
                'One wallet address does not establish beneficial ownership or coordination'])
        await store.update_dossier(doc);count+=1
    return dict(candidates=count,row_limit=None,version=ROLLUP_VERSION,scope='Seven UTC dates within retained sources; at least six hours and two observed dates')


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
    earliest=await store.fetch('''SELECT id FROM surveillance_information WHERE venue='polymarket'
        AND market_id=ANY(%s) AND first_seen_at<=%s AND document->>'publication_time_verified'='true'
        AND (document->>'published_at')::timestamptz<%s
        ORDER BY (document->>'published_at')::timestamptz,id LIMIT 1''',(members,cutoff,anchor))
    if earliest:
        # An earlier disclosure with zero trades still invalidates later anchors.
        result=await record_event(store,earliest[0]['id'],as_of,max_rows,refresh_resolution)
        return dict(result,redirected_to_earlier_verified_anchor=earliest[0]['id'])
    earlier=await store.fetch('''SELECT document FROM surveillance_wallet_events WHERE event_key=%s AND known_at<=%s
        AND document->>'publication_anchor'<%s LIMIT 1''',(group,cutoff,anchor.isoformat()))
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
    previous=await store.fetch('''SELECT DISTINCT ON(wallet) wallet,document,raw_ids FROM surveillance_wallet_events
        WHERE event_key=%s AND known_at<=%s ORDER BY wallet,known_at DESC LIMIT 1001''',(group,cutoff))
    if len(previous)>1000:raise ValueError('Event wallet invalidation budget exceeded; no partial result produced')
    for row in previous:
        old=row['document']
        if row['wallet'] in ranked or dt(old['publication_anchor'])<=anchor:continue
        doc=dict(old,status='anchor_superseded',information_id=information_id,publication_anchor=anchor.isoformat(),
            actual_alert_before_anchor=None,all_receipts_before_anchor=False,observed_fills=0,positive_observed_outcomes=0,
            gross_cash='0',knowledge_cutoff=cutoff.isoformat(),
            invalidation='Earlier verified anchor superseded prior comparison; wallet absent from bounded current selection')
        refs=sorted(set(row['raw_ids']+[i['raw_id']]+metadata_refs))
        doc['content_hash']=digest([doc,refs])
        async with store.connection() as c:
            await c.execute('INSERT INTO surveillance_wallet_events VALUES(%s,%s,%s,%s,%s)',(row['wallet'],group,now(),Jsonb(doc),refs))
        updated+=1
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
        key=digest(['wallet-repeat-v1',r['wallet']])
        old=await store.fetch('SELECT document FROM surveillance_cases WHERE id=%s',(key,))
        if not summary['repeated_settlement_matches'] and not old:continue
        refs=sorted({rid for e in summary['events'] for rid in e['raw_ids']})
        if len(refs)>4096:continue  # Explicit API summary remains available; no unpinned auto dossier.
        first=summary['events'][0]['document']
        doc=dict(id=key,kind='repeated_pre_anchor_matches',venue='polymarket',wallet=r['wallet'],
            market_id=first['market_ids'][0],status='candidate',summary={k:v for k,v in summary.items() if k!='events'},
            events=[e['document'] for e in summary['events']],replay_raw_ids=refs,
            detected_at=old[0]['document']['detected_at'] if old else now(),
            anomaly_score=None,evidence_quality=None,investigation_priority=None,
            current_repeat_criterion_met=summary['repeated_settlement_matches'],
            score_meaning='Selected independent-event comparison; current repeat qualification explicit, no calibrated probability',
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
