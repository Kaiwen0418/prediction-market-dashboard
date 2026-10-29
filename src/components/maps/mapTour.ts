import type { RegionMarket } from "@/components/maps/spotlightStates";
import type { RegionSignal } from "@/types/signals";

export function getAutoTourRegions(
  regions: RegionMarket[],
  signals: RegionSignal[]
) {
  const signalByRegion = new Map(
    signals.map((signal) => [
      `${signal.countryCode}:${signal.regionCode}`,
      signal
    ])
  );

  const getScore = (region: RegionMarket) =>
    signalByRegion.get(`${region.countryCode}:${region.code}`)?.score ??
    region.signal.score;

  return regions
    .filter(
      (region) => region.marketStatus === "open" && getScore(region) >= 70
    )
    .sort((left, right) => getScore(right) - getScore(left));
}
