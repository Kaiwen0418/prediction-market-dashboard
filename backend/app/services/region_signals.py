from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.analytics.signals import (
    RegionActivityScore,
    calculate_region_activity_score,
    get_signal_severity,
)
from app.schemas.live import LiveMetricSampleResponse
from app.schemas.signals import (
    RegionSignalResponse,
    RegionSignalsResponse,
    SignalComponentResponse,
)
from app.streaming.polymarket_ws import live_stream_manager

LIVE_SIGNAL_STALE_AFTER_SECONDS = 90


@dataclass(frozen=True)
class CachedRegionBaseline:
    latest_timestamp: str
    sample_count: int
    activity: RegionActivityScore | None


class RegionSignalBaselineCache:
    def __init__(self) -> None:
        self._entries: dict[str, CachedRegionBaseline] = {}

    def resolve(
        self,
        market_slug: str,
        samples: Sequence[LiveMetricSampleResponse],
    ) -> RegionActivityScore | None:
        latest_timestamp = samples[-1].timestamp if samples else ""
        cached = self._entries.get(market_slug)
        if (
            cached is not None
            and cached.latest_timestamp == latest_timestamp
            and cached.sample_count == len(samples)
        ):
            return cached.activity

        activity = calculate_region_activity_score(samples)
        self._entries[market_slug] = CachedRegionBaseline(
            latest_timestamp=latest_timestamp,
            sample_count=len(samples),
            activity=activity,
        )
        return activity

    def clear(self) -> None:
        self._entries.clear()


region_signal_baseline_cache = RegionSignalBaselineCache()


@dataclass(frozen=True)
class RegionSignalFixture:
    region_code: str
    country_code: str
    market_slug: str
    kind: str
    score: int
    headline: str
    detail: str
    observed_at: str


REGION_SIGNAL_FIXTURES = (
    RegionSignalFixture(
        "TX",
        "US",
        "texas-republican-senate-primary-winner",
        "whale-flow",
        92,
        "Whale-sized directional flow",
        "Large directional trades and one-sided depth make this the highest-priority region in the demo scanner.",
        "2026-07-24T09:40:00Z",
    ),
    RegionSignalFixture(
        "AZ",
        "US",
        "arizona-presidential-election-winner",
        "price-move",
        46,
        "Price action within normal range",
        "Movement remains below the abnormal-activity threshold.",
        "2026-07-24T09:36:00Z",
    ),
    RegionSignalFixture(
        "GA",
        "US",
        "georgia-presidential-election-winner",
        "normal",
        31,
        "No material anomaly",
        "Trading activity is close to its recent baseline.",
        "2026-07-24T09:34:00Z",
    ),
    RegionSignalFixture(
        "MI",
        "US",
        "michigan-presidential-election-winner",
        "volume-anomaly",
        55,
        "Volume beginning to accelerate",
        "Recent activity is elevated but has not reached a high-conviction threshold.",
        "2026-07-24T09:38:00Z",
    ),
    RegionSignalFixture(
        "PA",
        "US",
        "pennsylvania-presidential-election-winner",
        "poll-divergence",
        72,
        "Market and polling paths diverge",
        "The market-implied outcome has moved away from the latest polling baseline.",
        "2026-07-24T09:39:00Z",
    ),
    RegionSignalFixture(
        "WI",
        "US",
        "wisconsin-presidential-election-winner",
        "normal",
        38,
        "Order flow remains balanced",
        "No unusual concentration or probability shock is present.",
        "2026-07-24T09:31:00Z",
    ),
    RegionSignalFixture(
        "FL",
        "US",
        "florida-presidential-election-winner",
        "poll-divergence",
        63,
        "Moderate polling divergence",
        "Market pricing is separating from the regional polling baseline.",
        "2026-07-24T09:32:00Z",
    ),
    RegionSignalFixture(
        "CA",
        "US",
        "california-governor-election-2026",
        "volume-anomaly",
        79,
        "Unusual volume concentration",
        "Turnover is concentrated in a short window relative to the demo baseline.",
        "2026-07-24T09:41:00Z",
    ),
    RegionSignalFixture(
        "SCT",
        "GB",
        "will-scotland-hold-an-independence-referendum-before-2030",
        "poll-divergence",
        74,
        "Referendum pricing diverges from polling",
        "The market is trading away from the latest constitutional polling baseline.",
        "2026-07-24T10:05:00Z",
    ),
    RegionSignalFixture(
        "LDN",
        "GB",
        "next-london-mayoral-election-winner",
        "volume-anomaly",
        68,
        "Mayoral market volume is elevated",
        "Recent turnover is above the London market's recent baseline.",
        "2026-07-24T10:02:00Z",
    ),
    RegionSignalFixture(
        "WLS",
        "GB",
        "welsh-parliament-election-most-seats",
        "price-move",
        57,
        "Senedd pricing is repricing",
        "The leading-outcome probability has moved faster than its recent baseline.",
        "2026-07-24T09:58:00Z",
    ),
    RegionSignalFixture(
        "NIR",
        "GB",
        "northern-ireland-assembly-election-most-seats",
        "order-flow",
        43,
        "Assembly market flow remains balanced",
        "Directional activity remains below the abnormal-flow threshold.",
        "2026-07-24T09:55:00Z",
    ),
)


