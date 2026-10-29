"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Maximize2, Pause, Play, X } from "lucide-react";
import { ComposableMap, Geographies, Geography, Marker, ZoomableGroup } from "react-simple-maps";
import usAtlas from "us-atlas/states-10m.json";
import franceRegions from "@/components/maps/data/france-regions.json";
import germanyStates from "@/components/maps/data/germany-states.json";
import ukRegions from "@/components/maps/data/uk-regions.json";
import ukraineOblasts from "@/components/maps/data/ukraine-oblasts.json";
import worldCountries from "@/components/maps/data/world-countries-110m.json";
import { normalizeD3PolygonWinding } from "@/components/maps/geoJson";
import { summarizeMarketMovement } from "@/analytics/marketMovement";
import { AbnormalActivityFeed } from "@/components/maps/AbnormalActivityFeed";
import type {
  ActivityCountryScope,
  ActivitySignalFilter,
  ActivityTimeWindow,
  ActivityVolumeThreshold,
  MapViewMode
} from "@/components/maps/activityFeedFilters";
import {
  getMarketSignalColor,
  getMarketSignalSeverity,
  SIGNAL_LEGEND
} from "@/components/maps/marketSignals";
import { getAutoTourRegions } from "@/components/maps/mapTour";
import {
  MAP_CAMERA_SETTLE_MS,
  MAP_CAMERA_TRANSITION_MS,
  getMapTransitionPosition,
  type MapCameraPosition
} from "@/components/maps/mapCamera";
import {
  MapLiveTradeTape,
  formatTradePopupText
} from "@/components/maps/MapLiveTradeTape";
import { matchVenueTradesToRegions } from "@/components/maps/mapTradePopups";
import {
  formatMarketVolume,
  getMarketVolumeOpacity,
  getRegionMarketVolume,
  qualifiesByVolume
} from "@/components/maps/marketVolume";
import { paginateTradingPairs } from "@/components/maps/tradingPairPagination";
import {
  COUNTRY_MARKET_MAPS,
  REGION_MARKETS,
  getCountryMarketMaps,
  getRegionMarketPairLabel,
  getRegionMarketsByCountry,
  getRegionPolymarketSlugs,
  getSpotlightState,
  inferSpotlightCodeFromMarket,
  kalshiMarketMatchesRegion,
  marketMatchesRegion
} from "@/components/maps/spotlightStates";
import type {
  CountryMarketMap,
  RegionMarket
} from "@/components/maps/spotlightStates";
import type {
  MarketSnapshot,
  MarketTradePrint,
  TimePoint,
  VenueMarketSummary
} from "@/types/market";
import type { RegionSignal } from "@/types/signals";
import { formatTimestamp } from "@/utils/time";
import { useSignalWatchlist } from "@/hooks/useSignalWatchlist";

const R3fMarketGlobe = dynamic(
  () =>
    import("@/components/maps/R3fMarketGlobe").then(
      (module) => module.R3fMarketGlobe
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center font-sans text-xs text-slate-500">
        Loading 3D market map…
      </div>
    )
  }
);

const UKRAINE_LOCALITY_LABEL_OFFSETS: Record<
  string,
  { x: number; y: number }
> = {
  HUL: { x: -10, y: 16 },
  KOS: { x: 11, y: -19 },
  MYR: { x: -11, y: 20 },
  STI: { x: 11, y: 18 },
  BIL: { x: -11, y: -13 }
};

const ukraineOblastGeography = normalizeD3PolygonWinding(ukraineOblasts);

type RegionalTradePopup = {
  region: RegionMarket;
  id: string;
  timestamp: string;
  text: string;
};

function formatCompactCurrency(value?: number) {
  if (value === undefined || !Number.isFinite(value)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}

function formatMovement(value: number | null) {
  if (value === null) {
    return "—";
  }

  return `${value > 0 ? "+" : ""}${value.toFixed(1)} pts`;
}

function movementTone(value: number | null) {
  if (value === null || value === 0) {
    return "text-slate-500";
  }
  return value > 0 ? "text-emerald-700" : "text-rose-700";
}

function formatContractDate(value: string | undefined, status: MarketSnapshot["status"]) {
  if (!value) return null;

  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;

  const dateLabel = new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC"
  }).format(date);

  return status === "closed" ? `Closed ${dateLabel}` : `Closes ${dateLabel}`;
}

type UsMarketMapProps = {
  market: MarketSnapshot;
  workspaceLayout?: boolean;
  marketSeries?: TimePoint[];
  liveTrades?: MarketTradePrint[];
  polymarketMarkets?: MarketSnapshot[];
  kalshiMarkets?: VenueMarketSummary[];
  selectedCode?: string | null;
  selectedCountryCode?: string;
  regionSignals?: RegionSignal[];
  activityThreshold?: number;
  activityVolumeThreshold?: ActivityVolumeThreshold;
  autoTourEnabled?: boolean;
  countryScope?: ActivityCountryScope;
  activitySignalKind?: ActivitySignalFilter;
  activityMaxAgeHours?: ActivityTimeWindow;
  mapView?: MapViewMode;
  onActivityThresholdChange?: (score: number) => void;
  onActivityVolumeThresholdChange?: (
    volume: ActivityVolumeThreshold
  ) => void;
  onAutoTourEnabledChange?: (enabled: boolean) => void;
  onCountryScopeChange?: (scope: ActivityCountryScope) => void;
  onActivitySignalKindChange?: (kind: ActivitySignalFilter) => void;
  onActivityMaxAgeHoursChange?: (hours: ActivityTimeWindow) => void;
  onMapViewChange?: (view: MapViewMode) => void;
  onSelectCode?: (code: string | null) => void;
  onSelectCountryCode?: (code: string) => void;
  onSelectMarketSlug?: (slug: string) => void;
};

