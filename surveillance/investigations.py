from datetime import datetime, timedelta

from .detectors import evaluate, VERSION
from .discovery import tier
from .normalization import digest
from .money import cash
from .observation import intervals


ALTERNATIVES = ["Arbitrage or market making", "Thin order book", "Differences in settlement rules",
                "Earlier public disclosure or media syndication delay", "Live broadcast / score feed delay",
                "Missing or delayed trades and clock uncertainty"]


class ReplayCapacityError(ValueError):
    pass


async def replay(store,venue,market_id,as_of,persist=True,max_trades=50000,knowledge_cutoff=None):
    # Hold the evidence lock across all reads and case pins; FIFO cannot interleave.
    from psycopg.types.json import Jsonb
    class View:
        def __init__(self,c):self.c=c
        async def fetch(self,sql,params=()):return await (await self.c.execute(sql,params)).fetchall()
    async with store.connection() as c:
        docs=await _replay(View(c),venue,market_id,as_of,max_trades,knowledge_cutoff)
        if persist:
            for doc in docs:
                await c.execute("INSERT INTO surveillance_cases(id,venue,market_id,status,document) VALUES(%s,%s,%s,'candidate',%s) ON CONFLICT DO NOTHING",(doc['id'],venue,market_id,Jsonb(doc)))
                await c.execute('INSERT INTO surveillance_case_versions(case_id,version,document) VALUES(%s,1,%s) ON CONFLICT DO NOTHING',(doc['id'],Jsonb(doc)))
        return docs


async def _replay(store,venue,market_id,as_of,max_trades,knowledge_cutoff):
    cutoff = datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None:
        raise ValueError("as_of must include timezone")
    known=datetime.fromisoformat(knowledge_cutoff or as_of)
    if known.tzinfo is None or cutoff>known:raise ValueError('Event cutoff must not exceed knowledge cutoff')
    observations,observation_ids=await intervals(store,venue,market_id,cutoff-timedelta(hours=13),cutoff,known)
    rows = await store.fetch("""SELECT document,raw_id,id FROM surveillance_trades WHERE venue=%s AND market_id=%s
        AND event_time<=%s AND received_at<=%s AND event_time>%s ORDER BY event_time,id LIMIT %s""",
        (venue, market_id, cutoff, known, cutoff - timedelta(hours=13), max_trades + 1))
    if len(rows) > max_trades:
        raise ReplayCapacityError(f"Replay exceeds {max_trades} observed trades; no partial score produced")
    # Pin metadata to its observation time; current rules must not leak into replay.
    rules = await store.fetch("""SELECT * FROM surveillance_rules WHERE venue=%s AND market_id=%s AND observed_at<=%s
        ORDER BY observed_at DESC LIMIT 1""", (venue, market_id, known))
    catalog = await store.fetch("""SELECT document FROM surveillance_markets WHERE venue=%s AND (id=%s OR condition_id=%s)
        AND observed_at<=%s LIMIT 1""", (venue, market_id, market_id, known))
    if not rules and catalog:
        rules = await store.fetch("""SELECT * FROM surveillance_rules WHERE venue=%s AND market_id=%s AND observed_at<=%s
            ORDER BY observed_at DESC LIMIT 1""", (venue, catalog[0]["document"]["id"], known))
    info = await store.fetch("""SELECT document FROM surveillance_information WHERE venue=%s AND market_id=%s
        AND first_seen_at<=%s ORDER BY first_seen_at,id""", (venue, market_id, known))
    cases = []
    # Token/outcome grouping prevents interpreting a buy of NO as a buy of YES.
    groups = {}
    for row in rows:
        t = dict(row["document"], id=row["id"], raw_id=row["raw_id"])
        groups.setdefault(t["token_id"] or t["outcome"], []).append(t)
    for outcome_key, trades in groups.items():
        for signal in evaluate(trades,cutoff.isoformat(),knowledge_cutoff=known.isoformat(),coverage=observations):
            if signal["anomaly_score"] < 35:
                continue
            signal_ids = set(signal["trade_ids"])
            refs = [dict(trade_id=r["id"], raw_id=r["raw_id"]) for r in rows if r["id"] in signal_ids]
            quality=max(0,15+(15 if rules else 0)+(20 if signal['current_fully_observed'] else 0)+
                round(20*signal['baseline_observed_windows']/12)-min(20,int(signal['detected_with_delay_seconds']/30)))
            priority_tier = tier(rules[0]["document"]) if rules else 2
            wallet_observations = []
            if venue == "polymarket":
                wallets = {}
                for t in trades:
                    if t["wallet"] and t["id"] in signal_ids:
                        wallets.setdefault(t["wallet"], []).append(t)
                for wallet, activity in sorted(wallets.items()):
                    wallet_observations.append(dict(wallet=wallet, trade_count=len(activity),
                        volume_shares=sum(float(t["quantity"]) for t in activity),
                        cash_usd=sum(float(cash(t) or 0) for t in activity),
                        earliest_in_anomaly_window=min(t["event_time"] for t in activity),
                        scope="Observed anomaly window only; not wallet creation or full history"))
            document = dict(id=digest([VERSION, venue, market_id, outcome_key, signal["window_seconds"],cutoff.isoformat(),signal["trade_ids"]]),
                venue=venue,market_id=market_id,outcome_key=outcome_key,signal=signal,
                kind='trade_anomaly',knowledge_cutoff=known.isoformat(),observation_ids=observation_ids,
                analysis_mode='as_of_replay',
                quality_components=dict(current_observed=signal['current_fully_observed'],baseline_observed_windows=signal['baseline_observed_windows'],rules_available=bool(rules),delay_seconds=signal['detected_with_delay_seconds']),
                anomaly_score=signal["anomaly_score"], evidence_quality=quality,
                investigation_priority=round(signal["anomaly_score"] * (0.5 + quality / 200) * (1 - priority_tier * 0.1), 2),
                score_meaning="Triage scores; none is a probability of insider trading",
                rules=rules[0]["document"]["rules"] if rules else None, rules_hash=rules[0]["hash"] if rules else None,
                rules_raw_id=rules[0]["raw_id"] if rules else None,
                trade_references=refs, replay_input_ids=[t["id"] for t in trades],
                replay_raw_ids=sorted({t["raw_id"] for t in trades if t.get("raw_id")}),
                public_timeline=[r["document"] for r in info], supporting_evidence=[signal],
                counter_evidence=[], alternative_explanations=[dict(explanation=x, status="unverified") for x in ALTERNATIVES],
                open_questions=["Verify earliest public availability independently of our first_seen_at",
                                "Check collection gaps before interpreting the anomaly"],
                orderbook_coverage="not_collected; historical sweeps cannot be inferred",
                wallet_observations=wallet_observations, investigation_timeline=[],
                wallet_capability="public proxy wallet only" if venue == "polymarket" else "unavailable", status="candidate")
            cases.append(document)
    return cases
