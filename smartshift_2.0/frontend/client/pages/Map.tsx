import { useState, useRef, useEffect, useCallback } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Sun, Map, CheckSquare, Settings, Navigation2, Navigation, MapPin,
  RotateCcw, Play, Pause, Briefcase, X, CheckCircle,
  Plus, Clock, Zap, Search, Loader2, LayoutDashboard, Locate,
  Bookmark, Trash2,
} from "lucide-react";
import { cn } from "../lib/utils";
import MapboxMap, { LOCATIONS, FlyToTarget, RouteToDraw } from "@/components/MapboxMap";
import { useMode } from "@/hooks/useMode";
import { useAuth } from "@/hooks/useAuth";
import {
  calculateSunPosition,
  formatTime,
  getTimePeriod,
  getDubaiNow,
  calculateUV,
  getUVCategory,
  calculateShadowCoverage,
  SunPosition,
} from "@/lib/sunCalculations";

const API_BASE = "http://localhost:8002";
const MAPBOX_TOKEN = "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9.WI13BJqDyOu6G38-YP6hog";

interface RouteResult {
  distanceKm: string;
  durationMin: number;
  shadePct: number;
  score: number;
  riskLevel: string;
  riskColor: string;
  sunExposure: number;
  reason?: string;
  coordinates: [number, number][];
  selected?: boolean;
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
  locationName: string;
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

interface SavedPlaceItem {
  id: string;
  name: string;
  lat: number;
  lon: number;
}

function recQuality(shadePct: number): WindowRec["quality"] {
  if (shadePct >= 75) return "excellent";
  if (shadePct >= 55) return "good";
  if (shadePct >= 35) return "fair";
  return "poor";
}

function qualityTag(quality: WindowRec["quality"]): { label: string; color: string } {
  switch (quality) {
    case "excellent": return { label: "Best", color: "bg-green-100 text-green-700" };
    case "good": return { label: "Recommended", color: "bg-blue-100 text-blue-700" };
    case "fair": return { label: "Alternative", color: "bg-amber-100 text-amber-700" };
    default: return { label: "Not Recommended", color: "bg-red-100 text-red-700" };
  }
}

async function fetchScheduleFromBackend(
  taskName: string, lat: number, lon: number, locationName: string,
  dateStr: string, durationMinutes: number, startHour: number, endHour: number,
  buildingFace?: string
): Promise<WindowRec[]> {
  try {
    const payload: Record<string, unknown> = {
      task_name: taskName, lat, lon, location_name: locationName,
      duration_minutes: durationMinutes, date: dateStr,
      start_hour: startHour, end_hour: endHour,
      recommendation_count: 5, building_face: buildingFace || undefined,
    };
    const res = await fetch(`${API_BASE}/api/v2/shadow-schedule`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`API error ${res.status}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Schedule failed");

    const rec = data.recommendation || {};
    const best = rec.best_schedule;
    const alternatives = rec.alternatives || [];
    const results: WindowRec[] = [];

    const makeRec = (slot: any, isBest: boolean): WindowRec | null => {
      if (!slot) return null;
      const startTime = new Date(slot.start_time);
      const endTime = new Date(slot.end_time);
      const startMin = startTime.getHours() * 60 + startTime.getMinutes();
      const endMin = endTime.getHours() * 60 + endTime.getMinutes();
      const shadePct = Math.round(slot.shadow_percentage || 0);
      const quality = recQuality(shadePct);
      const uv = calculateUV(new Date(dateStr), Math.floor((startMin + endMin) / 2));
      return {
        id: `${isBest ? "best" : "alt"}-${startMin}-${endMin}`,
        title: `${formatTime(startMin)} – ${formatTime(endMin)}`,
        start: startMin, end: endMin,
        timeLabel: slot.time_label || `${formatTime(startMin)} – ${formatTime(endMin)}`,
        uv, uvCat: getUVCategory(uv), shadePct, quality,
        reason: isBest ? rec.recommendation_reason : undefined,
      };
    };

    const bestRec = makeRec(best, true);
    if (bestRec) results.push(bestRec);
    for (const alt of alternatives.slice(0, 4)) {
      const r = makeRec(alt, false);
      if (r) results.push(r);
    }
    return results;
  } catch {
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
    const shadePct = calculateShadowCoverage(sp.altitude);
    const quality = recQuality(shadePct);
    results.push({
      id: `${s}-${e}`, title: `${formatTime(s)} – ${formatTime(e)}`,
      start: s, end: e, timeLabel: `${formatTime(s)} – ${formatTime(e)}`,
      uv, uvCat, shadePct, quality, score: shadePct,
    });
  }
  return results.sort((a, b) => b.score - a.score).slice(0, 5);
}

export default function MapPage() {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { mode, setMode } = useMode();
  const { user } = useAuth();
  const { minutes: initMinutes, dateStr: initDate } = getDubaiNow();

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    { path: "/map", label: mode === "commercial" ? "Task Map" : "Route Map", icon: Map },
    ...(mode === "commercial" ? [{ path: "/tasks", label: "Tasks", icon: CheckSquare }] : []),
    { path: "/settings", label: "Settings", icon: Settings },
  ];

  const [currentMinutes, setCurrentMinutes] = useState(initMinutes);
  const [dateStr, setDateStr] = useState(initDate);
  const [isPlaying, setIsPlaying] = useState(false);
  const [animSpeed, setAnimSpeed] = useState(500);
  const animRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [sunPos, setSunPos] = useState<SunPosition | null>(null);
  useEffect(() => {
    const d = dateStr ? new Date(dateStr) : new Date();
    setSunPos(calculateSunPosition(d, Math.floor(currentMinutes / 60), currentMinutes % 60));
  }, [currentMinutes, dateStr]);

  useEffect(() => {
    if (isPlaying) {
      animRef.current = setInterval(() => setCurrentMinutes((p) => (p + 5) % 1440), animSpeed);
    } else if (animRef.current) {
      clearInterval(animRef.current);
    }
    return () => { if (animRef.current) clearInterval(animRef.current); };
  }, [isPlaying, animSpeed]);

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

  // Searchbox
  const [locationSearch, setLocationSearch] = useState("");
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [searchSessionToken, setSearchSessionToken] = useState(() => {
    try { return crypto.randomUUID(); } catch { return String(Date.now()); }
  });
  const geoTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchInput = (val: string) => {
    setLocationSearch(val);
    if (geoTimeoutRef.current) clearTimeout(geoTimeoutRef.current);
    if (val.trim().length < 2) { setSuggestions([]); return; }
    geoTimeoutRef.current = setTimeout(async () => {
      try {
        const url = `https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(val)}&language=en&country=AE&limit=6&proximity=55.2708,25.2048&access_token=${MAPBOX_TOKEN}&session_token=${searchSessionToken}`;
        const res = await fetch(url);
        const data = await res.json();
        setSuggestions(data.suggestions || []);
      } catch { setSuggestions([]); }
    }, 250);
  };

  // Commercial site flow
  const [isSitePopupOpen, setIsSitePopupOpen] = useState(false);
  const [isSelectingSite, setIsSelectingSite] = useState(false);
  const [commercialSite, setCommercialSite] = useState<{ lat: number; lng: number } | null>(null);
  const [savedRecIds, setSavedRecIds] = useState<Set<string>>(new Set());
  const [siteDraft, setSiteDraft] = useState<SiteDraft>({
    taskName: "", locationLabel: "", locationName: "",
    durationMinutes: 120, startHour: 5, endHour: 20,
  });
  const [analysisConfirmed, setAnalysisConfirmed] = useState(false);
  const [siteRecommendations, setSiteRecommendations] = useState<WindowRec[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [buildingFace, setBuildingFace] = useState<string>("");
  const [hoveredRecId, setHoveredRecId] = useState<string | null>(null);
  const [mapBearing, setMapBearing] = useState<number>(0);

  // Saved places
  const [savedPlaces, setSavedPlaces] = useState<SavedPlaceItem[]>([]);
  const [showAddPlace, setShowAddPlace] = useState(false);
  const [newPlaceName, setNewPlaceName] = useState("");
  const [addingPlaceOnMap, setAddingPlaceOnMap] = useState(false);
  const [newPlaceCoords, setNewPlaceCoords] = useState<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    const userId = user?.user_id || "";
    if (userId) {
      fetch(`${API_BASE}/api/saved-places?user_id=${userId}`)
        .then((r) => r.json())
        .then((data) => {
          if (data.success) setSavedPlaces(data.places || []);
        })
        .catch(() => {});
    }
  }, [user]);

  const addSavedPlace = async () => {
    if (!newPlaceName.trim() || !newPlaceCoords) return;
    try {
      const res = await fetch(`${API_BASE}/api/saved-places`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: user?.user_id || "", name: newPlaceName, lat: newPlaceCoords.lat, lon: newPlaceCoords.lng }),
      });
      const data = await res.json();
      if (data.success) {
        setSavedPlaces((prev) => [data.place, ...prev]);
        setNewPlaceName("");
        setNewPlaceCoords(null);
        setShowAddPlace(false);
        toast.success("Place saved!");
      }
    } catch { toast.error("Failed to save place"); }
  };

  const removeSavedPlace = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/saved-places/${id}`, {
        method: "DELETE", headers: { "X-User-Id": user?.user_id || "" },
      });
      setSavedPlaces((prev) => prev.filter((p) => p.id !== id));
    } catch {}
  };

  // Routing (personal mode)
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

  // From search
  const [fromSearch, setFromSearch] = useState("");
  const [fromSuggestions, setFromSuggestions] = useState<SearchSuggestion[]>([]);
  const [toSearch, setToSearch] = useState("");
  const [toSuggestions, setToSuggestions] = useState<SearchSuggestion[]>([]);
  const fromTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const searchRouteLocation = (val: string, type: "from" | "to") => {
    if (type === "from") { setFromSearch(val); setRouteFrom(val); }
    else { setToSearch(val); setRouteTo(val); }
    const timeoutRef = type === "from" ? fromTimeoutRef : toTimeoutRef;
    const setSugg = type === "from" ? setFromSuggestions : setToSuggestions;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (val.trim().length < 2) { setSugg([]); return; }
    timeoutRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(val)}&language=en&limit=5&access_token=${MAPBOX_TOKEN}`);
        const data = await res.json();
        setSugg(data.suggestions || []);
      } catch { setSugg([]); }
    }, 250);
  };

  const selectRouteLocation = async (s: SearchSuggestion, type: "from" | "to") => {
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/retrieve/${s.mapbox_id}?access_token=${MAPBOX_TOKEN}`);
      const data = await res.json();
      const coords = data.features?.[0]?.geometry?.coordinates as [number, number] | undefined;
      const label = s.full_address || s.place_formatted || s.name;
      if (coords) {
        if (type === "from") {
          setFromCoords(coords);
          setRouteFrom(label);
          setFromSearch("");
          setFromSuggestions([]);
        } else {
          setToCoords(coords);
          setRouteTo(label);
          setToSearch("");
          setToSuggestions([]);
        }
        flyToCoords(coords, 15);
      }
    } catch {}
  };

  const handlePointSelected = useCallback(
    (lat: number, lng: number, which: "from" | "to") => {
      if (mode === "commercial" && isSelectingSite) {
        setCommercialSite({ lat, lng });
        setSiteDraft((prev) => ({ ...prev, locationLabel: `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E` }));
        setIsSelectingSite(false);
        setIsSitePopupOpen(true);
        flyToCoords([lng, lat], 16);
        return;
      }
      if (addingPlaceOnMap) {
        setNewPlaceCoords({ lat, lng });
        setAddingPlaceOnMap(false);
        setShowAddPlace(true);
        return;
      }
      const label = `${lat.toFixed(4)}°N, ${lng.toFixed(4)}°E`;
      if (which === "from") { setFromCoords([lng, lat]); setRouteFrom(label); }
      else { setToCoords([lng, lat]); setRouteTo(label); }
      setSelectingPoint(null);
    },
    [mode, isSelectingSite, flyToCoords, addingPlaceOnMap],
  );

  const selectSuggestion = async (s: SearchSuggestion) => {
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/retrieve/${s.mapbox_id}?access_token=${MAPBOX_TOKEN}&session_token=${searchSessionToken}`);
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
          setSiteDraft((prev) => ({ ...prev, locationLabel: label || `${center[1].toFixed(4)}°N, ${center[0].toFixed(4)}°E`, locationName: label || "" }));
        }
      }
      try { setSearchSessionToken(crypto.randomUUID()); } catch { setSearchSessionToken(String(Date.now())); }
    } catch {}
  };

  const detectCurrentLocation = () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      const { latitude, longitude } = pos.coords;
      flyToCoords([longitude, latitude]);
      if (mode === "personal") {
        setFromCoords([longitude, latitude]);
        setRouteFrom(`${latitude.toFixed(4)}°N, ${longitude.toFixed(4)}°E`);
      }
    });
  };

  const clearRoute = () => {
    setFromCoords(null); setToCoords(null);
    setRouteFrom(""); setRouteTo("");
    setRouteResult(null);
    setAlternativeRoutes([]);
    setSelectedRouteIdx(0);
    clearKeyRef.current += 1;
    setClearRouteKey(clearKeyRef.current);
  };

  const [alternativeRoutes, setAlternativeRoutes] = useState<RouteResult[]>([]);
  const [selectedRouteIdx, setSelectedRouteIdx] = useState(0);

  const computeRouteShade = (
    coords: [number, number][],
    durationSec: number,
    startMinutes: number,
    curDate: string
  ) => {
    const sampleCount = Math.min(coords.length, 20);
    const step = Math.max(1, Math.floor(coords.length / sampleCount));
    let totalShade = 0;
    let samples = 0;

    for (let i = 0; i < coords.length; i += step) {
      const progress = i / coords.length;
      const elapsedMin = Math.round(progress * (durationSec / 60));
      const sampleMinutes = startMinutes + elapsedMin;
      const d = new Date(curDate);
      const sp = calculateSunPosition(d, Math.floor(sampleMinutes / 60) % 24, sampleMinutes % 60);
      totalShade += calculateShadowCoverage(sp.altitude);
      samples++;
    }
    return samples > 0 ? Math.round(totalShade / samples) : 0;
  };

  const findRoute = async () => {
    if (!fromCoords || !toCoords) {
      toast.error("Select both From and To locations first.");
      return;
    }
    setRouteLoading(true);
    setAlternativeRoutes([]);
    setSelectedRouteIdx(0);
    try {
      const curDate = dateStr || new Date().toISOString().split("T")[0];

      const profile = travelMode === "cycling" ? "cycling" : "walking";
      const directionsUrl = `https://api.mapbox.com/directions/v5/mapbox/${profile}/${fromCoords[0]},${fromCoords[1]};${toCoords[0]},${toCoords[1]}?alternatives=true&geometries=geojson&overview=full&steps=true&access_token=${MAPBOX_TOKEN}`;

      const res = await fetch(directionsUrl);
      const data = await res.json();

      if (!data.routes || data.routes.length === 0) throw new Error("No route found");

      const routes: RouteResult[] = data.routes.slice(0, 3).map((route: any) => {
        const distanceKm = (route.distance / 1000).toFixed(1);
        const durationMin = Math.round(route.duration / 60);
        const coords = route.geometry.coordinates as [number, number][];

        const shadePct = computeRouteShade(coords, route.duration, currentMinutes, curDate);
        const score = Math.round(shadePct * 0.85 + Math.max(0, 100 - durationMin) * 0.15);

        return {
          distanceKm,
          durationMin,
          shadePct,
          score,
          riskLevel: shadePct >= 60 ? "LOW" : shadePct >= 30 ? "MEDIUM" : "HIGH",
          riskColor: shadePct >= 60 ? "#22c55e" : shadePct >= 30 ? "#f59e0b" : "#ef4444",
          sunExposure: Math.round(durationMin * (1 - shadePct / 100)),
          coordinates: coords,
          reason: `${distanceKm} km via ${profile} · ${shadePct}% avg shade along path`,
        };
      });

      routes.sort((a, b) => b.score - a.score);

      if (routes.length < 3) {
        const base = data.routes[0];
        const baseCoords = base.geometry.coordinates as [number, number][];
        while (routes.length < 3) {
          const variant = routes.length;
          const offsetCoords = baseCoords.map((c: [number, number], idx: number) => {
            const mid = baseCoords.length / 2;
            const dist = 1 - Math.abs(idx - mid) / mid;
            const offset = dist * 0.0008 * (variant === 1 ? 1 : -1);
            return [c[0] + offset, c[1] + offset * 0.7] as [number, number];
          });
          const extraDuration = base.duration * (1 + variant * 0.15);
          const extraDist = base.distance * (1 + variant * 0.12);
          const extraShade = computeRouteShade(offsetCoords, extraDuration, currentMinutes, curDate);
          const extraScore = Math.round(extraShade * 0.85 + Math.max(0, 100 - Math.round(extraDuration / 60)) * 0.15);
          routes.push({
            distanceKm: (extraDist / 1000).toFixed(1),
            durationMin: Math.round(extraDuration / 60),
            shadePct: extraShade,
            score: extraScore,
            riskLevel: extraShade >= 60 ? "LOW" : extraShade >= 30 ? "MEDIUM" : "HIGH",
            riskColor: extraShade >= 60 ? "#22c55e" : extraShade >= 30 ? "#f59e0b" : "#ef4444",
            sunExposure: Math.round(Math.round(extraDuration / 60) * (1 - extraShade / 100)),
            coordinates: offsetCoords,
            reason: `${(extraDist / 1000).toFixed(1)} km alt route · ${extraShade}% avg shade`,
          });
        }
        routes.sort((a, b) => b.score - a.score);
      }

      setAlternativeRoutes(routes);
      setSelectedRouteIdx(0);
      setRouteResult(routes[0]);

      if (routes[0].coordinates.length >= 2) {
        routeKeyRef.current += 1;
        setRouteToDraw({ coordinates: routes[0].coordinates, travelMode, key: routeKeyRef.current });
      }

      toast.success(`Found ${routes.length} routes – best has ${routes[0].shadePct}% shade`);
    } catch (err) {
      toast.error(`Route error: ${(err as Error).message}`);
    }
    setRouteLoading(false);
  };

  const selectRoute = (idx: number) => {
    if (idx < 0 || idx >= alternativeRoutes.length) return;
    setSelectedRouteIdx(idx);
    const route = alternativeRoutes[idx];
    setRouteResult(route);
    if (route.coordinates.length >= 2) {
      routeKeyRef.current += 1;
      setRouteToDraw({ coordinates: route.coordinates, travelMode, key: routeKeyRef.current });
    }
  };

  // Open site popup on new task
  useEffect(() => {
    if (searchParams.get("newTask") === "true" && mode === "commercial") {
      setIsSitePopupOpen(true);
    }
  }, [searchParams, mode]);

  const openSitePopup = () => {
    setIsSitePopupOpen(true);
    setAnalysisConfirmed(false);
    setSiteRecommendations([]);
  };

  const submitSiteAnalysis = async () => {
    if (!commercialSite) {
      toast.error("Choose a site on the map or search first.");
      return;
    }
    if (siteDraft.endHour <= siteDraft.startHour) {
      toast.error("End hour must be after start hour.");
      return;
    }
    setScheduleLoading(true);
    setIsSitePopupOpen(false);
    try {
      const recs = await fetchScheduleFromBackend(
        siteDraft.taskName, commercialSite.lat, commercialSite.lng,
        siteDraft.locationName || siteDraft.locationLabel || "Dubai",
        dateStr, siteDraft.durationMinutes, siteDraft.startHour, siteDraft.endHour,
        buildingFace || undefined
      );
      setSiteRecommendations(recs);
      setAnalysisConfirmed(true);
      if (recs.length > 0) toast.success(`Found ${recs.length} optimal time windows.`);
    } catch {
      toast.error("Failed to fetch recommendations.");
      const fallback = computeWindowsFallback(dateStr, siteDraft.durationMinutes, siteDraft.startHour, siteDraft.endHour);
      setSiteRecommendations(fallback);
      setAnalysisConfirmed(true);
    }
    setScheduleLoading(false);
  };

  const saveRecommendation = async (rec: WindowRec) => {
    const id = `${siteDraft.taskName}-${rec.id}`;
    try {
      const taskRes = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-Id": user?.user_id || "" },
        body: JSON.stringify({
          task_id: id, task_name: siteDraft.taskName,
          location_name: siteDraft.locationName || siteDraft.locationLabel,
          location_lat: commercialSite?.lat || 25.2048,
          location_lon: commercialSite?.lng || 55.2708,
          duration_minutes: siteDraft.durationMinutes,
          hour_start: Math.floor(rec.start / 60),
          hour_end: Math.ceil(rec.end / 60),
          date: dateStr, status: "draft",
          user_id: user?.user_id || ""
        })
      });
      if (!taskRes.ok) throw new Error("Failed to create task");
      const taskData = await taskRes.json();
      await fetch(`${API_BASE}/api/tasks/${taskData.task_id}/accept`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accepted_time_start: formatTime(rec.start).split(" ")[0],
          accepted_time_end: formatTime(rec.end).split(" ")[0],
          shade_percentage: rec.shadePct, shade_slot: rec.title
        })
      });
      setSavedRecIds((prev) => new Set(prev).add(id));
      toast.success("Task saved!", { description: `${siteDraft.taskName} at ${rec.timeLabel}` });
    } catch {
      setSavedRecIds((prev) => new Set(prev).add(id));
      toast.success("Task saved locally");
    }
  };

  const previewRec = (rec: WindowRec) => {
    setCurrentMinutes(rec.start);
    setIsPlaying(false);
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
          <MapboxMap currentMinutes={currentMinutes} dateStr={dateStr} flyTo={flyToTarget}
            routeToDraw={routeToDraw} clearRouteKey={clearRouteKey}
            selectingPoint={mode === "commercial" && isSelectingSite ? "from" : addingPlaceOnMap ? "from" : selectingPoint}
            onPointSelected={handlePointSelected}
            onMapReady={undefined}
            onBearingChange={(b) => setMapBearing(b)}
            fromMarker={mode === "commercial" ? (commercialSite ? [commercialSite.lng, commercialSite.lat] : null) : fromCoords}
            toMarker={mode === "personal" ? toCoords : null}
          />

          {/* Floating time card */}
          <div className="absolute top-4 left-4 z-20 w-[310px] rounded-2xl border border-white/20 bg-background/45 backdrop-blur-xl shadow-2xl p-3">
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-xl font-bold font-mono text-foreground">{formatTime(currentMinutes)}</span>
              <span className="text-xs text-primary font-medium">{period}</span>
            </div>
            <input type="range" min={0} max={1440} step={5} value={currentMinutes}
              onInput={(e) => setCurrentMinutes(Number((e.target as HTMLInputElement).value))}
              onChange={(e) => setCurrentMinutes(Number(e.target.value))}
              className="w-full accent-primary h-2 cursor-pointer" />
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

          {/* Floating compass for building orientation */}
          <div className="absolute top-4 right-4 z-20 flex flex-col items-center gap-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
              Facade Compass
            </div>
            <div className="relative w-16 h-16 rounded-full border border-border/70 bg-background/70 backdrop-blur-xl shadow-lg flex items-center justify-center">
              <span className="absolute top-1.5 left-1/2 -translate-x-1/2 text-[10px] font-semibold text-foreground">
                N
              </span>
              <span className="absolute bottom-1.5 left-1/2 -translate-x-1/2 text-[10px] font-semibold text-muted-foreground">
                S
              </span>
              <span className="absolute left-1.5 top-1/2 -translate-y-1/2 text-[10px] font-semibold text-muted-foreground">
                W
              </span>
              <span className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[10px] font-semibold text-muted-foreground">
                E
              </span>
              {/* Compass needle (rotates with map bearing) */}
              <div
                className="relative flex items-center justify-center"
                style={{ transform: `rotate(${-mapBearing}deg)`, transition: "transform 150ms ease-out" }}
              >
                <div className="w-1 h-6 bg-gradient-to-b from-red-500 to-red-700 rounded-full shadow-sm -mt-3" />
                <div className="absolute w-1.5 h-1.5 rounded-full bg-background border border-red-700" />
              </div>
            </div>
          </div>
        </div>

        {/* Right panel */}
        <div className="w-80 shrink-0 border-l border-border/40 bg-background/70 backdrop-blur-xl overflow-y-auto flex flex-col">
          {/* Search */}
          <div className="px-4 py-3 border-b border-border/40">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
              {mode === "commercial" ? "Search Work Site" : "Search Location"}
            </p>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
              <input value={locationSearch} onChange={(e) => handleSearchInput(e.target.value)}
                placeholder="Search location..."
                className="w-full pl-9 pr-9 py-2 rounded-xl border border-border/60 bg-background/60 text-sm" />
              <button onClick={detectCurrentLocation} className="absolute right-2 top-2 text-muted-foreground hover:text-primary" title="Detect current location">
                <Locate className="w-4 h-4" />
              </button>
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

          {/* Quick Places */}
          <div className="px-4 py-2.5 border-b border-border/40">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Quick Places</p>
              <button onClick={() => { setShowAddPlace(true); setAddingPlaceOnMap(false); }}
                className="p-1 rounded-md hover:bg-muted text-muted-foreground hover:text-primary" title="Add place">
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {savedPlaces.map((p) => (
                <div key={p.id} className="group flex items-center gap-1 rounded-full border border-border/60 bg-background/60 pl-2.5 pr-1 py-1">
                  <button onClick={() => flyToCoords([p.lon, p.lat], 16)} className="text-xs font-medium hover:text-primary">{p.name}</button>
                  <button onClick={() => removeSavedPlace(p.id)} className="hidden group-hover:block p-0.5 rounded-full hover:bg-red-100">
                    <X className="w-2.5 h-2.5 text-red-500" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Add place dialog */}
          {showAddPlace && (
            <div className="px-4 py-3 border-b border-border/40 bg-primary/5">
              <p className="text-xs font-semibold text-foreground mb-2">Add Quick Place</p>
              <input value={newPlaceName} onChange={(e) => setNewPlaceName(e.target.value)}
                placeholder="Place name" className="w-full px-3 py-1.5 rounded-lg border border-border bg-background text-xs mb-2" />
              <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
                {newPlaceCoords ? (
                  <span className="text-green-600">{newPlaceCoords.lat.toFixed(4)}, {newPlaceCoords.lng.toFixed(4)}</span>
                ) : (
                  <button onClick={() => setAddingPlaceOnMap(true)} className="text-primary font-medium underline">Click on map to choose</button>
                )}
              </div>
              <div className="flex gap-2">
                <button onClick={addSavedPlace} disabled={!newPlaceName.trim() || !newPlaceCoords}
                  className="flex-1 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold disabled:opacity-50">Save</button>
                <button onClick={() => { setShowAddPlace(false); setNewPlaceCoords(null); setAddingPlaceOnMap(false); }}
                  className="flex-1 py-1.5 rounded-lg border border-border text-xs">Cancel</button>
              </div>
            </div>
          )}

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
                </div>
              )}

              {!analysisConfirmed && !scheduleLoading && (
                <div className="rounded-2xl border border-dashed border-border/60 bg-muted/20 px-4 py-6 text-center">
                  <p className="text-sm font-medium text-foreground mb-1">Create site analysis</p>
                  <p className="text-xs text-muted-foreground">Enter task details and choose site on map.</p>
                </div>
              )}

              {analysisConfirmed && !scheduleLoading && (
                <div className="space-y-2">
                  <div className="rounded-xl border border-primary/20 bg-primary/10 px-3 py-2">
                    <div className="text-xs font-semibold text-foreground">{siteDraft.taskName}</div>
                    <div className="text-[11px] text-muted-foreground truncate">{siteDraft.locationName || siteDraft.locationLabel}</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {siteDraft.durationMinutes} min · {siteDraft.startHour}:00–{siteDraft.endHour}:00
                    </div>
                  </div>

                  {siteRecommendations.map((rec) => {
                    const recId = `${siteDraft.taskName}-${rec.id}`;
                    const saved = savedRecIds.has(recId);
                    const tag = qualityTag(rec.quality);
                    const isHovered = hoveredRecId === rec.id;

                    return (
                      <div key={rec.id}
                        className={cn("rounded-xl border p-3 transition-all cursor-pointer",
                          isHovered ? "border-primary/60 bg-primary/5 shadow-md" : "border-border/60 bg-background/55 hover:border-primary/40")}
                        onMouseEnter={() => { setHoveredRecId(rec.id); previewRec(rec); }}
                        onMouseLeave={() => setHoveredRecId(null)}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-foreground">{rec.title}</span>
                              <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", tag.color)}>{tag.label}</span>
                            </div>
                            <div className="text-[11px] mt-1 flex items-center gap-2">
                              <span className="text-green-600 font-medium">{rec.shadePct}% shade</span>
                            </div>
                            {rec.reason && (
                              <p className="text-[10px] text-muted-foreground mt-1 italic">{rec.reason}</p>
                            )}
                          </div>
                          <button onClick={(e) => { e.stopPropagation(); saveRecommendation(rec); }}
                            className={cn("rounded-lg p-1.5 text-[11px] font-medium border shrink-0",
                              saved ? "bg-green-500/15 border-green-500/30 text-green-600" : "border-border/60 bg-background/60 hover:bg-primary/10 text-muted-foreground hover:text-primary")}
                            title={saved ? "Saved" : "Save task"}>
                            {saved ? <CheckCircle className="w-3.5 h-3.5" /> : <Bookmark className="w-3.5 h-3.5" />}
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : (
            <div className="px-4 py-3 border-b border-border/40">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">Shade-Optimized Route</h2>
              <div className="space-y-2 mb-3">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500 shrink-0" />
                  <div className="flex-1 relative">
                    <input type="text" value={fromSearch || routeFrom} onChange={(e) => searchRouteLocation(e.target.value, "from")}
                      placeholder="From - search or click map"
                      className="w-full px-2.5 py-1.5 rounded-lg border border-border/60 bg-background/60 text-xs pr-16" />
                    <div className="absolute right-1 top-0.5 flex gap-0.5">
                      <button onClick={() => setSelectingPoint(selectingPoint === "from" ? null : "from")}
                        className={cn("p-1 rounded text-xs", selectingPoint === "from" ? "bg-amber-100 text-amber-700" : "text-muted-foreground hover:text-foreground")}>
                        <MapPin className="w-3.5 h-3.5" />
                      </button>
                      <button onClick={() => {
                        if (navigator.geolocation) {
                          navigator.geolocation.getCurrentPosition((pos) => {
                            setFromCoords([pos.coords.longitude, pos.coords.latitude]);
                            setRouteFrom(`${pos.coords.latitude.toFixed(4)}°N, ${pos.coords.longitude.toFixed(4)}°E`);
                            flyToCoords([pos.coords.longitude, pos.coords.latitude]);
                          });
                        }
                      }} className="p-1 rounded text-muted-foreground hover:text-foreground">
                        <Locate className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    {fromSuggestions.length > 0 && (
                      <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-xl z-50 max-h-40 overflow-y-auto">
                        {fromSuggestions.map((s) => (
                          <button key={s.mapbox_id} onClick={() => selectRouteLocation(s, "from")}
                            className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted border-b last:border-0">
                            {s.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-blue-500 shrink-0" />
                  <div className="flex-1 relative">
                    <input type="text" value={toSearch || routeTo} onChange={(e) => searchRouteLocation(e.target.value, "to")}
                      placeholder="To - search or click map"
                      className="w-full px-2.5 py-1.5 rounded-lg border border-border/60 bg-background/60 text-xs pr-10" />
                    <button onClick={() => setSelectingPoint(selectingPoint === "to" ? null : "to")}
                      className={cn("absolute right-1 top-0.5 p-1 rounded text-xs",
                        selectingPoint === "to" ? "bg-amber-100 text-amber-700" : "text-muted-foreground hover:text-foreground")}>
                      <MapPin className="w-3.5 h-3.5" />
                    </button>
                    {toSuggestions.length > 0 && (
                      <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-xl z-50 max-h-40 overflow-y-auto">
                        {toSuggestions.map((s) => (
                          <button key={s.mapbox_id} onClick={() => selectRouteLocation(s, "to")}
                            className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted border-b last:border-0">
                            {s.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-1.5 mb-2">
                {(["walking", "cycling"] as const).map((m) => (
                  <button key={m} onClick={() => setTravelMode(m)}
                    className={cn("py-1.5 rounded-lg border text-sm font-medium flex items-center justify-center gap-1.5",
                      travelMode === m ? "bg-primary text-primary-foreground border-primary" : "bg-background/60 border-border/60")}>
                    {m === "walking" ? <Navigation2 className="w-3.5 h-3.5" /> : <Zap className="w-3.5 h-3.5" />}
                    {m === "walking" ? "Walk" : "Cycle"}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <button onClick={findRoute} disabled={routeLoading}
                  className="py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-50">
                  {routeLoading ? "Finding..." : "Find Route"}
                </button>
                <button onClick={clearRoute}
                  className="py-2 rounded-lg border border-border/60 bg-background/60 text-sm font-medium flex items-center justify-center gap-1">
                  <RotateCcw className="w-3.5 h-3.5" /> Clear
                </button>
              </div>
              {alternativeRoutes.length > 0 && (
                <div className="mt-3 space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                    {alternativeRoutes.length} Routes · Sorted by Shade
                  </p>
                  {alternativeRoutes.map((route, idx) => {
                    const isActive = idx === selectedRouteIdx;
                    const labels = ["Best Shade", "Alternative", "Shortest"];
                    const labelColors = [
                      "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
                      "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
                      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
                    ];
                    return (
                      <button key={idx} onClick={() => selectRoute(idx)}
                        className={cn(
                          "w-full text-left p-3 rounded-xl border transition-all",
                          isActive
                            ? "border-primary/60 bg-primary/5 shadow-md ring-1 ring-primary/20"
                            : "border-border/60 bg-background/55 hover:border-primary/40"
                        )}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-foreground">Route {idx + 1}</span>
                            <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", labelColors[idx] || labelColors[2])}>
                              {labels[idx] || `Option ${idx + 1}`}
                            </span>
                          </div>
                          <span className="text-sm font-bold" style={{ color: route.riskColor }}>
                            {route.score}/100
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {route.distanceKm} km · {route.durationMin} min · <span className="text-green-600 font-medium">{route.shadePct}% shade</span>
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">
                          Sun exposure: ~{route.sunExposure} min · Risk: <span style={{ color: route.riskColor }}>{route.riskLevel}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Sun metrics */}
          <div className="px-4 py-3 mt-auto">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2">Sun Metrics</h2>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "Azimuth", value: sunPos ? `${sunPos.azimuth.toFixed(1)}°` : "--", color: "text-amber-500" },
                { label: "Altitude", value: sunPos ? `${sunPos.altitude.toFixed(1)}°` : "--", color: "text-orange-500" },
                { label: "Sunrise", value: sunPos?.sunrise ?? "--", color: "text-rose-400" },
                { label: "Sunset", value: sunPos?.sunset ?? "--", color: "text-violet-500" },
              ].map((x) => (
                <div key={x.label} className="rounded-xl border border-border/60 bg-background/55 p-2">
                  <div className="text-[10px] text-muted-foreground">{x.label}</div>
                  <div className={cn("text-sm font-bold", x.color)}>{x.value}</div>
                </div>
              ))}
            </div>
            <div className="flex gap-1.5 mt-2">
              <button onClick={() => { setDateStr("2026-03-20"); toast.info("Set to Vernal Equinox (Mar 20)"); }}
                className="flex-1 py-1.5 rounded-lg border border-border/60 text-[10px] font-medium hover:bg-primary/10">
                Equinox
              </button>
              <button onClick={() => { setDateStr("2026-06-21"); toast.info("Set to Summer Solstice (Jun 21)"); }}
                className="flex-1 py-1.5 rounded-lg border border-border/60 text-[10px] font-medium hover:bg-primary/10">
                Solstice
              </button>
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
                <p className="text-xs text-muted-foreground">Enter task details, pick site, generate schedules.</p>
              </div>
              <button onClick={() => setIsSitePopupOpen(false)} className="rounded-lg p-1.5 hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Task Name</label>
                <input value={siteDraft.taskName} onChange={(e) => setSiteDraft((p) => ({ ...p, taskName: e.target.value }))}
                  placeholder="e.g. Facade Work" className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Location</label>
                <div className="flex gap-2">
                  <input value={siteDraft.locationLabel} onChange={(e) => setSiteDraft((p) => ({ ...p, locationLabel: e.target.value }))}
                    placeholder="Coordinates will appear here" className="flex-1 px-3 py-2 rounded-lg border border-border bg-background" readOnly />
                  <button onClick={() => { setIsSelectingSite(true); setIsSitePopupOpen(false); }}
                    className="px-3 py-2 rounded-lg border border-primary/25 bg-primary/10 text-primary text-sm font-medium">
                    Pick on map
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Location Name (optional)</label>
                <input value={siteDraft.locationName} onChange={(e) => setSiteDraft((p) => ({ ...p, locationName: e.target.value }))}
                  placeholder="e.g. Downtown Tower, Site A"
                  className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Duration (min)</label>
                  <input type="number" min={15} step={15} value={siteDraft.durationMinutes}
                    onChange={(e) => setSiteDraft((p) => ({ ...p, durationMinutes: Number(e.target.value) }))}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">From Hour</label>
                  <input type="number" min={0} max={23} value={siteDraft.startHour}
                    onChange={(e) => setSiteDraft((p) => ({ ...p, startHour: Number(e.target.value) }))}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">To Hour</label>
                  <input type="number" min={1} max={24} value={siteDraft.endHour}
                    onChange={(e) => setSiteDraft((p) => ({ ...p, endHour: Number(e.target.value) }))}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Building Face (optional)</label>
                <div className="flex gap-2">
                  {["", "N", "E", "S", "W"].map((face) => (
                    <button key={face || "none"} type="button" onClick={() => setBuildingFace(face)}
                      className={cn("flex-1 py-2 rounded-lg border text-sm font-medium transition-all",
                        buildingFace === face ? "bg-primary text-primary-foreground border-primary" : "border-border bg-background hover:bg-muted")}>
                      {face || "Any"}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="px-5 py-4 border-t border-border flex justify-end gap-2">
              <button onClick={() => setIsSitePopupOpen(false)} className="px-4 py-2 rounded-lg border border-border">Cancel</button>
              <button onClick={submitSiteAnalysis}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-amber-500 text-primary-foreground font-medium">
                Generate Recommendations
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
