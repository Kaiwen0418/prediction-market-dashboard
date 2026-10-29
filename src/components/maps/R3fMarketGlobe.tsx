"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject
} from "react";
import { Html, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import Globe from "r3f-globe";
import * as THREE from "three";
import { feature } from "topojson-client";
import usAtlas from "us-atlas/states-10m.json";
import franceRegions from "@/components/maps/data/france-regions.json";
import germanyStates from "@/components/maps/data/germany-states.json";
import ukRegions from "@/components/maps/data/uk-regions.json";
import ukraineOblasts from "@/components/maps/data/ukraine-oblasts.json";
import worldCountries from "@/components/maps/data/world-countries-110m.json";
import {
  appendTradePopupQueue,
  type ExpiringTradePopup
} from "@/components/maps/mapTradePopups";
import { getMarketSignalColor } from "@/components/maps/marketSignals";
import type {
  CountryMarketMap,
  RegionMarket
} from "@/components/maps/spotlightStates";
import { COUNTRY_MARKET_MAPS } from "@/components/maps/spotlightStates";

type Position = [number, number];

type PolygonGeometry = {
  type: "Polygon" | "MultiPolygon";
  coordinates: Position[][] | Position[][][];
};

type MapFeature = {
  id?: string | number;
  properties?: Record<string, unknown>;
  geometry: PolygonGeometry;
};

type GlobePolygon = {
  feature: MapFeature;
  geometry: PolygonGeometry;
  countryCode?: string;
  gradientCenter: Position;
  gradientRadius: number;
  region?: RegionMarket;
  signalScore?: number;
  selected?: boolean;
  layer: "land" | "region";
};

type VolumePillar = {
  lat: number;
  lng: number;
  altitude: number;
  shadowReceiverAltitude: number;
  color: string;
  radius: number;
};

type GlobeTradeLabel = {
  id: string;
  lat: number;
  lng: number;
  text: string;
  selected: boolean;
};

export type GlobeRegionDatum = {
  region: RegionMarket;
  signalScore: number;
  volume24h: number | null;
};

export type GlobeTradeDatum = {
  region: RegionMarket;
  id: string;
  timestamp: string;
  text: string;
};

type R3fMarketGlobeProps = {
  activeCountry: CountryMarketMap;
  regions: GlobeRegionDatum[];
  selectedCode?: string | null;
  trades: GlobeTradeDatum[];
  onSelectCountry: (country: CountryMarketMap) => void;
  onSelectRegion: (region: RegionMarket) => void;
};

type FeatureCollection = {
  features: MapFeature[];
};

const worldFeatureCollection = feature(
  worldCountries as never,
  (worldCountries as any).objects.countries
) as unknown as FeatureCollection;

const WORLD_FEATURES = worldFeatureCollection.features;
const GLOBE_RADIUS = 100;
const GLOBE_SCALE = 1.48;
const GLOBE_INTRO_ROTATION_DURATION_MS = 1200;
const GLOBE_DATA_REVEAL_DELAY_MS =
  GLOBE_INTRO_ROTATION_DURATION_MS + 50;
const COUNTRY_WALL_SIMPLIFICATION_TOLERANCE = 0.08;
const REGION_WALL_SIMPLIFICATION_TOLERANCE = 0.18;
const MARKET_ORBIT_WEST_LONGITUDE = -125;
const MARKET_ORBIT_EAST_LONGITUDE = 55;
const GLOBE_LOCAL_LIGHT_TARGET = new THREE.Vector3(0, 32, 0);
const GLOBE_LOCAL_LIGHT_POSITION = new THREE.Vector3(0, 230, 55);
const GLOBE_LOCAL_LIGHT_RAY = GLOBE_LOCAL_LIGHT_TARGET.clone()
  .sub(GLOBE_LOCAL_LIGHT_POSITION)
  .normalize();
const PROJECTED_PILLAR_CONTACT_SHADOWS_ENABLED = true;
const PROJECTED_SHADOW_DEPTH_OFFSET = 0.045;
const LAND_CAP_ALTITUDE = 0.0045;
const REGION_CAP_ALTITUDE = 0.011;
const SELECTED_REGION_CAP_ALTITUDE = 0.018;
const REGION_WALL_HEIGHT = 0.0018;
const SELECTED_REGION_WALL_HEIGHT = 0.0028;
const SELECTED_COUNTRY_SKIRT_HALF_WIDTH = 0.125;
const SELECTED_COUNTRY_SKIRT_TOP_CLEARANCE = 0.0002;
const WALL_TOP_COLOR = "#f4f2eb";
const LAND_EXTRUSION_SIDE_COLOR = "#9aa6a3";
const COUNTRY_BOUNDARY_CACHE = new Map<string, MapFeature[]>();

function createOceanTextures() {
  const size = 1024;
  const normalData = new Uint8Array(size * size * 4);

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const u = (x / size) * Math.PI * 2;
      const v = (y / size) * Math.PI * 2;
      const dx =
        Math.cos(u * 7 + v * 3) * 0.34 +
        Math.cos(u * 13 - v * 5) * 0.14;
      const dy =
        Math.cos(v * 11 - u * 4) * 0.3 +
        Math.cos(v * 17 + u * 6) * 0.12;
      const normal = new THREE.Vector3(-dx, -dy, 1).normalize();
      const index = (y * size + x) * 4;
      normalData[index] = Math.round((normal.x * 0.5 + 0.5) * 255);
      normalData[index + 1] = Math.round((normal.y * 0.5 + 0.5) * 255);
      normalData[index + 2] = Math.round((normal.z * 0.5 + 0.5) * 255);
      normalData[index + 3] = 255;
    }
  }

  const createTexture = (data: Uint8Array) => {
    const texture = new THREE.DataTexture(
      data,
      size,
      size,
      THREE.RGBAFormat,
      THREE.UnsignedByteType
    );
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(1, 1);
    texture.generateMipmaps = true;
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.needsUpdate = true;
    return texture;
  };

  return {
    normalMap: createTexture(normalData)
  };
}

function createOceanEnvironmentTexture() {
  const width = 1024;
  const height = 512;
  const data = new Uint8Array(width * height * 4);

  for (let y = 0; y < height; y += 1) {
    const v = y / (height - 1);
    const upperGlow = Math.exp(-(((v - 0.74) / 0.16) ** 2));
    const upperHemisphere = Math.max(0, v - 0.48);

    for (let x = 0; x < width; x += 1) {
      const u = x / (width - 1);
      const softVariation =
        Math.sin(u * Math.PI * 4 + v * Math.PI * 2) * 0.04 +
        Math.sin(u * Math.PI * 8 - v * Math.PI * 4) * 0.018;
      const brightness = THREE.MathUtils.clamp(
        0.2 + upperGlow * 0.46 + upperHemisphere * 0.2 + softVariation,
        0,
        1
      );
      const index = (y * width + x) * 4;
      data[index] = Math.round(112 + brightness * 116);
      data[index + 1] = Math.round(151 + brightness * 92);
      data[index + 2] = Math.round(166 + brightness * 82);
      data[index + 3] = 255;
    }
  }

  const texture = new THREE.DataTexture(
    data,
    width,
    height,
    THREE.RGBAFormat,
    THREE.UnsignedByteType
  );
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;
  return texture;
}

function toFeatureCollection(source: unknown, objectKey?: string): FeatureCollection {
  const candidate = source as {
    type?: string;
    features?: MapFeature[];
    objects?: Record<string, unknown>;
  };

  if (candidate.type === "FeatureCollection" && candidate.features) {
    return { features: candidate.features };
  }

  const topologyObject = objectKey
    ? candidate.objects?.[objectKey]
    : Object.values(candidate.objects ?? {})[0];

  if (!topologyObject) {
    return { features: [] };
  }

  return feature(
    source as never,
    topologyObject as never
  ) as unknown as FeatureCollection;
}

function getCountryBoundaryFeatures(country: CountryMarketMap) {
  const cachedFeatures = COUNTRY_BOUNDARY_CACHE.get(country.code);
  if (cachedFeatures) return cachedFeatures;

  let boundaryFeatures: MapFeature[];
  if (country.code === "US") {
    boundaryFeatures = toFeatureCollection(usAtlas, "states").features;
  } else if (country.code === "GB") {
    boundaryFeatures = toFeatureCollection(ukRegions, "UKregionmerc").features;
  } else if (country.code === "FR") {
    boundaryFeatures = toFeatureCollection(franceRegions).features;
  } else if (country.code === "DE") {
    boundaryFeatures = toFeatureCollection(germanyStates).features;
  } else if (country.code === "UA") {
    boundaryFeatures = toFeatureCollection(ukraineOblasts).features;
  } else {
    boundaryFeatures = WORLD_FEATURES.filter((countryFeature) =>
      country.worldFeatureIds.includes(String(countryFeature.id))
    );
  }

  COUNTRY_BOUNDARY_CACHE.set(country.code, boundaryFeatures);
  return boundaryFeatures;
}

function getFeatureId(featureItem: MapFeature, country: CountryMarketMap) {
  if (country.code === "US") {
    return String(featureItem.id).padStart(2, "0");
  }

  if (country.featureIdProperty) {
    return String(featureItem.properties?.[country.featureIdProperty] ?? "");
  }

  return String(featureItem.id);
}

function getRegionKey(region: RegionMarket) {
  return `${region.countryCode}:${region.code}`;
}

function getRegionBoundaryFeature(region: RegionMarket) {
  const country = COUNTRY_MARKET_MAPS.find(
    (candidate) => candidate.code === region.countryCode
  );
  if (!country) return null;

  if (region.coverage === "country") {
    return (
      WORLD_FEATURES.find((worldFeature) =>
        country.worldFeatureIds.includes(String(worldFeature.id))
      ) ?? null
    );
  }

  return (
    getCountryBoundaryFeatures(country).find(
      (boundaryFeature) =>
        getFeatureId(boundaryFeature, country) === region.featureId
    ) ?? null
  );
}

