"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { DivergenceGapChart } from "@/components/charts/DivergenceGapChart";
import { EventWindowBarChart } from "@/components/charts/EventWindowBarChart";
import { MarketPollChart } from "@/components/charts/MarketPollChart";
import { RollingCorrelationChart } from "@/components/charts/RollingCorrelationChart";
import { RollingVolatilityChart } from "@/components/charts/RollingVolatilityChart";
import { ShockWindowBarChart } from "@/components/charts/ShockWindowBarChart";
import { StateMetricSmallMultiples } from "@/components/charts/StateMetricSmallMultiples";
import { StateSignalMatrix } from "@/components/charts/StateSignalMatrix";
import { LoadingState } from "@/components/layout/LoadingState";
import { OperationalNotice } from "@/components/layout/OperationalNotice";
import { ProductDemoShell } from "@/components/layout/ProductDemoShell";
import { getShockWindows } from "@/services/analytics/api";
import {
  getLiveHistoryCases,
  getLiveHistoryOverview,
  type LiveHistoryCase
} from "@/services/history/liveHistory";
import supportDataset from "@/../public/data/state-party-support-2024.json";
import { researchCases, researchDataSources } from "@/services/history/researchStatic";

type Party = "Democrat" | "Republican";

function buildPollSeries(state: string, party: Party) {
  const stateData = supportDataset.states.find((entry) => entry.state === state);
  if (!stateData) return [];

  return stateData.series.flatMap((point) => {
    const support = party === "Republican" ? point.republican : point.democrat;
    if (typeof support !== "number") {
      return [];
    }

    return {
      timestamp: new Date(point.date).toISOString(),
      pollAverage: support,
      sampleSize: 0,
      source: "FiveThirtyEight cleaned public dataset",
      sourceUrl: "https://github.com/kevin-claw-agent/poll-data",
      fieldDateLabel: point.date,
      methodology: "Daily mean across all available 538 poll rows for the same state, date, and party",
      candidate: party
    };
  });
}

function buildCoverage(
  pollSeries: Array<{ timestamp: string }>,
  marketSeries: Array<{ timestamp: string }>
) {
  const marketDays = new Set(marketSeries.map((point) => point.timestamp.slice(0, 10)));
  const alignedDays = Array.from(
    new Set(pollSeries.map((point) => point.timestamp.slice(0, 10)).filter((day) => marketDays.has(day)))
  ).sort((left, right) => left.localeCompare(right));

  return {
    pollStart: pollSeries[0]?.timestamp.slice(0, 10),
    pollEnd: pollSeries.at(-1)?.timestamp.slice(0, 10),
    pollPoints: pollSeries.length,
    marketStart: marketSeries[0]?.timestamp.slice(0, 10),
    marketEnd: marketSeries.at(-1)?.timestamp.slice(0, 10),
    marketPoints: marketSeries.length,
    alignedStart: alignedDays[0],
    alignedEnd: alignedDays.at(-1),
    alignedPoints: alignedDays.length
  };
}

