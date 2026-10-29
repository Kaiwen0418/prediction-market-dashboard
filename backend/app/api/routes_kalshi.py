from typing import Any

from fastapi import APIRouter, Query, Response

from app.services.kalshi import fetch_kalshi_analytics, fetch_kalshi_events


router = APIRouter(prefix="/api/kalshi", tags=["kalshi"])


@router.get("/events")
async def get_kalshi_events(
    response: Response,
    tickers: str = Query(...),
) -> Any:
    response.headers["Cache-Control"] = (
        "public, s-maxage=15, stale-while-revalidate=60, stale-if-error=300"
    )
    return await fetch_kalshi_events(tickers.split(","))


@router.get("/analytics")
async def get_kalshi_analytics(
    response: Response,
    ticker: str = Query(...),
    seriesTicker: str = Query(...),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = (
        "public, s-maxage=10, stale-while-revalidate=60, stale-if-error=300"
    )
    return await fetch_kalshi_analytics(ticker, seriesTicker)
