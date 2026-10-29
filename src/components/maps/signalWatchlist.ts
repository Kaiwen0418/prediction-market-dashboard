import type { MarketSignalSource } from "@/types/signals";

export const SIGNAL_WATCHLIST_STORAGE_KEY = "pmi.signal-watchlist.v1";
export const SIGNAL_ALERTS_STORAGE_KEY = "pmi.signal-alerts.v1";

const WATCH_KEY_PATTERN = /^[A-Z]{2,3}:[A-Z0-9-]{2,8}$/;

export type SignalAlertSnapshot = {
  countryCode: string;
  regionCode: string;
  regionLabel: string;
  pairLabel: string;
  headline: string;
  score: number;
  observedAt: string;
  source: MarketSignalSource;
};

export type StoredSignalSnapshot = Pick<SignalAlertSnapshot, "score" | "observedAt">;

export function getSignalWatchKey(countryCode: string, regionCode: string) {
  return `${countryCode.toUpperCase()}:${regionCode.toUpperCase()}`;
}

export function parseSignalWatchlist(value: string | null): string[] {
  if (!value) {
    return [];
  }

  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return Array.from(
      new Set(
        parsed.filter(
          (item): item is string =>
            typeof item === "string" && WATCH_KEY_PATTERN.test(item)
        )
      )
    ).sort();
  } catch {
    return [];
  }
}

export function filterWatchedRegions<T extends { code: string; countryCode: string }>(
  regions: T[],
  watchlist: string[],
  watchedOnly: boolean
) {
  if (!watchedOnly) {
    return regions;
  }

  const watched = new Set(watchlist);
  return regions.filter((region) =>
    watched.has(getSignalWatchKey(region.countryCode, region.code))
  );
}

export function getSignalAlertCandidates(
  current: SignalAlertSnapshot[],
  previous: ReadonlyMap<string, StoredSignalSnapshot>,
  watchlist: string[]
) {
  const watched = new Set(watchlist);

  return current.filter((signal) => {
    const key = getSignalWatchKey(signal.countryCode, signal.regionCode);
    const prior = previous.get(key);

    if (
      signal.source !== "live" ||
      !watched.has(key) ||
      !prior ||
      prior.observedAt === signal.observedAt ||
      signal.score < 70
    ) {
      return false;
    }

    return prior.score < 70 || signal.score - prior.score >= 10;
  });
}

export function toStoredSignalSnapshots(signals: SignalAlertSnapshot[]) {
  return new Map<string, StoredSignalSnapshot>(
    signals.map((signal) => [
      getSignalWatchKey(signal.countryCode, signal.regionCode),
      {
        score: signal.score,
        observedAt: signal.observedAt
      }
    ])
  );
}