export function HistoryPageView() {
  const [party, setParty] = useState<Party>("Republican");
  const liveHistoryQuery = useQuery({
    queryKey: ["history-live-cases", party],
    queryFn: () => getLiveHistoryCases(party)
  });
  const overviewQuery = useQuery({
    queryKey: ["history-overview", party],
    queryFn: () => getLiveHistoryOverview(party)
  });

  const availableStates = ["Arizona", "Georgia", "Michigan", "Pennsylvania", "Wisconsin"];
  const [activeState, setActiveState] = useState(availableStates[0]);
  const liveCase = liveHistoryQuery.data?.find((item) => item.state === activeState) ?? null;
  const researchCase = researchCases.find((item) => item.state === activeState) ?? researchCases[0];
  const pollSeries = buildPollSeries(activeState, party);
  const fallbackCoverage = buildCoverage(pollSeries, researchCase.marketSeries);
  const activeCase: LiveHistoryCase = liveCase
    ? { ...liveCase, pollSeries }
    : {
        ...researchCase,
        eventSlug: `${activeState.toLowerCase()}-presidential-election-winner`,
        party,
        analyticsSource: "local" as const,
        researchSource: "local" as const,
        divergence: {
          averageGap: 0,
          maxGap: 0,
          currentGap: 0
        },
        pollSeries,
        rollingCorrelation: {
          coefficient: researchCase.correlation.coefficient,
          windowSize: Math.min(30, researchCase.marketSeries.length),
          points: []
        },
        eventWindow: {
          anchorIndex: Math.max(researchCase.marketSeries.length - 1, 0),
          anchorTimestamp: researchCase.marketSeries.at(-1)?.timestamp ?? "",
          preChange: 0,
          postChange: 0,
          netMove: 0,
          preWindow: 3,
          postWindow: 3
        },
        provenance: {
          computedAt: new Date().toISOString(),
          pollDatasetGeneratedAt: undefined,
          marketDatasetGeneratedAt: undefined
        },
        coverage: fallbackCoverage,
        narrative: {
          overview: `${activeState} ${party.toLowerCase()} support is compared with the latest available prediction-market history.`,
          methodology: "The comparison pairs cleaned public polling averages with the latest available market history."
        },
        researchHighlights: {
          shockLabel: "Shock-window analysis is currently unavailable.",
          leadLagLabel: researchCase.leadLag.interpretation,
          divergenceLabel: "Divergence analysis is currently unavailable."
        },
        summary: `${party} polling and prediction-market history for ${activeState}.`,
        sourceUrls: []
      };
  const pollingSources = Array.from(new Map(activeCase.pollSeries.map((point) => [point.source, point])).values());
  const usingLiveCases = Boolean(liveCase);
  const comparisonCases = overviewQuery.data?.items?.length
    ? overviewQuery.data.items
        .filter((item) => availableStates.includes(item.state))
        .map((item) => ({
          state: item.state,
          leadLagDays: item.leadLagDays,
          volatility: item.volatility,
          divergence: item.divergence,
          correlation: item.correlation,
        }))
    : (liveHistoryQuery.data ?? [])
        .filter((item) => availableStates.includes(item.state))
        .map((item) => ({
          state: item.state,
          leadLagDays: item.leadLag.lagDays,
          volatility: item.volatility.realizedVolatility,
          divergence: item.divergence.currentGap,
          correlation: item.correlation.coefficient,
        }));
  const shockWindowsQuery = useQuery({
    queryKey: ["history-shock-windows", activeCase.state, party, activeCase.marketSeries.length],
    queryFn: () => getShockWindows(activeCase.marketSeries, 7, 3),
    enabled: activeCase.marketSeries.length >= 2
  });

  useEffect(() => {
    if (!availableStates.includes(activeState)) {
      setActiveState(availableStates[0]);
    }
  }, [activeState]);

  if (liveHistoryQuery.isLoading && !liveHistoryQuery.data) {
    return <LoadingState label="Loading FiveThirtyEight polling averages and matching Polymarket state market histories..." />;
  }

  return (
    <ProductDemoShell
      brand="Prediction Market Intelligence"
      context="Research · Polling and market history"
      title="Research"
      showHero={false}
    >
      <div className="mx-auto flex max-w-7xl flex-col gap-8">
        <section>
          <p className="metric-label">Historical Analysis</p>
          <h2 className="mt-2 text-3xl font-semibold text-slate-900">Research-style market vs polling comparison</h2>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
            {activeCase.narrative?.overview}
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <a
              href={researchDataSources.paper}
              target="_blank"
              rel="noreferrer"
              className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
            >
              Paper source
            </a>
            <a
              href={researchDataSources.polymarket}
              target="_blank"
              rel="noreferrer"
              className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
            >
              Prediction market source
            </a>
            <a
              href={researchDataSources.fivethirtyeight}
              target="_blank"
              rel="noreferrer"
              className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700"
            >
              Polling aggregate reference
            </a>
          </div>
          {!usingLiveCases ? (
            <div className="mt-5 max-w-2xl">
              <OperationalNotice
                tone="warning"
                title="Showing the latest available research data"
                detail="The newest comparison is temporarily unavailable. Dates and coverage are shown below."
              />
            </div>
          ) : null}
          {activeCase.coverage ? (
            <p className="mt-2 text-sm text-slate-500">
              Coverage: polls {activeCase.coverage.pollStart ?? "unknown"} to {activeCase.coverage.pollEnd ?? "unknown"} ({activeCase.coverage.pollPoints} points)
              {" · "}
              market {activeCase.coverage.marketStart ?? "unknown"} to {activeCase.coverage.marketEnd ?? "unknown"} ({activeCase.coverage.marketPoints} points)
              {" · "}
              aligned {activeCase.coverage.alignedPoints} days
            </p>
          ) : null}
        </section>

        {activeCase.relatedMarketDivergence || activeCase.catalysts?.length ? (
          <section className="border-t border-[var(--demo-card-divider)] pt-8">
            <p className="metric-label">Political Catalyst Intelligence</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">
              Related markets and source-linked events
            </h2>

            {activeCase.relatedMarketDivergence ? (
              <div className="mt-6 grid gap-6 border-y border-[var(--demo-card-divider)] py-5 lg:grid-cols-[1fr_1fr_1.2fr]">
                {[activeCase.relatedMarketDivergence.primary, activeCase.relatedMarketDivergence.related].map(
                  (comparison) => (
                    <div key={comparison.label}>
                      <p className="metric-label">{comparison.label} outcome</p>
                      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
                        {(comparison.probability * 100).toFixed(1)}%
                      </p>
                      <a
                        href={comparison.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-2 block text-xs text-slate-500 hover:text-slate-900"
                      >
                        Observed {comparison.observedAt.slice(0, 10)} ↗
                      </a>
                    </div>
                  )
                )}
                <div>
                  <p className="metric-label">Consistency check</p>
                  <p className="mt-2 text-lg font-semibold text-slate-900">
                    {activeCase.relatedMarketDivergence.rawGapPoints.toFixed(2)} pts raw gap
                  </p>
                  <p className="mt-2 text-sm leading-6 text-slate-600">
                    {activeCase.relatedMarketDivergence.feeBpsPerLeg.toFixed(0)} bps per leg ·{" "}
                    {activeCase.relatedMarketDivergence.actionableGapPoints.toFixed(2)} pts after fees · liquidity{" "}
                    {activeCase.relatedMarketDivergence.liquidityUsd === null ||
                    activeCase.relatedMarketDivergence.liquidityUsd === undefined
                      ? "unverified"
                      : `$${activeCase.relatedMarketDivergence.liquidityUsd.toLocaleString()}`}
                  </p>
                  <p className="mt-2 text-xs leading-5 text-slate-500">
                    {activeCase.relatedMarketDivergence.explanation}
                  </p>
                  {activeCase.electionModelComparison ? (
                    <div className="mt-3 border-t border-[var(--demo-card-divider)] pt-3">
                      <p className="text-sm font-semibold text-slate-900">
                        Model {(activeCase.electionModelComparison.modelProbability * 100).toFixed(1)}% · market-model gap{" "}
                        {activeCase.electionModelComparison.divergencePoints >= 0 ? "+" : ""}
                        {activeCase.electionModelComparison.divergencePoints.toFixed(2)} pts
                      </p>
                      <a
                        href={activeCase.electionModelComparison.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 block text-xs text-slate-500 hover:text-slate-900"
                      >
                        {activeCase.electionModelComparison.modelName} · poll{" "}
                        {activeCase.electionModelComparison.pollObservedAt.slice(0, 10)} · market{" "}
                        {activeCase.electionModelComparison.marketObservedAt.slice(0, 10)} ↗
                      </a>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        {activeCase.electionModelComparison.methodology}
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {activeCase.catalysts?.length ? (
              <div className="mt-6 divide-y divide-[var(--demo-card-divider)]">
                {activeCase.catalysts.map((catalyst) => (
                  <div
                    key={catalyst.id}
                    className="grid gap-2 py-4 md:grid-cols-[150px_minmax(0,1fr)_120px]"
                  >
                    <div>
                      <p className="text-xs font-medium uppercase text-slate-500">{catalyst.eventType}</p>
                      <p className="mt-1 text-xs text-slate-400">{catalyst.occurredAt.slice(0, 10)}</p>
                    </div>
                    <div>
                      <a
                        href={catalyst.sourceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold text-slate-900 hover:underline"
                      >
                        {catalyst.headline} ↗
                      </a>
                      <p className="mt-1 text-sm leading-6 text-slate-600">{catalyst.summary}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        {catalyst.sourceName} · matched {catalyst.matchedMarketTimestamp.slice(0, 10)}
                      </p>
                    </div>
                    <p className="text-left text-lg font-semibold tabular-nums text-slate-900 md:text-right">
                      {catalyst.marketMove >= 0 ? "+" : ""}
                      {catalyst.marketMove.toFixed(2)} pts
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        ) : null}

        <section className="border-t border-[var(--demo-card-divider)] pt-8">
          <div className="flex flex-wrap items-center gap-3">
            {(["Republican", "Democrat"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setParty(option)}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                  option === party
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            {availableStates.map((state) => (
              <button
                key={state}
                type="button"
                onClick={() => setActiveState(state)}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                  state === activeState
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                }`}
              >
                {state}
              </button>
            ))}
          </div>
        </section>

        <section className="border-t border-[var(--demo-card-divider)] pt-8">
          <div>
            <p className="metric-label">Cross-State Parameters</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">Small multiples across battleground states</h2>
            <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-500">
              This panel compresses the current parameter state across all tracked states so the page reads like a research surface rather than a single-case report.
            </p>
            <div className="mt-6">
              <StateMetricSmallMultiples data={comparisonCases} />
            </div>
            <div className="mt-6">
              <p className="metric-label">State Signal Matrix</p>
              <p className="mt-2 max-w-4xl text-sm leading-7 text-slate-500">
                Heat-style matrix for the latest cross-state parameter snapshot. It compresses relative signal strength into a compact comparative surface.
              </p>
              <div className="mt-4">
                <StateSignalMatrix data={comparisonCases} />
              </div>
            </div>
          </div>
        </section>

        <section className="border-t border-[var(--demo-card-divider)] pt-8">
          <div>
            <p className="metric-label">Analytical Summary</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">Regime, repricing, and event response</h2>
            <p className="mt-3 max-w-4xl text-sm leading-7 text-slate-500">
              This section shifts the page away from isolated KPI figures and toward continuous analytical surfaces. The emphasis is on how alignment, volatility, and repricing evolve across the full market path.
            </p>
          </div>
          <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
            <div className="rounded-[28px] border border-slate-200 bg-slate-50/70 p-5">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="metric-label">Rolling Correlation Path</p>
                  <p className="mt-2 text-sm text-slate-500">
                    Trailing {activeCase.rollingCorrelation.windowSize}-day alignment after matching market and polling observations by date.
                  </p>
                </div>
                <p className="text-sm font-medium text-slate-700">{activeCase.rollingCorrelation.coefficient}</p>
              </div>
              <div className="mt-4">
                <RollingCorrelationChart rollingCorrelation={activeCase.rollingCorrelation} />
              </div>
            </div>
            <div className="rounded-[28px] border border-slate-200 bg-slate-50/70 p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="metric-label">Lead-Lag + Event Window</p>
                  <p className="mt-2 text-sm text-slate-500">
                    The lag offset gives the structural timing relationship; the event window shows how sharply the market repriced before and after the main shock.
                  </p>
                </div>
                <p className="text-sm font-medium text-slate-700">
                  {activeCase.leadLag.lagDays === 0 ? "Sync" : `${Math.abs(activeCase.leadLag.lagDays)}d`}
                </p>
              </div>
              <div className="mt-4">
                <EventWindowBarChart eventWindow={activeCase.eventWindow} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
                  <p className="metric-label">Lead-Lag Interpretation</p>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{activeCase.leadLag.interpretation}</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
                  <p className="metric-label">Window Geometry</p>
                  <p className="mt-2 text-sm leading-6 text-slate-700">
                    -{activeCase.eventWindow.preWindow} / +{activeCase.eventWindow.postWindow} around {activeCase.eventWindow.anchorTimestamp.slice(0, 10)}
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-8 grid gap-6 xl:grid-cols-2">
            <div className="rounded-[28px] border border-slate-200 bg-slate-50/70 p-5">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="metric-label">Rolling Volatility Path</p>
                  <p className="mt-2 text-sm text-slate-500">
                    Trailing market volatility regime. This reveals whether repricing is compressing or accelerating into event windows.
                  </p>
                </div>
                <p className="text-sm font-medium text-slate-700">{activeCase.volatility.realizedVolatility}%</p>
              </div>
              <div className="mt-4">
                <RollingVolatilityChart series={activeCase.marketSeries} />
              </div>
            </div>
            <div className="rounded-[28px] border border-slate-200 bg-slate-50/70 p-5">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="metric-label">Signed Divergence Path</p>
                  <p className="mt-2 text-sm text-slate-500">
                    Positive values mean the market prices the selected party above polling. Negative values mean PM is discounting the polling average.
                  </p>
                </div>
                <p className="text-sm font-medium text-slate-700">{activeCase.divergence.currentGap} pts</p>
              </div>
              <div className="mt-4">
                <DivergenceGapChart marketSeries={activeCase.marketSeries} pollSeries={activeCase.pollSeries} />
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
                  <p className="metric-label">Current</p>
                  <p className="mt-2 text-lg font-semibold text-slate-900">{activeCase.divergence.currentGap} pts</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
                  <p className="metric-label">Average</p>
                  <p className="mt-2 text-lg font-semibold text-slate-900">{activeCase.divergence.averageGap} pts</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3">
                  <p className="metric-label">Maximum</p>
                  <p className="mt-2 text-lg font-semibold text-slate-900">{activeCase.divergence.maxGap} pts</p>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
            <div className="rounded-[28px] border border-slate-200 bg-slate-50/70 p-5">
              <div>
                <div>
                  <p className="metric-label">Shock Windows</p>
                  <p className="mt-2 text-sm text-slate-500">
                    Largest {shockWindowsQuery.data?.summary.topK ?? 3} trailing {shockWindowsQuery.data?.summary.windowSize ?? 7}-day moves in the market path, ranked by absolute repricing and local volatility.
                  </p>
                </div>
              </div>
              <div className="mt-4">
                <ShockWindowBarChart windows={shockWindowsQuery.data?.summary.windows ?? []} />
              </div>
            </div>
            <div className="grid gap-3">
              {(shockWindowsQuery.data?.summary.windows ?? []).map((window, index) => (
                <div key={`${window.anchorTimestamp}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50/70 px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="metric-label">Window {index + 1}</p>
                      <p className="mt-2 text-lg font-semibold text-slate-900">
                        {window.netMove >= 0 ? "+" : ""}
                        {window.netMove} pts
                      </p>
                    </div>
                    <p className="text-xs uppercase tracking-[0.12em] text-slate-500">{window.startTimestamp.slice(5, 10)}</p>
                  </div>
                  <p className="mt-2 text-sm text-slate-500">
                    {window.startTimestamp.slice(0, 10)} to {window.endTimestamp.slice(0, 10)}
                  </p>
                  <p className="mt-2 text-sm text-slate-500">
                    Abs move {window.absoluteMove} pts · local vol {window.localVolatility}%
                  </p>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-5">
            <p className="metric-label">Research Finding</p>
            <p className="mt-3 text-xl font-semibold text-slate-900">{activeCase.state}</p>
            <p className="mt-2 max-w-4xl text-sm text-slate-500">{activeCase.summary}</p>
            {activeCase.researchHighlights ? (
              <div className="mt-4 grid gap-2 text-sm text-slate-600 md:grid-cols-3">
                <p>{activeCase.researchHighlights.shockLabel}</p>
                <p>{activeCase.researchHighlights.leadLagLabel}</p>
                <p>{activeCase.researchHighlights.divergenceLabel}</p>
              </div>
            ) : null}
            {activeCase.provenance ? (
              <p className="mt-3 text-xs uppercase tracking-[0.12em] text-slate-400">
                computed {new Date(activeCase.provenance.computedAt).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric"
                })}
              </p>
            ) : null}
          </div>
        </section>

        <section className="border-t border-[var(--demo-card-divider)] pt-8">
          <p className="metric-label">Time Series</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-900">
            {activeCase.state}: {party} support against PM contract path
          </h2>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-600">
            {pollingSources.map((point) => (
              <a
                key={`${point.source}-${point.timestamp}`}
                href={point.sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 hover:border-slate-300 hover:text-slate-900"
              >
                {point.source}
              </a>
            ))}
          </div>
          <p className="mt-4 text-sm leading-7 text-slate-500">
            {activeCase.narrative?.methodology}
          </p>
          {activeCase.provenance?.pollDatasetGeneratedAt || activeCase.provenance?.marketDatasetGeneratedAt ? (
            <p className="mt-3 text-xs text-slate-500">
              Data updated: polls {activeCase.provenance?.pollDatasetGeneratedAt ?? "unavailable"} · market {activeCase.provenance?.marketDatasetGeneratedAt ?? "unavailable"}
            </p>
          ) : null}
          <div className="mt-6">
            <MarketPollChart
              eventWindow={activeCase.eventWindow}
              marketSeries={activeCase.marketSeries}
              pollSeries={activeCase.pollSeries}
              shockWindows={shockWindowsQuery.data?.summary.windows ?? []}
            />
          </div>
        </section>
      </div>
    </ProductDemoShell>
  );
}
