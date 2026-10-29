import asyncio
import contextlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.core.config import get_settings
from app.services.polymarket import fetch_json


POLITICAL_CATEGORIES = {
    "politics",
    "elections",
    "geopolitics",
    "government",
    "world",
}
POLITICAL_TERMS = re.compile(
    r"\b("
    r"election|electoral|president|presidential|prime minister|chancellor|"
    r"governor|senate|senator|congress|parliament|assembly|referendum|"
    r"mayor|cabinet|coalition|party nominee|party leader|government|"
    r"impeach|resign|ceasefire|peace deal|war|invasion|capture|withdraw"
    r")\b",
    re.IGNORECASE,
)


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _event_search_text(event: dict[str, Any]) -> str:
    tags = event.get("tags")
    tag_text = " ".join(
        " ".join(
            filter(
                None,
                (_string(tag.get("slug")), _string(tag.get("label"))),
            )
        )
        for tag in tags
        if isinstance(tag, dict)
    ) if isinstance(tags, list) else ""
    return " ".join(
        filter(
            None,
            (
                _string(event.get("title")),
                _string(event.get("subtitle")),
                _string(event.get("category")),
                _string(event.get("subcategory")),
                tag_text,
            ),
        )
    )


def is_political_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False

    category_values = {
        _string(event.get("category")).lower(),
        _string(event.get("subcategory")).lower(),
    }
    tags = event.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, dict):
                continue
            category_values.add(_string(tag.get("slug")).lower())
            category_values.add(_string(tag.get("label")).lower())

    if category_values & POLITICAL_CATEGORIES:
        return True
    return POLITICAL_TERMS.search(_event_search_text(event)) is not None


def _pick_fields(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: source[field] for field in fields if field in source}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def compact_polymarket_event(event: dict[str, Any]) -> dict[str, Any]:
    compact = _pick_fields(
        event,
        (
            "id",
            "slug",
            "title",
            "category",
            "resolutionSource",
            "active",
            "closed",
            "endDate",
            "volume24hr",
            "openInterest",
            "liquidity",
            "image",
        ),
    )
    markets = event.get("markets")
    valid_markets = (
        [market for market in markets if isinstance(market, dict)]
        if isinstance(markets, list)
        else []
    )
    leader = max(
        valid_markets,
        key=lambda market: _number((_array(market.get("outcomePrices")) or [0])[0]),
        default=None,
    )
    compact["markets"] = [
        _pick_fields(
            leader,
            (
                "id",
                "conditionId",
                "clobTokenIds",
                "outcomes",
                "outcomePrices",
                "question",
                "title",
                "volume24hr",
                "openInterest",
                "liquidity",
                "active",
                "closed",
                "acceptingOrders",
                "endDate",
                "resolutionSource",
            ),
        )
    ] if leader else []
    return compact


def compact_kalshi_event(event: dict[str, Any]) -> dict[str, Any]:
    compact = _pick_fields(
        event,
        (
            "event_ticker",
            "series_ticker",
            "title",
            "category",
            "settlement_sources",
        ),
    )
    markets = event.get("markets")
    valid_markets = (
        [market for market in markets if isinstance(market, dict)]
        if isinstance(markets, list)
        else []
    )
    active_markets = [
        market for market in valid_markets if market.get("status") == "active"
    ]
    ranked_markets = active_markets or valid_markets
    leader = max(
        ranked_markets,
        key=lambda market: _number(market.get("last_price_dollars")),
        default=None,
    )
    if leader:
        compact_leader = _pick_fields(
            leader,
            (
                "ticker",
                "title",
                "subtitle",
                "yes_sub_title",
                "status",
                "last_price_dollars",
                "expected_expiration_time",
                "close_time",
            ),
        )
        compact_leader["volume_24h_fp"] = sum(
            _number(market.get("volume_24h_fp")) for market in valid_markets
        )
        compact_leader["liquidity_dollars"] = sum(
            _number(market.get("liquidity_dollars")) for market in valid_markets
        )
        compact["markets"] = [compact_leader]
    else:
        compact["markets"] = []
    return compact


async def scan_polymarket_events() -> tuple[list[dict[str, Any]], int]:
    settings = get_settings()
    events: list[dict[str, Any]] = []
    scanned = 0
    cursor = ""

    for _ in range(settings.market_catalog_max_pages):
        params = {
            "active": "true",
            "closed": "false",
            "tag_slug": "politics",
            "related_tags": "true",
            "limit": settings.market_catalog_page_size,
        }
        if cursor:
            params["after_cursor"] = cursor
        payload = await fetch_json(
            f"{settings.gamma_base_url}/events/keyset?{urlencode(params)}",
            cache_ttl_seconds=settings.market_catalog_sync_interval_seconds,
            stale_if_error_seconds=settings.market_catalog_stale_if_error_seconds,
        )
        page_events = (
            payload
            if isinstance(payload, list)
            else payload.get("events", [])
            if isinstance(payload, dict)
            else []
        )
        if not isinstance(page_events, list):
            break

        valid_events = [event for event in page_events if isinstance(event, dict)]
        scanned += len(valid_events)
        events.extend(
            compact_polymarket_event(event)
            for event in valid_events
            if is_political_event(event)
        )
        cursor = _string(payload.get("next_cursor")) if isinstance(payload, dict) else ""
        if not cursor:
            break

    return events, scanned


