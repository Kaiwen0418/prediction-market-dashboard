import { getRegionPolymarketSlugs } from "@/components/maps/spotlightStates";
import type { RegionMarket } from "@/components/maps/spotlightStates";
import type { MarketTradePrint } from "@/types/market";

export const MAX_GLOBE_TRADE_POPUPS = 3;
export const GLOBE_TRADE_POPUP_TTL_MS = 7_000;

export type RegionVenueTrade = {
  region: RegionMarket;
  trade: MarketTradePrint;
};

export type ExpiringTradePopup<T extends { id: string }> = T & {
  expiresAt: number;
};

export function matchVenueTradesToRegions(
  trades: MarketTradePrint[],
  regions: RegionMarket[]
): RegionVenueTrade[] {
  const regionBySlug = new Map<string, RegionMarket>();

  regions.forEach((region) => {
    getRegionPolymarketSlugs(region).forEach((slug) => {
      if (!regionBySlug.has(slug)) {
        regionBySlug.set(slug, region);
      }
    });
  });

  return trades.flatMap((trade) => {
    const region =
      regionBySlug.get(trade.marketSlug) ??
      (trade.eventSlug ? regionBySlug.get(trade.eventSlug) : undefined);

    return region ? [{ region, trade }] : [];
  });
}

export function appendTradePopupQueue<T extends { id: string }>(
  current: ExpiringTradePopup<T>[],
  incoming: T[],
  now: number,
  ttlMs = GLOBE_TRADE_POPUP_TTL_MS,
  limit = MAX_GLOBE_TRADE_POPUPS
) {
  const next = current.filter((popup) => popup.expiresAt > now);
  const queuedIds = new Set(next.map((popup) => popup.id));

  incoming.forEach((popup) => {
    if (queuedIds.has(popup.id)) return;
    next.push({ ...popup, expiresAt: now + ttlMs });
    queuedIds.add(popup.id);
  });

  return next.slice(-limit);
}
