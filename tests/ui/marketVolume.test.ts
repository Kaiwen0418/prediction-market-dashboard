import test from "node:test";
import assert from "node:assert/strict";
import {
  formatMarketVolume,
  getMarketVolumeOpacity,
  getRegionMarketVolume,
  qualifiesBySignal,
  qualifiesByVolume
} from "@/components/maps/marketVolume";
import type { RegionMarket } from "@/components/maps/spotlightStates";
import type { VenueMarketSummary } from "@/types/market";

const kalshiOnlyRegion: RegionMarket = {
  countryCode: "US",
  countryLabel: "United States",
  code: "OH",
  label: "Ohio",
  center: [-82.8, 40.4],
  marketTitle: "Ohio election",
  marketQuestion: "Which party will win Ohio?",
  note: "Kalshi-only market",
  kalshiEventTicker: "KXTEST-OH",
  kalshiMarketLabel: "Kalshi"
};

const comparableRegion: RegionMarket = {
  ...kalshiOnlyRegion,
  code: "PA",
  label: "Pennsylvania",
  liveMarketSlug: "test-polymarket-slug",
  kalshiEventTicker: "KXTEST-PA"
};

const markets: VenueMarketSummary[] = [
  {
    venue: "Kalshi",
    eventTicker: "KXTEST-OH",
    marketTicker: "KXTEST-OH-YES",
    seriesTicker: "KXTEST",
    title: "Ohio election",
    outcomeLabel: "Republican",
    probability: 0.62,
    volume24h: 12_500,
    status: "open",
    url: "https://kalshi.com/markets/kxtest/kxtest-oh",
    updatedAt: "2026-07-28T10:00:00.000Z"
  }
];

test("region volume is resolved from its Kalshi event", () => {
  assert.equal(getRegionMarketVolume(kalshiOnlyRegion, markets), 12_500);
  assert.equal(formatMarketVolume(12_500), "$12.5K");
});

test("volume eligibility is optional but defaults to a meaningful floor", () => {
  assert.equal(qualifiesByVolume(kalshiOnlyRegion, 12_500, 1_000), true);
  assert.equal(qualifiesByVolume(kalshiOnlyRegion, 500, 1_000), false);
  assert.equal(qualifiesByVolume(kalshiOnlyRegion, 500, 0), true);
  assert.equal(qualifiesByVolume(kalshiOnlyRegion, null, 0), false);
});

test("polygon opacity increases continuously with market volume", () => {
  const low = getMarketVolumeOpacity(100);
  const medium = getMarketVolumeOpacity(10_000);
  const high = getMarketVolumeOpacity(500_000);

  assert.ok(low < medium);
  assert.ok(medium < high);
  assert.ok(getMarketVolumeOpacity(0) >= 0.2);
  assert.ok(getMarketVolumeOpacity(null) > low);
});

test("volume eligibility applies consistently across venues", () => {
  assert.equal(qualifiesByVolume(comparableRegion, 12_500, 1_000), true);
});

test("score All does not bypass volume eligibility for an unscored Kalshi-only market", () => {
  assert.equal(qualifiesBySignal(kalshiOnlyRegion, 0, 0), false);
  assert.equal(qualifiesBySignal(kalshiOnlyRegion, 55, 50), true);
  assert.equal(qualifiesBySignal(comparableRegion, 0, 0), true);
});
