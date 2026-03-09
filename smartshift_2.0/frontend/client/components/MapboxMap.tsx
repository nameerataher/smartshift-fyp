/**
 * Pure map component — no floating HUD overlays.
 * All state lives in the parent (Map.tsx); this component
 * responds to props for lighting, flyTo, route drawing, and
 * click-to-select route points.
 */
import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
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

export interface MapboxMapProps {
  currentMinutes: number;
  dateStr: string;
  flyTo?: FlyToTarget | null;
  routeToDraw?: RouteToDraw | null;
  clearRouteKey?: number;
  selectingPoint?: "from" | "to" | null;
  onPointSelected?: (lat: number, lng: number, which: "from" | "to") => void;
  onMapReady?: () => void;
  fromMarker?: [number, number] | null;
  toMarker?: [number, number] | null;
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
  fromMarker,
  toMarker,
}: MapboxMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const mapReadyRef = useRef(false);
  const isUpdatingRef = useRef(false);

  // Stable refs for callbacks (avoid stale closures in map event handlers)
  const selectingPointRef = useRef(selectingPoint);
  const onPointSelectedRef = useRef(onPointSelected);
  useEffect(() => { selectingPointRef.current = selectingPoint; }, [selectingPoint]);
  useEffect(() => { onPointSelectedRef.current = onPointSelected; }, [onPointSelected]);

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
    if (!map || isUpdatingRef.current) return;
    isUpdatingRef.current = true;
    try {
      try { map.setConfigProperty("basemap", "lightPreset", getLightPreset(sp.altitude, sp.azimuth)); } catch {}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (map as any).setLights([
        {
          id: "sun-directional",
          type: "directional",
          properties: {
            direction: [sp.azimuth, 90 - sp.altitude],
            color: getTimeOfDayColor(sp.altitude),
            intensity: getSunIntensity(sp.altitude),
            "cast-shadows": true,
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
    } catch (e) { console.warn("Lighting error:", e); }
    isUpdatingRef.current = false;
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

    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");

    map.on("load", () => {
      const date = new Date();
      const h = Math.floor(currentMinutes / 60);
      const m = currentMinutes % 60;
      const sp = calculateSunPosition(date, h, m);
      try { map.setConfigProperty("basemap", "lightPreset", getLightPreset(sp.altitude, sp.azimuth)); } catch {}
      setTimeout(() => {
        applyLighting(sp);
        mapReadyRef.current = true;
        onMapReady?.();
      }, 800);
    });

    map.on("click", (e) => {
      const which = selectingPointRef.current;
      if (!which) return;
      onPointSelectedRef.current?.(e.lngLat.lat, e.lngLat.lng, which);
    });

    map.on("error", (e) => console.error("Map error:", e));

    return () => {
      fromMarkerInstanceRef.current?.remove();
      toMarkerInstanceRef.current?.remove();
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

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
}
