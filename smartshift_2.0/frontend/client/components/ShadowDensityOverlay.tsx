/**
 * ShadowDensityOverlay — true split-view comparison slider with a
 * canvas-rendered heatmap that shows shadow density.
 *
 * The heatmap is drawn on an HTML canvas that sits on top of the Mapbox
 * map.  The canvas is CSS-clipped to only the RIGHT side of the slider
 * so the left side stays as a clean, unobstructed normal view.
 *
 * Colour scheme: blue (low shadow / sunny) → red (high shadow / shaded)
 */

import { useEffect, useRef, useState, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { Loader2, GripVertical, Eye } from "lucide-react";
import { queryBuildingsFromMap, ClientBuilding } from "./MapboxMap";

const API_BASE = "http://localhost:8080";

// blue → cyan → green → yellow → orange → red
const GRADIENT_STOPS: [number, number, number, number][] = [
  [0, 60, 255, 0],      // 0 %  — blue  (low shadow)
  [0, 180, 255, 0.15],  // 15 % — cyan
  [0, 220, 120, 0.3],   // 30 % — green
  [255, 255, 0, 0.5],   // 50 % — yellow
  [255, 160, 0, 0.7],   // 70 % — orange
  [255, 40, 40, 0.85],  // 85 % — red-orange
  [200, 0, 0, 1.0],     // 100% — deep red (high shadow)
];

function buildGradientCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 1;
  const ctx = c.getContext("2d")!;
  const grad = ctx.createLinearGradient(0, 0, 256, 0);
  for (const [r, g, b, stop] of GRADIENT_STOPS) {
    grad.addColorStop(stop, `rgb(${r},${g},${b})`);
  }
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 256, 1);
  return c;
}

interface HeatPoint {
  x: number;
  y: number;
  value: number;
}

