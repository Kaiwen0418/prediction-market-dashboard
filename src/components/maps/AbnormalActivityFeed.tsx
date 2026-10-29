"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getMarketSignalColor,
  getMarketSignalLabel,
  rankRegionSignals
} from "@/components/maps/marketSignals";
import type {
  ActivityCountryScope,
  ActivitySignalFilter,
  ActivityTimeWindow,
  ActivityVolumeThreshold
} from "@/components/maps/activityFeedFilters";
import {
  formatMarketVolume,
  getRegionMarketVolume,
  KALSHI_VOLUME_COLOR,
  qualifiesBySignal,
  qualifiesByVolume
} from "@/components/maps/marketVolume";
import type { RegionMarket } from "@/components/maps/spotlightStates";
import type { MarketSnapshot, VenueMarketSummary } from "@/types/market";
import type { RegionSignal } from "@/types/signals";
import { relativeTime } from "@/utils/time";
import { filterWatchedRegions } from "@/components/maps/signalWatchlist";
import {
  ACTIVITY_FEED_PAGE_SIZE,
  getPaginationItems
} from "@/components/maps/activityFeedPagination";

type AbnormalActivityFeedProps = {
  regions: RegionMarket[];
  signals: RegionSignal[];
  selectedCode?: string | null;
  minimumScore: number;
  minimumVolume: ActivityVolumeThreshold;
  kalshiMarkets: VenueMarketSummary[];
  polymarketMarkets: MarketSnapshot[];
  signalKind: ActivitySignalFilter;
  maxAgeHours: ActivityTimeWindow;
  countryCode: string;
  countryLabel: string;
  countryScope: ActivityCountryScope;
  watchlist: string[];
  watchedOnly: boolean;
  alertsEnabled: boolean;
  alertPermission: NotificationPermission | "unsupported";
  onCountryScopeChange: (scope: ActivityCountryScope) => void;
  onMinimumScoreChange: (score: number) => void;
  onMinimumVolumeChange: (volume: ActivityVolumeThreshold) => void;
  onSignalKindChange: (kind: ActivitySignalFilter) => void;
  onMaxAgeHoursChange: (hours: ActivityTimeWindow) => void;
  onWatchedOnlyChange: (watchedOnly: boolean) => void;
  onAlertsEnabledChange: (enabled: boolean) => void;
  onToggleWatch: (countryCode: string, regionCode: string) => void;
  onSelect: (region: RegionMarket) => void;
};

const THRESHOLDS = [
  { label: "All", value: 0 },
  { label: "50+", value: 50 },
  { label: "70+", value: 70 },
  { label: "85+", value: 85 }
] as const;

const SIGNAL_TYPES: Array<{ label: string; value: ActivitySignalFilter }> = [
  { label: "All signals", value: "all" },
  { label: "Whale flow", value: "whale-flow" },
  { label: "Order flow", value: "order-flow" },
  { label: "Volume anomaly", value: "volume-anomaly" },
  { label: "Price move", value: "price-move" },
  { label: "Poll divergence", value: "poll-divergence" },
  { label: "Normal", value: "normal" }
];

const TIME_WINDOWS: Array<{ label: string; value: ActivityTimeWindow }> = [
  { label: "Any time", value: 0 },
  { label: "Past hour", value: 1 },
  { label: "Past 6 hours", value: 6 },
  { label: "Past 24 hours", value: 24 }
];

const VOLUME_THRESHOLDS: Array<{
  label: string;
  value: ActivityVolumeThreshold;
}> = [
  { label: "Off", value: 0 },
  { label: "$1K+", value: 1_000 },
  { label: "$10K+", value: 10_000 },
  { label: "$100K+", value: 100_000 }
];

