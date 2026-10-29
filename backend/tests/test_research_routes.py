import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.api import routes_research
from app.services.research import get_research_summary
from app.schemas.analytics import CorrelationResponse, DivergenceResponse, EventWindowResponse, LeadLagResponse, RollingCorrelationResponse, VolatilityResponse
from app.schemas.research import (
    ResearchCoverageResponse,
    ResearchHighlightsResponse,
    ResearchNarrativeResponse,
    ResearchOverviewItemResponse,
    ResearchOverviewResponse,
    ResearchProvenanceResponse,
    ResearchStateSummaryResponse,
)


class ResearchServiceTestCase(unittest.TestCase):
    def test_related_market_and_catalyst_outputs_are_traceable(self) -> None:
        summary = get_research_summary("Arizona", "Republican")

        divergence = summary.related_market_divergence
        self.assertTrue(divergence.primary.observed_at)
        self.assertTrue(divergence.related.observed_at)
        self.assertGreaterEqual(divergence.fee_buffer_points, 0)
        self.assertEqual(divergence.status, "insufficient-liquidity-data")
        self.assertIsNone(divergence.liquidity_usd)

        model = summary.election_model_comparison
        self.assertGreaterEqual(model.model_probability, 0)
        self.assertLessEqual(model.model_probability, 1)
        self.assertTrue(model.poll_observed_at)
        self.assertTrue(model.market_observed_at)

        self.assertEqual(len(summary.catalysts), 3)
        self.assertTrue(all(event.source_url.startswith("https://") for event in summary.catalysts))
        self.assertTrue(all(event.matched_market_timestamp for event in summary.catalysts))


class ResearchRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original_get_research_summary = routes_research.get_research_summary
        self.original_get_research_overview = routes_research.get_research_overview

        def fake_get_research_summary(state: str, party: str) -> ResearchStateSummaryResponse:
            return ResearchStateSummaryResponse(
                state=state,
                eventSlug=f"{state.lower()}-event",
                party=party,
                summary=f"{state} summary",
                analyticsSource="api",
                researchSource="api",
                marketSeries=[{"timestamp": "2024-01-01T00:00:00.000Z", "value": 0.5}, {"timestamp": "2024-01-02T00:00:00.000Z", "value": 0.55}],
                pollSeries=[{"timestamp": "2024-01-01T00:00:00.000Z", "pollAverage": 49, "sampleSize": 0, "source": "test"}],
                leadLag=LeadLagResponse(lagDays=-1, score=0.92, interpretation="Market leads polls by 1 day"),
                correlation=CorrelationResponse(coefficient=0.81, strength="strong"),
                volatility=VolatilityResponse(realizedVolatility=11.2, averageReturn=0.4),
                divergence=DivergenceResponse(averageGap=2.2, maxGap=5.4, currentGap=3.1),
                rollingCorrelation=RollingCorrelationResponse(coefficient=0.77, windowSize=2, points=[]),
                eventWindow=EventWindowResponse(
                    anchorIndex=1,
                    anchorTimestamp="2024-01-02T00:00:00.000Z",
                    preChange=5.0,
                    postChange=0.0,
                    netMove=5.0,
                    preWindow=1,
                    postWindow=1,
                ),
                provenance=ResearchProvenanceResponse(
                    computedAt="2026-07-07T12:00:00Z",
                    pollDatasetGeneratedAt="2026-07-01T00:00:00Z",
                    marketDatasetGeneratedAt="2026-07-01T00:00:00Z",
                ),
                researchHighlights=ResearchHighlightsResponse(
                    shockLabel="Shock label",
                    leadLagLabel="Lead-lag label",
                    divergenceLabel="Divergence label",
                ),
                coverage=ResearchCoverageResponse(
                    pollStart="2024-01-01",
                    pollEnd="2024-01-02",
                    pollPoints=2,
                    marketStart="2024-01-01",
                    marketEnd="2024-01-02",
                    marketPoints=2,
                    alignedStart="2024-01-01",
                    alignedEnd="2024-01-02",
                    alignedPoints=2,
                ),
                narrative=ResearchNarrativeResponse(overview="Overview", methodology="Methodology"),
                sourceUrls=["/data/state-party-support-2024.json"],
                relatedMarketDivergence={
                    "primary": {
                        "label": party,
                        "probability": 0.55,
                        "observedAt": "2024-01-02T00:00:00.000Z",
                        "sourceUrl": "/data/polymarket-history-2024.json",
                    },
                    "related": {
                        "label": "Democrat" if party == "Republican" else "Republican",
                        "probability": 0.44,
                        "observedAt": "2024-01-02T00:00:00.000Z",
                        "sourceUrl": "/data/polymarket-history-2024.json",
                    },
                    "rawProbabilitySum": 0.99,
                    "rawGapPoints": 1.0,
                    "feeBpsPerLeg": 0,
                    "feeBufferPoints": 0,
                    "actionableGapPoints": 1.0,
                    "liquidityUsd": None,
                    "minimumLiquidityUsd": 5_000,
                    "status": "insufficient-liquidity-data",
                    "explanation": "Liquidity is unavailable.",
                },
                electionModelComparison={
                    "modelName": "Test model",
                    "modelProbability": 0.57,
                    "marketProbability": 0.55,
                    "divergencePoints": -2.0,
                    "pollObservedAt": "2024-01-01T00:00:00.000Z",
                    "marketObservedAt": "2024-01-02T00:00:00.000Z",
                    "sourceUrl": "/data/state-party-support-2024.json",
                    "methodology": "Transparent test model.",
                },
                catalysts=[
                    {
                        "id": "debate",
                        "headline": "Presidential debate",
                        "eventType": "debate",
                        "occurredAt": "2024-01-01T00:00:00.000Z",
                        "sourceName": "Test source",
                        "sourceUrl": "https://example.com/source",
                        "matchedMarketTimestamp": "2024-01-02T00:00:00.000Z",
                        "marketMove": 5.0,
                        "summary": "Temporal correlation only.",
                    }
                ],
            )

        def fake_get_research_overview(party: str) -> ResearchOverviewResponse:
            return ResearchOverviewResponse(
                party=party,
                computedAt="2026-07-07T12:00:00Z",
                source="api",
                items=[
                    ResearchOverviewItemResponse(
                        state="Arizona",
                        eventSlug="arizona-event",
                        party=party,
                        leadLagDays=-1,
                        correlation=0.81,
                        divergence=3.1,
                        volatility=11.2,
                        alignedPoints=42,
                    ),
                    ResearchOverviewItemResponse(
                        state="Georgia",
                        eventSlug="georgia-event",
                        party=party,
                        leadLagDays=0,
                        correlation=0.74,
                        divergence=2.4,
                        volatility=9.8,
                        alignedPoints=40,
                    ),
                ],
            )

        routes_research.get_research_summary = fake_get_research_summary
        routes_research.get_research_overview = fake_get_research_overview

    def tearDown(self) -> None:
        routes_research.get_research_summary = self.original_get_research_summary
        routes_research.get_research_overview = self.original_get_research_overview

    def test_state_summary_route_returns_backend_bundle(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/research/states/Arizona/summary", params={"party": "Republican"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], "Arizona")
        self.assertEqual(payload["party"], "Republican")
        self.assertEqual(payload["analyticsSource"], "api")
        self.assertEqual(payload["divergence"]["currentGap"], 3.1)
        self.assertEqual(payload["relatedMarketDivergence"]["rawGapPoints"], 1.0)
        self.assertEqual(payload["electionModelComparison"]["modelName"], "Test model")
        self.assertEqual(payload["catalysts"][0]["sourceName"], "Test source")

    def test_states_overview_route_returns_compact_cross_state_metrics(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/research/states/overview", params={"party": "Democrat"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["party"], "Democrat")
        self.assertEqual(payload["source"], "api")
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][0]["state"], "Arizona")
        self.assertEqual(payload["items"][1]["leadLagDays"], 0)


if __name__ == "__main__":
    unittest.main()
