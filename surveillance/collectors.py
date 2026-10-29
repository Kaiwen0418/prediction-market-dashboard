"""Read-only HTTP with durable responses before parsing. No trading endpoints."""
import asyncio
from email.utils import parsedate_to_datetime
import json
import time
from urllib.parse import quote

import httpx

from .normalization import now


class ContractError(ValueError):
    pass


class UpstreamCooldown(ContractError):
    def __init__(self, seconds):
        super().__init__(f"Upstream cooldown {seconds}s")
        self.retry_after = seconds


def unpack(venue, kind, body):
    if not isinstance(body, dict) and not (venue=="polymarket" and kind=="details" and isinstance(body,list)):
        raise ContractError("Expected response envelope")
    if kind == "details":
        row = (body[0] if isinstance(body,list) and len(body)==1 else body) if venue == "polymarket" else body.get("market")
        if not isinstance(row, dict) or not row.get("id" if venue == "polymarket" else "ticker"):
            raise ContractError("Missing market detail")
        return [row], None
    if kind == "catalog":
        rows = body.get("markets")
        cursor = body.get("next_cursor") if venue == "polymarket" else body.get("cursor")
    elif venue == "polymarket":
        rows = body.get("data")
        pagination = body.get("pagination")
        if not isinstance(pagination, dict) or not isinstance(pagination.get("has_more"), bool):
            raise ContractError("Missing v2 pagination")
        cursor = pagination.get("next_cursor")
        if pagination["has_more"] != bool(cursor):
            raise ContractError("Inconsistent v2 pagination")
    else:
        rows, cursor = body.get("trades"), body.get("cursor")
        if "cursor" not in body:
            raise ContractError("Missing Kalshi pagination")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ContractError("Missing row array")
    if cursor is not None and not isinstance(cursor, str):
        raise ContractError("Invalid cursor")
    return rows, cursor or None


class Collector:
    def __init__(self, store, archive, interval=0.6, client=None):
        self.store, self.archive, self.interval = store, archive, interval
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def close(self):
        await self.client.aclose()

    async def get(self, venue, url, params):
        for attempt in range(4):
            async with self.lock:
                await asyncio.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                response = await self.client.get(url, params=params)
            raw = await asyncio.to_thread(self.archive.write, venue, url, params, response.status_code, response.content, now())
            raw['response_headers']={k:response.headers[k] for k in ('cache-control','age','date','cf-cache-status') if k in response.headers}
            await self.store.raw(raw)
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                response.raise_for_status()
                return raw, json.loads(response.content)
            retry = response.headers.get("retry-after", str(2 ** attempt))
            try:
                delay = float(retry)
            except ValueError:
                delay = max(0, parsedate_to_datetime(retry).timestamp() - time.time())
            # Long server cooldowns return control to the durable queue.
            if delay > 60:
                raise UpstreamCooldown(delay)
            await asyncio.sleep(max(delay, 2 ** attempt))
        raise AssertionError("Unreachable")

    async def page(self, job):
        venue, kind, cp, payload = job["venue"], job["kind"], job["checkpoint"], job["payload"]
        params = {"limit": 100 if kind == "catalog" else 1000}
        if kind == "details":
            key = str(payload.get("catalog_id") or payload["market_id"])
            base = "https://gamma-api.polymarket.com/markets/" if venue == "polymarket" else "https://external-api.kalshi.com/trade-api/v2/markets/"
            # Gamma's filtered list includes events/tags omitted by /markets/{id}.
            if venue=='polymarket':
                # The list defaults to open markets. Completed investigations and
                # contracts that just closed need an explicit second lookup.
                params={'condition_ids' if payload.get('lookup') else 'id':key,'include_tag':'true'}
                raw,body=await self.get(venue,'https://gamma-api.polymarket.com/markets',params)
                if body==[]:
                    raw,body=await self.get(venue,'https://gamma-api.polymarket.com/markets',dict(params,closed='true'))
                if body==[] and not payload.get('lookup'):
                    raw,body=await self.get(venue,base+quote(key,safe=''),{})
            else:
                raw, body = await self.get(venue, base + quote(key, safe=""), {})
            rows, _ = unpack(venue, kind, body)
            actual = str(rows[0]["id" if venue == "polymarket" else "ticker"])
            expected=str(rows[0].get('conditionId')) if venue=='polymarket' and payload.get('lookup') else actual
            if expected != key:
                raise ContractError("Detail response belongs to another contract")
            return raw, rows, None
        if venue == "polymarket":
            if kind == "catalog":
                url = "https://gamma-api.polymarket.com/markets/keyset"
                params.update(closed=str(payload["closed"]).lower(), include_tag="true")
                cursor_key = "after_cursor"
            else:
                url = "https://data-api.polymarket.com/v2/trades"
                if kind == 'wallet':
                    from datetime import datetime
                    params.update(user=payload['wallet'], taker_only='false', limit=500,
                        start=int(datetime.fromisoformat(payload['since']).timestamp()),
                        end=int(datetime.fromisoformat(payload['cutoff']).timestamp()))
                elif kind=='wide':
                    params['taker_only']='true'
                else:
                    params.update(condition=payload["market_id"], taker_only="true")
                cursor_key = "cursor"
        else:
            url = "https://external-api.kalshi.com/trade-api/v2/markets"
            if kind == "catalog" and payload.get("scope") == "active-v2":
                params.update(status="open", mve_filter="exclude")
            if kind in ("trades", "backfill", "wide"):
                url += "/trades"
                if kind!='wide':params["ticker"] = payload["market_id"]
                # Pin min_ts for the entire cursor walk. Replay the boundary second.
                if cp.get("since"):
                    params["min_ts"] = cp["since"]
            cursor_key = "cursor"
        if cp.get("cursor"):
            params[cursor_key] = cp["cursor"]
        raw, body = await self.get(venue, url, params)
        rows, cursor = unpack(venue, kind, body)
        if cursor and cursor == cp.get("cursor"):
            raise ContractError("Upstream cursor did not advance")
        return raw, rows, cursor
