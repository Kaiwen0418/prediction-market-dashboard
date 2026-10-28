from contextlib import asynccontextmanager
import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl
from psycopg.types.json import Jsonb

from .cases import completeness, report
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

    async def authorized(authorization: str = Header(default="")):
        if not settings.api_token:
            raise HTTPException(503, "Configure SURVEILLANCE_API_TOKEN")
        if not hmac.compare_digest(authorization, "Bearer " + settings.api_token):
            raise HTTPException(401, "Bearer token required")

    app = FastAPI(title="Market Surveillance", lifespan=lifespan, dependencies=[Depends(authorized)])

    @app.get("/health")
    async def health():
        await store.fetch("SELECT 1")
        return {"status": "ok", "collection_mode": "REST", "trading": False}

    @app.get("/coverage")
    async def coverage():
        return await completeness(store)

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
        key = digest(record)
        record.update(id=key, received_at=now(), first_seen_at=now(),
                      intake="manual evidence; URL/content not independently fetched or verified")
        raw = RawArchive(settings.raw_dir).write(body.venue, str(body.source_url), {"intake": "manual"}, 0,
                                               canonical(record).encode(), record["received_at"])
        async with store.connection() as c:
            await store.insert_raw(c, raw)
            await c.execute("INSERT INTO surveillance_information(id,venue,market_id,document,raw_id) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (key, body.venue, body.market_id, Jsonb(record), raw["id"]))
        return {"id": key}

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
        rows = await store.fetch("SELECT * FROM surveillance_raw WHERE id=%s", (raw_id,))
        if not rows:
            raise HTTPException(404, "Evidence not found")
        r = rows[0]
        content = RawArchive.read(r)
        return {"id": raw_id, "sha256": r["sha256"], "source": r["source"], "params": r["params"],
                "received_at": r["received_at"], "status": r["status"], "body": content.decode("utf-8", errors="replace")}

    return app
