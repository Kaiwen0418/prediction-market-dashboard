export type MarketSignalKind =
  | "whale-flow"
  | "order-flow"
  | "volume-anomaly"
  | "price-move"
  | "poll-divergence"
  | "normal";

export type MarketSignalSource = "fixture" | "live";

export type MarketSignalSeverity = "inactive" | "normal" | "elevated" | "high" | "critical";

export type RegionSignalComponent = {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  available: boolean;
  detail: string;
};

export type RegionMarketSignal = {
  kind: MarketSignalKind;
  score: number;
  headline: string;
  detail: string;
  observedAt: string;
  source: MarketSignalSource;
  confidence?: number;
  baselineWindow?: string;
  components?: RegionSignalComponent[];
  freshness?: "fixture" | "fresh" | "stale";
  ageSeconds?: number | null;
  degradationReasons?: string[];
};

export type RegionSignal = RegionMarketSignal & {
  regionCode: string;
  countryCode: string;
  marketSlug: string;
  severity: Exclude<MarketSignalSeverity, "inactive">;
  confidence: number;
  baselineWindow: string;
  components: RegionSignalComponent[];
};

export type RegionSignalsResponse = {
  countryCode: string;
  generatedAt: string;
  source: "fixture" | "mixed" | "live";
  freshness: "fixture" | "fresh" | "stale";
  degradationReasons: string[];
  signals: RegionSignal[];
};
