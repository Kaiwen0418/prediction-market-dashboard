from pydantic import BaseModel, Field

from app.schemas.analytics import (
    CorrelationResponse,
    DivergenceResponse,
    EventWindowResponse,
    LeadLagResponse,
    RollingCorrelationResponse,
    VolatilityResponse,
)


class PollPointResponse(BaseModel):
    timestamp: str
    poll_average: float = Field(alias="pollAverage")
    sample_size: int = Field(default=0, alias="sampleSize")
    source: str
    source_url: str | None = Field(default=None, alias="sourceUrl")
    field_date_label: str | None = Field(default=None, alias="fieldDateLabel")
    methodology: str | None = None
    candidate: str | None = None

    model_config = {"populate_by_name": True}


class TimePointResponse(BaseModel):
    timestamp: str
    value: float


class ResearchProvenanceResponse(BaseModel):
    computed_at: str = Field(alias="computedAt")
    poll_dataset_generated_at: str | None = Field(default=None, alias="pollDatasetGeneratedAt")
    market_dataset_generated_at: str | None = Field(default=None, alias="marketDatasetGeneratedAt")

    model_config = {"populate_by_name": True}


class ResearchHighlightsResponse(BaseModel):
    shock_label: str = Field(alias="shockLabel")
    lead_lag_label: str = Field(alias="leadLagLabel")
    divergence_label: str = Field(alias="divergenceLabel")

    model_config = {"populate_by_name": True}


class ResearchCoverageResponse(BaseModel):
    poll_start: str | None = Field(default=None, alias="pollStart")
    poll_end: str | None = Field(default=None, alias="pollEnd")
    poll_points: int = Field(alias="pollPoints")
    market_start: str | None = Field(default=None, alias="marketStart")
    market_end: str | None = Field(default=None, alias="marketEnd")
    market_points: int = Field(alias="marketPoints")
    aligned_start: str | None = Field(default=None, alias="alignedStart")
    aligned_end: str | None = Field(default=None, alias="alignedEnd")
    aligned_points: int = Field(alias="alignedPoints")

    model_config = {"populate_by_name": True}


class ResearchNarrativeResponse(BaseModel):
    overview: str
    methodology: str


class ComparedMarketResponse(BaseModel):
    label: str
    probability: float
    observed_at: str = Field(alias="observedAt")
    source_url: str = Field(alias="sourceUrl")

    model_config = {"populate_by_name": True}


class RelatedMarketDivergenceResponse(BaseModel):
    primary: ComparedMarketResponse
    related: ComparedMarketResponse
    raw_probability_sum: float = Field(alias="rawProbabilitySum")
    raw_gap_points: float = Field(alias="rawGapPoints")
    fee_bps_per_leg: float = Field(alias="feeBpsPerLeg")
    fee_buffer_points: float = Field(alias="feeBufferPoints")
    actionable_gap_points: float = Field(alias="actionableGapPoints")
    liquidity_usd: float | None = Field(default=None, alias="liquidityUsd")
    minimum_liquidity_usd: float = Field(alias="minimumLiquidityUsd")
    status: str
    explanation: str

    model_config = {"populate_by_name": True}


class CatalystEventResponse(BaseModel):
    id: str
    headline: str
    event_type: str = Field(alias="eventType")
    occurred_at: str = Field(alias="occurredAt")
    source_name: str = Field(alias="sourceName")
    source_url: str = Field(alias="sourceUrl")
    matched_market_timestamp: str = Field(alias="matchedMarketTimestamp")
    market_move: float = Field(alias="marketMove")
    summary: str

    model_config = {"populate_by_name": True}


class ElectionModelComparisonResponse(BaseModel):
    model_name: str = Field(alias="modelName")
    model_probability: float = Field(alias="modelProbability")
    market_probability: float = Field(alias="marketProbability")
    divergence_points: float = Field(alias="divergencePoints")
    poll_observed_at: str = Field(alias="pollObservedAt")
    market_observed_at: str = Field(alias="marketObservedAt")
    source_url: str = Field(alias="sourceUrl")
    methodology: str

    model_config = {"populate_by_name": True}


class ResearchStateSummaryResponse(BaseModel):
    state: str
    event_slug: str = Field(alias="eventSlug")
    party: str
    summary: str
    analytics_source: str = Field(alias="analyticsSource")
    research_source: str = Field(alias="researchSource")
    market_series: list[TimePointResponse] = Field(alias="marketSeries")
    poll_series: list[PollPointResponse] = Field(alias="pollSeries")
    lead_lag: LeadLagResponse = Field(alias="leadLag")
    correlation: CorrelationResponse
    volatility: VolatilityResponse
    divergence: DivergenceResponse
    rolling_correlation: RollingCorrelationResponse = Field(alias="rollingCorrelation")
    event_window: EventWindowResponse = Field(alias="eventWindow")
    provenance: ResearchProvenanceResponse
    research_highlights: ResearchHighlightsResponse = Field(alias="researchHighlights")
    coverage: ResearchCoverageResponse
    narrative: ResearchNarrativeResponse
    source_urls: list[str] = Field(alias="sourceUrls")
    related_market_divergence: RelatedMarketDivergenceResponse = Field(alias="relatedMarketDivergence")
    election_model_comparison: ElectionModelComparisonResponse = Field(alias="electionModelComparison")
    catalysts: list[CatalystEventResponse]

    model_config = {"populate_by_name": True}


class ResearchOverviewItemResponse(BaseModel):
    state: str
    event_slug: str = Field(alias="eventSlug")
    party: str
    lead_lag_days: int = Field(alias="leadLagDays")
    correlation: float
    divergence: float
    volatility: float
    aligned_points: int = Field(alias="alignedPoints")

    model_config = {"populate_by_name": True}


class ResearchOverviewResponse(BaseModel):
    party: str
    computed_at: str = Field(alias="computedAt")
    source: str = "api"
    items: list[ResearchOverviewItemResponse]

    model_config = {"populate_by_name": True}
