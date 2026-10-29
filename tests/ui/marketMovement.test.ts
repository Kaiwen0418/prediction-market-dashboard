import assert from "node:assert/strict";
import test from "node:test";
import { summarizeMarketMovement } from "@/analytics/marketMovement";
import type { TimePoint } from "@/types/market";

const latest = new Date("2026-07-24T12:00:00Z");

function point(hoursAgo: number, value: number): TimePoint {
  return {
    timestamp: new Date(latest.getTime() - hoursAgo * 60 * 60 * 1000).toISOString(),
    value
  };
}

test("market movement calculates supported trading windows in percentage points", () => {
  const summary = summarizeMarketMovement(
    [
      point(24 * 7, 0.38),
      point(24, 0.4),
      point(1, 0.41),
      point(0, 0.42)
    ],
    0.42
  );

  assert.deepEqual(summary, {
    oneHour: 1,
    twentyFourHours: 2,
    sevenDays: 4
  });
});

test("market movement withholds windows without a nearby observation", () => {
  const summary = summarizeMarketMovement(
    [point(24 * 7, 0.38), point(24, 0.4), point(0, 0.42)],
    0.42
  );

  assert.equal(summary.oneHour, null);
  assert.equal(summary.twentyFourHours, 2);
  assert.equal(summary.sevenDays, 4);
});
