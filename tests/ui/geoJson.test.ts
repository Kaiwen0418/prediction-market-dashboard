import assert from "node:assert/strict";
import test from "node:test";
import ukraineOblasts from "../../src/components/maps/data/ukraine-oblasts.json";
import { normalizeD3PolygonWinding } from "../../src/components/maps/geoJson";

function signedArea(ring: number[][]) {
  return ring.reduce((area, point, index) => {
    const previous = ring[index === 0 ? ring.length - 1 : index - 1];
    return area + previous[0] * point[1] - point[0] * previous[1];
  }, 0) / 2;
}

test("Ukraine oblast polygons use D3-compatible outer-ring winding", () => {
  const normalized = normalizeD3PolygonWinding(ukraineOblasts);

  normalized.features.forEach((feature) => {
    const polygons =
      feature.geometry.type === "Polygon"
        ? [feature.geometry.coordinates]
        : feature.geometry.coordinates;

    polygons.forEach((rings) => {
      assert.ok(signedArea(rings[0]) <= 0);
      rings.slice(1).forEach((ring) => assert.ok(signedArea(ring) >= 0));
    });
  });
});
