import unittest

from app.services import market_catalog as catalog_service


class MarketCatalogTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        catalog_service.market_catalog_service.clear()

    def test_classifies_political_categories_tags_and_titles(self) -> None:
        self.assertTrue(
            catalog_service.is_political_event(
                {"title": "Technology policy", "category": "Politics"}
            )
        )
        self.assertTrue(
            catalog_service.is_political_event(
                {
                    "title": "Who will lead the country?",
                    "tags": [{"slug": "elections"}],
                }
            )
        )
        self.assertTrue(
            catalog_service.is_political_event(
                {"title": "Will the ceasefire hold through August?"}
            )
        )
        self.assertFalse(
            catalog_service.is_political_event(
                {"title": "Will Bitcoin reach $200,000?", "category": "Crypto"}
            )
        )
        self.assertFalse(
            catalog_service.is_political_event(
                {"title": "Who will win the Champions League?", "category": "Sports"}
            )
        )

    async def test_polymarket_scan_pages_and_filters_events(self) -> None:
        urls: list[str] = []

        async def fake_fetch_json(url: str, **_kwargs):
            urls.append(url)
            return [
                {"slug": "election", "title": "Next presidential election"},
                {"slug": "bitcoin", "title": "Bitcoin above $200k?", "category": "Crypto"},
            ]

        original_fetch_json = catalog_service.fetch_json
        catalog_service.fetch_json = fake_fetch_json
        try:
            events, scanned = await catalog_service.scan_polymarket_events()
        finally:
            catalog_service.fetch_json = original_fetch_json

        self.assertEqual(scanned, 2)
        self.assertEqual([event["slug"] for event in events], ["election"])
        self.assertEqual(len(urls), 1)
        self.assertIn("active=true", urls[0])
        self.assertIn("closed=false", urls[0])
        self.assertIn("tag_slug=politics", urls[0])
        self.assertIn("related_tags=true", urls[0])
        self.assertIn("/events/keyset?", urls[0])

    async def test_kalshi_scan_follows_cursor_and_filters_events(self) -> None:
        urls: list[str] = []

        async def fake_fetch_json(url: str, **_kwargs):
            urls.append(url)
            if len(urls) == 1:
                return {
                    "events": [
                        {
                            "event_ticker": "PRES-28",
                            "title": "Presidential election winner",
                            "category": "Politics",
                        }
                    ],
                    "cursor": "next-page",
                }
            return {
                "events": [
                    {
                        "event_ticker": "SPORT-1",
                        "title": "Championship winner",
                        "category": "Sports",
                    }
                ],
                "cursor": "",
            }

        original_fetch_json = catalog_service.fetch_json
        catalog_service.fetch_json = fake_fetch_json
        try:
            events, scanned = await catalog_service.scan_kalshi_events()
        finally:
            catalog_service.fetch_json = original_fetch_json

        self.assertEqual(scanned, 2)
        self.assertEqual([event["event_ticker"] for event in events], ["PRES-28"])
        self.assertEqual(len(urls), 2)
        self.assertIn("cursor=next-page", urls[1])

    async def test_catalog_sync_preserves_successful_venue_on_partial_failure(self) -> None:
        async def polymarket_scan():
            return ([{"slug": "election"}], 4)

        async def kalshi_scan():
            raise RuntimeError("venue unavailable")

        original_polymarket_scan = catalog_service.scan_polymarket_events
        original_kalshi_scan = catalog_service.scan_kalshi_events
        catalog_service.scan_polymarket_events = polymarket_scan
        catalog_service.scan_kalshi_events = kalshi_scan
        try:
            result = await catalog_service.market_catalog_service.sync(force=True)
        finally:
            catalog_service.scan_polymarket_events = original_polymarket_scan
            catalog_service.scan_kalshi_events = original_kalshi_scan

        self.assertEqual(result["counts"]["polymarket"], 1)
        self.assertEqual(result["counts"]["kalshi"], 0)
        self.assertEqual(result["venues"]["kalshi"]["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
