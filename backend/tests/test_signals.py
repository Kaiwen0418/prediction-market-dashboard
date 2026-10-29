import unittest

from fastapi.testclient import TestClient

from app.analytics.signals import calculate_region_activity_score, get_signal_severity
from app.api import routes_signals
from app.main import app
from app.schemas.live import (
    LiveMarketSnapshotResponse,
    LiveMetricSampleResponse,
    LiveMicrostructureMetricsResponse,
    LiveReplayResponse,
    LiveStreamStatusResponse,
)
from app.schemas.signals import RegionSignalResponse, RegionSignalsResponse
from app.services.region_signals import RegionSignalBaselineCache, build_region_signals
from app.streaming.polymarket_ws import live_stream_manager


def sample(
    timestamp: str,
    mid_price: float,
    trade_intensity: float,
    order_flow_imbalance: float,
) -> LiveMetricSampleResponse:
    return LiveMetricSampleResponse(
        timestamp=timestamp,
        midPrice=mid_price,
        spreadBps=100,
        microprice=mid_price,
        depthSkew=0.1,
        realizedVolatility=0.02,
        tradeIntensity=trade_intensity,
        orderFlowImbalance=order_flow_imbalance,
    )


class SignalAnalyticsTestCase(unittest.TestCase):
    def test_score_is_reproducible_from_available_components(self) -> None:
        result = calculate_region_activity_score(
            [
                sample("2026-07-24T09:00:00Z", 0.50, 10, 0.1),
                sample("2026-07-24T09:01:00Z", 0.51, 10, 0.2),
                sample("2026-07-24T09:02:00Z", 0.57, 30, 0.8),
            ]
        )

        self.assertIsNotNone(result)
        assert result is not None
        expected = round(
            sum(component.contribution for component in result.components)
            / sum(component.weight for component in result.components if component.available)
        )
        self.assertEqual(result.score, expected)
        self.assertEqual(result.confidence, 0.75)
        self.assertEqual(result.kind, "volume-anomaly")

    def test_score_requires_a_baseline_sample(self) -> None:
        result = calculate_region_activity_score(
            [sample("2026-07-24T09:00:00Z", 0.50, 10, 0.1)]
        )
        self.assertIsNone(result)

    def test_severity_thresholds_match_frontend_contract(self) -> None:
        self.assertEqual(get_signal_severity(49), "normal")
        self.assertEqual(get_signal_severity(50), "elevated")
        self.assertEqual(get_signal_severity(70), "high")
        self.assertEqual(get_signal_severity(85), "critical")

    def test_baseline_cache_reuses_unchanged_replay_window(self) -> None:
        cache = RegionSignalBaselineCache()
        samples = [
            sample("2026-07-24T09:00:00Z", 0.50, 10, 0.1),
            sample("2026-07-24T09:01:00Z", 0.57, 30, 0.8),
        ]

        first = cache.resolve("market", samples)
        second = cache.resolve("market", samples)
        changed = cache.resolve(
            "market",
            [*samples, sample("2026-07-24T09:02:00Z", 0.58, 32, 0.7)],
        )

        self.assertIs(first, second)
        self.assertIsNot(first, changed)


class SignalServiceTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_get_snapshot = live_stream_manager.get_snapshot
        self.original_get_replay = live_stream_manager.get_replay

    def tearDown(self) -> None:
        live_stream_manager.get_snapshot = self.original_get_snapshot
        live_stream_manager.get_replay = self.original_get_replay

    async def test_live_active_region_replaces_only_its_fixture(self) -> None:
        slug = "california-governor-election-2026"
        status = LiveStreamStatusResponse(
            enabled=True,
            state="connected",
            marketSlug=slug,
            marketId="market",
            tokenId="token",
            messageCount=12,
            reconnectCount=0,
        )

        async def fake_get_snapshot(_: str | None) -> LiveMarketSnapshotResponse:
            return LiveMarketSnapshotResponse(
                status=status,
                orderbookSummary=None,
                microstructure=LiveMicrostructureMetricsResponse(
                    microprice=0.57,
                    depthSkew=0.2,
                    realizedVolatility=0.03,
                    tradeIntensity=30,
                    orderFlowImbalance=0.8,
                ),
            )

        async def fake_get_replay(_: str | None, limit: int) -> LiveReplayResponse:
            samples = [
                sample("2026-07-24T09:00:00Z", 0.50, 10, 0.1),
                sample("2026-07-24T09:01:00Z", 0.51, 10, 0.2),
                sample("2026-07-24T09:02:00Z", 0.57, 30, 0.8),
            ][:limit]
            return LiveReplayResponse(
                status=status,
                samples=samples,
                sampleCount=len(samples),
                source="stream",
            )

        live_stream_manager.get_snapshot = fake_get_snapshot
        live_stream_manager.get_replay = fake_get_replay

        response = await build_region_signals("US", slug)

        self.assertEqual(response.source, "mixed")
        self.assertEqual(len(response.signals), 8)
        california = next(signal for signal in response.signals if signal.region_code == "CA")
        texas = next(signal for signal in response.signals if signal.region_code == "TX")
        self.assertEqual(california.source, "live")
        self.assertEqual(california.confidence, 0.75)
        self.assertEqual(len(california.components), 5)
        self.assertEqual(california.freshness, "stale")
        self.assertGreater(california.age_seconds or 0, 90)
        self.assertEqual(response.freshness, "stale")
        self.assertTrue(response.degradation_reasons)
        self.assertEqual(texas.source, "fixture")

    async def test_stream_failure_keeps_fixture_batch_available(self) -> None:
        async def fail_snapshot(_: str | None) -> LiveMarketSnapshotResponse:
            raise RuntimeError("upstream unavailable")

        live_stream_manager.get_snapshot = fail_snapshot

        response = await build_region_signals(
            "US",
            "california-governor-election-2026",
        )

        self.assertEqual(response.source, "fixture")
        self.assertTrue(all(signal.source == "fixture" for signal in response.signals))

    async def test_uk_region_batch_uses_country_specific_registry(self) -> None:
        response = await build_region_signals("gb")

        self.assertEqual(response.country_code, "GB")
        self.assertEqual(response.source, "fixture")
        self.assertEqual(
            [signal.region_code for signal in response.signals],
            ["SCT", "LDN", "WLS", "NIR"],
        )
        self.assertTrue(all(signal.country_code == "GB" for signal in response.signals))


class SignalRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.original_start = live_stream_manager.start
        self.original_stop = live_stream_manager.stop
        self.original_build_region_signals = routes_signals.build_region_signals

        async def fake_start() -> None:
            return None

        async def fake_stop() -> None:
            return None

        async def fake_build_region_signals(
            country_code: str,
            active_slug: str | None,
        ) -> RegionSignalsResponse:
            return RegionSignalsResponse(
                countryCode=country_code.upper(),
                generatedAt="2026-07-24T09:00:00Z",
                source="live",
                freshness="fresh",
                signals=[
                    RegionSignalResponse(
                        regionCode="CA",
                        countryCode="US",
                        marketSlug=active_slug or "california-governor-election-2026",
                        kind="order-flow",
                        score=74,
                        severity="high",
                        headline="One-sided order flow is building",
                        detail="Computed from live stream samples.",
                        observedAt="2026-07-24T09:00:00Z",
                        source="live",
                        confidence=0.75,
                        baselineWindow="24 stream samples",
                        components=[],
                        freshness="fresh",
                        ageSeconds=0,
                    )
                ],
            )

        live_stream_manager.start = fake_start
        live_stream_manager.stop = fake_stop
        routes_signals.build_region_signals = fake_build_region_signals

    def tearDown(self) -> None:
        live_stream_manager.start = self.original_start
        live_stream_manager.stop = self.original_stop
        routes_signals.build_region_signals = self.original_build_region_signals

    def test_region_batch_route_uses_camel_case_contract(self) -> None:
        with TestClient(app) as client:
            response = client.get(
                "/api/signals/regions",
                params={
                    "countryCode": "us",
                    "activeSlug": "california-governor-election-2026",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["countryCode"], "US")
        self.assertEqual(payload["source"], "live")
        self.assertEqual(payload["signals"][0]["regionCode"], "CA")
        self.assertEqual(payload["signals"][0]["baselineWindow"], "24 stream samples")


if __name__ == "__main__":
    unittest.main()
