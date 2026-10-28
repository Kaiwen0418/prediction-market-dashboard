"""PostgreSQL transactions and immutable exact-response Parquet evidence."""
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pyarrow as pa
import pyarrow.parquet as pq

from .normalization import now


class RawArchive:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def write(self, venue, source, params, status, body, received_at=None):
        received_at = received_at or now()
        key = uuid.uuid4().hex
        folder = self.root / venue / received_at[:10]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{key}.parquet"
        temporary = target.with_suffix(".tmp")
        checksum = hashlib.sha256(body).hexdigest()
        table = pa.table({"body": [body], "source": [source], "received_at": [received_at], "sha256": [checksum]})
        try:
            pq.write_table(table, temporary, compression="zstd")
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return dict(id=key, venue=venue, source=source, params=params, status=status, sha256=checksum,
                    path=str(target), received_at=received_at)

    @staticmethod
    def read(record):
        body = pq.read_table(record["path"])["body"][0].as_py()
        if hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise ValueError("Evidence checksum mismatch")
        return body


class Store:
    def __init__(self, dsn):
        self.dsn = dsn

    @asynccontextmanager
    async def connection(self):
        async with await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row) as connection:
            yield connection

    async def initialize(self):
        async with self.connection() as c:
            # Serialize concurrent first-start migrations.
            await c.execute("SELECT pg_advisory_xact_lock(81724001)")
            await c.execute(Path(__file__).with_name("schema.sql").read_text())

    async def fetch(self, sql, params=()):
        async with self.connection() as c:
            return await (await c.execute(sql, params)).fetchall()

    async def enqueue(self, key, kind, venue, payload):
        async with self.connection() as c:
            await c.execute("""INSERT INTO surveillance_jobs(id,kind,venue,payload) VALUES(%s,%s,%s,%s)
                               ON CONFLICT DO NOTHING""", (key, kind, venue, Jsonb(payload)))

    async def claim(self):
        token = uuid.uuid4().hex
        async with self.connection() as c:
            return await (await c.execute("""
                UPDATE surveillance_jobs SET lease_until=now()+interval '5 minutes', lease_token=%s
                WHERE id=(SELECT id FROM surveillance_jobs WHERE enabled AND due_at<=now()
                    AND (lease_until IS NULL OR lease_until<now()) ORDER BY due_at,id
                    FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *
            """, (token,))).fetchone()

    @staticmethod
    async def fence(c, job):
        row = await (await c.execute("""SELECT id FROM surveillance_jobs WHERE id=%s AND lease_token=%s
            AND lease_until>now() FOR UPDATE""", (job["id"], job["lease_token"]))).fetchone()
        if not row:
            raise RuntimeError("Job lease lost; checkpoint not committed")

    async def release(self, job, delay, error=None):
        async with self.connection() as c:
            await c.execute("""UPDATE surveillance_jobs SET lease_until=NULL,lease_token=NULL,
                due_at=now()+(%s * interval '1 second'), failures=CASE WHEN %s::text IS NULL THEN 0 ELSE failures+1 END,
                last_error=%s, updated_at=now() WHERE id=%s AND lease_token=%s""",
                (delay, error, error, job["id"], job["lease_token"]))

    async def raw(self, record):
        async with self.connection() as c:
            await self.insert_raw(c, record)

    @staticmethod
    async def insert_raw(c, r):
        await c.execute("""INSERT INTO surveillance_raw VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING""", (r["id"], r["venue"], r["source"], Jsonb(r["params"]), r["received_at"],
                                       r["status"], r["sha256"], r["path"]))

    async def coverage(self, venue, kind, document, job_id=None):
        async with self.connection() as c:
            await c.execute("INSERT INTO surveillance_coverage(job_id,venue,kind,document) VALUES(%s,%s,%s,%s)",
                            (job_id, venue, kind, Jsonb(document)))

    async def checkpoint(self, job, checkpoint):
        async with self.connection() as c:
            await self.fence(c, job)
            await c.execute("UPDATE surveillance_jobs SET checkpoint=%s WHERE id=%s", (Jsonb(checkpoint), job["id"]))

    async def commit_page(self, job, raw, checkpoint, markets=(), trades=()):
        async with self.connection() as c:
            await self.fence(c, job)
            await self.insert_raw(c, raw)
            for m in markets:
                await c.execute("""INSERT INTO surveillance_markets VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(venue,id) DO UPDATE SET document=EXCLUDED.document,
                    condition_id=EXCLUDED.condition_id,observed_at=EXCLUDED.observed_at,raw_id=EXCLUDED.raw_id""",
                    (m["venue"], m["id"], m["condition_id"], Jsonb(m), m["observed_at"], raw["id"]))
                await c.execute("INSERT INTO surveillance_rules VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (m["venue"], m["condition_id"] or m["id"], m["rules_hash"], Jsonb(m), m["observed_at"], raw["id"]))
            for t in trades:
                await c.execute("""INSERT INTO surveillance_trades VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""", (t["venue"], t["id"], t["market_id"], t["outcome"], t["event_time"],
                                               t["received_at"], Jsonb(t), raw["id"]))
            await c.execute("""UPDATE surveillance_jobs SET checkpoint=%s,lease_until=now()+interval '5 minutes',
                            updated_at=now() WHERE id=%s""", (Jsonb(checkpoint), job["id"]))

    async def save_case(self, document):
        async with self.connection() as c:
            await c.execute("""INSERT INTO surveillance_cases(id,venue,market_id,status,document)
                VALUES(%s,%s,%s,'candidate',%s) ON CONFLICT DO NOTHING""",
                (document["id"], document["venue"], document["market_id"], Jsonb(document)))
            await c.execute("""INSERT INTO surveillance_case_versions(case_id,version,document)
                VALUES(%s,1,%s) ON CONFLICT DO NOTHING""", (document["id"], Jsonb(document)))

    async def review(self, case_id, status, note, reviewer):
        async with self.connection() as c:
            row = await (await c.execute("SELECT * FROM surveillance_cases WHERE id=%s FOR UPDATE", (case_id,))).fetchone()
            if not row:
                return None
            version = (await (await c.execute("SELECT max(version) AS n FROM surveillance_case_versions WHERE case_id=%s",
                                             (case_id,))).fetchone())["n"] + 1
            document = dict(row["document"], status=status, review={"status": status, "note": note, "reviewer": reviewer, "at": now()})
            await c.execute("UPDATE surveillance_cases SET document=%s,status=%s WHERE id=%s", (Jsonb(document), status, case_id))
            await c.execute("INSERT INTO surveillance_case_versions(case_id,version,document) VALUES(%s,%s,%s)",
                            (case_id, version, Jsonb(document)))
            return dict(document, version=version)

    async def attach_information(self, case_id, information_id):
        async with self.connection() as c:
            row = await (await c.execute("SELECT * FROM surveillance_cases WHERE id=%s FOR UPDATE", (case_id,))).fetchone()
            information = await (await c.execute("SELECT * FROM surveillance_information WHERE id=%s", (information_id,))).fetchone()
            if not row or not information:
                return None
            if row["venue"] != information["venue"] or row["market_id"] != information["market_id"]:
                raise ValueError("Evidence belongs to another contract")
            document = dict(row["document"])
            timeline = list(document.get("investigation_timeline", []))
            if any(item["id"] == information_id for item in timeline):
                return document
            timeline.append(dict(information["document"], raw_id=information["raw_id"]))
            document["investigation_timeline"] = timeline
            version = (await (await c.execute("SELECT max(version) AS n FROM surveillance_case_versions WHERE case_id=%s",
                                             (case_id,))).fetchone())["n"] + 1
            await c.execute("UPDATE surveillance_cases SET document=%s WHERE id=%s", (Jsonb(document), case_id))
            await c.execute("INSERT INTO surveillance_case_versions(case_id,version,document) VALUES(%s,%s,%s)",
                            (case_id, version, Jsonb(document)))
            return dict(document, version=version)
