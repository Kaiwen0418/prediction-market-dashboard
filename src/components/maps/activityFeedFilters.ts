import type { MarketSignalKind } from "@/types/signals";

export type ActivitySignalFilter = "all" | MarketSignalKind;
export type ActivityTimeWindow = 0 | 1 | 6 | 24;
export type ActivityVolumeThreshold = 0 | 1_000 | 10_000 | 100_000;
export type MapViewMode = "world" | "country";
export type ActivityCountryScope = "global" | "country";

export type ActivityFeedFilterState = {
  mapView: MapViewMode;
  countryScope: ActivityCountryScope;
  countryCode: string;
  regionCode: string | null;
  minimumScore: number;
  minimumVolume: ActivityVolumeThreshold;
  signalKind: ActivitySignalFilter;
  maxAgeHours: ActivityTimeWindow;
};

export const DEFAULT_ACTIVITY_FILTERS: ActivityFeedFilterState = {
  mapView: "country",
  countryScope: "global",
  countryCode: "US",
  regionCode: null,
  minimumScore: 50,
  minimumVolume: 1_000,
  signalKind: "all",
  maxAgeHours: 0
};

const SIGNAL_FILTERS = new Set<ActivitySignalFilter>([
  "all",
  "whale-flow",
  "order-flow",
  "volume-anomaly",
  "price-move",
  "poll-divergence",
  "normal"
]);
const SCORE_THRESHOLDS = new Set([0, 50, 70, 85]);
const VOLUME_THRESHOLDS = new Set<ActivityVolumeThreshold>([
  0,
  1_000,
  10_000,
  100_000
]);
const TIME_WINDOWS = new Set<ActivityTimeWindow>([0, 1, 6, 24]);

export function parseActivityFeedFilters(
  input: string | URLSearchParams
): ActivityFeedFilterState {
  const params = typeof input === "string" ? new URLSearchParams(input) : input;
  const requestedMapView = params.get("view");
  const mapView =
    requestedMapView === "world" || requestedMapView === "country"
      ? requestedMapView
      : DEFAULT_ACTIVITY_FILTERS.mapView;
  const countryScope = params.get("scope") === "country" ? "country" : DEFAULT_ACTIVITY_FILTERS.countryScope;
  const countryCode = params.get("country")?.trim().toUpperCase() || DEFAULT_ACTIVITY_FILTERS.countryCode;
  const rawRegionCode = params.get("region")?.trim().toUpperCase() || null;
  const scoreParam = params.get("score");
  const rawScore = scoreParam === null ? Number.NaN : Number(scoreParam);
  const rawSignal = params.get("signal") as ActivitySignalFilter | null;
  const volumeParam = params.get("volume");
  const rawVolume = (
    volumeParam === null ? Number.NaN : Number(volumeParam)
  ) as ActivityVolumeThreshold;
  const windowParam = params.get("window");
  const rawWindow = (windowParam === null ? Number.NaN : Number(windowParam)) as ActivityTimeWindow;

  return {
    mapView,
    countryScope,
    countryCode: /^[A-Z]{2}$/.test(countryCode) ? countryCode : DEFAULT_ACTIVITY_FILTERS.countryCode,
    regionCode: rawRegionCode && /^[A-Z0-9]{2,3}$/.test(rawRegionCode) ? rawRegionCode : null,
    minimumScore: SCORE_THRESHOLDS.has(rawScore) ? rawScore : DEFAULT_ACTIVITY_FILTERS.minimumScore,
    minimumVolume: VOLUME_THRESHOLDS.has(rawVolume)
      ? rawVolume
      : DEFAULT_ACTIVITY_FILTERS.minimumVolume,
    signalKind: rawSignal && SIGNAL_FILTERS.has(rawSignal) ? rawSignal : DEFAULT_ACTIVITY_FILTERS.signalKind,
    maxAgeHours: TIME_WINDOWS.has(rawWindow) ? rawWindow : DEFAULT_ACTIVITY_FILTERS.maxAgeHours
  };
}

export function serializeActivityFeedFilters(
  filters: ActivityFeedFilterState,
  existing: string | URLSearchParams = ""
) {
  const params = typeof existing === "string" ? new URLSearchParams(existing) : new URLSearchParams(existing);

  const setOrDelete = (key: string, value: string | null, defaultValue: string | null) => {
    if (value === defaultValue || value === null) {
      params.delete(key);
    } else {
      params.set(key, value);
    }
  };

  setOrDelete("view", filters.mapView, DEFAULT_ACTIVITY_FILTERS.mapView);
  setOrDelete("scope", filters.countryScope, DEFAULT_ACTIVITY_FILTERS.countryScope);
  setOrDelete("country", filters.countryCode, DEFAULT_ACTIVITY_FILTERS.countryCode);
  setOrDelete("region", filters.regionCode, DEFAULT_ACTIVITY_FILTERS.regionCode);
  setOrDelete("score", String(filters.minimumScore), String(DEFAULT_ACTIVITY_FILTERS.minimumScore));
  setOrDelete(
    "volume",
    String(filters.minimumVolume),
    String(DEFAULT_ACTIVITY_FILTERS.minimumVolume)
  );
  setOrDelete("signal", filters.signalKind, DEFAULT_ACTIVITY_FILTERS.signalKind);
  setOrDelete("window", String(filters.maxAgeHours), String(DEFAULT_ACTIVITY_FILTERS.maxAgeHours));

  return params;
}
