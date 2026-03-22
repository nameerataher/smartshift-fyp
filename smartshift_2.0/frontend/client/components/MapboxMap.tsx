/**
 * Pure map component — no floating HUD overlays.
 * All state lives in the parent (Map.tsx); this component
 * responds to props for lighting, flyTo, route drawing, and
 * click-to-select route points.
 */
import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
// @ts-ignore — no bundled types for mapbox-gl-draw
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { calculateSunPosition, SunPosition } from "@/lib/sunCalculations";
import {
  getTimeOfDayColor,
  getAmbientColor,
  getAmbientIntensity,
  getSunIntensity,
  getShadowIntensity,
} from "@/lib/lightingHelpers";

const DEFAULT_TOKEN =
  "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9.WI13BJqDyOu6G38-YP6hog";
const TOKEN_KEY = "smartshift:mapboxToken";

function loadToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) || DEFAULT_TOKEN; } catch { return DEFAULT_TOKEN; }
}

export const LOCATIONS: Record<
  string,
  { center: [number, number]; zoom: number; pitch: number; bearing: number }
> = {
  downtown: { center: [55.2708, 25.2048], zoom: 15,   pitch: 55, bearing: -20 },
  marina:   { center: [55.1386, 25.0805], zoom: 15.5, pitch: 60, bearing: 45  },
  frame:    { center: [55.3002, 25.2357], zoom: 16,   pitch: 65, bearing: -90 },
};

export interface FlyToTarget {
  center: [number, number];
  zoom: number;
  pitch: number;
  bearing: number;
  key: number; // increment to trigger
}

export interface RouteToDraw {
  coordinates: [number, number][];
  travelMode: string;
  key: number; // increment to trigger
}

export interface AltRouteToDraw {
  coordinates: [number, number][];
  color: string;
  active: boolean;
  routeId: number;
}

export interface SelectedBuilding {
  footprint: [number, number][];
  height: number;
  name: string;
  faces: BuildingFace[];
}

export interface BuildingFace {
  /** Cardinal label for display (derived from bearing). */
  direction: "N" | "E" | "S" | "W";
  /** Single edge vi → vi+1. Kept as one-element array for backward compat. */
  edges: [number, number][][];
  /** This facade's single edge [v0, v1] (LineString coordinates). */
  edge: [number, number][];
  /** Midpoint of the edge: ((x1+x2)/2, (y1+y2)/2) in [lon, lat]. */
  midpoint: [number, number];
  /** True facade direction in degrees 0–360 (outward normal angle). */
  bearing: number;
}

/**
 * Extract one facade per edge of the footprint polygon.
 *
 * Given footprint [v0, v1, v2, ...], each facade is edge_i = (vi → vi+1).
 * For each edge we compute:
 * - Midpoint: ((x1+x2)/2, (y1+y2)/2)
 * - Direction vector: dx = x2-x1, dy = y2-y1
 * - Outward normal (CCW polygon): nx = dy, ny = -dx
 * - Angle: atan2(nx, ny), then (angle + 360) % 360
 */
export function classifyFaces(footprint: [number, number][]): BuildingFace[] {
  const pts = footprint.length > 3 &&
    footprint[0][0] === footprint[footprint.length - 1][0] &&
    footprint[0][1] === footprint[footprint.length - 1][1]
    ? footprint.slice(0, -1)
    : [...footprint];

  // Ensure CCW winding (positive signed area = CCW in lon/lat space)
  let area = 0;
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length;
    area += (pts[j][0] - pts[i][0]) * (pts[j][1] + pts[i][1]);
  }
  if (area > 0) pts.reverse(); // was CW, flip to CCW

  const result: BuildingFace[] = [];

  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    const x1 = a[0], y1 = a[1], x2 = b[0], y2 = b[1];

    // 1. Midpoint
    const midpoint: [number, number] = [(x1 + x2) / 2, (y1 + y2) / 2];

    // 2. Direction vector
    const dx = x2 - x1;
    const dy = y2 - y1;

    // 3. Outward normal (CCW polygon): nx = dy, ny = -dx
    // In (x=east, y=north), normal = (nx, ny). Compass: 0°=North, 90°=East → bearing = atan2(nx, ny).
    const nx = dy;
    const ny = -dx;

    // 4. Compass bearing 0°=North, 90°=East (must use atan2(nx, ny); atan2(ny,nx) would flip SE↔NW)
    let bearing = (Math.atan2(nx, ny) * 180) / Math.PI;
    bearing = ((bearing % 360) + 360) % 360;

    let dir: "N" | "E" | "S" | "W";
    if (bearing >= 315 || bearing < 45) dir = "N";
    else if (bearing >= 45 && bearing < 135) dir = "E";
    else if (bearing >= 135 && bearing < 225) dir = "S";
    else dir = "W";

    const edge: [number, number][] = [a, b];
    result.push({
      direction: dir,
      edges: [edge],
      edge,
      midpoint,
      bearing,
    });
  }

  return result;
}

