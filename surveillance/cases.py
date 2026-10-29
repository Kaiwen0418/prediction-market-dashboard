import json
from datetime import datetime,timezone


async def completeness(store):
    counts = await store.fetch("""SELECT venue,count(*) AS contracts,max(observed_at) AS last_observed_at,
        count(*) FILTER(WHERE document->>'settled'='true') AS settled,
        count(*) FILTER(WHERE document->>'is_combo'='true') AS combinations,
        count(*) FILTER(WHERE document->>'tradable'='true') AS source_tradable
        FROM surveillance_markets GROUP BY venue""")
    jobs = await store.fetch("""SELECT id,kind,venue,enabled,due_at,lease_until,failures,last_error,checkpoint,updated_at
        FROM surveillance_jobs ORDER BY venue,kind,id""")
    recent = await store.fetch("SELECT * FROM surveillance_coverage ORDER BY id DESC LIMIT 200")
    raw = await store.fetch("SELECT venue,count(*) AS responses,max(received_at) AS latest_response FROM surveillance_raw GROUP BY venue")
    rules = await store.fetch("SELECT venue,count(*) AS versions,count(DISTINCT market_id) AS detailed_contracts FROM surveillance_rules GROUP BY venue")
    aggregate_state = await store.fetch('SELECT count(*) AS versions,max(known_at) AS latest_known_at FROM surveillance_aggregates')
    pending_bins = await store.fetch('SELECT count(*) AS n FROM surveillance_dirty_bins')
    profiles = await store.fetch("SELECT document->>'status' AS status,count(*) AS n FROM surveillance_wallet_profiles GROUP BY document->>'status'")
    wide = await store.fetch("""SELECT venue,count(DISTINCT market_id) AS observed_markets_15m,
        sum(fills) AS observed_fills_15m,max(known_at) AS latest_receipt,
        max(last_event) AS latest_event FROM surveillance_scout WHERE bucket>=now()-interval '15 minutes' GROUP BY venue""")
    selection = await store.fetch("""SELECT venue,document FROM surveillance_coverage c WHERE kind='budget'
        AND id=(SELECT max(id) FROM surveillance_coverage x WHERE x.kind='budget' AND x.venue=c.venue)""")
    freshness=[]
    for job in jobs:
        if job['kind']!='wide' or not job['enabled']:continue
        cp=job['checkpoint'];head=cp.get('feed_head_at');received=cp.get('last_page_received_at')
        head_age=(datetime.now(timezone.utc)-datetime.fromisoformat(head)).total_seconds() if head else None
        receipt_age=(datetime.now(timezone.utc)-datetime.fromisoformat(received)).total_seconds() if received else None
        freshness.append(dict(venue=job['venue'],head_event_age_seconds=head_age,receipt_age_seconds=receipt_age,
            cursor_pending=bool(cp.get('cursor')),http_cache_control=cp.get('http_cache_control'),http_age=cp.get('http_age'),
            observation='unknown' if head_age is None else ('stale_head_observation' if head_age>120 else 'recent_head_observation'),
            meaning='Observed API head age; not a guarantee of upstream completeness or sub-minute detection'))
    return dict(wide_freshness=freshness,wide_discovery=wide,selection=selection,aggregates=aggregate_state[0],pending_aggregate_bins=pending_bins[0]['n'],wallet_profiles=profiles,catalog=counts, detailed_rules=rules, jobs=jobs, recent_coverage=recent, raw=raw,
        accuracy="REST sampled; exact executable-depth history unavailable",
        limitations=["Catalog targets active non-combination contracts; global trades can include other contracts without deep eligibility",
                     "Catalog is a lightweight index; rule details exist only for selected/manual contracts",
                     "Global feeds are paginated observations; pending cursor is not caught-up coverage",
                     "Deep selection uses per-event caps, themed quotas and low-activity exploration",
                     "Wide overlap is finite; older upstream indexing delays may still be missed",
                     "No whole-platform coverage percentage: upstream denominator unknown",
                     "News and sports feeds require configured sources; manual evidence intake available",
                     "Capacity eviction expires oldest receipts and dependent cases; catalog is a rolling subset",
                     "Raw archive integrity can be checked with CLI verify; this report is not an integrity proof"])


def report(document):
    return "\n".join([f"# Surveillance case {document['id']}", "",
        f"Venue: {document['venue']} | Contract: {document['market_id']}",
        f"Anomaly: {document['anomaly_score']} | Evidence: {document['evidence_quality']} | Priority: {document['investigation_priority']}",
        "", "Scores are triage measures, not probabilities of insider trading.", "",
        "The complete machine-readable evidence dossier follows. Unverified explanations remain open.", "",
        "```json", json.dumps(document, indent=2, ensure_ascii=False), "```", ""])
