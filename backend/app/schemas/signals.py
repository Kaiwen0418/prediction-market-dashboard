from typing import Literal

from pydantic import BaseModel, Field


SignalKind = Literal[
    "whale-flow",
    "order-flow",
    "volume-anomaly",
    "price-move",
    "poll-divergence",
    "normal",
]
SignalSeverity = Literal["normal", "elevated", "high", "critical"]
SignalSource = Literal["fixture", "live"]
SignalBatchSource = Literal["fixture", "mixed", "live"]
SignalFreshness = Literal["fixture", "fresh", "stale"]


class SignalComponentResponse(BaseModel):
    key: str
    label: str
    value: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0)
    available: bool
    detail: str


class RegionSignalResponse(BaseModel):
    region_code: str = Field(alias="regionCode")
    country_code: str = Field(alias="countryCode")
    market_slug: str = Field(alias="marketSlug")
    kind: SignalKind
    score: int = Field(ge=0, le=100)
    severity: SignalSeverity
    headline: str
    detail: str
    observed_at: str = Field(alias="observedAt")
    source: SignalSource
    confidence: float = Field(ge=0, le=1)
    baseline_window: str = Field(alias="baselineWindow")
    components: list[SignalComponentResponse]
    freshness: SignalFreshness = "fixture"
    age_seconds: int | None = Field(default=None, alias="ageSeconds", ge=0)
    degradation_reasons: list[str] = Field(default_factory=list, alias="degradationReasons")

    model_config = {"populate_by_name": True}


class RegionSignalsResponse(BaseModel):
    country_code: str = Field(alias="countryCode")
    generated_at: str = Field(alias="generatedAt")
    source: SignalBatchSource
    signals: list[RegionSignalResponse]
    freshness: SignalFreshness = "fixture"
    degradation_reasons: list[str] = Field(default_factory=list, alias="degradationReasons")

    model_config = {"populate_by_name": True}
