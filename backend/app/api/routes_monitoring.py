from typing import Any

from fastapi import APIRouter

from app.services.market_monitoring import market_monitoring_service


router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/status")
async def get_monitoring_status() -> dict[str, Any]:
    return await market_monitoring_service.get_status()
