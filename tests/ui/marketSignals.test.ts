import test from "node:test";
import assert from "node:assert/strict";
import {
  getMarketSignalColor,
  getMarketSignalLabel,
  getMarketSignalSeverity,
  rankRegionSignals
} from "@/components/maps/marketSignals";
import type { RegionSignal } from "@/types/signals";
import {
  getCountryMarketMaps,
  getConfiguredPolymarketSlugs,
  getRegionMarketsByCountry,
  getRegionMarketPairLabel,
  getRegionPolymarketSlugs,
  marketMatchesRegion,
  type RegionMarket
} from "@/components/maps/spotlightStates";

const REGION_MARKET_FIXTURE: RegionMarket = {
  code: "TX",
  countryCode: "US",
  countryLabel: "United States",
  center: [-99.3, 31.1],
  featureId: "48",
  label: "Texas",
  liveMarketSlug: "texas-republican-senate-primary-winner",
  note: "Test",
  zoom: 3.2,
  status: "live",
  signal: {
    kind: "whale-flow",
    score: 92,
    headline: "Whale",
    detail: "Whale",
    observedAt: "2026-07-24T09:30:00Z",
    source: "fixture"
  }
};

test("signal scores map to stable severity thresholds", () => {
  assert.equal(getMarketSignalSeverity(null), "inactive");
  assert.equal(getMarketSignalSeverity(0), "normal");
  assert.equal(getMarketSignalSeverity(49), "normal");
  assert.equal(getMarketSignalSeverity(50), "elevated");
  assert.equal(getMarketSignalSeverity(70), "high");
  assert.equal(getMarketSignalSeverity(85), "critical");
  assert.equal(getMarketSignalSeverity(200), "critical");
});

test("signal colors distinguish inactive and abnormal activity", () => {
  assert.equal(getMarketSignalColor(null), "#dededb");
  assert.equal(getMarketSignalColor(0), "rgb(255, 244, 194)");
  assert.equal(getMarketSignalColor(50), "rgb(250, 188, 64)");
  assert.equal(getMarketSignalColor(70), "rgb(239, 120, 35)");
  assert.equal(getMarketSignalColor(100), "rgb(190, 45, 32)");
  assert.notEqual(getMarketSignalColor(null), getMarketSignalColor(50));
  assert.notEqual(getMarketSignalColor(null), getMarketSignalColor(0));
  assert.notEqual(getMarketSignalColor(0), getMarketSignalColor(25));
  assert.notEqual(getMarketSignalColor(50), getMarketSignalColor(85));
  assert.equal(getMarketSignalColor(-10), getMarketSignalColor(0));
  assert.equal(getMarketSignalColor(150), getMarketSignalColor(100));
});

test("signal labels are readable", () => {
  assert.equal(
    getMarketSignalLabel({
      kind: "whale-flow",
      score: 90,
      headline: "Whale flow",
      detail: "Test detail",
      observedAt: "2026-07-24T09:40:00Z",
      source: "fixture"
    }),
    "Whale Flow"
  );
  assert.equal(getMarketSignalLabel(null), "No active signal");
});

test("configured US regions include Polymarket-comparable and Kalshi-only pairs", () => {
  const usRegions = getRegionMarketsByCountry("US");
  const polymarketComparable = usRegions.filter(
    (region) => region.liveMarketSlug
  );
  const kalshiOnly = usRegions.filter((region) => !region.liveMarketSlug);

  assert.equal(polymarketComparable.length, 8);
  assert.equal(kalshiOnly.length, 20);
  assert.ok(
    usRegions.every((region) =>
      /^[A-Z0-9-]+$/.test(region.kalshiEventTicker ?? "")
    )
  );
  assert.equal(
    usRegions.find((region) => region.code === "CA")?.kalshiEventTicker,
    "KXGOVCA-26"
  );
  assert.equal(
    kalshiOnly.find((region) => region.code === "OH")?.kalshiMarketLabel,
    "Ohio Governor winner?"
  );
  assert.ok(kalshiOnly.every((region) => region.marketStatus === "open"));
});

