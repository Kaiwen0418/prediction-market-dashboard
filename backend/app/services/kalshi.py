import asyncio
import time
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException

from app.core.config import get_settings
from app.services.polymarket import fetch_json


def _validate_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized or len(normalized) > 100:
        raise HTTPException(status_code=400, detail="Invalid Kalshi ticker")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for character in normalized):
        raise HTTPException(status_code=400, detail="Invalid Kalshi ticker")
    return normalized


async def fetch_kalshi_events(event_tickers: list[str]) -> Any:
    settings = get_settings()
    tickers = list(dict.fromkeys(_validate_ticker(ticker) for ticker in event_tickers))[:20]
    if not tickers:
        raise HTTPException(status_code=400, detail="event tickers are required")

    query = urlencode(
        {
            "tickers": ",".join(tickers),
            "with_nested_markets": "true",
        }
    )
    return await fetch_json(
        f"{settings.kalshi_base_url}/events?{query}",
        cache_ttl_seconds=settings.kalshi_event_cache_ttl_seconds,
        stale_if_error_seconds=settings.kalshi_stale_if_error_seconds,
    )


async def fetch_kalshi_analytics(
    market_ticker: str,
    series_ticker: str,
) -> dict[str, Any]:
    settings = get_settings()
    ticker = _validate_ticker(market_ticker)
    series = _validate_ticker(series_ticker)
    end_timestamp = int(time.time() // 3600 * 3600)
    start_timestamp = end_timestamp - 14 * 24 * 60 * 60

    orderbook_url = (
        f"{settings.kalshi_base_url}/markets/{quote(ticker, safe='')}/orderbook?depth=100"
    )
    trades_url = (
        f"{settings.kalshi_base_url}/markets/trades?"
        f"{urlencode({'ticker': ticker, 'limit': 200})}"
    )
    candles_query = urlencode(
        {
            "start_ts": start_timestamp,
            "end_ts": end_timestamp,
            "period_interval": 60,
            "include_latest_before_start": "true",
        }
    )
    candles_url = (
        f"{settings.kalshi_base_url}/series/{quote(series, safe='')}/markets/"
        f"{quote(ticker, safe='')}/candlesticks?{candles_query}"
    )

    orderbook, trades, candlesticks = await asyncio.gather(
        fetch_json(
            orderbook_url,
            cache_ttl_seconds=settings.kalshi_analytics_cache_ttl_seconds,
            stale_if_error_seconds=settings.kalshi_stale_if_error_seconds,
        ),
        fetch_json(
            trades_url,
            cache_ttl_seconds=settings.kalshi_analytics_cache_ttl_seconds,
            stale_if_error_seconds=settings.kalshi_stale_if_error_seconds,
        ),
        fetch_json(
            candles_url,
            cache_ttl_seconds=settings.kalshi_history_cache_ttl_seconds,
            stale_if_error_seconds=settings.kalshi_stale_if_error_seconds,
        ),
        return_exceptions=True,
    )

    if all(isinstance(result, BaseException) for result in (orderbook, trades, candlesticks)):
        raise HTTPException(status_code=502, detail="Kalshi analytics requests failed")

    return {
        "ticker": ticker,
        "seriesTicker": series,
        "orderbook": None if isinstance(orderbook, BaseException) else orderbook,
        "trades": None if isinstance(trades, BaseException) else trades,
        "candlesticks": (
            None if isinstance(candlesticks, BaseException) else candlesticks
        ),
    }
