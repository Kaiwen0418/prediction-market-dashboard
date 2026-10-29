import json


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
    return dict(catalog=counts, detailed_rules=rules, jobs=jobs, recent_coverage=recent, raw=raw,
        accuracy="REST sampled; exact executable-depth history unavailable",
        limitations=["Active non-combination discovery across topics; closed/history and MVE combinations require explicit backfill",
                     "Catalog is a lightweight index; rule details exist only for selected/manual contracts",
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
