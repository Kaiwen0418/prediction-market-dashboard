import { withApiBase } from "@/services/api/base";
import { normalizeKalshiEvents } from "@/services/kalshi/normalizers";
import { normalizeGammaEvent } from "@/services/polymarket/normalizers";
import type { MarketSnapshot, VenueMarketSummary } from "@/types/market";

type UnknownRecord = Record<string, unknown>;

export type VenueCatalog = {
  updatedAt: string | null;
  polymarketMarkets: MarketSnapshot[];
  kalshiMarkets: VenueMarketSummary[];
  counts: {
    polymarket: number;
    kalshi: number;
  };
};

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null;
}

function dedupeBy<T>(values: T[], getKey: (value: T) => string) {
  return [...new Map(values.map((value) => [getKey(value), value])).values()];
}

export function normalizeVenueCatalog(payload: unknown): VenueCatalog | null {
  if (!isRecord(payload) || !isRecord(payload.venues)) return null;
  const polymarket = isRecord(payload.venues.polymarket)
    ? payload.venues.polymarket
    : {};
  const kalshi = isRecord(payload.venues.kalshi)
    ? payload.venues.kalshi
    : {};
  const polymarketEvents = Array.isArray(polymarket.events)
    ? polymarket.events
    : [];
  const kalshiEvents = Array.isArray(kalshi.events) ? kalshi.events : [];
  if (
    polymarketEvents.length === 0 &&
    kalshiEvents.length === 0 &&
    typeof polymarket.error === "string" &&
    typeof kalshi.error === "string"
  ) {
    return null;
  }
  const polymarketMarkets = dedupeBy(
    polymarketEvents
      .map((event) => normalizeGammaEvent(event))
      .filter((market): market is MarketSnapshot => market !== null),
    (market) => market.eventSlug ?? market.slug
  );
  const kalshiMarkets = dedupeBy(
    normalizeKalshiEvents({ events: kalshiEvents }),
    (market) => market.eventTicker
  );

  return {
    updatedAt:
      typeof payload.updatedAt === "string" ? payload.updatedAt : null,
    polymarketMarkets,
    kalshiMarkets,
    counts: {
      polymarket: polymarketMarkets.length,
      kalshi: kalshiMarkets.length
    }
  };
}

export async function fetchVenueCatalog(): Promise<VenueCatalog> {
  const path = "/api/catalog/markets";
  const url = withApiBase(path);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20_000);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`Venue catalog request failed: ${response.status}`);
    }
    const catalog = normalizeVenueCatalog(await response.json());
    if (!catalog) {
      throw new Error("Venue catalog response was malformed");
    }
    return catalog;
  } finally {
    window.clearTimeout(timeout);
  }
}
