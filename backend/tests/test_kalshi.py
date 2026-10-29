import unittest

from app.services import kalshi as kalshi_service


class KalshiAggregationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_event_batch_uses_one_cached_upstream_request(self) -> None:
        urls: list[str] = []

        async def fake_fetch_json(url: str, **kwargs):
            urls.append(url)
            self.assertEqual(kwargs["cache_ttl_seconds"], 15)
            return {"events": []}

        original_fetch_json = kalshi_service.fetch_json
        kalshi_service.fetch_json = fake_fetch_json
        try:
            result = await kalshi_service.fetch_kalshi_events(
                ["GOVPARTYOH-26", "GOVPARTYOH-26"]
            )
        finally:
            kalshi_service.fetch_json = original_fetch_json

        self.assertEqual(result, {"events": []})
        self.assertEqual(len(urls), 1)
        self.assertIn("tickers=GOVPARTYOH-26", urls[0])

    async def test_selected_analytics_aggregates_three_cached_feeds(self) -> None:
        urls: list[str] = []

        async def fake_fetch_json(url: str, **_kwargs):
            urls.append(url)
            if "/orderbook" in url:
                return {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
            if "/markets/trades" in url:
                return {"trades": []}
            return {"candlesticks": []}

        original_fetch_json = kalshi_service.fetch_json
        kalshi_service.fetch_json = fake_fetch_json
        try:
            result = await kalshi_service.fetch_kalshi_analytics(
                "GOVPARTYOH-26-D",
                "GOVPARTYOH",
            )
        finally:
            kalshi_service.fetch_json = original_fetch_json

        self.assertEqual(len(urls), 3)
        self.assertEqual(result["ticker"], "GOVPARTYOH-26-D")
        self.assertIsNotNone(result["orderbook"])
        self.assertIsNotNone(result["trades"])
        self.assertIsNotNone(result["candlesticks"])


if __name__ == "__main__":
    unittest.main()
