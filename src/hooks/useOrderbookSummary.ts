"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchOrderbookSummaryLive } from "@/services/polymarket/rest";

export function useOrderbookSummary(tokenId?: string, conditionId?: string) {
  return useQuery({
    queryKey: ["orderbook-summary", tokenId, conditionId],
    queryFn: () => (tokenId ? fetchOrderbookSummaryLive(tokenId, conditionId) : Promise.resolve(null)),
    enabled: Boolean(tokenId),
    refetchInterval: tokenId ? 30_000 : false
  });
}
