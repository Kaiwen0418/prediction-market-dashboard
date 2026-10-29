import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode
from weakref import WeakValueDictionary

import httpx
from fastapi import HTTPException

from app.core.config import get_settings
from app.services.upstream_rate_limit import upstream_rate_limiter
from app.schemas.polymarket import (
    FeaturedMarketResponse,
    LargeTradeResponse,
    LiquiditySummary,
    MarketContextResponse,
    OrderbookLevel,
    OrderbookSummaryResponse,
    PriceHistoryMetaResponse,
    TimelineEventResponse,
    TradePressureSummary,
    TradePrint,
    WhaleActivityResponse,
)
from app.analytics.whale_activity import (
    DEPTH_SHARE_THRESHOLD,
    HISTORICAL_MULTIPLE_THRESHOLD,
    MINIMUM_SAMPLE_SIZE,
    WALLET_SAMPLE_MINIMUM,
    WALLET_RESOLVED_MARKET_MINIMUM,
    analyze_whale_activity,
)


WALLET_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


@dataclass(frozen=True)
class CachedJsonResponse:
    payload: Any
    stored_at: float


class JsonResponseCache:
    def __init__(self) -> None:
        self._entries: dict[str, CachedJsonResponse] = {}
        self._locks: WeakValueDictionary[str, asyncio.Lock] = (
            WeakValueDictionary()
        )

    def get(self, url: str, max_age_seconds: float, now: float | None = None) -> Any | None:
        entry = self._entries.get(url)
        if entry is None:
            return None
        current_time = time.monotonic() if now is None else now
        if current_time - entry.stored_at > max_age_seconds:
            return None
        return entry.payload

    def put(self, url: str, payload: Any, now: float | None = None) -> None:
        if len(self._entries) >= 2_048 and url not in self._entries:
            oldest_url = min(
                self._entries,
                key=lambda key: self._entries[key].stored_at,
            )
            self._entries.pop(oldest_url, None)
        self._entries[url] = CachedJsonResponse(
            payload=payload,
            stored_at=time.monotonic() if now is None else now,
        )

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()

    def lock_for(self, url: str) -> asyncio.Lock:
        lock = self._locks.get(url)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[url] = lock
        return lock


json_response_cache = JsonResponseCache()


async def fetch_json(
    url: str,
    cache_ttl_seconds: int = 0,
    stale_if_error_seconds: int = 0,
) -> Any:
    if cache_ttl_seconds > 0:
        cached = json_response_cache.get(url, cache_ttl_seconds)
        if cached is not None:
            return cached

        async with json_response_cache.lock_for(url):
            cached = json_response_cache.get(url, cache_ttl_seconds)
            if cached is not None:
                return cached
            return await _fetch_json_upstream(
                url,
                cache_ttl_seconds,
                stale_if_error_seconds,
            )

    return await _fetch_json_upstream(
        url,
        cache_ttl_seconds,
        stale_if_error_seconds,
    )


async def _fetch_json_upstream(
    url: str,
    cache_ttl_seconds: int,
    stale_if_error_seconds: int,
) -> Any:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    try:
        await upstream_rate_limiter.acquire_url(url)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/json"})

        if response.status_code >= 400:
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    cooldown_seconds = min(max(float(retry_after), 1.0), 60.0)
                except ValueError:
                    cooldown_seconds = 1.0
                upstream_rate_limiter.penalize_url(url, cooldown_seconds)
            raise HTTPException(status_code=response.status_code, detail=response.text)

        payload = response.json()
        if cache_ttl_seconds > 0:
            json_response_cache.put(url, payload)
        return payload
    except HTTPException as error:
        can_use_stale = error.status_code == 429 or error.status_code >= 500
        stale = (
            json_response_cache.get(
                url,
                cache_ttl_seconds + stale_if_error_seconds,
            )
            if can_use_stale and stale_if_error_seconds > 0
            else None
        )
        if stale is not None:
            return stale
        raise
    except httpx.HTTPError as error:
        stale = (
            json_response_cache.get(
                url,
                cache_ttl_seconds + stale_if_error_seconds,
            )
            if stale_if_error_seconds > 0
            else None
        )
        if stale is not None:
            return stale
        raise HTTPException(status_code=502, detail="Upstream market request failed") from error


