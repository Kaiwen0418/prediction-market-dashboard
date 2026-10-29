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
        trades = await c.execute("""DELETE FROM surveillance_trades WHERE ctid IN (
            SELECT t.ctid FROM surveillance_trades t WHERE event_time<%s AND received_at<%s
            AND NOT EXISTS(SELECT 1 FROM surveillance_cases c WHERE c.venue=t.venue AND c.market_id=t.market_id
                AND c.document->'replay_input_ids' ? t.id) LIMIT %s)""",
            (evidence_cutoff, evidence_cutoff, limit))
        coverage = await c.execute("""DELETE FROM surveillance_coverage WHERE id IN (
            SELECT id FROM surveillance_coverage WHERE observed_at<%s LIMIT %s)""", (cutoff, limit))
        jobs = await c.execute("""DELETE FROM surveillance_jobs WHERE id IN (
            SELECT id FROM surveillance_jobs WHERE NOT enabled AND kind IN ('trades','detect')
            AND updated_at<%s AND (lease_until IS NULL OR lease_until<now()) LIMIT %s)""", (cutoff, limit))
        # A current rule snapshot and any case-pinned rule evidence survive expiry.
        rules = await c.execute("""DELETE FROM surveillance_rules r WHERE r.ctid IN (
            SELECT old.ctid FROM surveillance_rules old WHERE old.observed_at<%s
            AND EXISTS (SELECT 1 FROM surveillance_rules newer WHERE newer.venue=old.venue
                AND newer.market_id=old.market_id AND newer.observed_at>old.observed_at)
            AND NOT EXISTS (SELECT 1 FROM surveillance_cases c WHERE c.document->>'rules_raw_id'=old.raw_id)
            LIMIT %s)""", (evidence_cutoff, limit))
        deleted = await (await c.execute("""WITH refs AS (
            SELECT raw_id AS id FROM surveillance_markets UNION SELECT raw_id FROM surveillance_rules
            UNION SELECT raw_id FROM surveillance_trades UNION SELECT raw_id FROM surveillance_information
            UNION SELECT document->>'rules_raw_id' FROM surveillance_cases
            UNION SELECT jsonb_array_elements_text(COALESCE(document->'replay_raw_ids','[]')) FROM surveillance_cases
            UNION SELECT value#>>'{}' FROM surveillance_cases,
                LATERAL jsonb_path_query(document,'$.**.raw_id') AS value
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
