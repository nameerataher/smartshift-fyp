import { useState, useRef, useEffect, useCallback } from "react";
import { Link, useLocation } from "react-router-dom";
import { Sun, Map, CheckSquare, Settings, Navigation2, Navigation, MapPin, RotateCcw, Play, Pause, Briefcase, AlertTriangle } from "lucide-react";
import { cn } from "../lib/utils";
import MapboxMap, { LOCATIONS, FlyToTarget, RouteToDraw } from "@/components/MapboxMap";
import { useMode } from "@/hooks/useMode";
import mapboxgl from "mapbox-gl";
import {
  calculateSunPosition,
  formatTime,
  getTimePeriod,
  getDubaiNow,
  calculateUV,
  getUVCategory,
  SunPosition,
} from "@/lib/sunCalculations";

const API_BASE = "http://localhost:8002";
const MAPBOX_TOKEN =
  "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9.WI13BJqDyOu6G38-YP6hog";

// nav items are built dynamically inside the component (mode-aware)

interface RouteResult {
  distanceKm: string;
  durationMin: number;
  shadePct: number;
  score: number;
  riskLevel: string;
  riskColor: string;
  sunExposure: number;
  reason?: string;
}

export default function MapPage() {
  const location = useLocation();
  const { mode, setMode } = useMode();
  const { minutes: initMinutes, dateStr: initDate } = getDubaiNow();

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: AlertTriangle },
    { path: "/map",       label: mode === "commercial" ? "Task Map" : "Route Map", icon: Map },
    { path: "/tasks",     label: mode === "commercial" ? "Tasks" : "Saved Routes", icon: mode === "commercial" ? CheckSquare : Navigation },
    { path: "/settings",  label: "Settings",  icon: Settings },
  ];

  // ── Time state ─────────────────────────────────────────────────────────
  const [currentMinutes, setCurrentMinutes] = useState(initMinutes);
  const [dateStr, setDateStr] = useState(initDate);
  const [isPlaying, setIsPlaying] = useState(false);
  const [animSpeed, setAnimSpeed] = useState(500);
  const animRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sliderDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [sliderMinutes, setSliderMinutes] = useState(initMinutes);

  // Keep sliderMinutes in sync with currentMinutes (but only when not dragging)
  const isDraggingRef = useRef(false);

  // ── Sun position ────────────────────────────────────────────────────────
  const [sunPos, setSunPos] = useState<SunPosition | null>(null);
  useEffect(() => {
    const date = dateStr ? new Date(dateStr) : new Date();
    setSunPos(calculateSunPosition(date, Math.floor(currentMinutes / 60), currentMinutes % 60));
  }, [currentMinutes, dateStr]);

  // ── Animation ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (isPlaying) {
      animRef.current = setInterval(() => {
        setCurrentMinutes((p) => {
          const next = (p + 5) % 1440;
          if (!isDraggingRef.current) setSliderMinutes(next);
          return next;
        });
      }, animSpeed);
    } else {
      if (animRef.current) clearInterval(animRef.current);
    }
    return () => { if (animRef.current) clearInterval(animRef.current); };
  }, [isPlaying, animSpeed]);

  // ── Map flyTo ───────────────────────────────────────────────────────────
  const [flyToTarget, setFlyToTarget] = useState<FlyToTarget | null>(null);
  const flyToKeyRef = useRef(0);

  const flyTo = (key: string) => {
    const loc = LOCATIONS[key];
    if (!loc) return;
    flyToKeyRef.current += 1;
    setFlyToTarget({ ...loc, key: flyToKeyRef.current });
  };

  const flyToCoords = useCallback((center: [number, number], zoom = 16) => {
    flyToKeyRef.current += 1;
    setFlyToTarget({ center, zoom, pitch: 55, bearing: 0, key: flyToKeyRef.current });
  }, []);

  // ── Location search ─────────────────────────────────────────────────────
  const [locationSearch, setLocationSearch] = useState("");
  const [suggestions, setSuggestions] = useState<{ place_name: string; center: [number, number] }[]>([]);
  const geoTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchInput = (val: string) => {
    setLocationSearch(val);
    if (geoTimeout.current) clearTimeout(geoTimeout.current);
    if (val.length < 2) { setSuggestions([]); return; }
    geoTimeout.current = setTimeout(async () => {
      try {
        const res = await fetch(
          `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(val)}.json?access_token=${MAPBOX_TOKEN}&proximity=55.2708,25.2048&types=poi,address,place&limit=5`
        );
        const data = await res.json();
        setSuggestions(data.features || []);
      } catch {}
    }, 300);
  };

  const selectSuggestion = (s: { place_name: string; center: [number, number] }) => {
    setLocationSearch(s.place_name);
    setSuggestions([]);
    flyToCoords(s.center, 16);
  };

  // ── Route finding ───────────────────────────────────────────────────────
  const [routeFrom, setRouteFrom] = useState("");
  const [routeTo, setRouteTo] = useState("");
  const [travelMode, setTravelMode] = useState<"walking" | "cycling">("walking");
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [routeToDraw, setRouteToDraw] = useState<RouteToDraw | null>(null);
  const routeKeyRef = useRef(0);
  const [clearRouteKey, setClearRouteKey] = useState(0);
  const clearKeyRef = useRef(0);

  const [fromCoords, setFromCoords] = useState<[number, number] | null>(null);
  const [toCoords, setToCoords] = useState<[number, number] | null>(null);
  const [selectingPoint, setSelectingPoint] = useState<"from" | "to" | null>(null);

  const handlePointSelected = useCallback((lat: number, lng: number, which: "from" | "to") => {
    const label = `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
    if (which === "from") {
      setFromCoords([lng, lat]);
      setRouteFrom(label);
    } else {
      setToCoords([lng, lat]);
      setRouteTo(label);
    }
    setSelectingPoint(null);
  }, []);

  const clearRoute = () => {
    setFromCoords(null);
    setToCoords(null);
    setRouteFrom("");
    setRouteTo("");
    setRouteResult(null);
    clearKeyRef.current += 1;
    setClearRouteKey(clearKeyRef.current);
  };

  const findRoute = async () => {
    if (!fromCoords || !toCoords) {
      alert("Click the 📍 pin button next to From/To, then click on the map to set points.");
      return;
    }
    setRouteLoading(true);
    try {
      const date = dateStr || new Date().toISOString().split("T")[0];
      const time = formatTime(currentMinutes);
      const payload = {
        start: { lat: fromCoords[1], lon: fromCoords[0] },
        end:   { lat: toCoords[1],   lon: toCoords[0]   },
        mode: travelMode,
        departure_time: new Date(`${date}T${time}:00`).toISOString(),
        mapbox_token: MAPBOX_TOKEN,
        alternatives: 3,
      };
      const res = await fetch(`${API_BASE}/api/v2/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      let data: Record<string, unknown> | null = null;
      try { data = await res.json(); } catch {}
      if (!res.ok || !data) throw new Error((data as { error?: string })?.error || `API ${res.status}`);
      if (!(data as { success?: boolean }).success) throw new Error((data as { error?: string }).error || "Failed");

      const isV2 = !!(data.recommendation && (data.recommendation as Record<string, unknown>).recommended_route);
      const rec = isV2 ? (data.recommendation as Record<string, unknown>) : null;
      const route = isV2 ? (rec!.recommended_route as Record<string, unknown>) : data;

      const score = isV2 ? Math.round(((route as Record<string, unknown>).comfort_score as number || 0) * 100) : Math.round((data.shade_score as number) || 0);
      let heatRiskPct = 0;
      if (isV2 && (route as Record<string, unknown>).risk_distribution) {
        const r = (route as Record<string, unknown>).risk_distribution as Record<string, number>;
        const total = (r.high || 0) + (r.medium || 0) + (r.low || 0);
        heatRiskPct = total > 0 ? (((r.high || 0) + 0.5 * (r.medium || 0)) / total) * 100 : 0;
      } else {
        heatRiskPct = (data.average_heat_risk as number) || 0;
      }
      const riskLevel = heatRiskPct <= 30 ? "LOW" : heatRiskPct <= 60 ? "MEDIUM" : "HIGH";
      const riskColor = riskLevel === "LOW" ? "#22c55e" : riskLevel === "MEDIUM" ? "#f59e0b" : "#ef4444";
      const distanceKm = (((route as Record<string, unknown>).distance_meters as number || (data.total_distance as number) || 0) / 1000).toFixed(1);
      const durationMin = Math.round(((route as Record<string, unknown>).duration_seconds as number || (data.total_duration as number) || 0) / 60);
      const shadePct = Math.round((route as Record<string, unknown>).shade_coverage_percent as number || (data.average_shade_coverage as number) || 0);
      const sunExposure = Math.round((route as Record<string, unknown>).sun_exposure_minutes as number || (data.sun_exposure_minutes as number) || 0);
      const reason = isV2 && rec ? (rec.recommendation_reason as string) : undefined;

      setRouteResult({ distanceKm, durationMin, shadePct, score, riskLevel, riskColor, sunExposure, reason });

      // Extract coordinates
      let coordinates: [number, number][] = [];
      if (isV2 && (route as Record<string, unknown>).geometry) {
        coordinates = ((route as Record<string, unknown>).geometry as { coordinates: [number, number][] }).coordinates || [];
      } else if (Array.isArray(data.geometry) && (data.geometry as unknown[]).length > 1) {
        coordinates = data.geometry as [number, number][];
      }

      if (coordinates.length >= 2) {
        routeKeyRef.current += 1;
        setRouteToDraw({ coordinates, travelMode: isV2 && rec ? (rec.travel_mode as string || travelMode) : travelMode, key: routeKeyRef.current });
      }
    } catch (err) {
      alert(`Route error: ${(err as Error).message}\n\nMake sure server is running: python api_server.py`);
    }
    setRouteLoading(false);
  };

  // ── GPS location for route from ─────────────────────────────────────────
  const useGPSForFrom = () => {
    if (!navigator.geolocation) { alert("GPS not available"); return; }
    navigator.geolocation.getCurrentPosition((pos) => {
      const { latitude: lat, longitude: lng } = pos.coords;
      setFromCoords([lng, lat]);
      setRouteFrom(`${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`);
      flyToCoords([lng, lat]);
    }, () => alert("Could not get GPS location"));
  };

  // ── Derived ─────────────────────────────────────────────────────────────
  const uv = calculateUV(dateStr ? new Date(dateStr) : new Date(), currentMinutes);
  const uvCat = getUVCategory(uv);
  const period = sunPos ? getTimePeriod(sunPos.altitude, sunPos.azimuth) : "—";
  const timeOptions = Array.from({ length: 49 }, (_, i) => i * 30);

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ── Header (matches AppLayout exactly) ──────────────────────────── */}
      <header className="border-b border-border bg-card sticky top-0 z-50 shadow-sm shrink-0">
        <div className="max-w-full px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary to-amber-400 rounded-lg flex items-center justify-center shadow-md">
                <Sun className="w-6 h-6 text-primary-foreground" />
              </div>
              <span className="text-xl font-bold text-foreground hidden sm:block">SmartShift</span>
            </Link>

            {/* Mode Toggle */}
            <div className="hidden sm:flex items-center gap-2 bg-muted rounded-lg p-1">
              <button
                onClick={() => setMode("commercial")}
                className={cn("px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5",
                  mode === "commercial" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
              >
                <Briefcase className="w-4 h-4" />
                <span className="hidden lg:inline">Commercial</span>
              </button>
              <button
                onClick={() => setMode("personal")}
                className={cn("px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5",
                  mode === "personal" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
              >
                <Navigation className="w-4 h-4" />
                <span className="hidden lg:inline">Personal</span>
              </button>
            </div>

            <nav className="flex items-center gap-1">
              {navItems.map(({ path, label, icon: Icon }) => (
                <Link
                  key={path}
                  to={path}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200",
                    location.pathname === path
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted"
                  )}
                >
                  <Icon className="w-5 h-5" />
                  <span className="hidden sm:inline text-sm font-medium">{label}</span>
                </Link>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* ── Content: map + sidebar ──────────────────────────────────────── */}
      <div className="flex-1 flex min-h-0">

        {/* ── LEFT: Mapbox map ──────────────────────────────────────────── */}
        <div className="flex-1 relative min-h-0">
          <MapboxMap
            currentMinutes={currentMinutes}
            dateStr={dateStr}
            flyTo={flyToTarget}
            routeToDraw={routeToDraw}
            clearRouteKey={clearRouteKey}
            selectingPoint={selectingPoint}
            onPointSelected={handlePointSelected}
            fromMarker={fromCoords}
            toMarker={toCoords}
          />
        </div>

        {/* ── RIGHT: Sidebar ────────────────────────────────────────────── */}
        <div className="w-96 shrink-0 border-l border-border bg-background overflow-y-auto flex flex-col">

          {/* ── Location Search ─────────────────────────────────────────── */}
          <div className="px-5 py-4 border-b border-border">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Location Search
            </h2>
            <div className="relative">
              <input
                type="text"
                value={locationSearch}
                onChange={(e) => handleSearchInput(e.target.value)}
                placeholder="Search buildings, areas, landmarks…"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-foreground text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary"
              />
              {suggestions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-xl z-50 max-h-56 overflow-y-auto">
                  {suggestions.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => selectSuggestion(s)}
                      className="w-full text-left px-3 py-2.5 text-sm text-foreground hover:bg-muted transition-colors border-b border-border last:border-0"
                    >
                      {s.place_name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ── Saved Places / Landmarks ─────────────────────────────────── */}
          <div className="px-5 py-4 border-b border-border">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Saved Places
            </h2>
            <div className="space-y-2">
              {[
                { key: "marina",   emoji: "🏙️", label: "Dubai Marina",    sub: "Waterfront skyline" },
                { key: "downtown", emoji: "🏢", label: "Downtown Dubai",  sub: "Burj Khalifa area" },
                { key: "frame",    emoji: "🖼️", label: "Dubai Frame",     sub: "Zabeel Park" },
              ].map(({ key, emoji, label, sub }) => (
                <button
                  key={key}
                  onClick={() => flyTo(key)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border border-border bg-background hover:bg-muted transition-colors text-left group"
                >
                  <span className="text-xl shrink-0">{emoji}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground">{label}</div>
                    <div className="text-xs text-muted-foreground">{sub}</div>
                  </div>
                  <MapPin className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors ml-auto shrink-0" />
                </button>
              ))}
            </div>
          </div>

          {/* ── Navigation Routing ───────────────────────────────────────── */}
          <div className="px-5 py-4 border-b border-border">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Shade-Optimized Route
            </h2>

            {/* From / To */}
            <div className="space-y-2 mb-3">
              {/* From */}
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-green-500 shrink-0" />
                <div className="flex-1 flex gap-1.5">
                  <input
                    type="text"
                    value={routeFrom}
                    readOnly
                    placeholder="From — click 📍 then tap map"
                    className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-border bg-muted text-sm text-foreground placeholder-muted-foreground text-xs"
                  />
                  <button
                    onClick={() => setSelectingPoint(selectingPoint === "from" ? null : "from")}
                    className={cn(
                      "px-2.5 py-2 rounded-lg border text-sm font-medium transition-colors shrink-0",
                      selectingPoint === "from"
                        ? "bg-amber-100 border-amber-400 text-amber-700"
                        : "bg-background border-border text-muted-foreground hover:text-foreground hover:bg-muted"
                    )}
                    title="Click map to set start point"
                  >
                    📍
                  </button>
                  <button
                    onClick={useGPSForFrom}
                    className="px-2.5 py-2 rounded-lg border border-border bg-background text-muted-foreground hover:text-foreground hover:bg-muted transition-colors text-sm shrink-0"
                    title="Use current GPS location"
                  >
                    📡
                  </button>
                </div>
              </div>

              {/* To */}
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-blue-500 shrink-0" />
                <div className="flex-1 flex gap-1.5">
                  <input
                    type="text"
                    value={routeTo}
                    readOnly
                    placeholder="To — click 📍 then tap map"
                    className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-border bg-muted text-sm text-foreground placeholder-muted-foreground text-xs"
                  />
                  <button
                    onClick={() => setSelectingPoint(selectingPoint === "to" ? null : "to")}
                    className={cn(
                      "px-2.5 py-2 rounded-lg border text-sm font-medium transition-colors shrink-0",
                      selectingPoint === "to"
                        ? "bg-amber-100 border-amber-400 text-amber-700"
                        : "bg-background border-border text-muted-foreground hover:text-foreground hover:bg-muted"
                    )}
                    title="Click map to set end point"
                  >
                    📍
                  </button>
                </div>
              </div>
            </div>

            {selectingPoint && (
              <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
                Click anywhere on the map to set the <strong>{selectingPoint === "from" ? "start" : "destination"}</strong> point
              </p>
            )}

            {/* Travel mode */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              {(["walking", "cycling"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setTravelMode(mode)}
                  className={cn(
                    "py-2 rounded-lg border text-sm font-medium transition-colors",
                    travelMode === mode
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-background border-border text-foreground hover:bg-muted"
                  )}
                >
                  {mode === "walking" ? "🚶 Walking" : "🚴 Cycling"}
                </button>
              ))}
            </div>

            {/* Buttons */}
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={findRoute}
                disabled={routeLoading}
                className="py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {routeLoading ? "Finding…" : "🗺️ Find Route"}
              </button>
              <button
                onClick={clearRoute}
                className="py-2.5 rounded-lg border border-border bg-background text-foreground text-sm font-medium hover:bg-muted transition-colors"
              >
                <RotateCcw className="w-4 h-4 inline mr-1" />
                Clear
              </button>
            </div>

            {/* Route result */}
            {routeResult && (
              <div className="mt-3 p-3 rounded-xl bg-blue-50 border border-blue-200">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs font-semibold text-blue-700">Route Found</span>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full font-bold text-white"
                    style={{ background: routeResult.score >= 70 ? "#22c55e" : routeResult.score >= 50 ? "#f59e0b" : "#ef4444" }}
                  >
                    {routeResult.score}/100
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                  <div className="text-center p-1.5 rounded-lg bg-white border border-border">
                    <div className="text-muted-foreground">Dist</div>
                    <div className="font-bold text-foreground">{routeResult.distanceKm} km</div>
                  </div>
                  <div className="text-center p-1.5 rounded-lg bg-white border border-border">
                    <div className="text-muted-foreground">Time</div>
                    <div className="font-bold text-foreground">{routeResult.durationMin} min</div>
                  </div>
                  <div className="text-center p-1.5 rounded-lg bg-white border border-border">
                    <div className="text-muted-foreground">Shade</div>
                    <div className="font-bold text-foreground">{routeResult.shadePct}%</div>
                  </div>
                </div>
                <div className="text-xs font-semibold" style={{ color: routeResult.riskColor }}>
                  🌡️ {routeResult.riskLevel} heat risk · ☀️ {routeResult.sunExposure} min sun
                </div>
                {routeResult.reason && (
                  <p className="text-xs text-muted-foreground mt-1">{routeResult.reason}</p>
                )}
              </div>
            )}
          </div>

          {/* ── Time Controls ────────────────────────────────────────────── */}
          <div className="px-5 py-4 border-b border-border">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">
              Time Controls
            </h2>

            {/* Big time + period */}
            <div className="flex items-baseline gap-3 mb-4">
              <span className="text-4xl font-bold font-mono text-foreground tracking-tight">
                {formatTime(currentMinutes)}
              </span>
              <span className="text-sm text-primary font-medium">{period}</span>
            </div>

            {/* Time slider */}
            <div className="mb-3">
              <input
                type="range"
                min={0}
                max={1440}
                step={5}
                value={sliderMinutes}
                onChange={(e) => {
                  isDraggingRef.current = true;
                  const val = parseInt(e.target.value);
                  setSliderMinutes(val);
                  if (sliderDebounceRef.current) clearTimeout(sliderDebounceRef.current);
                  sliderDebounceRef.current = setTimeout(() => {
                    setCurrentMinutes(val);
                    isDraggingRef.current = false;
                  }, 60);
                }}
                className="w-full accent-primary h-2 cursor-pointer"
              />
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                {["00:00", "06:00", "12:00", "18:00", "24:00"].map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </div>
            </div>

            {/* Dropdown + Date */}
            <div className="grid grid-cols-2 gap-2 mb-3">
              <select
                value={Math.round(currentMinutes / 30) * 30}
                onChange={(e) => {
                  const val = parseInt(e.target.value);
                  setCurrentMinutes(val);
                  setSliderMinutes(val);
                }}
                className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              >
                {timeOptions.map((m) => (
                  <option key={m} value={m}>{formatTime(m)}</option>
                ))}
              </select>
              <input
                type="date"
                value={dateStr}
                onChange={(e) => setDateStr(e.target.value)}
                className="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
              />
            </div>

            {/* Play / Pause / Reset */}
            <div className="flex gap-2 mb-3">
              <button
                onClick={() => setIsPlaying((p) => !p)}
                className={cn(
                  "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium transition-colors",
                  isPlaying
                    ? "bg-amber-500 hover:bg-amber-400 text-white"
                    : "bg-primary text-primary-foreground hover:bg-primary/90"
                )}
              >
                {isPlaying ? <><Pause className="w-4 h-4" /> Pause</> : <><Play className="w-4 h-4" /> Play</>}
              </button>
              <button
                onClick={() => { setIsPlaying(false); setCurrentMinutes(720); setSliderMinutes(720); }}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg border border-border bg-background text-foreground text-sm font-medium hover:bg-muted transition-colors"
              >
                <RotateCcw className="w-4 h-4" /> Reset
              </button>
            </div>

            {/* Speed */}
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground shrink-0">Speed</span>
              <input
                type="range"
                min={100}
                max={2000}
                step={100}
                value={2100 - animSpeed}
                onChange={(e) => setAnimSpeed(2100 - parseInt(e.target.value))}
                className="flex-1 accent-primary h-1.5 cursor-pointer"
              />
              <span className="text-xs text-muted-foreground w-8 text-right font-mono">
                {(1000 / animSpeed).toFixed(1)}×
              </span>
            </div>

            {/* Astronomical events */}
            <div className="mt-4">
              <div className="text-xs text-muted-foreground mb-2">Jump to equinox / solstice</div>
              <div className="grid grid-cols-4 gap-1.5">
                {[
                  { label: "🌱", title: "Spring", month: 2,  day: 20 },
                  { label: "☀️", title: "Summer", month: 5,  day: 21 },
                  { label: "🍂", title: "Autumn", month: 8,  day: 23 },
                  { label: "❄️", title: "Winter", month: 11, day: 21 },
                ].map(({ label, title, month, day }) => (
                  <button
                    key={title}
                    title={title}
                    onClick={() => {
                      const d = new Date(new Date().getFullYear(), month, day);
                      setDateStr(d.toISOString().split("T")[0]);
                    }}
                    className="py-2 rounded-lg border border-border bg-background hover:bg-muted text-base transition-colors"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* ── Sun Position ─────────────────────────────────────────────── */}
          <div className="px-5 py-4">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Sun Position
            </h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "Azimuth",  value: sunPos ? `${sunPos.azimuth.toFixed(1)}°`  : "--", color: "text-amber-600" },
                { label: "Altitude", value: sunPos ? `${sunPos.altitude.toFixed(1)}°` : "--", color: "text-orange-500" },
                { label: "Sunrise",  value: sunPos?.sunrise ?? "--", color: "text-yellow-600" },
                { label: "Sunset",   value: sunPos?.sunset  ?? "--", color: "text-rose-500"   },
              ].map(({ label, value, color }) => (
                <div key={label} className="p-3 rounded-xl bg-muted/50 border border-border">
                  <div className="text-xs text-muted-foreground mb-0.5">{label}</div>
                  <div className={`text-base font-bold ${color}`}>{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className="p-3 rounded-xl bg-muted/50 border border-border">
                <div className="text-xs text-muted-foreground mb-0.5">UV Index</div>
                <div className="text-base font-bold" style={{ color: uvCat.color }}>{uv} — {uvCat.level}</div>
              </div>
              <div className="p-3 rounded-xl bg-muted/50 border border-border">
                <div className="text-xs text-muted-foreground mb-0.5">Daylight</div>
                <div className={`text-base font-bold ${sunPos?.isDaylight ? "text-amber-500" : "text-slate-400"}`}>
                  {sunPos?.isDaylight ? "☀️ Day" : "🌙 Night"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
