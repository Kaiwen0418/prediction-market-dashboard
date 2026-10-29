import json
import math
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException

from app.analytics.series import (
    calculate_correlation,
    calculate_divergence,
    calculate_event_window,
    calculate_lead_lag,
    calculate_rolling_correlation,
    calculate_volatility,
)
from app.schemas.analytics import EventWindowRequest, LeadLagRequest
from app.schemas.research import (
    CatalystEventResponse,
    ComparedMarketResponse,
    ElectionModelComparisonResponse,
    ResearchOverviewItemResponse,
    ResearchOverviewResponse,
    ResearchCoverageResponse,
    ResearchHighlightsResponse,
    ResearchNarrativeResponse,
    RelatedMarketDivergenceResponse,
    PollPointResponse,
    ResearchProvenanceResponse,
    ResearchStateSummaryResponse,
    TimePointResponse,
)

Party = Literal["Democrat", "Republican"]

ROOT_DIR = Path(__file__).resolve().parents[3]
STATE_SUPPORT_PATH = ROOT_DIR / "public" / "data" / "state-party-support-2024.json"
POLYMARKET_HISTORY_PATH = ROOT_DIR / "public" / "data" / "polymarket-history-2024.json"

STATE_REGISTRY = {
    "Arizona": {
        "eventSlug": "arizona-presidential-election-winner",
    },
    "Georgia": {
        "eventSlug": "georgia-presidential-election-winner",
    },
    "Michigan": {
        "eventSlug": "michigan-presidential-election-winner",
    },
    "Pennsylvania": {
        "eventSlug": "pennsylvania-presidential-election-winner",
    },
    "Wisconsin": {
        "eventSlug": "wisconsin-presidential-election-winner",
    },
}

MARKET_HISTORY_SOURCE_URL = "/data/polymarket-history-2024.json"
RELATED_MARKET_FEE_BPS_PER_LEG = 0.0
RELATED_MARKET_MINIMUM_LIQUIDITY_USD = 5_000.0

POLITICAL_CATALYSTS = (
    {
        "id": "2024-presidential-debate-atlanta",
        "headline": "Presidential debate in Atlanta",
        "eventType": "debate",
        "occurredAt": "2024-06-27T21:00:00Z",
        "sourceName": "The American Presidency Project",
        "sourceUrl": "https://www.presidency.ucsb.edu/documents/presidential-debate-atlanta-georgia",
    },
    {
        "id": "2024-republican-national-convention",
        "headline": "Republican National Convention opened",
        "eventType": "scheduled-event",
        "occurredAt": "2024-07-15T13:00:00Z",
        "sourceName": "Republican National Committee",
        "sourceUrl": "https://prod-static.gop.com/media/documents/2024_Call_of_the_Convention_as_adopted_11.20.23_1700517775.pdf",
    },
    {
        "id": "2024-biden-withdrawal",
        "headline": "President Biden ended his reelection campaign",
        "eventType": "candidate-event",
        "occurredAt": "2024-07-21T18:46:00Z",
        "sourceName": "The American Presidency Project",
        "sourceUrl": "https://www.presidency.ucsb.edu/documents/letter-the-nation-announcing-decision-not-seek-reelection",
    },
)


@lru_cache
def _load_json(path: Path) -> Any:
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Dataset not found: {path.name}")
    return json.loads(path.read_text())


def _normalize_poll_series(dataset: dict[str, Any], state: str, party: Party) -> list[PollPointResponse]:
    state_data = next((entry for entry in dataset["states"] if entry["state"] == state), None)
    if not state_data:
        return []

    normalized: list[PollPointResponse] = []
    for point in state_data["series"]:
        support = point.get("republican") if party == "Republican" else point.get("democrat")
        if not isinstance(support, (int, float)):
            continue
        normalized.append(
            PollPointResponse(
                timestamp=f"{point['date']}T00:00:00.000Z",
                pollAverage=float(support),
                sampleSize=0,
                source="FiveThirtyEight cleaned public dataset",
                sourceUrl="https://github.com/kevin-claw-agent/poll-data",
                fieldDateLabel=point["date"],
                methodology="Daily mean across all available 538 poll rows for the same state, date, and party",
                candidate=party,
            )
        )

    return normalized


def _normalize_market_series(dataset: dict[str, Any], state: str, party: Party) -> tuple[str, list[TimePointResponse]]:
    state_data = next((entry for entry in dataset["states"] if entry["state"] == state), None)
    if not state_data:
        return STATE_REGISTRY[state]["eventSlug"], []

    party_payload = state_data.get("parties", {}).get(party)
    series = []
    if party_payload and isinstance(party_payload, dict):
        series = [
            TimePointResponse(timestamp=point["timestamp"], value=float(point["value"]))
            for point in party_payload.get("series", [])
            if isinstance(point.get("value"), (int, float))
        ]

    return state_data.get("eventSlug", STATE_REGISTRY[state]["eventSlug"]), series


def _date_key(timestamp: str) -> str:
    return timestamp[:10]


