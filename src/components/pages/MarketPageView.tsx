"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Share2, Star } from "lucide-react";
import { PolymarketHistoryChart } from "@/components/charts/PolymarketHistoryChart";
import { ErrorState } from "@/components/layout/ErrorState";
import { LoadingState } from "@/components/layout/LoadingState";
import { OperationalNotice } from "@/components/layout/OperationalNotice";
import { OrderFlowEvidence } from "@/components/orderbook/OrderFlowEvidence";
import {
  parseActivityFeedFilters,
  serializeActivityFeedFilters
} from "@/components/maps/activityFeedFilters";
import type {
  ActivityCountryScope,
  ActivitySignalFilter,
  ActivityTimeWindow,
  ActivityVolumeThreshold,
  MapViewMode
} from "@/components/maps/activityFeedFilters";
import {
  COUNTRY_MARKET_MAPS,
  REGION_MARKETS,
  getConfiguredPolymarketSlugs,
  getRegionMarketPairLabel,
  getRegionPolymarketSlugs,
  getSpotlightState,
  kalshiMarketMatchesRegion,
  marketMatchesRegion
} from "@/components/maps/spotlightStates";
import { UsMarketMap } from "@/components/maps/UsMarketMap";
import { TopNav } from "@/components/navigation/TopNav";
import { MarketWorkspaceNav } from "@/components/navigation/MarketWorkspaceNav";
import { useMarketContext } from "@/hooks/useMarketContext";
import { useMarketData } from "@/hooks/useMarketData";
import { useLiveReplay } from "@/hooks/useLiveReplay";
import { useLiveMarketStream } from "@/hooks/useLiveMarketStream";
import { useKalshiAnalytics } from "@/hooks/useKalshiAnalytics";
import { useKalshiMarkets } from "@/hooks/useKalshiMarkets";
import { useRecentMarketTrades } from "@/hooks/useRecentMarketTrades";
import { useOrderbook } from "@/hooks/useOrderbook";
import { useOrderbookSummary } from "@/hooks/useOrderbookSummary";
import { usePolymarketEvents } from "@/hooks/usePolymarketEvents";
import { useRegionSignals } from "@/hooks/useRegionSignals";
import { useTimelineData } from "@/hooks/useTimelineData";
import { useSourceDiagnostics } from "@/hooks/useSourceDiagnostics";
import { useVenueCatalog } from "@/hooks/useVenueCatalog";
import { formatTimestamp } from "@/utils/time";
import {
  formatMarketProbability,
  getMarketDisplayTitle,
  getMarketOutcomeLabel
} from "@/utils/marketDisplay";
import type { MarketSnapshot, OrderbookState } from "@/types/market";

type MarketPageViewProps = {
  embedded?: boolean;
  strictLive?: boolean;
  workspace?: boolean;
};

const KALSHI_EVENT_TICKERS = REGION_MARKETS.flatMap((region) =>
  region.kalshiEventTicker ? [region.kalshiEventTicker] : []
);
const POLYMARKET_EVENT_SLUGS = getConfiguredPolymarketSlugs();

function marketMatchesSlug(market: MarketSnapshot, slug: string) {
  return market.slug === slug || market.eventSlug === slug;
}

function createPendingOrderbook(market: MarketSnapshot): OrderbookState {
  return {
    marketId: market.marketId,
    tokenId: market.tokenId,
    bids: [],
    asks: [],
    trades: [],
    spread: 0,
    midPrice: market.probability,
    source: "live",
    updatedAt: market.updatedAt
  };
}

