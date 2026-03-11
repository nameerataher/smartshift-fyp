/**
 * ShadowDensityOverlay — split-view comparison slider that reveals a
 * colour-ramped shadow-density heatmap over the Mapbox map.
 *
 * How it works:
 *   1. A Mapbox "fill" layer is added to the map with the shadow grid data.
 *   2. A masking div covers the LEFT portion of the map (up to the slider)
 *      and renders the map tiles without the overlay via backdrop-filter.
 *   3. Dragging the slider resizes the mask — revealing more or less of the
 *      density layer underneath.
 *
 * The net effect: slide right → the heatmap is revealed from the left.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { Layers, Loader2, GripVertical } from "lucide-react";
import { queryBuildingsFromMap, ClientBuilding } from "./MapboxMap";

const API_BASE = "http://localhost:8002";

const DENSITY_SOURCE = "shadow-density-src";
const DENSITY_LAYER = "shadow-density-fill";
const DENSITY_LINE_LAYER = "shadow-density-line";

const COLOR_RAMP: [number, string][] = [
  [0, "#FEF3C7"],
  [10, "#FDE68A"],
  [25, "#FBBF24"],
  [40, "#F97316"],
  [55, "#C026D3"],
  [70, "#7C3AED"],
  [85, "#4338CA"],
  [100, "#1E1B4B"],
];

function buildFillColor(): any {
  const stops: (number | string)[] = [];
  for (const [pct, color] of COLOR_RAMP) {
    stops.push(pct, color);
  }
  return ["interpolate", ["linear"], ["get", "shadow_pct"], ...stops];
}

interface Props {
  map: mapboxgl.Map | null;
  dateStr: string;
  currentMinutes: number;
  visible: boolean;
}

export default function ShadowDensityOverlay({
  map,
  dateStr,
  currentMinutes,
  visible,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [sliderPct, setSliderPct] = useState(50);
  const [hasData, setHasData] = useState(false);
  const [metadata, setMetadata] = useState<Record<string, any> | null>(null);
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const fetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ─── fetch density grid ───────────────────────────────────────
  const fetchDensity = useCallback(async () => {
    if (!map || !visible) return;

    const bounds = map.getBounds();
    const bbox = {
      min_lat: bounds.getSouth(),
      max_lat: bounds.getNorth(),
      min_lon: bounds.getWest(),
      max_lon: bounds.getEast(),
    };

    const center = map.getCenter();
    let buildings: ClientBuilding[] = [];
    try {
      buildings = queryBuildingsFromMap(map, center.lng, center.lat, 1200);
    } catch { /* tilequery fallback on backend */ }

    const hours = Math.floor(currentMinutes / 60);
    const mins = currentMinutes % 60;
    const timeStr = `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/shadow-density`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          bbox,
          grid_size_meters: gridSizeForZoom(map.getZoom()),
          date: dateStr,
          time: timeStr,
          buildings: buildings.length
            ? buildings.map((b) => ({
                id: b.id,
                footprint: b.footprint,
                height: b.height,
                name: b.name,
              }))
            : undefined,
        }),
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      if (!data.success || !data.grid) throw new Error(data.error || "No grid");

      applyGridToMap(map, data.grid);
      setMetadata(data.metadata ?? null);
      setHasData(true);
    } catch (e: any) {
      if (e.name !== "AbortError") console.warn("[shadow-density]", e);
    } finally {
      setLoading(false);
    }
  }, [map, visible, dateStr, currentMinutes]);

  // fetch on visibility / time change (debounced)
  useEffect(() => {
    if (!visible || !map) {
      removeLayer(map);
      setHasData(false);
      return;
    }
    if (fetchTimer.current) clearTimeout(fetchTimer.current);
    fetchTimer.current = setTimeout(fetchDensity, 400);
    return () => {
      if (fetchTimer.current) clearTimeout(fetchTimer.current);
    };
  }, [visible, fetchDensity]);

  // re-fetch on pan/zoom
  useEffect(() => {
    if (!map || !visible) return;
    const handler = () => {
      if (fetchTimer.current) clearTimeout(fetchTimer.current);
      fetchTimer.current = setTimeout(fetchDensity, 600);
    };
    map.on("moveend", handler);
    return () => { map.off("moveend", handler); };
  }, [map, visible, fetchDensity]);

  // cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (fetchTimer.current) clearTimeout(fetchTimer.current);
      removeLayer(map);
    };
  }, []);

  // ─── slider drag ──────────────────────────────────────────────
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pct = ((e.clientX - rect.left) / rect.width) * 100;
    setSliderPct(Math.max(2, Math.min(98, pct)));
  }, []);

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  if (!visible) return null;

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 z-10"
      style={{ pointerEvents: "none", overflow: "hidden" }}
    >
      {/* ── Left mask: covers the map to the left of the slider ── */}
      <div
        className="absolute top-0 bottom-0 left-0"
        style={{
          width: `${sliderPct}%`,
          pointerEvents: "none",
          background:
            "linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,255,255,0) 92%, rgba(255,255,255,0.04) 100%)",
        }}
      />

      {/* ── Right tint: subtle overlay so density layer pops ── */}
      <div
        className="absolute top-0 bottom-0 right-0"
        style={{
          left: `${sliderPct}%`,
          pointerEvents: "none",
          background: "rgba(15,23,42,0.08)",
          borderLeft: "1px solid rgba(255,255,255,0.3)",
        }}
      />

      {/* ── Slider bar ── */}
      <div
        className="absolute top-0 bottom-0"
        style={{
          left: `${sliderPct}%`,
          width: "44px",
          transform: "translateX(-50%)",
          zIndex: 30,
          pointerEvents: "auto",
          touchAction: "none",
          cursor: "col-resize",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {/* Vertical line */}
        <div className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 w-[3px] bg-white/90 shadow-[0_0_8px_rgba(0,0,0,0.4)]" />

        {/* Handle circle */}
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                     w-11 h-11 rounded-full bg-white shadow-xl border-2 border-indigo-500
                     flex items-center justify-center select-none
                     hover:scale-110 transition-transform"
        >
          <GripVertical className="w-5 h-5 text-indigo-600" />
        </div>
      </div>

      {/* ── Labels ── */}
      <div
        className="absolute top-4 pointer-events-none select-none z-20"
        style={{ right: `calc(${100 - sliderPct}% + 20px)` }}
      >
        <span className="bg-white/90 dark:bg-gray-800/90 text-gray-600 dark:text-gray-300 text-xs font-medium px-2.5 py-1 rounded-full shadow">
          Normal View
        </span>
      </div>
      <div
        className="absolute top-4 pointer-events-none select-none z-20"
        style={{ left: `calc(${sliderPct}% + 20px)` }}
      >
        <span className="bg-indigo-600/90 text-white text-xs font-semibold px-2.5 py-1 rounded-full shadow">
          Shadow Density
        </span>
      </div>

      {/* ── Legend (bottom-right of the density side) ── */}
      <div
        className="absolute bottom-8 pointer-events-none select-none z-20"
        style={{ left: `calc(${sliderPct}% + 16px)` }}
      >
        <div className="bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm rounded-xl shadow-lg px-4 py-3 text-xs border border-gray-200 dark:border-gray-700">
          <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-indigo-500" />
            Shadow Coverage
          </div>
          <div className="flex items-center gap-px rounded-md overflow-hidden" style={{ width: 180, height: 14 }}>
            {COLOR_RAMP.map(([, color], i) => (
              <div
                key={i}
                className="h-full"
                style={{ backgroundColor: color, flex: 1 }}
              />
            ))}
          </div>
          <div className="flex justify-between mt-1.5 text-[10px] text-gray-500 dark:text-gray-400 font-medium">
            <span>0% shade (sun)</span>
            <span>100% shade</span>
          </div>
          {metadata && (
            <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 text-[10px] text-gray-400 space-y-0.5">
              <div>{metadata.buildings_used} buildings &middot; {metadata.shadow_polys} shadows</div>
              <div>Sun altitude {metadata.sun_altitude}° &middot; {metadata.rows}&times;{metadata.cols} grid</div>
            </div>
          )}
        </div>
      </div>

      {/* ── Loading indicator ── */}
      {loading && (
        <div
          className="absolute top-4 pointer-events-none select-none z-20"
          style={{ left: `calc(${sliderPct}% + 160px)` }}
        >
          <span className="bg-white/95 text-gray-600 px-3 py-1.5 rounded-full shadow text-xs flex items-center gap-1.5 font-medium">
            <Loader2 className="w-3 h-3 animate-spin text-indigo-500" />
            Computing shadows...
          </span>
        </div>
      )}
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────

function gridSizeForZoom(zoom: number): number {
  if (zoom >= 17) return 10;
  if (zoom >= 16) return 15;
  if (zoom >= 15) return 25;
  if (zoom >= 14) return 40;
  return 60;
}

function applyGridToMap(map: mapboxgl.Map, geojson: any) {
  const existing = map.getSource(DENSITY_SOURCE) as mapboxgl.GeoJSONSource | undefined;
  if (existing) {
    existing.setData(geojson);
    return;
  }

  map.addSource(DENSITY_SOURCE, { type: "geojson", data: geojson });

  map.addLayer(
    {
      id: DENSITY_LAYER,
      type: "fill",
      source: DENSITY_SOURCE,
      paint: {
        "fill-color": buildFillColor(),
        "fill-opacity": 0.55,
      },
    } as any,
  );

  map.addLayer(
    {
      id: DENSITY_LINE_LAYER,
      type: "line",
      source: DENSITY_SOURCE,
      paint: {
        "line-color": "#ffffff",
        "line-opacity": 0.06,
        "line-width": 0.5,
      },
    } as any,
  );
}

function removeLayer(map: mapboxgl.Map | null) {
  if (!map) return;
  try {
    if (map.getLayer(DENSITY_LINE_LAYER)) map.removeLayer(DENSITY_LINE_LAYER);
    if (map.getLayer(DENSITY_LAYER)) map.removeLayer(DENSITY_LAYER);
    if (map.getSource(DENSITY_SOURCE)) map.removeSource(DENSITY_SOURCE);
  } catch { /* already removed */ }
}