test("configured conflict markets use selectable national polygons without synthetic scores", () => {
  for (const countryCode of ["UA", "RU", "IL", "IR", "LB", "PS"]) {
    const regions = getRegionMarketsByCountry(countryCode);
    const nationalRegion = regions.find(
      (region) => region.coverage === "country"
    );

    assert.ok(nationalRegion);
    assert.equal(nationalRegion.marketStatus, "open");
    assert.ok(nationalRegion.liveMarketSlug);
    assert.ok(regions.every((region) => region.signal.score === 0));
  }
});

test("European registry exposes multiple live election pairs by country", () => {
  const expectedCountries = [
    "FR",
    "DE",
    "ES",
    "IT",
    "RO",
    "HU",
    "SE",
    "GR",
    "RS",
    "BG"
  ];
  const configuredCountries = new Set(
    getCountryMarketMaps().map((country) => country.code)
  );

  expectedCountries.forEach((countryCode) => {
    assert.ok(configuredCountries.has(countryCode));
    assert.ok(
      getRegionPolymarketSlugs(
        getRegionMarketsByCountry(countryCode)[0]
      ).length
    );
  });
  assert.ok(
    getRegionPolymarketSlugs(getRegionMarketsByCountry("FR")[0]).length >= 3
  );
  assert.ok(
    getRegionPolymarketSlugs(getRegionMarketsByCountry("RO")[0]).length >= 4
  );
  assert.equal(
    new Set(getConfiguredPolymarketSlugs()).size,
    getConfiguredPolymarketSlugs().length
  );
});

test("Ukraine exposes oblast-linked locality contracts", () => {
  const regions = getRegionMarketsByCountry("UA");
  const localities = regions.filter((region) => region.coverage === "region");

  assert.deepEqual(
    localities.map((region) => region.code),
    ["HUL", "KOS", "MYR", "STI", "BIL"]
  );
  assert.deepEqual(
    new Set(localities.map((region) => region.featureId)),
    new Set(["UA14", "UA23"])
  );
  assert.ok(localities.every((region) => region.marketStatus === "open"));
  assert.ok(localities.every((region) => region.liveMarketSlug));
});

test("activity ranking applies backend overrides and minimum score", () => {
  const regions = [
    {
      code: "TX",
      signal: {
        kind: "whale-flow" as const,
        score: 92,
        headline: "Fixture Texas",
        detail: "Fixture",
        observedAt: "2026-07-24T08:00:00Z",
        source: "fixture" as const
      }
    },
    {
      code: "CA",
      signal: {
        kind: "volume-anomaly" as const,
        score: 79,
        headline: "Fixture California",
        detail: "Fixture",
        observedAt: "2026-07-24T08:00:00Z",
        source: "fixture" as const
      }
    }
  ];
  const overrides: RegionSignal[] = [
    {
      regionCode: "CA",
      countryCode: "US",
      marketSlug: "california",
      kind: "order-flow",
      score: 95,
      severity: "critical",
      headline: "Live California",
      detail: "Live",
      observedAt: "2026-07-24T09:59:00Z",
      source: "live",
      confidence: 0.75,
      baselineWindow: "24 samples",
      components: []
    }
  ];

  const ranked = rankRegionSignals(regions, overrides, {
    minimumScore: 85,
    now: new Date("2026-07-24T10:00:00Z")
  });

  assert.deepEqual(ranked.map((item) => item.region.code), ["CA", "TX"]);
  assert.equal(ranked[0]?.signal.headline, "Live California");
});

test("activity ranking excludes regions below the selected threshold", () => {
  const ranked = rankRegionSignals(
    [
      {
        code: "AZ",
        signal: {
          kind: "normal" as const,
          score: 49,
          headline: "Normal",
          detail: "Normal",
          observedAt: "2026-07-24T08:00:00Z",
          source: "fixture" as const
        }
      }
    ],
    [],
    {
      minimumScore: 50,
      now: new Date("2026-07-24T10:00:00Z")
    }
  );

  assert.equal(ranked.length, 0);
});

