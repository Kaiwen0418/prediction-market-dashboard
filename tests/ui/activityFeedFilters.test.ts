import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_ACTIVITY_FILTERS,
  parseActivityFeedFilters,
  serializeActivityFeedFilters
} from "@/components/maps/activityFeedFilters";

test("activity filters parse a valid shareable query", () => {
  const filters = parseActivityFeedFilters(
    "?region=tx&score=85&volume=10000&signal=whale-flow&window=6"
  );

  assert.deepEqual(filters, {
    mapView: "country",
    countryScope: "global",
    countryCode: "US",
    regionCode: "TX",
    minimumScore: 85,
    minimumVolume: 10_000,
    signalKind: "whale-flow",
    maxAgeHours: 6
  });
});

test("activity filters keep defaults when query parameters are absent", () => {
  assert.deepEqual(parseActivityFeedFilters(""), DEFAULT_ACTIVITY_FILTERS);
});

test("activity filters reject unsupported values", () => {
  const filters = parseActivityFeedFilters(
    "?country=invalid&region=toolong&score=42&signal=unknown&window=3"
  );

  assert.deepEqual(filters, DEFAULT_ACTIVITY_FILTERS);
});

test("activity filter serialization preserves unrelated query values", () => {
  const params = serializeActivityFeedFilters(
    {
      countryCode: "US",
      mapView: "country",
      countryScope: "country",
      regionCode: "PA",
      minimumScore: 70,
      minimumVolume: 100_000,
      signalKind: "poll-divergence",
      maxAgeHours: 24
    },
    "?campaign=general"
  );

  assert.equal(
    params.toString(),
    "campaign=general&scope=country&region=PA&score=70&volume=100000&signal=poll-divergence&window=24"
  );
});

test("activity filters apply the default volume floor and preserve an explicit off state", () => {
  assert.equal(parseActivityFeedFilters("").minimumVolume, 1_000);

  const parsed = parseActivityFeedFilters("?volume=0");
  assert.equal(parsed.minimumVolume, 0);
  assert.equal(serializeActivityFeedFilters(parsed).toString(), "volume=0");
});

test("activity filters preserve the global map view with country context", () => {
  const parsed = parseActivityFeedFilters(
    "?view=world&country=GB&region=SCT&score=70&signal=poll-divergence"
  );

  assert.equal(parsed.mapView, "world");
  assert.equal(parsed.countryScope, "global");
  assert.equal(parsed.countryCode, "GB");
  assert.equal(parsed.regionCode, "SCT");

  const params = serializeActivityFeedFilters(parsed);
  assert.equal(
    params.toString(),
    "view=world&country=GB&region=SCT&score=70&signal=poll-divergence"
  );
});

test("activity filters preserve manual country scope", () => {
  const parsed = parseActivityFeedFilters(
    "?view=country&scope=country&country=GB&region=SCT"
  );

  assert.equal(parsed.mapView, "country");
  assert.equal(parsed.countryScope, "country");

  const params = serializeActivityFeedFilters(parsed);
  assert.equal(
    params.toString(),
    "scope=country&country=GB&region=SCT"
  );
});