async def scan_kalshi_events() -> tuple[list[dict[str, Any]], int]:
    settings = get_settings()
    events: list[dict[str, Any]] = []
    scanned = 0
    cursor = ""

    for _ in range(settings.market_catalog_max_pages):
        params: dict[str, str | int] = {
            "status": "open",
            "with_nested_markets": "true",
            "limit": settings.market_catalog_page_size,
        }
        if cursor:
            params["cursor"] = cursor
        payload = await fetch_json(
            f"{settings.kalshi_base_url}/events?{urlencode(params)}",
            cache_ttl_seconds=settings.market_catalog_sync_interval_seconds,
            stale_if_error_seconds=settings.market_catalog_stale_if_error_seconds,
        )
        if not isinstance(payload, dict):
            break
        page_events = payload.get("events", [])
        if not isinstance(page_events, list):
            break

        valid_events = [event for event in page_events if isinstance(event, dict)]
        scanned += len(valid_events)
        events.extend(
            compact_kalshi_event(event)
            for event in valid_events
            if is_political_event(event)
        )
        cursor = _string(payload.get("cursor"))
        if not cursor:
            break

    return events, scanned


class MarketCatalogService:
    def __init__(self) -> None:
        self._snapshot: dict[str, Any] | None = None
        self._stored_at = 0.0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def clear(self) -> None:
        self._snapshot = None
        self._stored_at = 0.0

    def _is_fresh(self) -> bool:
        settings = get_settings()
        return (
            self._snapshot is not None
            and time.monotonic() - self._stored_at
            < settings.market_catalog_sync_interval_seconds
        )

    async def get_catalog(self) -> dict[str, Any]:
        if not self._is_fresh():
            await self.sync()
        return self._snapshot or self._empty_snapshot()

    async def sync(self, force: bool = False) -> dict[str, Any]:
        if not force and self._is_fresh():
            return self._snapshot or self._empty_snapshot()

        async with self._lock:
            if not force and self._is_fresh():
                return self._snapshot or self._empty_snapshot()

            previous_venues = (
                self._snapshot.get("venues", {})
                if isinstance(self._snapshot, dict)
                else {}
            )
            results = await asyncio.gather(
                scan_polymarket_events(),
                scan_kalshi_events(),
                return_exceptions=True,
            )
            venues: dict[str, dict[str, Any]] = {}
            for venue, result in zip(("polymarket", "kalshi"), results):
                if isinstance(result, BaseException):
                    previous = previous_venues.get(venue, {})
                    venues[venue] = {
                        "events": previous.get("events", []),
                        "scanned": previous.get("scanned", 0),
                        "error": type(result).__name__,
                    }
                else:
                    events, scanned = result
                    venues[venue] = {
                        "events": events,
                        "scanned": scanned,
                        "error": None,
                    }

            now = datetime.now(timezone.utc).isoformat()
            self._snapshot = {
                "updatedAt": now,
                "venues": venues,
                "counts": {
                    venue: len(details["events"])
                    for venue, details in venues.items()
                },
            }
            self._stored_at = time.monotonic()
            return self._snapshot

    async def replace_event(
        self,
        venue: str,
        identifier: str,
        event: dict[str, Any],
    ) -> bool:
        async with self._lock:
            if not self._snapshot:
                return False
            venue_snapshot = self._snapshot.get("venues", {}).get(venue)
            if not isinstance(venue_snapshot, dict):
                return False
            events = venue_snapshot.get("events")
            if not isinstance(events, list):
                return False

            id_field = "slug" if venue == "polymarket" else "event_ticker"
            for index, current in enumerate(events):
                if (
                    isinstance(current, dict)
                    and _string(current.get(id_field)) == identifier
                ):
                    events[index] = event
                    return True
            return False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        settings = get_settings()
        while True:
            await asyncio.sleep(settings.market_catalog_sync_interval_seconds)
            with contextlib.suppress(Exception):
                await self.sync(force=True)

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {
            "updatedAt": None,
            "venues": {
                "polymarket": {"events": [], "scanned": 0, "error": None},
                "kalshi": {"events": [], "scanned": 0, "error": None},
            },
            "counts": {"polymarket": 0, "kalshi": 0},
        }


market_catalog_service = MarketCatalogService()
