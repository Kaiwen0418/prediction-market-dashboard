import {
  kalshiMarketMatchesRegion,
  marketMatchesRegion,
  type RegionMarket
} from "@/components/maps/spotlightStates";
import type { MarketSnapshot, VenueMarketSummary } from "@/types/market";

export const KALSHI_VOLUME_COLOR = "#3f7f6b";
const MINIMUM_MARKET_VOLUME_OPACITY = 0.24;
const MAXIMUM_MARKET_VOLUME_OPACITY = 0.94;
const DEFAULT_UNKNOWN_VOLUME_OPACITY = 0.82;
const VOLUME_OPACITY_CEILING = 500_000;

export function getRegionMarketVolume(
  region: RegionMarket,
  kalshiMarkets: VenueMarketSummary[],
  polymarketMarkets: MarketSnapshot[] = []
) {
  const polymarketVolume = polymarketMarkets
    .filter((market) => marketMatchesRegion(region, market))
    .reduce((sum, market) => sum + market.volume24h, 0);
  const kalshiVolume = kalshiMarkets
    .filter((market) => kalshiMarketMatchesRegion(region, market))
    .reduce((sum, market) => sum + market.volume24h, 0);
  const totalVolume = polymarketVolume + kalshiVolume;

  return totalVolume > 0 ? totalVolume : null;
}

export function qualifiesByVolume(
  region: RegionMarket,
  volume24h: number | null,
  minimumVolume: number
) {
  return (
    volume24h !== null &&
    (minimumVolume === 0 || volume24h >= minimumVolume)
  );
}

export function qualifiesBySignal(
  region: RegionMarket,
  score: number,
  minimumScore: number
) {
  return (
    score >= minimumScore &&
    (Boolean(region.liveMarketSlug) || score > 0)
  );
}

export function getMarketVolumeOpacity(volume24h: number | null) {
  if (volume24h === null || !Number.isFinite(volume24h)) {
    return DEFAULT_UNKNOWN_VOLUME_OPACITY;
  }

  const boundedVolume = Math.max(
    0,
    Math.min(VOLUME_OPACITY_CEILING, volume24h)
  );
  const progress =
    Math.log1p(boundedVolume) / Math.log1p(VOLUME_OPACITY_CEILING);

  return (
    MINIMUM_MARKET_VOLUME_OPACITY +
    progress *
      (MAXIMUM_MARKET_VOLUME_OPACITY - MINIMUM_MARKET_VOLUME_OPACITY)
  );
}

export function formatMarketVolume(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}
