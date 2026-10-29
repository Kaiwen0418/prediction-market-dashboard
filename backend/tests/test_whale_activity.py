import unittest

from app.analytics.whale_activity import ResolvedWalletOutcome, analyze_whale_activity
from app.schemas.polymarket import TradePrint


def trade(
    trade_id: str,
    side: str,
    size: float,
    price: float = 0.5,
    wallet_address: str | None = None,
) -> TradePrint:
    return TradePrint(
        id=trade_id,
        side=side,
        price=price,
        size=size,
        timestamp="2026-07-24T10:00:00Z",
        walletAddress=wallet_address,
    )


class WhaleActivityTestCase(unittest.TestCase):
    def test_requires_a_minimum_normalized_trade_sample(self) -> None:
        result = analyze_whale_activity(
            [trade("1", "buy", 10), trade("2", "sell", 20)],
            total_bid_depth=1_000,
            total_ask_depth=1_000,
        )

        self.assertEqual(result.status, "insufficient-data")
        self.assertEqual(result.sample_size, 2)
        self.assertEqual(result.detections, ())

    def test_flags_trade_only_when_size_and_depth_thresholds_are_met(self) -> None:
        result = analyze_whale_activity(
            [
                trade("1", "buy", 10),
                trade("2", "sell", 10),
                trade("3", "buy", 12),
                trade("4", "sell", 8),
                trade("large-buy", "buy", 60, price=0.55),
            ],
            total_bid_depth=2_000,
            total_ask_depth=1_000,
        )

        self.assertEqual(result.status, "detected")
        self.assertEqual(len(result.detections), 1)
        detection = result.detections[0]
        self.assertEqual(detection.trade_id, "large-buy")
        self.assertEqual(detection.historical_size_multiple, 6.0)
        self.assertEqual(detection.executable_depth_share, 0.06)
        self.assertEqual(detection.notional_usd, 33.0)

    def test_rejects_trade_that_only_meets_one_relative_threshold(self) -> None:
        result = analyze_whale_activity(
            [
                trade("1", "buy", 10),
                trade("2", "sell", 10),
                trade("3", "buy", 10),
                trade("4", "sell", 10),
                trade("large-history-only", "buy", 40),
            ],
            total_bid_depth=1_000,
            total_ask_depth=10_000,
        )

        self.assertEqual(result.status, "clear")
        self.assertEqual(result.detections, ())

    def test_wallet_concentration_requires_attributed_sample_and_reports_hhi(self) -> None:
        wallet_a = "0x1111111111111111111111111111111111111111"
        wallet_b = "0x2222222222222222222222222222222222222222"
        trades = [
            trade(str(index), "buy", 10, wallet_address=wallet_a if index < 7 else wallet_b)
            for index in range(10)
        ]

        result = analyze_whale_activity(
            trades,
            total_bid_depth=1_000,
            total_ask_depth=1_000,
        )

        self.assertEqual(result.wallet_concentration_status, "available")
        self.assertEqual(result.attributed_trade_count, 10)
        self.assertEqual(result.unique_wallet_count, 2)
        self.assertEqual(result.top_wallet_volume_share, 0.7)
        self.assertAlmostEqual(result.wallet_concentration_score or 0, 58.0, places=1)

    def test_wallet_concentration_withholds_score_below_sample_minimum(self) -> None:
        wallet = "0x1111111111111111111111111111111111111111"
        result = analyze_whale_activity(
            [trade(str(index), "buy", 10, wallet_address=wallet) for index in range(5)],
            total_bid_depth=1_000,
            total_ask_depth=1_000,
        )

        self.assertEqual(result.wallet_concentration_status, "insufficient-data")
        self.assertIsNone(result.wallet_concentration_score)

    def test_wallet_reputation_requires_resolved_market_history(self) -> None:
        wallet = "0x1111111111111111111111111111111111111111"
        trades = [
            trade(str(index), "buy", 10, wallet_address=wallet)
            for index in range(10)
        ]
        outcomes = [
            ResolvedWalletOutcome(
                wallet_address=wallet,
                market_id=f"market-{index}",
                realized_return=0.2,
            )
            for index in range(4)
        ]

        result = analyze_whale_activity(
            trades,
            total_bid_depth=1_000,
            total_ask_depth=1_000,
            resolved_outcomes=outcomes,
        )

        self.assertEqual(result.wallet_reputation_status, "insufficient-history")
        self.assertEqual(result.wallet_resolved_market_count, 4)
        self.assertIsNone(result.wallet_reputation_score)

    def test_wallet_reputation_scores_sufficient_resolved_history(self) -> None:
        wallet = "0x1111111111111111111111111111111111111111"
        trades = [
            trade(str(index), "buy", 10, wallet_address=wallet)
            for index in range(10)
        ]
        outcomes = [
            ResolvedWalletOutcome(
                wallet_address=wallet,
                market_id=f"market-{index}",
                realized_return=value,
            )
            for index, value in enumerate([0.4, 0.2, -0.1, 0.5, 0.3])
        ]

        result = analyze_whale_activity(
            trades,
            total_bid_depth=1_000,
            total_ask_depth=1_000,
            resolved_outcomes=outcomes,
        )

        self.assertEqual(result.wallet_reputation_status, "available")
        self.assertEqual(result.wallet_resolved_market_count, 5)
        self.assertAlmostEqual(result.wallet_reputation_score or 0, 74.9, places=1)


if __name__ == "__main__":
    unittest.main()
