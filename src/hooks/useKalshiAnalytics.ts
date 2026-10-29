"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchKalshiAnalytics } from "@/services/kalshi/rest";
import type { VenueMarketSummary } from "@/types/market";

export function useKalshiAnalytics(
  market?: VenueMarketSummary | null
) {
  return useQuery({
    queryKey: [
      "kalshi-analytics",
      market?.marketTicker ?? "none",
      market?.seriesTicker ?? "none"
    ],
    queryFn: () => (market ? fetchKalshiAnalytics(market) : null),
    enabled: Boolean(market),
    staleTime: 15_000,
    gcTime: 15 * 60_000,
    refetchInterval: market?.status === "open" ? 30_000 : false,
    placeholderData: (previous) =>
      previous?.market.marketId === market?.marketTicker
        ? previous
        : undefined
  });
}
