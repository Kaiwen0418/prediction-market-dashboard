import test from "node:test";
import assert from "node:assert/strict";
import {
  filterWatchedRegions,
  getSignalAlertCandidates,
  parseSignalWatchlist
} from "@/components/maps/signalWatchlist";

test("watchlist parsing validates, deduplicates, and sorts stored keys", () => {
  assert.deepEqual(
    parseSignalWatchlist(
      JSON.stringify(["US:TX", "invalid", "US:PA", "US:TX", 42])
    ),
    ["US:PA", "US:TX"]
  );
  assert.deepEqual(parseSignalWatchlist("{not-json"), []);
});

test("watched-only filtering keeps matching regions across countries", () => {
  const regions = [
    { code: "TX", countryCode: "US" },
    { code: "PA", countryCode: "US" },
    { code: "ON", countryCode: "CA" }
  ];

  assert.deepEqual(
    filterWatchedRegions(regions, ["US:PA", "CA:ON"], true),
    [regions[1], regions[2]]
  );
  assert.equal(filterWatchedRegions(regions, [], false), regions);
});

test("alerts require a watched live signal with a material new score", () => {
  const previous = new Map([
    ["US:TX", { score: 65, observedAt: "2026-07-24T10:00:00Z" }],
    ["US:PA", { score: 74, observedAt: "2026-07-24T10:00:00Z" }]
  ]);
  const signals = [
    {
      countryCode: "US",
      regionCode: "TX",
      regionLabel: "Texas",
      pairLabel: "Texas market",
      headline: "Flow accelerated",
      score: 72,
      observedAt: "2026-07-24T10:01:00Z",
      source: "live" as const
    },
    {
      countryCode: "US",
      regionCode: "PA",
      regionLabel: "Pennsylvania",
      pairLabel: "Pennsylvania market",
      headline: "Small change",
      score: 79,
      observedAt: "2026-07-24T10:01:00Z",
      source: "live" as const
    },
    {
      countryCode: "US",
      regionCode: "AZ",
      regionLabel: "Arizona",
      pairLabel: "Arizona market",
      headline: "Fixture",
      score: 90,
      observedAt: "2026-07-24T10:01:00Z",
      source: "fixture" as const
    }
  ];

  assert.deepEqual(
    getSignalAlertCandidates(signals, previous, ["US:TX", "US:PA", "US:AZ"]).map(
      (signal) => signal.regionCode
    ),
    ["TX"]
  );
  assert.deepEqual(getSignalAlertCandidates(signals, new Map(), ["US:TX"]), []);
});
