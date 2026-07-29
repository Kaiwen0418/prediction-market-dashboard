import assert from "node:assert/strict";
import test from "node:test";
import { subdivideGlobeBoundaryEdge } from "@/components/maps/globeBoundaryGeometry";

function approximateSpan(
  start: [number, number],
  end: [number, number]
) {
  const longitudeDelta = ((end[0] - start[0] + 540) % 360) - 180;
  const latitudeDelta = end[1] - start[1];
  const latitudeScale = Math.cos(
    ((start[1] + end[1]) / 2) * (Math.PI / 180)
  );
  return Math.hypot(longitudeDelta * latitudeScale, latitudeDelta);
}

test("long globe boundary edges are subdivided to follow the sphere", () => {
  const edges = subdivideGlobeBoundaryEdge([22, 44], [28, 44]);

  assert.ok(edges.length > 1);
  edges.forEach((edge) => {
    assert.ok(approximateSpan(edge.start, edge.end) <= 0.61);
  });
  assert.deepEqual(edges[0].start, [22, 44]);
  assert.deepEqual(edges.at(-1)?.end, [28, 44]);
});

test("globe boundary subdivision uses the short antimeridian path", () => {
  const edges = subdivideGlobeBoundaryEdge(
    [179.5, 50],
    [-179.5, 50]
  );

  assert.ok(edges.length >= 1);
  assert.ok(edges.length <= 3);
  edges.forEach((edge) => {
    assert.ok(approximateSpan(edge.start, edge.end) <= 0.61);
  });
});
