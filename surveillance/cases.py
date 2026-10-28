import json


async def completeness(store):
    counts = await store.fetch("""SELECT venue,count(*) AS contracts,max(observed_at) AS last_observed_at
        FROM surveillance_markets GROUP BY venue""")
    jobs = await store.fetch("""SELECT id,kind,venue,enabled,due_at,lease_until,failures,last_error,checkpoint,updated_at
        FROM surveillance_jobs ORDER BY venue,kind,id""")
    recent = await store.fetch("SELECT * FROM surveillance_coverage ORDER BY id DESC LIMIT 200")
    raw = await store.fetch("SELECT venue,count(*) AS responses,max(received_at) AS latest_response FROM surveillance_raw GROUP BY venue")
    return dict(catalog=counts, jobs=jobs, recent_coverage=recent, raw=raw,
        accuracy="REST sampled; exact executable-depth history unavailable",
        limitations=["No whole-platform coverage percentage: upstream denominator unknown",
                     "News and sports feeds require configured sources; manual evidence intake available",
                     "Raw archive integrity can be checked with CLI verify; this report is not an integrity proof"])


def report(document):
    return "\n".join([f"# Surveillance case {document['id']}", "",
        f"Venue: {document['venue']} | Contract: {document['market_id']}",
        f"Anomaly: {document['anomaly_score']} | Evidence: {document['evidence_quality']} | Priority: {document['investigation_priority']}",
        "", "Scores are triage measures, not probabilities of insider trading.", "",
        "The complete machine-readable evidence dossier follows. Unverified explanations remain open.", "",
        "```json", json.dumps(document, indent=2, ensure_ascii=False), "```", ""])