function seededRandom(seed: number) {
  let state = seed || 1;
  return () => {
    state = Math.imul(1664525, state) + 1013904223;
    return (state >>> 0) / 4294967296;
  };
}

function hashString(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function sampleStandardNormal(random: () => number) {
  const first = Math.max(Number.EPSILON, random());
  const second = random();
  return (
    Math.sqrt(-2 * Math.log(first)) *
    Math.cos(Math.PI * 2 * second)
  );
}

function pointInRing(point: Position, ring: Position[]) {
  let inside = false;

  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [x, y] = ring[index];
    const [previousX, previousY] = ring[previous];
    const intersects =
      y > point[1] !== previousY > point[1] &&
      point[0] <
        ((previousX - x) * (point[1] - y)) / (previousY - y || 1e-9) + x;
    if (intersects) inside = !inside;
  }

  return inside;
}

function pointInPolygon(point: Position, polygon: Position[][]) {
  return (
    pointInRing(point, polygon[0]) &&
    !polygon.slice(1).some((hole) => pointInRing(point, hole))
  );
}

function pointInGeometry(point: Position, geometry: PolygonGeometry) {
  return polygonParts(geometry).some((polygon) =>
    pointInPolygon(point, polygon)
  );
}

function polygonParts(geometry: PolygonGeometry): Position[][][] {
  return geometry.type === "Polygon"
    ? [geometry.coordinates as Position[][]]
    : (geometry.coordinates as Position[][][]);
}

function getGeometryCenter(geometry: PolygonGeometry): Position {
  const largestPart = polygonParts(geometry).reduce((largest, part) => {
    const bounds = getBounds(part);
    const largestBounds = getBounds(largest);
    const area =
      (bounds.maxLng - bounds.minLng) * (bounds.maxLat - bounds.minLat);
    const largestArea =
      (largestBounds.maxLng - largestBounds.minLng) *
      (largestBounds.maxLat - largestBounds.minLat);
    return area > largestArea ? part : largest;
  });
  const bounds = getBounds(largestPart);
  return [
    (bounds.minLng + bounds.maxLng) / 2,
    (bounds.minLat + bounds.maxLat) / 2
  ];
}

function getGradientRadius(
  geometry: PolygonGeometry,
  center: Position
) {
  const polygon = chooseRegionGeometry(geometry, center);
  const latitudeScale = Math.cos(THREE.MathUtils.degToRad(center[1]));
  const maximumDistance = polygon[0].reduce((maximum, [lng, lat]) => {
    const longitudeDistance = Math.abs(
      ((lng - center[0] + 540) % 360) - 180
    );
    const distance = Math.hypot(
      longitudeDistance * latitudeScale,
      lat - center[1]
    );
    return Math.max(maximum, distance);
  }, 0);

  return THREE.MathUtils.degToRad(Math.max(1.2, maximumDistance * 0.9));
}

function globePosition(
  [lng, lat]: Position,
  altitude: number,
  target = new THREE.Vector3()
) {
  const latitude = THREE.MathUtils.degToRad(lat);
  const longitude = THREE.MathUtils.degToRad(lng);
  const radius = GLOBE_RADIUS * (1 + altitude);
  return target.set(
    radius * Math.cos(latitude) * Math.sin(longitude),
    radius * Math.sin(latitude),
    radius * Math.cos(latitude) * Math.cos(longitude)
  );
}

type BoundaryWallSegment = {
  start: Position;
  end: Position;
  bottomAltitude: number;
  topAltitude: number;
  halfWidth: number;
  color: THREE.Color;
  sideColor: THREE.Color;
  priority: number;
};

type BoundaryEdge = {
  start: Position;
  end: Position;
};

type RegionalBoundaryPrecision = {
  edgesByPolygon: Map<GlobePolygon, BoundaryEdge[]>;
  perimeter: BoundaryEdge[];
};

function boundarySegmentKey(
  start: Position,
  end: Position,
  precision = 4
) {
  const pointKey = ([lng, lat]: Position) =>
    `${lng.toFixed(precision)},${lat.toFixed(precision)}`;
  const startKey = pointKey(start);
  const endKey = pointKey(end);
  return startKey < endKey
    ? `${startKey}|${endKey}`
    : `${endKey}|${startKey}`;
}

function squaredPointSegmentDistance(
  point: Position,
  start: Position,
  end: Position
) {
  const longitudeScale = Math.cos(
    THREE.MathUtils.degToRad((point[1] + start[1] + end[1]) / 3)
  );
  const pointX = point[0] * longitudeScale;
  const startX = start[0] * longitudeScale;
  const endX = end[0] * longitudeScale;
  const segmentX = endX - startX;
  const segmentY = end[1] - start[1];
  const segmentLengthSquared = segmentX ** 2 + segmentY ** 2;
  const progress =
    segmentLengthSquared === 0
      ? 0
      : THREE.MathUtils.clamp(
          ((pointX - startX) * segmentX +
            (point[1] - start[1]) * segmentY) /
            segmentLengthSquared,
          0,
          1
        );
  const offsetX = pointX - (startX + segmentX * progress);
  const offsetY = point[1] - (start[1] + segmentY * progress);
  return offsetX ** 2 + offsetY ** 2;
}

function simplifyOpenBoundary(points: Position[], tolerance: number) {
  if (points.length <= 2) return points;
  // Iterative Douglas-Peucker avoids deep recursion on detailed boundaries.
  const keep = new Uint8Array(points.length);
  const pending: Array<[number, number]> = [[0, points.length - 1]];
  const toleranceSquared = tolerance ** 2;
  keep[0] = 1;
  keep[points.length - 1] = 1;

  while (pending.length) {
    const [startIndex, endIndex] = pending.pop()!;
    let furthestIndex = -1;
    let furthestDistance = toleranceSquared;

    for (let index = startIndex + 1; index < endIndex; index += 1) {
      const distance = squaredPointSegmentDistance(
        points[index],
        points[startIndex],
        points[endIndex]
      );
      if (distance > furthestDistance) {
        furthestDistance = distance;
        furthestIndex = index;
      }
    }

    if (furthestIndex !== -1) {
      keep[furthestIndex] = 1;
      pending.push(
        [startIndex, furthestIndex],
        [furthestIndex, endIndex]
      );
    }
  }

  return points.filter((_, index) => keep[index]);
}

function simplifyBoundaryRing(ring: Position[], tolerance: number) {
  const points =
    ring.length > 1 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1]
      ? ring.slice(0, -1)
      : ring;
  if (points.length <= 4) return points;

  // Split the closed ring across its widest span so both open halves simplify.
  const longitudeScale = Math.cos(
    THREE.MathUtils.degToRad(points[0][1])
  );
  let splitIndex = 1;
  let splitDistance = 0;
  for (let index = 1; index < points.length; index += 1) {
    const longitudeDistance =
      (points[index][0] - points[0][0]) * longitudeScale;
    const latitudeDistance = points[index][1] - points[0][1];
    const distance = longitudeDistance ** 2 + latitudeDistance ** 2;
    if (distance > splitDistance) {
      splitDistance = distance;
      splitIndex = index;
    }
  }

  const firstHalf = simplifyOpenBoundary(
    points.slice(0, splitIndex + 1),
    tolerance
  );
  const secondHalf = simplifyOpenBoundary(
    [...points.slice(splitIndex), points[0]],
    tolerance
  );
  return [...firstHalf.slice(0, -1), ...secondHalf.slice(0, -1)];
}