/** Convert bearing (0–360°) to cardinal label for display only. */
export function angleToCardinal(angle: number): "N" | "E" | "S" | "W" {
  const a = ((angle % 360) + 360) % 360;
  if (a >= 315 || a < 45) return "N";
  if (a < 135) return "E";
  if (a < 225) return "S";
  return "W";
}

/** Find which face a click point is closest to. */
export function closestFace(
  click: [number, number],
  faces: BuildingFace[]
): BuildingFace | null {
  let best: BuildingFace | null = null;
  let bestDist = Infinity;
  for (const face of faces) {
    for (const [a, b] of face.edges) {
      const d = pointToSegmentDist(click, a, b);
      if (d < bestDist) {
        bestDist = d;
        best = face;
      }
    }
  }
  return best;
}

function pointToSegmentDist(p: [number, number], a: [number, number], b: [number, number]): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

export interface MapboxMapProps {
  currentMinutes: number;
  dateStr: string;
  flyTo?: FlyToTarget | null;
  routeToDraw?: RouteToDraw | null;
  altRoutes?: AltRouteToDraw[] | null;
  altRoutesKey?: number;
  /** When set, draw Shadow vs Google route overlay for comparison */
  compareRoutes?: { shadow: [number, number][]; google: [number, number][] } | null;
  clearRouteKey?: number;
  selectingPoint?: "from" | "to" | null;
  onPointSelected?: (lat: number, lng: number, which: "from" | "to") => void;
  onMapReady?: () => void;
  onBearingChange?: (bearing: number) => void;
  fromMarker?: [number, number] | null;
  toMarker?: [number, number] | null;
  drawPolygonMode?: boolean;
  onPolygonDrawn?: (points: [number, number][]) => void;
  drawnPolygon?: [number, number][] | null;
  debugShadowGeoJSON?: any | null;
  mapInstanceRef?: React.MutableRefObject<mapboxgl.Map | null>;
  // Facade mode
  facadeSelectMode?: boolean;
  onBuildingSelected?: (building: SelectedBuilding) => void;
  onFaceClicked?: (face: BuildingFace) => void;
  selectedBuildingFootprint?: [number, number][] | null;
  selectedFaceDirection?: "N" | "E" | "S" | "W" | null;
  /** When set, highlight the facade with this bearing (identifies exact edge when multiple share a direction). */
  selectedFaceAngle?: number | null;
}

export interface ClientBuilding {
  id: string;
  footprint: [number, number][];
  height: number;
  min_height: number;
  name: string;
}

function isBuilding(f: mapboxgl.GeoJSONFeature): boolean {
  if (f.sourceLayer === "building") return true;

  const layerId = (f.layer?.id ?? "").toLowerCase();
  if (layerId.includes("building")) return true;

  const layerType = (f.layer as any)?.type;
  if (layerType === "fill-extrusion") return true;

  const p = f.properties || {};
  if (p.height !== undefined || p["render_height"] !== undefined) return true;

  return false;
}

function extractHeight(props: Record<string, any>): number {
  const raw =
    props["height"] ??
    props["render_height"] ??
    props["fill-extrusion-height"] ??
    props["extrude"] ??
    null;
  return raw !== null && raw !== undefined ? Math.max(1, Number(raw)) : 0;
}

/**
 * Extract building footprints + heights from the map's rendered vector tiles.
 * Uses multiple detection strategies to work across all Mapbox style types
 * (Standard, Streets, custom) because internal layer names vary.
 */
