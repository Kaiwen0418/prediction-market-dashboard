"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { getFeaturedMarket, getFeaturedMarketStrict, getHistoricalMarketSeries, getMarketBySlug, getMarketBySlugStrict } from "@/services/polymarket/api";
import type { MarketSnapshot } from "@/types/market";
import { useMarketStore } from "@/stores/marketStore";

type UseMarketDataOptions = {
  strictFeaturedMarket?: boolean;
  slug?: string;
  initialFeaturedMarket?: MarketSnapshot | null;
};

export function useMarketData(options: UseMarketDataOptions = {}) {
  const { strictFeaturedMarket = false, slug, initialFeaturedMarket = null } = options;
  const setFeaturedMarket = useMarketStore((state) => state.setFeaturedMarket);
  const setSeries = useMarketStore((state) => state.setSeries);

  const featuredMarketQuery = useQuery({
    queryKey: ["featured-market", slug ?? "default", strictFeaturedMarket ? "strict" : "fallback"],
    queryFn: () => {
      if (slug) {
        return strictFeaturedMarket ? getMarketBySlugStrict(slug) : getMarketBySlug(slug);
      }
      return strictFeaturedMarket ? getFeaturedMarketStrict() : getFeaturedMarket();
    },
    initialData: initialFeaturedMarket ?? undefined,
    placeholderData: (previous) => previous,
    staleTime: 5 * 60_000,
    gcTime: 60 * 60_000,
    retry: 2
  });

  const historicalSeriesQuery = useQuery({
    queryKey: ["historical-market-series", featuredMarketQuery.data?.tokenId ?? initialFeaturedMarket?.tokenId],
    queryFn: () => getHistoricalMarketSeries(featuredMarketQuery.data?.tokenId ?? initialFeaturedMarket?.tokenId),
    enabled: Boolean(featuredMarketQuery.data ?? initialFeaturedMarket),
    placeholderData: (previous) => previous
  });

  useEffect(() => {
    if (featuredMarketQuery.data) {
      setFeaturedMarket(featuredMarketQuery.data);
    }
  }, [featuredMarketQuery.data, setFeaturedMarket]);

  useEffect(() => {
    if (historicalSeriesQuery.data) {
      setSeries(historicalSeriesQuery.data);
    }
  }, [historicalSeriesQuery.data, setSeries]);

  return {
    featuredMarket: featuredMarketQuery.data ?? initialFeaturedMarket,
    marketSeries: historicalSeriesQuery.isPlaceholderData
      ? []
      : historicalSeriesQuery.data ?? [],
    featuredMarketQuery,
    historicalSeriesQuery
  };
}
