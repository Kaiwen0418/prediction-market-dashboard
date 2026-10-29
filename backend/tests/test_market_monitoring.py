import unittest

from app.core.config import get_settings
from app.services import market_monitoring as monitoring_module
from app.services.market_monitoring import MarketMonitoringService, _event_activity


def polymarket_event(slug: str, volume: float) -> dict:
    return {
        "slug": slug,
        "title": slug,
        "volume24hr": volume,
        "liquidity": volume / 2,
        "markets": [],
    }


def kalshi_event(ticker: str, volume: float) -> dict:
    return {
        "event_ticker": ticker,
        "title": ticker,
        "markets": [
            {
                "volume_24h_fp": volume,
                "liquidity_dollars": volume / 2,
            }
        ],
    }


class MarketMonitoringTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = get_settings()
        self.original_hot = self.settings.monitoring_hot_markets_per_venue
        self.original_warm = self.settings.monitoring_warm_markets_per_venue
        self.original_streams = self.settings.monitoring_polymarket_hot_streams
        self.settings.monitoring_hot_markets_per_venue = 1
        self.settings.monitoring_warm_markets_per_venue = 1
        self.settings.monitoring_polymarket_hot_streams = 1
        self.service = MarketMonitoringService()

    def tearDown(self) -> None:
        self.settings.monitoring_hot_markets_per_venue = self.original_hot
        self.settings.monitoring_warm_markets_per_venue = self.original_warm
        self.settings.monitoring_polymarket_hot_streams = self.original_streams

    def test_activity_score_increases_with_volume_and_liquidity(self) -> None:
        self.assertGreater(
            _event_activity(polymarket_event("high", 10_000)),
            _event_activity(polymarket_event("low", 10)),
        )

    async def test_assignment_caps_each_tier_per_venue(self) -> None:
        snapshot = {
            "venues": {
                "polymarket": {
                    "events": [
                        polymarket_event("low", 10),
                        polymarket_event("high", 10_000),
                        polymarket_event("mid", 500),
                    ]
                },
                "kalshi": {
                    "events": [
                        kalshi_event("K-LOW", 10),
                        kalshi_event("K-HIGH", 10_000),
                        kalshi_event("K-MID", 500),
                    ]
                },
            }
        }

        async def fake_catalog():
            return snapshot

        streamed: list[str] = []

        async def fake_ensure_stream(slug: str):
            streamed.append(slug)

        original_catalog = monitoring_module.market_catalog_service.get_catalog
        original_ensure_stream = monitoring_module.live_stream_manager.ensure_stream
        monitoring_module.market_catalog_service.get_catalog = fake_catalog
        monitoring_module.live_stream_manager.ensure_stream = fake_ensure_stream
        try:
            assignments = await self.service.rebuild_assignments()
        finally:
            monitoring_module.market_catalog_service.get_catalog = original_catalog
            monitoring_module.live_stream_manager.ensure_stream = original_ensure_stream

        by_key = {
            (assignment.venue, assignment.identifier): assignment.tier
            for assignment in assignments
        }
        self.assertEqual(by_key[("polymarket", "high")], "hot")
        self.assertEqual(by_key[("polymarket", "mid")], "warm")
        self.assertEqual(by_key[("polymarket", "low")], "catalog")
        self.assertEqual(by_key[("kalshi", "K-HIGH")], "hot")
        self.assertEqual(by_key[("kalshi", "K-MID")], "warm")
        self.assertEqual(by_key[("kalshi", "K-LOW")], "catalog")
        self.assertEqual(streamed, ["high"])

    async def test_refresh_updates_catalog_and_schedules_next_due_time(self) -> None:
        market = monitoring_module.MonitoredMarket(
            venue="polymarket",
            identifier="election",
            title="Election",
            tier="warm",
            activity_score=10,
        )
        replaced: list[tuple[str, str, dict]] = []

        async def fake_fetch_json(*_args, **_kwargs):
            return polymarket_event("election", 12_000)

        async def fake_replace(venue: str, identifier: str, event: dict):
            replaced.append((venue, identifier, event))
            return True

        original_fetch = monitoring_module.fetch_json
        original_replace = monitoring_module.market_catalog_service.replace_event
        monitoring_module.fetch_json = fake_fetch_json
        monitoring_module.market_catalog_service.replace_event = fake_replace
        try:
            await self.service._refresh(market)
        finally:
            monitoring_module.fetch_json = original_fetch
            monitoring_module.market_catalog_service.replace_event = original_replace

        self.assertEqual(replaced[0][0:2], ("polymarket", "election"))
        self.assertIn(("polymarket", "election"), self.service._last_success_at)
        self.assertIn(("polymarket", "election"), self.service._due_at)


if __name__ == "__main__":
    unittest.main()
