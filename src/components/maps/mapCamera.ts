export type MapCameraPosition = {
  center: [number, number];
  zoom: number;
};

export const MAP_CAMERA_TRANSITION_MS = 1_800;
export const MAP_CAMERA_SETTLE_MS = 600;

function clampProgress(progress: number) {
  return Math.min(1, Math.max(0, progress));
}

function easeInOutCubic(progress: number) {
  const value = clampProgress(progress);
  return value < 0.5
    ? 4 * value * value * value
    : 1 - Math.pow(-2 * value + 2, 3) / 2;
}

function interpolate(from: number, to: number, progress: number) {
  return from + (to - from) * easeInOutCubic(progress);
}

export function getMapTransitionPosition(
  from: MapCameraPosition,
  to: MapCameraPosition,
  progress: number
): MapCameraPosition {
  const value = clampProgress(progress);
  const travelZoom = Math.min(1.25, from.zoom, to.zoom);

  if (value === 0) return from;
  if (value === 1) return to;

  if (value <= 0.25) {
    return {
      center: from.center,
      zoom: interpolate(from.zoom, travelZoom, value / 0.25)
    };
  }

  if (value <= 0.65) {
    const panProgress = (value - 0.25) / 0.4;
    return {
      center:
        panProgress >= 1
          ? to.center
          : [
              interpolate(from.center[0], to.center[0], panProgress),
              interpolate(from.center[1], to.center[1], panProgress)
            ],
      zoom: travelZoom
    };
  }

  return {
    center: to.center,
    zoom: interpolate(travelZoom, to.zoom, (value - 0.65) / 0.35)
  };
}
