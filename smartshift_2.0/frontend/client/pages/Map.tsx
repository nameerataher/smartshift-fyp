import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { toast } from "sonner";
import {
  Sun, Map, CheckSquare, Settings, Navigation2, Navigation, MapPin,
  RotateCcw, Play, Pause, Briefcase, AlertTriangle, X, CheckCircle,
  Plus, Clock, Zap, Search, Loader2,
} from "lucide-react";
import { cn } from "../lib/utils";
import MapboxMap, { LOCATIONS, FlyToTarget, RouteToDraw } from "@/components/MapboxMap";
import { useMode } from "@/hooks/useMode";
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

interface SearchSuggestion {
  mapbox_id: string;
  name: string;
  full_address?: string;
  place_formatted?: string;
}

interface SiteDraft {
  taskName: string;
  locationLabel: string;
  durationMinutes: number;
  startHour: number;
  endHour: number;
}

interface WindowRec {
  id: string;
  title: string;
  start: number;
  end: number;
  timeLabel: string;
  uv: number;
  uvCat: { level: string; color: string };
  shadePct: number;
  quality: "excellent" | "good" | "fair" | "poor";
  reason?: string;
}

const SAVED_PLACES = [
  { key: "marina", label: "Marina" },
  { key: "downtown", label: "Downtown" },
  { key: "frame", label: "Dubai Frame" },
];

function recQuality(shadePct: number): WindowRec["quality"] {
  if (shadePct >= 75) return "excellent";
  if (shadePct >= 55) return "good";
  if (shadePct >= 35) return "fair";
  return "poor";
}

function qualityTitle(quality: WindowRec["quality"]): string {
  return quality === "excellent" ? "Best Window" : quality === "good" ? "Recommended" : quality === "fair" ? "Alternative" : "Fallback";
}