def _fixture_response(fixture: RegionSignalFixture) -> RegionSignalResponse:
    return RegionSignalResponse(
        regionCode=fixture.region_code,
        countryCode=fixture.country_code,
        marketSlug=fixture.market_slug,
        kind=fixture.kind,
        score=fixture.score,
        severity=get_signal_severity(fixture.score),
        headline=fixture.headline,
        detail=fixture.detail,
        observedAt=fixture.observed_at,
        source="fixture",
        confidence=0.0,
        baselineWindow="curated demo snapshot",
        components=[],
    )


def _live_headline(kind: str) -> str:
    if kind == "volume-anomaly":
        return "Trade intensity is accelerating"
    if kind == "order-flow":
        return "One-sided order flow is building"
    if kind == "price-move":
        return "Probability is repricing quickly"
    return "Live activity is above baseline"


def _live_freshness(observed_at: str, now: datetime) -> tuple[str, int, list[str]]:
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return "stale", LIVE_SIGNAL_STALE_AFTER_SECONDS, ["Live sample timestamp is invalid."]

    age_seconds = max(0, int((now - observed.astimezone(timezone.utc)).total_seconds()))
    if age_seconds > LIVE_SIGNAL_STALE_AFTER_SECONDS:
        return (
            "stale",
            age_seconds,
            [f"Live sample is {age_seconds} seconds old."],
        )
    return "fresh", age_seconds, []


async def build_region_signals(
    country_code: str,
    active_slug: str | None = None,
) -> RegionSignalsResponse:
    now = datetime.now(timezone.utc)
    normalized_country = country_code.strip().upper()
    fixtures = [fixture for fixture in REGION_SIGNAL_FIXTURES if fixture.country_code == normalized_country]
    signals = [_fixture_response(fixture) for fixture in fixtures]

    active_fixture = next((fixture for fixture in fixtures if fixture.market_slug == active_slug), None)
    if active_fixture is not None:
        try:
            snapshot = await live_stream_manager.get_snapshot(active_slug)
            replay = await live_stream_manager.get_replay(active_slug, limit=60)
        except Exception:
            snapshot = None
            replay = None

        activity = (
            region_signal_baseline_cache.resolve(active_slug, replay.samples)
            if replay is not None and replay.source == "stream"
            else None
        )

        if activity is not None and snapshot is not None and snapshot.microstructure is not None and replay is not None:
            freshness, age_seconds, degradation_reasons = _live_freshness(
                replay.samples[-1].timestamp,
                now,
            )
            components = [
                SignalComponentResponse(
                    key=component.key,
                    label=component.label,
                    value=component.value,
                    weight=component.weight,
                    contribution=component.contribution,
                    available=component.available,
                    detail=component.detail,
                )
                for component in activity.components
            ]
            live_signal = RegionSignalResponse(
                regionCode=active_fixture.region_code,
                countryCode=active_fixture.country_code,
                marketSlug=active_fixture.market_slug,
                kind=activity.kind,
                score=activity.score,
                severity=get_signal_severity(activity.score),
                headline=_live_headline(activity.kind),
                detail=(
                    f"Computed from {len(replay.samples)} live stream samples. "
                    f"{sum(component.available for component in activity.components)} of "
                    f"{len(activity.components)} signal components are available."
                ),
                observedAt=replay.samples[-1].timestamp,
                source="live",
                confidence=activity.confidence,
                baselineWindow=f"{len(replay.samples)} stream samples",
                components=components,
                freshness=freshness,
                ageSeconds=age_seconds,
                degradationReasons=degradation_reasons,
            )
            signals = [
                live_signal if signal.region_code == active_fixture.region_code else signal
                for signal in signals
            ]

    live_count = sum(signal.source == "live" for signal in signals)
    source = "live" if live_count == len(signals) and signals else "mixed" if live_count else "fixture"
    stale_signals = [signal for signal in signals if signal.freshness == "stale"]
    freshness = "stale" if stale_signals else "fresh" if live_count else "fixture"
    degradation_reasons = [
        f"{signal.region_code}: {reason}"
        for signal in stale_signals
        for reason in signal.degradation_reasons
    ]
    if source == "mixed":
        degradation_reasons.append(
            f"{len(signals) - live_count} configured regions are using signal fixtures."
        )
    return RegionSignalsResponse(
        countryCode=normalized_country,
        generatedAt=now.isoformat(),
        source=source,
        signals=signals,
        freshness=freshness,
        degradationReasons=degradation_reasons,
    )
