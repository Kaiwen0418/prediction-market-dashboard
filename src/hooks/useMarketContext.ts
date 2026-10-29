"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchMarketContextLive } from "@/services/polymarket/rest";

export function useMarketContext(slug?: string, enabled = true) {
  return useQuery({
    queryKey: ["market-context", slug ?? "default"],
    queryFn: () => fetchMarketContextLive(slug),
    enabled,
    refetchInterval: 30_000,
    staleTime: 60_000,
    gcTime: 15 * 60_000
  });
}