function buildRegionalBoundaryPrecision(
  polygons: GlobePolygon[]
): RegionalBoundaryPrecision {
  const edgeCounts = new Map<string, number>();
  const edgeOwners = new Map<string, GlobePolygon>();
  const polygonRings = new Map<GlobePolygon, Position[][]>();

  polygons.forEach((polygon) => {
    const rings = polygonParts(polygon.geometry).map((part) => {
      const ring = part[0];
      return ring.length > 1 &&
        ring[0][0] === ring[ring.length - 1][0] &&
        ring[0][1] === ring[ring.length - 1][1]
        ? ring.slice(0, -1)
        : ring;
    });
    polygonRings.set(polygon, rings);
    rings.forEach((ring) => {
      ring.forEach((start, index) => {
        const end = ring[(index + 1) % ring.length];
        const key = boundarySegmentKey(start, end, 6);
        edgeCounts.set(key, (edgeCounts.get(key) ?? 0) + 1);
        const currentOwner = edgeOwners.get(key);
        if (
          !currentOwner ||
          (polygon.selected && !currentOwner.selected)
        ) {
          edgeOwners.set(key, polygon);
        }
      });
    });
  });

  const edgesByPolygon = new Map<GlobePolygon, BoundaryEdge[]>();
  const perimeter: BoundaryEdge[] = [];
  const appendPath = (
    target: BoundaryEdge[],
    points: Position[],
    close: boolean,
    isPerimeter: boolean
  ) => {
    const edgeCount = close ? points.length : points.length - 1;
    for (let index = 0; index < edgeCount; index += 1) {
      const edge = {
        start: points[index],
        end: points[(index + 1) % points.length]
      };
      target.push(edge);
      if (isPerimeter) perimeter.push(edge);
    }
  };

  polygons.forEach((polygon) => {
    const polygonEdges: BoundaryEdge[] = [];
    (polygonRings.get(polygon) ?? []).forEach((ring) => {
      const classifiedEdges = ring.map((start, index) => {
        const end = ring[(index + 1) % ring.length];
        const key = boundarySegmentKey(start, end, 6);
        const edgeCount = edgeCounts.get(key) ?? 0;
        return {
          start,
          end,
          kind:
            edgeCount === 1
              ? ("perimeter" as const)
              : edgeOwners.get(key) === polygon
                ? ("internal" as const)
                : ("skip" as const)
        };
      });
      if (!classifiedEdges.length) return;

      const allPerimeter = classifiedEdges.every(
        (edge) => edge.kind === "perimeter"
      );
      const allInternal = classifiedEdges.every(
        (edge) => edge.kind === "internal"
      );
      const allSkipped = classifiedEdges.every(
        (edge) => edge.kind === "skip"
      );
      if (allPerimeter) {
        appendPath(
          polygonEdges,
          simplifyBoundaryRing(
            ring,
            COUNTRY_WALL_SIMPLIFICATION_TOLERANCE
          ),
          true,
          true
        );
        return;
      }
      if (allSkipped) return;
      if (allInternal) {
        appendPath(
          polygonEdges,
          simplifyBoundaryRing(
            ring,
            REGION_WALL_SIMPLIFICATION_TOLERANCE
          ),
          true,
          false
        );
        return;
      }

      const firstChangeIndex = classifiedEdges.findIndex(
        (edge, index) =>
          edge.kind !==
          classifiedEdges[
            (index + classifiedEdges.length - 1) % classifiedEdges.length
          ].kind
      );
      const orderedEdges = [
        ...classifiedEdges.slice(firstChangeIndex),
        ...classifiedEdges.slice(0, firstChangeIndex)
      ];
      const runs: typeof classifiedEdges[] = [];
      orderedEdges.forEach((edge) => {
        const currentRun = runs[runs.length - 1];
        if (!currentRun || currentRun[0].kind !== edge.kind) {
          runs.push([edge]);
        } else {
          currentRun.push(edge);
        }
      });

      runs.forEach((run) => {
        if (run[0].kind === "skip") return;
        const points = [run[0].start, ...run.map((edge) => edge.end)];
        const processedPoints = run[0].kind === "perimeter"
          ? simplifyOpenBoundary(
              points,
              COUNTRY_WALL_SIMPLIFICATION_TOLERANCE
            )
          : simplifyOpenBoundary(
              points,
              REGION_WALL_SIMPLIFICATION_TOLERANCE
            );
        appendPath(
          polygonEdges,
          processedPoints,
          false,
          run[0].kind === "perimeter"
        );
      });
    });
    edgesByPolygon.set(polygon, polygonEdges);
  });

  return { edgesByPolygon, perimeter };
}

function createBoundaryWallGeometry(
  polygons: GlobePolygon[],
  {
    edgesByPolygon,
    preciseCountryCode,
    preciseCountryPerimeter
  }: {
    edgesByPolygon?: Map<GlobePolygon, BoundaryEdge[]>;
    preciseCountryCode?: string;
    preciseCountryPerimeter?: BoundaryEdge[];
  } = {}
) {
  const segments = new Map<string, BoundaryWallSegment>();

  polygons.forEach((polygon) => {
    const usesPreciseCountryPerimeter =
      polygon.layer === "land" &&
      polygon.countryCode === preciseCountryCode &&
      Boolean(preciseCountryPerimeter?.length);
    const capAltitude =
      polygon.layer === "land"
        ? LAND_CAP_ALTITUDE
        : polygon.selected
          ? SELECTED_REGION_CAP_ALTITUDE
          : REGION_CAP_ALTITUDE;
    const wallHeight =
      polygon.layer === "region"
        ? polygon.selected
          ? SELECTED_REGION_WALL_HEIGHT
          : REGION_WALL_HEIGHT
        : polygon.selected
          ? SELECTED_REGION_CAP_ALTITUDE -
            LAND_CAP_ALTITUDE +
            SELECTED_REGION_WALL_HEIGHT -
            SELECTED_COUNTRY_SKIRT_TOP_CLEARANCE
          : usesPreciseCountryPerimeter
            ? REGION_CAP_ALTITUDE -
              LAND_CAP_ALTITUDE +
              REGION_WALL_HEIGHT -
              SELECTED_COUNTRY_SKIRT_TOP_CLEARANCE
          : 0.0016;
    const priority =
      polygon.layer === "region" ? (polygon.selected ? 3 : 2) : 1;
    const halfWidth =
      polygon.layer === "region"
        ? polygon.selected
          ? 0.11
          : 0.075
        : polygon.selected
          ? SELECTED_COUNTRY_SKIRT_HALF_WIDTH
          : usesPreciseCountryPerimeter
            ? 0.09
          : 0.055;
    const color = new THREE.Color(
      polygon.layer === "region" || polygon.selected
        ? WALL_TOP_COLOR
        : "#dfe7e4"
    );
    const sideColor = new THREE.Color(LAND_EXTRUSION_SIDE_COLOR);

    const precisePerimeter = usesPreciseCountryPerimeter
      ? preciseCountryPerimeter
      : null;
    const polygonEdges =
      edgesByPolygon?.get(polygon) ??
      precisePerimeter ??
      polygonParts(polygon.geometry).flatMap((part) => {
        const ring =
          polygon.layer === "region"
            ? simplifyBoundaryRing(
                part[0],
                REGION_WALL_SIMPLIFICATION_TOLERANCE
              )
            : part[0];
        return ring.map((start, index) => ({
          start,
          end: ring[(index + 1) % ring.length]
        }));
      });

    polygonEdges.forEach(({ start, end }) => {
      if (
        Math.abs(start[0] - end[0]) < 1e-7 &&
        Math.abs(start[1] - end[1]) < 1e-7
      ) {
        return;
      }
      const key = boundarySegmentKey(start, end);
      if ((segments.get(key)?.priority ?? 0) > priority) return;
      segments.set(key, {
        start,
        end,
        bottomAltitude: capAltitude + 0.0001,
        topAltitude: capAltitude + wallHeight,
        halfWidth,
        color,
        sideColor,
        priority
      });
    });
  });

  const positions: number[] = [];
  const colors: number[] = [];
  const bottomStart = new THREE.Vector3();
  const bottomEnd = new THREE.Vector3();
  const topStart = new THREE.Vector3();
  const topEnd = new THREE.Vector3();
  const radialStart = new THREE.Vector3();
  const radialEnd = new THREE.Vector3();
  const segmentDirection = new THREE.Vector3();
  const sideStart = new THREE.Vector3();
  const sideEnd = new THREE.Vector3();
  const bottomStartLeft = new THREE.Vector3();
  const bottomStartRight = new THREE.Vector3();
  const bottomEndLeft = new THREE.Vector3();
  const bottomEndRight = new THREE.Vector3();
  const topStartLeft = new THREE.Vector3();
  const topStartRight = new THREE.Vector3();
  const topEndLeft = new THREE.Vector3();
  const topEndRight = new THREE.Vector3();
  const pushFace = (points: THREE.Vector3[], color: THREE.Color) => {
    points.forEach((point) => {
      positions.push(point.x, point.y, point.z);
      colors.push(color.r, color.g, color.b);
    });
  };

  segments.forEach((segment) => {
    globePosition(segment.start, segment.bottomAltitude, bottomStart);
    globePosition(segment.end, segment.bottomAltitude, bottomEnd);
    globePosition(segment.start, segment.topAltitude, topStart);
    globePosition(segment.end, segment.topAltitude, topEnd);
    radialStart.copy(bottomStart).normalize();
    radialEnd.copy(bottomEnd).normalize();
    segmentDirection.copy(bottomEnd).sub(bottomStart).normalize();
    sideStart
      .crossVectors(radialStart, segmentDirection)
      .normalize()
      .multiplyScalar(segment.halfWidth);
    sideEnd
      .crossVectors(radialEnd, segmentDirection)
      .normalize()
      .multiplyScalar(segment.halfWidth);
    bottomStartLeft.copy(bottomStart).add(sideStart);
    bottomStartRight.copy(bottomStart).sub(sideStart);
    bottomEndLeft.copy(bottomEnd).add(sideEnd);
    bottomEndRight.copy(bottomEnd).sub(sideEnd);
    topStartLeft.copy(topStart).add(sideStart);
    topStartRight.copy(topStart).sub(sideStart);
    topEndLeft.copy(topEnd).add(sideEnd);
    topEndRight.copy(topEnd).sub(sideEnd);

    const topColor = segment.color;
    pushFace(
      [
        topStartLeft,
        topEndLeft,
        topEndRight,
        topStartLeft,
        topEndRight,
        topStartRight
      ],
      topColor
    );
    pushFace(
      [
        bottomStartLeft,
        bottomEndLeft,
        topEndLeft,
        bottomStartLeft,
        topEndLeft,
        topStartLeft
      ],
      segment.sideColor
    );
    pushFace(
      [
        bottomEndRight,
        bottomStartRight,
        topStartRight,
        bottomEndRight,
        topStartRight,
        topEndRight
      ],
      segment.sideColor
    );
  });

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3)
  );
  geometry.setAttribute(
    "color",
    new THREE.Float32BufferAttribute(colors, 3)
  );
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

function chooseRegionGeometry(geometry: PolygonGeometry, center: Position) {
  const parts = polygonParts(geometry);
  const containingPart = parts.find((polygon) => pointInPolygon(center, polygon));
  return containingPart ?? parts[0];
}

function getBounds(polygon: Position[][]) {
  return polygon[0].reduce(
    (bounds, [lng, lat]) => ({
      minLng: Math.min(bounds.minLng, lng),
      maxLng: Math.max(bounds.maxLng, lng),
      minLat: Math.min(bounds.minLat, lat),
      maxLat: Math.max(bounds.maxLat, lat)
    }),
    {
      minLng: Number.POSITIVE_INFINITY,
      maxLng: Number.NEGATIVE_INFINITY,
      minLat: Number.POSITIVE_INFINITY,
      maxLat: Number.NEGATIVE_INFINITY
    }
  );
}

