"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchRegionSignals } from "@/services/polymarket/rest";

export function useRegionSignals(countryCode: string, activeSlug?: string | null) {
  return useQuery({
    queryKey: ["region-signals", countryCode, activeSlug ?? "none"],
    queryFn: () => fetchRegionSignals(countryCode, activeSlug ?? undefined),
    refetchInterval: 15_000
  });
}
