"""Read-only runtime snapshot; contains no credentials or raw response bodies."""
import asyncio
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from surveillance.capacity import usage
from surveillance.config import Settings
from surveillance.discovery import event_key
from surveillance.storage import Store


async def main():
    settings=Settings.env();store=Store(settings.database_url)
    selected=await store.fetch("""SELECT j.venue,j.payload,m.document FROM surveillance_jobs j
        JOIN surveillance_markets m ON m.venue=j.venue AND m.id=j.payload->>'catalog_id'
        WHERE j.kind='trades' AND j.enabled AND NOT COALESCE((j.payload->>'manual')::boolean,false)""")
    selection={}
    for venue in ('polymarket','kalshi'):
        rows=[r for r in selected if r['venue']==venue]
        events=Counter(event_key(r['document']) for r in rows)
        selection[venue]=dict(contracts=len(rows),events=len(events),max_per_event=max(events.values(),default=0),
            unmapped=sum(not r['document'].get('event_ids') for r in rows),
            themes=dict(Counter(r['payload'].get('selection',{}).get('theme') for r in rows)),
            reasons=dict(Counter(r['payload'].get('selection',{}).get('reason') for r in rows)))
    broad=await store.fetch("""SELECT venue,count(*) AS retained_fills,
        count(DISTINCT market_id) AS markets,
        count(*) FILTER(WHERE received_at>now()-interval '60 seconds') AS newly_received_60s,
        max(received_at) AS latest_receipt,max(event_time) AS latest_event
        FROM surveillance_trades WHERE document->>'collection_scope'='wide' GROUP BY venue""")
    job_state=await store.fetch("SELECT venue,kind,failures,last_error,(checkpoint-'counts'-'seen_cursors'-'walk_raw_ids'-'cursor')||jsonb_build_object('cursor_pending',checkpoint ? 'cursor') AS checkpoint FROM surveillance_jobs WHERE kind='wide' AND enabled ORDER BY venue")
    lags=await store.fetch("""SELECT venue,count(*) AS completed,
        percentile_cont(.95) WITHIN GROUP(ORDER BY extract(epoch FROM now()-(checkpoint->>'as_of')::timestamptz)) AS p95_age_seconds
        FROM surveillance_jobs WHERE enabled AND kind='detect' AND checkpoint ? 'as_of' GROUP BY venue""")
    receipts=await store.fetch("""SELECT venue,count(*) AS pages_5m FROM surveillance_raw
        WHERE received_at>now()-interval '5 minutes' AND source LIKE '%%/trades'
        AND NOT(params ? 'condition') AND NOT(params ? 'ticker') AND NOT(params ? 'user') GROUP BY venue""")
    files=('worker.py','storage.py','discovery.py','collectors.py','normalization.py','schema.sql','aggregates.py','config.py','detectors.py','observation.py','screening.py','longitudinal.py','money.py','investigations.py')
    print(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),settings=dict(contracts_per_venue=settings.contracts_per_venue,deep_poll_seconds=settings.poll_seconds,detail_seconds=settings.detail_seconds,wide_poll_seconds=settings.wide_poll_seconds,pages_per_claim=settings.pages_per_job),usage=await usage(store,settings),
        selection=selection,wide=broad,wide_jobs=job_state,wide_pages_5m=receipts,detector_ages=lags,
        observation_intervals=await store.fetch("SELECT venue,count(*) AS intervals,min(lower_time) AS oldest_sampled,max(upper_time) AS source_head,max(known_at) AS latest_known FROM surveillance_observations GROUP BY venue"),
        multi_day=await store.fetch("SELECT count(*) AS daily_cells,pg_total_relation_size('surveillance_wallet_daily') AS bytes,min(first_event) AS oldest_event,max(last_event) AS newest_event FROM surveillance_wallet_daily"),
        case_kinds=await store.fetch("SELECT COALESCE(document->>'kind','legacy') AS kind,count(*) AS cases FROM surveillance_cases GROUP BY 1"),
        first_pass=await store.fetch("SELECT venue,checkpoint FROM surveillance_jobs WHERE kind='candidate_scan' ORDER BY venue"),
        pending_bins=await store.fetch("SELECT count(*) AS n,count(*) FILTER(WHERE bin_end<=now()) AS closed_ready,min(bin_end) AS oldest FROM surveillance_dirty_bins"),
        source_sha256={name:hashlib.sha256((Path('surveillance')/name).read_bytes()).hexdigest() for name in files},
        caveat='Bounded REST observations; counts are not platform coverage percentages; startup includes metadata repair/history warmup'),default=str,indent=2))


if __name__=='__main__':asyncio.run(main())
