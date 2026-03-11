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
  getLightPreset,
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

export interface SelectedBuilding {
  footprint: [number, number][];
  height: number;
  name: string;
  faces: BuildingFace[];
}

export interface BuildingFace {
  direction: "N" | "E" | "S" | "W";
  edges: [number, number][][];
  bearing: number;
}

/**
 * Classify a building footprint's edges into N/S/E/W faces.
 *
 * For each edge we compute the outward-pointing normal. The normal's
 * compass bearing determines the cardinal direction:
 *   N: 315°–45°   E: 45°–135°   S: 135°–225°   W: 225°–315°
 *
 * We assume the footprint ring is wound counter-clockwise (standard
 * GeoJSON). For a CW ring the normals would flip, so we check and
 * reverse if needed.
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

  const buckets: Record<"N" | "E" | "S" | "W", { edges: [number, number][][]; bearings: number[] }> = {
    N: { edges: [], bearings: [] },
    E: { edges: [], bearings: [] },
    S: { edges: [], bearings: [] },
    W: { edges: [], bearings: [] },
  };

  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % pts.length];
    const dx = b[0] - a[0]; // delta lon
    const dy = b[1] - a[1]; // delta lat
    // Outward normal for CCW winding: rotate edge vector 90° CW → (dy, -dx)
    const nx = dy;
    const ny = -dx;
    // Bearing of normal: atan2(east, north) in degrees
    let bearing = (Math.atan2(nx, ny) * 180) / Math.PI;
    if (bearing < 0) bearing += 360;

    let dir: "N" | "E" | "S" | "W";
    if (bearing >= 315 || bearing < 45) dir = "N";
    else if (bearing >= 45 && bearing < 135) dir = "E";
    else if (bearing >= 135 && bearing < 225) dir = "S";
    else dir = "W";

    buckets[dir].edges.push([a, b]);
    buckets[dir].bearings.push(bearing);
  }

  return (["N", "E", "S", "W"] as const)
    .filter((d) => buckets[d].edges.length > 0)
    .map((d) => ({
      direction: d,
      edges: buckets[d].edges,
      bearing: buckets[d].bearings.reduce((s, v) => s + v, 0) / buckets[d].bearings.length,
    }));
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
}

export interface ClientBuilding {
  id: string;
  footprint: [number, number][];
  height: number;
  min_height: number;
  name: string;
}

function isBuilding(f: mapboxgl.MapGeoJSONFeature): boolean {
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
  let features: mapboxgl.MapGeoJSONFeature[] = [];
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

  // ── Lighting helper ──────────────────────────────────────────────────────
  const applyLighting = useCallback((sp: SunPosition) => {
    const map = mapRef.current;
    if (!map) return;
    try {
      try { map.setConfigProperty("basemap", "lightPreset", getLightPreset(sp.altitude, sp.azimuth)); } catch {}
      
      // Polar angle: 0° = directly above, 90° = horizon, 180° = below
      const polarAngle = 90 - sp.altitude;
      
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (map as any).setLights([
        {
          id: "sun-directional",
          type: "directional",
          properties: {
            direction: [sp.azimuth, polarAngle],
            color: getTimeOfDayColor(sp.altitude, sp.azimuth),
            intensity: getSunIntensity(sp.altitude),
            "cast-shadows": sp.altitude > 0,
            "shadow-intensity": getShadowIntensity(sp.altitude),
          },
        },
        {
          id: "ambient",
          type: "ambient",
          properties: {
            color: getAmbientColor(sp.altitude),
            intensity: getAmbientIntensity(sp.altitude),
          },
        },
      ]);
      
      console.log(`Lighting: alt=${sp.altitude.toFixed(1)}°, az=${sp.azimuth.toFixed(1)}°, polar=${polarAngle.toFixed(1)}°`);
    } catch (e) { console.warn("Lighting error:", e); }
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
      try { map.setConfigProperty("basemap", "lightPreset", getLightPreset(sp.altitude, sp.azimuth)); } catch {}
      setTimeout(() => {
        applyLighting(sp);
        mapReadyRef.current = true;
        onMapReady?.();
      }, 800);
      // Emit initial bearing once map is ready
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
          // Second click: select the face
          const clickPt: [number, number] = [e.lngLat.lng, e.lngLat.lat];
          const faces = classifyFaces(selectedBuildingRef.current);
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
        const faces = classifyFaces(selectedBuildingRef.current);
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

  // ── Facade: selected building + face edges overlay ──────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    const FACE_COLORS: Record<string, string> = {
      N: "#3b82f6", E: "#22c55e", S: "#ef4444", W: "#f59e0b",
    };
    const layers = ["facade-bldg-fill", "facade-bldg-line", "facade-face-N", "facade-face-E", "facade-face-S", "facade-face-W", "facade-sel-line"];
    const sources = ["facade-bldg-src", "facade-faces-N", "facade-faces-E", "facade-faces-S", "facade-faces-W", "facade-sel-src"];
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

    // Colored edges per face direction
    const faces = classifyFaces(selectedBuildingFootprint);
    for (const face of faces) {
      const srcId = `facade-faces-${face.direction}`;
      const layerId = `facade-face-${face.direction}`;
      const lineFeatures = face.edges.map((edge) => ({
        type: "Feature" as const,
        properties: {},
        geometry: { type: "LineString" as const, coordinates: edge },
      }));
      map.addSource(srcId, { type: "geojson", data: { type: "FeatureCollection", features: lineFeatures } });
      const isSelected = selectedFaceDirection === face.direction;
      map.addLayer({
        id: layerId, type: "line", source: srcId, slot: "top",
        paint: {
          "line-color": FACE_COLORS[face.direction] || "#888",
          "line-width": isSelected ? 6 : 3.5,
          "line-opacity": isSelected ? 1 : 0.7,
        },
      } as any);
    }

    // Extra-highlight the selected face
    if (selectedFaceDirection) {
      const selFace = faces.find((f) => f.direction === selectedFaceDirection);
      if (selFace) {
        const lineFeatures = selFace.edges.map((edge) => ({
          type: "Feature" as const,
          properties: {},
          geometry: { type: "LineString" as const, coordinates: edge },
        }));
        map.addSource("facade-sel-src", { type: "geojson", data: { type: "FeatureCollection", features: lineFeatures } });
        map.addLayer({
          id: "facade-sel-line", type: "line", source: "facade-sel-src", slot: "top",
          paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": 0.4 },
        } as any);
      }
    }
  }, [selectedBuildingFootprint, selectedFaceDirection]);

  // ── Facade: cursor style ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (facadeSelectMode) {
      map.getCanvas().style.cursor = "crosshair";
    }
  }, [facadeSelectMode]);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
