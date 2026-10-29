import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from psycopg.types.json import Jsonb

from .cases import completeness, report
from .config import Settings
from .investigations import replay
from .maintenance import reset_test_dataset
from .normalization import timestamp
from .storage import Store, RawArchive
from .worker import Worker


async def execute(args):
    settings = Settings.env()
    store = Store(settings.database_url)
    await store.initialize()
    if args.command == "init":
        print("Schema ready")
    elif args.command == "worker":
        await Worker(settings).run(once=args.once)
    elif args.command == "reset-test-data":
        if not args.confirm_test_data:
            raise ValueError("reset-test-data requires --confirm-test-data")
        print(json.dumps(await reset_test_dataset(store, settings.raw_dir)))
    elif args.command == "backfill":
        since = int(datetime.fromisoformat(timestamp(args.since)).timestamp())
        if since > datetime.now(timezone.utc).timestamp():
            raise ValueError("since must not be in the future")
        detail = f"details:manual:{args.venue}:{args.market}:{since}"
        key = f"backfill:{args.venue}:{args.market}:{since}"
        payload = {"market_id": args.market, "catalog_id": args.market, "manual": True}
        # No second archive writer: the single worker performs all network intake.
        # Insert checkpoint atomically with the job so a claim cannot race since.
        async with store.connection() as c:
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,'details',%s,%s)
                ON CONFLICT DO NOTHING""", (detail,args.venue,Jsonb(payload)))
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload,checkpoint) VALUES(%s,'backfill',%s,%s,%s)
                ON CONFLICT DO NOTHING""", (key,args.venue,Jsonb(payload),Jsonb({"since":since})))
        print(json.dumps({"detail_job": detail, "trade_job": key,
                          "historical_received_at": "actual collection time; never backdated"}))
    elif args.command == 'review-event':
        from .event_review import enqueue_review
        rows = await store.fetch('SELECT venue,document FROM surveillance_information WHERE id=%s', (args.information,))
        if not rows or not rows[0]['document'].get('publication_time_verified'):
            raise ValueError('Verified information record required')
        async with store.connection() as c:
            key = await enqueue_review(c,args.information,rows[0]['venue'],datetime.now(timezone.utc).isoformat(),args.contract_only)
        print(json.dumps({'job_id': key}))
    elif args.command == 'aggregate-market':
        from datetime import timedelta
        start,end = (datetime.fromisoformat(timestamp(v)) for v in (args.start,args.end))
        if not start<end or end-start>timedelta(days=7):
            raise ValueError('Select at most seven days')
        async with store.connection() as c:
            rows = await (await c.execute("""SELECT DISTINCT venue,market_id,
                COALESCE(NULLIF(document->>'token_id',''),outcome) AS outcome,
                to_timestamp((floor(extract(epoch FROM event_time)/300)+1)*300) AS bin_end
                FROM surveillance_trades WHERE venue=%s AND market_id=%s AND event_time>=%s AND event_time<%s
                LIMIT 20001""", (args.venue,args.market,start,end))).fetchall()
            if len(rows)>20000:
                raise ValueError('Aggregate rebuild exceeds 20000 bins; shorten interval')
            async with c.cursor() as cursor:
                await cursor.executemany('INSERT INTO surveillance_dirty_bins VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                    [(r['venue'],r['market_id'],r['outcome'],r['bin_end']) for r in rows])
        print(json.dumps({'dirty_bins':len(rows),'known_at':'actual worker materialization; never backdated'}))
    elif args.command == "coverage":
        print(json.dumps(await completeness(store), default=str, indent=2))
    elif args.command == "replay":
        result = await replay(store, args.venue, args.market, timestamp(args.as_of), max_trades=settings.replay_max_trades)
        print(json.dumps(result, indent=2))
    elif args.command == "report":
        rows = await store.fetch("SELECT document FROM surveillance_cases WHERE id=%s", (args.case,))
        if not rows:
            raise ValueError("Case not found")
        print(report(rows[0]["document"]))
    elif args.command == "verify":
        verified = 0
        async with store.connection() as c:
            async with c.cursor(name="verify") as cursor:
                cursor.itersize = 256
                await cursor.execute("SELECT * FROM surveillance_raw ORDER BY received_at")
                async for r in cursor:
                    RawArchive.read(r)
                    verified += 1
        print(json.dumps({"verified_responses": verified}))


def main():
    parser = argparse.ArgumentParser(description="Independent read-only market surveillance")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "coverage", "verify"):
        commands.add_parser(name)
    reset = commands.add_parser("reset-test-data")
    reset.add_argument("--confirm-test-data", action="store_true")
    backfill = commands.add_parser("backfill")
    backfill.add_argument("--venue", choices=("polymarket", "kalshi"), required=True)
    backfill.add_argument("--market", required=True, help="Polymarket numeric catalog ID or Kalshi ticker")
    backfill.add_argument("--since", required=True, help="Timezone-aware lower boundary; market cursor walk may be long")
    rebuild = commands.add_parser('aggregate-market')
    rebuild.add_argument('--venue',choices=('polymarket','kalshi'),required=True)
    rebuild.add_argument('--market',required=True)
    rebuild.add_argument('--start',required=True)
    rebuild.add_argument('--end',required=True)
    event = commands.add_parser('review-event')
    event.add_argument('--information',required=True)
    event.add_argument('--contract-only',action='store_true')
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--venue", choices=("polymarket", "kalshi"), required=True)
    replay_parser.add_argument("--market", required=True)
    replay_parser.add_argument("--as-of", required=True)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("--case", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
