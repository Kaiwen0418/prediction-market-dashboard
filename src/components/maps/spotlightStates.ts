"use client";

import type { RegionMarketSignal } from "@/components/maps/marketSignals";
import type { MarketSnapshot } from "@/types/market";

export type RegionMarketStatus = "live" | "watch" | "research";

export type RegionMarket = {
  code: string;
  countryCode: string;
  countryLabel: string;
  coverage?: "country" | "region";
  center: [number, number];
  featureId: string;
  label: string;
  liveMarketSlug?: string;
  liveMarketSlugs?: string[];
  kalshiEventTicker?: string;
  kalshiMarketLabel?: string;
  note: string;
  zoom: number;
  status: RegionMarketStatus;
  marketStatus?: MarketSnapshot["status"];
  signal: RegionMarketSignal;
};

export type CountryMarketMap = {
  code: string;
  worldFeatureIds: string[];
  label: string;
  projection: "geoAlbersUsa" | "geoMercator";
  featureIdProperty?: string;
  defaultRegionCode: string;
  defaultCenter: [number, number];
  defaultZoom: number;
  projectionScale?: number;
  boundarySourceLabel: string;
  boundarySourceUrl: string;
};

function kalshiOnlyRegion({
  center,
  code,
  featureId,
  kalshiEventTicker,
  kalshiMarketLabel,
  label,
  zoom
}: {
  center: [number, number];
  code: string;
  featureId: string;
  kalshiEventTicker: string;
  kalshiMarketLabel: string;
  label: string;
  zoom: number;
}): RegionMarket {
  return {
    code,
    countryCode: "US",
    countryLabel: "United States",
    center,
    featureId,
    label,
    kalshiEventTicker,
    kalshiMarketLabel,
    note: "Open Kalshi election market without a configured Polymarket equivalent.",
    zoom,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "normal",
      score: 0,
      headline: "Signal scoring not connected",
      detail:
        "This region has an open Kalshi political market. Venue-specific anomaly scoring is not active yet.",
      observedAt: "2026-07-28T00:00:00Z",
      source: "fixture"
    }
  };
}

function nationalConflictRegion({
  center,
  code,
  countryLabel,
  liveMarketSlug,
  note,
  zoom
}: {
  center: [number, number];
  code: string;
  countryLabel: string;
  liveMarketSlug: string;
  note: string;
  zoom: number;
}): RegionMarket {
  return {
    code,
    countryCode: code,
    countryLabel,
    coverage: "country",
    center,
    featureId: "*",
    label: countryLabel,
    liveMarketSlug,
    note,
    zoom,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "normal",
      score: 0,
      headline: "Conflict signal scoring pending",
      detail:
        "Live market pricing is available. Conflict-specific flow and anomaly scoring are not connected yet.",
      observedAt: "2026-07-28T00:00:00Z",
      source: "fixture"
    }
  };
}

function europeanPoliticalRegion({
  center,
  code,
  countryLabel,
  liveMarketSlug,
  liveMarketSlugs,
  zoom
}: {
  center: [number, number];
  code: string;
  countryLabel: string;
  liveMarketSlug: string;
  liveMarketSlugs: string[];
  zoom: number;
}): RegionMarket {
  return {
    code,
    countryCode: code,
    countryLabel,
    coverage: "country",
    center,
    featureId: "*",
    label: countryLabel,
    liveMarketSlug,
    liveMarketSlugs,
    note: "Open national election and government markets from Polymarket.",
    zoom,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "normal",
      score: 0,
      headline: "Venue analytics available",
      detail:
        "Live prices and market evidence are available. Country-level anomaly scoring is not connected yet.",
      observedAt: "2026-07-28T00:00:00Z",
      source: "fixture"
    }
  };
}

function ukraineConflictLocality({
  center,
  code,
  featureId,
  label,
  liveMarketSlug,
  note
}: {
  center: [number, number];
  code: string;
  featureId: string;
  label: string;
  liveMarketSlug: string;
  note: string;
}): RegionMarket {
  return {
    code,
    countryCode: "UA",
    countryLabel: "Ukraine",
    coverage: "region",
    center,
    featureId,
    label,
    liveMarketSlug,
    note,
    zoom: 9,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "normal",
      score: 0,
      headline: "Local conflict signal scoring pending",
      detail:
        "Live market pricing is available. Locality-specific flow and anomaly scoring are not connected yet.",
      observedAt: "2026-07-28T00:00:00Z",
      source: "fixture"
    }
  };
}

