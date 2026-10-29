export type TimePoint = {
  timestamp: string;
  value: number;
};

export type MarketStatus = "open" | "closed" | "inactive" | "unknown";

export type MarketSnapshot = {
  marketId: string;
  conditionId?: string;
  eventId?: string;
  tokenId?: string;
  slug: string;
  eventSlug?: string;
  title: string;
  category: string;
  probability: number;
  volume24h: number;
  openInterest: number;
  liquidity?: number;
  image?: string;
  description?: string;
  endDate?: string;
  resolutionSource?: string;
  venue?: string;
  status: MarketStatus;
  outcomeLabel?: string;
  contractLabel?: string;
  updatedAt: string;
};

export type VenueMarketSummary = {
  venue: "Kalshi";
  eventTicker: string;
  marketTicker: string;
  seriesTicker: string;
  title: string;
  outcomeLabel?: string;
  probability: number;
  volume24h: number;
  liquidity?: number;
  status: MarketStatus;
  endDate?: string;
  resolutionSource?: string;
  url: string;
  updatedAt: string;
};

export type KalshiMarketAnalytics = {
  venue: "Kalshi";
  market: MarketSnapshot;
  orderbook: OrderbookState;
  orderbookSummary: OrderbookSummary;
  marketSeries: TimePoint[];
  replay: LiveReplay;
};

export type OrderbookLevel = {
  price: number;
  size: number;
};

export type TradePrint = {
  id: string;
  side: "buy" | "sell";
  price: number;
  size: number;
  timestamp: string;
  walletAddress?: string;
};

export type MarketTradePrint = TradePrint & {
  conditionId: string;
  marketSlug: string;
  eventSlug?: string;
  title: string;
  outcome?: string;
};

export type OrderbookState = {
  marketId: string;
  tokenId?: string;
  bids: OrderbookLevel[];
  asks: OrderbookLevel[];
  trades: TradePrint[];
  spread: number;
  midPrice: number;
  tickSize?: number;
  source: "mock" | "live";
  updatedAt: string;
};

export type OrderbookSummary = {
  marketId: string;
  tokenId: string;
  updatedAt: string;
  bestBid: number;
  bestAsk: number;
  midPrice: number;
  spread: number;
  bidLevels: number;
  askLevels: number;
  tradeCount: number;
  liquidity: {
    totalBidDepth: number;
    totalAskDepth: number;
    imbalance: number;
    spreadBps: number;
  };
  tradePressure: {
    buyVolume: number;
    sellVolume: number;
    ratio: number;
    pressure: "buy" | "sell" | "balanced";
  };
  whaleActivity?: {
    status: "insufficient-data" | "clear" | "detected";
    sampleSize: number;
    medianTradeSize: number;
    historicalMultipleThreshold: number;
    depthShareThreshold: number;
    minimumSampleSize: number;
    attributionAvailable: boolean;
    attributedTradeCount: number;
    uniqueWalletCount: number;
    walletSampleMinimum: number;
    walletConcentrationStatus: "unavailable" | "insufficient-data" | "available";
    walletConcentrationScore: number | null;
    topWalletVolumeShare: number | null;
    walletReputationStatus: "unavailable" | "insufficient-history" | "available";
    walletReputationScore: number | null;
    walletResolvedMarketCount: number;
    walletResolvedMarketMinimum: number;
    largeTrades: Array<{
      tradeId: string;
      side: "buy" | "sell";
      price: number;
      size: number;
      timestamp: string;
      notionalUsd: number;
      historicalSizeMultiple: number;
      executableDepthShare: number;
      walletAddress?: string | null;
    }>;
  };
};

export type PriceHistoryMeta = {
  market: string;
  points: number;
  startTimestamp?: string | null;
  endTimestamp?: string | null;
};

export type MarketContext = {
  featuredMarket: MarketSnapshot;
  orderbookSummary: OrderbookSummary | null;
  priceHistoryMeta: PriceHistoryMeta;
  timelineEvents: TimelineEvent[];
};

export type LiveStreamStatus = {
  enabled: boolean;
  state: string;
  marketSlug: string;
  marketId?: string | null;
  tokenId?: string | null;
  connectedAt?: string | null;
  lastMessageAt?: string | null;
  lastEventType?: string | null;
  messageCount: number;
  reconnectCount: number;
  latencyMs?: number | null;
  error?: string | null;
};

export type LiveMicrostructureMetrics = {
  microprice: number;
  depthSkew: number;
  realizedVolatility: number;
  tradeIntensity: number;
  orderFlowImbalance: number;
};

export type LiveMetricSample = {
  timestamp: string;
  midPrice: number;
  spreadBps: number;
  microprice: number;
  depthSkew: number;
  realizedVolatility: number;
  tradeIntensity: number;
  orderFlowImbalance: number;
};

export type LiveMarketSnapshot = {
  status: LiveStreamStatus;
  orderbookSummary: OrderbookSummary | null;
  microstructure?: LiveMicrostructureMetrics | null;
};

export type LiveReplay = {
  status: LiveStreamStatus;
  samples: LiveMetricSample[];
  sampleCount: number;
  source?: "stream" | "fixture";
};

export type LiveRegistryHealth = {
  enabled: boolean;
  state: string;
  featuredSlug: string;
  registrySize: number;
  connectedStreams: number;
  errorStreams: number;
  staleStreams: number;
  disabledStreams: number;
  maxMarkets: number;
  idleTtlSeconds: number;
  streams: LiveStreamStatus[];
};

export type LiveReadinessCheck = {
  name: string;
  state: string;
  detail: string;
};

export type LiveReadiness = {
  ready: boolean;
  state: string;
  featuredSlug: string;
  checks: LiveReadinessCheck[];
};

export type LiveDegradationIssue = {
  code: string;
  severity: string;
  summary: string;
  streamSlug?: string | null;
  detail?: string | null;
};

export type LiveDegradation = {
  state: string;
  issueCount: number;
  issues: LiveDegradationIssue[];
};

export type TimelineEvent = {
  id: string;
  eventId?: string;
  timestamp: string;
  headline: string;
  source: string;
  category?: string;
  impactScore: number;
  marketMove: number;
  summary: string;
};
