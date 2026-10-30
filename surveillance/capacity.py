"""FIFO eviction for the disposable test dataset, with physical space reclamation.

Budgets are admission watermarks, not filesystem quotas. One in-flight job plus
PostgreSQL WAL/compaction scratch space must fit outside the configured budget.
"""
import asyncio
from pathlib import Path
import time

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

LOCK = 81724003
QUERY_TIMEOUT_MS = 15000
DERIVED = ('surveillance_observations','surveillance_wallet_daily','surveillance_wallet_events','surveillance_aggregates','surveillance_walks','surveillance_wallet_profiles')
TABLES = ('surveillance_scout',*DERIVED, 'surveillance_dirty_bins', "surveillance_case_versions", "surveillance_cases", "surveillance_information",
          "surveillance_trades", "surveillance_rules", "surveillance_markets",
          "surveillance_raw", "surveillance_coverage")


def raw_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


async def usage(store, settings):
    rows=await store.fetch("SELECT pg_database_size(current_database()) AS bytes")
    previous=await store.fetch("SELECT document,extract(epoch FROM now()-updated_at) AS age FROM surveillance_capacity WHERE id=1")
    credit=previous[0]['document'].get('reusable_database_bytes',0) if previous and previous[0]['age']<120 else 0
    physical=rows[0]['bytes']
    return dict(database_bytes=physical,database_used_bytes=max(0,physical-credit),
        reusable_database_bytes=credit,raw_bytes=await asyncio.to_thread(raw_bytes,settings.raw_dir))


def pressured(measured, settings, ratio=.8):
    return (measured.get('database_used_bytes',measured['database_bytes'])>=settings.database_max_bytes*ratio
            or measured['database_bytes']>=settings.database_max_bytes
            or measured['raw_bytes']>=settings.raw_max_bytes*ratio)


async def index_legacy_cases(c,limit=100):
    result=await c.execute("""UPDATE surveillance_cases SET document=document WHERE id IN(
        SELECT id FROM surveillance_cases WHERE NOT evidence_indexed ORDER BY id LIMIT %s)""",(limit,))
    remaining=await (await c.execute('SELECT EXISTS(SELECT 1 FROM surveillance_cases WHERE NOT evidence_indexed) AS pending')).fetchone()
    return dict(indexed=result.rowcount,pending=remaining['pending'])


class EvidenceIndexPending(Exception):
    pass


async def evict_batch(c, limit=500, changed=None):
    """Remove oldest receipts and every dependent record in the same transaction.

    Capacity eviction intentionally overrides case pins and manual evidence. Keep
    discovery cursors so a large closed catalog does not restart from page one.
    """
    changed=changed if changed is not None else set()
    rows = await (await c.execute("SELECT id,path,received_at FROM surveillance_raw ORDER BY received_at,id LIMIT %s",
                                  (limit,))).fetchall()
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    cutoff = max(r["received_at"] for r in rows)
    async with c.transaction():
        # Drop a whole case when any of its inputs expires; never leave a dossier
        # that appears replayable but silently refers to deleted evidence.
        # Index only legacy rows once; no case-by-case scans of the trade table.
        progress=await index_legacy_cases(c)
        if progress['pending']:raise EvidenceIndexPending('Complete legacy index before FIFO eviction')
        # Large overlap arrays make PostgreSQL underestimate sequential-scan CPU.
        # Both branches have dedicated indexes; keep the hint local to this query.
        previous_scan=(await (await c.execute("SHOW enable_seqscan")).fetchone())['enable_seqscan']
        previous_index=(await (await c.execute("SHOW enable_indexscan")).fetchone())['enable_indexscan']
        previous_jit=(await (await c.execute('SHOW jit')).fetchone())['jit']
        await c.execute('SET LOCAL jit=off')
        await c.execute('SET LOCAL enable_seqscan=off')
        await c.execute('SET LOCAL enable_indexscan=off')
        await c.execute("""CREATE TEMP TABLE capacity_cases ON COMMIT DROP AS
            SELECT id FROM surveillance_cases WHERE created_at<=%s
            UNION ALL SELECT id FROM surveillance_cases WHERE evidence_raw_ids && %s
            UNION ALL SELECT id FROM surveillance_cases WHERE evidence_observation_ids &&
                (SELECT array_agg(id) FROM surveillance_observations WHERE raw_ids && %s)""",(cutoff,ids,ids))
        removed=await c.execute("DELETE FROM surveillance_case_versions WHERE case_id IN(SELECT id FROM capacity_cases)")
        if removed.rowcount:changed.add("surveillance_case_versions")
        removed=await c.execute("DELETE FROM surveillance_cases WHERE id IN(SELECT id FROM capacity_cases)")
        if removed.rowcount:changed.add("surveillance_cases")
        for table in DERIVED:
            removed=await c.execute(sql.SQL('DELETE FROM {} WHERE raw_ids && %s').format(sql.Identifier(table)), (ids,))
            if removed.rowcount:changed.add(table)
        removed=await c.execute('DELETE FROM surveillance_markets WHERE metadata_raw_ids && %s',(ids,))
        if removed.rowcount:changed.add('surveillance_markets')
        await c.execute("SELECT set_config('enable_seqscan',%s,true)",(previous_scan,))
        await c.execute("SELECT set_config('enable_indexscan',%s,true)",(previous_index,))
        await c.execute("SELECT set_config('jit',%s,true)",(previous_jit,))
        await c.execute("DELETE FROM surveillance_dirty_bins WHERE bin_end<=%s", (cutoff,))
        await c.execute("DELETE FROM surveillance_wallet_profiles WHERE NOT EXISTS(SELECT 1 FROM surveillance_cases c WHERE c.id=case_id)")
        await c.execute('DELETE FROM surveillance_scout WHERE bucket<=%s', (cutoff,))
        for table in ("surveillance_information", "surveillance_trades", "surveillance_rules", "surveillance_markets"):
            removed=await c.execute(sql.SQL("DELETE FROM {} WHERE raw_id=ANY(%s)").format(sql.Identifier(table)), (ids,))
            if removed.rowcount:changed.add(table)
        removed=await c.execute("DELETE FROM surveillance_raw WHERE id=ANY(%s)", (ids,))
        if removed.rowcount:changed.add("surveillance_raw")
        await c.execute("DELETE FROM surveillance_coverage WHERE observed_at<=%s", (cutoff,))
        await c.execute("""UPDATE surveillance_jobs j SET enabled=false WHERE kind IN('details','trades','detect') AND NOT COALESCE((j.payload->>'manual')::boolean,false)
            AND NOT EXISTS(SELECT 1 FROM surveillance_markets m WHERE m.venue=j.venue
                AND m.id=j.payload->>'market_id')
            AND NOT EXISTS(SELECT 1 FROM surveillance_markets m WHERE m.venue=j.venue
                AND m.condition_id=j.payload->>'market_id')""")
        await c.execute("""INSERT INTO surveillance_coverage(venue,kind,document)
            VALUES('system','capacity_eviction_batch',%s)""",
            (Jsonb({"evicted_receipts": len(rows), "oldest_remaining_boundary": cutoff.isoformat(),
                    "dependent_evidence_expired": True}),))
    return len(rows)