export const COUNTRY_MARKET_MAPS: CountryMarketMap[] = [
  {
    code: "US",
    worldFeatureIds: ["840"],
    label: "United States",
    projection: "geoAlbersUsa",
    defaultRegionCode: "CA",
    defaultCenter: [-96, 38],
    defaultZoom: 1,
    boundarySourceLabel: "US Census Bureau",
    boundarySourceUrl: "https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html"
  },
  {
    code: "GB",
    worldFeatureIds: ["826"],
    label: "United Kingdom",
    projection: "geoMercator",
    featureIdProperty: "AREACD",
    defaultRegionCode: "SCT",
    defaultCenter: [-3.5, 55.2],
    defaultZoom: 1,
    projectionScale: 1_650,
    boundarySourceLabel: "Office for National Statistics",
    boundarySourceUrl: "https://github.com/ONSvisual/topojson_boundaries"
  },
  {
    code: "FR",
    worldFeatureIds: ["250"],
    label: "France",
    projection: "geoMercator",
    defaultRegionCode: "FR",
    defaultCenter: [2.2, 46.3],
    defaultZoom: 7.5,
    featureIdProperty: "code",
    boundarySourceLabel: "France GeoJSON",
    boundarySourceUrl: "https://github.com/gregoiredavid/france-geojson"
  },
  {
    code: "DE",
    worldFeatureIds: ["276"],
    label: "Germany",
    projection: "geoMercator",
    defaultRegionCode: "BER",
    defaultCenter: [10.4, 51.1],
    defaultZoom: 7.5,
    featureIdProperty: "id",
    boundarySourceLabel: "Deutschland GeoJSON",
    boundarySourceUrl: "https://github.com/isellsoap/deutschlandGeoJSON"
  },
  {
    code: "ES",
    worldFeatureIds: ["724"],
    label: "Spain",
    projection: "geoMercator",
    defaultRegionCode: "ES",
    defaultCenter: [-3.7, 40.2],
    defaultZoom: 7,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "IT",
    worldFeatureIds: ["380"],
    label: "Italy",
    projection: "geoMercator",
    defaultRegionCode: "IT",
    defaultCenter: [12.6, 42.8],
    defaultZoom: 6,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "IS",
    worldFeatureIds: ["352"],
    label: "Iceland",
    projection: "geoMercator",
    defaultRegionCode: "IS",
    defaultCenter: [-18.6, 64.9],
    defaultZoom: 7,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "RO",
    worldFeatureIds: ["642"],
    label: "Romania",
    projection: "geoMercator",
    defaultRegionCode: "RO",
    defaultCenter: [24.9, 45.9],
    defaultZoom: 7,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "HU",
    worldFeatureIds: ["348"],
    label: "Hungary",
    projection: "geoMercator",
    defaultRegionCode: "HU",
    defaultCenter: [19.4, 47.2],
    defaultZoom: 8,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "SE",
    worldFeatureIds: ["752"],
    label: "Sweden",
    projection: "geoMercator",
    defaultRegionCode: "SE",
    defaultCenter: [16.5, 62.2],
    defaultZoom: 5,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "GR",
    worldFeatureIds: ["300"],
    label: "Greece",
    projection: "geoMercator",
    defaultRegionCode: "GR",
    defaultCenter: [22.2, 39.0],
    defaultZoom: 7,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "RS",
    worldFeatureIds: ["688"],
    label: "Serbia",
    projection: "geoMercator",
    defaultRegionCode: "RS",
    defaultCenter: [20.8, 44.0],
    defaultZoom: 8,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "BG",
    worldFeatureIds: ["100"],
    label: "Bulgaria",
    projection: "geoMercator",
    defaultRegionCode: "BG",
    defaultCenter: [25.3, 42.7],
    defaultZoom: 8,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "UA",
    worldFeatureIds: ["804"],
    label: "Ukraine",
    projection: "geoMercator",
    defaultRegionCode: "UA",
    defaultCenter: [31.2, 48.4],
    defaultZoom: 6.5,
    featureIdProperty: "ISO_CODE",
    boundarySourceLabel: "ArcGIS Ukraine Oblasts",
    boundarySourceUrl:
      "https://services1.arcgis.com/4ezfu5dIwH83BUNL/ArcGIS/rest/services/Ukraine_Oblasts/FeatureServer/0"
  },
  {
    code: "RU",
    worldFeatureIds: ["643"],
    label: "Russia",
    projection: "geoMercator",
    defaultRegionCode: "RU",
    defaultCenter: [88, 60],
    defaultZoom: 2.2,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "IL",
    worldFeatureIds: ["376"],
    label: "Israel",
    projection: "geoMercator",
    defaultRegionCode: "IL",
    defaultCenter: [34.9, 31.5],
    defaultZoom: 10,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "IR",
    worldFeatureIds: ["364"],
    label: "Iran",
    projection: "geoMercator",
    defaultRegionCode: "IR",
    defaultCenter: [53.7, 32.4],
    defaultZoom: 5,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "LB",
    worldFeatureIds: ["422"],
    label: "Lebanon",
    projection: "geoMercator",
    defaultRegionCode: "LB",
    defaultCenter: [35.8, 33.9],
    defaultZoom: 12,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  },
  {
    code: "PS",
    worldFeatureIds: ["275"],
    label: "Palestine",
    projection: "geoMercator",
    defaultRegionCode: "PS",
    defaultCenter: [35.2, 31.9],
    defaultZoom: 12,
    boundarySourceLabel: "Natural Earth",
    boundarySourceUrl: "https://github.com/topojson/world-atlas"
  }
];

