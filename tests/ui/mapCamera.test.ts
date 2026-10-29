import assert from "node:assert/strict";
import test from "node:test";
import { getMapTransitionPosition } from "@/components/maps/mapCamera";

const from = {
  center: [-119.4, 36.7] as [number, number],
  zoom: 3.8
};
const to = {
  center: [2.2, 46.3] as [number, number],
  zoom: 7.5
};

test("map camera zooms out, pans, then zooms into the next region", () => {
  assert.deepEqual(getMapTransitionPosition(from, to, 0), from);

  const zoomedOut = getMapTransitionPosition(from, to, 0.25);
  assert.deepEqual(zoomedOut.center, from.center);
  assert.equal(zoomedOut.zoom, 1.25);

  const panned = getMapTransitionPosition(from, to, 0.65);
  assert.deepEqual(panned.center, to.center);
  assert.equal(panned.zoom, 1.25);

  assert.deepEqual(getMapTransitionPosition(from, to, 1), to);
});

test("map camera clamps transition progress", () => {
  assert.deepEqual(getMapTransitionPosition(from, to, -1), from);
  assert.deepEqual(getMapTransitionPosition(from, to, 2), to);
});
