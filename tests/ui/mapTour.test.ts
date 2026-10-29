import assert from "node:assert/strict";
import test from "node:test";
import { getAutoTourRegions } from "@/components/maps/mapTour";
import { REGION_MARKETS } from "@/components/maps/spotlightStates";

test("map tour ranks only verified open high-activity regions", () => {
  const tourRegions = getAutoTourRegions(REGION_MARKETS, []);

  assert.deepEqual(
    tourRegions.map((region) => region.code),
    ["FR", "CA", "BER"]
  );
  assert.ok(!tourRegions.some((region) => region.code === "TX"));
});
