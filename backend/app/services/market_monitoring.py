import asyncio
import contextlib
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

from app.core.config import get_settings
from app.services.kalshi import fetch_kalshi_events
from app.services.market_catalog import (
    compact_kalshi_event,
    compact_polymarket_event,
    market_catalog_service,
)
from app.services.polymarket import fetch_json
from app.services.upstream_rate_limit import upstream_rate_limiter
from app.streaming.polymarket_ws import live_stream_manager


Tier = Literal["hot", "warm", "catalog"]


def _number(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _event_activity(event: dict[str, Any]) -> float:
    markets = event.get("markets")
    market = markets[0] if isinstance(markets, list) and markets else {}
    if not isinstance(market, dict):
        market = {}
    volume = max(
        _number(event.get("volume24hr")),
        _number(market.get("volume24hr")),
        _number(market.get("volume_24h_fp")),
    )
    liquidity = max(
        _number(event.get("liquidity")),
        _number(event.get("openInterest")),
        _number(market.get("liquidity")),
        _number(market.get("openInterest")),
        _number(market.get("liquidity_dollars")),
    )
    return round(math.log1p(volume) * 2 + math.log1p(liquidity), 6)


@dataclass(frozen=True)
class MonitoredMarket:
    venue: str
    identifier: str
    title: str
    tier: Tier
    activity_score: float


class MarketMonitoringService:
    def __init__(self) -> None:
        self._assignments: dict[tuple[str, str], MonitoredMarket] = {}
        self._due_at: dict[tuple[str, str], float] = {}
        self._last_success_at: dict[tuple[str, str], str] = {}
        self._last_error: dict[tuple[str, str], str] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._lock = asyncio.Lock()
        self._refresh_semaphore: asyncio.Semaphore | None = None
        self._started_at: str | None = None

    def clear(self) -> None:
        self._assignments.clear()
        self._due_at.clear()
        self._last_success_at.clear()
        self._last_error.clear()
        self._started_at = None

    async def start(self) -> None:
        settings = get_settings()
        if not settings.monitoring_enabled or (self._task and not self._task.done()):
            return
        self._stop_requested = False
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._refresh_semaphore = asyncio.Semaphore(
            max(settings.monitoring_max_refreshes_per_tick, 1)
        )
        self._task = asyncio.create_task(
            self._run(),
            name="market-monitoring-scheduler",
        )

    async def stop(self) -> None:
        self._stop_requested = True
        if not self._task:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def rebuild_assignments(self) -> list[MonitoredMarket]:
        snapshot = await market_catalog_service.get_catalog()
        settings = get_settings()
        assignments: dict[tuple[str, str], MonitoredMarket] = {}

        for venue in ("polymarket", "kalshi"):
            venue_data = snapshot.get("venues", {}).get(venue, {})
            events = venue_data.get("events", []) if isinstance(venue_data, dict) else []
            ranked: list[tuple[float, str, dict[str, Any]]] = []
            for event in events if isinstance(events, list) else []:
                if not isinstance(event, dict):
                    continue
                identifier = str(
                    event.get("slug")
                    if venue == "polymarket"
                    else event.get("event_ticker")
                    or ""
                ).strip()
                if not identifier:
                    continue
                ranked.append((_event_activity(event), identifier, event))
            ranked.sort(key=lambda row: (-row[0], row[1]))

            hot_end = max(settings.monitoring_hot_markets_per_venue, 0)
            warm_end = hot_end + max(settings.monitoring_warm_markets_per_venue, 0)
            for index, (score, identifier, event) in enumerate(ranked):
                tier: Tier = (
                    "hot" if index < hot_end
                    else "warm" if index < warm_end
                    else "catalog"
                )
                assignments[(venue, identifier)] = MonitoredMarket(
                    venue=venue,
                    identifier=identifier,
                    title=str(event.get("title") or identifier),
                    tier=tier,
                    activity_score=score,
                )

        now = time.monotonic()
        async with self._lock:
            previous_keys = set(self._assignments)
            self._assignments = assignments
            for key, assignment in assignments.items():
                if assignment.tier == "catalog":
                    self._due_at.pop(key, None)
                elif key not in previous_keys:
                    self._due_at[key] = now + random.uniform(0.0, 2.0)
            for key in set(self._due_at) - set(assignments):
                self._due_at.pop(key, None)
                self._last_success_at.pop(key, None)
                self._last_error.pop(key, None)

        await self._ensure_hot_polymarket_streams()
        return list(assignments.values())

    async def run_due_refreshes(self) -> int:
        settings = get_settings()
        now = time.monotonic()
        async with self._lock:
            due = [
                assignment
                for key, assignment in self._assignments.items()
                if assignment.tier != "catalog"
                and self._due_at.get(key, now) <= now
            ]
        due.sort(key=lambda item: (item.tier != "hot", -item.activity_score))
        selected = due[: max(settings.monitoring_max_refreshes_per_tick, 1)]
        if not selected:
            return 0
        await asyncio.gather(*(self._refresh_guarded(item) for item in selected))
        return len(selected)

    async def get_status(self) -> dict[str, Any]:
        async with self._lock:
            assignments = list(self._assignments.values())
            last_success = dict(self._last_success_at)
            last_error = dict(self._last_error)
            due_at = dict(self._due_at)
        counts = {
            venue: {
                tier: sum(
                    item.venue == venue and item.tier == tier
                    for item in assignments
                )
                for tier in ("hot", "warm", "catalog")
            }
            for venue in ("polymarket", "kalshi")
        }
        now = time.monotonic()
        active = sorted(
            (item for item in assignments if item.tier != "catalog"),
            key=lambda item: (item.venue, item.tier != "hot", -item.activity_score),
        )
        return {
            "enabled": get_settings().monitoring_enabled,
            "startedAt": self._started_at,
            "counts": counts,
            "rateLimits": upstream_rate_limiter.status(),
            "markets": [
                {
                    "venue": item.venue,
                    "identifier": item.identifier,
                    "title": item.title,
                    "tier": item.tier,
                    "activityScore": item.activity_score,
                    "nextRefreshSeconds": max(
                        round(due_at.get((item.venue, item.identifier), now) - now, 1),
                        0,
                    ),
                    "lastSuccessAt": last_success.get((item.venue, item.identifier)),
                    "lastError": last_error.get((item.venue, item.identifier)),
                }
                for item in active[:50]
            ],
        }

    async def _refresh_guarded(self, market: MonitoredMarket) -> None:
        semaphore = self._refresh_semaphore
        if semaphore is None:
            return
        async with semaphore:
            await self._refresh(market)

    async def _refresh(self, market: MonitoredMarket) -> None:
        settings = get_settings()
        key = (market.venue, market.identifier)
        interval = (
            settings.monitoring_hot_refresh_seconds
            if market.tier == "hot"
            else settings.monitoring_warm_refresh_seconds
        )
        try:
            if market.venue == "polymarket":
                url = (
                    f"{settings.gamma_base_url}/events/slug/"
                    f"{quote(market.identifier, safe='')}"
                )
                payload = await fetch_json(
                    url,
                    cache_ttl_seconds=max(interval - 1, 1),
                    stale_if_error_seconds=settings.market_catalog_stale_if_error_seconds,
                )
                event = payload[0] if isinstance(payload, list) and payload else payload
                if not isinstance(event, dict):
                    raise RuntimeError("Polymarket event refresh returned no event")
                compact = compact_polymarket_event(event)
            else:
                payload = await fetch_kalshi_events([market.identifier])
                events = payload.get("events", []) if isinstance(payload, dict) else []
                event = next(
                    (
                        item
                        for item in events
                        if isinstance(item, dict)
                        and item.get("event_ticker") == market.identifier
                    ),
                    None,
                )
                if event is None:
                    raise RuntimeError("Kalshi event refresh returned no event")
                compact = compact_kalshi_event(event)

            await market_catalog_service.replace_event(
                market.venue,
                market.identifier,
                compact,
            )
            async with self._lock:
                self._last_success_at[key] = datetime.now(timezone.utc).isoformat()
                self._last_error.pop(key, None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self._lock:
                self._last_error[key] = type(error).__name__
        finally:
            jitter = random.uniform(0.9, 1.1)
            async with self._lock:
                self._due_at[key] = time.monotonic() + interval * jitter

    async def _ensure_hot_polymarket_streams(self) -> None:
        settings = get_settings()
        if not settings.live_stream_enabled:
            return
        async with self._lock:
            hot = sorted(
                (
                    item for item in self._assignments.values()
                    if item.venue == "polymarket" and item.tier == "hot"
                ),
                key=lambda item: -item.activity_score,
            )[: max(settings.monitoring_polymarket_hot_streams, 0)]
        health = await live_stream_manager.get_registry_health()
        existing_slugs = {status.market_slug for status in health.streams}
        proactive_capacity = max(health.max_markets - 2, 1)
        registry_size = health.registry_size
        for market in hot:
            if (
                market.identifier not in existing_slugs
                and registry_size >= proactive_capacity
            ):
                continue
            await live_stream_manager.ensure_stream(market.identifier)
            if market.identifier not in existing_slugs:
                existing_slugs.add(market.identifier)
                registry_size += 1

    async def _run(self) -> None:
        settings = get_settings()
        next_rebuild = 0.0
        while not self._stop_requested:
            try:
                now = time.monotonic()
                if now >= next_rebuild:
                    await self.rebuild_assignments()
                    next_rebuild = (
                        now + settings.market_catalog_sync_interval_seconds
                    )
                await self.run_due_refreshes()
                await asyncio.sleep(max(settings.monitoring_scheduler_tick_seconds, 0.1))
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)


market_monitoring_service = MarketMonitoringService()
