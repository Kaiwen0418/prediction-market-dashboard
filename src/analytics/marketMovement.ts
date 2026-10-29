import type { TimePoint } from "@/types/market";

export type MarketMovementSummary = {
  oneHour: number | null;
  twentyFourHours: number | null;
  sevenDays: number | null;
};

function changeAtWindow(
  series: TimePoint[],
  currentValue: number,
  latestTimestamp: number,
  hours: number
) {
  const targetTimestamp = latestTimestamp - hours * 60 * 60 * 1000;
  const toleranceMs = Math.max(15 * 60 * 1000, hours * 0.2 * 60 * 60 * 1000);
  const baseline = series
    .map((point) => ({
      point,
      timestamp: new Date(point.timestamp).getTime()
    }))
    .filter(
      ({ timestamp }) =>
        Number.isFinite(timestamp) && timestamp < latestTimestamp
    )
    .sort(
      (left, right) =>
        Math.abs(left.timestamp - targetTimestamp) -
        Math.abs(right.timestamp - targetTimestamp)
    )[0];

  if (!baseline || Math.abs(baseline.timestamp - targetTimestamp) > toleranceMs) {
    return null;
  }

  return Number(((currentValue - baseline.point.value) * 100).toFixed(2));
}

export function summarizeMarketMovement(
  series: TimePoint[],
  currentValue: number
): MarketMovementSummary {
  const validSeries = series
    .filter(
      (point) =>
        Number.isFinite(point.value) &&
        Number.isFinite(new Date(point.timestamp).getTime())
    )
    .sort(
      (left, right) =>
        new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime()
    );
  const latestTimestamp = new Date(validSeries.at(-1)?.timestamp ?? "").getTime();

  if (!validSeries.length || !Number.isFinite(latestTimestamp)) {
    return {
      oneHour: null,
      twentyFourHours: null,
      sevenDays: null
    };
  }

  return {
    oneHour: changeAtWindow(validSeries, currentValue, latestTimestamp, 1),
    twentyFourHours: changeAtWindow(validSeries, currentValue, latestTimestamp, 24),
    sevenDays: changeAtWindow(validSeries, currentValue, latestTimestamp, 24 * 7)
  };
}
