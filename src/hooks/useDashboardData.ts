"use client";

import { calculateCorrelation } from "@/analytics/correlation";
import { calculateEventImpact } from "@/analytics/eventImpact";
import { calculateLeadLag } from "@/analytics/leadLag";
import { calculateLiquidity } from "@/analytics/liquidity";
import { calculateMomentum } from "@/analytics/momentum";
import { calculateTradePressure } from "@/analytics/tradePressure";
import { calculateVolatility } from "@/analytics/volatility";
import { useMarketData } from "@/hooks/useMarketData";
import { useOrderbook } from "@/hooks/useOrderbook";
import { usePollingData } from "@/hooks/usePollingData";
import { useTimelineData } from "@/hooks/useTimelineData";
import { useEventStore } from "@/stores/eventStore";
import { useMarketStore } from "@/stores/marketStore";

export function useDashboardData() {
  const { featuredMarketQuery, historicalSeriesQuery, featuredMarket } = useMarketData();
  const pollingQuery = usePollingData(featuredMarket);
  const timelineQuery = useTimelineData(featuredMarket);
  const { orderbook, snapshotQuery } = useOrderbook(featuredMarket?.tokenId, {
    conditionId: featuredMarket?.conditionId
  });

  const marketFromStore = useMarketStore((state) => state.featuredMarket);
  const marketSeries = useMarketStore((state) => state.series);
  const events = useEventStore((state) => state.events);

  const market = featuredMarket ?? marketFromStore;
  const isLoading =
    featuredMarketQuery.isLoading ||
    historicalSeriesQuery.isLoading ||
    pollingQuery.isLoading ||
    timelineQuery.isLoading ||
    snapshotQuery.isLoading ||
    !market ||
    !orderbook ||
    !pollingQuery.data;

  const analytics =
    !market || !orderbook || !pollingQuery.data
      ? null
      : {
          leadLag: calculateLeadLag(marketSeries, pollingQuery.data),
          volatility: calculateVolatility(marketSeries),
          momentum: calculateMomentum(marketSeries),
          liquidity: calculateLiquidity(orderbook),
          correlation: calculateCorrelation(marketSeries, pollingQuery.data),
          tradePressure: calculateTradePressure(orderbook.trades),
          eventImpact: calculateEventImpact(events)
        };

  return {
    isLoading,
    market,
    marketSeries,
    pollSeries: pollingQuery.data ?? [],
    events,
    orderbook,
    analytics,
    queries: {
      featuredMarketQuery,
      historicalSeriesQuery,
      pollingQuery,
      timelineQuery,
      snapshotQuery
    }
  };
}
