from typing import Any

from fastapi import APIRouter

from app.services.market_monitoring import market_monitoring_service
from app.services.polymarket import json_response_cache


router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/status")
async def get_monitoring_status() -> dict[str, Any]:
    status = await market_monitoring_service.get_status()
    status["responseCache"] = json_response_cache.stats()
    return status
