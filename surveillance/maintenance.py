"""Bounded test-data retention. Run within the single collection worker."""
from datetime import datetime, timedelta, timezone
from pathlib import Path


async def prune(store, days=7, limit=50000):
    if days < 1 or limit < 1:
        raise ValueError("Positive retention and batch limit required")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Keep an extra day of baseline inputs for every retained case.
    evidence_cutoff = cutoff - timedelta(days=1)
    async with store.connection(exclusive=True) as c:
        await c.execute("SELECT pg_advisory_xact_lock(81724002)")
        expired = await (await c.execute("SELECT id FROM surveillance_cases WHERE created_at<%s LIMIT %s",
                                        (cutoff, limit))).fetchall()
        ids = [r["id"] for r in expired]
        await c.execute("DELETE FROM surveillance_case_versions WHERE case_id=ANY(%s)", (ids,))
        await c.execute("DELETE FROM surveillance_cases WHERE id=ANY(%s)", (ids,))
        # Derived summaries are disposable under the same seven-day/capacity policy.
        for table in ('surveillance_aggregates','surveillance_walks','surveillance_wallet_profiles','surveillance_wallet_daily','surveillance_wallet_events'):
            from psycopg import sql
            await c.execute(sql.SQL('DELETE FROM {} WHERE ctid IN (SELECT ctid FROM {} WHERE {}<%s LIMIT %s)').format(
                sql.Identifier(table),sql.Identifier(table),sql.Identifier('admitted_at' if table=='surveillance_wallet_profiles' else 'known_at')), (cutoff,limit))
        await c.execute('''DELETE FROM surveillance_observations o WHERE known_at<%s AND NOT EXISTS(
            SELECT 1 FROM surveillance_cases c WHERE c.document->'observation_ids' ? o.id)''',(cutoff,))
        await c.execute("DELETE FROM surveillance_wallet_daily WHERE day<(now() AT TIME ZONE 'UTC')::date-6")
        await c.execute('DELETE FROM surveillance_wallet_profiles WHERE NOT EXISTS(SELECT 1 FROM surveillance_cases c WHERE c.id=case_id)')
        await c.execute('DELETE FROM surveillance_dirty_bins WHERE bin_end<%s', (evidence_cutoff,))
        await c.execute("DELETE FROM surveillance_scout WHERE bucket<now()-interval '30 minutes'")
        trades = await c.execute("""DELETE FROM surveillance_trades WHERE ctid IN (
            SELECT t.ctid FROM surveillance_trades t WHERE event_time<%s AND received_at<%s
            AND NOT EXISTS(SELECT 1 FROM surveillance_cases c WHERE c.evidence_raw_ids @> ARRAY[t.raw_id]) LIMIT %s)""",
            (evidence_cutoff, evidence_cutoff, limit))
        coverage = await c.execute("""DELETE FROM surveillance_coverage WHERE id IN (
            SELECT id FROM surveillance_coverage WHERE observed_at<%s LIMIT %s)""", (cutoff, limit))
        jobs = await c.execute("""DELETE FROM surveillance_jobs WHERE id IN (
            SELECT id FROM surveillance_jobs WHERE NOT enabled AND kind IN ('details','trades','detect','backfill','event_review','wallet','scout_detect')
            AND updated_at<%s AND (lease_until IS NULL OR lease_until<now()) LIMIT %s)""", (cutoff, limit))
        # A current rule snapshot and any case-pinned rule evidence survive expiry.
        rules = await c.execute("""DELETE FROM surveillance_rules r WHERE r.ctid IN (
            SELECT old.ctid FROM surveillance_rules old WHERE old.observed_at<%s
            AND (EXISTS (SELECT 1 FROM surveillance_rules newer WHERE newer.venue=old.venue
                AND newer.market_id=old.market_id AND newer.observed_at>old.observed_at)
                OR (NOT EXISTS(SELECT 1 FROM surveillance_markets m WHERE m.venue=old.venue AND m.id=old.market_id)
                    AND NOT EXISTS(SELECT 1 FROM surveillance_markets m WHERE m.venue=old.venue AND m.condition_id=old.market_id)))
            AND NOT EXISTS (SELECT 1 FROM surveillance_cases c WHERE c.document->>'rules_raw_id'=old.raw_id)
            LIMIT %s)""", (evidence_cutoff, limit))
        deleted = await (await c.execute("""WITH refs AS (
            SELECT unnest(raw_ids) AS id FROM surveillance_observations
            UNION SELECT unnest(raw_ids) FROM surveillance_wallet_daily
            UNION SELECT unnest(raw_ids) FROM surveillance_wallet_events
            UNION SELECT unnest(metadata_raw_ids) FROM surveillance_markets
            UNION SELECT unnest(raw_ids) FROM surveillance_aggregates
            UNION SELECT unnest(raw_ids) FROM surveillance_walks
            UNION SELECT unnest(raw_ids) FROM surveillance_wallet_profiles
            UNION SELECT raw_id FROM surveillance_markets UNION SELECT raw_id FROM surveillance_rules
            UNION SELECT raw_id FROM surveillance_trades UNION SELECT raw_id FROM surveillance_information
            UNION SELECT unnest(evidence_raw_ids) FROM surveillance_cases
        ), expired AS (
            SELECT id FROM surveillance_raw r WHERE received_at<%s AND NOT EXISTS(SELECT 1 FROM refs WHERE refs.id=r.id)
            LIMIT %s
        ) DELETE FROM surveillance_raw WHERE id IN(SELECT id FROM expired) RETURNING path""",
            (evidence_cutoff, min(limit, 10000)))).fetchall()
        paths = sorted({r["path"] for r in deleted})
        used = await (await c.execute("SELECT DISTINCT path FROM surveillance_raw WHERE path=ANY(%s)", (paths,))).fetchall()
        keep = {r["path"] for r in used}
        result = dict(expired_cases=len(ids), expired_trades=trades.rowcount, expired_coverage=coverage.rowcount,
                      expired_rule_versions=rules.rowcount, expired_paused_jobs=jobs.rowcount, expired_raw_receipts=len(deleted), removed_blobs=0,
                      retention_days=days, baseline_cushion_days=1)
        # Commit references before unlink; the session lock remains held until close.
        await c.commit()
        # Keep the exclusive evidence lock through filesystem removal as well.
        for path in paths:
            if path not in keep:
                Path(path).unlink(missing_ok=True)
                result["removed_blobs"] += 1
    return result


async def reset_test_dataset(store, raw_dir):
    """Discard this module's disposable dataset only; never drop the database."""
    import asyncio
    import shutil
    from psycopg import sql
    from .capacity import TABLES
    root = Path(raw_dir).resolve()
    if root == Path(root.anchor) or len(root.parts) < 3:
        raise ValueError("Refusing a non-dedicated raw archive directory")
    async with store.connection(exclusive=True) as c:
        tables = (*TABLES, "surveillance_jobs", "surveillance_capacity")
        await c.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
            sql.SQL(",").join(sql.Identifier(t) for t in tables)))
        await c.commit()
        if root.exists():
            await asyncio.to_thread(shutil.rmtree, root)
        root.mkdir(parents=True, exist_ok=True)
    await store.coverage("system", "test_dataset_reset", {"reason": "lightweight active-catalog deployment",
                         "historical_test_data_discarded": True})
    return {"reset": True, "scope": "surveillance tables and configured raw directory only"}