async def sweep_orphans(c, root):
    """Clean unreferenced blobs, including files left by interrupted page writes."""
    removed = 0
    # Check references in bounded batches, rather than loading the whole archive.
    pending = []

    async def remove_unreferenced(paths):
        rows = await (await c.execute("SELECT DISTINCT path FROM surveillance_raw WHERE path=ANY(%s)",
                                     ([str(p.resolve()) for p in paths],))).fetchall()
        used = {r["path"] for r in rows}
        count = 0
        for p in paths:
            if str(p.resolve()) not in used:
                p.unlink()
                count += 1
        return count

    for p in Path(root).rglob("*"):
        if p.is_file():
            pending.append(p)
        if len(pending) == 256:
            removed += await remove_unreferenced(pending)
            pending.clear()
    return removed + await remove_unreferenced(pending)


async def free_space(c,details=False):
    """FSM/visibility-map estimate; index bytes stay conservatively allocated."""
    rows=await (await c.execute("""SELECT c.oid,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema() AND c.relkind='r'""")).fetchall()
    reusable=0;candidates=[]
    for row in rows:
        table_free=0
        # TOAST owns much of JSON evidence storage and has its own FSM.
        tables=await (await c.execute('SELECT oid FROM pg_class WHERE oid=%s OR oid=(SELECT reltoastrelid FROM pg_class WHERE oid=%s)',(row['oid'],row['oid']))).fetchall()
        for table in tables:
            result=await (await c.execute('SELECT approx_free_space FROM public.pgstattuple_approx(%s::oid::regclass)',(table['oid'],))).fetchone()
            table_free+=result['approx_free_space']
        reusable+=table_free
        if row['relname'] in TABLES:candidates.append((table_free,row['relname']))
    return (reusable,sorted(candidates,reverse=True)) if details else reusable


class ProgressConnection:
    def __init__(self,connection):self.connection=connection;self.phase='starting'
    def __getattr__(self,name):return getattr(self.connection,name)
    async def execute(self,query,params=()):
        template=query if isinstance(query,str) else query.as_string(self.connection)
        self.phase=' '.join(template.split())[:160]
        return await self.connection.execute(query,params)


