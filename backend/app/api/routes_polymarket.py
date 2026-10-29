from fastapi import APIRouter, Query, Response

from app.core.config import get_settings
from app.services.polymarket import (
    fetch_featured_market,
    fetch_market_events,
    fetch_market_context,
    fetch_orderbook,
    fetch_orderbook_summary,
    fetch_price_history,
    fetch_trades,
    normalize_featured_market_from_event,
)
from app.schemas.polymarket import MarketContextResponse, OrderbookSummaryResponse

router = APIRouter(prefix="/api/polymarket", tags=["polymarket"])


@router.get("/events")
async def get_market_events(
    response: Response,
    slugs: str = Query(...),
) -> dict[str, list[dict]]:
    response.headers["Cache-Control"] = (
        "public, s-maxage=300, stale-while-revalidate=3600, stale-if-error=3600"
    )
    events = await fetch_market_events(slugs.split(","))
    markets: list[dict] = []
    for event in events:
        try:
            market = normalize_featured_market_from_event(event).model_dump(
                by_alias=True
            )
        except Exception:
            continue
        market.update(
            {
                "venue": "Polymarket",
                "status": (
                    "open"
                    if isinstance(event, dict)
                    and event.get("active") is True
                    and event.get("closed") is False
                    else "unknown"
                ),
                "endDate": event.get("endDate") if isinstance(event, dict) else None,
                "resolutionSource": (
                    event.get("resolutionSource")
                    if isinstance(event, dict)
                    else None
                ),
            }
        )
        markets.append(market)
    return {"markets": markets}


@router.get("/featured-market")
async def get_featured_market(
    response: Response,
    slug: str | None = Query(default=None),
) -> dict | list:
    settings = get_settings()
    response.headers["Cache-Control"] = (
        f"public, max-age=60, "
        f"s-maxage={settings.polymarket_market_cache_ttl_seconds}, "
        f"stale-while-revalidate={settings.polymarket_market_stale_if_error_seconds}, "
        f"stale-if-error={settings.polymarket_market_stale_if_error_seconds}"
    )
    return await fetch_featured_market(slug)


@router.get("/market-context", response_model=MarketContextResponse)
async def get_market_context(slug: str | None = Query(default=None)) -> MarketContextResponse:
    return await fetch_market_context(slug)


@router.get("/orderbook")
async def get_orderbook(
    response: Response,
    tokenId: str = Query(...),
) -> dict | list:
    response.headers["Cache-Control"] = "public, s-maxage=2, stale-while-revalidate=15"
    return await fetch_orderbook(tokenId)


@router.get("/orderbook-summary", response_model=OrderbookSummaryResponse)
async def get_orderbook_summary(
    tokenId: str = Query(...),
    conditionId: str | None = Query(default=None),
) -> OrderbookSummaryResponse:
    return await fetch_orderbook_summary(tokenId, conditionId)


@router.get("/price-history")
async def get_price_history(
    response: Response,
    market: str = Query(...),
) -> dict | list:
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=3600"
    return await fetch_price_history(market)


@router.get("/trades")
async def get_trades(
    response: Response,
    conditionId: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
) -> dict | list:
    response.headers["Cache-Control"] = "public, s-maxage=3, stale-while-revalidate=15"
    return await fetch_trades(conditionId, limit)