export function queryBuildingsFromMap(
  map: mapboxgl.Map,
  lon: number,
  lat: number,
  radiusPx = 800
): ClientBuilding[] {
  const center = map.project([lon, lat]);
  const bbox: [mapboxgl.PointLike, mapboxgl.PointLike] = [
    [center.x - radiusPx, center.y - radiusPx],
    [center.x + radiusPx, center.y + radiusPx],
  ];

  // Strategy 1: try querying with explicit layer name (not all styles have this)
  let features: mapboxgl.GeoJSONFeature[] = [];
  try {
    features = map.queryRenderedFeatures(bbox, { layers: ["building"] });
  } catch {
    // expected in Standard style — fall through silently
  }

  // Strategy 2: if nothing found, query everything and filter
  if (features.length === 0) {
    features = map.queryRenderedFeatures(bbox).filter(isBuilding);
  }

  const buildings: ClientBuilding[] = [];
  const seen = new Set<string>();

  for (const f of features) {
    const geom = f.geometry as any;
    if (geom.type !== "Polygon" && geom.type !== "MultiPolygon") continue;

    const coords: [number, number][] =
      geom.type === "Polygon"
        ? geom.coordinates[0]
        : geom.coordinates[0][0];

    if (!coords || coords.length < 3) continue;

    // Deduplicate by first vertex + vertex count
    const key = `${coords[0][0].toFixed(6)},${coords[0][1].toFixed(6)},${coords.length}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const props = f.properties || {};
    const height = extractHeight(props);
    const minH = Number(props["min_height"] ?? 0);

    // Skip if no usable height and not clearly a building extrusion
    if (height === 0 && !f.sourceLayer?.includes("building")) continue;
    const effectiveHeight = height > 0 ? height - minH : 30;

    buildings.push({
      id: `cl_${buildings.length}`,
      footprint: coords.map((c) => [c[0], c[1]] as [number, number]),
      height: Math.max(1, effectiveHeight),
      min_height: minH,
      name: props.type || props.class || "building",
    });
  }

  const heights = buildings.map((b) => b.height);
  const avgH = heights.length ? (heights.reduce((a, b) => a + b, 0) / heights.length).toFixed(1) : "0";
  const maxH = heights.length ? Math.max(...heights).toFixed(1) : "0";
  console.log(
    `[queryBuildingsFromMap] Found ${buildings.length} buildings near [${lon.toFixed(4)}, ${lat.toFixed(4)}]` +
    ` (${features.length} raw features, radius=${radiusPx}px, zoom=${map.getZoom().toFixed(1)})` +
    ` Heights: avg=${avgH}m, max=${maxH}m`
  );
  if (buildings.length > 0 && buildings.length <= 5) {
    buildings.forEach((b) =>
      console.log(`  ${b.id}: height=${b.height}m, vertices=${b.footprint.length}`)
    );
  }

  return buildings;
}

export default function MapboxMap({
  currentMinutes,
  dateStr,
  flyTo,
  routeToDraw,
  altRoutes,
  altRoutesKey,
  compareRoutes,
  clearRouteKey,
  selectingPoint,
  onPointSelected,
  onMapReady,
  onBearingChange,
  fromMarker,
  toMarker,
  drawPolygonMode,
  onPolygonDrawn,
  drawnPolygon,
  debugShadowGeoJSON,
  mapInstanceRef,
  facadeSelectMode,
  onBuildingSelected,
  onFaceClicked,
  selectedBuildingFootprint,
  selectedFaceDirection,
  selectedFaceAngle,
}: MapboxMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const mapReadyRef = useRef(false);
  const drawRef = useRef<any>(null);

  // Stable refs for callbacks (avoid stale closures in map event handlers)
  const selectingPointRef = useRef(selectingPoint);
  const onPointSelectedRef = useRef(onPointSelected);
  const onBearingChangeRef = useRef(onBearingChange);
  const onPolygonDrawnRef = useRef(onPolygonDrawn);
  const facadeSelectModeRef = useRef(facadeSelectMode);
  const onBuildingSelectedRef = useRef(onBuildingSelected);
  const onFaceClickedRef = useRef(onFaceClicked);
  const selectedBuildingRef = useRef(selectedBuildingFootprint);
  useEffect(() => { selectingPointRef.current = selectingPoint; }, [selectingPoint]);
  useEffect(() => { onPointSelectedRef.current = onPointSelected; }, [onPointSelected]);
  useEffect(() => { onBearingChangeRef.current = onBearingChange; }, [onBearingChange]);
  useEffect(() => { onPolygonDrawnRef.current = onPolygonDrawn; }, [onPolygonDrawn]);
  useEffect(() => { facadeSelectModeRef.current = facadeSelectMode; }, [facadeSelectMode]);
  useEffect(() => { onBuildingSelectedRef.current = onBuildingSelected; }, [onBuildingSelected]);
  useEffect(() => { onFaceClickedRef.current = onFaceClicked; }, [onFaceClicked]);
  useEffect(() => { selectedBuildingRef.current = selectedBuildingFootprint; }, [selectedBuildingFootprint]);

  // Markers for route from/to
  const fromMarkerInstanceRef = useRef<mapboxgl.Marker | null>(null);
  const toMarkerInstanceRef = useRef<mapboxgl.Marker | null>(null);

  // Track keys to avoid re-running effects with stale values
  const prevFlyKeyRef = useRef<number | null>(null);
  const prevRouteKeyRef = useRef<number | null>(null);
  const prevClearKeyRef = useRef<number | undefined>(undefined);
  const prevAltRoutesKeyRef = useRef<number | undefined>(undefined);

  // ── Lighting: Use ONLY setLights (do not set lightPreset — it overrides setLights in Standard style) ──
  const applyLighting = useCallback((sp: SunPosition) => {
    const map = mapRef.current;
    if (!map) return;

    // Polar angle: 0° = overhead, 90° = horizon. Clamp to [5, 70] for shadow updates (Mapbox limit ~75°)
    const polarAngle = Math.min(70, Math.max(5, 90 - sp.altitude));
    // Mapbox direction = position of the light source (where the sun is). 270° = sun in west → shadows east.
    const azimuth = sp.azimuth;

    const mapAny = map as any;
    if (typeof mapAny.setLights !== "function") return;

    try {
      // Do NOT call setConfigProperty("lightPreset") — it overrides setLights and locks shadows to 4 presets
      mapAny.setLights([
        {
          id: "sun-light",
          type: "directional",
          properties: {
            direction: [azimuth, polarAngle],
            color: getTimeOfDayColor(sp.altitude, sp.azimuth),
            intensity: getSunIntensity(sp.altitude),
            "cast-shadows": sp.altitude > 0,
            "shadow-intensity": getShadowIntensity(sp.altitude),
          },
        },
        {
          id: "ambient-light",
          type: "ambient",
          properties: {
            color: getAmbientColor(sp.altitude),
            intensity: getAmbientIntensity(sp.altitude),
          },
        },
      ]);
      map.triggerRepaint();
    } catch (e) {
      console.warn("Lighting error:", e);
    }
  }, []);

  // ── Init map ─────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainerRef.current) return;
    mapboxgl.accessToken = loadToken();

    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/standard",
      center: LOCATIONS.marina.center,
      zoom: LOCATIONS.marina.zoom,
      pitch: LOCATIONS.marina.pitch,
      bearing: LOCATIONS.marina.bearing,
      antialias: true,
    });
    mapRef.current = map;
    if (mapInstanceRef) mapInstanceRef.current = map;

    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      const date = dateStr ? new Date(dateStr) : new Date();
      const h = Math.floor(currentMinutes / 60);
      const m = currentMinutes % 60;
      const sp = calculateSunPosition(date, h, m);
      // Apply our lights only (no lightPreset — so shadows update with slider)
      setTimeout(() => {
        applyLighting(sp);
        mapReadyRef.current = true;
        onMapReady?.();
      }, 300);
      try {
        const bearing = map.getBearing();
        onBearingChangeRef.current?.(bearing);
      } catch {}
    });

    map.on("click", (e) => {
      // Facade mode: building/face click
      if (facadeSelectModeRef.current) {
        const features = map.queryRenderedFeatures(e.point).filter(isBuilding);
        if (features.length > 0 && !selectedBuildingRef.current) {
          // First click: select the building
          const f = features[0];
          const geom = f.geometry;
          if (geom.type === "Polygon" || geom.type === "MultiPolygon") {
            const coords: [number, number][] =
              geom.type === "Polygon"
                ? (geom.coordinates[0] as [number, number][])
                : (geom.coordinates[0][0] as [number, number][]);
            const h = extractHeight(f.properties || {});
            const faces = classifyFaces(coords);
            onBuildingSelectedRef.current?.({
              footprint: coords,
              height: h > 0 ? h : 30,
              name: (f.properties as any)?.type || "building",
              faces,
            });
          }
        } else if (selectedBuildingRef.current) {
          // Second click: select the face (ref holds the footprint array)
          const clickPt: [number, number] = [e.lngLat.lng, e.lngLat.lat];
          const faces = classifyFaces(selectedBuildingRef.current as [number, number][]);
          const face = closestFace(clickPt, faces);
          if (face) onFaceClickedRef.current?.(face);
        }
        return;
      }

      const which = selectingPointRef.current;
      if (!which) return;
      onPointSelectedRef.current?.(e.lngLat.lat, e.lngLat.lng, which);
    });

    // Facade mode: hover highlight
    map.on("mousemove", (e) => {
      if (!facadeSelectModeRef.current) return;
      const hoverSrc = "facade-hover-src";
      const hoverFill = "facade-hover-fill";
      const hoverLine = "facade-hover-line";

      if (selectedBuildingRef.current) {
        // Building already selected — highlight nearest face edge on hover
        try { if (map.getLayer(hoverFill)) map.removeLayer(hoverFill); } catch {}
        try { if (map.getLayer(hoverLine)) map.removeLayer(hoverLine); } catch {}
        try { if (map.getSource(hoverSrc)) map.removeSource(hoverSrc); } catch {}

        const clickPt: [number, number] = [e.lngLat.lng, e.lngLat.lat];
        const faces = classifyFaces(selectedBuildingRef.current as [number, number][]);
        const face = closestFace(clickPt, faces);
        if (face) {
          const lineFeatures = face.edges.map((edge) => ({
            type: "Feature" as const,
            properties: { dir: face.direction },
            geometry: { type: "LineString" as const, coordinates: edge },
          }));
          map.addSource(hoverSrc, {
            type: "geojson",
            data: { type: "FeatureCollection", features: lineFeatures },
          });
          map.addLayer({
            id: hoverLine, type: "line", source: hoverSrc, slot: "top",
            paint: { "line-color": "#facc15", "line-width": 5, "line-opacity": 0.9 },
          } as any);
          map.getCanvas().style.cursor = "pointer";
        }
        return;
      }

      // No building selected yet — highlight building under cursor
      const features = map.queryRenderedFeatures(e.point).filter(isBuilding);
      try { if (map.getLayer(hoverFill)) map.removeLayer(hoverFill); } catch {}
      try { if (map.getLayer(hoverLine)) map.removeLayer(hoverLine); } catch {}
      try { if (map.getSource(hoverSrc)) map.removeSource(hoverSrc); } catch {}

      if (features.length > 0) {
        const f = features[0];
        const geom = f.geometry;
        if (geom.type === "Polygon" || geom.type === "MultiPolygon") {
          const coords =
            geom.type === "Polygon" ? geom.coordinates : geom.coordinates[0];
          map.addSource(hoverSrc, {
            type: "geojson",
            data: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: coords } },
          });
          map.addLayer({
            id: hoverFill, type: "fill", source: hoverSrc, slot: "top",
            paint: { "fill-color": "#3b82f6", "fill-opacity": 0.25 },
          } as any);
          map.addLayer({
            id: hoverLine, type: "line", source: hoverSrc, slot: "top",
            paint: { "line-color": "#3b82f6", "line-width": 2.5 },
          } as any);
          map.getCanvas().style.cursor = "pointer";
        }
      } else {
        map.getCanvas().style.cursor = facadeSelectModeRef.current ? "crosshair" : "";
      }
    });

    // Report bearing changes when the map is rotated
    const handleRotate = () => {
      try {
        const bearing = map.getBearing();
        onBearingChangeRef.current?.(bearing);
      } catch {}
    };
    map.on("rotate", handleRotate);

    map.on("error", (e) => console.error("Map error:", e));

    return () => {
      fromMarkerInstanceRef.current?.remove();
      toMarkerInstanceRef.current?.remove();
      if (mapInstanceRef) mapInstanceRef.current = null;
      map.remove();
      mapReadyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyLighting]);

  // ── Crosshair cursor when selecting ──────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = selectingPoint ? "crosshair" : "";
  }, [selectingPoint]);

  // ── Update lighting when time changes ────────────────────────────────────
  useEffect(() => {
    if (!mapReadyRef.current) return;
    const date = dateStr ? new Date(dateStr) : new Date();
    const sp = calculateSunPosition(date, Math.floor(currentMinutes / 60), currentMinutes % 60);
    applyLighting(sp);
  }, [currentMinutes, dateStr, applyLighting]);

  // ── FlyTo when target changes ─────────────────────────────────────────────
  useEffect(() => {
    if (!flyTo || !mapRef.current) return;
    if (flyTo.key === prevFlyKeyRef.current) return;
    prevFlyKeyRef.current = flyTo.key;
    mapRef.current.flyTo({ center: flyTo.center, zoom: flyTo.zoom, pitch: flyTo.pitch, bearing: flyTo.bearing, duration: 2000 });
  }, [flyTo]);

  // ── Draw route when routeToDraw changes ──────────────────────────────────
  useEffect(() => {
    if (!routeToDraw || !mapRef.current) return;
    if (routeToDraw.key === prevRouteKeyRef.current) return;
    prevRouteKeyRef.current = routeToDraw.key;
    const map = mapRef.current;
    try {
      if (map.getSource("shaded-route")) {
        map.removeLayer("shaded-route-line");
        map.removeSource("shaded-route");
      }
    } catch {}
    const { coordinates, travelMode } = routeToDraw;
    if (coordinates.length < 2) return;
    map.addSource("shaded-route", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } },
    });
    map.addLayer({
      id: "shaded-route-line",
      type: "line",
      source: "shaded-route",
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": travelMode === "cycling" ? "#22c55e" : "#3b82f6",
        "line-width": 6,
        "line-opacity": 0.9,
      },
    });
    const bounds = coordinates.reduce(
      (b, c) => b.extend(c),
      new mapboxgl.LngLatBounds(coordinates[0], coordinates[0])
    );
    map.fitBounds(bounds, { padding: 60 });
  }, [routeToDraw]);

  // ── Draw alternative routes ──────────────────────────────────────────────
  useEffect(() => {
    if (!altRoutes || !mapRef.current) return;
    if (altRoutesKey === prevAltRoutesKeyRef.current) return;
    prevAltRoutesKeyRef.current = altRoutesKey;
    const map = mapRef.current;

    for (let i = 0; i < 5; i++) {
      try {
        if (map.getSource(`alt-route-${i}`)) {
          map.removeLayer(`alt-route-line-${i}`);
          map.removeSource(`alt-route-${i}`);
        }
      } catch {}
    }

    altRoutes.forEach((route, idx) => {
      if (route.coordinates.length < 2 || route.active) return;
      const srcId = `alt-route-${idx}`;
      map.addSource(srcId, {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: route.coordinates } },
      });
      map.addLayer({
        id: `alt-route-line-${idx}`,
        type: "line",
        source: srcId,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": route.color,
          "line-width": 4,
          "line-opacity": 0.4,
          "line-dasharray": [2, 2],
        },
      });
    });
  }, [altRoutes, altRoutesKey]);

  // ── Draw compare overlay (Shadow vs Google) ─────────────────────────────
  useEffect(() => {
    if (!compareRoutes || !mapRef.current) return;
    const map = mapRef.current;
    const hasShadow = compareRoutes.shadow.length >= 2;
    const hasGoogle = compareRoutes.google.length >= 2;

    try {
      if (map.getSource("compare-route-shadow")) {
        map.removeLayer("compare-route-shadow-line");
        map.removeSource("compare-route-shadow");
      }
      if (map.getSource("compare-route-google")) {
        map.removeLayer("compare-route-google-line");
        map.removeSource("compare-route-google");
      }
    } catch {}

    if (hasShadow) {
      map.addSource("compare-route-shadow", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: compareRoutes.shadow } },
      });
      map.addLayer({
        id: "compare-route-shadow-line",
        type: "line",
        source: "compare-route-shadow",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#2563eb",
          "line-width": 6,
          "line-opacity": 0.9,
        },
      });
    }
    if (hasGoogle) {
      map.addSource("compare-route-google", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: compareRoutes.google } },
      });
      map.addLayer({
        id: "compare-route-google-line",
        type: "line",
        source: "compare-route-google",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#ea580c",
          "line-width": 5,
          "line-opacity": 0.85,
          "line-dasharray": [2, 1],
        },
      });
    }

    if (hasShadow || hasGoogle) {
      // Only use coordinates that look like [lng, lat] (Mapbox/GeoJSON) so invalid or swapped data doesn't blow bounds to globe
      const valid = (c: [number, number]) =>
        Number.isFinite(c[0]) && Number.isFinite(c[1]) && c[0] >= -180 && c[0] <= 180 && c[1] >= -90 && c[1] <= 90;
      const shadowSafe = hasShadow ? compareRoutes.shadow.filter(valid) : [];
      const googleSafe = hasGoogle ? compareRoutes.google.filter(valid) : [];
      const all = [...shadowSafe, ...googleSafe];
      if (all.length >= 2) {
        const bounds = all.reduce(
          (b, c) => b.extend(c),
          new mapboxgl.LngLatBounds(all[0], all[0])
        );
        const ne = bounds.getNorthEast();
        const sw = bounds.getSouthWest();
        const spanLng = Math.abs(ne.lng - sw.lng);
        const spanLat = Math.abs(ne.lat - sw.lat);
        // If bounds are too large (e.g. wrong coords), fit only to shadow so we don't zoom to globe
        if (spanLng > 50 || spanLat > 50) {
          const use = shadowSafe.length >= 2 ? shadowSafe : googleSafe;
          if (use.length >= 2) {
            const b = use.reduce(
              (b, c) => b.extend(c),
              new mapboxgl.LngLatBounds(use[0], use[0])
            );
            map.fitBounds(b, { padding: 80, maxZoom: 14 });
          }
        } else {
          map.fitBounds(bounds, { padding: 80, maxZoom: 14 });
        }
      } else if (shadowSafe.length >= 2) {
        const b = shadowSafe.reduce(
          (b, c) => b.extend(c),
          new mapboxgl.LngLatBounds(shadowSafe[0], shadowSafe[0])
        );
        map.fitBounds(b, { padding: 80, maxZoom: 14 });
      } else if (googleSafe.length >= 2) {
        const b = googleSafe.reduce(
          (b, c) => b.extend(c),
          new mapboxgl.LngLatBounds(googleSafe[0], googleSafe[0])
        );
        map.fitBounds(b, { padding: 80, maxZoom: 14 });
      }
    }

    return () => {
      try {
        if (map.getSource("compare-route-shadow")) {
          map.removeLayer("compare-route-shadow-line");
          map.removeSource("compare-route-shadow");
        }
        if (map.getSource("compare-route-google")) {
          map.removeLayer("compare-route-google-line");
          map.removeSource("compare-route-google");
        }
      } catch {}
    };
  }, [compareRoutes]);

  // ── Clear route ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (clearRouteKey === undefined || clearRouteKey === prevClearKeyRef.current) return;
    prevClearKeyRef.current = clearRouteKey;
    const map = mapRef.current;
    if (!map) return;
    try {
      if (map.getSource("shaded-route")) {
        map.removeLayer("shaded-route-line");
        map.removeSource("shaded-route");
      }
    } catch {}
    for (let i = 0; i < 5; i++) {
      try {
        if (map.getSource(`alt-route-${i}`)) {
          map.removeLayer(`alt-route-line-${i}`);
          map.removeSource(`alt-route-${i}`);
        }
      } catch {}
    }
    try {
      if (map.getSource("compare-route-shadow")) {
        map.removeLayer("compare-route-shadow-line");
        map.removeSource("compare-route-shadow");
      }
      if (map.getSource("compare-route-google")) {
        map.removeLayer("compare-route-google-line");
        map.removeSource("compare-route-google");
      }
    } catch {}
  }, [clearRouteKey]);

  // ── From marker ──────────────────────────────────────────────────────────
  useEffect(() => {
    fromMarkerInstanceRef.current?.remove();
    fromMarkerInstanceRef.current = null;
    if (fromMarker && mapRef.current) {
      fromMarkerInstanceRef.current = new mapboxgl.Marker({ color: "#22c55e" })
        .setLngLat(fromMarker)
        .addTo(mapRef.current);
    }
  }, [fromMarker]);

  // ── To marker ────────────────────────────────────────────────────────────
  useEffect(() => {
    toMarkerInstanceRef.current?.remove();
    toMarkerInstanceRef.current = null;
    if (toMarker && mapRef.current) {
      toMarkerInstanceRef.current = new mapboxgl.Marker({ color: "#ef4444" })
        .setLngLat(toMarker)
        .addTo(mapRef.current);
    }
  }, [toMarker]);

  // ── Mapbox Draw for polygon mode ────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    if (drawPolygonMode) {
      if (!drawRef.current) {
        const draw = new MapboxDraw({
          displayControlsDefault: false,
          controls: { polygon: true, trash: true },
          defaultMode: "draw_polygon",
        });
        map.addControl(draw, "top-left");
        drawRef.current = draw;

        const handleCreate = (e: any) => {
          const feature = e.features?.[0];
          if (!feature || feature.geometry.type !== "Polygon") return;
          const ring: [number, number][] = feature.geometry.coordinates[0];
          onPolygonDrawnRef.current?.(ring);
        };
        map.on("draw.create", handleCreate);
        map.on("draw.update", handleCreate);
      }
      map.getCanvas().style.cursor = "crosshair";
    } else {
      if (drawRef.current) {
        try { map.removeControl(drawRef.current); } catch {}
        drawRef.current = null;
        map.getCanvas().style.cursor = "";
      }
    }
  }, [drawPolygonMode]);

  // ── Render a previously-drawn polygon outline on the map ────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    const SRC = "drawn-polygon-src";
    const FILL = "drawn-polygon-fill";
    const LINE = "drawn-polygon-line";

    try { if (map.getLayer(FILL)) map.removeLayer(FILL); } catch {}
    try { if (map.getLayer(LINE)) map.removeLayer(LINE); } catch {}
    try { if (map.getSource(SRC)) map.removeSource(SRC); } catch {}

    if (!drawnPolygon || drawnPolygon.length < 3) return;

    map.addSource(SRC, {
      type: "geojson",
      data: {
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [drawnPolygon] },
      },
    });
    map.addLayer({
      id: FILL,
      type: "fill",
      source: SRC,
      slot: "top",
      paint: { "fill-color": "#3b82f6", "fill-opacity": 0.15 },
    } as any);
    map.addLayer({
      id: LINE,
      type: "line",
      source: SRC,
      slot: "top",
      paint: { "line-color": "#3b82f6", "line-width": 2, "line-dasharray": [2, 2] },
    } as any);
  }, [drawnPolygon]);

  // ── Debug shadow + footprint overlay ─────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    const layers = [
      "debug-shadow-fill", "debug-shadow-line",
      "debug-fp-fill", "debug-fp-line",
    ];
    const sources = ["debug-shadow-src", "debug-fp-src"];
    for (const l of layers) { try { if (map.getLayer(l)) map.removeLayer(l); } catch {} }
    for (const s of sources) { try { if (map.getSource(s)) map.removeSource(s); } catch {} }

    if (!debugShadowGeoJSON) return;

    // Shadow polygons = dark blue (SHADED area)
    // Use slot: "top" so layers render above 3D buildings in Standard style
    if (debugShadowGeoJSON.shadows) {
      map.addSource("debug-shadow-src", { type: "geojson", data: debugShadowGeoJSON.shadows });
      map.addLayer({
        id: "debug-shadow-fill", type: "fill", source: "debug-shadow-src",
        slot: "top",
        paint: { "fill-color": "#1e3a5f", "fill-opacity": 0.4 },
      } as any);
      map.addLayer({
        id: "debug-shadow-line", type: "line", source: "debug-shadow-src",
        slot: "top",
        paint: { "line-color": "#0ea5e9", "line-width": 2, "line-dasharray": [3, 2] },
      } as any);
    }

    // Building footprints = orange outline (so you can see building vs shadow)
    if (debugShadowGeoJSON.footprints) {
      map.addSource("debug-fp-src", { type: "geojson", data: debugShadowGeoJSON.footprints });
      map.addLayer({
        id: "debug-fp-fill", type: "fill", source: "debug-fp-src",
        slot: "top",
        paint: { "fill-color": "#f97316", "fill-opacity": 0.25 },
      } as any);
      map.addLayer({
        id: "debug-fp-line", type: "line", source: "debug-fp-src",
        slot: "top",
        paint: { "line-color": "#f97316", "line-width": 2.5 },
      } as any);
    }
  }, [debugShadowGeoJSON]);

  // ── Facade: selected building + face edges overlay (one facade per edge) ──
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    const FACE_COLORS: Record<string, string> = {
      N: "#3b82f6", E: "#22c55e", S: "#ef4444", W: "#f59e0b",
    };
    const layers = ["facade-face-labels", "facade-bldg-fill", "facade-bldg-line", "facade-faces-line", "facade-sel-line"];
    const sources = ["facade-labels-src", "facade-bldg-src", "facade-faces-src", "facade-sel-src"];
    for (const l of layers) { try { if (map.getLayer(l)) map.removeLayer(l); } catch {} }
    for (const s of sources) { try { if (map.getSource(s)) map.removeSource(s); } catch {} }

    if (!selectedBuildingFootprint || selectedBuildingFootprint.length < 3) return;

    // Building footprint fill
    const ring = [...selectedBuildingFootprint];
    if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ring.push(ring[0]);
    map.addSource("facade-bldg-src", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } },
    });
    map.addLayer({
      id: "facade-bldg-fill", type: "fill", source: "facade-bldg-src", slot: "top",
      paint: { "fill-color": "#6366f1", "fill-opacity": 0.15 },
    } as any);
    map.addLayer({
      id: "facade-bldg-line", type: "line", source: "facade-bldg-src", slot: "top",
      paint: { "line-color": "#6366f1", "line-width": 2, "line-dasharray": [2, 2] },
    } as any);

    // One feature per facade (edge); highlight by true bearing (walls are rarely axis-aligned)
    const faces = classifyFaces(selectedBuildingFootprint);
    const lineFeatures = faces.map((face) => {
      const bearingDelta =
        selectedFaceAngle != null
          ? Math.abs(((face.bearing - selectedFaceAngle + 180) % 360) - 180)
          : 999;
      const angleMatch = selectedFaceAngle != null && bearingDelta < 3;
      const legacyMatch =
        selectedFaceAngle == null &&
        selectedFaceDirection != null &&
        selectedFaceDirection === face.direction;
      const isSelected = angleMatch || legacyMatch ? 1 : 0;
      return {
        type: "Feature" as const,
        properties: { direction: face.direction, bearing: face.bearing, isSelected },
        geometry: { type: "LineString" as const, coordinates: face.edge as [number, number][] },
      };
    });
    map.addSource("facade-faces-src", {
      type: "geojson",
      data: { type: "FeatureCollection", features: lineFeatures },
    });
    const lineColorExpr: unknown = [
      "case",
      ["==", ["get", "isSelected"], 1], "#ffffff",
      ["match", ["get", "direction"], "N", FACE_COLORS.N, "E", FACE_COLORS.E, "S", FACE_COLORS.S, "W", FACE_COLORS.W, "#888"],
    ];
    map.addLayer({
      id: "facade-faces-line",
      type: "line",
      source: "facade-faces-src",
      slot: "top",
      paint: {
        "line-color": lineColorExpr as string,
        "line-width": ["case", ["==", ["get", "isSelected"], 1], 8, 3.5],
        "line-opacity": ["case", ["==", ["get", "isSelected"], 1], 0.9, 0.7],
      },
    } as any);

    // Point labels at edge midpoints: true compass bearing (walls can face any direction)
    const labelFeatures = faces.map((face) => {
      const br = Math.round(face.bearing);
      return {
        type: "Feature" as const,
        properties: {
          label: `${br}° ${face.direction}`,
        },
        geometry: { type: "Point" as const, coordinates: face.midpoint },
      };
    });
    map.addSource("facade-labels-src", {
      type: "geojson",
      data: { type: "FeatureCollection", features: labelFeatures },
    });
    map.addLayer({
      id: "facade-face-labels",
      type: "symbol",
      source: "facade-labels-src",
      slot: "top",
      layout: {
        "text-field": ["get", "label"],
        "text-size": 10,
        "text-line-height": 1.1,
        "text-offset": [0, 0.4],
        "text-anchor": "center",
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": "#f8fafc",
        "text-halo-color": "#0f172a",
        "text-halo-width": 2,
        "text-halo-blur": 0.5,
      },
    } as any);
  }, [selectedBuildingFootprint, selectedFaceDirection, selectedFaceAngle]);

  // ── Facade: cursor style ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (facadeSelectMode) {
      map.getCanvas().style.cursor = "crosshair";
    }
  }, [facadeSelectMode]);

  const showFacadeLegend =
    selectedBuildingFootprint != null && selectedBuildingFootprint.length >= 3;

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
      {showFacadeLegend && (
        <div
          className="pointer-events-none absolute bottom-3 left-3 z-30 max-w-[200px] rounded-lg border border-white/20 bg-black/70 px-2.5 py-2 text-[10px] leading-snug text-slate-100 shadow-lg backdrop-blur-sm"
          aria-label="Facade edge legend"
        >
          <div className="font-semibold text-white/95 mb-1">Edges</div>
          <p className="text-slate-300/95 mb-1.5">Each label: degrees + N/S/E/W (wall direction).</p>
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[9px]">
            <span><span className="inline-block w-2 h-2 rounded-sm align-middle mr-0.5" style={{ background: "#3b82f6" }} />N</span>
            <span><span className="inline-block w-2 h-2 rounded-sm align-middle mr-0.5" style={{ background: "#22c55e" }} />E</span>
            <span><span className="inline-block w-2 h-2 rounded-sm align-middle mr-0.5" style={{ background: "#ef4444" }} />S</span>
            <span><span className="inline-block w-2 h-2 rounded-sm align-middle mr-0.5" style={{ background: "#f59e0b" }} />W</span>
            <span className="text-slate-400">· white = pick</span>
          </div>
        </div>
      )}
    </div>
  );
}
