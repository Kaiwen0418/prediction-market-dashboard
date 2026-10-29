import type {
  MarketSignalKind,
  MarketSignalSeverity,
  RegionMarketSignal,
  RegionSignal
} from "@/types/signals";

export type {
  MarketSignalKind,
  MarketSignalSeverity,
  MarketSignalSource,
  RegionMarketSignal,
  RegionSignal,
  RegionSignalComponent,
  RegionSignalsResponse
} from "@/types/signals";

export const SIGNAL_LEGEND: Array<{
  severity: Exclude<MarketSignalSeverity, "inactive">;
  label: string;
}> = [
  { severity: "normal", label: "Normal" },
  { severity: "elevated", label: "Elevated" },
  { severity: "high", label: "High" },
  { severity: "critical", label: "Critical" }
];

const INACTIVE_SIGNAL_COLOR = "#dededb";
const SIGNAL_COLOR_STOPS = [
  { score: 0, color: [255, 244, 194] },
  { score: 50, color: [250, 188, 64] },
  { score: 70, color: [239, 120, 35] },
  { score: 100, color: [190, 45, 32] }
] as const;

function interpolateChannel(start: number, end: number, progress: number) {
  return Math.round(start + (end - start) * progress);
}

export function getMarketSignalSeverity(score?: number | null): MarketSignalSeverity {
  if (score === undefined || score === null) {
    return "inactive";
  }

  const boundedScore = Math.max(0, Math.min(100, score));

  if (boundedScore >= 85) {
    return "critical";
  }

  if (boundedScore >= 70) {
    return "high";
  }

  if (boundedScore >= 50) {
    return "elevated";
  }

  return "normal";
}

export function getMarketSignalColor(score?: number | null) {
  if (score === undefined || score === null) {
    return INACTIVE_SIGNAL_COLOR;
  }

  const boundedScore = Math.max(0, Math.min(100, score));
  const endIndex = SIGNAL_COLOR_STOPS.findIndex(
    (stop) => boundedScore <= stop.score
  );
  const boundedEndIndex =
    endIndex <= 0 ? 1 : Math.min(endIndex, SIGNAL_COLOR_STOPS.length - 1);
  const start = SIGNAL_COLOR_STOPS[boundedEndIndex - 1];
  const end = SIGNAL_COLOR_STOPS[boundedEndIndex];
  const progress = (boundedScore - start.score) / (end.score - start.score);
  const color = start.color.map((channel, index) =>
    interpolateChannel(channel, end.color[index], progress)
  );

  return `rgb(${color.join(", ")})`;
}

export function getMarketSignalLabel(signal?: RegionMarketSignal | null) {
  if (!signal) {
    return "No active signal";
  }

  return signal.kind
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export type RankedRegionSignal<T> = {
  region: T;
  signal: RegionMarketSignal;
  priority: number;
};

export type RegionSignalRankingOptions = {
  minimumScore?: number;
  signalKind?: "all" | MarketSignalKind;
  maxAgeHours?: number;
  now?: Date;
};

export function rankRegionSignals<T extends { code: string; signal: RegionMarketSignal }>(
  regions: T[],
  overrides: RegionSignal[],
  options: RegionSignalRankingOptions = {}
): Array<RankedRegionSignal<T>> {
  const {
    minimumScore = 0,
    signalKind = "all",
    maxAgeHours = 0,
    now = new Date()
  } = options;
  const overrideByRegion = new Map(overrides.map((signal) => [signal.regionCode, signal]));
  const nowMs = now.getTime();

  return regions
    .map((region) => {
      const signal = overrideByRegion.get(region.code) ?? region.signal;
      const observedAtMs = Date.parse(signal.observedAt);
      const ageHours = Number.isFinite(observedAtMs) ? Math.max(0, nowMs - observedAtMs) / 3_600_000 : 24;
      const freshnessBoost = signal.source === "live" ? Math.max(0, 5 - ageHours) : 0;
      const confidenceBoost = signal.source === "live" ? (signal.confidence ?? 0) * 5 : 0;

      return {
        region,
        signal,
        priority: signal.score + freshnessBoost + confidenceBoost
      };
    })
    .filter((item) => {
      if (item.signal.score < minimumScore) {
        return false;
      }
      if (signalKind !== "all" && item.signal.kind !== signalKind) {
        return false;
      }
      if (maxAgeHours <= 0) {
        return true;
      }
      const observedAtMs = Date.parse(item.signal.observedAt);
      return Number.isFinite(observedAtMs) && nowMs - observedAtMs <= maxAgeHours * 3_600_000;
    })
    .sort((left, right) => right.priority - left.priority || right.signal.score - left.signal.score);
}