function volumeProgress(volume24h: number | null, score: number) {
  if (volume24h !== null && Number.isFinite(volume24h)) {
    return Math.log1p(Math.min(500_000, Math.max(0, volume24h))) /
      Math.log1p(500_000);
  }
  return Math.max(0.16, Math.min(0.58, score / 155));
}

function interpolateColor(start: string, end: string, progress: number) {
  const color = new THREE.Color(start);
  color.lerp(new THREE.Color(end), Math.max(0, Math.min(1, progress)));
  return `#${color.getHexString()}`;
}

function adjustColor(
  source: string,
  lightnessDelta: number,
  saturationDelta = 0
) {
  const color = new THREE.Color(source);
  const hsl = { h: 0, s: 0, l: 0 };
  color.getHSL(hsl);
  color.setHSL(
    hsl.h,
    Math.max(0, Math.min(1, hsl.s + saturationDelta)),
    Math.max(0, Math.min(1, hsl.l + lightnessDelta))
  );
  return `#${color.getHexString()}`;
}

function getPolygonScoreColor(polygon: GlobePolygon) {
  if (polygon.layer === "land") {
    return polygon.signalScore === undefined
      ? "#d6d6d1"
      : getMarketSignalColor(polygon.signalScore);
  }
  if (!polygon.region) return "#c8c9c5";
  return polygon.selected
    ? getMarketSignalColor(Math.max(82, polygon.signalScore ?? 0))
    : getMarketSignalColor(polygon.signalScore ?? 0);
}

function getGlobeSignalColor(score: number) {
  const baseColor = getMarketSignalColor(score);
  return score < 50
    ? adjustColor(baseColor, -0.025, 0.24)
    : adjustColor(baseColor, -0.01, 0.08);
}

function createGradientCapMaterial(polygon: GlobePolygon) {
  const baseColor = getPolygonScoreColor(polygon);
  const centerColor =
    polygon.signalScore === undefined
      ? baseColor
      : polygon.selected
        ? adjustColor(baseColor, -0.025, 0.1)
        : getGlobeSignalColor(polygon.signalScore);
  const edgeColor =
    polygon.signalScore === undefined
      ? adjustColor(centerColor, 0.035, -0.08)
      : adjustColor(centerColor, 0.105, -0.5);
  const [lng, lat] = polygon.gradientCenter;
  const latitude = THREE.MathUtils.degToRad(lat);
  const longitude = THREE.MathUtils.degToRad(lng);
  const centerDirection = new THREE.Vector3(
    Math.cos(latitude) * Math.sin(longitude),
    Math.sin(latitude),
    Math.cos(latitude) * Math.cos(longitude)
  ).normalize();
  const material = new THREE.MeshStandardMaterial({
    color: centerColor,
    roughness: 0.78,
    metalness: 0,
    envMapIntensity: 0.22,
    transparent: false,
    opacity: 1,
    depthWrite: true
  });

  material.onBeforeCompile = (shader) => {
    shader.uniforms.marketGradientCenter = { value: centerDirection };
    shader.uniforms.marketGradientRadius = {
      value: polygon.gradientRadius
    };
    shader.uniforms.marketCenterColor = {
      value: new THREE.Color(centerColor)
    };
    shader.uniforms.marketEdgeColor = {
      value: new THREE.Color(edgeColor)
    };
    shader.vertexShader = shader.vertexShader
      .replace(
        "void main() {",
        "varying vec3 vMarketGlobeDirection;\nvoid main() {"
      )
      .replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nvMarketGlobeDirection = normalize(position);"
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "void main() {",
        [
          "uniform vec3 marketGradientCenter;",
          "uniform float marketGradientRadius;",
          "uniform vec3 marketCenterColor;",
          "uniform vec3 marketEdgeColor;",
          "varying vec3 vMarketGlobeDirection;",
          "void main() {"
        ].join("\n")
      )
      .replace(
        "vec4 diffuseColor = vec4( diffuse, opacity );",
        [
          "float marketAngularDistance = acos(clamp(dot(normalize(vMarketGlobeDirection), marketGradientCenter), -1.0, 1.0));",
          "float marketEdgeMix = smoothstep(marketGradientRadius * 0.04, marketGradientRadius * 0.82, marketAngularDistance);",
          "vec3 marketGradientColor = mix(marketCenterColor, marketEdgeColor, marketEdgeMix);",
          "vec4 diffuseColor = vec4(marketGradientColor, opacity);"
        ].join("\n")
      );
  };
  material.customProgramCacheKey = () => "market-gradient-cap-v2";
  return material;
}

function createRegionPillars(
  datum: GlobeRegionDatum,
  mapFeature: MapFeature,
  selected: boolean,
  focusedCountry: boolean
) {
  const polygon = chooseRegionGeometry(mapFeature.geometry, datum.region.center);
  const bounds = getBounds(polygon);
  const progress = volumeProgress(datum.volume24h, datum.signalScore);
  const requestedCount = Math.round(
    (12 + progress * 104) *
      (selected ? 1.38 : 1) *
      (focusedCountry ? 1 : 0.66)
  );
  const count = Math.min(
    requestedCount,
    focusedCountry ? (selected ? 76 : 48) : 24
  );
  const random = seededRandom(
    hashString(`${datum.region.countryCode}:${datum.region.code}:r3f-volume`)
  );
  const spanLng = Math.max(0.5, bounds.maxLng - bounds.minLng);
  const spanLat = Math.max(0.5, bounds.maxLat - bounds.minLat);
  const proposedCenter = datum.region.center;
  const mountainCenter: Position = pointInPolygon(proposedCenter, polygon)
    ? proposedCenter
    : [
        (bounds.minLng + bounds.maxLng) / 2,
        (bounds.minLat + bounds.maxLat) / 2
      ];
  const scoreColor = getGlobeSignalColor(datum.signalScore);
  const colorRange = [
    adjustColor(scoreColor, selected ? -0.26 : -0.2, 0.04),
    adjustColor(scoreColor, selected ? 0.08 : 0.04, 0.02)
  ];
  const countryScale =
    datum.region.countryCode === "US"
      ? 1.32
      : datum.region.countryCode === "RU"
        ? 1.35
        : 1;
  const points: VolumePillar[] = [];
  let attempts = 0;

  while (points.length < count && attempts < count * 90) {
    attempts += 1;
    const clusteredSample = random() < 0.88;
    const lng = clusteredSample
      ? mountainCenter[0] + sampleStandardNormal(random) * spanLng * 0.135
      : bounds.minLng + random() * spanLng;
    const lat = clusteredSample
      ? mountainCenter[1] + sampleStandardNormal(random) * spanLat * 0.135
      : bounds.minLat + random() * spanLat;
    if (!pointInPolygon([lng, lat], polygon)) continue;

    const normalizedX = (lng - mountainCenter[0]) / (spanLng * 0.18);
    const normalizedY = (lat - mountainCenter[1]) / (spanLat * 0.18);
    const radialDistanceSquared =
      normalizedX * normalizedX + normalizedY * normalizedY;
    const gaussianWeight = Math.max(
      0.01,
      Math.exp(-0.5 * radialDistanceSquared) ** 1.55
    );
    const colorWeight = Math.min(
      1,
      gaussianWeight * 1.55 + random() * 0.1
    );
    const focusScale = focusedCountry ? 1 : 0.62;
    const edgeFloor = (0.006 + progress * 0.008) * focusScale;
    const peak =
      (0.038 + progress * 0.1) *
      (selected ? 1.12 : 1) *
      countryScale *
      focusScale *
      (focusedCountry ? 1.04 : 1);
    const heightSample = random();
    const centralSpike =
      gaussianWeight > 0.48 && heightSample > 0.93;
    const heightVariation = centralSpike
      ? 1.22 + random() * 0.42
      : 0.24 + Math.pow(heightSample, 2.5) * 0.76;
    const mountainWeight = gaussianWeight ** 2.05;
    const altitude =
      edgeFloor + peak * mountainWeight * heightVariation;

    points.push({
      lat,
      lng,
      altitude: Math.min(
        altitude,
        focusedCountry ? (selected ? 0.13 : 0.115) : 0.07
      ),
      shadowReceiverAltitude: focusedCountry
        ? selected
          ? SELECTED_REGION_CAP_ALTITUDE
          : REGION_CAP_ALTITUDE
        : 0,
      color: interpolateColor(colorRange[0], colorRange[1], colorWeight),
      radius:
        (0.017 +
          progress * 0.016 +
          gaussianWeight * 0.026 +
          random() * 0.007) *
        (focusedCountry ? 1 : 0.82)
    });
  }

  return points;
}

function GlobeCamera({ distance }: { distance: number }) {
  const { camera, size } = useThree();
  const compact = size.width < 520;

  useEffect(() => {
    camera.position.set(0, 35, compact ? distance * 1.1 : distance);
    camera.lookAt(0, 45, 0);
  }, [camera, compact, distance]);

  return null;
}

function GlobeControls({
  distance,
  focusLongitude
}: {
  distance: number;
  focusLongitude: number;
}) {
  const { gl, invalidate, size } = useThree();
  const compact = size.width < 520;
  const minimumAzimuth = Math.min(
    0,
    Math.max(
      -Math.PI * 0.96,
      THREE.MathUtils.degToRad(
        MARKET_ORBIT_WEST_LONGITUDE - focusLongitude
      )
    )
  );
  const maximumAzimuth = Math.max(
    0,
    Math.min(
      Math.PI * 0.96,
      THREE.MathUtils.degToRad(
        MARKET_ORBIT_EAST_LONGITUDE - focusLongitude
      )
    )
  );
  const refreshShadows = () => {
    gl.shadowMap.needsUpdate = true;
    invalidate();
  };

  return (
    <OrbitControls
      enablePan={false}
      enableDamping
      dampingFactor={0.075}
      rotateSpeed={0.34}
      zoomSpeed={0.65}
      target={[0, 43, 0]}
      minDistance={(compact ? distance * 1.1 : distance) - 30}
      maxDistance={(compact ? distance * 1.1 : distance) + 80}
      minAzimuthAngle={minimumAzimuth}
      maxAzimuthAngle={maximumAzimuth}
      minPolarAngle={Math.PI * 0.27}
      maxPolarAngle={Math.PI * 0.515}
      onStart={refreshShadows}
      onChange={refreshShadows}
      onEnd={refreshShadows}
    />
  );
}

