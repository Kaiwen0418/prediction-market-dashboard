"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchKalshiEvents } from "@/services/kalshi/rest";

export function useKalshiMarkets(eventTickers: string[], enabled = true) {
  const tickers = [...eventTickers].sort();

  return useQuery({
    queryKey: ["kalshi-events", tickers],
    queryFn: () => fetchKalshiEvents(tickers),
    enabled: enabled && tickers.length > 0,
    refetchInterval: 15_000,
    refetchIntervalInBackground: true
  });
}