interface GridCell {
  lat: number;
  lon: number;
  shadow_pct: number;
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
  const [metadata, setMetadata] = useState<Record<string, any> | null>(null);
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const gridDataRef = useRef<GridCell[]>([]);
  const gradientRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);

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

      const points: GridCell[] = (data.grid.points as GridCell[]) ?? [];
      gridDataRef.current = points;
      setMetadata(data.metadata ?? null);
      drawHeatmap();
    } catch (e: any) {
      if (e.name !== "AbortError") console.warn("[shadow-density]", e);
    } finally {
      setLoading(false);
    }
  }, [map, visible, dateStr, currentMinutes]);

  // ─── canvas heatmap renderer ──────────────────────────────────
  const drawHeatmap = useCallback(() => {
    const canvas = canvasRef.current;
    const m = map;
    if (!canvas || !m || !gridDataRef.current.length) return;

    const dpr = window.devicePixelRatio || 1;
    const mapCanvas = m.getCanvas();
    const w = mapCanvas.clientWidth;
    const h = mapCanvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (!gradientRef.current) {
      gradientRef.current = buildGradientCanvas();
    }
    const gradCanvas = gradientRef.current;
    const gradCtx = gradCanvas.getContext("2d")!;
    const gradPixels = gradCtx.getImageData(0, 0, 256, 1).data;

    const points: HeatPoint[] = [];
    for (const cell of gridDataRef.current) {
      const pt = m.project([cell.lon, cell.lat]);
      if (pt.x < -50 || pt.x > w + 50 || pt.y < -50 || pt.y > h + 50) continue;
      points.push({ x: pt.x, y: pt.y, value: cell.shadow_pct });
    }

    if (!points.length) return;

    const radius = radiusForZoom(m.getZoom());

    // 1) draw intensity circles onto an offscreen alpha canvas
    const alphaCanvas = document.createElement("canvas");
    alphaCanvas.width = w * dpr;
    alphaCanvas.height = h * dpr;
    const aCtx = alphaCanvas.getContext("2d")!;
    aCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

    for (const p of points) {
      const intensity = p.value / 100;
      aCtx.globalAlpha = Math.max(0.02, intensity * 0.8);
      const grad = aCtx.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius);
      grad.addColorStop(0, `rgba(0,0,0,${intensity})`);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      aCtx.fillStyle = grad;
      aCtx.fillRect(p.x - radius, p.y - radius, radius * 2, radius * 2);
    }

    // 2) colorize: read alpha channel, map to gradient colour
    const imgData = aCtx.getImageData(0, 0, alphaCanvas.width, alphaCanvas.height);
    const pixels = imgData.data;
    for (let i = 0; i < pixels.length; i += 4) {
      const a = pixels[i + 3]; // alpha = intensity
      if (a < 2) {
        pixels[i + 3] = 0;
        continue;
      }
      const gradIdx = Math.min(255, a) * 4;
      pixels[i] = gradPixels[gradIdx];
      pixels[i + 1] = gradPixels[gradIdx + 1];
      pixels[i + 2] = gradPixels[gradIdx + 2];
      pixels[i + 3] = Math.min(255, Math.round(a * 0.75));
    }

    ctx.putImageData(imgData, 0, 0);
  }, [map]);

  // redraw on every map render frame when visible
  useEffect(() => {
    if (!map || !visible) return;
    const onRender = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(drawHeatmap);
    };
    map.on("render", onRender);
    return () => {
      map.off("render", onRender);
      cancelAnimationFrame(rafRef.current);
    };
  }, [map, visible, drawHeatmap]);

  // fetch on visibility / time change
  useEffect(() => {
    if (!visible || !map) {
      gridDataRef.current = [];
      setMetadata(null);
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

  // cleanup
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (fetchTimer.current) clearTimeout(fetchTimer.current);
      cancelAnimationFrame(rafRef.current);
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
      {/* ── Heatmap canvas — clipped to RIGHT of slider ── */}
      <canvas
        ref={canvasRef}
        className="absolute top-0 left-0"
        style={{
          clipPath: `inset(0 0 0 ${sliderPct}%)`,
          pointerEvents: "none",
        }}
      />

      {/* ── Subtle tint on the density side ── */}
      <div
        className="absolute top-0 bottom-0 right-0"
        style={{
          left: `${sliderPct}%`,
          pointerEvents: "none",
          background: "rgba(10,15,30,0.06)",
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
        <div className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 w-[3px] bg-white/90 shadow-[0_0_12px_rgba(0,0,0,0.5)]" />
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                     w-11 h-11 rounded-full bg-white shadow-xl border-2 border-blue-500
                     flex items-center justify-center select-none
                     hover:scale-110 transition-transform"
        >
          <GripVertical className="w-5 h-5 text-blue-600" />
        </div>
      </div>

      {/* ── Labels ── */}
      <div
        className="absolute top-4 pointer-events-none select-none z-20"
        style={{ right: `calc(${100 - sliderPct}% + 24px)` }}
      >
        <span className="bg-white/90 dark:bg-gray-800/90 text-gray-600 dark:text-gray-300 text-xs font-medium px-2.5 py-1.5 rounded-full shadow flex items-center gap-1.5">
          <Eye className="w-3 h-3" />
          Normal View
        </span>
      </div>
      <div
        className="absolute top-4 pointer-events-none select-none z-20"
        style={{ left: `calc(${sliderPct}% + 24px)` }}
      >
        <span className="bg-gradient-to-r from-blue-600 to-red-600 text-white text-xs font-semibold px-2.5 py-1.5 rounded-full shadow">
          Shadow Density
        </span>
      </div>

      {/* ── Legend ── */}
      <div
        className="absolute bottom-8 pointer-events-none select-none z-20"
        style={{ left: `calc(${sliderPct}% + 16px)` }}
      >
        <div className="bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm rounded-xl shadow-lg px-4 py-3 text-xs border border-gray-200/60 dark:border-gray-700">
          <div className="font-semibold mb-2 text-gray-700 dark:text-gray-200">
            Shadow Exposure
          </div>
          <div
            className="rounded-md overflow-hidden"
            style={{
              width: 180,
              height: 14,
              background: "linear-gradient(90deg, rgb(0,60,255) 0%, rgb(0,180,255) 15%, rgb(0,220,120) 30%, rgb(255,255,0) 50%, rgb(255,160,0) 70%, rgb(255,40,40) 85%, rgb(200,0,0) 100%)",
            }}
          />
          <div className="flex justify-between mt-1.5 text-[10px] text-gray-500 dark:text-gray-400 font-medium">
            <span>Low (sunny)</span>
            <span>High (shaded)</span>
          </div>
          {metadata && (
            <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 text-[10px] text-gray-400 space-y-0.5">
              <div>{metadata.buildings_used} buildings &middot; {metadata.shadow_polys} shadow projections</div>
              <div>Sun {metadata.sun_altitude}&deg; altitude &middot; {metadata.rows}&times;{metadata.cols} sample grid</div>
            </div>
          )}
        </div>
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div
          className="absolute top-4 pointer-events-none select-none z-20"
          style={{ left: `calc(${sliderPct}% + 180px)` }}
        >
          <span className="bg-white/95 text-gray-600 px-3 py-1.5 rounded-full shadow text-xs flex items-center gap-1.5 font-medium">
            <Loader2 className="w-3 h-3 animate-spin text-blue-500" />
            Projecting shadows...
          </span>
        </div>
      )}
    </div>
  );
}

// ─── helpers ────────────────────────────────────────────────────

function gridSizeForZoom(zoom: number): number {
  if (zoom >= 17) return 8;
  if (zoom >= 16) return 12;
  if (zoom >= 15) return 20;
  if (zoom >= 14) return 35;
  return 50;
}

function radiusForZoom(zoom: number): number {
  if (zoom >= 17) return 28;
  if (zoom >= 16) return 22;
  if (zoom >= 15) return 16;
  if (zoom >= 14) return 12;
  return 10;
}