export function MarketPageView({
  embedded = false,
  strictLive = true,
  workspace = false
}: MarketPageViewProps) {
  const [selectedCountryCode, setSelectedCountryCode] = useState("US");
  const [selectedStateCode, setSelectedStateCode] = useState<string | null>("CA");
  const [selectedMarketSlug, setSelectedMarketSlug] = useState<string | null>(
    null
  );
  const [mapView, setMapView] = useState<MapViewMode>("country");
  const [countryScope, setCountryScope] = useState<ActivityCountryScope>("global");
  const [evidenceView, setEvidenceView] = useState<"flow" | "history">("flow");
  const [activityThreshold, setActivityThreshold] = useState(50);
  const [activityVolumeThreshold, setActivityVolumeThreshold] =
    useState<ActivityVolumeThreshold>(1_000);
  const [activitySignalKind, setActivitySignalKind] = useState<ActivitySignalFilter>("all");
  const [activityMaxAgeHours, setActivityMaxAgeHours] = useState<ActivityTimeWindow>(0);
  const [filtersHydrated, setFiltersHydrated] = useState(false);
  const [autoTourEnabled, setAutoTourEnabled] = useState(false);
  const [marketSaved, setMarketSaved] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const parsed = parseActivityFeedFilters(params);
    const country =
      COUNTRY_MARKET_MAPS.find((candidate) => candidate.code === parsed.countryCode) ??
      COUNTRY_MARKET_MAPS[0];
    const region = getSpotlightState(parsed.regionCode);

    setSelectedCountryCode(country.code);
    setMapView(parsed.mapView);
    setCountryScope(parsed.countryScope);
    setSelectedStateCode(
      region?.countryCode === country.code ? region.code : country.defaultRegionCode
    );
    setActivityThreshold(parsed.minimumScore);
    setActivityVolumeThreshold(parsed.minimumVolume);
    setActivitySignalKind(parsed.signalKind);
    setActivityMaxAgeHours(parsed.maxAgeHours);
    setAutoTourEnabled(
      !["country", "region", "view"].some((key) => params.has(key))
    );
    setFiltersHydrated(true);
  }, []);

  useEffect(() => {
    if (!filtersHydrated) {
      return;
    }

    const params = serializeActivityFeedFilters(
      {
        mapView,
        countryScope,
        countryCode: selectedCountryCode,
        regionCode: selectedStateCode,
        minimumScore: activityThreshold,
        minimumVolume: activityVolumeThreshold,
        signalKind: activitySignalKind,
        maxAgeHours: activityMaxAgeHours
      },
      window.location.search
    );
    const query = params.toString();
    const nextUrl = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", nextUrl);
  }, [
    activityMaxAgeHours,
    activitySignalKind,
    activityThreshold,
    activityVolumeThreshold,
    countryScope,
    filtersHydrated,
    mapView,
    selectedCountryCode,
    selectedStateCode
  ]);

  const selectedState = getSpotlightState(selectedStateCode);
  const venueCatalogQuery = useVenueCatalog();
  const useCuratedVenueFallback = venueCatalogQuery.isError;
  const polymarketEventsQuery = usePolymarketEvents(
    POLYMARKET_EVENT_SLUGS,
    useCuratedVenueFallback
  );
  const kalshiMarketsQuery = useKalshiMarkets(
    KALSHI_EVENT_TICKERS,
    useCuratedVenueFallback
  );
  const polymarketMarkets =
    venueCatalogQuery.data?.polymarketMarkets ??
    polymarketEventsQuery.data ??
    [];
  const kalshiMarkets =
    venueCatalogQuery.data?.kalshiMarkets ?? kalshiMarketsQuery.data ?? [];
  const selectedRegionSlugs = getRegionPolymarketSlugs(selectedState);
  const selectedDiscoveredMarket = selectedMarketSlug
    ? polymarketMarkets.find(
        (candidate) =>
          marketMatchesSlug(candidate, selectedMarketSlug) &&
          marketMatchesRegion(selectedState, candidate)
      )
    : null;
  const selectedSlug =
    selectedMarketSlug &&
    (selectedRegionSlugs.includes(selectedMarketSlug) ||
      selectedDiscoveredMarket)
      ? selectedMarketSlug
      : selectedState?.liveMarketSlug;
  const selectedKalshiMarkets = kalshiMarkets.filter((market) =>
    kalshiMarketMatchesRegion(selectedState, market)
  );
  const selectedKalshiMarket = selectedKalshiMarkets[0] ?? null;
  const useKalshiPair = Boolean(
    selectedKalshiMarket && selectedState?.kalshiEventTicker && !selectedSlug
  );
  const kalshiAnalyticsQuery = useKalshiAnalytics(
    useKalshiPair ? selectedKalshiMarket : null
  );
  const kalshiAnalytics = kalshiAnalyticsQuery.data ?? null;
  const selectedPolymarketSummary = useMemo(
    () =>
      selectedSlug
        ? polymarketMarkets.find((candidate) =>
            marketMatchesSlug(candidate, selectedSlug)
          ) ?? null
        : null,
    [polymarketMarkets, selectedSlug]
  );
  const marketContextQuery = useMarketContext(
    selectedSlug,
    Boolean(selectedSlug)
  );
  const contextMarket = marketContextQuery.data?.featuredMarket ?? null;
  const {
    featuredMarketQuery,
    featuredMarket: polymarketMarket,
    historicalSeriesQuery,
    marketSeries: polymarketSeries
  } = useMarketData({
    slug: selectedSlug,
    strictFeaturedMarket: strictLive && Boolean(selectedSlug),
    initialFeaturedMarket: contextMarket ?? selectedPolymarketSummary
  });
  const { orderbook: polymarketOrderbook, snapshotQuery } = useOrderbook(polymarketMarket?.tokenId, {
    conditionId: polymarketMarket?.conditionId,
    strictSnapshot: strictLive && Boolean(selectedSlug),
    allowMockStreamFallback: !strictLive,
    enableRealtime: strictLive && Boolean(selectedSlug)
  });
  const liveStream = useLiveMarketStream(selectedSlug ?? polymarketMarket?.slug);
  const recentMarketTradesQuery = useRecentMarketTrades();
  const liveReplayQuery = useLiveReplay(selectedSlug ?? polymarketMarket?.slug, 48);
  const regionSignalsQuery = useRegionSignals(selectedCountryCode, selectedSlug ?? polymarketMarket?.slug);
  const activeRegionSignal = selectedState
    ? regionSignalsQuery.data?.signals.find(
        (signal) =>
          signal.countryCode === selectedState.countryCode &&
          signal.regionCode === selectedState.code
      ) ?? selectedState.signal
    : null;
  const orderbookSummaryQuery = useOrderbookSummary(polymarketMarket?.tokenId, polymarketMarket?.conditionId);
  const sources = useSourceDiagnostics();
  const liveStreamMatchesMarket =
    Boolean(liveStream.snapshot?.orderbookSummary) &&
    Boolean(polymarketMarket?.slug) &&
    liveStream.snapshot?.status.marketSlug === (selectedSlug ?? polymarketMarket?.slug);
  const streamedOrderbookSummary = liveStreamMatchesMarket
    ? liveStream.snapshot?.orderbookSummary
    : null;
  const restOrderbookSummary =
    marketContextQuery.data?.orderbookSummary ?? orderbookSummaryQuery.data;
  const polymarketOrderbookSummary = streamedOrderbookSummary
    ? {
        ...streamedOrderbookSummary,
        whaleActivity:
          restOrderbookSummary?.whaleActivity ??
          streamedOrderbookSummary.whaleActivity
      }
    : restOrderbookSummary;
  const polymarketMicrostructure = liveStreamMatchesMarket ? liveStream.snapshot?.microstructure ?? null : null;
  const polymarketReplay =
    liveReplayQuery.data && liveReplayQuery.data.status.marketSlug === (selectedSlug ?? polymarketMarket?.slug)
      ? liveReplayQuery.data
      : null;
  const polymarketOrderbookMatchesMarket = Boolean(
    polymarketMarket &&
      polymarketOrderbook &&
      (polymarketMarket.tokenId
        ? polymarketOrderbook.tokenId === polymarketMarket.tokenId
        : polymarketOrderbook.marketId === polymarketMarket.marketId)
  );
  const currentPolymarketOrderbook = polymarketOrderbookMatchesMarket
    ? polymarketOrderbook
    : polymarketMarket
      ? createPendingOrderbook(polymarketMarket)
      : null;
  const market = useKalshiPair
    ? kalshiAnalytics?.market ?? polymarketMarket
    : polymarketMarket;
  const orderbook = useKalshiPair
    ? kalshiAnalytics?.orderbook ?? currentPolymarketOrderbook
    : currentPolymarketOrderbook;
  const resolvedOrderbookSummary = useKalshiPair
    ? kalshiAnalytics?.orderbookSummary ?? null
    : polymarketOrderbookSummary;
  const liveMicrostructure = useKalshiPair ? null : polymarketMicrostructure;
  const liveReplay = useKalshiPair
    ? kalshiAnalytics?.replay ?? null
    : polymarketReplay;
  const marketSeries = useKalshiPair
    ? kalshiAnalytics?.marketSeries ?? []
    : polymarketSeries;
  const historyMeta = useKalshiPair
    ? {
        points: marketSeries.length,
        market: selectedKalshiMarket?.marketTicker ?? ""
      }
    : marketContextQuery.data?.priceHistoryMeta;
  const marketMatchesSelectedRegion = useKalshiPair
    ? Boolean(kalshiAnalytics)
    : marketMatchesRegion(selectedState, market);
  const timelineQuery = useTimelineData(
    market,
    useKalshiPair ? [] : marketContextQuery.data?.timelineEvents
  );
  const deferredEvents = useDeferredValue(
    useKalshiPair ? [] : timelineQuery.data ?? []
  );
  const effectiveEvidenceView =
    market?.status === "closed" ? "history" : evidenceView;
  const displayMarketTitle =
    mapView === "world"
      ? "Global political market activity"
      : useKalshiPair && marketMatchesSelectedRegion
        ? market?.title
      : selectedState && !marketMatchesSelectedRegion
      ? getRegionMarketPairLabel(selectedState)
      : getMarketDisplayTitle(market);
  const displayOutcomeMarket =
    mapView !== "country"
      ? null
      : marketMatchesSelectedRegion
        ? market
        : selectedKalshiMarkets[0] ?? null;
  const displayOutcomeLabel = getMarketOutcomeLabel(displayOutcomeMarket);
  const displayOutcomeProbability = formatMarketProbability(
    displayOutcomeMarket?.probability
  );
  const displayUpdatedAt = marketMatchesSelectedRegion
    ? orderbook?.updatedAt
    : selectedKalshiMarkets[0]?.updatedAt;
  const marketDetailsUpdating =
    !useKalshiPair &&
    Boolean(selectedSlug) &&
    (marketContextQuery.isFetching ||
      featuredMarketQuery.isFetching ||
      snapshotQuery.isFetching) &&
    (!marketMatchesSelectedRegion || !polymarketOrderbookMatchesMarket);
  const primarySource = sources["market-context"] ?? sources["featured-market"];
  const signalSource = sources["region-signals"];
  const operationalNotice =
    useKalshiPair && kalshiAnalyticsQuery.isLoading
      ? {
          tone: "info" as const,
          title: "Loading Kalshi market analytics",
          detail: "Order-book depth, trades, and price history are updating."
        }
      : useKalshiPair && !kalshiAnalytics
        ? {
            tone: "warning" as const,
            title: "Kalshi analytics are temporarily unavailable",
            detail:
              "Current probability and volume remain available. Detailed market evidence will retry automatically."
          }
        : useKalshiPair
          ? null
        : marketDetailsUpdating
          ? {
              tone: "info" as const,
              title: "Updating market details",
              detail:
                "Current pricing and map coverage are available while order-book depth refreshes."
            }
        : !marketMatchesSelectedRegion
      ? {
          tone: "info" as const,
          title: "Limited market coverage",
          detail:
            "Current regional signals remain available while venue-specific market depth is unavailable."
        }
      : market?.status === "closed"
        ? {
            tone: "info" as const,
            title: "This market is closed",
            detail: "Prices, volume, and order-book statistics are shown as historical information."
          }
        : market?.status === "inactive"
          ? {
              tone: "warning" as const,
              title: "Trading is not currently available",
              detail: "The venue is not accepting orders for this contract."
            }
      : primarySource?.state === "failed" || signalSource?.state === "failed"
        ? {
            tone: "error" as const,
            title: "Market data is temporarily unavailable",
            detail: "Some prices or signals may be missing. Please try again shortly."
          }
        : regionSignalsQuery.data?.freshness === "stale"
          ? {
              tone: "warning" as const,
              title: "Market data may be delayed",
              detail: orderbook
                ? `Last updated ${formatTimestamp(orderbook.updatedAt, "MMM d, HH:mm:ss")}.`
                : "The latest update time is unavailable."
            }
          : primarySource?.state === "fallback" || signalSource?.state === "fallback"
            ? {
                tone: "warning" as const,
                title: "Showing the latest available market information",
                detail: "Recent updates are temporarily delayed."
              }
            : primarySource?.state === "pending" || signalSource?.state === "pending"
              ? {
                  tone: "info" as const,
                  title: "Updating market information",
                  detail: "New prices and signals will appear automatically."
                }
              : null;
  const isLoading = useKalshiPair
    ? false
    : !market ||
      !orderbook;
  const hasLoadError =
    !useKalshiPair &&
    !market &&
    (Boolean(marketContextQuery.error) ||
      Boolean(featuredMarketQuery.error) ||
      Boolean(snapshotQuery.error));

  if (isLoading) {
    return <LoadingState label="Loading market data..." />;
  }

  if (hasLoadError || !market || !orderbook) {
    return (
      <ErrorState
        detail="We could not load this market. Please try again shortly."
      />
    );
  }

  const shareMarket = async () => {
    const shareData = {
      title: displayMarketTitle,
      url: window.location.href
    };

    if (navigator.share) {
      await navigator.share(shareData);
      return;
    }

    await navigator.clipboard.writeText(window.location.href);
  };

  const content = (
    <>
      <section
        id="market-map"
        className={workspace ? "market-workspace-stage" : undefined}
      >
        <header className={workspace ? "market-workspace-header" : undefined}>
          <div className="market-workspace-heading">
            <div className="flex max-w-4xl flex-wrap items-center gap-x-3 gap-y-2">
              <h2 className="text-xl font-semibold leading-tight text-slate-900 sm:text-2xl">
                {displayMarketTitle}
              </h2>
              {displayOutcomeLabel && displayOutcomeProbability ? (
                <span
                  className="market-workspace-outcome inline-flex max-w-full items-center gap-2 border border-slate-300 bg-white px-2.5 py-1 font-sans text-xs text-slate-700"
                  aria-label={`${displayOutcomeLabel} current probability ${displayOutcomeProbability}`}
                >
                  <span className="max-w-48 truncate font-medium">
                    {displayOutcomeLabel}
                  </span>
                  <strong className="tabular-nums text-slate-950">
                    {displayOutcomeProbability}
                  </strong>
                </span>
              ) : null}
              {mapView === "country" &&
              marketMatchesSelectedRegion &&
              market.status === "closed" ? (
                <span className="border border-slate-400 px-2 py-1 font-sans text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
                  Closed market
                </span>
              ) : null}
            </div>
            {mapView === "country" ? (
              <>
                {displayUpdatedAt ? (
                  <p className="market-workspace-update mt-3 font-sans text-xs text-slate-500">
                    <span className="market-workspace-live">
                      <span aria-hidden="true" />
                      {market.status === "open" ? "Live" : "Closed"}
                    </span>
                    <span>
                      {marketMatchesSelectedRegion ? "Updated" : "Checked"}{" "}
                      {formatTimestamp(displayUpdatedAt, "MMM d, HH:mm:ss")}
                    </span>
                  </p>
                ) : null}
                {operationalNotice ? (
                  <div className="market-workspace-notice mt-4 max-w-2xl">
                    <OperationalNotice {...operationalNotice} />
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
          {workspace ? (
            <div className="market-workspace-actions">
              <button
                type="button"
                aria-label={marketSaved ? "Remove market from saved markets" : "Save market"}
                title={marketSaved ? "Remove from saved markets" : "Save market"}
                aria-pressed={marketSaved}
                onClick={() => setMarketSaved((saved) => !saved)}
                data-active={marketSaved ? "true" : "false"}
              >
                <Star aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label="Share market"
                title="Share market"
                onClick={() => void shareMarket()}
              >
                <Share2 aria-hidden="true" />
              </button>
            </div>
          ) : null}
        </header>
        <div className={workspace ? "market-workspace-map" : "mt-7"}>
          <UsMarketMap
            workspaceLayout={workspace}
            market={market}
            marketSeries={marketSeries}
            liveTrades={recentMarketTradesQuery.data}
            polymarketMarkets={polymarketMarkets}
            kalshiMarkets={kalshiMarkets}
            regionSignals={regionSignalsQuery.data?.signals}
            activityThreshold={activityThreshold}
            activityVolumeThreshold={activityVolumeThreshold}
            autoTourEnabled={autoTourEnabled}
            countryScope={countryScope}
            activitySignalKind={activitySignalKind}
            activityMaxAgeHours={activityMaxAgeHours}
            mapView={mapView}
            selectedCountryCode={selectedCountryCode}
            selectedCode={selectedStateCode}
            onSelectCountryCode={setSelectedCountryCode}
            onSelectCode={(code) => {
              setSelectedStateCode(code);
              setSelectedMarketSlug(getSpotlightState(code)?.liveMarketSlug ?? null);
            }}
            onSelectMarketSlug={setSelectedMarketSlug}
            onActivityThresholdChange={setActivityThreshold}
            onActivityVolumeThresholdChange={setActivityVolumeThreshold}
            onAutoTourEnabledChange={setAutoTourEnabled}
            onCountryScopeChange={setCountryScope}
            onActivitySignalKindChange={setActivitySignalKind}
            onActivityMaxAgeHoursChange={setActivityMaxAgeHours}
            onMapViewChange={setMapView}
          />
        </div>
      </section>

      {mapView === "world" ? null : marketMatchesSelectedRegion ? (
      <section
        id="market-evidence"
        className={workspace ? "market-workspace-evidence" : "pt-2"}
      >
        <div className="mb-7 flex border-b border-[var(--demo-card-divider)] font-sans" role="tablist" aria-label="Market evidence">
          {market.status === "closed" ? null : (
            <button
              type="button"
              role="tab"
              aria-selected={effectiveEvidenceView === "flow"}
              onClick={() => setEvidenceView("flow")}
              className={`border-b-2 px-4 py-3 text-sm font-semibold ${
                effectiveEvidenceView === "flow"
                  ? "border-slate-900 text-slate-900"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
            >
              Order flow
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={effectiveEvidenceView === "history"}
            onClick={() => setEvidenceView("history")}
            className={`border-b-2 px-4 py-3 text-sm font-semibold ${
              effectiveEvidenceView === "history"
                ? "border-slate-900 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-900"
            }`}
          >
            Price history
          </button>
        </div>

        {effectiveEvidenceView === "flow" ? (
          <div role="tabpanel">
            <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
              <div>
                <p className="metric-label">Order Flow</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900 sm:text-2xl">
                  Current liquidity and trade evidence
                </h2>
              </div>
              <p className="text-sm leading-6 text-slate-500 md:max-w-[320px] md:text-right">
                Snapshot metrics and large-print detection update with the selected market.
              </p>
            </div>
            <div className="mt-6">
              <OrderFlowEvidence
                liveMicrostructure={liveMicrostructure}
                orderbook={orderbook}
                orderbookSummary={resolvedOrderbookSummary}
                signal={activeRegionSignal}
              />
            </div>
          </div>
        ) : (
          <div role="tabpanel">
            <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
              <div>
                <p className="metric-label">Price History</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-900 sm:text-2xl">
                  {market.status === "closed"
                    ? "Final contract probability over time"
                    : "Selected market probability over time"}
                </h2>
              </div>
              <p className="text-sm leading-6 text-slate-500 md:max-w-[280px] md:text-right">
                {(useKalshiPair
                  ? kalshiAnalyticsQuery.isLoading
                  : historicalSeriesQuery.isLoading)
                  ? "Loading history..."
                  : `${historyMeta?.points ?? marketSeries.length} historical observations`}
              </p>
            </div>
            <div className="mt-6">
              <PolymarketHistoryChart
                events={deferredEvents}
                series={marketSeries}
                venueName={useKalshiPair ? "Kalshi" : "Polymarket"}
              />
            </div>
          </div>
        )}
      </section>
      ) : (
        <section className="py-8">
          <p className="metric-label">Market Evidence</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-900">Coverage unavailable for this pair</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
            Regional signals remain visible, but order-book replay and price history are unavailable because this
            region does not have matching market coverage.
          </p>
        </section>
      )}
    </>
  );

  if (workspace) {
    return (
      <main className="market-workspace">
        <MarketWorkspaceNav />
        <div className="market-workspace-content">{content}</div>
      </main>
    );
  }

  if (embedded) {
    return <div className="flex flex-col gap-8">{content}</div>;
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-8 px-4 py-6 md:px-6 lg:px-8">
      <TopNav />
      {content}
    </main>
  );
}
