import argparse
import asyncio
import json
import logging

from .cases import completeness, report
from .config import Settings
from .investigations import replay
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