def _series_bounds(series: list[PollPointResponse] | list[TimePointResponse]) -> tuple[str | None, str | None]:
    if not series:
        return None, None
    return series[0].timestamp[:10], series[-1].timestamp[:10]


def _build_coverage(
    poll_series: list[PollPointResponse],
    market_series: list[TimePointResponse],
) -> ResearchCoverageResponse:
    poll_start, poll_end = _series_bounds(poll_series)
    market_start, market_end = _series_bounds(market_series)
    aligned_days = sorted(
        {_date_key(point.timestamp) for point in poll_series}
        & {_date_key(point.timestamp) for point in market_series}
    )

    return ResearchCoverageResponse(
        pollStart=poll_start,
        pollEnd=poll_end,
        pollPoints=len(poll_series),
        marketStart=market_start,
        marketEnd=market_end,
        marketPoints=len(market_series),
        alignedStart=aligned_days[0] if aligned_days else None,
        alignedEnd=aligned_days[-1] if aligned_days else None,
        alignedPoints=len(aligned_days),
    )


def _build_related_market_divergence(
    dataset: dict[str, Any],
    state: str,
    party: Party,
) -> RelatedMarketDivergenceResponse:
    state_data = next((entry for entry in dataset["states"] if entry["state"] == state), None)
    related_party: Party = "Democrat" if party == "Republican" else "Republican"
    primary_payload = state_data.get("parties", {}).get(party) if state_data else None
    related_payload = state_data.get("parties", {}).get(related_party) if state_data else None
    primary_point = primary_payload.get("series", [])[-1]
    related_point = related_payload.get("series", [])[-1]
    probability_sum = float(primary_point["value"]) + float(related_point["value"])
    raw_gap_points = abs(1.0 - probability_sum) * 100
    fee_buffer_points = RELATED_MARKET_FEE_BPS_PER_LEG * 2 / 100
    actionable_gap_points = max(0.0, raw_gap_points - fee_buffer_points)

    return RelatedMarketDivergenceResponse(
        primary=ComparedMarketResponse(
            label=party,
            probability=float(primary_point["value"]),
            observedAt=primary_point["timestamp"],
            sourceUrl=MARKET_HISTORY_SOURCE_URL,
        ),
        related=ComparedMarketResponse(
            label=related_party,
            probability=float(related_point["value"]),
            observedAt=related_point["timestamp"],
            sourceUrl=MARKET_HISTORY_SOURCE_URL,
        ),
        rawProbabilitySum=round(probability_sum, 4),
        rawGapPoints=round(raw_gap_points, 2),
        feeBpsPerLeg=RELATED_MARKET_FEE_BPS_PER_LEG,
        feeBufferPoints=round(fee_buffer_points, 2),
        actionableGapPoints=round(actionable_gap_points, 2),
        liquidityUsd=None,
        minimumLiquidityUsd=RELATED_MARKET_MINIMUM_LIQUIDITY_USD,
        status="insufficient-liquidity-data",
        explanation=(
            "The complementary outcomes are checked for probability inconsistency after the configured fee buffer. "
            "The historical bundle does not contain executable liquidity, so no actionable arbitrage alert is emitted."
        ),
    )


def _build_catalysts(market_series: list[TimePointResponse]) -> list[CatalystEventResponse]:
    if len(market_series) < 2:
        return []

    catalysts: list[CatalystEventResponse] = []
    for event in POLITICAL_CATALYSTS:
        event_time = datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00"))
        index = min(
            range(len(market_series)),
            key=lambda candidate: abs(
                datetime.fromisoformat(
                    market_series[candidate].timestamp.replace("Z", "+00:00")
                )
                - event_time
            ),
        )
        previous_index = max(0, index - 1)
        move = (market_series[index].value - market_series[previous_index].value) * 100
        catalysts.append(
            CatalystEventResponse(
                id=event["id"],
                headline=event["headline"],
                eventType=event["eventType"],
                occurredAt=event["occurredAt"],
                sourceName=event["sourceName"],
                sourceUrl=event["sourceUrl"],
                matchedMarketTimestamp=market_series[index].timestamp,
                marketMove=round(move, 2),
                summary=(
                    f"Nearest cached market observation moved {move:+.2f} points from its preceding sample. "
                    "This is temporal correlation, not a claim of causation."
                ),
            )
        )
    return catalysts


def _build_election_model_comparison(
    poll_series: list[PollPointResponse],
    market_series: list[TimePointResponse],
) -> ElectionModelComparisonResponse:
    latest_poll = poll_series[-1]
    latest_market = market_series[-1]
    logit_input = (latest_poll.poll_average - 0.5) / 0.03
    model_probability = 1.0 / (1.0 + math.exp(-logit_input))

    return ElectionModelComparisonResponse(
        modelName="PMI polling-derived logistic baseline",
        modelProbability=round(model_probability, 4),
        marketProbability=round(latest_market.value, 4),
        divergencePoints=round((latest_market.value - model_probability) * 100, 2),
        pollObservedAt=latest_poll.timestamp,
        marketObservedAt=latest_market.timestamp,
        sourceUrl="/data/state-party-support-2024.json",
        methodology=(
            "Transforms the latest two-party polling margin through a logistic curve with a three-point scale. "
            "This transparent research baseline is not a calibrated election forecast."
        ),
    )


