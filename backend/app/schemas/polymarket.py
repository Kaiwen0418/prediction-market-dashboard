from typing import Any, Literal

from pydantic import BaseModel, Field


class MarketProxyResponse(BaseModel):
    payload: dict[str, Any] | list[Any]


class FeaturedMarketResponse(BaseModel):
    market_id: str = Field(alias="marketId")
    condition_id: str | None = Field(default=None, alias="conditionId")
    event_id: str | None = Field(default=None, alias="eventId")
    token_id: str | None = Field(default=None, alias="tokenId")
    slug: str
    event_slug: str | None = Field(default=None, alias="eventSlug")
    title: str
    category: str
    probability: float
    volume24h: float
    open_interest: float = Field(alias="openInterest")
    liquidity: float | None = None
    image: str | None = None
    description: str | None = None
    outcome_label: str | None = Field(default=None, alias="outcomeLabel")
    contract_label: str | None = Field(default=None, alias="contractLabel")
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class PricePoint(BaseModel):
    timestamp: str
    value: float


class OrderbookLevel(BaseModel):
    price: float
    size: float


class TradePrint(BaseModel):
    id: str
    side: str
    price: float
    size: float
    timestamp: str
    wallet_address: str | None = Field(default=None, alias="walletAddress")

    model_config = {"populate_by_name": True}


class OrderbookSnapshot(BaseModel):
    market_id: str = Field(alias="marketId")
    token_id: str | None = Field(default=None, alias="tokenId")
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]
    trades: list[TradePrint] = Field(default_factory=list)
    spread: float
    mid_price: float = Field(alias="midPrice")
    tick_size: float | None = Field(default=None, alias="tickSize")
    source: str = "live"
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class LiquiditySummary(BaseModel):
    total_bid_depth: float = Field(alias="totalBidDepth")
    total_ask_depth: float = Field(alias="totalAskDepth")
    imbalance: float
    spread_bps: float = Field(alias="spreadBps")

    model_config = {"populate_by_name": True}


class TradePressureSummary(BaseModel):
    buy_volume: float = Field(alias="buyVolume")
    sell_volume: float = Field(alias="sellVolume")
    ratio: float
    pressure: str

    model_config = {"populate_by_name": True}


class LargeTradeResponse(BaseModel):
    trade_id: str = Field(alias="tradeId")
    side: Literal["buy", "sell"]
    price: float
    size: float
    timestamp: str
    notional_usd: float = Field(alias="notionalUsd")
    historical_size_multiple: float = Field(alias="historicalSizeMultiple")
    executable_depth_share: float = Field(alias="executableDepthShare")
    wallet_address: str | None = Field(default=None, alias="walletAddress")

    model_config = {"populate_by_name": True}


class WhaleActivityResponse(BaseModel):
    status: Literal["insufficient-data", "clear", "detected"]
    sample_size: int = Field(alias="sampleSize")
    median_trade_size: float = Field(alias="medianTradeSize")
    historical_multiple_threshold: float = Field(alias="historicalMultipleThreshold")
    depth_share_threshold: float = Field(alias="depthShareThreshold")
    minimum_sample_size: int = Field(alias="minimumSampleSize")
    attribution_available: bool = Field(default=False, alias="attributionAvailable")
    attributed_trade_count: int = Field(default=0, alias="attributedTradeCount")
    unique_wallet_count: int = Field(default=0, alias="uniqueWalletCount")
    wallet_sample_minimum: int = Field(default=10, alias="walletSampleMinimum")
    wallet_concentration_status: Literal["unavailable", "insufficient-data", "available"] = Field(
        default="unavailable",
        alias="walletConcentrationStatus",
    )
    wallet_concentration_score: float | None = Field(default=None, alias="walletConcentrationScore")
    top_wallet_volume_share: float | None = Field(default=None, alias="topWalletVolumeShare")
    wallet_reputation_status: Literal["unavailable", "insufficient-history", "available"] = Field(
        default="unavailable",
        alias="walletReputationStatus",
    )
    wallet_reputation_score: float | None = Field(default=None, alias="walletReputationScore")
    wallet_resolved_market_count: int = Field(default=0, alias="walletResolvedMarketCount")
    wallet_resolved_market_minimum: int = Field(default=5, alias="walletResolvedMarketMinimum")
    large_trades: list[LargeTradeResponse] = Field(default_factory=list, alias="largeTrades")

    model_config = {"populate_by_name": True}


def default_whale_activity() -> WhaleActivityResponse:
    return WhaleActivityResponse(
        status="insufficient-data",
        sampleSize=0,
        medianTradeSize=0,
        historicalMultipleThreshold=3.0,
        depthShareThreshold=0.05,
        minimumSampleSize=5,
        attributionAvailable=False,
        attributedTradeCount=0,
        uniqueWalletCount=0,
        walletSampleMinimum=10,
        walletConcentrationStatus="unavailable",
        walletConcentrationScore=None,
        topWalletVolumeShare=None,
        walletReputationStatus="unavailable",
        walletReputationScore=None,
        walletResolvedMarketCount=0,
        walletResolvedMarketMinimum=5,
        largeTrades=[],
    )


class OrderbookSummaryResponse(BaseModel):
    market_id: str = Field(alias="marketId")
    token_id: str = Field(alias="tokenId")
    updated_at: str = Field(alias="updatedAt")
    best_bid: float = Field(alias="bestBid")
    best_ask: float = Field(alias="bestAsk")
    mid_price: float = Field(alias="midPrice")
    spread: float
    bid_levels: int = Field(alias="bidLevels")
    ask_levels: int = Field(alias="askLevels")
    trade_count: int = Field(alias="tradeCount")
    liquidity: LiquiditySummary
    trade_pressure: TradePressureSummary = Field(alias="tradePressure")
    whale_activity: WhaleActivityResponse = Field(
        default_factory=default_whale_activity,
        alias="whaleActivity",
    )

    model_config = {"populate_by_name": True}


class PriceHistoryMetaResponse(BaseModel):
    market: str
    points: int
    start_timestamp: str | None = Field(default=None, alias="startTimestamp")
    end_timestamp: str | None = Field(default=None, alias="endTimestamp")

    model_config = {"populate_by_name": True}


class TimelineEventResponse(BaseModel):
    id: str
    event_id: str | None = Field(default=None, alias="eventId")
    timestamp: str
    headline: str
    source: str
    category: str | None = None
    impact_score: int = Field(alias="impactScore")
    market_move: float = Field(alias="marketMove")
    summary: str

    model_config = {"populate_by_name": True}


class MarketContextResponse(BaseModel):
    featured_market: FeaturedMarketResponse = Field(alias="featuredMarket")
    orderbook_summary: OrderbookSummaryResponse | None = Field(default=None, alias="orderbookSummary")
    price_history_meta: PriceHistoryMetaResponse = Field(alias="priceHistoryMeta")
    timeline_events: list[TimelineEventResponse] = Field(default_factory=list, alias="timelineEvents")

    model_config = {"populate_by_name": True}
