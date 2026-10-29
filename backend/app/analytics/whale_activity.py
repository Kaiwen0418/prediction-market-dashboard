from dataclasses import dataclass
from statistics import mean, median
from typing import Sequence

from app.schemas.polymarket import TradePrint


HISTORICAL_MULTIPLE_THRESHOLD = 3.0
DEPTH_SHARE_THRESHOLD = 0.05
MINIMUM_SAMPLE_SIZE = 5
WALLET_SAMPLE_MINIMUM = 10
WALLET_RESOLVED_MARKET_MINIMUM = 5


@dataclass(frozen=True)
class LargeTradeDetection:
    trade_id: str
    side: str
    price: float
    size: float
    timestamp: str
    notional_usd: float
    historical_size_multiple: float
    executable_depth_share: float
    wallet_address: str | None


@dataclass(frozen=True)
class ResolvedWalletOutcome:
    wallet_address: str
    market_id: str
    realized_return: float


@dataclass(frozen=True)
class WhaleActivityAnalysis:
    status: str
    sample_size: int
    median_trade_size: float
    detections: tuple[LargeTradeDetection, ...]
    attributed_trade_count: int
    unique_wallet_count: int
    wallet_concentration_status: str
    wallet_concentration_score: float | None
    top_wallet_volume_share: float | None
    wallet_reputation_status: str
    wallet_reputation_score: float | None
    wallet_resolved_market_count: int


def _wallet_concentration(
    trades: Sequence[TradePrint],
) -> tuple[int, int, str, float | None, float | None]:
    wallet_volume: dict[str, float] = {}
    attributed_trade_count = 0

    for trade in trades:
        if not trade.wallet_address:
            continue
        attributed_trade_count += 1
        wallet_volume[trade.wallet_address] = (
            wallet_volume.get(trade.wallet_address, 0.0) + trade.price * trade.size
        )

    unique_wallet_count = len(wallet_volume)
    if attributed_trade_count == 0:
        return 0, 0, "unavailable", None, None
    if attributed_trade_count < WALLET_SAMPLE_MINIMUM or unique_wallet_count < 2:
        return (
            attributed_trade_count,
            unique_wallet_count,
            "insufficient-data",
            None,
            None,
        )

    total_volume = sum(wallet_volume.values())
    shares = [volume / total_volume for volume in wallet_volume.values()] if total_volume > 0 else []
    if not shares:
        return (
            attributed_trade_count,
            unique_wallet_count,
            "insufficient-data",
            None,
            None,
        )

    return (
        attributed_trade_count,
        unique_wallet_count,
        "available",
        round(sum(share * share for share in shares) * 100, 1),
        round(max(shares), 4),
    )


def _wallet_reputation(
    trades: Sequence[TradePrint],
    resolved_outcomes: Sequence[ResolvedWalletOutcome],
) -> tuple[str, float | None, int]:
    wallet_volume: dict[str, float] = {}
    for trade in trades:
        if trade.wallet_address:
            wallet_volume[trade.wallet_address] = (
                wallet_volume.get(trade.wallet_address, 0.0) + trade.price * trade.size
            )

    if not wallet_volume:
        return "unavailable", None, 0

    top_wallet = max(wallet_volume, key=wallet_volume.get)
    wallet_outcomes = [
        outcome
        for outcome in resolved_outcomes
        if outcome.wallet_address.lower() == top_wallet.lower()
    ]
    resolved_market_count = len({outcome.market_id for outcome in wallet_outcomes})
    if resolved_market_count == 0:
        return "unavailable", None, 0
    if resolved_market_count < WALLET_RESOLVED_MARKET_MINIMUM:
        return "insufficient-history", None, resolved_market_count

    unique_outcomes = {
        outcome.market_id: max(-1.0, min(1.0, outcome.realized_return))
        for outcome in wallet_outcomes
    }
    returns = list(unique_outcomes.values())
    hit_rate = sum(value > 0 for value in returns) / len(returns)
    normalized_return = (mean(returns) + 1.0) / 2.0
    score = round((hit_rate * 0.7 + normalized_return * 0.3) * 100, 1)
    return "available", score, resolved_market_count


def analyze_whale_activity(
    trades: Sequence[TradePrint],
    total_bid_depth: float,
    total_ask_depth: float,
    resolved_outcomes: Sequence[ResolvedWalletOutcome] = (),
) -> WhaleActivityAnalysis:
    sample_size = len(trades)
    median_trade_size = float(median(trade.size for trade in trades)) if trades else 0.0
    (
        attributed_trade_count,
        unique_wallet_count,
        wallet_concentration_status,
        wallet_concentration_score,
        top_wallet_volume_share,
    ) = _wallet_concentration(trades)
    (
        wallet_reputation_status,
        wallet_reputation_score,
        wallet_resolved_market_count,
    ) = _wallet_reputation(trades, resolved_outcomes)

    if (
        sample_size < MINIMUM_SAMPLE_SIZE
        or median_trade_size <= 0
        or total_bid_depth <= 0
        or total_ask_depth <= 0
    ):
        return WhaleActivityAnalysis(
            status="insufficient-data",
            sample_size=sample_size,
            median_trade_size=round(median_trade_size, 4),
            detections=(),
            attributed_trade_count=attributed_trade_count,
            unique_wallet_count=unique_wallet_count,
            wallet_concentration_status=wallet_concentration_status,
            wallet_concentration_score=wallet_concentration_score,
            top_wallet_volume_share=top_wallet_volume_share,
            wallet_reputation_status=wallet_reputation_status,
            wallet_reputation_score=wallet_reputation_score,
            wallet_resolved_market_count=wallet_resolved_market_count,
        )

    detections: list[LargeTradeDetection] = []
    for trade in trades:
        executable_depth = total_ask_depth if trade.side == "buy" else total_bid_depth
        historical_multiple = trade.size / median_trade_size
        depth_share = trade.size / executable_depth

        if (
            historical_multiple < HISTORICAL_MULTIPLE_THRESHOLD
            or depth_share < DEPTH_SHARE_THRESHOLD
        ):
            continue

        detections.append(
            LargeTradeDetection(
                trade_id=trade.id,
                side=trade.side,
                price=trade.price,
                size=trade.size,
                timestamp=trade.timestamp,
                notional_usd=round(trade.price * trade.size, 2),
                historical_size_multiple=round(historical_multiple, 2),
                executable_depth_share=round(depth_share, 4),
                wallet_address=trade.wallet_address,
            )
        )

    detections.sort(
        key=lambda detection: (
            detection.historical_size_multiple,
            detection.executable_depth_share,
        ),
        reverse=True,
    )
    return WhaleActivityAnalysis(
        status="detected" if detections else "clear",
        sample_size=sample_size,
        median_trade_size=round(median_trade_size, 4),
        detections=tuple(detections),
        attributed_trade_count=attributed_trade_count,
        unique_wallet_count=unique_wallet_count,
        wallet_concentration_status=wallet_concentration_status,
        wallet_concentration_score=wallet_concentration_score,
        top_wallet_volume_share=top_wallet_volume_share,
        wallet_reputation_status=wallet_reputation_status,
        wallet_reputation_score=wallet_reputation_score,
        wallet_resolved_market_count=wallet_resolved_market_count,
    )