async def enforce(store,settings,batch_limit=500,max_batches=1):
    before=await usage(store,settings)
    old=await store.fetch('SELECT document FROM surveillance_capacity WHERE id=1')
    previous=old[0]['document'] if old else {}
    needs_index=await store.fetch('SELECT EXISTS(SELECT 1 FROM surveillance_cases WHERE NOT evidence_indexed) AS pending')
    if not pressured(before,settings) and not previous.get('reclaiming') and not needs_index[0]['pending'] and not before.get('reusable_database_bytes'):
        return dict(before,blocked=False,evicted_receipts=0)
    started=time.monotonic();count=0;error=None;error_phase=None;indexed=0;measured=before;changed=set()
    compacted=None;next_compaction=previous.get('next_compaction_after',0);reclaiming=previous.get('reclaiming',False)
    async with await psycopg.AsyncConnection.connect(store.dsn,autocommit=True,row_factory=dict_row) as c:
        c=ProgressConnection(c)
        await c.execute("SELECT set_config('statement_timeout',%s,false)",(str(QUERY_TIMEOUT_MS),))
        await c.execute("SET lock_timeout='1s'")
        acquired=(await (await c.execute('SELECT pg_try_advisory_lock(%s) AS ok',(LOCK,))).fetchone())['ok']
        if not acquired:return dict(before,blocked=pressured(before,settings),busy=True,evicted_receipts=0)
        locked=True
        try:
            # Extension lives in public, never in an ephemeral test schema.
            await c.execute('CREATE EXTENSION IF NOT EXISTS pgstattuple WITH SCHEMA public')
            progress=await index_legacy_cases(c)
            indexed=progress['indexed']
            if progress['pending']:
                return dict(before,blocked=True,index_pending=True,indexed_cases=indexed,evicted_receipts=0)
            credit=await free_space(c)
            measured=dict(before,database_used_bytes=max(0,before['database_bytes']-credit),reusable_database_bytes=credit)
            reclaiming=pressured(measured,settings) or previous.get('reclaiming',False)
            for _ in range(max_batches if reclaiming else 0):
                if time.monotonic()-started>15:break
                n=await evict_batch(c,batch_limit,changed);count+=n
                if not n:break
            if count:
                await sweep_orphans(c,settings.raw_dir)
            # References/files are consistent now. Ordinary VACUUM and measurement
            # need no application-wide lock; API readers can proceed concurrently.
            await c.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));locked=False
            if count:
                # Ordinary VACUUM exposes reusable pages; no recurring full-table rewrites.
                for table in sorted(changed):
                    if time.monotonic()-started>20:break
                    await c.execute(sql.SQL('VACUUM (TRUNCATE FALSE) {}').format(sql.Identifier(table)))
            physical=(await (await c.execute('SELECT pg_database_size(current_database()) AS n')).fetchone())['n']
            credit,candidates=await free_space(c,details=True)
            # Rare physical-ceiling recovery, never a full rewrite of every table.
            # A failed rewrite is rolled back and not retried for an hour.
            if physical>=settings.database_max_bytes and time.time()>=next_compaction and candidates and candidates[0][0]>=128*1024**2:
                locked=(await (await c.execute('SELECT pg_try_advisory_lock(%s) AS ok',(LOCK,))).fetchone())['ok']
                if not locked:raise psycopg.errors.LockNotAvailable('Compaction deferred: evidence reader active')
                next_compaction=time.time()+3600
                await c.execute("SET statement_timeout='45s'")
                await c.execute(sql.SQL('VACUUM (FULL) {}').format(sql.Identifier(candidates[0][1])))
                compacted=candidates[0][1]
                await c.execute("SELECT set_config('statement_timeout',%s,false)",(str(QUERY_TIMEOUT_MS),))
                physical=(await (await c.execute('SELECT pg_database_size(current_database()) AS n')).fetchone())['n']
                credit=await free_space(c)
            measured=dict(database_bytes=physical,database_used_bytes=max(0,physical-credit),reusable_database_bytes=credit,
                raw_bytes=await asyncio.to_thread(raw_bytes,settings.raw_dir))
        except (psycopg.errors.QueryCanceled,psycopg.errors.LockNotAvailable,psycopg.errors.InsufficientPrivilege) as exc:
            error=type(exc).__name__;error_phase=c.phase
            # An interrupted batch rolls back. No unbounded automatic retry loop.
        finally:
            if locked:await c.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
        result=dict(measured,before=before,blocked=pressured(measured,settings),evicted_receipts=count,indexed_cases=indexed,
            reclaiming=reclaiming and pressured(measured,settings,.6),error=error,error_phase=error_phase,compacted_table=compacted,next_compaction_after=next_compaction,elapsed_seconds=time.monotonic()-started,
            mode='indexed FIFO; reusable heap pages counted; bounded ordinary vacuum',
            database_max_bytes=settings.database_max_bytes,raw_max_bytes=settings.raw_max_bytes)
        await c.execute("""INSERT INTO surveillance_capacity(id,document) VALUES(1,%s)
            ON CONFLICT(id) DO UPDATE SET document=EXCLUDED.document,updated_at=now()""",(Jsonb(result),))
        await c.execute("INSERT INTO surveillance_coverage(venue,kind,document) VALUES('system','capacity_eviction',%s)",(Jsonb(result),))
        return result


class CapacityGuard:
    def __init__(self,store,settings):
        self.store,self.settings=store,settings
        self.checked_at=float('-inf');self.result={'blocked':False}

    async def check(self):
        interval=1 if self.result.get('index_pending') else 300 if self.result.get('error') else 60
        if time.monotonic()-self.checked_at>=interval:
            self.result=await enforce(self.store,self.settings)
            self.checked_at=time.monotonic()
        return not self.result['blocked']
