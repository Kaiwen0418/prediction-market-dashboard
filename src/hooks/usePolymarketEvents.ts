"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPolymarketEventsBySlugs } from "@/services/polymarket/rest";

export function usePolymarketEvents(slugs: string[], enabled = true) {
  const normalizedSlugs = [...new Set(slugs)].sort();

  return useQuery({
    queryKey: ["polymarket-events", normalizedSlugs],
    queryFn: () => fetchPolymarketEventsBySlugs(normalizedSlugs),
    enabled: enabled && normalizedSlugs.length > 0,
    staleTime: 5 * 60_000,
    gcTime: 60 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false
  });
}
