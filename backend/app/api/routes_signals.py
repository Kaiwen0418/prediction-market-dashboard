from fastapi import APIRouter, Query

from app.schemas.signals import RegionSignalsResponse
from app.services.region_signals import build_region_signals

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/regions", response_model=RegionSignalsResponse)
async def get_region_signals(
    country_code: str = Query(default="US", alias="countryCode", min_length=2, max_length=2),
    active_slug: str | None = Query(default=None, alias="activeSlug", min_length=1, max_length=200),
) -> RegionSignalsResponse:
    return await build_region_signals(country_code, active_slug)
