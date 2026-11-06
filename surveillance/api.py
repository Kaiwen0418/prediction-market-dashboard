from datetime import datetime, timezone
from contextlib import asynccontextmanager
import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from psycopg.errors import LockNotAvailable, QueryCanceled
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
    knowledge_cutoff: str | None = None


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

    @app.exception_handler(LockNotAvailable)
    @app.exception_handler(QueryCanceled)
    async def database_budget_exhausted(request,exc):
        return JSONResponse(status_code=503,content={'detail':'Database maintenance or query time budget; retry shortly'},headers={'Retry-After':'5'})

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
        return {"status": "ok", "collection_mode": "REST", "analysis_mode": settings.mode, "trading": False}

    @app.get('/wallets/{wallet}/timing')
    async def wallet_timing(wallet: str, horizon: int = Query(3600)):
        import re
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}',wallet):
            raise HTTPException(422,'Valid public wallet required')
        if horizon not in (300,900,3600):
            raise HTTPException(422,'Choose 300, 900 or 3600 seconds')
        from .wallet_timing import patterns
        try:
            return await patterns(store,wallet.lower(),horizon)
        except ValueError as exc:
            raise HTTPException(413,str(exc))

    @app.get('/retrospectives')
    async def retrospectives(after: str = '', limit: int = Query(50,ge=1,le=200)):
        rows=await store.fetch("""SELECT id,venue,market_id,status,known_at,
            document->'market'->>'title' AS title,document->'completion' AS completion,
            document->>'requested_start' AS requested_start,document->>'requested_end' AS requested_end
            FROM surveillance_retrospectives WHERE id>%s ORDER BY id LIMIT %s""",(after,limit))
        return dict(data=rows,next_after=rows[-1]['id'] if len(rows)==limit else None)

    @app.get('/retrospectives/status')
    async def retrospective_status():
        states=await store.fetch('SELECT venue,status,count(*) AS n FROM surveillance_retrospectives GROUP BY venue,status')
        budgets=await store.fetch('SELECT * FROM surveillance_research_budget')
        jobs=await store.fetch("""SELECT id,kind,venue,enabled,failures,last_error,due_at,checkpoint FROM surveillance_jobs
            WHERE kind IN ('settlement_discovery','retrospective_dispatch','research_bootstrap') OR (kind IN ('retrospective','retrospective_analysis') AND enabled)
            ORDER BY id LIMIT 100""")
        return dict(mode=settings.mode,states=states,budgets=budgets,jobs=jobs,
            tape_budget=settings.research_tape_max_bytes,summary_budget=settings.research_summary_max_bytes,
            budget_basis='Recorded tuple bytes plus per-row allowance; global physical DB ceiling also applies',
            retention_days=settings.research_retention_days,lookback_days=settings.review_lookback_days,
            market_trade_limit=settings.review_max_trades,estimated_bytes_per_trade=4096,
            limits='Bounded archive and lookback, not guaranteed full market lifetime or full venue coverage')

    @app.get('/retrospectives/{review_id}')
    async def retrospective(review_id: str, after: str = '', limit: int = Query(1,ge=1,le=5)):
        rows=await store.fetch('SELECT * FROM surveillance_retrospectives WHERE id=%s',(review_id,))
        if not rows:raise HTTPException(404,'Review not found or expired')
        slices=await store.fetch('SELECT * FROM surveillance_review_slices WHERE review_id=%s AND id>%s ORDER BY id LIMIT %s',(review_id,after,limit))
        refs={r['raw_id'] for s in slices for r in s['document'].get('raw_references',[])}
        refs.add(rows[0]['document']['raw_id'])
        available={r['id'] for r in await store.fetch('SELECT id FROM surveillance_raw WHERE id=ANY(%s)',(list(refs),))}
        for s in slices:
            references=s['document'].get('raw_references',[])
            missing=sum(r['raw_id'] not in available for r in references)
            s['document']['raw_evidence_status']='expired_or_partial' if missing else 'retained' if references else 'no_references'
            s['document']['missing_raw_receipts']=missing
            # Current archive availability, never trust a frozen replayability flag.
            tape=await store.fetch('SELECT count(*) AS n,sum(fills) AS fills FROM surveillance_research_tape WHERE venue=%s AND market_id=%s AND lower_time<%s AND upper_time>=%s',
                (rows[0]['venue'],rows[0]['market_id'],s['upper_time'],s['document']['context_start']))
            s['document']['normalized_replay_available']=None
            s['document']['current_archive_fragments']=tape[0]['n']
            s['document']['replay_note']='Use replay endpoint to verify the input digest; surviving fragments alone do not prove completeness'
        pages=await store.fetch('SELECT pass,count(*) AS pages FROM surveillance_review_pages WHERE review_id=%s GROUP BY pass ORDER BY pass',(review_id,))
        return dict(continuity=rows[0]['document'].get('continuity',{'status':'legacy_unverified'}),page_manifest=pages,review=rows[0],settlement_raw_available=rows[0]['document']['raw_id'] in available,
            slices=slices,next_after=slices[-1]['id'] if len(slices)==limit else None)

    @app.get('/retrospectives/{review_id}/report',response_class=PlainTextResponse)
    async def retrospective_report(review_id: str, after: str = ''):
        import json
        dossier=await retrospective(review_id,after,1)
        return '# Retrospective market review\n\n' + 'Future-price research; not an online alert, profit calculation or insider probability.\n\n' +             'One slice per page. Use next_after to retrieve the remaining slices.\n\n```json\n' + json.dumps(dossier,default=str,ensure_ascii=False,indent=2) + '\n```\n'

    @app.post('/retrospectives/{review_id}/slices/{slice_id}/replay')
    async def retrospective_replay(review_id: str,slice_id: str):
        rows=await store.fetch('SELECT r.venue,r.market_id,s.document FROM surveillance_review_slices s JOIN surveillance_retrospectives r ON r.id=s.review_id WHERE s.id=%s AND r.id=%s',(slice_id,review_id))
        if not rows:raise HTTPException(404,'Slice not found or expired')
        from .research_archive import read_tape
        from .leadlag import analyze
        r=rows[0];d=r['document']
        try:trades,_=await read_tape(store,r['venue'],r['market_id'],d['context_start'],d.get('data_end',d['end']),settings.replay_max_trades,known_at=d.get('archive_cutoff'))
        except ValueError as exc:raise HTTPException(413,str(exc))
        result=analyze(trades,d['start'],d['end'],observation_end=d.get('data_end',d['end']))
        if not d.get('input_digest') or result['input_digest']!=d['input_digest']:
            raise HTTPException(409,'Normalized input set changed or expired; original replay unavailable')
        return result

    @app.get("/coverage")
    async def coverage():
        return await completeness(store)

    @app.get('/wallets/{wallet}/patterns')
    async def wallet_pattern_summary(wallet: str,as_of: str | None = None):
        import re
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}',wallet):raise HTTPException(422,'Valid public wallet required')
        from .longitudinal import wallet_patterns
        try:
            cutoff=timestamp(as_of) if as_of else None
            if cutoff and datetime.fromisoformat(cutoff)>datetime.now(timezone.utc):raise ValueError('Knowledge cutoff cannot be in the future')
            return await wallet_patterns(store,wallet,cutoff)
        except ValueError as exc:raise HTTPException(422,str(exc))

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
            from datetime import datetime,timezone
            known=timestamp(body.knowledge_cutoff) if body.knowledge_cutoff else as_of
            if datetime.fromisoformat(known)>datetime.now(timezone.utc):raise ValueError('Knowledge cutoff cannot be in the future')
            return await replay(store,body.venue,body.market_id,as_of,max_trades=settings.replay_max_trades,knowledge_cutoff=known)
        except ReplayCapacityError as exc:
            raise HTTPException(413,str(exc))
        except (ValueError,TypeError) as exc:
            raise HTTPException(422,str(exc))

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