function AtmosphericFog({ distance }: { distance: number }) {
  const { size } = useThree();
  const compact = size.width < 520;
  const effectiveDistance = compact ? distance * 1.1 : distance;
  const worldRadius = GLOBE_RADIUS * GLOBE_SCALE;
  const surfaceDistance = Math.max(1, effectiveDistance - worldRadius);
  const horizonDistance = Math.sqrt(
    Math.max(1, effectiveDistance ** 2 - worldRadius ** 2)
  );
  const fogNear =
    surfaceDistance + (horizonDistance - surfaceDistance) * 0.58;
  const fogFar = horizonDistance + 24;

  return <fog attach="fog" args={["#d8e8ec", fogNear, fogFar]} />;
}

function PersistentGlobeShadowRegistry({ revision }: { revision: string }) {
  const { gl, scene } = useThree();
  const registeredMeshes = useRef(new WeakSet<THREE.Mesh>());
  const forceShadowRefresh = useRef(true);

  useEffect(() => {
    forceShadowRefresh.current = true;
    gl.shadowMap.needsUpdate = true;
  }, [gl, revision]);

  useFrame(() => {
    let registrationChanged = false;

    scene.traverse((object) => {
      const mesh = object as THREE.Mesh & { __globeObjType?: string };
      if (!mesh.isMesh || mesh.userData.skipShadowRegistration === true) return;
      const globeObjectType = mesh.__globeObjType;
      const materials = Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material];
      const isAtmosphere = globeObjectType === "atmosphere";
      const isOcean = materials.some(
        (material) => material.name === "reflective-ocean"
      );
      const isPillar =
        globeObjectType === "point" || globeObjectType === "points";
      const shouldCastShadow = !isAtmosphere && !isOcean;
      const shouldReceiveShadow = !isAtmosphere && !isPillar;

      if (
        !registeredMeshes.current.has(mesh) ||
        mesh.castShadow !== shouldCastShadow ||
        mesh.receiveShadow !== shouldReceiveShadow
      ) {
        mesh.castShadow = shouldCastShadow;
        mesh.receiveShadow = shouldReceiveShadow;
        registeredMeshes.current.add(mesh);
        registrationChanged = true;
      }
    });

    if (registrationChanged || forceShadowRefresh.current) {
      gl.shadowMap.needsUpdate = true;
      forceShadowRefresh.current = false;
    }
  });

  return null;
}

function RendererLightingSetup() {
  const { gl } = useThree();

  useEffect(() => {
    const previousToneMapping = gl.toneMapping;
    const previousExposure = gl.toneMappingExposure;
    const previousShadowEnabled = gl.shadowMap.enabled;
    const previousShadowType = gl.shadowMap.type;
    const previousShadowAutoUpdate = gl.shadowMap.autoUpdate;
    gl.toneMapping = THREE.ACESFilmicToneMapping;
    gl.toneMappingExposure = 1.04;
    gl.shadowMap.enabled = true;
    gl.shadowMap.type = THREE.PCFShadowMap;
    gl.shadowMap.autoUpdate = true;
    gl.shadowMap.needsUpdate = true;

    return () => {
      gl.toneMapping = previousToneMapping;
      gl.toneMappingExposure = previousExposure;
      gl.shadowMap.enabled = previousShadowEnabled;
      gl.shadowMap.type = previousShadowType;
      gl.shadowMap.autoUpdate = previousShadowAutoUpdate;
    };
  }, [gl]);

  return null;
}

function GlobeFixedShadowLight({
  globeGroupRef
}: {
  globeGroupRef: RefObject<THREE.Group | null>;
}) {
  const light = useRef<THREE.DirectionalLight>(null);
  const target = useRef<THREE.Object3D>(null);
  const worldLightPosition = useRef(new THREE.Vector3());
  const worldLightTarget = useRef(new THREE.Vector3());

  useFrame(() => {
    const globeGroup = globeGroupRef.current;
    if (!globeGroup || !light.current || !target.current) return;

    globeGroup.updateWorldMatrix(true, false);
    worldLightPosition.current
      .copy(GLOBE_LOCAL_LIGHT_POSITION)
      .applyMatrix4(globeGroup.matrixWorld);
    worldLightTarget.current
      .copy(GLOBE_LOCAL_LIGHT_TARGET)
      .applyMatrix4(globeGroup.matrixWorld);
    light.current.position.copy(worldLightPosition.current);
    target.current.position.copy(worldLightTarget.current);
    target.current.updateMatrixWorld();
    light.current.target = target.current;
  });

  return (
    <>
      <object3D ref={target} />
      <directionalLight
        ref={light}
        castShadow
        position={[0, 340, 80]}
        intensity={2.7}
        color="#fffaf0"
        shadow-bias={-0.00006}
        shadow-normalBias={0.015}
        shadow-radius={1.8}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={70}
        shadow-camera-far={520}
        shadow-camera-left={-152}
        shadow-camera-right={152}
        shadow-camera-top={152}
        shadow-camera-bottom={-152}
      />
    </>
  );
}

function normalizeSurfaceTangent(
  tangent: THREE.Vector3,
  surfaceNormal: THREE.Vector3
) {
  tangent.addScaledVector(surfaceNormal, -tangent.dot(surfaceNormal));
  if (tangent.lengthSq() < 1e-8) {
    tangent.set(
      Math.abs(surfaceNormal.y) > 0.9 ? 1 : 0,
      Math.abs(surfaceNormal.y) > 0.9 ? 0 : 1,
      0
    );
    tangent.addScaledVector(surfaceNormal, -tangent.dot(surfaceNormal));
  }
  return tangent.normalize();
}

