type Position = number[];
type LinearRing = Position[];
type PolygonCoordinates = LinearRing[];
type MultiPolygonCoordinates = PolygonCoordinates[];

type PolygonGeometry = {
  type: "Polygon";
  coordinates: PolygonCoordinates;
};

type MultiPolygonGeometry = {
  type: "MultiPolygon";
  coordinates: MultiPolygonCoordinates;
};

type PolygonFeature = {
  geometry: PolygonGeometry | MultiPolygonGeometry;
  [key: string]: unknown;
};

type PolygonFeatureCollection = {
  type: "FeatureCollection";
  features: PolygonFeature[];
  [key: string]: unknown;
};

function getSignedRingArea(ring: LinearRing) {
  return ring.reduce((area, point, index) => {
    const previous = ring[index === 0 ? ring.length - 1 : index - 1];
    return area + previous[0] * point[1] - point[0] * previous[1];
  }, 0) / 2;
}

function normalizePolygonRings(rings: PolygonCoordinates) {
  return rings.map((ring, index) => {
    const isClockwise = getSignedRingArea(ring) < 0;
    const shouldBeClockwise = index === 0;
    return isClockwise === shouldBeClockwise ? ring : [...ring].reverse();
  });
}

export function normalizeD3PolygonWinding<T>(
  collection: T
): T {
  const source = collection as unknown as PolygonFeatureCollection;

  return {
    ...source,
    features: source.features.map((feature) => ({
      ...feature,
      geometry:
        feature.geometry.type === "Polygon"
          ? {
              ...feature.geometry,
              coordinates: normalizePolygonRings(feature.geometry.coordinates)
            }
          : {
              ...feature.geometry,
              coordinates: feature.geometry.coordinates.map(
                normalizePolygonRings
              )
            }
    }))
  } as unknown as T;
}