async function fetchScheduleFromBackend(
  taskName: string,
  lat: number,
  lon: number,
  dateStr: string,
  durationMinutes: number,
  startHour: number,
  endHour: number,
  buildingFace?: string
): Promise<WindowRec[]> {
  try {
    const payload: Record<string, unknown> = {
      task_name: taskName,
      mode: "shadow_only",
      work_zone: {
        zone_id: `site_${Date.now()}`,
        name: taskName,
        lat,
        lon,
        radius: 50,
        is_facade: !!buildingFace,
        orientation: buildingFace ? { N: 0, E: 90, S: 180, W: 270 }[buildingFace] : undefined,
      },
      task_duration_minutes: durationMinutes,
      date: dateStr,
      start_hour: startHour,
      end_hour: endHour,
      recommendation_count: 5,
      rank_by: "shade",
      building_face: buildingFace,
    };

    const res = await fetch(`${API_BASE}/api/v2/schedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) throw new Error(`API error ${res.status}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Schedule failed");

    const rec = data.recommendation || {};
    const best = rec.best_schedule;
    const alternatives = rec.alternatives || [];

    const results: WindowRec[] = [];

    if (best) {
      const startTime = new Date(best.start_time);
      const endTime = new Date(best.end_time);
      const startMin = startTime.getHours() * 60 + startTime.getMinutes();
      const endMin = endTime.getHours() * 60 + endTime.getMinutes();
      const shadePct = Math.round(best.shadow_percentage || 0);
      const quality = recQuality(shadePct);
      const uv = calculateUV(new Date(dateStr), Math.floor((startMin + endMin) / 2));
      
      results.push({
        id: `best-${startMin}-${endMin}`,
        title: qualityTitle(quality),
        start: startMin,
        end: endMin,
        timeLabel: `${formatTime(startMin)} – ${formatTime(endMin)}`,
        uv,
        uvCat: getUVCategory(uv),
        shadePct,
        quality,
        reason: rec.recommendation_reason,
      });
    }

    for (const alt of alternatives.slice(0, 4)) {
      const startTime = new Date(alt.start_time);
      const endTime = new Date(alt.end_time);
      const startMin = startTime.getHours() * 60 + startTime.getMinutes();
      const endMin = endTime.getHours() * 60 + endTime.getMinutes();
      const shadePct = Math.round(alt.shadow_percentage || 0);
      const quality = recQuality(shadePct);
      const uv = calculateUV(new Date(dateStr), Math.floor((startMin + endMin) / 2));
      
      results.push({
        id: `alt-${startMin}-${endMin}`,
        title: qualityTitle(quality),
        start: startMin,
        end: endMin,
        timeLabel: `${formatTime(startMin)} – ${formatTime(endMin)}`,
        uv,
        uvCat: getUVCategory(uv),
        shadePct,
        quality,
      });
    }

    return results;
  } catch (err) {
    console.error("Schedule API error:", err);
    return computeWindowsFallback(dateStr, durationMinutes, startHour, endHour);
  }
}

function computeWindowsFallback(dateStr: string, durationMinutes: number, startHour: number, endHour: number): WindowRec[] {
  const date = new Date(dateStr || new Date().toISOString().split("T")[0]);
  const startMin = Math.max(0, startHour * 60);
  const endMin = Math.min(24 * 60, endHour * 60);
  const results: (WindowRec & { score: number })[] = [];

  for (let s = startMin; s + durationMinutes <= endMin; s += 30) {
    const e = s + durationMinutes;
    const mid = Math.floor((s + e) / 2);
    const sp = calculateSunPosition(date, Math.floor(mid / 60), mid % 60);
    const uv = calculateUV(date, mid);
    const uvCat = getUVCategory(uv);
    const shadePct = sp.altitude <= 0 ? 96 : Math.max(8, Math.round(100 - (sp.altitude / 90) * 84));
    const score = shadePct - uv * 8;
    const quality = recQuality(shadePct);
    results.push({
      id: `${s}-${e}`,
      title: qualityTitle(quality),
      start: s,
      end: e,
      timeLabel: `${formatTime(s)} – ${formatTime(e)}`,
      uv,
      uvCat,
      shadePct,
      quality,
      score,
    });
  }

  return results.sort((a, b) => b.score - a.score).slice(0, 5);
}

export default function MapPage() {
  const location = useLocation();
  const { mode, setMode } = useMode();
  const { minutes: initMinutes, dateStr: initDate } = getDubaiNow();

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: AlertTriangle },
    { path: "/map", label: mode === "commercial" ? "Task Map" : "Route Map", icon: Map },
    { path: "/tasks", label: mode === "commercial" ? "Tasks" : "Saved Routes", icon: mode === "commercial" ? CheckSquare : Navigation },
    { path: "/settings", label: "Settings", icon: Settings },
  ];

  // time state
  const [currentMinutes, setCurrentMinutes] = useState(initMinutes);
  const [dateStr, setDateStr] = useState(initDate);
  const [isPlaying, setIsPlaying] = useState(false);
  const [animSpeed, setAnimSpeed] = useState(500);
  const animRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // sun state
  const [sunPos, setSunPos] = useState<SunPosition | null>(null);
  useEffect(() => {
    const d = dateStr ? new Date(dateStr) : new Date();
    setSunPos(calculateSunPosition(d, Math.floor(currentMinutes / 60), currentMinutes % 60));
  }, [currentMinutes, dateStr]);

  useEffect(() => {
    if (isPlaying) {
      animRef.current = setInterval(() => {
        setCurrentMinutes((p) => (p + 5) % 1440);
      }, animSpeed);
    } else if (animRef.current) {
      clearInterval(animRef.current);
    }
    return () => {
      if (animRef.current) clearInterval(animRef.current);
    };
  }, [isPlaying, animSpeed]);

  // flyTo
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

  // Mapbox Searchbox API
  const [locationSearch, setLocationSearch] = useState("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [searchSessionToken, setSearchSessionToken] = useState(() => {
    try {
      return crypto.randomUUID();
    } catch {
      return String(Date.now());
    }
  });
  const geoTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchInput = (val: string) => {
    setLocationSearch(val);
    if (geoTimeoutRef.current) clearTimeout(geoTimeoutRef.current);
    if (val.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    geoTimeoutRef.current = setTimeout(async () => {
      try {
        const url = `https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(
          val,
        )}&language=en&country=AE&limit=6&proximity=55.2708,25.2048&access_token=${MAPBOX_TOKEN}&session_token=${searchSessionToken}`;
        const res = await fetch(url);
        const data = await res.json();
        setSuggestions(data.suggestions || []);
      } catch {
        setSuggestions([]);
      }
    }, 250);
  };

  // commercial site flow
  const [isSitePopupOpen, setIsSitePopupOpen] = useState(false);
  const [isSelectingSite, setIsSelectingSite] = useState(false);
  const [commercialSite, setCommercialSite] = useState<{ lat: number; lng: number } | null>(null);
  const [savedRecIds, setSavedRecIds] = useState<Set<string>>(new Set());
  const [siteDraft, setSiteDraft] = useState<SiteDraft>({
    taskName: "Facade Work",
    locationLabel: "",
    durationMinutes: 120,
    startHour: 5,
    endHour: 20,
  });
  const [analysisConfirmed, setAnalysisConfirmed] = useState(false);
  const [siteRecommendations, setSiteRecommendations] = useState<WindowRec[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [buildingFace, setBuildingFace] = useState<string>("");

  // routing (personal mode only)
  const [routeFrom, setRouteFrom] = useState("");
  const [routeTo, setRouteTo] = useState("");
  const [travelMode, setTravelMode] = useState<"walking" | "cycling">("walking");
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeResult, setRouteResult] = useState<RouteResult | null>(null);
  const [routeToDraw, setRouteToDraw] = useState<RouteToDraw | null>(null);
  const [clearRouteKey, setClearRouteKey] = useState(0);
  const routeKeyRef = useRef(0);
  const clearKeyRef = useRef(0);
  const [fromCoords, setFromCoords] = useState<[number, number] | null>(null);
  const [toCoords, setToCoords] = useState<[number, number] | null>(null);
  const [selectingPoint, setSelectingPoint] = useState<"from" | "to" | null>(null);

  const handlePointSelected = useCallback(
    (lat: number, lng: number, which: "from" | "to") => {
      if (mode === "commercial" && isSelectingSite) {
        setCommercialSite({ lat, lng });
        setSiteDraft((prev) => ({ ...prev, locationLabel: `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E` }));
        setIsSelectingSite(false);
        flyToCoords([lng, lat], 16);
        return;
      }

      const label = `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
      if (which === "from") {
        setFromCoords([lng, lat]);
        setRouteFrom(label);
      } else {
        setToCoords([lng, lat]);
        setRouteTo(label);
      }
      setSelectingPoint(null);
    },
    [mode, isSelectingSite, flyToCoords],
  );

  const selectSuggestion = async (s: SearchSuggestion) => {
    try {
      const res = await fetch(
        `https://api.mapbox.com/search/searchbox/v1/retrieve/${s.mapbox_id}?access_token=${MAPBOX_TOKEN}&session_token=${searchSessionToken}`,
      );
      const data = await res.json();
      const feature = data.features?.[0];
      const center = feature?.geometry?.coordinates as [number, number] | undefined;
      const label = s.full_address || s.place_formatted || s.name;
      if (center) {
        setLocationSearch(label || "");
        setSuggestions([]);
        flyToCoords(center, 16);
        if (mode === "commercial") {
          setCommercialSite({ lat: center[1], lng: center[0] });
          setSiteDraft((prev) => ({ ...prev, locationLabel: label || `${center[1].toFixed(4)}°N, ${center[0].toFixed(4)}°E` }));
        }
      }
      try {
        setSearchSessionToken(crypto.randomUUID());
      } catch {
        setSearchSessionToken(String(Date.now()));
      }
    } catch {}
  };

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
      alert("Click the pin button next to From/To, then click on map.");
      return;
    }
    setRouteLoading(true);
    try {
      const date = dateStr || new Date().toISOString().split("T")[0];
      const time = formatTime(currentMinutes);
      const payload = {
        start: { lat: fromCoords[1], lon: fromCoords[0] },
        end: { lat: toCoords[1], lon: toCoords[0] },
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
      const data = await res.json();
      if (!res.ok || !data?.success) throw new Error(data?.error || "Route failed");

      const rec = data.recommendation;
      const route = rec?.recommended_route || data;
      const score = rec ? Math.round((route.comfort_score || 0) * 100) : Math.round(data.shade_score || 0);
      const heatRiskPct = rec ? (((route.risk_distribution?.high || 0) + 0.5 * (route.risk_distribution?.medium || 0)) * 100) : (data.average_heat_risk || 0);
      const riskLevel = heatRiskPct <= 30 ? "LOW" : heatRiskPct <= 60 ? "MEDIUM" : "HIGH";
      const riskColor = riskLevel === "LOW" ? "#22c55e" : riskLevel === "MEDIUM" ? "#f59e0b" : "#ef4444";
      const distanceKm = ((route.distance_meters || data.total_distance || 0) / 1000).toFixed(1);
      const durationMin = Math.round((route.duration_seconds || data.total_duration || 0) / 60);
      const shadePct = Math.round(route.shade_coverage_percent || data.average_shade_coverage || 0);
      const sunExposure = Math.round(route.sun_exposure_minutes || data.sun_exposure_minutes || 0);
      setRouteResult({ distanceKm, durationMin, shadePct, score, riskLevel, riskColor, sunExposure, reason: rec?.recommendation_reason });

      const coords: [number, number][] = route.geometry?.coordinates || data.geometry || [];
      if (coords.length >= 2) {
        routeKeyRef.current += 1;
        setRouteToDraw({ coordinates: coords, travelMode: rec?.travel_mode || travelMode, key: routeKeyRef.current });
      }
    } catch (err) {
      alert(`Route error: ${(err as Error).message}`);
    }
    setRouteLoading(false);
  };

  const useGPSForFrom = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      const { latitude, longitude } = pos.coords;
      setFromCoords([longitude, latitude]);
      setRouteFrom(`${latitude.toFixed(4)}°N, ${longitude.toFixed(4)}°E`);
      flyToCoords([longitude, latitude]);
    });
  };

  const openSitePopup = () => {
    setIsSitePopupOpen(true);
    setAnalysisConfirmed(false);
    setSiteRecommendations([]);
  };

  const submitSiteAnalysis = async () => {
    if (!commercialSite) {
      toast.error("Please choose a site on the map or from search before generating recommendations.");
      return;
    }
    if (siteDraft.endHour <= siteDraft.startHour) {
      toast.error("End hour must be after start hour.");
      return;
    }
    
    setScheduleLoading(true);
    setIsSitePopupOpen(false);
    
    try {
      const recommendations = await fetchScheduleFromBackend(
        siteDraft.taskName,
        commercialSite.lat,
        commercialSite.lng,
        dateStr,
        siteDraft.durationMinutes,
        siteDraft.startHour,
        siteDraft.endHour,
        buildingFace || undefined
      );
      setSiteRecommendations(recommendations);
      setAnalysisConfirmed(true);
      
      if (recommendations.length > 0) {
        toast.success(`Found ${recommendations.length} optimal time windows based on shadow coverage.`);
      }
    } catch (err) {
      toast.error("Failed to fetch recommendations. Using local calculation.");
      const fallback = computeWindowsFallback(dateStr, siteDraft.durationMinutes, siteDraft.startHour, siteDraft.endHour);
      setSiteRecommendations(fallback);
      setAnalysisConfirmed(true);
    }
    
    setScheduleLoading(false);
  };

  const saveRecommendation = async (rec: WindowRec) => {
    const id = `${siteDraft.taskName}-${rec.id}`;
    
    try {
      // Create task in backend
      const taskRes = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: id,
          task_name: siteDraft.taskName,
          location_name: siteDraft.locationLabel,
          location_lat: commercialSite?.lat || 25.2048,
          location_lon: commercialSite?.lng || 55.2708,
          duration_minutes: siteDraft.durationMinutes,
          hour_start: Math.floor(rec.start / 60),
          hour_end: Math.ceil(rec.end / 60),
          date: dateStr,
          status: "draft"
        })
      });
      
      if (!taskRes.ok) throw new Error("Failed to create task");
      const taskData = await taskRes.json();
      
      // Accept the recommendation
      await fetch(`${API_BASE}/api/tasks/${taskData.task_id}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accepted_time_start: formatTime(rec.start).split(" ")[0],
          accepted_time_end: formatTime(rec.end).split(" ")[0],
          shade_percentage: rec.shadePct,
          shade_slot: rec.title
        })
      });
      
      setSavedRecIds((prev) => new Set(prev).add(id));
      
      // Also save to localStorage for backward compatibility
      const existing = JSON.parse(localStorage.getItem("smartshift_saved_recommendations") || "[]");
      const payload = {
        id,
        task_name: siteDraft.taskName,
        location: siteDraft.locationLabel,
        duration_minutes: siteDraft.durationMinutes,
        date: dateStr,
        best_window: rec.timeLabel,
        shade_pct: rec.shadePct,
        uv: Number(rec.uv.toFixed(1)),
        quality: rec.quality,
        status: "scheduled",
        created_at: new Date().toISOString(),
      };
      localStorage.setItem("smartshift_saved_recommendations", JSON.stringify([payload, ...existing]));
      
      toast.success("Task added to Tasks page!", {
        description: `${siteDraft.taskName} scheduled for ${rec.timeLabel}`,
        action: {
          label: "View Tasks",
          onClick: () => window.location.href = "/tasks",
        },
      });
    } catch (err) {
      console.error("Save error:", err);
      // Fallback to localStorage only
      setSavedRecIds((prev) => new Set(prev).add(id));
      const existing = JSON.parse(localStorage.getItem("smartshift_saved_recommendations") || "[]");
      const payload = {
        id,
        task_name: siteDraft.taskName,
        location: siteDraft.locationLabel,
        duration_minutes: siteDraft.durationMinutes,
        date: dateStr,
        best_window: rec.timeLabel,
        shade_pct: rec.shadePct,
        uv: Number(rec.uv.toFixed(1)),
        quality: rec.quality,
        status: "scheduled",
        created_at: new Date().toISOString(),
      };
      localStorage.setItem("smartshift_saved_recommendations", JSON.stringify([payload, ...existing]));
      toast.success("Task saved locally (backend unavailable)", {
        description: "View in Tasks page",
      });
    }
  };
  
  const playAnimationForRec = (rec: WindowRec) => {
    setCurrentMinutes(rec.start);
    setIsPlaying(true);
    toast.info(`Playing shadow animation for ${rec.timeLabel}`);
  };

  const uv = calculateUV(dateStr ? new Date(dateStr) : new Date(), currentMinutes);
  const uvCat = getUVCategory(uv);
  const period = sunPos ? getTimePeriod(sunPos.altitude, sunPos.azimuth) : "—";
  const timeOptions = Array.from({ length: 49 }, (_, i) => i * 30);

  return (
    <div className="flex flex-col h-screen bg-background">
      <header className="border-b border-border bg-card sticky top-0 z-50 shadow-sm shrink-0">
        <div className="max-w-full px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary to-amber-400 rounded-lg flex items-center justify-center shadow-md">
                <Sun className="w-6 h-6 text-primary-foreground" />
              </div>
              <span className="text-xl font-bold text-foreground hidden sm:block">SmartShift</span>
            </Link>

            <div className="hidden sm:flex items-center gap-2 bg-muted rounded-lg p-1">
              <button onClick={() => setMode("commercial")} className={cn("px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5", mode === "commercial" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                <Briefcase className="w-4 h-4" /><span className="hidden lg:inline">Commercial</span>
              </button>
              <button onClick={() => setMode("personal")} className={cn("px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5", mode === "personal" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                <Navigation className="w-4 h-4" /><span className="hidden lg:inline">Personal</span>
              </button>
            </div>

            <nav className="flex items-center gap-1">
              {navItems.map(({ path, label, icon: Icon }) => (
                <Link key={path} to={path} className={cn("flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200", location.pathname === path ? "bg-primary text-primary-foreground" : "text-foreground hover:bg-muted")}>
                  <Icon className="w-5 h-5" />
                  <span className="hidden sm:inline text-sm font-medium">{label}</span>
                </Link>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        <div className="flex-1 relative min-h-0">
          <MapboxMap
            currentMinutes={currentMinutes}
            dateStr={dateStr}
            flyTo={flyToTarget}
            routeToDraw={routeToDraw}
            clearRouteKey={clearRouteKey}
            selectingPoint={mode === "commercial" && isSelectingSite ? "from" : selectingPoint}
            onPointSelected={handlePointSelected}
            fromMarker={mode === "commercial" ? (commercialSite ? [commercialSite.lng, commercialSite.lat] : null) : fromCoords}
            toMarker={mode === "personal" ? toCoords : null}
          />

          {/* Floating transparent time card */}
          <div className="absolute top-4 left-4 z-20 w-[310px] rounded-2xl border border-white/20 bg-background/45 backdrop-blur-xl shadow-2xl p-3">
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-xl font-bold font-mono text-foreground">{formatTime(currentMinutes)}</span>
              <span className="text-xs text-primary font-medium">{period}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1440}
              step={5}
              value={currentMinutes}
              onInput={(e) => setCurrentMinutes(Number((e.target as HTMLInputElement).value))}
              onChange={(e) => setCurrentMinutes(Number(e.target.value))}
              className="w-full accent-primary h-2 cursor-pointer"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground mb-2">
              {["12A", "6A", "12P", "6P", "12A"].map((t) => <span key={t}>{t}</span>)}
            </div>
            <div className="grid grid-cols-[1fr_1fr_auto_auto] gap-1.5 items-center">
              <select value={Math.round(currentMinutes / 30) * 30} onChange={(e) => setCurrentMinutes(Number(e.target.value))} className="px-2 py-1.5 rounded-lg border border-border/60 bg-background/50 text-xs">
                {timeOptions.map((m) => <option key={m} value={m}>{formatTime(m)}</option>)}
              </select>
              <input type="date" value={dateStr} onChange={(e) => setDateStr(e.target.value)} className="px-2 py-1.5 rounded-lg border border-border/60 bg-background/50 text-xs" />
              <button onClick={() => setIsPlaying((p) => !p)} className={cn("rounded-lg px-2 py-1.5 text-xs font-medium", isPlaying ? "bg-amber-500 text-white" : "bg-primary text-primary-foreground")}>
                {isPlaying ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
              </button>
              <button onClick={() => { setIsPlaying(false); setCurrentMinutes(720); }} className="rounded-lg px-2 py-1.5 text-xs border border-border/60 bg-background/50">
                <RotateCcw className="w-3 h-3" />
              </button>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <span className="text-[10px] text-muted-foreground">Speed</span>
              <input type="range" min={100} max={2000} step={100} value={2100 - animSpeed} onChange={(e) => setAnimSpeed(2100 - Number(e.target.value))} className="flex-1 accent-primary h-1.5" />
              <span className="text-[10px] text-muted-foreground font-mono">{(1000 / animSpeed).toFixed(1)}x</span>
            </div>
          </div>
        </div>

        {/* Translucent right panel */}
        <div className="w-80 shrink-0 border-l border-border/40 bg-background/70 backdrop-blur-xl overflow-y-auto flex flex-col">
          <div className="px-4 py-3 border-b border-border/40">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
              <input value={locationSearch} onChange={(e) => handleSearchInput(e.target.value)} placeholder={mode === "commercial" ? "Search work site..." : "Search location..."} className="w-full pl-9 pr-3 py-2 rounded-xl border border-border/60 bg-background/60 text-sm" />
              {suggestions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-card/95 border border-border rounded-xl shadow-xl z-50 max-h-56 overflow-y-auto">
                  {suggestions.map((s) => (
                    <button key={s.mapbox_id} onClick={() => selectSuggestion(s)} className="w-full text-left px-3 py-2 text-sm hover:bg-muted/60 border-b border-border/40 last:border-0">
                      <div className="font-medium">{s.name}</div>
                      <div className="text-xs text-muted-foreground">{s.full_address || s.place_formatted}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="px-4 py-2.5 border-b border-border/40">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">Quick Places</p>
            <div className="flex flex-wrap gap-1.5">
              {SAVED_PLACES.map(({ key, label }) => (
                <button key={key} onClick={() => flyTo(key)} className="flex items-center gap-1 rounded-full border border-border/60 bg-background/60 px-2.5 py-1 text-xs font-medium hover:bg-primary/10 hover:border-primary/30">
                  {label}
                </button>
              ))}
            </div>
          </div>

          {mode === "commercial" ? (
            <div className="px-4 py-3 border-b border-border/40 flex-1">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Site Analysis</h2>
                <button onClick={openSitePopup} className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium border border-primary/25 bg-primary/10 text-primary hover:bg-primary/15">
                  <Plus className="w-3 h-3" /> New
                </button>
              </div>

              {scheduleLoading && (
                <div className="rounded-2xl border border-primary/20 bg-primary/5 px-4 py-6 text-center">
                  <Loader2 className="w-6 h-6 text-primary animate-spin mx-auto mb-2" />
                  <p className="text-sm font-medium text-foreground">Analyzing shadow patterns...</p>
                  <p className="text-xs text-muted-foreground">Finding optimal times based on shadow exposure</p>
                </div>
              )}
              
              {!analysisConfirmed && !scheduleLoading && (
                <div className="rounded-2xl border border-dashed border-border/60 bg-muted/20 px-4 py-6 text-center">
                  <p className="text-sm font-medium text-foreground mb-1">Create site analysis</p>
                  <p className="text-xs text-muted-foreground">Enter task details in popup and choose site on map.</p>
                </div>
              )}

              {analysisConfirmed && !scheduleLoading && (
                <div className="space-y-2">
                  <div className="rounded-xl border border-primary/20 bg-primary/10 px-3 py-2">
                    <div className="text-xs font-semibold text-foreground">{siteDraft.taskName}</div>
                    <div className="text-[11px] text-muted-foreground truncate">{siteDraft.locationLabel}</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {siteDraft.durationMinutes} min · {siteDraft.startHour}:00–{siteDraft.endHour}:00
                      {buildingFace && <span className="ml-1 text-primary">· {buildingFace} Face</span>}
                    </div>
                  </div>

                  {siteRecommendations.map((rec, idx) => {
                    const recId = `${siteDraft.taskName}-${rec.id}`;
                    const saved = savedRecIds.has(recId);
                    return (
                      <div 
                        key={rec.id} 
                        className="rounded-xl border border-border/60 bg-background/55 p-3 cursor-pointer hover:border-primary/40 transition-colors"
                        onClick={() => playAnimationForRec(rec)}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className={cn(
                                "text-sm font-semibold",
                                idx === 0 ? "text-green-600" : "text-foreground"
                              )}>
                                {idx === 0 ? "🏆 " : ""}{rec.title}
                              </span>
                            </div>
                            <div className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5">
                              <Clock className="w-3 h-3" /> {rec.timeLabel}
                              <span className="ml-1 text-primary/60">(click to preview)</span>
                            </div>
                            <div className="text-[11px] mt-1 flex items-center gap-2">
                              <span className="text-green-600 font-medium">{rec.shadePct}% shade</span>
                              <span style={{ color: rec.uvCat.color }}>UV {rec.uv.toFixed(1)}</span>
                            </div>
                            {rec.reason && idx === 0 && (
                              <p className="text-[10px] text-muted-foreground mt-1 italic">{rec.reason}</p>
                            )}
                          </div>
                          <button 
                            onClick={(e) => { e.stopPropagation(); saveRecommendation(rec); }} 
                            className={cn(
                              "rounded-lg px-2 py-1 text-[11px] font-medium border", 
                              saved 
                                ? "bg-green-500/15 border-green-500/30 text-green-600" 
                                : "border-border/60 bg-background/60 hover:bg-primary/10 hover:border-primary/30 text-muted-foreground hover:text-primary"
                            )}
                          >
                            {saved ? "✓ Saved" : "Save"}
                          </button>
                        </div>
                      </div>
                    );
                  })}

                  {savedRecIds.size > 0 && (
                    <div className="rounded-xl border border-green-500/20 bg-green-500/5 px-3 py-2 flex items-center gap-2">
                      <CheckCircle className="w-3.5 h-3.5 text-green-600 shrink-0" />
                      <p className="text-xs text-muted-foreground">
                        {savedRecIds.size} task{savedRecIds.size > 1 ? "s" : ""} added. <Link to="/tasks" className="text-primary underline font-medium">View Tasks →</Link>
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="px-4 py-3 border-b border-border/40">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">Shade-Optimized Route</h2>
              <div className="space-y-2 mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500 shrink-0" />
                  <div className="flex-1 flex gap-1.5">
                    <input type="text" value={routeFrom} readOnly placeholder="From — click pin then map" className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-border/60 bg-background/60 text-xs" />
                    <button onClick={() => setSelectingPoint(selectingPoint === "from" ? null : "from")} className={cn("px-2 py-1.5 rounded-lg border text-sm", selectingPoint === "from" ? "bg-amber-100 border-amber-400 text-amber-700" : "bg-background/60 border-border/60 text-muted-foreground")}>📍</button>
                    <button onClick={useGPSForFrom} className="px-2 py-1.5 rounded-lg border border-border/60 bg-background/60 text-sm">📡</button>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-blue-500 shrink-0" />
                  <div className="flex-1 flex gap-1.5">
                    <input type="text" value={routeTo} readOnly placeholder="To — click pin then map" className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-border/60 bg-background/60 text-xs" />
                    <button onClick={() => setSelectingPoint(selectingPoint === "to" ? null : "to")} className={cn("px-2 py-1.5 rounded-lg border text-sm", selectingPoint === "to" ? "bg-amber-100 border-amber-400 text-amber-700" : "bg-background/60 border-border/60 text-muted-foreground")}>📍</button>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                {(["walking", "cycling"] as const).map((m) => (
                  <button key={m} onClick={() => setTravelMode(m)} className={cn("py-1.5 rounded-lg border text-sm font-medium", travelMode === m ? "bg-primary text-primary-foreground border-primary" : "bg-background/60 border-border/60")}>
                    {m === "walking" ? "🚶 Walk" : "🚴 Cycle"}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <button onClick={findRoute} disabled={routeLoading} className="py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50">
                  {routeLoading ? "Finding…" : "Find Route"}
                </button>
                <button onClick={clearRoute} className="py-2 rounded-lg border border-border/60 bg-background/60 text-sm font-medium flex items-center justify-center gap-1">
                  <RotateCcw className="w-3.5 h-3.5" /> Clear
                </button>
              </div>
              {routeResult && (
                <div className="mt-3 p-3 rounded-xl bg-blue-50/70 border border-blue-200/60">
                  <div className="text-xs font-semibold text-blue-700 mb-1">Route Found · {routeResult.score}/100</div>
                  <div className="text-xs text-muted-foreground">{routeResult.distanceKm} km · {routeResult.durationMin} min · {routeResult.shadePct}% shade</div>
                </div>
              )}
            </div>
          )}

          {/* less-important sun metrics back on right panel bottom */}
          <div className="px-4 py-3 mt-auto">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2">Sun Metrics</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "Azimuth", value: sunPos ? `${sunPos.azimuth.toFixed(1)}°` : "--" },
                { label: "Altitude", value: sunPos ? `${sunPos.altitude.toFixed(1)}°` : "--" },
                { label: "Sunrise", value: sunPos?.sunrise ?? "--" },
                { label: "Sunset", value: sunPos?.sunset ?? "--" },
              ].map((x) => (
                <div key={x.label} className="rounded-xl border border-border/60 bg-background/55 p-2">
                  <div className="text-[10px] text-muted-foreground">{x.label}</div>
                  <div className="text-sm font-bold text-foreground">{x.value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Site Analysis popup */}
      {mode === "commercial" && isSitePopupOpen && (
        <div className="fixed inset-0 z-[100] bg-black/45 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-xl rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">
            <div className="px-5 py-4 border-b border-border flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold text-foreground">New Site Analysis</h3>
                <p className="text-xs text-muted-foreground">Enter task details, pick exact site on map, generate schedules.</p>
              </div>
              <button onClick={() => setIsSitePopupOpen(false)} className="rounded-lg p-1.5 hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Task Name</label>
                <input value={siteDraft.taskName} onChange={(e) => setSiteDraft((p) => ({ ...p, taskName: e.target.value }))} className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Location</label>
                <div className="flex gap-2">
                  <input value={siteDraft.locationLabel} onChange={(e) => setSiteDraft((p) => ({ ...p, locationLabel: e.target.value }))} placeholder="Search above or pick on map" className="flex-1 px-3 py-2 rounded-lg border border-border bg-background" />
                  <button onClick={() => { setIsSelectingSite(true); setIsSitePopupOpen(false); }} className="px-3 py-2 rounded-lg border border-primary/25 bg-primary/10 text-primary text-sm font-medium">
                    Pick on map
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Duration (min)</label>
                  <input type="number" min={15} step={15} value={siteDraft.durationMinutes} onChange={(e) => setSiteDraft((p) => ({ ...p, durationMinutes: Number(e.target.value) }))} className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">From Hour</label>
                  <input type="number" min={0} max={23} value={siteDraft.startHour} onChange={(e) => setSiteDraft((p) => ({ ...p, startHour: Number(e.target.value) }))} className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">To Hour</label>
                  <input type="number" min={1} max={24} value={siteDraft.endHour} onChange={(e) => setSiteDraft((p) => ({ ...p, endHour: Number(e.target.value) }))} className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
              </div>
              
              <div>
                <label className="block text-sm font-medium mb-1">Building Face (optional)</label>
                <p className="text-xs text-muted-foreground mb-2">Select if working on a specific building facade</p>
                <div className="flex gap-2">
                  {["", "N", "E", "S", "W"].map((face) => (
                    <button
                      key={face || "none"}
                      type="button"
                      onClick={() => setBuildingFace(face)}
                      className={cn(
                        "flex-1 py-2 rounded-lg border text-sm font-medium transition-all",
                        buildingFace === face
                          ? "bg-primary text-primary-foreground border-primary"
                          : "border-border bg-background hover:bg-muted"
                      )}
                    >
                      {face || "Any"}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="px-5 py-4 border-t border-border flex justify-end gap-2">
              <button onClick={() => setIsSitePopupOpen(false)} className="px-4 py-2 rounded-lg border border-border">Cancel</button>
              <button onClick={submitSiteAnalysis} className="px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-amber-500 text-primary-foreground font-medium">
                Generate Recommendations
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