function ProjectedPillarContactShadows({
  pillars
}: {
  pillars: VolumePillar[];
}) {
  const ribbonGeometry = useMemo(() => new THREE.BufferGeometry(), []);
  const contactGeometry = useMemo(() => new THREE.BufferGeometry(), []);
  const ribbonMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: "#263033",
        transparent: true,
        opacity: 0.115,
        depthTest: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -1.5,
        polygonOffsetUnits: -2,
        toneMapped: false
      }),
    []
  );
  const contactMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: "#1d2729",
        transparent: true,
        opacity: 0.17,
        depthTest: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -3,
        toneMapped: false
      }),
    []
  );
  const ribbonMesh = useMemo(() => {
    const value = new THREE.Mesh(ribbonGeometry, ribbonMaterial);
    value.frustumCulled = false;
    value.renderOrder = 8;
    value.userData.skipShadowRegistration = true;
    return value;
  }, [ribbonGeometry, ribbonMaterial]);
  const contactMesh = useMemo(() => {
    const value = new THREE.Mesh(contactGeometry, contactMaterial);
    value.frustumCulled = false;
    value.renderOrder = 9;
    value.userData.skipShadowRegistration = true;
    return value;
  }, [contactGeometry, contactMaterial]);
  const shadowGroup = useMemo(() => {
    const value = new THREE.Group();
    value.add(ribbonMesh, contactMesh);
    return value;
  }, [contactMesh, ribbonMesh]);
  const rayLocal = useRef(new THREE.Vector3());
  const pillarRay = useRef(new THREE.Vector3());
  const normal = useRef(new THREE.Vector3());
  const pillarTop = useRef(new THREE.Vector3());
  const hitPoint = useRef(new THREE.Vector3());
  const shadowTangent = useRef(new THREE.Vector3());
  const shadowSide = useRef(new THREE.Vector3());
  const curvePoint = useRef(new THREE.Vector3());
  const previousCurvePoint = useRef(new THREE.Vector3());
  const nextCurvePoint = useRef(new THREE.Vector3());
  const leftPoint = useRef(new THREE.Vector3());
  const rightPoint = useRef(new THREE.Vector3());
  const nextLeftPoint = useRef(new THREE.Vector3());
  const nextRightPoint = useRef(new THREE.Vector3());
  const contactPoint = useRef(new THREE.Vector3());
  const nextContactPoint = useRef(new THREE.Vector3());

  useEffect(
    () => () => {
      ribbonGeometry.dispose();
      contactGeometry.dispose();
      ribbonMaterial.dispose();
      contactMaterial.dispose();
    },
    [contactGeometry, contactMaterial, ribbonGeometry, ribbonMaterial]
  );

  useEffect(() => {
    rayLocal.current.copy(GLOBE_LOCAL_LIGHT_RAY);

    const ribbonPositions: number[] = [];
    const contactPositions: number[] = [];

    pillars.forEach((pillar, pillarIndex) => {
      if (pillar.altitude <= 0.012 || pillarIndex % 2 !== 0) return;
      const receiverRadius =
        GLOBE_RADIUS * (1 + pillar.shadowReceiverAltitude);
      const displayRadius =
        receiverRadius + PROJECTED_SHADOW_DEPTH_OFFSET;
      const latitude = THREE.MathUtils.degToRad(pillar.lat);
      const longitude = THREE.MathUtils.degToRad(pillar.lng);
      normal.current
        .set(
          Math.cos(latitude) * Math.sin(longitude),
          Math.sin(latitude),
          Math.cos(latitude) * Math.cos(longitude)
        )
        .normalize();
      pillarTop.current
        .copy(normal.current)
        .multiplyScalar(GLOBE_RADIUS * (1 + pillar.altitude));

      pillarRay.current.copy(rayLocal.current);
      const inwardProjection = pillarRay.current.dot(normal.current);
      if (inwardProjection > -0.2) {
        pillarRay.current
          .addScaledVector(normal.current, -0.2 - inwardProjection)
          .normalize();
      }
      const projection =
        pillarTop.current.dot(pillarRay.current);
      const discriminant =
        projection * projection -
        (pillarTop.current.lengthSq() -
          receiverRadius * receiverRadius);
      if (discriminant <= 0) return;

      const distance = -projection - Math.sqrt(discriminant);
      if (distance <= 0) return;
      hitPoint.current
        .copy(pillarTop.current)
        .addScaledVector(pillarRay.current, distance)
        .normalize();
      const angularDistance = normal.current.angleTo(hitPoint.current);
      if (angularDistance > 0.065) {
        hitPoint.current
          .copy(normal.current)
          .lerp(hitPoint.current, 0.065 / angularDistance)
          .normalize();
      }
      const rootHalfWidth = THREE.MathUtils.clamp(
        0.2 + pillar.radius * 2.5 + pillar.altitude * 0.85,
        0.22,
        0.46
      );
      const ribbonSegments = 5;

      previousCurvePoint.current
        .copy(normal.current)
        .multiplyScalar(displayRadius);
      for (let segment = 0; segment < ribbonSegments; segment += 1) {
        const progress = segment / ribbonSegments;
        const nextProgress = (segment + 1) / ribbonSegments;
        nextCurvePoint.current
          .copy(normal.current)
          .lerp(hitPoint.current, nextProgress)
          .normalize()
          .multiplyScalar(displayRadius);
        curvePoint.current
          .copy(previousCurvePoint.current)
          .normalize();
        shadowTangent.current
          .copy(nextCurvePoint.current)
          .sub(previousCurvePoint.current);
        normalizeSurfaceTangent(
          shadowTangent.current,
          curvePoint.current
        );
        shadowSide.current
          .crossVectors(curvePoint.current, shadowTangent.current)
          .normalize();

        const halfWidth = THREE.MathUtils.lerp(
          rootHalfWidth,
          rootHalfWidth * 0.2,
          progress
        );
        const nextHalfWidth = THREE.MathUtils.lerp(
          rootHalfWidth,
          rootHalfWidth * 0.2,
          nextProgress
        );
        leftPoint.current
          .copy(previousCurvePoint.current)
          .addScaledVector(shadowSide.current, halfWidth)
          .normalize()
          .multiplyScalar(displayRadius);
        rightPoint.current
          .copy(previousCurvePoint.current)
          .addScaledVector(shadowSide.current, -halfWidth)
          .normalize()
          .multiplyScalar(displayRadius);
        nextLeftPoint.current
          .copy(nextCurvePoint.current)
          .addScaledVector(shadowSide.current, nextHalfWidth)
          .normalize()
          .multiplyScalar(displayRadius);
        nextRightPoint.current
          .copy(nextCurvePoint.current)
          .addScaledVector(shadowSide.current, -nextHalfWidth)
          .normalize()
          .multiplyScalar(displayRadius);

        ribbonPositions.push(
          leftPoint.current.x,
          leftPoint.current.y,
          leftPoint.current.z,
          rightPoint.current.x,
          rightPoint.current.y,
          rightPoint.current.z,
          nextLeftPoint.current.x,
          nextLeftPoint.current.y,
          nextLeftPoint.current.z,
          rightPoint.current.x,
          rightPoint.current.y,
          rightPoint.current.z,
          nextRightPoint.current.x,
          nextRightPoint.current.y,
          nextRightPoint.current.z,
          nextLeftPoint.current.x,
          nextLeftPoint.current.y,
          nextLeftPoint.current.z
        );
        previousCurvePoint.current.copy(nextCurvePoint.current);
      }

      shadowTangent.current
        .copy(hitPoint.current)
        .sub(normal.current);
      normalizeSurfaceTangent(shadowTangent.current, normal.current);
      shadowSide.current
        .crossVectors(normal.current, shadowTangent.current)
        .normalize();
      const contactCenter = curvePoint.current
        .copy(normal.current)
        .addScaledVector(
          shadowTangent.current,
          rootHalfWidth * 0.22 / displayRadius
        )
        .normalize()
        .multiplyScalar(displayRadius);
      const contactSegments = 10;
      for (let segment = 0; segment < contactSegments; segment += 1) {
        const angle = (segment / contactSegments) * Math.PI * 2;
        const nextAngle = ((segment + 1) / contactSegments) * Math.PI * 2;
        contactPoint.current
          .copy(contactCenter)
          .addScaledVector(
            shadowTangent.current,
            Math.cos(angle) * rootHalfWidth * 1.4
          )
          .addScaledVector(
            shadowSide.current,
            Math.sin(angle) * rootHalfWidth
          )
          .normalize()
          .multiplyScalar(displayRadius);
        nextContactPoint.current
          .copy(contactCenter)
          .addScaledVector(
            shadowTangent.current,
            Math.cos(nextAngle) * rootHalfWidth * 1.4
          )
          .addScaledVector(
            shadowSide.current,
            Math.sin(nextAngle) * rootHalfWidth
          )
          .normalize()
          .multiplyScalar(displayRadius);
        contactPositions.push(
          contactCenter.x,
          contactCenter.y,
          contactCenter.z,
          contactPoint.current.x,
          contactPoint.current.y,
          contactPoint.current.z,
          nextContactPoint.current.x,
          nextContactPoint.current.y,
          nextContactPoint.current.z
        );
      }
    });

    ribbonGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(ribbonPositions, 3)
    );
    contactGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(contactPositions, 3)
    );
  }, [contactGeometry, pillars, ribbonGeometry]);

  return <primitive object={shadowGroup} />;
}

function BoundaryWalls({
  polygons,
  edgesByPolygon,
  preciseCountryCode,
  preciseCountryPerimeter
}: {
  polygons: GlobePolygon[];
  edgesByPolygon?: Map<GlobePolygon, BoundaryEdge[]>;
  preciseCountryCode?: string;
  preciseCountryPerimeter?: BoundaryEdge[];
}) {
  const geometry = useMemo(
    () =>
      createBoundaryWallGeometry(polygons, {
        edgesByPolygon,
        preciseCountryCode,
        preciseCountryPerimeter
      }),
    [
      edgesByPolygon,
      polygons,
      preciseCountryCode,
      preciseCountryPerimeter
    ]
  );
  const material = useMemo(() => {
    const value = new THREE.MeshStandardMaterial({
      vertexColors: true,
      flatShading: false,
      roughness: 0.72,
      metalness: 0,
      envMapIntensity: 0.1,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1
    });
    value.shadowSide = THREE.DoubleSide;
    return value;
  }, []);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material]
  );

  return (
    <mesh
      geometry={geometry}
      material={material}
      castShadow
      receiveShadow={false}
      userData={{ skipShadowRegistration: true }}
      renderOrder={6}
    />
  );
}

function OceanReflectionEnvironment() {
  const { gl, scene } = useThree();

  useEffect(() => {
    const previousEnvironment = scene.environment;
    const pmremGenerator = new THREE.PMREMGenerator(gl);
    const environmentTexture = createOceanEnvironmentTexture();
    const environmentTarget =
      pmremGenerator.fromEquirectangular(environmentTexture);
    scene.environment = environmentTarget.texture;

    return () => {
      scene.environment = previousEnvironment;
      environmentTarget.dispose();
      environmentTexture.dispose();
      pmremGenerator.dispose();
    };
  }, [gl, scene]);

  return null;
}