async def fetch_featured_market(slug: str | None = None) -> Any:
    settings = get_settings()
    selected_slug = (slug or settings.featured_market_slug).strip()
    if not selected_slug:
        raise HTTPException(status_code=400, detail="slug is required")

    by_slug_url = f"{settings.gamma_base_url}/events/slug/{quote(selected_slug, safe='')}"
    try:
        return await fetch_json(
            by_slug_url,
            cache_ttl_seconds=settings.polymarket_market_cache_ttl_seconds,
            stale_if_error_seconds=settings.polymarket_market_stale_if_error_seconds,
        )
    except HTTPException:
        fallback_url = f"{settings.gamma_base_url}/events?slug={quote(selected_slug, safe='')}"
        return await fetch_json(
            fallback_url,
            cache_ttl_seconds=settings.polymarket_market_cache_ttl_seconds,
            stale_if_error_seconds=settings.polymarket_market_stale_if_error_seconds,
        )


async def fetch_market_events(slugs: list[str]) -> list[Any]:
    settings = get_settings()
    normalized_slugs = list(
        dict.fromkeys(slug.strip() for slug in slugs if slug.strip())
    )[:100]
    if not normalized_slugs:
        raise HTTPException(status_code=400, detail="slugs are required")
    if any(len(slug) > 220 for slug in normalized_slugs):
        raise HTTPException(status_code=400, detail="invalid market slug")

    query = urlencode(
        [
            *[("slug", slug) for slug in normalized_slugs],
            ("closed", "false"),
            ("limit", str(len(normalized_slugs))),
        ]
    )
    payload = await fetch_json(
        f"{settings.gamma_base_url}/events/keyset?{query}",
        cache_ttl_seconds=settings.polymarket_market_cache_ttl_seconds,
        stale_if_error_seconds=settings.polymarket_market_stale_if_error_seconds,
    )
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return events if isinstance(events, list) else []


async def fetch_orderbook(token_id: str) -> Any:
    settings = get_settings()
    if not token_id.strip():
        raise HTTPException(status_code=400, detail="tokenId is required")
    url = f"{settings.clob_base_url}/book?token_id={quote(token_id, safe='')}"
    return await fetch_json(
        url,
        cache_ttl_seconds=settings.polymarket_orderbook_cache_ttl_seconds,
        stale_if_error_seconds=settings.polymarket_realtime_stale_if_error_seconds,
    )


async def fetch_price_history(market: str) -> Any:
    settings = get_settings()
    if not market.strip():
        raise HTTPException(status_code=400, detail="market is required")
    url = f"{settings.clob_base_url}/prices-history?interval=all&market={quote(market, safe='')}&fidelity=720"
    return await fetch_json(
        url,
        cache_ttl_seconds=settings.polymarket_history_cache_ttl_seconds,
        stale_if_error_seconds=settings.polymarket_market_stale_if_error_seconds,
    )


async def fetch_trades(condition_id: str | None = None, limit: int = 100) -> Any:
    settings = get_settings()
    safe_limit = max(1, min(limit, 100))
    market_query = (
        f"&market={quote(condition_id.strip(), safe='')}"
        if condition_id and condition_id.strip()
        else ""
    )
    url = f"{settings.data_api_base_url}/trades?limit={safe_limit}&takerOnly=true{market_query}"
    return await fetch_json(
        url,
        cache_ttl_seconds=settings.polymarket_trades_cache_ttl_seconds,
        stale_if_error_seconds=settings.polymarket_realtime_stale_if_error_seconds,
    )


