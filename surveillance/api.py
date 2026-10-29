from contextlib import asynccontextmanager
import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl
from psycopg.types.json import Jsonb

from .cases import completeness, report
from .capacity import usage, pressured
from .config import Settings
from .investigations import replay, ReplayCapacityError
from .normalization import canonical, digest, now, timestamp
from .storage import Store, RawArchive


class ReplayRequest(BaseModel):
    venue: Literal["polymarket", "kalshi"]
    market_id: str = Field(min_length=1, max_length=256)
    as_of: str


class Review(BaseModel):
    status: Literal["investigating", "reviewed", "dismissed", "closed"]
    note: str = Field(min_length=1, max_length=10000)
    reviewer: str = Field(min_length=1, max_length=200)


class Information(BaseModel):
    venue: Literal["polymarket", "kalshi"]
    market_id: str = Field(min_length=1, max_length=256)
    source_url: HttpUrl
    title: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=100000)
    published_at: str | None = None
    event_time: str | None = None
    publication_time_verified: bool = False
    verification_note: str = Field(default="", max_length=10000)


def create_app(settings=None):
    settings = settings or Settings.env()
    store = Store(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        await store.initialize()
        yield

    async def authorized(request: Request, authorization: str = Header(default="")):
        if not settings.api_token:
            raise HTTPException(503, "Configure SURVEILLANCE_API_TOKEN")
        if not hmac.compare_digest(authorization, "Bearer " + settings.api_token):
            raise HTTPException(401, "Bearer token required")
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and pressured(await usage(store, settings), settings):
            raise HTTPException(503, "Capacity watermark reached; automatic eviction pending", headers={"Retry-After": "60"})

    app = FastAPI(title="Market Surveillance", lifespan=lifespan, dependencies=[Depends(authorized)])

    @app.get("/capacity")
    async def capacity_status():
        measured = await usage(store, settings)
        previous = await store.fetch("SELECT updated_at,document FROM surveillance_capacity WHERE id=1")
        return {**measured, "database_max_bytes": settings.database_max_bytes, "raw_max_bytes": settings.raw_max_bytes,
                "evict_at_ratio": .8, "target_ratio": .6, "admission_blocked": pressured(measured, settings),
                "last_eviction": previous[0] if previous else None,
                "limits": "Admission budgets; excludes WAL, images, logs and compaction scratch; not a filesystem quota"}

    @app.get("/health")
    async def health():
        await store.fetch("SELECT 1")
        return {"status": "ok", "collection_mode": "REST", "trading": False}

    @app.get("/coverage")
    async def coverage():
        return await completeness(store)

    @app.get('/selection')
    async def selection():
        return await store.fetch("""SELECT venue,payload,due_at,checkpoint FROM surveillance_jobs
            WHERE kind='trades' AND enabled AND NOT COALESCE((payload->>'manual')::boolean,false)
            ORDER BY venue,id""")

    @app.get("/markets")
    async def markets(venue: Literal["polymarket", "kalshi"], after: str = "", limit: int = Query(100, ge=1, le=1000)):
        rows = await store.fetch("SELECT document,id FROM surveillance_markets WHERE venue=%s AND id>%s ORDER BY id LIMIT %s",
                                 (venue, after, limit))
        return {"data": [r["document"] for r in rows], "next_after": rows[-1]["id"] if len(rows) == limit else None}

    @app.get("/cases")
    async def cases(after: str = "", limit: int = Query(100, ge=1, le=1000)):
        rows = await store.fetch("SELECT id,status,document FROM surveillance_cases WHERE id>%s ORDER BY id LIMIT %s", (after, limit))
        return {"data": rows, "next_after": rows[-1]["id"] if len(rows) == limit else None}

    @app.get("/cases/{case_id}")
    async def case(case_id: str, version: int | None = Query(None, ge=1)):
        if version is None:
            rows = await store.fetch("SELECT document FROM surveillance_cases WHERE id=%s", (case_id,))
        else:
            rows = await store.fetch("SELECT document FROM surveillance_case_versions WHERE case_id=%s AND version=%s", (case_id, version))
        if not rows:
            raise HTTPException(404, "Case/version not found")
        return rows[0]["document"]

    @app.get("/cases/{case_id}/report", response_class=PlainTextResponse)
    async def case_report(case_id: str):
        return report(await case(case_id, None))

    @app.post("/cases/{case_id}/review")
    async def review(case_id: str, body: Review):
        result = await store.review(case_id, body.status, body.note, body.reviewer)
        if result is None:
            raise HTTPException(404, "Case not found")
        return result

    @app.post("/replay")
    async def run_replay(body: ReplayRequest):
        try:
            as_of = timestamp(body.as_of)
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(422, "as_of must be a timezone-aware timestamp")
        try:
            return await replay(store, body.venue, body.market_id, as_of, max_trades=settings.replay_max_trades)
        except ReplayCapacityError as exc:
            raise HTTPException(413, str(exc))

    @app.post("/information")
    async def information(body: Information):
        record = body.model_dump(mode="json")
        for key in ("published_at", "event_time"):
            if record[key] is not None:
                try:
                    record[key] = timestamp(record[key])
                except (ValueError, TypeError, OverflowError):
                    raise HTTPException(422, f"{key} requires timezone")
        if body.publication_time_verified and (not body.published_at or not body.verification_note):
            raise HTTPException(422, "Verified publication time requires a timestamp and verification note")
        if body.publication_time_verified:
            from datetime import datetime,timezone
            if datetime.fromisoformat(record['published_at'])>datetime.now(timezone.utc):
                raise HTTPException(422,'Verified publication cannot be in the future')
        key = digest(record)
        record.update(id=key, received_at=now(), first_seen_at=now(),
                      intake="manual evidence; URL/content not independently fetched or verified")
        async with store.connection() as c:
            raw = RawArchive(settings.raw_dir).write(body.venue, str(body.source_url), {"intake": "manual"}, 0,
                                                   canonical(record).encode(), record["received_at"])
            await store.insert_raw(c, raw)
            await c.execute("INSERT INTO surveillance_information(id,venue,market_id,document,raw_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (key, body.venue, body.market_id, Jsonb(record), raw["id"]))
            if body.publication_time_verified:
                from .event_review import enqueue_review
                await enqueue_review(c, key, body.venue, now())
        return {"id": key, "event_review_queued": body.publication_time_verified}

    @app.post('/event-reviews/{information_id}')
    async def queue_event_review(information_id: str, contract_only: bool = False):
        rows = await store.fetch('SELECT venue,document FROM surveillance_information WHERE id=%s', (information_id,))
        if not rows:
            raise HTTPException(404, 'Information not found')
        if not rows[0]['document'].get('publication_time_verified'):
            raise HTTPException(422, 'Verified publication time required')
        from .event_review import enqueue_review
        async with store.connection() as c:
            key = await enqueue_review(c,information_id,rows[0]['venue'],now(),contract_only)
        return {'job_id': key}

    @app.get('/aggregates')
    async def aggregates(venue: Literal['polymarket','kalshi'], market_id: str,
                         start: str, end: str, as_of: str, limit: int = Query(2016,ge=1,le=20000)):
        from .aggregates import read_bins
        try:
            start,end,as_of = (timestamp(v) for v in (start,end,as_of))
            from datetime import datetime,timedelta
            if datetime.fromisoformat(end)-datetime.fromisoformat(start)>timedelta(days=7) or start>=end:
                raise ValueError('Select an interval of at most seven days')
            rows = await read_bins(store,venue,market_id,start,end,as_of,limit)
        except (ValueError,TypeError,OverflowError) as exc:
            raise HTTPException(422,str(exc))
        return {'data': rows, 'missing_bins': 'unknown; never zero-filled', 'version_clock': 'actual materialization time'}

    @app.get('/wallet-profiles')
    async def wallet_profiles(case_id: str, limit: int = Query(20,ge=1,le=100)):
        return await store.fetch('SELECT id,known_at,document FROM surveillance_wallet_profiles WHERE case_id=%s ORDER BY admitted_at DESC LIMIT %s', (case_id,limit))

    @app.post("/cases/{case_id}/information/{information_id}")
    async def attach_information(case_id: str, information_id: str):
        try:
            document = await store.attach_information(case_id, information_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if document is None:
            raise HTTPException(404, "Case or information not found")
        return document

    @app.get("/evidence/{raw_id}")
    async def evidence(raw_id: str):
        async with store.connection() as c:
            r = await (await c.execute("SELECT * FROM surveillance_raw WHERE id=%s", (raw_id,))).fetchone()
            if not r:
                raise HTTPException(404, "Evidence not found")
            content = RawArchive.read(r)
        return {"id": raw_id, "sha256": r["sha256"], "source": r["source"], "params": r["params"],
                "received_at": r["received_at"], "status": r["status"], "response_headers":r.get("response_headers",{}), "body": content.decode("utf-8", errors="replace")}

    return app