export function AbnormalActivityFeed({
  regions,
  signals,
  selectedCode,
  minimumScore,
  minimumVolume,
  kalshiMarkets,
  polymarketMarkets,
  signalKind,
  maxAgeHours,
  countryCode,
  countryLabel,
  countryScope,
  watchlist,
  watchedOnly,
  alertsEnabled,
  alertPermission,
  onCountryScopeChange,
  onMinimumScoreChange,
  onMinimumVolumeChange,
  onSignalKindChange,
  onMaxAgeHoursChange,
  onWatchedOnlyChange,
  onAlertsEnabledChange,
  onToggleWatch,
  onSelect
}: AbnormalActivityFeedProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const rankedSignals = useMemo(
    () => {
      const ranked = rankRegionSignals(
        filterWatchedRegions(regions, watchlist, watchedOnly),
        signals,
        {
          minimumScore: 0,
          signalKind,
          maxAgeHours
        }
      ).map((item) => ({
        ...item,
        volume: getRegionMarketVolume(
          item.region,
          kalshiMarkets,
          polymarketMarkets
        )
      }));

      return ranked
        .filter(
          ({ region, signal, volume }) =>
            qualifiesBySignal(region, signal.score, minimumScore) ||
            qualifiesByVolume(region, volume, minimumVolume)
        )
        .sort((left, right) => {
          const leftHasSignal = qualifiesBySignal(
            left.region,
            left.signal.score,
            minimumScore
          );
          const rightHasSignal = qualifiesBySignal(
            right.region,
            right.signal.score,
            minimumScore
          );
          if (leftHasSignal !== rightHasSignal) {
            return leftHasSignal ? -1 : 1;
          }
          if (leftHasSignal) {
            return right.signal.score - left.signal.score;
          }
          return (right.volume ?? 0) - (left.volume ?? 0);
        });
    },
    [
      countryCode,
      kalshiMarkets,
      polymarketMarkets,
      maxAgeHours,
      minimumScore,
      minimumVolume,
      regions,
      signalKind,
      signals,
      watchedOnly,
      watchlist
    ]
  );
  const pageCount = Math.ceil(
    rankedSignals.length / ACTIVITY_FEED_PAGE_SIZE
  );
  const safePage = Math.min(Math.max(1, currentPage), Math.max(1, pageCount));
  const pageStart = (safePage - 1) * ACTIVITY_FEED_PAGE_SIZE;
  const pagedSignals = rankedSignals.slice(
    pageStart,
    pageStart + ACTIVITY_FEED_PAGE_SIZE
  );
  const paginationItems = getPaginationItems(safePage, pageCount);

  useEffect(() => {
    setCurrentPage(1);
  }, [
    countryCode,
    countryScope,
    maxAgeHours,
    minimumScore,
    minimumVolume,
    regions,
    signalKind,
    watchedOnly,
    watchlist
  ]);

  useEffect(() => {
    if (pageCount > 0 && currentPage > pageCount) {
      setCurrentPage(pageCount);
    }
  }, [currentPage, pageCount]);

  return (
    <section className="pt-2" aria-labelledby="activity-feed-title">
      <div>
        <div>
          <p className="metric-label">Signal Scanner</p>
          <h3 id="activity-feed-title" className="mt-1 text-lg font-semibold text-slate-900">
            Abnormal activity
          </h3>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
            Scope
          </p>
          <div
            className="flex divide-x divide-slate-200 overflow-hidden rounded-md border border-slate-200"
            role="group"
            aria-label="Signal country scope"
          >
            {([
              ["global", "All countries"],
              ["country", countryLabel]
            ] satisfies Array<[ActivityCountryScope, string]>).map(([scope, label]) => {
              const isActive = countryScope === scope;
              return (
                <button
                  key={scope}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => onCountryScopeChange(scope)}
                  className={`px-3 py-1.5 text-xs font-medium transition ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
            Volume
          </p>
          <div
            className="flex divide-x divide-slate-200 overflow-hidden rounded-md border border-slate-200"
            role="group"
            aria-label="Minimum market volume"
          >
            {VOLUME_THRESHOLDS.map((threshold) => {
              const isActive = threshold.value === minimumVolume;
              return (
                <button
                  key={threshold.value}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => onMinimumVolumeChange(threshold.value)}
                  className={`min-w-12 px-3 py-1.5 text-xs font-medium transition ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  {threshold.label}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
            Score
          </p>
          <div
            className="flex divide-x divide-slate-200 overflow-hidden rounded-md border border-slate-200"
            role="group"
            aria-label="Minimum activity score"
          >
            {THRESHOLDS.map((threshold) => {
              const isActive = threshold.value === minimumScore;
              return (
                <button
                  key={threshold.value}
                  type="button"
                  aria-pressed={isActive}
                  onClick={() => onMinimumScoreChange(threshold.value)}
                  className={`min-w-12 px-3 py-1.5 text-xs font-medium transition ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  {threshold.label}
                </button>
              );
            })}
          </div>
        </div>
        <label className="grid gap-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
          Signal
          <select
            value={signalKind}
            onChange={(event) => onSignalKindChange(event.target.value as ActivitySignalFilter)}
            className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium normal-case tracking-normal text-slate-700"
          >
            {SIGNAL_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
          Window
          <select
            value={maxAgeHours}
            onChange={(event) => onMaxAgeHoursChange(Number(event.target.value) as ActivityTimeWindow)}
            className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs font-medium normal-case tracking-normal text-slate-700"
          >
            {TIME_WINDOWS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-h-8 items-center gap-2 text-xs font-medium text-slate-700">
          <input
            type="checkbox"
            checked={watchedOnly}
            onChange={(event) => onWatchedOnlyChange(event.target.checked)}
            className="h-4 w-4 accent-slate-900"
          />
          Watched only
        </label>
        <label className="flex min-h-8 items-center gap-2 text-xs font-medium text-slate-700">
          <input
            type="checkbox"
            checked={alertsEnabled}
            disabled={alertPermission === "denied" || alertPermission === "unsupported"}
            onChange={(event) => onAlertsEnabledChange(event.target.checked)}
            className="h-4 w-4 accent-slate-900 disabled:opacity-50"
          />
          Browser alerts
        </label>
        {alertPermission === "denied" || alertPermission === "unsupported" ? (
          <span className="pb-2 text-xs text-slate-400">
            {alertPermission === "denied" ? "Permission denied" : "Not supported"}
          </span>
        ) : null}
      </div>

      <div className="mt-4">
        <div className="hidden grid-cols-[42px_72px_minmax(0,1fr)_82px_86px_52px_44px] gap-3 border-b border-[var(--demo-card-divider)] px-2 py-2 text-[10px] uppercase tracking-[0.18em] text-slate-400 sm:grid">
          <span>Rank</span>
          <span>Region</span>
          <span>Signal</span>
          <span>24h volume</span>
          <span>Updated</span>
          <span className="text-right">Score</span>
          <span className="text-center">Watch</span>
        </div>

        {pagedSignals.length ? (
          <div className="divide-y divide-[var(--demo-card-divider)]">
            {pagedSignals.map(({ region, signal, volume }, index) => {
              const isSelected =
                region.countryCode === countryCode && region.code === selectedCode;
              const watched = watchlist.includes(`${region.countryCode}:${region.code}`);
              return (
                <div
                  key={`${region.countryCode}:${region.code}`}
                  className={`flex items-stretch transition ${
                    isSelected ? "bg-slate-50" : "hover:bg-slate-50"
                  }`}
                >
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelect(region)}
                    className="grid min-w-0 flex-1 grid-cols-[52px_minmax(0,1fr)_44px] items-center gap-3 px-2 py-3 text-left sm:grid-cols-[42px_72px_minmax(0,1fr)_82px_86px_52px]"
                  >
                    <span className="hidden text-xs tabular-nums text-slate-400 sm:block">
                      {String(pageStart + index + 1).padStart(2, "0")}
                    </span>
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{
                          backgroundColor: qualifiesBySignal(
                            region,
                            signal.score,
                            minimumScore
                          )
                            ? getMarketSignalColor(signal.score)
                            : KALSHI_VOLUME_COLOR
                        }}
                      />
                      {region.code}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-900">{signal.headline}</span>
                      <span className="mt-0.5 block text-xs text-slate-500">
                        {getMarketSignalLabel(signal)}
                        {volume !== null
                          ? ` · ${formatMarketVolume(volume)} 24h`
                          : ""}
                      </span>
                    </span>
                    <span className="hidden text-xs font-medium tabular-nums text-slate-700 sm:block">
                      {formatMarketVolume(volume)}
                    </span>
                    <span className="hidden text-xs text-slate-500 sm:block">
                      {relativeTime(signal.observedAt)}
                    </span>
                    <span className="text-right text-xl font-semibold tabular-nums text-slate-900">
                      {signal.score}
                    </span>
                  </button>
                  <label className="flex w-11 shrink-0 cursor-pointer items-center justify-center">
                    <span className="sr-only">Watch {region.label}</span>
                    <input
                      type="checkbox"
                      checked={watched}
                      onChange={() => onToggleWatch(region.countryCode, region.code)}
                      className="h-4 w-4 accent-slate-900"
                    />
                  </label>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="px-2 py-6 text-sm text-slate-500">
            No regions match the current filters.
          </p>
        )}

        {rankedSignals.length ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--demo-card-divider)] px-2 pt-3 font-sans">
            <p className="text-xs tabular-nums text-slate-500">
              {pageStart + 1}–{Math.min(pageStart + ACTIVITY_FEED_PAGE_SIZE, rankedSignals.length)} of{" "}
              {rankedSignals.length}
            </p>
            {pageCount > 1 ? (
              <nav
                aria-label="Activity ranking pages"
                className="flex items-center gap-1"
              >
                <button
                  type="button"
                  title="Previous page"
                  aria-label="Previous activity page"
                  disabled={safePage === 1}
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  className="grid h-8 w-8 place-items-center border border-slate-200 bg-white text-base text-slate-700 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  ‹
                </button>
                {paginationItems.map((item, index) =>
                  item === "ellipsis" ? (
                    <span
                      key={`ellipsis-${index}`}
                      className="grid h-8 w-6 place-items-center text-xs text-slate-400"
                    >
                      …
                    </span>
                  ) : (
                    <button
                      key={item}
                      type="button"
                      aria-label={`Activity page ${item}`}
                      aria-current={item === safePage ? "page" : undefined}
                      onClick={() => setCurrentPage(item)}
                      className={`grid h-8 min-w-8 place-items-center border px-2 text-xs font-semibold ${
                        item === safePage
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"
                      }`}
                    >
                      {item}
                    </button>
                  )
                )}
                <button
                  type="button"
                  title="Next page"
                  aria-label="Next activity page"
                  disabled={safePage === pageCount}
                  onClick={() =>
                    setCurrentPage((page) => Math.min(pageCount, page + 1))
                  }
                  className="grid h-8 w-8 place-items-center border border-slate-200 bg-white text-base text-slate-700 disabled:cursor-not-allowed disabled:opacity-35"
                >
                  ›
                </button>
              </nav>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
