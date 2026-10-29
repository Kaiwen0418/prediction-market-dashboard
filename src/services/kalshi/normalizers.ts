import type {
  KalshiMarketAnalytics,
  LiveMetricSample,
  MarketSnapshot,
  MarketStatus,
  OrderbookLevel,
  OrderbookState,
  OrderbookSummary,
  TimePoint,
  TradePrint,
  VenueMarketSummary
} from "@/types/market";

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function asTimestamp(value: unknown) {
  const timestamp = new Date(asString(value));
  return Number.isFinite(timestamp.getTime())
    ? timestamp.toISOString()
    : undefined;
}

function asEpochTimestamp(value: unknown) {
  const seconds = asNumber(value, Number.NaN);
  return Number.isFinite(seconds)
    ? new Date(seconds * 1_000).toISOString()
    : undefined;
}

function asHttpUrl(value: unknown) {
  const rawUrl = asString(value);
  if (!rawUrl) return undefined;

  try {
    const url = new URL(rawUrl);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function normalizeStatus(markets: UnknownRecord[]): MarketStatus {
  const statuses = new Set(markets.map((market) => asString(market.status)));
  if (statuses.has("active")) return "open";
  if (statuses.has("inactive") || statuses.has("paused")) return "inactive";
  if (statuses.has("closed") || statuses.has("finalized")) return "closed";
  return "unknown";
}

function getKalshiUrl(seriesTicker: string, eventTicker: string) {
  return `https://kalshi.com/markets/${seriesTicker.toLowerCase()}/${eventTicker.toLowerCase()}`;
}

export function normalizeKalshiEvents(payload: unknown): VenueMarketSummary[] {
  if (!isRecord(payload) || !Array.isArray(payload.events)) return [];

  return payload.events.flatMap((eventValue) => {
    if (!isRecord(eventValue) || !Array.isArray(eventValue.markets)) return [];

    const eventTicker = asString(eventValue.event_ticker);
    const seriesTicker = asString(eventValue.series_ticker);
    const markets = eventValue.markets.filter(isRecord);
    if (!eventTicker || !seriesTicker || !markets.length) return [];

    const tradableMarkets = markets.filter(
      (market) => asString(market.status) === "active"
    );
    const rankedMarkets = (tradableMarkets.length ? tradableMarkets : markets)
      .slice()
      .sort(
        (left, right) =>
          asNumber(right.last_price_dollars) -
          asNumber(left.last_price_dollars)
      );
    const leader = rankedMarkets[0];
    const marketTicker = asString(leader.ticker);
    if (!marketTicker) return [];
    const settlementSource = Array.isArray(eventValue.settlement_sources)
      ? eventValue.settlement_sources.find(isRecord)
      : undefined;

    return [
      {
        venue: "Kalshi" as const,
        eventTicker,
        marketTicker,
        seriesTicker,
        title: asString(eventValue.title, asString(leader.title, eventTicker)),
        outcomeLabel:
          asString(leader.yes_sub_title) ||
          asString(leader.subtitle) ||
          undefined,
        probability: asNumber(leader.last_price_dollars),
        volume24h: markets.reduce(
          (sum, market) => sum + asNumber(market.volume_24h_fp),
          0
        ),
        liquidity: markets.reduce(
          (sum, market) => sum + asNumber(market.liquidity_dollars),
          0
        ),
        status: normalizeStatus(markets),
        endDate:
          asTimestamp(leader.expected_expiration_time) ??
          asTimestamp(leader.close_time),
        resolutionSource: settlementSource
          ? asHttpUrl(settlementSource.url)
          : undefined,
        url: getKalshiUrl(seriesTicker, eventTicker),
        updatedAt: new Date().toISOString()
      }
    ];
  });
}

function normalizeLevels(
  value: unknown,
  side: "yes" | "no"
): OrderbookLevel[] {
  if (!Array.isArray(value)) return [];

  return value
    .flatMap((level) => {
      if (!Array.isArray(level) || level.length < 2) return [];
      const rawPrice = asNumber(level[0], Number.NaN);
      const size = asNumber(level[1], Number.NaN);
      if (
        !Number.isFinite(rawPrice) ||
        !Number.isFinite(size) ||
        rawPrice < 0 ||
        rawPrice > 1 ||
        size <= 0
      ) {
        return [];
      }

      return [{ price: side === "yes" ? rawPrice : 1 - rawPrice, size }];
    })
    .sort((left, right) =>
      side === "yes" ? right.price - left.price : left.price - right.price
    );
}

function normalizeKalshiTrades(payload: unknown): TradePrint[] {
  if (!isRecord(payload) || !Array.isArray(payload.trades)) return [];

  return payload.trades.flatMap((tradeValue) => {
    if (!isRecord(tradeValue)) return [];
    const id = asString(tradeValue.trade_id);
    const timestamp = asTimestamp(tradeValue.created_time);
    const price = asNumber(tradeValue.yes_price_dollars, Number.NaN);
    const size = asNumber(tradeValue.count_fp, Number.NaN);
    if (
      !id ||
      !timestamp ||
      !Number.isFinite(price) ||
      !Number.isFinite(size) ||
      price < 0 ||
      price > 1 ||
      size <= 0
    ) {
      return [];
    }

    return [
      {
        id,
        side:
          asString(tradeValue.taker_outcome_side, asString(tradeValue.taker_side)) ===
          "no"
            ? ("sell" as const)
            : ("buy" as const),
        price,
        size,
        timestamp
      }
    ];
  });
}

function normalizeCandlesticks(payload: unknown): Array<{
  point: TimePoint;
  bid: number | null;
  ask: number | null;
  volume: number;
}> {
  if (!isRecord(payload) || !Array.isArray(payload.candlesticks)) return [];

  return payload.candlesticks
    .flatMap((candleValue) => {
      if (!isRecord(candleValue)) return [];
      const price = isRecord(candleValue.price) ? candleValue.price : {};
      const yesBid = isRecord(candleValue.yes_bid)
        ? candleValue.yes_bid
        : {};
      const yesAsk = isRecord(candleValue.yes_ask)
        ? candleValue.yes_ask
        : {};
      const timestamp = asEpochTimestamp(candleValue.end_period_ts);
      const value = asNumber(
        price.close_dollars,
        asNumber(price.previous_dollars, Number.NaN)
      );
      if (
        !timestamp ||
        !Number.isFinite(value) ||
        value < 0 ||
        value > 1
      ) {
        return [];
      }

      const bid = asNumber(yesBid.close_dollars, Number.NaN);
      const ask = asNumber(yesAsk.close_dollars, Number.NaN);
      return [
        {
          point: { timestamp, value },
          bid: Number.isFinite(bid) ? bid : null,
          ask: Number.isFinite(ask) ? ask : null,
          volume: asNumber(candleValue.volume_fp)
        }
      ];
    })
    .sort((left, right) =>
      left.point.timestamp.localeCompare(right.point.timestamp)
    );
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
    values.length;
  return Math.sqrt(variance);
}

function buildReplaySamples(
  candles: ReturnType<typeof normalizeCandlesticks>
): LiveMetricSample[] {
  return candles.slice(-48).map((candle, index, visibleCandles) => {
    const recent = visibleCandles.slice(Math.max(0, index - 5), index + 1);
    const changes = recent.slice(1).map(
      (point, changeIndex) =>
        point.point.value - recent[changeIndex].point.value
    );
    const previousValue =
      visibleCandles[index - 1]?.point.value ?? candle.point.value;
    const direction = Math.sign(candle.point.value - previousValue);
    const spread =
      candle.bid !== null && candle.ask !== null
        ? Math.max(0, candle.ask - candle.bid)
        : 0;

    return {
      timestamp: candle.point.timestamp,
      midPrice: candle.point.value,
      spreadBps:
        candle.point.value > 0
          ? Number(((spread / candle.point.value) * 10_000).toFixed(1))
          : 0,
      microprice: candle.point.value,
      depthSkew: 0,
      realizedVolatility: Number(standardDeviation(changes).toFixed(5)),
      tradeIntensity: candle.volume,
      orderFlowImbalance: direction
    };
  });
}

function median(values: number[]) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function normalizeKalshiAnalytics(
  payload: unknown,
  summary: VenueMarketSummary
): KalshiMarketAnalytics | null {
  if (!isRecord(payload)) return null;
  const orderbookPayload = isRecord(payload.orderbook)
    ? payload.orderbook
    : {};
  const orderbookFp = isRecord(orderbookPayload.orderbook_fp)
    ? orderbookPayload.orderbook_fp
    : {};
  const bids = normalizeLevels(orderbookFp.yes_dollars, "yes");
  const asks = normalizeLevels(orderbookFp.no_dollars, "no");
  const trades = normalizeKalshiTrades(payload.trades);
  const candles = normalizeCandlesticks(payload.candlesticks);
  const bestBid = bids[0]?.price ?? summary.probability;
  const bestAsk = asks[0]?.price ?? summary.probability;
  const midPrice =
    bids.length && asks.length
      ? (bestBid + bestAsk) / 2
      : summary.probability;
  const spread = Math.max(0, bestAsk - bestBid);
  const updatedAt =
    trades[0]?.timestamp ??
    candles.at(-1)?.point.timestamp ??
    summary.updatedAt;
  const totalBidDepth = bids.reduce((sum, level) => sum + level.size, 0);
  const totalAskDepth = asks.reduce((sum, level) => sum + level.size, 0);
  const totalDepth = totalBidDepth + totalAskDepth;
  const buyVolume = trades
    .filter((trade) => trade.side === "buy")
    .reduce((sum, trade) => sum + trade.size, 0);
  const sellVolume = trades
    .filter((trade) => trade.side === "sell")
    .reduce((sum, trade) => sum + trade.size, 0);
  const tradeSizes = trades.map((trade) => trade.size);
  const medianTradeSize = median(tradeSizes);
  const largeTrades = trades.flatMap((trade) => {
    const executableDepth =
      trade.side === "buy" ? totalAskDepth : totalBidDepth;
    const sizeMultiple =
      medianTradeSize > 0 ? trade.size / medianTradeSize : 0;
    const depthShare =
      executableDepth > 0 ? trade.size / executableDepth : 0;
    if (sizeMultiple < 3 || depthShare < 0.05) return [];

    return [
      {
        tradeId: trade.id,
        side: trade.side,
        price: trade.price,
        size: trade.size,
        timestamp: trade.timestamp,
        notionalUsd: trade.price * trade.size,
        historicalSizeMultiple: sizeMultiple,
        executableDepthShare: depthShare
      }
    ];
  });
  const market: MarketSnapshot = {
    marketId: summary.marketTicker,
    eventId: summary.eventTicker,
    tokenId: summary.marketTicker,
    slug: summary.marketTicker,
    eventSlug: summary.eventTicker,
    title: summary.title,
    category: "Politics",
    probability: summary.probability,
    volume24h: summary.volume24h,
    openInterest: 0,
    liquidity: summary.liquidity,
    endDate: summary.endDate,
    resolutionSource: summary.resolutionSource,
    venue: "Kalshi",
    status: summary.status,
    outcomeLabel: summary.outcomeLabel ?? "Yes",
    contractLabel: summary.title,
    updatedAt
  };
  const orderbook: OrderbookState = {
    marketId: summary.marketTicker,
    tokenId: summary.marketTicker,
    bids,
    asks,
    trades,
    spread,
    midPrice,
    source: "live",
    updatedAt
  };
  const orderbookSummary: OrderbookSummary = {
    marketId: summary.marketTicker,
    tokenId: summary.marketTicker,
    updatedAt,
    bestBid,
    bestAsk,
    midPrice,
    spread,
    bidLevels: bids.length,
    askLevels: asks.length,
    tradeCount: trades.length,
    liquidity: {
      totalBidDepth,
      totalAskDepth,
      imbalance:
        totalDepth > 0 ? (totalBidDepth - totalAskDepth) / totalDepth : 0,
      spreadBps:
        midPrice > 0 ? Number(((spread / midPrice) * 10_000).toFixed(1)) : 0
    },
    tradePressure: {
      buyVolume,
      sellVolume,
      ratio: sellVolume > 0 ? buyVolume / sellVolume : buyVolume,
      pressure:
        buyVolume > sellVolume * 1.2
          ? "buy"
          : sellVolume > buyVolume * 1.2
            ? "sell"
            : "balanced"
    },
    whaleActivity: {
      status:
        trades.length < 5
          ? "insufficient-data"
          : largeTrades.length
            ? "detected"
            : "clear",
      sampleSize: trades.length,
      medianTradeSize,
      historicalMultipleThreshold: 3,
      depthShareThreshold: 0.05,
      minimumSampleSize: 5,
      attributionAvailable: false,
      attributedTradeCount: 0,
      uniqueWalletCount: 0,
      walletSampleMinimum: 10,
      walletConcentrationStatus: "unavailable",
      walletConcentrationScore: null,
      topWalletVolumeShare: null,
      walletReputationStatus: "unavailable",
      walletReputationScore: null,
      walletResolvedMarketCount: 0,
      walletResolvedMarketMinimum: 5,
      largeTrades
    }
  };
  const samples = buildReplaySamples(candles);

  return {
    venue: "Kalshi",
    market,
    orderbook,
    orderbookSummary,
    marketSeries: candles.map((candle) => candle.point),
    replay: {
      status: {
        enabled: true,
        state: samples.length ? "historical" : "pending",
        marketSlug: summary.marketTicker,
        marketId: summary.marketTicker,
        tokenId: summary.marketTicker,
        messageCount: samples.length,
        reconnectCount: 0,
        lastMessageAt: samples.at(-1)?.timestamp ?? null
      },
      samples,
      sampleCount: samples.length,
      source: "stream"
    }
  };
}