test("activity ranking includes normal regions when score filter is All", () => {
  const ranked = rankRegionSignals(
    [
      {
        code: "AZ",
        signal: {
          kind: "normal" as const,
          score: 46,
          headline: "Normal",
          detail: "Normal",
          observedAt: "2026-07-24T08:00:00Z",
          source: "fixture" as const
        }
      }
    ],
    [],
    {
      minimumScore: 0,
      now: new Date("2026-07-24T10:00:00Z")
    }
  );

  assert.deepEqual(ranked.map((item) => item.region.code), ["AZ"]);
});

test("activity ranking filters by signal kind and freshness window", () => {
  const regions = [
    {
      code: "TX",
      signal: {
        kind: "whale-flow" as const,
        score: 92,
        headline: "Whale",
        detail: "Whale",
        observedAt: "2026-07-24T09:30:00Z",
        source: "fixture" as const
      }
    },
    {
      code: "PA",
      signal: {
        kind: "poll-divergence" as const,
        score: 72,
        headline: "Poll",
        detail: "Poll",
        observedAt: "2026-07-24T07:00:00Z",
        source: "fixture" as const
      }
    }
  ];

  const ranked = rankRegionSignals(regions, [], {
    signalKind: "whale-flow",
    maxAgeHours: 1,
    now: new Date("2026-07-24T10:00:00Z")
  });

  assert.deepEqual(ranked.map((item) => item.region.code), ["TX"]);
});

test("region pair labels remain readable during market fallback", () => {
  assert.equal(
    getRegionMarketPairLabel(REGION_MARKET_FIXTURE),
    "Texas Republican Senate Primary Winner"
  );
});

test("region coverage only matches the configured market identity", () => {
  assert.equal(
    marketMatchesRegion(REGION_MARKET_FIXTURE, {
      slug: "texas-republican-senate-primary-winner"
    }),
    true
  );
  assert.equal(
    marketMatchesRegion(REGION_MARKET_FIXTURE, {
      slug: "outcome-token",
      eventSlug: "texas-republican-senate-primary-winner"
    }),
    true
  );
  assert.equal(
    marketMatchesRegion(REGION_MARKET_FIXTURE, {
      slug: "california-governor-election-2026"
    }),
    false
  );
  assert.equal(
    marketMatchesRegion(getRegionMarketsByCountry("FR")[0], {
      slug: "new-french-election-market",
      title: "Who will win the next French presidential election?"
    }),
    true
  );
  assert.equal(
    marketMatchesRegion(getRegionMarketsByCountry("FR")[0], {
      slug: "wisconsin-primary",
      title: "Francesca Hong vote percent"
    }),
    false
  );
});

test("country adapters expose distinct configured region identifiers", () => {
  assert.deepEqual(
    getCountryMarketMaps().map((country) => country.code),
    [
      "US",
      "GB",
      "FR",
      "DE",
      "ES",
      "IT",
      "IS",
      "RO",
      "HU",
      "SE",
      "GR",
      "RS",
      "BG",
      "UA",
      "RU",
      "IL",
      "IR",
      "LB",
      "PS"
    ]
  );

  const ukRegions = getRegionMarketsByCountry("GB");
  assert.deepEqual(
    ukRegions.map((region) => region.code),
    ["SCT", "LDN", "WLS", "NIR"]
  );
  assert.equal(new Set(ukRegions.map((region) => region.featureId)).size, ukRegions.length);

  const franceRegions = getRegionMarketsByCountry("FR");
  assert.deepEqual(
    franceRegions.map((region) => region.code),
    ["FR"]
  );
  assert.equal(franceRegions[0]?.coverage, "country");

  const germanyRegions = getRegionMarketsByCountry("DE");
  assert.deepEqual(
    germanyRegions.map((region) => region.code),
    ["BER"]
  );
  assert.equal(germanyRegions[0]?.featureId, "DE-BE");
  assert.ok(
    [...franceRegions, ...germanyRegions].every(
      (region) => region.marketStatus === "open"
    )
  );
});
