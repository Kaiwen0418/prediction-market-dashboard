import { getAnalyticsSummary } from "@/services/analytics/api";
import { getExternalApiBaseUrl, withApiBase } from "@/services/api/base";
import type { CorrelationResult, EventWindowResult, LeadLagResult, RollingCorrelationResult, VolatilityResult } from "@/types/analytics";
import type { PollPoint } from "@/types/poll";
import type { TimePoint } from "@/types/market";
import { useDataSourceStore } from "@/stores/dataSourceStore";

type StatePartySupportDataset = {
  generatedAt: string;
  sourceUrl: string;
  description: string;
  states: Array<{
    state: string;
    series: Array<{
      date: string;
      democrat?: number;
      republican?: number;
    }>;
  }>;
};

type StaticPolymarketHistoryDataset = {
  generatedAt: string;
  sourceUrls: {
    gamma: string;
    clob: string;
  };
  description: string;
  states: Array<{
    state: string;
    eventSlug: string;
    parties: {
      Republican: {
        marketId: string;
        tokenId: string;
        title: string;
        outcomeLabel?: string;
        contractLabel?: string;
        series: TimePoint[];
      } | null;
      Democrat: {
        marketId: string;
        tokenId: string;
        title: string;
        outcomeLabel?: string;
        contractLabel?: string;
        series: TimePoint[];
      } | null;
    };
  }>;
};

export type LiveHistoryCase = {
  state: string;
  eventSlug: string;
  party: "Democrat" | "Republican";
  summary: string;
  analyticsSource: "api" | "local";
  researchSource: "api" | "local";
  marketSeries: TimePoint[];
  pollSeries: PollPoint[];
  leadLag: LeadLagResult;
  correlation: CorrelationResult;
  volatility: VolatilityResult;
  divergence: {
    averageGap: number;
    maxGap: number;
    currentGap: number;
  };
  rollingCorrelation: RollingCorrelationResult;
  eventWindow: EventWindowResult;
  provenance?: {
    computedAt: string;
    pollDatasetGeneratedAt?: string | null;
    marketDatasetGeneratedAt?: string | null;
  };
  coverage?: {
    pollStart?: string | null;
    pollEnd?: string | null;
    pollPoints: number;
    marketStart?: string | null;
    marketEnd?: string | null;
    marketPoints: number;
    alignedStart?: string | null;
    alignedEnd?: string | null;
    alignedPoints: number;
  };
  narrative?: {
    overview: string;
    methodology: string;
  };
  researchHighlights?: {
    shockLabel: string;
    leadLagLabel: string;
    divergenceLabel: string;
  };
  relatedMarketDivergence?: {
    primary: {
      label: string;
      probability: number;
      observedAt: string;
      sourceUrl: string;
    };
    related: {
      label: string;
      probability: number;
      observedAt: string;
      sourceUrl: string;
    };
    rawProbabilitySum: number;
    rawGapPoints: number;
    feeBpsPerLeg: number;
    feeBufferPoints: number;
    actionableGapPoints: number;
    liquidityUsd?: number | null;
    minimumLiquidityUsd: number;
    status: string;
    explanation: string;
  };
  electionModelComparison?: {
    modelName: string;
    modelProbability: number;
    marketProbability: number;
    divergencePoints: number;
    pollObservedAt: string;
    marketObservedAt: string;
    sourceUrl: string;
    methodology: string;
  };
  catalysts?: Array<{
    id: string;
    headline: string;
    eventType: string;
    occurredAt: string;
    sourceName: string;
    sourceUrl: string;
    matchedMarketTimestamp: string;
    marketMove: number;
    summary: string;
  }>;
  sourceUrls: string[];
};

export type LiveHistoryOverviewItem = {
  state: string;
  eventSlug: string;
  party: "Democrat" | "Republican";
  leadLagDays: number;
  correlation: number;
  divergence: number;
  volatility: number;
  alignedPoints: number;
};

export type LiveHistoryOverview = {
  party: "Democrat" | "Republican";
  computedAt: string;
  source: "api";
  items: LiveHistoryOverviewItem[];
};

const STATE_SUPPORT_PUBLIC_URL = "/data/state-party-support-2024.json";
const POLYMARKET_HISTORY_PUBLIC_URL = "/data/polymarket-history-2024.json";

const stateRegistry = [
  {
    state: "Arizona",
    eventSlug: "arizona-presidential-election-winner",
    pollStateCode: "Arizona",
    pollLabel: "Republican"
  },
  {
    state: "Georgia",
    eventSlug: "georgia-presidential-election-winner",
    pollStateCode: "Georgia",
    pollLabel: "Republican"
  },
  {
    state: "Michigan",
    eventSlug: "michigan-presidential-election-winner",
    pollStateCode: "Michigan",
    pollLabel: "Republican"
  },
  {
    state: "Pennsylvania",
    eventSlug: "pennsylvania-presidential-election-winner",
    pollStateCode: "Pennsylvania",
    pollLabel: "Republican"
  },
  {
    state: "Wisconsin",
    eventSlug: "wisconsin-presidential-election-winner",
    pollStateCode: "Wisconsin",
    pollLabel: "Republican"
  }
] as const;