def _as_number(value: Any, fallback: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return fallback
    return fallback


def _as_string(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _parse_json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _first_string(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def normalize_featured_market_from_event(payload: Any) -> FeaturedMarketResponse:
    if isinstance(payload, list):
        payload = payload[0] if payload else None

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Featured market payload was not an object")

    markets = payload.get("markets")
    if not isinstance(markets, list) or not markets:
        raise HTTPException(status_code=502, detail="Featured event did not include markets")

    candidates: list[FeaturedMarketResponse] = []
    for market in markets:
        if not isinstance(market, dict):
            continue
        token_ids = _parse_json_array(market.get("clobTokenIds"))
        outcomes = _parse_json_array(market.get("outcomes"))
        outcome_prices = _parse_json_array(market.get("outcomePrices"))
        token_id = _first_string([token_ids[0] if token_ids else None, market.get("clobTokenId"), market.get("conditionId")])
        if not token_id:
            continue
        contract_label = _as_string(market.get("question"), _as_string(market.get("title"), ""))
        outcome_label = _first_string([outcomes[0] if outcomes else None, contract_label, "Yes"])
        probability = _as_number(outcome_prices[0] if outcome_prices else None, _as_number(market.get("lastTradePrice"), 0.5))
        candidates.append(
            FeaturedMarketResponse(
                marketId=_as_string(market.get("id"), _as_string(market.get("conditionId"), token_id)),
                conditionId=_as_string(market.get("conditionId")) or None,
                eventId=_as_string(payload.get("id")) or None,
                tokenId=token_id,
                slug=_as_string(payload.get("slug"), token_id),
                eventSlug=_as_string(payload.get("slug"), token_id),
                title=_as_string(payload.get("title"), _as_string(payload.get("slug"), token_id)),
                category=_as_string(payload.get("category"), _as_string(market.get("category"), "Politics")),
                probability=probability,
                volume24h=_as_number(market.get("volume24hr"), _as_number(payload.get("volume24hr"))),
                openInterest=_as_number(market.get("openInterest"), _as_number(payload.get("openInterest"))),
                liquidity=_as_number(market.get("liquidity"), _as_number(payload.get("liquidity"))),
                image=_as_string(payload.get("image")) or None,
                description=_as_string(payload.get("description")) or None,
                outcomeLabel=outcome_label,
                contractLabel=contract_label or None,
                updatedAt=datetime.now(timezone.utc).isoformat(),
            )
        )

    if not candidates:
        raise HTTPException(status_code=502, detail="Featured event did not yield a usable token")

    return sorted(candidates, key=lambda candidate: candidate.probability, reverse=True)[0]


def _normalize_price_history_rows(payload: Any) -> list[tuple[str, float]]:
    rows = (
        payload
        if isinstance(payload, list)
        else payload.get("history", [])
        if isinstance(payload, dict)
        else []
    )
    normalized: list[tuple[str, float]] = []
    if not isinstance(rows, list):
        return normalized

    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp_value = row.get("t", row.get("timestamp"))
        price_value = _as_number(row.get("p", row.get("price")))
        if price_value <= 0:
            continue
        if isinstance(timestamp_value, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp_value, tz=timezone.utc).isoformat()
        elif isinstance(timestamp_value, str) and timestamp_value:
            timestamp = timestamp_value
        else:
            continue
        normalized.append((timestamp, price_value))
    return normalized


def _build_timeline_events(
    event_id: str | None,
    title: str,
    history: list[tuple[str, float]],
) -> list[TimelineEventResponse]:
    if len(history) < 2:
        return []

    ranked_moves: list[tuple[int, float]] = []
    for index in range(1, len(history)):
        move = history[index][1] - history[index - 1][1]
        ranked_moves.append((index, move))

    ranked_moves.sort(key=lambda item: abs(item[1]), reverse=True)
    selected: list[tuple[int, float]] = []
    used_indices: set[int] = set()
    for index, move in ranked_moves:
        if index in used_indices or index - 1 in used_indices or index + 1 in used_indices:
            continue
        selected.append((index, move))
        used_indices.add(index)
        if len(selected) == 4:
            break

    selected.sort(key=lambda item: item[0])
    events: list[TimelineEventResponse] = []
    for rank, (index, move) in enumerate(selected):
        timestamp, value = history[index]
        direction = "up" if move > 0 else "down"
        move_points = round(move * 100, 2)
        events.append(
            TimelineEventResponse(
                id=f"{event_id or title}-{index}-{rank}",
                eventId=event_id,
                timestamp=timestamp,
                headline=(
                    f"{title} repriced {direction} by {abs(move_points):.1f} pts"
                ),
                source="Polymarket price history",
                category="market",
                impactScore=min(100, max(1, int(round(abs(move_points) * 4)))),
                marketMove=move_points,
                summary=(
                    f"Automated market-context annotation derived from the largest one-step move in the cached price history. "
                    f"Contract probability moved to {value * 100:.1f}% at this point."
                ),
            )
        )

    return events


def _normalize_levels(value: Any) -> list[OrderbookLevel]:
    if not isinstance(value, list):
        return []

    levels: list[OrderbookLevel] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        price = _as_number(row.get("price"))
        size = _as_number(row.get("size"))
        if price > 0 and size > 0:
            levels.append(OrderbookLevel(price=price, size=size))
    return levels


def _normalize_trades(value: Any) -> list[TradePrint]:
    if not isinstance(value, list):
        return []

    trades: list[TradePrint] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            continue
        side = "sell" if _as_string(row.get("side")).lower() == "sell" else "buy"
        raw_timestamp = row.get("timestamp")
        if isinstance(raw_timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc).isoformat()
        else:
            timestamp = _as_string(raw_timestamp, datetime.now(timezone.utc).isoformat())
        price = _as_number(row.get("price"))
        size = _as_number(row.get("size"))
        wallet_address = _as_string(row.get("proxyWallet"), _as_string(row.get("proxy_wallet")))
        if not WALLET_ADDRESS_PATTERN.fullmatch(wallet_address):
            wallet_address = ""
        else:
            wallet_address = wallet_address.lower()
        if price <= 0 or size <= 0:
            continue
        trades.append(
            TradePrint(
                id=_as_string(
                    row.get("id"),
                    _as_string(row.get("transactionHash"), f"trade-{index}"),
                ),
                side=side,
                price=price,
                size=size,
                timestamp=timestamp,
                walletAddress=wallet_address or None,
            )
        )
    return trades


async def fetch_orderbook_summary(
    token_id: str,
    condition_id: str | None = None,
) -> OrderbookSummaryResponse:
    if not token_id.strip():
        raise HTTPException(status_code=400, detail="tokenId is required")

    orderbook_payload, trades_payload = await asyncio.gather(
        fetch_orderbook(token_id),
        fetch_trades(condition_id) if condition_id else asyncio.sleep(0, result=[]),
        return_exceptions=True,
    )

    if isinstance(orderbook_payload, HTTPException):
        raise orderbook_payload
    if isinstance(orderbook_payload, BaseException):
        raise HTTPException(status_code=502, detail="Orderbook request failed") from orderbook_payload
    if not isinstance(orderbook_payload, dict):
        raise HTTPException(status_code=502, detail="Orderbook payload was not an object")
    if isinstance(trades_payload, BaseException):
        trades_payload = []

    bids = _normalize_levels(orderbook_payload.get("bids"))
    asks = _normalize_levels(orderbook_payload.get("asks"))
    trades = _normalize_trades(trades_payload)

    best_bid = bids[0].price if bids else 0.0
    best_ask = asks[0].price if asks else 0.0
    mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else best_bid or best_ask
    spread = best_ask - best_bid if best_bid and best_ask else 0.0

    total_bid_depth = sum(level.size for level in bids)
    total_ask_depth = sum(level.size for level in asks)
    imbalance_base = total_bid_depth + total_ask_depth
    imbalance = (total_bid_depth - total_ask_depth) / imbalance_base if imbalance_base else 0.0
    spread_bps = (spread / mid_price) * 10_000 if mid_price else 0.0

    buy_volume = sum(trade.size for trade in trades if trade.side == "buy")
    sell_volume = sum(trade.size for trade in trades if trade.side == "sell")
    ratio = buy_volume if sell_volume == 0 else buy_volume / sell_volume
    pressure = "buy" if ratio > 1.15 else "sell" if ratio < 0.87 else "balanced"
    whale_activity = analyze_whale_activity(
        trades,
        total_bid_depth=total_bid_depth,
        total_ask_depth=total_ask_depth,
    )

    return OrderbookSummaryResponse(
        marketId=_as_string(orderbook_payload.get("market"), token_id),
        tokenId=token_id,
        updatedAt=datetime.now(timezone.utc).isoformat(),
        bestBid=round(best_bid, 4),
        bestAsk=round(best_ask, 4),
        midPrice=round(mid_price, 4),
        spread=round(spread, 4),
        bidLevels=len(bids),
        askLevels=len(asks),
        tradeCount=len(trades),
        liquidity=LiquiditySummary(
            totalBidDepth=round(total_bid_depth, 4),
            totalAskDepth=round(total_ask_depth, 4),
            imbalance=round(imbalance, 3),
            spreadBps=round(spread_bps, 1),
        ),
        tradePressure=TradePressureSummary(
            buyVolume=round(buy_volume, 4),
            sellVolume=round(sell_volume, 4),
            ratio=round(ratio, 2),
            pressure=pressure,
        ),
        whaleActivity=WhaleActivityResponse(
            status=whale_activity.status,
            sampleSize=whale_activity.sample_size,
            medianTradeSize=whale_activity.median_trade_size,
            historicalMultipleThreshold=HISTORICAL_MULTIPLE_THRESHOLD,
            depthShareThreshold=DEPTH_SHARE_THRESHOLD,
            minimumSampleSize=MINIMUM_SAMPLE_SIZE,
            attributionAvailable=whale_activity.attributed_trade_count > 0,
            attributedTradeCount=whale_activity.attributed_trade_count,
            uniqueWalletCount=whale_activity.unique_wallet_count,
            walletSampleMinimum=WALLET_SAMPLE_MINIMUM,
            walletConcentrationStatus=whale_activity.wallet_concentration_status,
            walletConcentrationScore=whale_activity.wallet_concentration_score,
            topWalletVolumeShare=whale_activity.top_wallet_volume_share,
            walletReputationStatus=whale_activity.wallet_reputation_status,
            walletReputationScore=whale_activity.wallet_reputation_score,
            walletResolvedMarketCount=whale_activity.wallet_resolved_market_count,
            walletResolvedMarketMinimum=WALLET_RESOLVED_MARKET_MINIMUM,
            largeTrades=[
                LargeTradeResponse(
                    tradeId=detection.trade_id,
                    side=detection.side,
                    price=detection.price,
                    size=detection.size,
                    timestamp=detection.timestamp,
                    notionalUsd=detection.notional_usd,
                    historicalSizeMultiple=detection.historical_size_multiple,
                    executableDepthShare=detection.executable_depth_share,
                    walletAddress=detection.wallet_address,
                )
                for detection in whale_activity.detections
            ],
        ),
    )


async def fetch_market_context(slug: str | None = None) -> MarketContextResponse:
    featured_event = await fetch_featured_market(slug)
    featured_market = normalize_featured_market_from_event(featured_event)

    orderbook_summary = (
        await fetch_orderbook_summary(
            featured_market.token_id,
            featured_market.condition_id,
        )
        if featured_market.token_id
        else None
    )

    price_history_payload = await fetch_price_history(featured_market.token_id or featured_market.market_id)
    normalized_history = _normalize_price_history_rows(price_history_payload)

    start_timestamp: str | None = None
    end_timestamp: str | None = None
    normalized_points = len(normalized_history)
    if normalized_history:
        start_timestamp = normalized_history[0][0]
        end_timestamp = normalized_history[-1][0]

    return MarketContextResponse(
        featuredMarket=featured_market,
        orderbookSummary=orderbook_summary,
        priceHistoryMeta=PriceHistoryMetaResponse(
            market=featured_market.token_id or featured_market.market_id,
            points=normalized_points,
            startTimestamp=start_timestamp,
            endTimestamp=end_timestamp,
        ),
        timelineEvents=_build_timeline_events(
            featured_market.event_id,
            featured_market.title,
            normalized_history,
        ),
    )
