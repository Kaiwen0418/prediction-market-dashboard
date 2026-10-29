from typing import Any

from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.services.market_catalog import market_catalog_service


router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/markets")
async def get_market_catalog(response: Response) -> dict[str, Any]:
    settings = get_settings()
    response.headers["Cache-Control"] = (
        f"public, s-maxage={settings.market_catalog_sync_interval_seconds}, "
        f"stale-while-revalidate={settings.market_catalog_stale_if_error_seconds}, "
        f"stale-if-error={settings.market_catalog_stale_if_error_seconds}"
    )
    return await market_catalog_service.get_catalog()