export const REGION_MARKETS: RegionMarket[] = [
  {
    code: "TX",
    countryCode: "US",
    countryLabel: "United States",
    center: [-99.3, 31.1],
    featureId: "48",
    label: "Texas",
    liveMarketSlug: "texas-republican-senate-primary-winner",
    kalshiEventTicker: "SENATETX-26",
    note: "Order book and recent market activity are available.",
    zoom: 3.2,
    status: "live",
    marketStatus: "closed",
    signal: {
      kind: "whale-flow",
      score: 92,
      headline: "Whale-sized directional flow",
      detail: "Large directional trades and one-sided depth make this the highest-priority region in the scanner.",
      observedAt: "2026-07-24T09:40:00Z",
      source: "fixture"
    }
  },
  {
    code: "AZ",
    countryCode: "US",
    countryLabel: "United States",
    center: [-111.7, 34.2],
    featureId: "04",
    label: "Arizona",
    liveMarketSlug: "arizona-presidential-election-winner",
    kalshiEventTicker: "GOVPARTYAZ-26",
    note: "Historical pricing is available for this political market.",
    zoom: 4.2,
    status: "research",
    signal: {
      kind: "price-move",
      score: 46,
      headline: "Price action within normal range",
      detail: "Movement remains below the abnormal-activity threshold.",
      observedAt: "2026-07-24T09:36:00Z",
      source: "fixture"
    }
  },
  {
    code: "GA",
    countryCode: "US",
    countryLabel: "United States",
    center: [-83.5, 32.7],
    featureId: "13",
    label: "Georgia",
    liveMarketSlug: "georgia-presidential-election-winner",
    kalshiEventTicker: "SENATEGA-26",
    note: "Historical pricing is available for this political market.",
    zoom: 5,
    status: "research",
    signal: {
      kind: "normal",
      score: 31,
      headline: "No material anomaly",
      detail: "Trading activity is close to its recent baseline.",
      observedAt: "2026-07-24T09:34:00Z",
      source: "fixture"
    }
  },
  {
    code: "MI",
    countryCode: "US",
    countryLabel: "United States",
    center: [-85.5, 44.4],
    featureId: "26",
    label: "Michigan",
    liveMarketSlug: "michigan-presidential-election-winner",
    kalshiEventTicker: "KXMISENATE-26",
    note: "Historical pricing is available for this political market.",
    zoom: 4.1,
    status: "research",
    signal: {
      kind: "volume-anomaly",
      score: 55,
      headline: "Volume beginning to accelerate",
      detail: "Recent activity is elevated but has not reached a high-conviction threshold.",
      observedAt: "2026-07-24T09:38:00Z",
      source: "fixture"
    }
  },
  {
    code: "PA",
    countryCode: "US",
    countryLabel: "United States",
    center: [-77.7, 40.8],
    featureId: "42",
    label: "Pennsylvania",
    liveMarketSlug: "pennsylvania-presidential-election-winner",
    kalshiEventTicker: "GOVPARTYPA-26",
    note: "Historical pricing is available for this political market.",
    zoom: 5.2,
    status: "research",
    signal: {
      kind: "poll-divergence",
      score: 72,
      headline: "Market and polling paths diverge",
      detail: "The market-implied outcome has moved away from the latest polling baseline.",
      observedAt: "2026-07-24T09:39:00Z",
      source: "fixture"
    }
  },
  {
    code: "WI",
    countryCode: "US",
    countryLabel: "United States",
    center: [-89.9, 44.6],
    featureId: "55",
    label: "Wisconsin",
    liveMarketSlug: "wisconsin-presidential-election-winner",
    kalshiEventTicker: "GOVPARTYWI-26",
    note: "Historical pricing is available for this political market.",
    zoom: 5.4,
    status: "research",
    signal: {
      kind: "normal",
      score: 38,
      headline: "Order flow remains balanced",
      detail: "No unusual concentration or probability shock is present.",
      observedAt: "2026-07-24T09:31:00Z",
      source: "fixture"
    }
  },
  {
    code: "FL",
    countryCode: "US",
    countryLabel: "United States",
    center: [-82.3, 28.4],
    featureId: "12",
    label: "Florida",
    liveMarketSlug: "florida-presidential-election-winner",
    kalshiEventTicker: "GOVPARTYFL-26",
    note: "Select this market to inspect available pricing and signals.",
    zoom: 4.2,
    status: "watch",
    signal: {
      kind: "poll-divergence",
      score: 63,
      headline: "Moderate polling divergence",
      detail: "Market pricing is separating from the regional polling baseline.",
      observedAt: "2026-07-24T09:32:00Z",
      source: "fixture"
    }
  },
  {
    code: "CA",
    countryCode: "US",
    countryLabel: "United States",
    center: [-119.4, 36.7],
    featureId: "06",
    label: "California",
    liveMarketSlug: "california-governor-election-2026",
    kalshiEventTicker: "KXGOVCA-26",
    note: "California governor market with regional signal coverage.",
    zoom: 3.8,
    status: "watch",
    marketStatus: "open",
    signal: {
      kind: "volume-anomaly",
      score: 79,
      headline: "Unusual volume concentration",
      detail: "Turnover is concentrated in a short window relative to its recent baseline.",
      observedAt: "2026-07-24T09:41:00Z",
      source: "fixture"
    }
  },
  kalshiOnlyRegion({
    code: "OH",
    featureId: "39",
    label: "Ohio",
    center: [-82.8, 40.4],
    zoom: 5,
    kalshiEventTicker: "GOVPARTYOH-26",
    kalshiMarketLabel: "Ohio Governor winner?"
  }),
  kalshiOnlyRegion({
    code: "SC",
    featureId: "45",
    label: "South Carolina",
    center: [-80.9, 33.8],
    zoom: 5.4,
    kalshiEventTicker: "KXSCRSENS-26",
    kalshiMarketLabel: "South Carolina Republican Senate special primary winner?"
  }),
  kalshiOnlyRegion({
    code: "ME",
    featureId: "23",
    label: "Maine",
    center: [-69, 45.2],
    zoom: 5,
    kalshiEventTicker: "SENATEME-26",
    kalshiMarketLabel: "Maine Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "CO",
    featureId: "08",
    label: "Colorado",
    center: [-105.5, 39],
    zoom: 5,
    kalshiEventTicker: "GOVPARTYCO-26",
    kalshiMarketLabel: "Colorado Governor winner?"
  }),
  kalshiOnlyRegion({
    code: "KS",
    featureId: "20",
    label: "Kansas",
    center: [-98.4, 38.5],
    zoom: 5,
    kalshiEventTicker: "KXGOVKSNOMR-26",
    kalshiMarketLabel: "Kansas Republican Governor nominee?"
  }),
  kalshiOnlyRegion({
    code: "AK",
    featureId: "02",
    label: "Alaska",
    center: [-152, 64],
    zoom: 3.5,
    kalshiEventTicker: "SENATEAK-26",
    kalshiMarketLabel: "Alaska Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "MN",
    featureId: "27",
    label: "Minnesota",
    center: [-94.5, 46],
    zoom: 4.5,
    kalshiEventTicker: "KXGOVMNNOMR-26",
    kalshiMarketLabel: "Minnesota Republican Governor nominee?"
  }),
  kalshiOnlyRegion({
    code: "TN",
    featureId: "47",
    label: "Tennessee",
    center: [-86, 35.8],
    zoom: 5,
    kalshiEventTicker: "KXGOVTNNOMR-2-26",
    kalshiMarketLabel: "Tennessee Republican Governor nominee?"
  }),
  kalshiOnlyRegion({
    code: "MS",
    featureId: "28",
    label: "Mississippi",
    center: [-89.7, 32.7],
    zoom: 5.2,
    kalshiEventTicker: "SENATEMS-26",
    kalshiMarketLabel: "Mississippi Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "LA",
    featureId: "22",
    label: "Louisiana",
    center: [-92, 31],
    zoom: 5.2,
    kalshiEventTicker: "KXSENATELA-26NOV",
    kalshiMarketLabel: "Louisiana Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "MT",
    featureId: "30",
    label: "Montana",
    center: [-109.5, 47],
    zoom: 4.5,
    kalshiEventTicker: "SENATEMT-26",
    kalshiMarketLabel: "Montana Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "OR",
    featureId: "41",
    label: "Oregon",
    center: [-120.5, 44],
    zoom: 4.7,
    kalshiEventTicker: "GOVPARTYOR-26",
    kalshiMarketLabel: "Oregon Governor winner?"
  }),
  kalshiOnlyRegion({
    code: "NJ",
    featureId: "34",
    label: "New Jersey",
    center: [-74.5, 40.1],
    zoom: 6,
    kalshiEventTicker: "SENATENJ-26",
    kalshiMarketLabel: "New Jersey Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "OK",
    featureId: "40",
    label: "Oklahoma",
    center: [-97.5, 35.5],
    zoom: 5,
    kalshiEventTicker: "SENATEOK-26",
    kalshiMarketLabel: "Oklahoma Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "SD",
    featureId: "46",
    label: "South Dakota",
    center: [-100, 44.5],
    zoom: 5,
    kalshiEventTicker: "SENATESD-26",
    kalshiMarketLabel: "South Dakota Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "NE",
    featureId: "31",
    label: "Nebraska",
    center: [-99.8, 41.5],
    zoom: 5,
    kalshiEventTicker: "SENATENE-26",
    kalshiMarketLabel: "Nebraska Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "NC",
    featureId: "37",
    label: "North Carolina",
    center: [-79, 35.5],
    zoom: 5.2,
    kalshiEventTicker: "SENATENC-26",
    kalshiMarketLabel: "North Carolina Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "IA",
    featureId: "19",
    label: "Iowa",
    center: [-93.5, 42],
    zoom: 5,
    kalshiEventTicker: "SENATEIA-26",
    kalshiMarketLabel: "Iowa Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "WV",
    featureId: "54",
    label: "West Virginia",
    center: [-80.5, 38.6],
    zoom: 5.6,
    kalshiEventTicker: "SENATEWV-26",
    kalshiMarketLabel: "West Virginia Senate winner?"
  }),
  kalshiOnlyRegion({
    code: "NY",
    featureId: "36",
    label: "New York",
    center: [-75, 43],
    zoom: 4.8,
    kalshiEventTicker: "GOVPARTYNY-26",
    kalshiMarketLabel: "New York Governor winner?"
  }),
  nationalConflictRegion({
    code: "UA",
    countryLabel: "Ukraine",
    center: [31.2, 48.4],
    zoom: 6.5,
    liveMarketSlug: "ukraine-signs-peace-deal-with-russia-before-2027",
    note:
      "Open Polymarket contract on Ukraine signing a peace framework with Russia before 2027."
  }),
  ukraineConflictLocality({
    code: "HUL",
    featureId: "UA23",
    label: "Huliaipole",
    center: [36.1654, 47.6484],
    liveMarketSlug:
      "will-russia-capture-all-of-huliaipole-by-september-30",
    note:
      "Open Polymarket contract on Russia capturing all of Huliaipole by September 30, 2026."
  }),
  ukraineConflictLocality({
    code: "KOS",
    featureId: "UA14",
    label: "Kostyantynivka",
    center: [37.7069, 48.5277],
    liveMarketSlug:
      "will-russia-capture-kostyantynivka-by-december-31-2026-936-942-271-276-578-687-312-238",
    note:
      "Open Polymarket contract on Russia capturing Kostyantynivka by December 31, 2026."
  }),
  ukraineConflictLocality({
    code: "MYR",
    featureId: "UA14",
    label: "Myrne",
    center: [37.00788, 48.367306],
    liveMarketSlug: "will-russia-enter-myrne-by-july-31-2026",
    note:
      "Open Polymarket contract on Russian forces entering Myrne by July 31, 2026."
  }),
  ukraineConflictLocality({
    code: "STI",
    featureId: "UA14",
    label: "Stinky",
    center: [37.739606, 48.57883],
    liveMarketSlug: "will-russia-enter-stinky-by-july-31",
    note:
      "Open Polymarket contract on Russian forces entering Stinky by July 31, 2026."
  }),
  ukraineConflictLocality({
    code: "BIL",
    featureId: "UA14",
    label: "Bilytske",
    center: [37.1811, 48.4064],
    liveMarketSlug:
      "will-russia-capture-bilytske-by-december-31-2026-252-757-575",
    note:
      "Open Polymarket contract on Russia capturing Bilytske by December 31, 2026."
  }),
  nationalConflictRegion({
    code: "RU",
    countryLabel: "Russia",
    center: [88, 60],
    zoom: 2.2,
    liveMarketSlug:
      "russia-x-ukraine-ceasefire-agreement-by-december-31-2026",
    note:
      "Open Polymarket contract on a Russia-Ukraine ceasefire agreement by December 31, 2026."
  }),
  nationalConflictRegion({
    code: "IL",
    countryLabel: "Israel",
    center: [34.9, 31.5],
    zoom: 10,
    liveMarketSlug:
      "israel-x-iran-ceasefire-continues-through-august-31-20260716224448970-754-896-823",
    note:
      "Open Polymarket contract on the Israel-Iran ceasefire continuing through August 31, 2026."
  }),
  nationalConflictRegion({
    code: "IR",
    countryLabel: "Iran",
    center: [53.7, 32.4],
    zoom: 5,
    liveMarketSlug:
      "us-x-iran-effective-ceasfire-by-august-31-20260715194822047",
    note:
      "Open Polymarket contract on an effective US-Iran ceasefire by August 31, 2026."
  }),
  nationalConflictRegion({
    code: "LB",
    countryLabel: "Lebanon",
    center: [35.8, 33.9],
    zoom: 12,
    liveMarketSlug: "israel-withdraws-from-lebanon-by-august-31-2026",
    note:
      "Open Polymarket contract on an Israeli withdrawal from Lebanon by August 31, 2026."
  }),
  nationalConflictRegion({
    code: "PS",
    countryLabel: "Palestine",
    center: [35.2, 31.9],
    zoom: 12,
    liveMarketSlug:
      "israel-x-hamas-ceasefire-phase-ii-by-december-31-632",
    note:
      "Open Polymarket contract on Israel-Hamas ceasefire Phase II by December 31, 2026."
  }),
  {
    code: "SCT",
    countryCode: "GB",
    countryLabel: "United Kingdom",
    center: [-4.2, 56.7],
    featureId: "S92000003",
    label: "Scotland",
    liveMarketSlug: "will-scotland-hold-an-independence-referendum-before-2030",
    note: "Constitutional politics market with regional signal coverage.",
    zoom: 1,
    status: "research",
    signal: {
      kind: "poll-divergence",
      score: 74,
      headline: "Referendum pricing diverges from polling",
      detail: "The market is trading away from the latest constitutional polling baseline.",
      observedAt: "2026-07-24T10:05:00Z",
      source: "fixture"
    }
  },
  {
    code: "FR",
    countryCode: "FR",
    countryLabel: "France",
    coverage: "country",
    center: [2.2, 46.3],
    featureId: "*",
    label: "France",
    liveMarketSlug: "next-french-presidential-election",
    liveMarketSlugs: [
      "next-french-presidential-election",
      "france-united-left-primary-winner",
      "socialist-party-of-france-presidential-nominee-20260710182042067"
    ],
    note: "French presidential market with active liquidity and regional signal coverage.",
    zoom: 7.5,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "volume-anomaly",
      score: 88,
      headline: "Presidential market turnover is accelerating",
      detail: "French election turnover is elevated relative to the broader European political market set.",
      observedAt: "2026-07-24T14:25:00Z",
      source: "fixture"
    }
  },
  {
    code: "BER",
    countryCode: "DE",
    countryLabel: "Germany",
    center: [13.4, 52.5],
    featureId: "DE-BE",
    label: "Berlin",
    liveMarketSlug: "berlin-state-election-winner",
    liveMarketSlugs: [
      "berlin-state-election-winner",
      "friedrich-merz-out-as-chancellor-of-germany-before-2027",
      "next-leader-of-germanys-union-cducsu-20260718204733993"
    ],
    note: "Berlin state election market with state-level signal coverage.",
    zoom: 10.5,
    status: "live",
    marketStatus: "open",
    signal: {
      kind: "order-flow",
      score: 76,
      headline: "Berlin election flow is one-sided",
      detail: "Directional order flow in the Berlin state election is elevated against its recent baseline.",
      observedAt: "2026-07-24T14:20:00Z",
      source: "fixture"
    }
  },
  {
    code: "ES",
    countryCode: "ES",
    countryLabel: "Spain",
    coverage: "country",
    center: [-3.7, 40.2],
    featureId: "*",
    label: "Spain",
    liveMarketSlug: "next-prime-minister-of-spain-20260625005215443",
    liveMarketSlugs: [
      "next-prime-minister-of-spain-20260625005215443",
      "spain-snap-election-called-by",
      "spain-snap-election-called-in-2026",
      "no-confidence-vote-against-spain-pm-sanchez-by-june-30"
    ],
    note: "Next-prime-minister market with country-level signal coverage.",
    zoom: 5,
    status: "watch",
    marketStatus: "open",
    signal: {
      kind: "price-move",
      score: 69,
      headline: "Leadership pricing moved sharply",
      detail: "The leading Spanish prime-minister outcome has repriced faster than its recent range.",
      observedAt: "2026-07-24T14:18:00Z",
      source: "fixture"
    }
  },
  {
    code: "IT",
    countryCode: "IT",
    countryLabel: "Italy",
    coverage: "country",
    center: [12.6, 42.8],
    featureId: "*",
    label: "Italy",
    liveMarketSlug: "next-prime-minister-of-italy",
    liveMarketSlugs: [
      "next-prime-minister-of-italy",
      "meloni-out-as-prime-minister-of-italy-by-june-30"
    ],
    note: "Next-prime-minister market with country-level signal coverage.",
    zoom: 5,
    status: "watch",
    marketStatus: "open",
    signal: {
      kind: "poll-divergence",
      score: 58,
      headline: "Leadership market differs from baseline",
      detail: "Italian leadership pricing is moderately separated from the current comparison baseline.",
      observedAt: "2026-07-24T14:15:00Z",
      source: "fixture"
    }
  },
  {
    code: "IS",
    countryCode: "IS",
    countryLabel: "Iceland",
    coverage: "country",
    center: [-18.6, 64.9],
    featureId: "*",
    label: "Iceland",
    liveMarketSlug:
      "icelandic-european-union-membership-negotiations-referendum-passes-20260609135241589",
    note: "European Union membership referendum market with country-level signal coverage.",
    zoom: 5,
    status: "research",
    marketStatus: "open",
    signal: {
      kind: "volume-anomaly",
      score: 52,
      headline: "Referendum activity is above baseline",
      detail: "Trading in Iceland's EU membership referendum is beginning to accelerate.",
      observedAt: "2026-07-24T14:12:00Z",
      source: "fixture"
    }
  },
  europeanPoliticalRegion({
    code: "RO",
    countryLabel: "Romania",
    center: [24.9, 45.9],
    liveMarketSlug: "next-prime-minister-of-romania-732",
    liveMarketSlugs: [
      "next-prime-minister-of-romania-732",
      "which-coalition-will-form-the-next-romanian-government",
      "party-of-next-prime-minister-of-romania-788",
      "romanian-pm-bolojan-out-by"
    ],
    zoom: 7
  }),
  europeanPoliticalRegion({
    code: "HU",
    countryLabel: "Hungary",
    center: [19.4, 47.2],
    liveMarketSlug: "next-president-of-hungary-20260727225539504",
    liveMarketSlugs: ["next-president-of-hungary-20260727225539504"],
    zoom: 8
  }),
  europeanPoliticalRegion({
    code: "SE",
    countryLabel: "Sweden",
    center: [16.5, 62.2],
    liveMarketSlug: "next-prime-minister-of-sweden",
    liveMarketSlugs: [
      "next-prime-minister-of-sweden",
      "sweden-parliamentary-election-winner",
      "sweden-parliamentary-election-2nd-place",
      "sweden-parliamentary-election-3rd-place"
    ],
    zoom: 5
  }),
  europeanPoliticalRegion({
    code: "GR",
    countryLabel: "Greece",
    center: [22.2, 39.0],
    liveMarketSlug: "next-prime-minister-of-greece-20260714160853421",
    liveMarketSlugs: ["next-prime-minister-of-greece-20260714160853421"],
    zoom: 7
  }),
  europeanPoliticalRegion({
    code: "RS",
    countryLabel: "Serbia",
    center: [20.8, 44.0],
    liveMarketSlug: "next-serbia-presidential-election-winner-20260629192336823",
    liveMarketSlugs: [
      "next-serbia-presidential-election-winner-20260629192336823",
      "next-prime-minister-of-serbia-20260629223938642",
      "serbia-parliament-dissolved-by-20260629164744649"
    ],
    zoom: 8
  }),
  europeanPoliticalRegion({
    code: "BG",
    countryLabel: "Bulgaria",
    center: [25.3, 42.7],
    liveMarketSlug: "bulgaria-presidential-election",
    liveMarketSlugs: ["bulgaria-presidential-election"],
    zoom: 8
  }),
  {
    code: "LDN",
    countryCode: "GB",
    countryLabel: "United Kingdom",
    center: [-0.1, 51.5],
    featureId: "E12000007",
    label: "London",
    liveMarketSlug: "next-london-mayoral-election-winner",
    note: "Mayoral election market with regional signal coverage.",
    zoom: 1,
    status: "watch",
    signal: {
      kind: "volume-anomaly",
      score: 68,
      headline: "Mayoral market volume is elevated",
      detail: "Recent turnover is above the London market's recent baseline.",
      observedAt: "2026-07-24T10:02:00Z",
      source: "fixture"
    }
  },
  {
    code: "WLS",
    countryCode: "GB",
    countryLabel: "United Kingdom",
    center: [-3.7, 52.3],
    featureId: "W92000004",
    label: "Wales",
    liveMarketSlug: "welsh-parliament-election-most-seats",
    note: "Senedd election market with regional signal coverage.",
    zoom: 1,
    status: "research",
    signal: {
      kind: "price-move",
      score: 57,
      headline: "Senedd pricing is repricing",
      detail: "The leading-outcome probability has moved faster than its recent baseline.",
      observedAt: "2026-07-24T09:58:00Z",
      source: "fixture"
    }
  },
  {
    code: "NIR",
    countryCode: "GB",
    countryLabel: "United Kingdom",
    center: [-6.8, 54.7],
    featureId: "N92000002",
    label: "Northern Ireland",
    liveMarketSlug: "northern-ireland-assembly-election-most-seats",
    note: "Assembly election market with regional signal coverage.",
    zoom: 1,
    status: "research",
    signal: {
      kind: "order-flow",
      score: 43,
      headline: "Assembly market flow remains balanced",
      detail: "Directional activity remains below the abnormal-flow threshold.",
      observedAt: "2026-07-24T09:55:00Z",
      source: "fixture"
    }
  }
];

