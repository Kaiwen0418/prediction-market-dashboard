import asyncio
from collections import Counter
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import logging
import signal

from .collectors import Collector, ContractError
from .discovery import Selector,event_key,theme
from .detectors import automatic_candidate
from .investigations import replay, ReplayCapacityError
from .maintenance import prune
from .capacity import CapacityGuard
from .normalization import market, trade, digest
from .storage import Store, RawArchive
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings, collector=None):
        self.settings = settings
        self.store = Store(settings.database_url)
        self.capacity = CapacityGuard(self.store, settings)
        self.collector = collector or Collector(self.store, RawArchive(settings.raw_dir), settings.request_interval)

    async def seed(self):
        await self.store.enqueue("aggregates", "aggregates", "system", {})
        await self.store.enqueue("maintenance", "maintenance", "system", {})
        catalog_ids = []
        for venue in ("polymarket", "kalshi"):
            key = f"catalog:{venue}:active:v2"
            catalog_ids.append(key)
            await self.store.enqueue(key, "catalog", venue, {"closed": False, "scope": "active-v2"})
        async with self.store.connection() as c:
            # Repair the initial v2 flag: Gamma combo eligibility is not a combo.
            await c.execute("""UPDATE surveillance_markets SET document=jsonb_set(document,'{is_combo}','false'::jsonb)
                WHERE venue='polymarket' AND document->>'is_combo'='true'""")
            # Query scope changes invalidate opaque cursors: use new job identities.
            await c.execute("UPDATE surveillance_jobs SET enabled=false WHERE kind='catalog' AND NOT(id=ANY(%s))", (catalog_ids,))
            # A pre-walk-marker checkpoint cannot safely expire unseen rows.
            await c.execute("""UPDATE surveillance_jobs SET checkpoint='{}',due_at=now(),lease_until=NULL,lease_token=NULL
                WHERE id=ANY(%s) AND checkpoint->>'cursor' IS NOT NULL
                AND NOT(checkpoint ? 'walk_started_at')""", (catalog_ids,))
        # Repair sparse detail overwrites left by schema 1/2, through the one writer.
        async with self.store.connection() as c:
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload)
                SELECT 'metadata-repair:'||m.id,'details',m.venue,
                    jsonb_build_object('market_id',COALESCE(m.condition_id,m.id),'catalog_id',m.id,
                        'manual',true,'reason','restore omitted catalog metadata')
                FROM surveillance_markets m JOIN surveillance_raw r ON r.id=m.raw_id
                WHERE m.venue='polymarket' AND m.document->'event_ids'='[]'::jsonb
                    AND r.source ~ '/markets/[0-9]+$' LIMIT 500 ON CONFLICT DO NOTHING""")
        for venue in ("polymarket", "kalshi"):
            await self.store.enqueue(f'wide:{venue}:v2','wide',venue,{'scope':'global'})
            await self.store.enqueue(f"schedule:{venue}", "schedule", venue, {})
        async with self.store.connection() as c:
            await c.execute("UPDATE surveillance_jobs SET due_at=LEAST(due_at,now()) WHERE kind='schedule'")
            await c.execute("UPDATE surveillance_jobs SET enabled=false WHERE kind='wide' AND id NOT LIKE '%:v2'")

    async def schedule(self, venue):
        activity=await self.store.fetch("""SELECT market_id,
            COALESCE(sum(cash) FILTER(WHERE bucket>=date_trunc('minute',now())-interval '5 minutes'),0) AS recent_cash,
            COALESCE(sum(cash) FILTER(WHERE bucket<date_trunc('minute',now())-interval '5 minutes'),0) AS prior_cash,
            max(last_event) AS last_event FROM surveillance_scout
            WHERE venue=%s AND bucket>=now()-interval '15 minutes' GROUP BY market_id""", (venue,))
        scouts={r['market_id']:r for r in activity}
        previous=await self.store.fetch("SELECT payload FROM surveillance_jobs WHERE venue=%s AND kind='trades' AND enabled AND NOT COALESCE((payload->>'manual')::boolean,false)",(venue,))
        selector = Selector(self.settings.contracts_per_venue, self.settings.exploration_fraction,
            end_grace_hours=self.settings.end_grace_hours,scouts=scouts,previous={r['payload']['market_id'] for r in previous})
        async with self.store.connection() as c:
            async with c.cursor(name="selection") as cursor:
                cursor.itersize = 256
                await cursor.execute("""SELECT document FROM surveillance_markets WHERE venue=%s
                    AND document->>'closed'='false' AND observed_at>=now()-(%s * interval '1 second')""",
                    (venue,2*self.settings.catalog_seconds))
                async for row in cursor:
                    selector.add(row["document"])
        chosen = selector.result()
        # Unmapped catalog rows get bounded enrichment instead of pretending that
        # each missing event ID denotes a different independent event.
        async with self.store.connection() as c:
            pending=(await (await c.execute("SELECT count(*) AS n FROM surveillance_jobs WHERE venue=%s AND enabled AND payload->>'lookup'='true'",(venue,))).fetchone())['n']
            for _,m in selector.unmapped.items[:min(10,max(0,20-pending))]:
                key=m.get('condition_id') or m['id']
                await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'details',%s,%s)
                    ON CONFLICT DO NOTHING""",('lookup:'+venue+':'+key,venue,Jsonb(dict(market_id=key,
                    lookup=True,manual=True,trigger='unmapped_exploration',reason='one-off native event metadata resolution'))))
        count = (await self.store.fetch("SELECT count(*) AS n FROM surveillance_markets WHERE venue=%s", (venue,)))[0]["n"]
        rows=[]
        for m in chosen:
            key=m['condition_id'] or m['id']
            for kind in ('details','trades','detect'):
                rows.append((f'{kind}:{venue}:{key}',kind,venue,Jsonb(dict(market_id=key,
                    catalog_id=m['id'],selection=selector.selection[m['id']]))))
        keys=[r[0] for r in rows]
        async with self.store.connection() as c:
            async with c.cursor() as cursor:
                await cursor.executemany("""INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET payload=EXCLUDED.payload""", rows)
            await c.execute("""UPDATE surveillance_jobs SET enabled=(id=ANY(%s)),
                due_at=CASE WHEN NOT enabled AND id=ANY(%s) THEN now() ELSE due_at END
                WHERE venue=%s AND kind IN ('details','trades','detect') AND NOT COALESCE((payload->>'manual')::boolean,false)""", (keys,keys,venue))
        await self.store.coverage(venue, "budget", {"catalog_rows": count, "selected_contracts": len(chosen),
            "budget": self.settings.contracts_per_venue, "exploration_fraction": self.settings.exploration_fraction,
            'independent_events':len({event_key(m) for m in chosen}),
            'theme_counts':dict(Counter(theme(m) for m in chosen)),
            'low_activity_selected':sum(selector.selection[m['id']]['reason']=='low_activity_exploration' for m in chosen),
            'unmapped_event_count':sum(not m.get('event_ids') for m in chosen),
            'unmapped_catalog_candidates':selector.counts['unmapped'],
            'recent_broad_markets':len(scouts),
            'scout_promoted':sum(selector.selection[m['id']]['reason']=='wide_activity_promotion' for m in chosen),
            "limitations": ["Heuristic category ranking; only native within-platform event grouping available",
                             "REST only; order books and broadcast feeds not collected",
                             "Automatic catalog: active contracts only; MVE combinations excluded",
                             "Closed contracts are available through explicit detail/backfill jobs",
                             "Past schedule time lowers ranking; explicit source tradability controls eligibility"]})

    async def resolve_unknowns(self,venue,trades):
        amounts={}
        for t in trades:
            amounts[t['market_id']]=amounts.get(t['market_id'],Decimal(0))+Decimal(t['price'])*Decimal(t['quantity'])
        keys=[k for k,v in sorted(amounts.items(),key=lambda kv:kv[1],reverse=True) if v>=1000][:20]
        if not keys:return
        async with self.store.connection() as c:
            known=await (await c.execute("SELECT id,condition_id FROM surveillance_markets WHERE venue=%s AND (id=ANY(%s) OR condition_id=ANY(%s)) AND jsonb_array_length(COALESCE(document->'event_ids','[]'))>0", (venue,keys,keys))).fetchall()
            mapped={r['condition_id'] or r['id'] for r in known}
            pending=(await (await c.execute("SELECT count(*) AS n FROM surveillance_jobs WHERE venue=%s AND enabled AND payload->>'lookup'='true'", (venue,))).fetchone())['n']
            for key in [k for k in keys if k not in mapped][:max(0,20-pending)]:
                await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'details',%s,%s)
                    ON CONFLICT DO NOTHING""", ('lookup:'+venue+':'+key,venue,Jsonb(dict(market_id=key,
                    manual=True,lookup=True,trigger='wide_feed',reason='one-off metadata resolution; not a user investigation'))))

    async def ingest(self, job):
        cp = dict(job["checkpoint"])
        if job["kind"] == "backfill":
            rows = await self.store.fetch("SELECT document FROM surveillance_markets WHERE venue=%s AND id=%s",
                                          (job["venue"],job["payload"]["catalog_id"]))
            if not rows:
                raise ContractError("Backfill requires its detail job to complete first")
            m = rows[0]["document"]
            job["payload"] = dict(job["payload"], market_id=m["condition_id"] or m["id"])
        if job["kind"] in ("trades", "backfill", "wide") and not cp.get("since"):
            horizon=timedelta(seconds=self.settings.wide_bootstrap_seconds) if job['kind']=='wide' else timedelta(hours=self.settings.deep_history_hours)
            cp['since']=int((datetime.now(timezone.utc)-horizon).timestamp())
            await self.store.checkpoint(job, cp)
            await self.store.coverage(job["venue"], "bootstrap_horizon", {"market_id": job["payload"].get("market_id"),
                "since": cp["since"], "older_history": "not_collected", "scope":job["payload"].get("scope","contract")}, job["id"])
        for _ in range(self.settings.pages_per_job):
            if not await self.capacity.check():
                return 60
            job["checkpoint"] = cp
            raw, rows, cursor = await self.collector.page(job)
            cursor_hash = digest(cursor) if cursor else None
            seen = cp.get("seen_cursors", [])
            if cursor_hash and cursor_hash in seen:
                raise ContractError("Pagination cursor cycle; checkpoint preserved")
            cp["seen_cursors"] = (seen + [cursor_hash])[-1000:] if cursor_hash else []
            if job["kind"] in ("catalog", "details"):
                markets = [market(job["venue"], r, raw["received_at"]) for r in rows]
                started = cp.get("walk_started_at", raw["received_at"])
                cp = dict(cp, cursor=cursor, pages=cp.get("pages", 0) + 1, walk_started_at=started)
                if not cursor:
                    cp = {"completed_at": raw["received_at"], "pages": 0, "last_walk_started_at": started}
                expire_before = started if job["kind"] == "catalog" and not cursor and job["payload"].get("scope") == "active-v2" else None
                await self.store.commit_page(job, raw, cp, markets=markets, detailed=job["kind"] == "details",
                                             catalog_expire_before=expire_before)
            else:
                cp.setdefault('legacy_walk', bool(cp.get('cursor')) and not cp.get('walk_upper'))
                cp.setdefault('walk_upper', raw['received_at'])
                cp.setdefault('walk_lower', datetime.fromtimestamp(cp['since'], timezone.utc).isoformat())
                cp['walk_pages'] = cp.get('walk_pages', 0) + 1
                cp['walk_raw_ids'] = (cp.get('walk_raw_ids', []) + [raw['id']])[:64]
                normalized = [trade(job["venue"], r, raw["received_at"]) for r in rows]
                if job['kind']=='wide' and normalized and cp['walk_pages']==1:
                    cp['feed_head_at']=normalized[0]['event_time']
                previous = cp.get("last_time")
                counts = Counter(cp.get("counts", {}))
                accepted = []
                exhausted = False
                high_watermark = cp.get("high_watermark", cp["since"])
                for t in normalized:
                    ts = int(datetime.fromisoformat(t["event_time"]).timestamp())
                    if previous is not None and ts > previous:
                        raise ContractError("Trade feed not ordered newest-first; cannot safely checkpoint")
                    if ts < cp["since"]:
                        exhausted = True
                        break
                    if ts != previous:
                        counts.clear()
                    previous = ts
                    counts[t["identity"]] += 1
                    t["id"] = t["identity"] + (f":{counts[t['identity']]}" if job["venue"] == "polymarket" else "")
                    t["raw_id"] = raw["id"]
                    t["collection_scope"]=job["kind"]
                    accepted.append(t)
                    high_watermark = max(high_watermark, ts)
                cp.update(cursor=cursor, high_watermark=high_watermark, last_time=previous, counts=dict(counts))
                cp['walk_trades'] = cp.get('walk_trades',0)+len(accepted)
                if job['kind']=='wide':
                    cp.update(http_cache_control=raw.get('response_headers',{}).get('cache-control'),http_age=raw.get('response_headers',{}).get('age'))
                    cp.update(last_page_fills=len(accepted),last_page_markets=len({t['market_id'] for t in accepted}),
                        last_page_received_at=raw['received_at'],
                        head_event_time=datetime.fromtimestamp(high_watermark,timezone.utc).isoformat())
                completed_walk = None
                if exhausted or not cursor:
                    completed_walk = dict(lower_time=cp['walk_lower'], upper_time=cp['walk_upper'],
                        raw_ids=cp['walk_raw_ids'], refs_complete=cp['walk_pages']<=64,observed_trades=cp['walk_trades'])
                    if cp.get('legacy_walk') or job['kind']=='wide':
                        completed_walk = None
                    overlap=self.settings.wide_overlap_seconds if job['kind']=='wide' else 300
                    cp={"since":max(cp['since'],high_watermark-overlap),"completed_at":raw['received_at'],
                        'high_watermark_at':datetime.fromtimestamp(high_watermark,timezone.utc).isoformat(),
                        'last_walk_pages':cp['walk_pages'],'last_walk_fills':cp['walk_trades'],
                        'first_page_received_at':cp['walk_upper'],
                        'last_page_received_at':raw['received_at'],'feed_head_at':cp.get('feed_head_at'),
                        'http_cache_control':cp.get('http_cache_control'),'http_age':cp.get('http_age')}
                    cursor = None
                await self.store.commit_page(job, raw, cp, trades=accepted, completed_walk=completed_walk)
                if job['kind']=='wide':
                    await self.resolve_unknowns(job['venue'],accepted)
            if not cursor:
                await self.store.coverage(job["venue"], "walk_completed", {"kind": job["kind"],
                    "market_id": job["payload"].get("market_id"), "checkpoint": cp,
                    "meaning": "Completed requested walk only; not proof of upstream completeness"}, job["id"])
                if job["kind"] == "details":
                    return self.settings.detail_seconds
                if job['kind']=='wide':
                    return self.settings.wide_poll_seconds
                if job["kind"] in ("trades", "backfill"):
                    return self.settings.poll_seconds
                return self.settings.closed_catalog_seconds if job["payload"].get("closed") else self.settings.catalog_seconds
        await self.store.coverage(job["venue"], "walk_pending", {"kind": job["kind"],
            "reason": "page budget reached", "cursor_saved": True,
            "scope":job['payload'].get('scope','contract'),
            "oldest_event_seen":cp.get('last_time'),"requested_since":cp.get('since'),
            "note":"Cursor pending is not caught-up coverage"}, job["id"])
        return 1

    async def run_once(self):
        if not await self.capacity.check():
            return False
        job = await self.store.claim()
        if not job:
            return False
        try:
            if job['kind'] == 'aggregates':
                from .aggregates import materialize
                if not job['checkpoint'].get('bootstrapped'):
                    async with self.store.connection() as c:
                        await c.execute("""INSERT INTO surveillance_dirty_bins
                            SELECT DISTINCT venue,market_id,COALESCE(NULLIF(document->>'token_id',''),outcome),
                                to_timestamp((floor(extract(epoch FROM event_time)/300)+1)*300)
                            FROM surveillance_trades WHERE event_time>=now()-interval '7 days'
                            ON CONFLICT DO NOTHING""")
                await self.store.checkpoint(job, dict(await materialize(self.store),bootstrapped=True))
                delay = 30
            elif job['kind'] == 'event_review':
                from .event_review import build_review
                try:
                    result = await build_review(self.store, job['payload']['information_id'], job['payload']['as_of'],job['payload'].get('contract_only',False))
                    checkpoint = {'case_id': result['id'], 'completed_at': datetime.now(timezone.utc).isoformat()}
                except ValueError as exc:
                    # Invalid/expired inputs and explicit work caps require a new request,
                    # rather than unbounded retries of the same immutable cutoff.
                    checkpoint = {'review_unavailable': str(exc), 'completed_at': datetime.now(timezone.utc).isoformat()}
                    await self.store.coverage(job['venue'],'event_review_unavailable',checkpoint,job['id'])
                await self.store.checkpoint(job, checkpoint)
                async with self.store.connection() as c:
                    await self.store.fence(c, job)
                    await c.execute('UPDATE surveillance_jobs SET enabled=false WHERE id=%s', (job['id'],))
                delay = 3600
            elif job['kind'] == 'wallet':
                from .wallets import collect_profile
                delay = await collect_profile(self, job)
            elif job["kind"] == "maintenance":
                result = await prune(self.store, self.settings.retention_days)
                await self.store.checkpoint(job, result)
                delay = 3600
            elif job["kind"] == "schedule":
                await self.schedule(job["venue"])
                delay = 300
            elif job["kind"] == "detect":
                # Fixed UTC minute makes duplicate executions idempotent.
                as_of = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
                cases = await replay(self.store, job["venue"], job["payload"]["market_id"], as_of, persist=False, max_trades=self.settings.replay_max_trades)
                new_cases = 0
                eligible_cases = [case for case in cases if automatic_candidate(case["signal"], self.settings.automatic_min_cash_usd)]
                for case in eligible_cases:
                    created = await self.store.save_candidate(case, self.settings.case_cooldown_seconds)
                    new_cases += int(created)
                    if created:
                        from .wallets import admit_profile
                        await admit_profile(self.store, case)
                await self.store.checkpoint(job, {"as_of": as_of, "detected": len(cases),
                    "new_cases": new_cases, "coalesced": len(eligible_cases) - new_cases,
                    "suppressed_by_cost_floor": len(cases) - len(eligible_cases),
                    "automatic_min_cash_usd": self.settings.automatic_min_cash_usd})
                if cases:
                    # Escalation stays within the selected per-platform contract budget.
                    async with self.store.connection() as c:
                        await c.execute("""UPDATE surveillance_jobs SET due_at=LEAST(due_at,now()) WHERE id=%s""",
                            (f"trades:{job['venue']}:{job['payload']['market_id']}",))
                delay = 60
            else:
                delay = await self.ingest(job)
            if job["payload"].get("manual"):
                saved = await self.store.fetch("SELECT checkpoint FROM surveillance_jobs WHERE id=%s", (job["id"],))
                if saved and saved[0]["checkpoint"].get("completed_at"):
                    async with self.store.connection() as c:
                        await self.store.fence(c, job)
                        await c.execute("UPDATE surveillance_jobs SET enabled=false WHERE id=%s", (job["id"],))
            await self.store.release(job, delay)
        except asyncio.CancelledError:
            await self.store.release(job, 0, "worker interrupted; resume checkpoint")
            raise
        except Exception as exc:
            # Do not emit credentials, response bodies or query strings into logs.
            detail = str(exc) if isinstance(exc, (ContractError, ReplayCapacityError)) else "collection/job failed; inspect raw evidence"
            reason = f"{type(exc).__name__}: {detail}"
            logger.warning("Job %s failed (%s)", job["id"], type(exc).__name__)
            await self.store.coverage(job["venue"], "error", {"error": reason, "checkpoint_preserved": True}, job["id"])
            backoff = min(3600, 60 * 2 ** min(job["failures"], 5))
            if (job['payload'].get('lookup') or job['payload'].get('reason')=='restore omitted catalog metadata') and job['failures']>=2:
                async with self.store.connection() as c:
                    await self.store.fence(c,job)
                    await c.execute('UPDATE surveillance_jobs SET enabled=false WHERE id=%s',(job['id'],))
                await self.store.coverage(job['venue'],'unmapped_market',{'reason':'metadata lookup failed three times; source remains unresolved'},job['id'])
            await self.store.release(job, max(backoff, getattr(exc, "retry_after", 0)), reason)
        return True

    async def run(self, once=False):
        loop=asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM,asyncio.current_task().cancel)
        await self.seed()
        try:
            if once:
                return await self.run_once()
            while True:
                if not await self.run_once():
                    await asyncio.sleep(1)
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            await self.collector.close()
