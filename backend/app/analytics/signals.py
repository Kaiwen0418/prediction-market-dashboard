from dataclasses import dataclass
from statistics import median
from typing import Sequence

from app.schemas.live import LiveMetricSampleResponse


@dataclass(frozen=True)
class SignalComponentScore:
    key: str
    label: str
    value: float
    weight: float
    available: bool
    detail: str

    @property
    def contribution(self) -> float:
        return round(self.value * self.weight, 3) if self.available else 0.0


@dataclass(frozen=True)
class RegionActivityScore:
    score: int
    confidence: float
    kind: str
    components: tuple[SignalComponentScore, ...]


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 3)


def calculate_region_activity_score(
    samples: Sequence[LiveMetricSampleResponse],
) -> RegionActivityScore | None:
    if len(samples) < 2:
        return None

    latest = samples[-1]
    baseline = samples[:-1]
    baseline_intensity = median(sample.trade_intensity for sample in baseline)
    intensity_ratio = latest.trade_intensity / baseline_intensity if baseline_intensity > 0 else 0.0
    volume_score = _clamp_score((intensity_ratio - 1.0) * 50.0) if intensity_ratio > 0 else 0.0
    order_flow_score = _clamp_score(abs(latest.order_flow_imbalance) * 100.0)
    probability_move = abs(latest.mid_price - samples[0].mid_price)
    price_move_score = _clamp_score(probability_move * 1_000.0)

    components = (
        SignalComponentScore(
            key="volume-anomaly",
            label="Volume anomaly",
            value=volume_score,
            weight=0.30,
            available=True,
            detail=f"Latest trade intensity is {intensity_ratio:.2f}x the replay baseline.",
        ),
        SignalComponentScore(
            key="order-flow",
            label="Order-flow imbalance",
            value=order_flow_score,
            weight=0.25,
            available=True,
            detail=f"Absolute order-flow imbalance is {abs(latest.order_flow_imbalance) * 100:.1f}%.",
        ),
        SignalComponentScore(
            key="price-move",
            label="Probability velocity",
            value=price_move_score,
            weight=0.20,
            available=True,
            detail=f"Probability moved {probability_move * 100:.2f} points across the replay window.",
        ),
        SignalComponentScore(
            key="wallet-concentration",
            label="Wallet concentration",
            value=0.0,
            weight=0.15,
            available=False,
            detail="Wallet-level attribution is not available from the current stream.",
        ),
        SignalComponentScore(
            key="poll-divergence",
            label="Poll divergence",
            value=0.0,
            weight=0.10,
            available=False,
            detail="No timestamp-aligned polling baseline is attached to this live window.",
        ),
    )

    available_weight = sum(component.weight for component in components if component.available)
    weighted_score = sum(component.contribution for component in components)
    score = round(weighted_score / available_weight) if available_weight else 0
    leading_component = max(
        (component for component in components if component.available),
        key=lambda component: component.contribution,
    )

    return RegionActivityScore(
        score=max(0, min(100, score)),
        confidence=round(available_weight, 2),
        kind=leading_component.key,
        components=components,
    )


def get_signal_severity(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 50:
        return "elevated"
    return "normal"