export function UsMarketMap({
  market,
  workspaceLayout = false,
  marketSeries = [],
  liveTrades = [],
  polymarketMarkets = [],
  kalshiMarkets = [],
  selectedCode,
  selectedCountryCode = "US",
  regionSignals = [],
  activityThreshold = 50,
  activityVolumeThreshold = 1_000,
  autoTourEnabled = false,
  countryScope = "global",
  activitySignalKind = "all",
  activityMaxAgeHours = 0,
  mapView = "country",
  onActivityThresholdChange,
  onActivityVolumeThresholdChange,
  onAutoTourEnabledChange,
  onCountryScopeChange,
  onActivitySignalKindChange,
  onActivityMaxAgeHoursChange,
  onMapViewChange,
  onSelectCode,
  onSelectCountryCode,
  onSelectMarketSlug
}: UsMarketMapProps) {
  const defaultCode = useMemo(() => inferSpotlightCodeFromMarket(market), [market]);
  const availableCountries = useMemo(() => getCountryMarketMaps(), []);
  const activeCountry = COUNTRY_MARKET_MAPS.find((country) => country.code === selectedCountryCode) ?? COUNTRY_MARKET_MAPS[0];
  const allRegionMarkets = useMemo(() => REGION_MARKETS, []);
  const regionMarkets = useMemo(() => getRegionMarketsByCountry(activeCountry.code), [activeCountry.code]);
  const signalByRegion = useMemo(
    () =>
      new Map(
        regionSignals.map((signal) => [
          `${signal.countryCode}:${signal.regionCode}`,
          signal
        ])
      ),
    [regionSignals]
  );
  const getRegionSignal = (region: RegionMarket) =>
    signalByRegion.get(`${region.countryCode}:${region.code}`) ?? region.signal;
  const countrySummaries = useMemo(
    () =>
      availableCountries.map((country) => {
        const regions = getRegionMarketsByCountry(country.code);
        const topRegion = regions
          .filter(
            (region) =>
              region.marketStatus !== "closed" &&
              region.marketStatus !== "inactive"
          )
          .map((region) => ({
            region,
            signal: getRegionSignal(region)
          }))
          .sort((left, right) => right.signal.score - left.signal.score)[0];
        const regionVolumes = regions
          .map((region) =>
            getRegionMarketVolume(region, kalshiMarkets, polymarketMarkets)
          )
          .filter((volume): volume is number => volume !== null);

        return {
          country,
          regions,
          topRegion,
          volume24h: regionVolumes.length
            ? regionVolumes.reduce((sum, volume) => sum + volume, 0)
            : null
        };
      }),
    [availableCountries, kalshiMarkets, polymarketMarkets, signalByRegion]
  );
  const labeledRegions = useMemo(
    () =>
      regionMarkets
        .map((region) => ({
          region,
          signal: getRegionSignal(region),
          volume: getRegionMarketVolume(
            region,
            kalshiMarkets,
            polymarketMarkets
          )
        }))
        .filter(
          ({ region, signal, volume }) =>
            signal.score >= 70 ||
            qualifiesByVolume(region, volume, activityVolumeThreshold)
        )
        .sort((left, right) => {
          const scoreDifference = right.signal.score - left.signal.score;
          if (scoreDifference) return scoreDifference;
          return (right.volume ?? 0) - (left.volume ?? 0);
        })
        .slice(0, 6),
    [
      activityVolumeThreshold,
      kalshiMarkets,
      polymarketMarkets,
      signalByRegion,
      regionMarkets
    ]
  );
  const globeRegionData = useMemo(
    () =>
      mapView === "country"
        ? allRegionMarkets
            .map((region) => {
              const signal = getRegionSignal(region);
              const volume = getRegionMarketVolume(
                region,
                kalshiMarkets,
                polymarketMarkets
              );

              return {
                region,
                signalScore: signal.score,
                volume24h: volume
              };
            })
            .filter(
              ({ region }) =>
                region.marketStatus !== "closed" &&
                region.marketStatus !== "inactive"
            )
        : [],
    [
      kalshiMarkets,
      mapView,
      polymarketMarkets,
      allRegionMarkets,
      signalByRegion
    ]
  );
  const regionalTradePopups = useMemo<RegionalTradePopup[]>(
    () =>
      mapView === "country"
        ? matchVenueTradesToRegions(liveTrades, allRegionMarkets).map(
            ({ region, trade }) => ({
              region,
              id: trade.id,
              timestamp: trade.timestamp,
              text: formatTradePopupText(trade)
            })
          )
        : [],
    [allRegionMarkets, liveTrades, mapView]
  );
  const labeledCountries = useMemo(
    () =>
      countrySummaries
        .filter(
          (summary) =>
            summary.topRegion && summary.topRegion.signal.score >= 70
        )
        .sort(
          (left, right) =>
            (right.topRegion?.signal.score ?? 0) -
            (left.topRegion?.signal.score ?? 0)
        ),
    [countrySummaries]
  );
  const alertSignals = useMemo(
    () =>
      regionSignals.map((signal) => {
        const region = allRegionMarkets.find(
          (candidate) =>
            candidate.countryCode === signal.countryCode &&
            candidate.code === signal.regionCode
        );
        return {
          countryCode: signal.countryCode,
          regionCode: signal.regionCode,
          regionLabel: region?.label ?? signal.regionCode,
          pairLabel: region
            ? getRegionMarketPairLabel(region)
            : signal.marketSlug,
          headline: signal.headline,
          score: signal.score,
          observedAt: signal.observedAt,
          source: signal.source
        };
      }),
    [allRegionMarkets, regionSignals]
  );
  const signalWatchlist = useSignalWatchlist(alertSignals);
  const [tradingPairPage, setTradingPairPage] = useState(0);
  const [localSelectedCode, setLocalSelectedCode] = useState<string | null>(null);
  const [hoveredCode, setHoveredCode] = useState<string | null>(null);
  const [hoveredBoundaryLabel, setHoveredBoundaryLabel] = useState<string | null>(
    null
  );
  const [focusedLocalityCode, setFocusedLocalityCode] = useState<string | null>(
    null
  );
  const [tourActive, setTourActive] = useState(false);
  const [tourIndex, setTourIndex] = useState(0);
  const [tourTransitioning, setTourTransitioning] = useState(false);
  const [fullscreenActive, setFullscreenActive] = useState(false);
  const [mapPosition, setMapPosition] = useState<MapCameraPosition>({
    center: [0, 20],
    zoom: 1
  });
  const mapPositionRef = useRef(mapPosition);
  const mapAnimationFrameRef = useRef<number | null>(null);
  const mapSettleTimeoutRef = useRef<number | null>(null);
  const mapSurfaceRef = useRef<HTMLDivElement>(null);
  const activeSelectedCode = selectedCode ?? localSelectedCode;
  const countryMapActive = mapView === "country";
  const selectedState = getSpotlightState(activeSelectedCode);
  const defaultRegion = getSpotlightState(defaultCode);
  const activeRegion =
    selectedState?.countryCode === activeCountry.code
      ? selectedState
      : defaultRegion?.countryCode === activeCountry.code
        ? defaultRegion
        : null;
  const selectedKalshiMarkets = useMemo(
    () =>
      kalshiMarkets.filter((kalshiMarket) =>
        kalshiMarketMatchesRegion(activeRegion, kalshiMarket)
      ),
    [activeRegion, kalshiMarkets]
  );
  const selectedPolymarketMarkets = useMemo(() => {
    const slugs = getRegionPolymarketSlugs(activeRegion);
    const markets = polymarketMarkets.filter((candidate) =>
      marketMatchesRegion(activeRegion, candidate)
    );
    if (
      market.venue !== "Kalshi" &&
      marketMatchesRegion(activeRegion, market) &&
      !markets.some((candidate) => candidate.eventSlug === market.eventSlug)
    ) {
      markets.push(market);
    }
    return markets.sort((left, right) => {
      const leftIndex = slugs.indexOf(left.eventSlug ?? left.slug);
      const rightIndex = slugs.indexOf(right.eventSlug ?? right.slug);
      if (leftIndex >= 0 || rightIndex >= 0) {
        return (
          (leftIndex >= 0 ? leftIndex : Number.MAX_SAFE_INTEGER) -
          (rightIndex >= 0 ? rightIndex : Number.MAX_SAFE_INTEGER)
        );
      }
      return right.volume24h - left.volume24h;
    });
  }, [activeRegion, market, polymarketMarkets]);
  const tradingPairs = useMemo(
    () => [
      ...selectedPolymarketMarkets.map((pair) => ({
        venue: "polymarket" as const,
        pair
      })),
      ...selectedKalshiMarkets.map((pair) => ({
        venue: "kalshi" as const,
        pair
      }))
    ],
    [selectedKalshiMarkets, selectedPolymarketMarkets]
  );
  const paginatedTradingPairs = useMemo(
    () => paginateTradingPairs(tradingPairs, tradingPairPage),
    [tradingPairPage, tradingPairs]
  );

  useEffect(() => {
    setTradingPairPage(0);
  }, [activeCountry.code, activeRegion?.code]);

  useEffect(() => {
    if (tradingPairPage !== paginatedTradingPairs.page) {
      setTradingPairPage(paginatedTradingPairs.page);
    }
  }, [paginatedTradingPairs.page, tradingPairPage]);

  useEffect(() => {
    if (!onSelectCode) {
      setLocalSelectedCode(null);
    }
  }, [defaultCode, onSelectCode]);

  const selectCode = (code: string | null) => {
    if (onSelectCode) {
      onSelectCode(code);
      return;
    }
    setLocalSelectedCode(code);
  };

  useEffect(() => {
    if (selectedCode === undefined) {
      return;
    }

    setLocalSelectedCode(selectedCode);
  }, [selectedCode]);

  useEffect(() => {
    mapPositionRef.current = mapPosition;
  }, [mapPosition]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setFullscreenActive(document.fullscreenElement === mapSurfaceRef.current);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () =>
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement === mapSurfaceRef.current) {
        await document.exitFullscreen();
      } else {
        await mapSurfaceRef.current?.requestFullscreen();
      }
    } catch {
      setFullscreenActive(false);
    }
  };

  const cancelMapTransition = useCallback(() => {
    if (mapAnimationFrameRef.current !== null) {
      window.cancelAnimationFrame(mapAnimationFrameRef.current);
      mapAnimationFrameRef.current = null;
    }
    if (mapSettleTimeoutRef.current !== null) {
      window.clearTimeout(mapSettleTimeoutRef.current);
      mapSettleTimeoutRef.current = null;
    }
    setTourTransitioning(false);
  }, []);

  useEffect(() => {
    const countryZoom =
      activeCountry.code === "GB"
        ? 6
        : activeCountry.code === "US"
          ? 2.1
          : activeCountry.defaultZoom;
    const target: MapCameraPosition =
      mapView === "world"
        ? { center: [0, 20], zoom: 1 }
        : tourActive && activeRegion
          ? {
              center: activeRegion.center,
              zoom: activeRegion.zoom
            }
          : {
              center: activeCountry.defaultCenter,
              zoom: countryZoom
            };

    cancelMapTransition();

    if (!tourActive) {
      mapPositionRef.current = target;
      setMapPosition(target);
      return;
    }

    const from = mapPositionRef.current;
    const isAlreadyAtTarget =
      Math.abs(from.center[0] - target.center[0]) < 0.001 &&
      Math.abs(from.center[1] - target.center[1]) < 0.001 &&
      Math.abs(from.zoom - target.zoom) < 0.001;

    if (isAlreadyAtTarget) return;

    setTourTransitioning(true);
    const startedAt = window.performance.now();

    const animate = (timestamp: number) => {
      const progress = Math.min(
        1,
        (timestamp - startedAt) / MAP_CAMERA_TRANSITION_MS
      );
      const position = getMapTransitionPosition(from, target, progress);
      mapPositionRef.current = position;
      setMapPosition(position);

      if (progress < 1) {
        mapAnimationFrameRef.current =
          window.requestAnimationFrame(animate);
        return;
      }

      mapAnimationFrameRef.current = null;
      mapSettleTimeoutRef.current = window.setTimeout(() => {
        mapSettleTimeoutRef.current = null;
        setTourTransitioning(false);
      }, MAP_CAMERA_SETTLE_MS);
    };

    mapAnimationFrameRef.current = window.requestAnimationFrame(animate);

    return cancelMapTransition;
  }, [
    activeCountry,
    activeRegion,
    cancelMapTransition,
    mapView,
    tourActive
  ]);

  const tourRegions = useMemo(
    () => getAutoTourRegions(allRegionMarkets, regionSignals),
    [allRegionMarkets, regionSignals]
  );

  useEffect(() => {
    setTourActive(autoTourEnabled);
  }, [autoTourEnabled]);

  const setTourEnabled = (enabled: boolean) => {
    if (!enabled) cancelMapTransition();
    setTourActive(enabled);
    onAutoTourEnabledChange?.(enabled);
  };

  useEffect(() => {
    if (
      !tourActive ||
      tourTransitioning ||
      !tourRegions.length ||
      !onSelectCountryCode ||
      !onSelectCode ||
      !onMapViewChange
    ) {
      return;
    }

    const delay = mapView === "world" ? 3_500 : 6_500;
    const timeout = window.setTimeout(() => {
      const region = tourRegions[tourIndex % tourRegions.length];
      onSelectCountryCode(region.countryCode);
      onSelectCode(region.code);
      onMapViewChange("country");
      setTourIndex((current) => (current + 1) % tourRegions.length);
    }, delay);

    return () => window.clearTimeout(timeout);
  }, [
    mapView,
    onMapViewChange,
    onSelectCode,
    onSelectCountryCode,
    tourActive,
    tourIndex,
    tourRegions,
    tourTransitioning
  ]);

  const compactTitle =
    market.title.length > 56 ? `${market.title.slice(0, 56)}...` : market.title;
  const marketMovement = useMemo(
    () => summarizeMarketMovement(marketSeries, market.probability),
    [market.probability, marketSeries]
  );
  const marketMatchesActiveRegion =
    Boolean(activeRegion) &&
    (marketMatchesRegion(activeRegion, market) ||
      (market.venue === "Kalshi" &&
        market.eventId === activeRegion?.kalshiEventTicker));
  const activeRegionWatched = activeRegion
    ? signalWatchlist.watchlist.includes(`${activeCountry.code}:${activeRegion.code}`)
    : false;
  const marketCloseLabel = formatContractDate(market.endDate, market.status);
  const highPriorityCount = regionMarkets.filter(
    (region) => getRegionSignal(region).score >= 70
  ).length;
  const hoveredRegion = getSpotlightState(hoveredCode);
  const hoveredSignal = hoveredRegion
    ? getRegionSignal(hoveredRegion)
    : null;
  const hoveredVolume = hoveredRegion
    ? getRegionMarketVolume(
        hoveredRegion,
        kalshiMarkets,
        polymarketMarkets
      )
    : null;

  const selectCountry = (country: CountryMarketMap) => {
    setTourEnabled(false);
    onSelectCountryCode?.(country.code);
    selectCode(country.defaultRegionCode);
    onMapViewChange?.("country");
  };

  const selectRegion = (region: RegionMarket) => {
    setTourEnabled(false);
    const country =
      availableCountries.find((candidate) => candidate.code === region.countryCode) ??
      activeCountry;
    onSelectCountryCode?.(country.code);
    selectCode(region.code);
    onMapViewChange?.("country");
  };

  return (
    <div
      className={`market-map-layout grid gap-8 ${
        workspaceLayout ? "market-map-layout--workspace " : ""
      }${
        mapView === "country"
          ? "lg:grid-cols-[minmax(0,1.7fr)_minmax(260px,0.9fr)] lg:items-start xl:grid-cols-[3fr_1fr]"
          : ""
      }`}
    >
      <div className="market-map-primary min-w-0">
        <div className="market-map-context mb-4 flex flex-wrap items-center gap-3">
          <p className="font-sans text-xs font-medium text-slate-600">
            {mapView === "world"
              ? `${allRegionMarkets.length} markets tracked across ${availableCountries.length} countries`
              : `${regionMarkets.length} markets mapped · ${highPriorityCount} high priority${
                  activeRegion ? ` · Focus ${activeRegion.label}` : ""
                }`}
          </p>
        </div>

        <div className="market-map-stack grid items-stretch gap-6">
          <div
            ref={mapSurfaceRef}
            className="market-map-surface relative order-1 aspect-[4/3] min-h-[320px] overflow-hidden rounded-lg bg-transparent lg:aspect-[16/10]"
            style={{ border: "1.5px solid var(--demo-card-bg)" }}
            onPointerDownCapture={(event) => {
              if (
                (event.target as HTMLElement).closest("[data-map-control]")
              ) {
                return;
              }
              setTourEnabled(false);
            }}
          >
            {mapView === "country" ? (
              <R3fMarketGlobe
                activeCountry={activeCountry}
                regions={globeRegionData}
                selectedCode={activeSelectedCode}
                trades={regionalTradePopups}
                onSelectCountry={selectCountry}
                onSelectRegion={selectRegion}
              />
            ) : (
            <ComposableMap
              projection="geoMercator"
              projectionConfig={{ scale: 147 }}
              width={980}
              height={620}
              className="market-map-svg h-full w-full"
            >
              <ZoomableGroup
                center={mapPosition.center}
                zoom={mapPosition.zoom}
                minZoom={0.8}
                maxZoom={12}
                onMoveEnd={({ coordinates, zoom }) =>
                  setMapPosition({
                    center: coordinates as [number, number],
                    zoom
                  })
                }
                translateExtent={[
                  [-220, -100],
                  [1200, 720]
                ]}
              >
                <Geographies geography={worldCountries}>
                  {({ geographies }) =>
                    geographies.map((geo) => {
                      const country = availableCountries.find(
                        (candidate) =>
                          candidate.worldFeatureIds.includes(String(geo.id))
                      );
                      const countrySummary = country
                        ? countrySummaries.find(
                            (summary) => summary.country.code === country.code
                          )
                        : null;
                      const topSignal = countrySummary?.topRegion?.signal ?? null;
                      const isSelectedCountry =
                        countryMapActive && country?.code === activeCountry.code;
                      const countryInteractive =
                        mapView === "world"
                          ? country
                          : country?.code === activeCountry.code
                            ? undefined
                            : country;
                      const fill = isSelectedCountry
                        ? "#c7c7c3"
                        : topSignal
                          ? getMarketSignalColor(topSignal.score)
                          : getMarketSignalColor(null);
                      const fillOpacity = country
                        ? getMarketVolumeOpacity(
                            countrySummary?.volume24h ?? null
                          )
                        : 1;

                      return (
                        <Geography
                          key={geo.rsmKey}
                          geography={geo}
                          onClick={
                            countryInteractive
                              ? () => selectCountry(countryInteractive)
                              : undefined
                          }
                          onKeyDown={
                            countryInteractive
                              ? (event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    selectCountry(countryInteractive);
                                  }
                                }
                              : undefined
                          }
                          aria-label={
                            countryInteractive
                              ? `${countryInteractive.label}: top activity score ${topSignal?.score ?? 0}`
                              : undefined
                          }
                          role={countryInteractive ? "button" : "presentation"}
                          tabIndex={countryInteractive ? 0 : -1}
                          style={{
                            default: {
                              fill,
                              fillOpacity,
                              outline: "none",
                              stroke: "var(--map-boundary)",
                              strokeWidth: isSelectedCountry ? 1.4 : 0.45,
                              cursor: countryInteractive ? "pointer" : "grab"
                            },
                            hover: {
                              fill: countryInteractive ? fill : "#cfcfcb",
                              fillOpacity,
                              outline: "none",
                              stroke: "var(--map-boundary)",
                              strokeWidth: countryInteractive ? 1.2 : 0.45,
                              cursor: countryInteractive ? "pointer" : "grab"
                            },
                            pressed: {
                              fill,
                              fillOpacity,
                              outline: "none",
                              stroke: "var(--map-boundary)",
                              strokeWidth: 1.2
                            }
                          }}
                        />
                      );
                    })
                  }
                </Geographies>

                {countryMapActive ? (() => {
                  const country = activeCountry;
                  const regions = regionMarkets;
                  const regionById = new Map<string, RegionMarket>();
                  regions
                    .filter((region) => region.coverage !== "country")
                    .forEach((region) => {
                      if (!regionById.has(region.featureId)) {
                        regionById.set(region.featureId, region);
                      }
                    });
                  const nationalRegion = regions.find(
                    (region) => region.coverage === "country"
                  );
                  const geography =
                    country.code === "US"
                      ? usAtlas
                      : country.code === "GB"
                        ? ukRegions
                        : country.code === "FR"
                          ? franceRegions
                          : country.code === "DE"
                            ? germanyStates
                            : country.code === "UA"
                              ? ukraineOblastGeography
                            : worldCountries;

                  return (
                    <Geographies key={country.code} geography={geography}>
                      {({ geographies }) =>
                        geographies.map((geo) => {
                          if (
                            geography === worldCountries &&
                            !country.worldFeatureIds.includes(String(geo.id))
                          ) {
                            return null;
                          }

                          const featureId =
                            country.code === "US"
                              ? String(geo.id).padStart(2, "0")
                              : country.featureIdProperty
                                ? String(
                                  geo.properties?.[
                                      country.featureIdProperty
                                    ] ?? ""
                                  )
                                : String(geo.id);
                          const region =
                            regionById.get(featureId) ?? nationalRegion ?? null;
                          const boundaryLabel = String(
                            geo.properties?.nom ??
                              geo.properties?.name ??
                              geo.properties?.NAME ??
                              geo.properties?.Display_Name_w_Oblast ??
                              region?.label ??
                              country.label
                          );
                          const signal = region ? getRegionSignal(region) : null;
                          const volume = region
                            ? getRegionMarketVolume(
                                region,
                                kalshiMarkets,
                                polymarketMarkets
                              )
                            : null;
                          const isSelected =
                            region?.countryCode === activeCountry.code &&
                            region?.code === activeSelectedCode;
                          const fill = signal
                            ? getMarketSignalColor(signal.score)
                            : getMarketSignalColor(null);
                          const fillOpacity = region
                            ? getMarketVolumeOpacity(volume)
                            : 1;

                          return (
                            <Geography
                              key={geo.rsmKey}
                              geography={geo}
                              onClick={
                                region ? () => selectRegion(region) : undefined
                              }
                              onMouseEnter={
                                region
                                  ? () => {
                                      setHoveredCode(region.code);
                                      setHoveredBoundaryLabel(boundaryLabel);
                                    }
                                  : undefined
                              }
                              onMouseLeave={
                                region
                                  ? () => {
                                      setHoveredCode(null);
                                      setHoveredBoundaryLabel(null);
                                    }
                                  : undefined
                              }
                              onKeyDown={
                                region
                                  ? (event) => {
                                      if (
                                        event.key === "Enter" ||
                                        event.key === " "
                                      ) {
                                        event.preventDefault();
                                        selectRegion(region);
                                      }
                                    }
                                  : undefined
                              }
                              aria-label={
                                region && signal
                                  ? `${boundaryLabel}, ${country.label}: ${region.coverage === "country" ? "national market " : ""}activity score ${signal.score}, ${getMarketSignalSeverity(signal.score)}${volume !== null ? `, 24 hour volume ${formatMarketVolume(volume)}` : ""}`
                                  : undefined
                              }
                              role={region ? "button" : "presentation"}
                              tabIndex={region ? 0 : -1}
                              style={{
                                default: {
                                  fill,
                                  fillOpacity,
                                  outline: "none",
                                  stroke: "var(--map-boundary)",
                                  strokeWidth:
                                    (isSelected ? 1.8 : 0.55) /
                                    mapPosition.zoom,
                                  cursor: region ? "pointer" : "grab"
                                },
                                hover: {
                                  fill: region ? fill : "#cfcfcb",
                                  fillOpacity,
                                  outline: "none",
                                  stroke: "var(--map-boundary)",
                                  strokeWidth:
                                    (region ? 1.4 : 0.55) /
                                    mapPosition.zoom,
                                  cursor: region ? "pointer" : "grab"
                                },
                                pressed: {
                                  fill,
                                  fillOpacity,
                                  outline: "none",
                                  stroke: "var(--map-boundary)",
                                  strokeWidth:
                                    (region ? 1.8 : 0.55) /
                                    mapPosition.zoom
                                }
                              }}
                            />
                          );
                        })
                      }
                    </Geographies>
                  );
                })() : null}

                {countryMapActive && activeCountry.code === "UA"
                  ? regionMarkets
                      .filter((region) => region.coverage === "region")
                      .map((region) => {
                        const signal = getRegionSignal(region);
                        const offset =
                          UKRAINE_LOCALITY_LABEL_OFFSETS[region.code] ?? {
                            x: 8,
                            y: -8
                          };
                        const selected = region.code === activeSelectedCode;

                        return (
                          <Marker
                            key={`ukraine-locality:${region.code}`}
                            coordinates={region.center}
                          >
                            <g
                              role="button"
                              tabIndex={0}
                              aria-label={`${region.label}, Ukraine: ${getRegionMarketPairLabel(region)}`}
                              onClick={() => selectRegion(region)}
                              onKeyDown={(event) => {
                                if (
                                  event.key === "Enter" ||
                                  event.key === " "
                                ) {
                                  event.preventDefault();
                                  selectRegion(region);
                                }
                              }}
                              onFocus={() => setFocusedLocalityCode(region.code)}
                              onBlur={() => setFocusedLocalityCode(null)}
                              className="cursor-pointer"
                              style={{ outline: "none" }}
                            >
                              {focusedLocalityCode === region.code ? (
                                <circle
                                  r={7 / mapPosition.zoom}
                                  fill="none"
                                  stroke="var(--map-boundary)"
                                  strokeWidth={1.5 / mapPosition.zoom}
                                  pointerEvents="none"
                                />
                              ) : null}
                              <circle
                                r={(selected ? 5 : 3.5) / mapPosition.zoom}
                                fill={getMarketSignalColor(signal.score)}
                                stroke="var(--map-boundary)"
                                strokeWidth={1.5 / mapPosition.zoom}
                              />
                              <text
                                x={offset.x / mapPosition.zoom}
                                y={offset.y / mapPosition.zoom}
                                textAnchor={offset.x < 0 ? "end" : "start"}
                                fill="#111827"
                                fontFamily="Inter, Segoe UI, sans-serif"
                                fontSize={10 / mapPosition.zoom}
                                fontWeight={700}
                                paintOrder="stroke"
                                stroke="var(--demo-card-bg)"
                                strokeWidth={3 / mapPosition.zoom}
                              >
                                {region.label}
                              </text>
                            </g>
                          </Marker>
                        );
                      })
                  : null}

                {mapView === "world"
                  ? labeledCountries.map(({ country, topRegion }) => (
                      <Marker
                        key={country.code}
                        coordinates={country.defaultCenter}
                      >
                        <g aria-hidden="true" className="pointer-events-none">
                          <circle
                            r={8 / mapPosition.zoom}
                            fill={getMarketSignalColor(
                              topRegion?.signal.score ?? 0
                            )}
                            stroke="#ffffff"
                            strokeWidth={1.5 / mapPosition.zoom}
                          />
                          <text
                            y={-14 / mapPosition.zoom}
                            textAnchor="middle"
                            fill="#111827"
                            fontFamily="Inter, Segoe UI, sans-serif"
                            fontSize={9 / mapPosition.zoom}
                            fontWeight={700}
                            paintOrder="stroke"
                            stroke="var(--demo-card-bg)"
                            strokeWidth={3 / mapPosition.zoom}
                          >
                            {country.code} {topRegion?.signal.score ?? 0}
                          </text>
                        </g>
                      </Marker>
                    ))
                  : labeledRegions.map(({ region, signal, volume }) => (
                  <Marker
                    key={`${region.countryCode}:${region.code}`}
                    coordinates={region.center}
                  >
                    <g aria-hidden="true" className="pointer-events-none">
                      <circle
                        r={8 / mapPosition.zoom}
                        fill={getMarketSignalColor(signal.score)}
                        stroke="#ffffff"
                        strokeWidth={1.5 / mapPosition.zoom}
                      />
                      <text
                        y={-14 / mapPosition.zoom}
                        textAnchor="middle"
                        fill="#111827"
                        fontFamily="Inter, Segoe UI, sans-serif"
                        fontSize={9 / mapPosition.zoom}
                        fontWeight={700}
                        paintOrder="stroke"
                        stroke="var(--demo-card-bg)"
                        strokeWidth={3 / mapPosition.zoom}
                      >
                        {region.code}{" "}
                        {signal.score >= 70
                          ? signal.score
                          : formatMarketVolume(volume)}
                      </text>
                    </g>
                  </Marker>
                    ))}
              </ZoomableGroup>
            </ComposableMap>
            )}
            {hoveredRegion && hoveredSignal ? (
              <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-[260px] border border-slate-200 bg-white/95 px-3 py-2 font-sans shadow-sm">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-xs font-semibold text-slate-900">
                    {hoveredBoundaryLabel ?? hoveredRegion.label}
                  </span>
                  <span className="text-xs font-semibold tabular-nums text-slate-900">
                    {hoveredSignal.score > 0
                      ? hoveredSignal.score
                      : formatMarketVolume(hoveredVolume)}
                  </span>
                </div>
                <p className="mt-1 truncate text-[11px] text-slate-600">
                  {getRegionMarketPairLabel(hoveredRegion)}
                </p>
              </div>
            ) : null}
            {mapView === "world" ? (
              <MapLiveTradeTape
                marketSlugs={allRegionMarkets.flatMap((region) =>
                  getRegionPolymarketSlugs(region)
                )}
                trades={liveTrades}
              />
            ) : null}
            <div
              data-map-control
              className="market-map-controls absolute right-3 top-3 z-10 flex gap-2"
            >
              <span className="market-map-live-status">
                <span aria-hidden="true" />
                Live
              </span>
              <button
                type="button"
                title={fullscreenActive ? "Exit fullscreen" : "Enter fullscreen"}
                aria-label={
                  fullscreenActive ? "Exit fullscreen map" : "Enter fullscreen map"
                }
                aria-pressed={fullscreenActive}
                onClick={toggleFullscreen}
                className="market-map-control-button"
              >
                {fullscreenActive ? <X aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}
              </button>
              <button
                type="button"
                title={tourActive ? "Pause live map tour" : "Resume live map tour"}
                aria-label={tourActive ? "Pause live map tour" : "Resume live map tour"}
                aria-pressed={tourActive}
                onClick={() => setTourEnabled(!tourActive)}
                className="market-map-control-button"
              >
                {tourActive ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
              </button>
            </div>
          </div>
          {workspaceLayout ? (
            <div className="market-map-legend market-map-volume-key order-2">
              <span className="market-map-volume-title">24h volume</span>
              <span className="market-map-volume-scale" aria-hidden="true" />
              <span className="market-map-volume-range">
                <span>Low</span>
                <span>High</span>
              </span>
            </div>
          ) : (
            <div className="market-map-legend order-2 flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-xs text-slate-600">
              <span className="font-medium text-slate-900">Activity score</span>
              {SIGNAL_LEGEND.map((item) => (
                <span key={item.severity} className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: getMarketSignalColor(item.severity === "critical" ? 85 : item.severity === "high" ? 70 : item.severity === "elevated" ? 50 : 0) }}
                  />
                  {item.label}
                </span>
              ))}
              <span className="font-medium text-slate-900">24h volume</span>
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full bg-slate-700"
                  style={{ opacity: getMarketVolumeOpacity(100) }}
                />
                Low
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="h-2.5 w-2.5 rounded-full bg-slate-700"
                  style={{ opacity: getMarketVolumeOpacity(500_000) }}
                />
                High
              </span>
              <a
                href={
                  mapView === "world"
                    ? "https://github.com/topojson/world-atlas"
                    : activeCountry.boundarySourceUrl
                }
                target="_blank"
                rel="noreferrer"
                className="ml-auto text-slate-400 hover:text-slate-700"
              >
                Boundaries:{" "}
                {mapView === "world"
                  ? "Natural Earth"
                  : activeCountry.boundarySourceLabel}{" "}
                ↗
              </a>
            </div>
          )}
          <div id="market-activity" className="market-map-feed order-3">
            <AbnormalActivityFeed
              regions={
                countryScope === "global" ? allRegionMarkets : regionMarkets
              }
              signals={regionSignals}
              selectedCode={activeSelectedCode ?? defaultCode}
              minimumScore={activityThreshold}
              minimumVolume={activityVolumeThreshold}
              kalshiMarkets={kalshiMarkets}
              polymarketMarkets={polymarketMarkets}
              signalKind={activitySignalKind}
              maxAgeHours={activityMaxAgeHours}
              countryCode={activeCountry.code}
              countryLabel={activeCountry.label}
              countryScope={countryScope}
              watchlist={signalWatchlist.watchlist}
              watchedOnly={signalWatchlist.watchedOnly}
              alertsEnabled={signalWatchlist.alertsEnabled}
              alertPermission={signalWatchlist.alertPermission}
              onCountryScopeChange={(scope) => {
                setTourEnabled(false);
                onCountryScopeChange?.(scope);
              }}
              onMinimumScoreChange={onActivityThresholdChange ?? (() => undefined)}
              onMinimumVolumeChange={
                onActivityVolumeThresholdChange ?? (() => undefined)
              }
              onSignalKindChange={onActivitySignalKindChange ?? (() => undefined)}
              onMaxAgeHoursChange={onActivityMaxAgeHoursChange ?? (() => undefined)}
              onWatchedOnlyChange={signalWatchlist.setWatchedOnly}
              onAlertsEnabledChange={(enabled) => {
                void signalWatchlist.setBrowserAlertsEnabled(enabled);
              }}
              onToggleWatch={signalWatchlist.toggleWatch}
              onSelect={selectRegion}
            />
          </div>
        </div>
      </div>

      <div
        id="market-pairs"
        className={
          mapView === "world"
            ? "hidden"
            : "market-map-inspector pt-4 lg:pl-2 lg:pt-0"
        }
      >
        <p className="metric-label">Market Overview</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <h3 className="text-xl font-semibold leading-tight text-slate-900 sm:text-2xl">
            {activeRegion?.label ?? compactTitle}
          </h3>
          {marketMatchesActiveRegion && market.status === "closed" ? (
            <span className="border border-slate-400 px-2 py-1 font-sans text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
              Closed
            </span>
          ) : null}
        </div>
        {activeRegion ? (
          <p className="mt-3 text-sm leading-6 text-slate-600">
            {activeRegion.countryLabel} ·{" "}
            {marketMatchesActiveRegion && market.status === "closed"
              ? "This contract is closed. Market statistics are historical."
              : activeRegion.note}
          </p>
        ) : null}

        {marketMatchesActiveRegion ? (
          <div className="mt-6 font-sans">
            <div className="flex items-end justify-between gap-5">
              <div>
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  {market.status === "closed" ? "Final probability" : "Probability"}
                </p>
                <p className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">
                  {(market.probability * 100).toFixed(1)}%
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  {market.status === "closed" ? "Last 24h volume" : "24h volume"}
                </p>
                <p className="mt-1 text-base font-semibold tabular-nums text-slate-900">
                  {market.status === "closed" && market.volume24h === 0
                    ? "—"
                    : formatCompactCurrency(market.volume24h)}
                </p>
              </div>
            </div>
            <dl className="mt-5 grid grid-cols-4 gap-3">
              {([
                ["1h", marketMovement.oneHour],
                ["24h", marketMovement.twentyFourHours],
                ["7d", marketMovement.sevenDays]
              ] satisfies Array<[string, number | null]>).map(([label, value]) => (
                <div key={label}>
                  <dt className="text-[10px] uppercase tracking-[0.16em] text-slate-400">{label}</dt>
                  <dd className={`mt-1 text-xs font-semibold tabular-nums ${movementTone(value)}`}>
                    {formatMovement(value)}
                  </dd>
                </div>
              ))}
              <div className="text-right">
                <dt className="text-[10px] uppercase tracking-[0.16em] text-slate-400">Liquidity</dt>
                <dd className="mt-1 text-xs font-semibold tabular-nums text-slate-900">
                  {!market.liquidity
                    ? "—"
                    : formatCompactCurrency(market.liquidity)}
                </dd>
              </div>
            </dl>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2 font-sans">
          {activeRegion ? (
            <button
              type="button"
              aria-pressed={activeRegionWatched}
              onClick={() => signalWatchlist.toggleWatch(activeCountry.code, activeRegion.code)}
              className={`border px-3 py-2 text-xs font-semibold transition ${
                activeRegionWatched
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 text-slate-700 hover:border-slate-900 hover:text-slate-900"
              }`}
            >
              {activeRegionWatched ? "Watching" : "Watch region"}
            </button>
          ) : null}
        </div>

        {tradingPairs.length ? (
          <section
            aria-label="Available trading pairs"
            className="mt-5 border-t border-slate-200 font-sans"
          >
            <div className="flex items-center justify-between py-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Trading pairs
              </p>
              <p className="text-[10px] text-slate-400">
                {paginatedTradingPairs.start + 1}–{paginatedTradingPairs.end} of {tradingPairs.length}
              </p>
            </div>
            {paginatedTradingPairs.items.map((tradingPair) => {
              if (tradingPair.venue === "polymarket") {
                const polymarketMarket = tradingPair.pair;
                const eventSlug =
                  polymarketMarket.eventSlug ?? polymarketMarket.slug;
                const selected =
                  market.venue !== "Kalshi" &&
                  (market.eventSlug ?? market.slug) === eventSlug;
                return (
                  <div
                    key={eventSlug}
                    className={`grid grid-cols-[72px_minmax(0,1fr)_auto] items-center gap-3 border-t py-3 ${
                      selected
                        ? "border-slate-300 bg-slate-50"
                        : "border-slate-200"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectMarketSlug?.(eventSlug)}
                      className="col-span-2 grid min-w-0 grid-cols-[72px_minmax(0,1fr)] items-center gap-3 text-left"
                      aria-pressed={selected}
                    >
                      <span className="text-[10px] font-semibold uppercase text-slate-500">
                        Polymarket
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-xs font-semibold text-slate-900">
                          {polymarketMarket.title}
                        </span>
                        <span className="mt-1 block text-[10px] text-slate-500">
                          {polymarketMarket.status === "open"
                            ? selected
                              ? "Selected"
                              : "Open"
                            : "View only"}{" "}
                          · 24h {formatCompactCurrency(polymarketMarket.volume24h)}
                        </span>
                      </span>
                    </button>
                    <a
                      href={`https://polymarket.com/event/${eventSlug}`}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Open ${polymarketMarket.title} on Polymarket`}
                      className="text-xs font-semibold tabular-nums text-slate-900"
                    >
                      {(polymarketMarket.probability * 100).toFixed(0)}% ↗
                    </a>
                  </div>
                );
              }

              const kalshiMarket = tradingPair.pair;
              return (
                <a
                  key={kalshiMarket.eventTicker}
                  href={kalshiMarket.url}
                  target="_blank"
                  rel="noreferrer"
                  className="grid grid-cols-[72px_minmax(0,1fr)_auto] items-center gap-3 border-t border-slate-200 py-3 transition hover:bg-slate-50"
                >
                  <span className="text-[10px] font-semibold uppercase text-slate-500">
                    Kalshi
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-semibold text-slate-900">
                      {kalshiMarket.title}
                    </span>
                    <span className="mt-1 block truncate text-[10px] text-slate-500">
                      {kalshiMarket.outcomeLabel ?? "Leading outcome"} · 24h{" "}
                      {formatCompactCurrency(kalshiMarket.volume24h)}
                    </span>
                  </span>
                  <span className="text-xs font-semibold tabular-nums text-slate-900">
                    {(kalshiMarket.probability * 100).toFixed(0)}% ↗
                  </span>
                </a>
              );
            })}
            {paginatedTradingPairs.pageCount > 1 ? (
              <div className="flex items-center justify-end gap-2 border-t border-slate-200 py-3">
                <button
                  type="button"
                  title="Previous trading-pair page"
                  aria-label="Previous trading-pair page"
                  disabled={paginatedTradingPairs.page === 0}
                  onClick={() => setTradingPairPage((page) => page - 1)}
                  className="grid h-7 w-7 place-items-center border border-slate-300 text-sm text-slate-700 transition hover:border-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  ‹
                </button>
                <span className="text-[10px] tabular-nums text-slate-500">
                  {paginatedTradingPairs.page + 1} / {paginatedTradingPairs.pageCount}
                </span>
                <button
                  type="button"
                  title="Next trading-pair page"
                  aria-label="Next trading-pair page"
                  disabled={
                    paginatedTradingPairs.page ===
                    paginatedTradingPairs.pageCount - 1
                  }
                  onClick={() => setTradingPairPage((page) => page + 1)}
                  className="grid h-7 w-7 place-items-center border border-slate-300 text-sm text-slate-700 transition hover:border-slate-900 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  ›
                </button>
              </div>
            ) : null}
          </section>
        ) : null}

        {marketMatchesActiveRegion &&
        (market.venue || marketCloseLabel || market.description || market.resolutionSource) ? (
          <div className="mt-5 font-sans text-xs leading-5 text-slate-500">
            {market.venue || marketCloseLabel ? (
              <p>
                {[
                  market.venue ? `Venue: ${market.venue}` : null,
                  marketCloseLabel
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            ) : null}
            {market.description || market.resolutionSource ? (
              <details className="mt-2">
                <summary className="w-fit cursor-pointer font-semibold text-slate-700 transition hover:text-slate-900">
                  Contract details
                </summary>
                {market.description ? (
                  <p className="mt-2 max-w-prose text-sm leading-6 text-slate-600">
                    {market.description}
                  </p>
                ) : null}
                {market.resolutionSource ? (
                  <a
                    href={market.resolutionSource}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-block font-semibold text-slate-700 hover:text-slate-900"
                  >
                    Resolution source ↗
                  </a>
                ) : null}
              </details>
            ) : null}
          </div>
        ) : null}

      </div>
    </div>
  );
}
