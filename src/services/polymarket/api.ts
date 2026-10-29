import type { MarketSnapshot, OrderbookState, TimelineEvent, TimePoint } from "@/types/market";
import type { PollPoint } from "@/types/poll";
import { getNewsEvents } from "@/services/news/api";
import { fetchEventMarketBySlug, fetchFeaturedMarketLive, fetchOrderbookLive, fetchPriceHistoryLive, fetchTradesLive } from "./rest";
import {
  createMarketSeries,
  createOrderbookSnapshot,
  featuredMarket,
  getMockMarketBySlug,
  getMockMarketByTokenId,
  marketSeries,
  pollSeries
} from "./mockData";
import { normalizeTimelineFromMarket } from "./normalizers";

function simulateLatency<T>(payload: T, delay = 200): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(payload), delay);
  });
}

export async function getFeaturedMarket(): Promise<MarketSnapshot> {
  const liveMarket = await fetchFeaturedMarketLive().catch(() => null);
  return liveMarket ?? simulateLatency(featuredMarket);
}

export async function getFeaturedMarketStrict(): Promise<MarketSnapshot> {
  const liveMarket = await fetchFeaturedMarketLive().catch(() => null);
  if (!liveMarket) {
    throw new Error("Featured market live request failed and no fallback is allowed.");
  }
  return liveMarket;
}

export async function getMarketBySlug(slug: string): Promise<MarketSnapshot> {
  const liveMarket = await fetchEventMarketBySlug(slug).catch(() => null);
  return liveMarket ?? simulateLatency(getMockMarketBySlug(slug));
}

export async function getMarketBySlugStrict(slug: string): Promise<MarketSnapshot> {
  const liveMarket = await fetchEventMarketBySlug(slug).catch(() => null);
  if (!liveMarket) {
    throw new Error(`Live market request failed for slug "${slug}" and no fallback is allowed.`);
  }
  return liveMarket;
}

export async function getHistoricalMarketSeries(tokenId?: string): Promise<TimePoint[]> {
  if (!tokenId) return simulateLatency(marketSeries);

  const liveHistory = await fetchPriceHistoryLive(tokenId).catch(() => []);
  if (liveHistory.length > 1) return liveHistory;
  return simulateLatency(createMarketSeries(getMockMarketByTokenId(tokenId)));
}

export async function getHistoricalPollSeries(): Promise<PollPoint[]> {
  return simulateLatency(pollSeries);
}

export async function getOrderbookSnapshot(tokenId?: string, conditionId?: string): Promise<OrderbookState> {
  if (tokenId) {
    const liveOrderbook = await fetchOrderbookLive(tokenId).catch(() => null);
    if (liveOrderbook) {
      const liveTrades = conditionId ? await fetchTradesLive(conditionId).catch(() => []) : [];
      return {
        ...liveOrderbook,
        trades: liveTrades.length ? liveTrades : liveOrderbook.trades
      };
    }
  }

  return simulateLatency(createOrderbookSnapshot(getMockMarketByTokenId(tokenId)), 180);
}

export async function getOrderbookSnapshotStrict(tokenId?: string, conditionId?: string): Promise<OrderbookState> {
  if (!tokenId) {
    throw new Error("Cannot load live orderbook without a live token id.");
  }

  const liveOrderbook = await fetchOrderbookLive(tokenId).catch(() => null);
  if (!liveOrderbook) {
    throw new Error("Live orderbook request failed and no fallback is allowed.");
  }

  const liveTrades = conditionId ? await fetchTradesLive(conditionId).catch(() => []) : [];
  return {
    ...liveOrderbook,
    trades: liveTrades.length ? liveTrades : liveOrderbook.trades
  };
}

export async function getTimelineEvents(market?: MarketSnapshot): Promise<TimelineEvent[]> {
  const events = await getNewsEvents().catch(() => []);
  if (events.length) return events;
  if (market) return normalizeTimelineFromMarket(market);
  return normalizeTimelineFromMarket(featuredMarket);
}
