import unittest

from app.services.upstream_rate_limit import TokenBucket, venue_for_url


class UpstreamRateLimitTestCase(unittest.IsolatedAsyncioTestCase):
    def test_detects_supported_venue_hosts(self) -> None:
        self.assertEqual(
            venue_for_url("https://gamma-api.polymarket.com/events"),
            "polymarket",
        )
        self.assertEqual(
            venue_for_url("https://external-api.kalshi.com/trade-api/v2/events"),
            "kalshi",
        )
        self.assertEqual(venue_for_url("https://example.com/events"), "other")

    async def test_token_bucket_delays_requests_beyond_burst(self) -> None:
        bucket = TokenBucket(rate_per_second=100.0, burst=1)

        await bucket.acquire()
        await bucket.acquire()

        snapshot = bucket.snapshot()
        self.assertEqual(snapshot.acquired, 2)
        self.assertEqual(snapshot.delayed, 1)
        self.assertGreater(snapshot.total_wait_seconds, 0)

    async def test_token_bucket_applies_upstream_cooldown(self) -> None:
        bucket = TokenBucket(rate_per_second=100.0, burst=2)
        bucket.penalize(0.01)

        await bucket.acquire()

        snapshot = bucket.snapshot()
        self.assertEqual(snapshot.acquired, 1)
        self.assertEqual(snapshot.delayed, 1)


if __name__ == "__main__":
    unittest.main()
