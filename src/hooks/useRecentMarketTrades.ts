"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchRecentMarketTrades } from "@/services/polymarket/rest";

export function useRecentMarketTrades(limit = 100) {
  return useQuery({
    queryKey: ["recent-market-trades", limit],
    queryFn: () => fetchRecentMarketTrades(limit),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true
  });
}