export const SPOTLIGHT_STATES = REGION_MARKETS;

export function getCountryMarketMaps() {
  return COUNTRY_MARKET_MAPS.filter((country) => REGION_MARKETS.some((region) => region.countryCode === country.code));
}

export function getRegionMarketsByCountry(countryCode: string) {
  return REGION_MARKETS.filter((region) => region.countryCode === countryCode);
}

export function inferSpotlightCodeFromMarket(input: { slug: string; eventSlug?: string; title: string }) {
  const text = `${input.slug} ${input.eventSlug ?? ""} ${input.title}`.toLowerCase();
  const match = REGION_MARKETS.find(
    (region) =>
      (region.liveMarketSlug && input.slug === region.liveMarketSlug) ||
      text.includes(region.label.toLowerCase())
  );
  return match?.code ?? "TX";
}

export function getSpotlightState(code?: string | null) {
  return REGION_MARKETS.find((region) => region.code === code) ?? null;
}

export function getRegionMarket(code?: string | null) {
  return getSpotlightState(code);
}

export function getRegionMarketPairLabel(region: RegionMarket) {
  if (region.kalshiMarketLabel && !region.liveMarketSlug) {
    return region.kalshiMarketLabel;
  }

  return (region.liveMarketSlug ?? region.kalshiEventTicker ?? region.label)
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function getRegionPolymarketSlugs(
  region: RegionMarket | null | undefined
) {
  if (!region) return [];
  return [
    ...new Set(
      [region.liveMarketSlug, ...(region.liveMarketSlugs ?? [])].filter(
        (slug): slug is string => Boolean(slug)
      )
    )
  ];
}

export function getConfiguredPolymarketSlugs() {
  return [
    ...new Set(REGION_MARKETS.flatMap((region) => getRegionPolymarketSlugs(region)))
  ];
}

export function getRegionKalshiEventTickers(
  region: RegionMarket | null | undefined
) {
  return region?.kalshiEventTicker ? [region.kalshiEventTicker] : [];
}

const COUNTRY_DISCOVERY_ALIASES: Record<string, string[]> = {
  US: ["united states", "u.s.", "american"],
  GB: ["united kingdom", "britain", "british"],
  FR: ["france", "french"],
  DE: ["germany", "german"],
  ES: ["spain", "spanish"],
  IT: ["italy", "italian"],
  IS: ["iceland", "icelandic"],
  RO: ["romania", "romanian"],
  HU: ["hungary", "hungarian"],
  SE: ["sweden", "swedish"],
  GR: ["greece", "greek"],
  RS: ["serbia", "serbian"],
  BG: ["bulgaria", "bulgarian"],
  UA: ["ukraine", "ukrainian"],
  RU: ["russia", "russian"],
  IL: ["israel", "israeli"],
  IR: ["iran", "iranian"],
  LB: ["lebanon", "lebanese"],
  PS: ["palestine", "palestinian", "gaza", "west bank"]
};

function matchesDiscoveredRegion(
  region: RegionMarket,
  values: Array<string | undefined>
) {
  const text = values.filter(Boolean).join(" ").toLowerCase();
  const aliases =
    region.coverage === "country"
      ? COUNTRY_DISCOVERY_ALIASES[region.countryCode] ?? [
          region.countryLabel.toLowerCase()
        ]
      : [region.label.toLowerCase()];
  return aliases.some((alias) => {
    const escapedAlias = alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(
      `(^|[^a-z0-9])${escapedAlias}(?=$|[^a-z0-9])`,
      "i"
    ).test(text);
  });
}

export function marketMatchesRegion(
  region: RegionMarket | null | undefined,
  market:
    | (Pick<MarketSnapshot, "slug" | "eventSlug"> &
        Partial<Pick<MarketSnapshot, "title">>)
    | null
    | undefined
) {
  if (!region) {
    return true;
  }

  if (!market) {
    return false;
  }

  const slugs = getRegionPolymarketSlugs(region);
  if (
    slugs.includes(market.slug) ||
    Boolean(market.eventSlug && slugs.includes(market.eventSlug))
  ) {
    return true;
  }

  return matchesDiscoveredRegion(region, [
    market.title,
    market.slug,
    market.eventSlug
  ]);
}

export function kalshiMarketMatchesRegion(
  region: RegionMarket | null | undefined,
  market:
    | { eventTicker: string; title: string; outcomeLabel?: string }
    | null
    | undefined
) {
  if (!region || !market) return false;
  if (
    region.kalshiEventTicker &&
    market.eventTicker === region.kalshiEventTicker
  ) {
    return true;
  }
  return matchesDiscoveredRegion(region, [
    market.title,
    market.outcomeLabel,
    market.eventTicker
  ]);
}
