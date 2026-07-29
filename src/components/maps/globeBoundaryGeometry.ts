export type GlobeBoundaryPosition = [number, number];

export type GlobeBoundaryEdge = {
  start: GlobeBoundaryPosition;
  end: GlobeBoundaryPosition;
};

export function subdivideGlobeBoundaryEdge(
  start: GlobeBoundaryPosition,
  end: GlobeBoundaryPosition,
  maximumSpanDegrees = 0.6
): GlobeBoundaryEdge[] {
  const longitudeDelta = ((end[0] - start[0] + 540) % 360) - 180;
  const latitudeDelta = end[1] - start[1];
  const latitudeScale = Math.cos(
    ((start[1] + end[1]) / 2) * (Math.PI / 180)
  );
  const angularSpan = Math.hypot(
    longitudeDelta * latitudeScale,
    latitudeDelta
  );
  const segmentCount = Math.max(
    1,
    Math.ceil(angularSpan / maximumSpanDegrees)
  );
  const points = Array.from(
    { length: segmentCount + 1 },
    (_, index): GlobeBoundaryPosition => {
      if (index === segmentCount) return end;
      const progress = index / segmentCount;
      return [
        start[0] + longitudeDelta * progress,
        start[1] + latitudeDelta * progress
      ];
    }
  );

  return points.slice(0, -1).map((point, index) => ({
    start: point,
    end: points[index + 1]
  }));
}