export function R3fMarketGlobe({
  activeCountry,
  regions,
  selectedCode,
  trades,
  onSelectCountry,
  onSelectRegion
}: R3fMarketGlobeProps) {
  const globeGroupRef = useRef<THREE.Group>(null);
  const introRevealTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );
  const introRevealStartedRef = useRef(false);
  const [introDataVisible, setIntroDataVisible] = useState(false);
  const seenTradeIdsRef = useRef(new Set<string>());
  const seenTradeOrderRef = useRef<string[]>([]);
  const tradeScopeRef = useRef(activeCountry.code);
  const [tradePopupQueue, setTradePopupQueue] = useState<
    ExpiringTradePopup<GlobeTradeDatum>[]
  >([]);
  const handleGlobeReady = useCallback(() => {
    if (introRevealStartedRef.current) return;
    introRevealStartedRef.current = true;
    introRevealTimeoutRef.current = setTimeout(() => {
      setIntroDataVisible(true);
      introRevealTimeoutRef.current = null;
    }, GLOBE_DATA_REVEAL_DELAY_MS);
  }, []);
  useEffect(
    () => () => {
      if (introRevealTimeoutRef.current) {
        clearTimeout(introRevealTimeoutRef.current);
      }
    },
    []
  );
  const boundaryFeatures = useMemo(
    () => getCountryBoundaryFeatures(activeCountry),
    [activeCountry]
  );
  const activeRegions = useMemo(
    () =>
      regions.filter(
        ({ region }) => region.countryCode === activeCountry.code
      ),
    [activeCountry.code, regions]
  );
  const nationalRegion = regions.find(
    ({ region }) =>
      region.countryCode === activeCountry.code &&
      region.coverage === "country"
  );
  const regionByFeatureId = useMemo(
    () =>
      new Map(
        activeRegions
          .filter(({ region }) => region.coverage !== "country")
          .map((datum) => [datum.region.featureId, datum])
      ),
    [activeRegions]
  );
  const regionalPolygons = useMemo<GlobePolygon[]>(
    () =>
      boundaryFeatures.map((boundaryFeature) => {
        const datum =
          regionByFeatureId.get(
            getFeatureId(boundaryFeature, activeCountry)
          ) ?? nationalRegion;

        return {
          feature: boundaryFeature,
          geometry: boundaryFeature.geometry,
          gradientCenter:
            datum?.region.center ?? getGeometryCenter(boundaryFeature.geometry),
          gradientRadius: getGradientRadius(
            boundaryFeature.geometry,
            datum?.region.center ?? getGeometryCenter(boundaryFeature.geometry)
          ),
          region: datum?.region,
          signalScore: datum?.signalScore,
          selected: datum?.region.code === selectedCode,
          layer: "region"
        };
      }),
    [
      activeCountry,
      boundaryFeatures,
      nationalRegion,
      regionByFeatureId,
      selectedCode
    ]
  );
  const regionalBoundaryPrecision = useMemo(
    () => buildRegionalBoundaryPrecision(regionalPolygons),
    [regionalPolygons]
  );
  const worldPolygons = useMemo<GlobePolygon[]>(
    () => {
      const countryScoreByCode = new Map<string, number>();
      const countryDatumByCode = new Map<string, GlobeRegionDatum>();
      regions.forEach((datum) => {
        const { region, signalScore } = datum;
        const existingScore = countryScoreByCode.get(region.countryCode);
        if (existingScore === undefined || signalScore > existingScore) {
          countryScoreByCode.set(region.countryCode, signalScore);
          countryDatumByCode.set(region.countryCode, datum);
        }
      });

      return WORLD_FEATURES.map((worldFeature) => {
        const country = COUNTRY_MARKET_MAPS.find((candidate) =>
          candidate.worldFeatureIds.includes(String(worldFeature.id))
        );
        const countryDatum = country
          ? countryDatumByCode.get(country.code)
          : undefined;
        const gradientCenter =
          countryDatum?.region.center ??
          getGeometryCenter(worldFeature.geometry);
        return {
          feature: worldFeature,
          geometry: worldFeature.geometry,
          countryCode: country?.code,
          gradientCenter,
          gradientRadius: getGradientRadius(
            worldFeature.geometry,
            gradientCenter
          ),
          signalScore: country
            ? countryScoreByCode.get(country.code)
            : undefined,
          selected:
            country?.code === activeCountry.code &&
            nationalRegion?.region.code === selectedCode,
          layer: "land" as const
        };
      });
    },
    [activeCountry.code, nationalRegion, regions, selectedCode]
  );
  const worldPolygonCapMaterials = useMemo(
    () =>
      new Map(
        worldPolygons.map((polygon) => [
          polygon,
          createGradientCapMaterial(polygon)
        ])
      ),
    [worldPolygons]
  );
  useEffect(
    () => () => {
      worldPolygonCapMaterials.forEach((material) => material.dispose());
    },
    [worldPolygonCapMaterials]
  );
  const regionalPolygonCapMaterials = useMemo(
    () =>
      new Map(
        regionalPolygons.map((polygon) => [
          polygon,
          createGradientCapMaterial(polygon)
        ])
      ),
    [regionalPolygons]
  );
  useEffect(
    () => () => {
      regionalPolygonCapMaterials.forEach((material) => material.dispose());
    },
    [regionalPolygonCapMaterials]
  );
  const polygonSideMaterial = useMemo(
    () => {
      const material = new THREE.MeshStandardMaterial({
        color: LAND_EXTRUSION_SIDE_COLOR,
        roughness: 0.74,
        metalness: 0,
        envMapIntensity: 0.1,
        side: THREE.DoubleSide
      });
      material.onBeforeCompile = (shader) => {
        shader.fragmentShader = shader.fragmentShader.replaceAll(
          "&& receiveShadow",
          "&& false"
        );
      };
      material.customProgramCacheKey = () =>
        "market-polygon-side-without-received-shadows-v1";
      return material;
    },
    []
  );
  const hiddenPolygonSideMaterial = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
        colorWrite: false,
        side: THREE.DoubleSide
      }),
    []
  );
  useEffect(
    () => () => {
      polygonSideMaterial.dispose();
      hiddenPolygonSideMaterial.dispose();
    },
    [hiddenPolygonSideMaterial, polygonSideMaterial]
  );
  const selectablePolygons = useMemo(
    () => [...worldPolygons, ...regionalPolygons],
    [regionalPolygons, worldPolygons]
  );
  const getWorldPolygonCapMaterial = useCallback(
    (polygon: object) =>
      worldPolygonCapMaterials.get(polygon as GlobePolygon)!,
    [worldPolygonCapMaterials]
  );
  const getRegionalPolygonCapMaterial = useCallback(
    (polygon: object) =>
      regionalPolygonCapMaterials.get(polygon as GlobePolygon)!,
    [regionalPolygonCapMaterials]
  );
  const nationalFocusSelected =
    nationalRegion?.region.code === selectedCode;
  const getWorldPolygonSideMaterial = useCallback(
    () => polygonSideMaterial,
    [polygonSideMaterial]
  );
  const getRegionalPolygonSideMaterial = useCallback(
    (polygon: object) =>
      !nationalFocusSelected && (polygon as GlobePolygon).selected
        ? polygonSideMaterial
        : hiddenPolygonSideMaterial,
    [
      hiddenPolygonSideMaterial,
      nationalFocusSelected,
      polygonSideMaterial
    ]
  );
  const getWorldPolygonAltitude = useCallback(() => LAND_CAP_ALTITUDE, []);
  const getRegionalPolygonAltitude = useCallback(
    (polygon: object) =>
      (polygon as GlobePolygon).selected
        ? SELECTED_REGION_CAP_ALTITUDE
        : REGION_CAP_ALTITUDE,
    []
  );
  const contextualCountryCodes = useMemo(() => {
    const result = new Set<string>();

    regions.forEach(({ region }) => {
      if (region.countryCode !== activeCountry.code) {
        result.add(region.countryCode);
      }
    });
    return result;
  }, [activeCountry.code, regions]);
  const focusedFeatureByRegionKey = useMemo(() => {
    const result = new Map<string, MapFeature>();
    if (nationalRegion) {
      const countryFeature = WORLD_FEATURES.find((worldFeature) =>
        activeCountry.worldFeatureIds.includes(String(worldFeature.id))
      );
      if (countryFeature) {
        result.set(getRegionKey(nationalRegion.region), countryFeature);
      }
    }
    regionalPolygons.forEach((polygon) => {
      if (polygon.region && !result.has(getRegionKey(polygon.region))) {
        result.set(getRegionKey(polygon.region), polygon.feature);
      }
    });
    return result;
  }, [
    activeCountry.worldFeatureIds,
    nationalRegion,
    regionalPolygons
  ]);
  const focusedPillars = useMemo(
    () =>
      activeRegions.flatMap((datum) => {
        if (datum.region.marketStatus === "closed") return [];
        if (datum.volume24h === null && datum.signalScore < 50) return [];
        const mapFeature = focusedFeatureByRegionKey.get(
          getRegionKey(datum.region)
        );
        if (!mapFeature) return [];
        return createRegionPillars(
          datum,
          mapFeature,
          datum.region.code === selectedCode,
          true
        );
      }),
    [
      activeRegions,
      focusedFeatureByRegionKey,
      selectedCode
    ]
  );
  const contextualPillarsByCountry = useMemo(() => {
    const result = new Map<string, VolumePillar[]>();

    regions.forEach((datum) => {
      if (datum.region.marketStatus === "closed") return;
      if (datum.volume24h === null && datum.signalScore < 50) return;
      const mapFeature = getRegionBoundaryFeature(datum.region);
      if (!mapFeature) return;
      const countryPillars = result.get(datum.region.countryCode) ?? [];
      countryPillars.push(
        ...createRegionPillars(datum, mapFeature, false, false)
      );
      result.set(datum.region.countryCode, countryPillars);
    });

    return result;
  }, [regions]);
  const visibleContextPillars = useMemo(
    () =>
      [...contextualPillarsByCountry.entries()].flatMap(
        ([countryCode, countryPillars]) =>
          contextualCountryCodes.has(countryCode) ? countryPillars : []
      ),
    [contextualCountryCodes, contextualPillarsByCountry]
  );
  const pillars = useMemo(
    () => [...focusedPillars, ...visibleContextPillars],
    [focusedPillars, visibleContextPillars]
  );
  const visibleTrades = useMemo(() => {
    const [focusLng, focusLat] = activeCountry.defaultCenter;

    return trades
      .filter(({ region }) => {
        const longitudeDistance = Math.abs(
          ((region.center[0] - focusLng + 540) % 360) - 180
        );
        const latitudeDistance = Math.abs(region.center[1] - focusLat);
        return longitudeDistance <= 42 && latitudeDistance <= 28;
      })
      .sort(
        (left, right) =>
          new Date(left.timestamp).getTime() -
          new Date(right.timestamp).getTime()
      );
  }, [activeCountry, trades]);
  useEffect(() => {
    const scopeChanged = tradeScopeRef.current !== activeCountry.code;
    if (scopeChanged) {
      tradeScopeRef.current = activeCountry.code;
      seenTradeIdsRef.current.clear();
      seenTradeOrderRef.current = [];
    }

    const incoming = visibleTrades.filter(
      (trade) => !seenTradeIdsRef.current.has(trade.id)
    );
    if (!incoming.length && !scopeChanged) return;

    incoming.forEach((trade) => {
      seenTradeIdsRef.current.add(trade.id);
      seenTradeOrderRef.current.push(trade.id);
    });
    while (seenTradeOrderRef.current.length > 500) {
      const expiredId = seenTradeOrderRef.current.shift();
      if (expiredId) seenTradeIdsRef.current.delete(expiredId);
    }

    const now = Date.now();
    setTradePopupQueue((current) =>
      appendTradePopupQueue(scopeChanged ? [] : current, incoming, now)
    );
  }, [activeCountry.code, visibleTrades]);
  useEffect(() => {
    if (!tradePopupQueue.length) return;

    const nextExpiry = Math.min(
      ...tradePopupQueue.map((popup) => popup.expiresAt)
    );
    const timeout = window.setTimeout(() => {
      const now = Date.now();
      setTradePopupQueue((current) =>
        current.filter((popup) => popup.expiresAt > now)
      );
    }, Math.max(0, nextExpiry - Date.now()));

    return () => window.clearTimeout(timeout);
  }, [tradePopupQueue]);
  const tradeLabels = useMemo<GlobeTradeLabel[]>(
    () =>
      tradePopupQueue.map(({ id, region, text }, index) => ({
        id,
        lat:
          region.center[1] +
          (region.countryCode === activeCountry.code ? 2 : 1.35) +
          index * 0.12,
        lng:
          region.center[0] +
          (index % 2 === 0 ? 1 : -1) *
            (region.countryCode === activeCountry.code ? 7 : 5),
        text,
        selected:
          region.countryCode === activeCountry.code &&
          region.code === selectedCode
      })),
    [activeCountry.code, selectedCode, tradePopupQueue]
  );
  const globeMaterial = useMemo(
    () => {
      const { normalMap } = createOceanTextures();
      const material = new THREE.MeshPhysicalMaterial({
        color: "#78a7b5",
        emissive: "#466f7b",
        emissiveIntensity: 0.055,
        roughness: 0.43,
        metalness: 0.08,
        ior: 1.333,
        clearcoat: 0.64,
        clearcoatRoughness: 0.27,
        normalMap,
        normalScale: new THREE.Vector2(0.36, 0.36),
        envMapIntensity: 0.5
      });
      material.name = "reflective-ocean";
      return material;
    },
    []
  );
  useEffect(
    () => () => {
      globeMaterial.normalMap?.dispose();
      globeMaterial.dispose();
    },
    [globeMaterial]
  );
  const focusLatitude = activeCountry.defaultCenter[1];
  const focusLongitude = activeCountry.defaultCenter[0];
  const cameraDistance =
    activeCountry.code === "RU"
      ? 315
      : activeCountry.code === "US"
        ? 282
        : activeCountry.code === "UA"
          ? 232
          : activeCountry.code === "GB"
            ? 218
            : 208;
  const focusOffset =
    -49 -
    (Math.sin(THREE.MathUtils.degToRad(focusLatitude)) -
      Math.sin(THREE.MathUtils.degToRad(46))) *
      GLOBE_RADIUS *
      GLOBE_SCALE;
  const selectPolygon = (polygon: GlobePolygon | undefined) => {
    if (polygon?.region) {
      onSelectRegion(polygon.region);
      return true;
    }
    if (
      polygon?.countryCode &&
      polygon.countryCode !== activeCountry.code
    ) {
      const country = COUNTRY_MARKET_MAPS.find(
        (candidate) => candidate.code === polygon.countryCode
      );
      if (country) {
        onSelectCountry(country);
        return true;
      }
    }
    return false;
  };
  const selectAtWorldPoint = (worldPoint: THREE.Vector3) => {
    if (!globeGroupRef.current) return false;
    const localPoint = globeGroupRef.current
      .worldToLocal(worldPoint.clone())
      .normalize();
    const position: Position = [
      THREE.MathUtils.radToDeg(Math.atan2(localPoint.x, localPoint.z)),
      THREE.MathUtils.radToDeg(Math.asin(localPoint.y))
    ];
    const polygon = [...selectablePolygons]
      .reverse()
      .find((candidate) => pointInGeometry(position, candidate.geometry));
    return selectPolygon(polygon);
  };

  return (
    <div
      className="h-full w-full"
      aria-label={`${activeCountry.label} 3D market volume map`}
      data-pillar-count={pillars.length}
      data-context-pillar-count={visibleContextPillars.length}
      data-trade-label-count={tradeLabels.length}
      data-intro-layers-visible={introDataVisible}
    >
      <Canvas
        camera={{ fov: 35, near: 1, far: 1000 }}
        dpr={[1, 1.75]}
        gl={{ alpha: true, antialias: true, powerPreference: "high-performance" }}
        shadows
      >
        <GlobeCamera distance={cameraDistance} />
        <AtmosphericFog distance={cameraDistance} />
        <RendererLightingSetup />
        <PersistentGlobeShadowRegistry
          revision={`${activeCountry.code}:${selectedCode}:${pillars.length}`}
        />
        <OceanReflectionEnvironment />
        <ambientLight intensity={0.02} />
        <hemisphereLight args={["#f8fbff", "#35494f", 0.06]} />
        <GlobeFixedShadowLight globeGroupRef={globeGroupRef} />
        <directionalLight
          position={[0, 210, 180]}
          intensity={0.04}
          color="#b8e1ed"
        />
        <group
          ref={globeGroupRef}
          position={[4, focusOffset, 0]}
          scale={GLOBE_SCALE}
          rotation={[
            activeCountry.code === "US" || activeCountry.code === "RU"
              ? 0.16
              : 0.1,
            THREE.MathUtils.degToRad(-focusLongitude),
            -0.035
          ]}
          onClick={(event) => {
            if (event.delta > 5) return;
            if (selectAtWorldPoint(event.point)) event.stopPropagation();
          }}
        >
          <Globe
            globeImageUrl={null}
            globeMaterial={globeMaterial}
            showAtmosphere
            atmosphereColor="#d8eef6"
            atmosphereAltitude={0.13}
            onGlobeReady={handleGlobeReady}
            onClick={(layer, data, event) => {
              const pointerEvent = event as unknown as {
                delta?: number;
                point?: THREE.Vector3;
              };
              if ((pointerEvent.delta ?? 0) > 5) return;
              if (layer === "polygon") {
                selectPolygon(data as GlobePolygon | undefined);
              } else if (pointerEvent.point) {
                selectAtWorldPoint(pointerEvent.point);
              }
            }}
            polygonsData={worldPolygons}
            polygonsTransitionDuration={0}
            polygonGeoJsonGeometry="geometry"
            polygonCapMaterial={getWorldPolygonCapMaterial}
            polygonSideColor=""
            polygonSideMaterial={getWorldPolygonSideMaterial}
            polygonStrokeColor={false}
            polygonAltitude={getWorldPolygonAltitude}
          />
          <group visible={introDataVisible}>
            <Globe
              animateIn={false}
              showGlobe={false}
              showAtmosphere={false}
              onClick={(layer, data, event) => {
                const pointerEvent = event as unknown as {
                  delta?: number;
                  point?: THREE.Vector3;
                };
                if ((pointerEvent.delta ?? 0) > 5) return;
                if (layer === "polygon") {
                  selectPolygon(data as GlobePolygon | undefined);
                } else if (pointerEvent.point) {
                  selectAtWorldPoint(pointerEvent.point);
                }
              }}
              polygonsData={regionalPolygons}
              polygonsTransitionDuration={0}
              polygonGeoJsonGeometry="geometry"
              polygonCapMaterial={getRegionalPolygonCapMaterial}
              polygonSideColor=""
              polygonSideMaterial={getRegionalPolygonSideMaterial}
              polygonStrokeColor={false}
              polygonAltitude={getRegionalPolygonAltitude}
            />
            {[...contextualPillarsByCountry.entries()].map(
              ([countryCode, countryPillars]) => (
                <group
                  key={`context-pillars:${countryCode}`}
                  visible={contextualCountryCodes.has(countryCode)}
                >
                  <Globe
                    animateIn={false}
                    showGlobe={false}
                    showAtmosphere={false}
                    pointsData={countryPillars}
                    pointLat="lat"
                    pointLng="lng"
                    pointAltitude="altitude"
                    pointRadius="radius"
                    pointColor="color"
                    pointResolution={6}
                    pointsMerge
                    pointsTransitionDuration={0}
                  />
                </group>
              )
            )}
            <Globe
              animateIn={false}
              showGlobe={false}
              showAtmosphere={false}
              pointsData={focusedPillars}
              pointLat="lat"
              pointLng="lng"
              pointAltitude="altitude"
              pointRadius="radius"
              pointColor="color"
              pointResolution={6}
              pointsMerge
              pointsTransitionDuration={0}
            />
            <BoundaryWalls
              polygons={worldPolygons}
              preciseCountryCode={activeCountry.code}
              preciseCountryPerimeter={regionalBoundaryPrecision.perimeter}
            />
            <BoundaryWalls
              polygons={regionalPolygons}
              edgesByPolygon={regionalBoundaryPrecision.edgesByPolygon}
            />
            {PROJECTED_PILLAR_CONTACT_SHADOWS_ENABLED ? (
              <ProjectedPillarContactShadows pillars={pillars} />
            ) : null}
          </group>
          {introDataVisible
            ? tradeLabels.map((label) => {
                const latitude = THREE.MathUtils.degToRad(label.lat);
                const longitude = THREE.MathUtils.degToRad(label.lng);
                const radius = GLOBE_RADIUS * 1.015;
                const position: [number, number, number] = [
                  radius * Math.cos(latitude) * Math.sin(longitude),
                  radius * Math.sin(latitude),
                  radius * Math.cos(latitude) * Math.cos(longitude)
                ];

                return (
                  <Html
                    key={label.id}
                    position={position}
                    center
                    zIndexRange={[20, 0]}
                    style={{ pointerEvents: "none" }}
                  >
                    <span
                      className={`market-map-trade-label ${
                        label.selected
                          ? "market-map-trade-label--selected"
                          : "market-map-trade-label--context"
                      } whitespace-nowrap font-sans text-[11px] font-extrabold text-slate-700`}
                    >
                      {label.text}
                    </span>
                  </Html>
                );
              })
            : null}
        </group>
        <GlobeControls
          distance={cameraDistance}
          focusLongitude={focusLongitude}
        />
      </Canvas>
    </div>
  );
}