def get_research_summary(state: str, party: Party) -> ResearchStateSummaryResponse:
    if state not in STATE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unsupported battleground state: {state}")

    poll_dataset = _load_json(STATE_SUPPORT_PATH)
    market_dataset = _load_json(POLYMARKET_HISTORY_PATH)

    poll_series = _normalize_poll_series(poll_dataset, state, party)
    event_slug, market_series = _normalize_market_series(market_dataset, state, party)

    if len(poll_series) < 2 or len(market_series) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient history for state={state} party={party}: poll={len(poll_series)} market={len(market_series)}",
        )

    analytics_payload = LeadLagRequest(
        market=[{"timestamp": point.timestamp, "value": point.value} for point in market_series],
        polling=[{"timestamp": point.timestamp, "value": point.poll_average} for point in poll_series],
        maxLagDays=7,
    )
    lead_lag = calculate_lead_lag(analytics_payload)
    correlation = calculate_correlation(analytics_payload)
    volatility = calculate_volatility([point.value for point in market_series])
    divergence = calculate_divergence(analytics_payload)
    rolling_correlation = calculate_rolling_correlation(analytics_payload)
    coverage = _build_coverage(poll_series, market_series)
    related_market_divergence = _build_related_market_divergence(
        market_dataset,
        state,
        party,
    )
    catalysts = _build_catalysts(market_series)
    election_model_comparison = _build_election_model_comparison(
        poll_series,
        market_series,
    )
    market_values = [point.value for point in market_series]
    if len(market_values) > 1:
        deltas = [abs(market_values[index] - market_values[index - 1]) for index in range(1, len(market_values))]
        anchor_index = deltas.index(max(deltas)) + 1
    else:
        anchor_index = 0
    event_window = calculate_event_window(
        EventWindowRequest(
            series=[{"timestamp": point.timestamp, "value": point.value} for point in market_series],
            anchorIndex=anchor_index,
            preWindow=3,
            postWindow=3,
        )
    )

    return ResearchStateSummaryResponse(
        state=state,
        eventSlug=event_slug,
        party=party,
        summary=(
            f"FiveThirtyEight {party} state support compared with Polymarket history for {state}, "
            "including lead-lag, correlation, volatility, divergence, and rolling-correlation analysis."
        ),
        analyticsSource="api",
        researchSource="api",
        marketSeries=market_series,
        pollSeries=poll_series,
        leadLag=lead_lag,
        correlation=correlation,
        volatility=volatility,
        divergence=divergence,
        rollingCorrelation=rolling_correlation,
        eventWindow=event_window,
        provenance=ResearchProvenanceResponse(
            computedAt=datetime.now(timezone.utc).isoformat(),
            pollDatasetGeneratedAt=poll_dataset.get("generatedAt"),
            marketDatasetGeneratedAt=market_dataset.get("generatedAt"),
        ),
        researchHighlights=ResearchHighlightsResponse(
            shockLabel=(
                f"Primary shock window moved {event_window.net_move:+.2f} pts around "
                f"{event_window.anchor_timestamp[:10]}"
            ),
            leadLagLabel=lead_lag.interpretation,
            divergenceLabel=(
                f"Current market-poll divergence is {divergence.current_gap:.2f} pts "
                f"(max {divergence.max_gap:.2f} pts)"
            ),
        ),
        coverage=coverage,
        narrative=ResearchNarrativeResponse(
            overview=(
                f"{state} {party.lower()} support is evaluated across {coverage.aligned_points} aligned daily observations. "
                f"The market/poll relationship currently reads as {correlation.strength}, with "
                f"{lead_lag.interpretation.lower()}."
            ),
            methodology=(
                "Poll and market series are aligned by date before the service calculates lead-lag, "
                "correlation, divergence, volatility, rolling correlation, and the largest event-window shock."
            ),
        ),
        sourceUrls=[
            "/data/state-party-support-2024.json",
            MARKET_HISTORY_SOURCE_URL,
        ],
        relatedMarketDivergence=related_market_divergence,
        electionModelComparison=election_model_comparison,
        catalysts=catalysts,
    )


def get_research_overview(party: Party) -> ResearchOverviewResponse:
    items: list[ResearchOverviewItemResponse] = []
    for state in STATE_REGISTRY:
        summary = get_research_summary(state, party)
        items.append(
            ResearchOverviewItemResponse(
                state=summary.state,
                eventSlug=summary.event_slug,
                party=summary.party,
                leadLagDays=summary.lead_lag.lag_days,
                correlation=summary.correlation.coefficient,
                divergence=summary.divergence.current_gap,
                volatility=summary.volatility.realized_volatility,
                alignedPoints=summary.coverage.aligned_points,
            )
        )

    items.sort(key=lambda item: item.state)
    return ResearchOverviewResponse(
        party=party,
        computedAt=datetime.now(timezone.utc).isoformat(),
        source="api",
        items=items,
    )
