import { withApiBase } from "@/services/api/base";
import type {
  KalshiMarketAnalytics,
  VenueMarketSummary
} from "@/types/market";
import { kalshiConfig } from "./config";
import {
  normalizeKalshiAnalytics,
  normalizeKalshiEvents
} from "./normalizers";

export async function fetchKalshiEvents(
  eventTickers: string[]
): Promise<VenueMarketSummary[]> {
  const tickers = [...new Set(eventTickers)].filter((ticker) =>
    /^[A-Z0-9-]{2,80}$/.test(ticker)
  );
  if (!tickers.length) return [];

  const batches = Array.from(
    { length: Math.ceil(tickers.length / 20) },
    (_, index) => tickers.slice(index * 20, index * 20 + 20)
  );

  const results = await Promise.all(
    batches.map(async (batch) => {
      const path = `/api/kalshi/events?tickers=${encodeURIComponent(
        batch.join(",")
      )}`;
      const urls = [withApiBase(path), path].filter(
        (url, index, all) => all.indexOf(url) === index
      );

      for (const url of urls) {
        const controller = new AbortController();
        const timeout = setTimeout(
          () => controller.abort(),
          kalshiConfig.requestTimeoutMs
        );

        try {
          const response = await fetch(url, {
            headers: { Accept: "application/json" },
            signal: controller.signal
          });
          if (!response.ok) continue;

          const markets = normalizeKalshiEvents(await response.json());
          if (markets.length) return markets;
        } catch {
          continue;
        } finally {
          clearTimeout(timeout);
        }
      }

      return [];
    })
  );

  return results.flat();
}

export async function fetchKalshiAnalytics(
  market: VenueMarketSummary
): Promise<KalshiMarketAnalytics | null> {
  if (
    !/^[A-Z0-9-]{2,100}$/.test(market.marketTicker) ||
    !/^[A-Z0-9-]{2,100}$/.test(market.seriesTicker)
  ) {
    return null;
  }

  const path = `/api/kalshi/analytics?ticker=${encodeURIComponent(
    market.marketTicker
  )}&seriesTicker=${encodeURIComponent(market.seriesTicker)}`;
  const urls = [withApiBase(path), path].filter(
    (url, index, all) => all.indexOf(url) === index
  );

  for (const url of urls) {
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      kalshiConfig.requestTimeoutMs
    );

    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: controller.signal
      });
      if (!response.ok) continue;
      const analytics = normalizeKalshiAnalytics(
        await response.json(),
        market
      );
      if (analytics) return analytics;
    } catch {
      continue;
    } finally {
      clearTimeout(timeout);
    }
  }

  return null;
}
