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
TABLES = ("surveillance_case_versions", "surveillance_cases", "surveillance_information",
          "surveillance_trades", "surveillance_rules", "surveillance_markets",
          "surveillance_raw", "surveillance_coverage")


def raw_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


async def usage(store, settings):
    rows = await store.fetch("SELECT pg_database_size(current_database()) AS bytes")
    return {"database_bytes": rows[0]["bytes"],
            "raw_bytes": await asyncio.to_thread(raw_bytes, settings.raw_dir)}


def pressured(measured, settings, ratio=.8):
    return (measured["database_bytes"] >= settings.database_max_bytes * ratio
            or measured["raw_bytes"] >= settings.raw_max_bytes * ratio)


async def evict_batch(c, limit=10000):
    """Remove oldest receipts and every dependent record in the same transaction.

    Capacity eviction intentionally overrides case pins and manual evidence. Keep
    discovery cursors so a large closed catalog does not restart from page one.
    """
    rows = await (await c.execute("SELECT id,path,received_at FROM surveillance_raw ORDER BY received_at,id LIMIT %s",
                                  (limit,))).fetchall()
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    cutoff = max(r["received_at"] for r in rows)
    async with c.transaction():
        # Drop a whole case when any of its inputs expires; never leave a dossier
        # that appears replayable but silently refers to deleted evidence.
        await c.execute("""CREATE TEMP TABLE capacity_cases ON COMMIT DROP AS
            SELECT id FROM surveillance_cases c WHERE created_at<=%s
            OR document->>'rules_raw_id'=ANY(%s)
            OR COALESCE(document->'replay_raw_ids','[]') ?| %s
            OR EXISTS (SELECT 1 FROM jsonb_path_query(document,'$.**.raw_id') v
                       WHERE v#>>'{}'=ANY(%s))
            OR EXISTS (SELECT 1 FROM surveillance_trades t WHERE t.raw_id=ANY(%s)
                       AND c.document->'replay_input_ids' ? t.id)""", (cutoff, ids, ids, ids, ids))
        await c.execute("DELETE FROM surveillance_case_versions WHERE case_id IN(SELECT id FROM capacity_cases)")
        await c.execute("DELETE FROM surveillance_cases WHERE id IN(SELECT id FROM capacity_cases)")
        for table in ("surveillance_information", "surveillance_trades", "surveillance_rules", "surveillance_markets"):
            await c.execute(sql.SQL("DELETE FROM {} WHERE raw_id=ANY(%s)").format(sql.Identifier(table)), (ids,))
        await c.execute("DELETE FROM surveillance_raw WHERE id=ANY(%s)", (ids,))
        await c.execute("DELETE FROM surveillance_coverage WHERE observed_at<=%s", (cutoff,))
        await c.execute("""UPDATE surveillance_jobs j SET enabled=false WHERE kind IN('trades','detect')
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


async def enforce(store, settings, batch_limit=10000, max_batches=8):
    before = await usage(store, settings)
    if not pressured(before, settings):
        return {**before, "blocked": False, "evicted_receipts": 0}
    # All Store transactions hold a shared lock. This dedicated session holds the
    # exclusive lock across deletion, raw cleanup and VACUUM FULL. API writes and
    # collection cannot reintroduce references while their files are being removed.
    async with await psycopg.AsyncConnection.connect(store.dsn, autocommit=True, row_factory=dict_row) as c:
        await c.execute("SELECT pg_advisory_lock(%s)", (LOCK,))
        try:
            count = 0
            for _ in range(max_batches):
                n = await evict_batch(c, batch_limit)
                count += n
                await sweep_orphans(c, settings.raw_dir)
                # DELETE alone does not reduce physical relation files. Bound each
                # pass and compact before admitting any further collection jobs.
                for table in TABLES:
                    await c.execute(sql.SQL("VACUUM (FULL, ANALYZE) {}").format(sql.Identifier(table)))
                measured = {"database_bytes": (await (await c.execute(
                    "SELECT pg_database_size(current_database()) AS n")).fetchone())["n"],
                    "raw_bytes": await asyncio.to_thread(raw_bytes, settings.raw_dir)}
                if not pressured(measured, settings, .6) or not n:
                    break
            result = {**measured, "before": before, "blocked": pressured(measured, settings),
                      "evicted_receipts": count, "mode": "oldest-receipts-first; dependent cases expire",
                      "database_max_bytes": settings.database_max_bytes, "raw_max_bytes": settings.raw_max_bytes}
            await c.execute("""INSERT INTO surveillance_coverage(venue,kind,document)
                VALUES('system','capacity_eviction',%s)""", (Jsonb(result),))
            await c.execute("""INSERT INTO surveillance_capacity(id,document) VALUES(1,%s)
                ON CONFLICT(id) DO UPDATE SET document=EXCLUDED.document,updated_at=now()""", (Jsonb(result),))
            return result
        finally:
            await c.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))


class CapacityGuard:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.checked_at = float('-inf')
        self.result = {"blocked": False}

    async def check(self):
        if time.monotonic() - self.checked_at >= 60:
            self.result = await enforce(self.store, self.settings)
            self.checked_at = time.monotonic()
        return not self.result["blocked"]
