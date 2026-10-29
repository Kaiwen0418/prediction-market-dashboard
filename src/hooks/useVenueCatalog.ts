"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchVenueCatalog } from "@/services/catalog/api";

export function useVenueCatalog() {
  return useQuery({
    queryKey: ["venue-market-catalog"],
    queryFn: fetchVenueCatalog,
    staleTime: 5 * 60_000,
    gcTime: 60 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
    retry: false
  });
}