function normalizePollJson(
  dataset: StatePartySupportDataset,
  state: string,
  party: "Democrat" | "Republican"
): PollPoint[] {
  const stateData = dataset.states.find((entry) => entry.state === state);
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

async function fetchPollDataset() {
  const response = await fetch(STATE_SUPPORT_PUBLIC_URL, {
    headers: {
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    throw new Error(`Polling JSON request failed: ${response.status}`);
  }

  return (await response.json()) as StatePartySupportDataset;
}

function historySourceKey(state: string, party: "Democrat" | "Republican") {
  return `history:${state}:${party}`;
}

function historyBackendSourceKey(state: string, party: "Democrat" | "Republican") {
  return `history-backend:${state}:${party}`;
}

function describeRange(series: Array<{ timestamp: string }>) {
  if (!series.length) return "none";
  return `${series[0].timestamp} -> ${series.at(-1)?.timestamp ?? series[0].timestamp}`;
}

function toDateKey(timestamp: string) {
  return timestamp.slice(0, 10);
}

function getCoverage(pollSeries: PollPoint[], marketSeries: TimePoint[]) {
  const marketDays = new Set(marketSeries.map((point) => toDateKey(point.timestamp)));
  const alignedDays = Array.from(
    new Set(pollSeries.map((point) => toDateKey(point.timestamp)).filter((day) => marketDays.has(day)))
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

async function fetchPolymarketHistoryDataset() {
  const response = await fetch(POLYMARKET_HISTORY_PUBLIC_URL, {
    headers: {
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    throw new Error(`Polymarket history JSON request failed: ${response.status}`);
  }

  return (await response.json()) as StaticPolymarketHistoryDataset;
}

async function fetchBackendResearchSummary(state: string, party: "Democrat" | "Republican"): Promise<LiveHistoryCase> {
  const response = await fetch(
    withApiBase(`/api/research/states/${encodeURIComponent(state)}/summary?party=${encodeURIComponent(party)}`),
    {
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    throw new Error(`Research summary request failed: ${response.status}`);
  }

  const payload = (await response.json()) as LiveHistoryCase;
  return payload;
}

async function fetchBackendResearchOverview(
  party: "Democrat" | "Republican",
): Promise<LiveHistoryOverview> {
  const response = await fetch(
    withApiBase(`/api/research/states/overview?party=${encodeURIComponent(party)}`),
    {
      headers: {
        Accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    throw new Error(`Research overview request failed: ${response.status}`);
  }

  return (await response.json()) as LiveHistoryOverview;
}

async function getLiveHistoryCasesFromBackend(
  party: "Democrat" | "Republican" = "Republican",
): Promise<LiveHistoryCase[]> {
  const cases = await Promise.all(
    stateRegistry.map(async (stateCase) => {
      useDataSourceStore.getState().markPending(historyBackendSourceKey(stateCase.state, party));
      useDataSourceStore.getState().markPending(historySourceKey(stateCase.state, party));
      const result = await fetchBackendResearchSummary(stateCase.state, party);
      useDataSourceStore.getState().markLive(historyBackendSourceKey(stateCase.state, party));
      useDataSourceStore.getState().markCurated(historySourceKey(stateCase.state, party));
      return result;
    }),
  );

  return cases;
}

async function getLiveHistoryCasesLocal(
  party: "Democrat" | "Republican" = "Republican",
): Promise<LiveHistoryCase[]> {
  let dataset: StatePartySupportDataset | null = null;
  let polymarketHistoryDataset: StaticPolymarketHistoryDataset | null = null;
  try {
    [dataset, polymarketHistoryDataset] = await Promise.all([
      fetchPollDataset(),
      fetchPolymarketHistoryDataset()
    ]);
  } catch {
    stateRegistry.forEach((stateCase) => {
      useDataSourceStore.getState().markFallback(historySourceKey(stateCase.state, party), {
        stage: "reachability",
        message: "Failed to fetch cleaned public polling or Polymarket history dataset"
      });
    });
    return [];
  }

  const cases = await Promise.all(
    stateRegistry.map(async (stateCase) => {
      useDataSourceStore.getState().markPending(historySourceKey(stateCase.state, party));

      const pollSeries = normalizePollJson(dataset, stateCase.pollStateCode, party);
      const stateHistory = polymarketHistoryDataset.states.find((entry) => entry.state === stateCase.state) ?? null;
      const market = stateHistory?.parties[party] ?? null;
      const marketSeries = market?.series ?? [];
      const pollRange = describeRange(pollSeries);
      const marketRange = describeRange(marketSeries);

      console.info("[history]", {
        state: stateCase.state,
        party,
        eventSlug: stateCase.eventSlug,
        matchedOutcome: market?.outcomeLabel ?? null,
        matchedContract: market?.contractLabel ?? null,
        marketId: market?.marketId ?? null,
        tokenId: market?.tokenId ?? null,
        pollPoints: pollSeries.length,
        pollRange,
        marketPoints: marketSeries.length,
        marketRange,
        staticHistoryGeneratedAt: polymarketHistoryDataset.generatedAt
      });

      if (pollSeries.length > 1 && marketSeries.length > 1) {
        useDataSourceStore.getState().markCurated(historySourceKey(stateCase.state, party));
      } else {
        const detailedMessage =
          pollSeries.length <= 1
            ? `Public cleaned polling dataset did not have enough usable rows. party=${party}, pollPoints=${pollSeries.length}, pollRange=${pollRange}`
            : `Static Polymarket history dataset did not have enough points for the matched event outcome. party=${party}, outcome=${market?.outcomeLabel ?? "unknown"}, contract=${market?.contractLabel ?? "unknown"}, marketId=${market?.marketId ?? "unknown"}, token=${market?.tokenId ?? "unknown"}, marketPoints=${marketSeries.length}, marketRange=${marketRange}`;
        useDataSourceStore.getState().markFallback(historySourceKey(stateCase.state, party), {
          stage: "normalization",
          message: detailedMessage
        });
      }

      const analytics = await getAnalyticsSummary(marketSeries, pollSeries);
      const coverage = getCoverage(pollSeries, marketSeries);

      return {
        state: stateCase.state,
        eventSlug: stateCase.eventSlug,
        party,
        summary: `FiveThirtyEight ${party} state support compared with Polymarket history for ${stateCase.state}, including lead-lag, correlation, and volatility analysis.`,
        analyticsSource: analytics.source,
        researchSource: "local" as const,
        marketSeries,
        pollSeries,
        leadLag: analytics.summary.leadLag,
        correlation: analytics.summary.correlation,
        volatility: analytics.summary.volatility,
        divergence: analytics.summary.divergence,
        rollingCorrelation: analytics.summary.rollingCorrelation,
        eventWindow: analytics.summary.eventWindow,
        provenance: {
          computedAt: new Date().toISOString(),
          pollDatasetGeneratedAt: dataset.generatedAt,
          marketDatasetGeneratedAt: polymarketHistoryDataset.generatedAt
        },
        coverage,
        narrative: {
          overview: `${stateCase.state} ${party.toLowerCase()} support is evaluated across ${coverage.alignedPoints} aligned daily observations from the cached frontend datasets.`,
          methodology:
            "Poll and market series are aligned by date before lead-lag, volatility, event-window, and divergence measures are calculated."
        },
        researchHighlights: {
          shockLabel: `Primary shock window moved ${analytics.summary.eventWindow.netMove >= 0 ? "+" : ""}${analytics.summary.eventWindow.netMove} pts around ${analytics.summary.eventWindow.anchorTimestamp.slice(0, 10)}`,
          leadLagLabel: analytics.summary.leadLag.interpretation,
          divergenceLabel: `Current market-poll divergence is ${analytics.summary.divergence.currentGap.toFixed(2)} pts (max ${analytics.summary.divergence.maxGap.toFixed(2)} pts)`
        },
        sourceUrls: [
          STATE_SUPPORT_PUBLIC_URL,
          POLYMARKET_HISTORY_PUBLIC_URL
        ]
      };
    })
  );

  return cases.filter((item) => item.marketSeries.length > 1 && item.pollSeries.length > 1);
}

export async function getLiveHistoryCases(party: "Democrat" | "Republican" = "Republican"): Promise<LiveHistoryCase[]> {
  if (getExternalApiBaseUrl()) {
    try {
      return await getLiveHistoryCasesFromBackend(party);
    } catch {
      stateRegistry.forEach((stateCase) => {
        useDataSourceStore.getState().markFallback(historyBackendSourceKey(stateCase.state, party), {
          stage: "reachability",
          message: "FastAPI research summary route was unavailable; backend-owned research bundle could not be loaded",
        });
        useDataSourceStore.getState().markFallback(historySourceKey(stateCase.state, party), {
          stage: "reachability",
          message: "FastAPI research summary route was unavailable; reverted to local history assembly",
        });
      });
    }
  }

  return getLiveHistoryCasesLocal(party);
}

export async function getLiveHistoryOverview(
  party: "Democrat" | "Republican" = "Republican",
): Promise<LiveHistoryOverview | null> {
  if (!getExternalApiBaseUrl()) {
    return null;
  }

  try {
    useDataSourceStore.getState().markPending(`history-overview-backend:${party}`);
    const overview = await fetchBackendResearchOverview(party);
    useDataSourceStore.getState().markLive(`history-overview-backend:${party}`);
    return overview;
  } catch {
    useDataSourceStore.getState().markFallback(`history-overview-backend:${party}`, {
      stage: "reachability",
      message: "FastAPI research overview route was unavailable; reverted to per-state frontend aggregation",
    });
    return null;
  }
}
