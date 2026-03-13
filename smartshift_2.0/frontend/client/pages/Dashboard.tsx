import { AppLayout } from "@/components/AppLayout";
import { useMode } from "@/hooks/useMode";
import { useAuth } from "@/hooks/useAuth";
import {
  Sun, Clock, Compass, Navigation2, Thermometer, ShieldAlert,
  Briefcase, Navigation, AlertCircle, CheckCircle, TrendingUp,
  BarChart3, ClipboardList, ShieldCheck, Pencil, X, Save, Info, Check,
  MapPin, Search, Locate, Globe,
} from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  calculateSunPosition,
  getDubaiNow,
  getTimePeriod,
  formatTime,
  calculateUV,
  getUVCategory,
} from "@/lib/sunCalculations";

const API_BASE = "http://localhost:8080";
const MAPBOX_TOKEN = "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9.WI13BJqDyOu6G38-YP6hog";

interface HeatRisk {
  risk_level?: string;
  risk_color?: string;
  safety_message?: string;
  temperature?: number;
  humidity?: number;
  wind_speed?: number;
  uv_index?: number;
  heat_index?: number;
  wbgt_estimate?: number;
}

interface ScheduledTask {
  id: string;
  name: string;
  location: string;
  location_lat: number;
  location_lon: number;
  timeWindow: string;
  shadePercentage: number;
  status: "scheduled" | "in-process" | "completed" | "draft";
  date: string;
  duration_minutes: number;
}

interface DashboardData {
  today_tasks: Array<{
    task_id: string;
    task_name: string;
    location_name: string;
    location_lat: number;
    location_lon: number;
    hour_start: number;
    hour_end: number;
    status: string;
    duration_minutes: number;
    date: string;
  }>;
  today_task_count: number;
  total_duration_minutes: number;
  completed_count: number;
  avg_shade_coverage: number;
  scheduled_count: number;
  in_process_count: number;
}

interface AnalyticsData {
  month: string;
  total_tasks: number;
  completed_tasks: number;
  total_duration_minutes: number;
  avg_shade_coverage: number;
  target_tasks: number;
}

type ChartScale = "daily" | "weekly" | "monthly";

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function Dashboard() {
  const { mode } = useMode();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { minutes: initMinutes, dateStr: initDate } = getDubaiNow();
  const [currentMinutes, setCurrentMinutes] = useState(initMinutes);
  const [dateStr] = useState(initDate);
  const [weather, setWeather] = useState<{ temperature: number; humidity: number; wind_speed: number } | null>(null);
  const [heatRisk, setHeatRisk] = useState<HeatRisk | null>(null);
  const [heatRiskLoading, setHeatRiskLoading] = useState(false);
  const [heatRiskChecked, setHeatRiskChecked] = useState(false);
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [chartScale, setChartScale] = useState<ChartScale>("monthly");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<ScheduledTask>>({});
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [analyticsData, setAnalyticsData] = useState<AnalyticsData[]>([]);
  const [userTarget, setUserTarget] = useState(50);
  const [editingTarget, setEditingTarget] = useState(false);
  const [tempTarget, setTempTarget] = useState(50);

  // Heat risk location
  const [heatRiskLat, setHeatRiskLat] = useState(25.2048);
  const [heatRiskLon, setHeatRiskLon] = useState(55.2708);
  const [heatRiskLocationName, setHeatRiskLocationName] = useState("Detecting...");
  const [heatRiskSearch, setHeatRiskSearch] = useState("");
  const [heatRiskSuggestions, setHeatRiskSuggestions] = useState<Array<{mapbox_id: string; name: string; full_address?: string; place_formatted?: string}>>([]);

  // Personal mode location
  const [personalLat, setPersonalLat] = useState(25.2048);
  const [personalLon, setPersonalLon] = useState(55.2708);
  const [personalLocationName, setPersonalLocationName] = useState("Detecting...");
  const [personalLocationSearch, setPersonalLocationSearch] = useState("");
  const [personalSuggestions, setPersonalSuggestions] = useState<Array<{mapbox_id: string; name: string; full_address?: string; place_formatted?: string}>>([]);

  const startEdit = (task: ScheduledTask) => {
    setEditingTaskId(task.id);
    setEditForm({ name: task.name, status: task.status });
  };
  const cancelEdit = () => { setEditingTaskId(null); setEditForm({}); };
  const saveEdit = async () => {
    if (!editingTaskId) return;
    try {
      await fetch(`${API_BASE}/api/tasks/${editingTaskId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_name: editForm.name, status: editForm.status })
      });
      fetchDashboardData();
    } catch {}
    cancelEdit();
  };
  const markCompleted = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/tasks/${id}/complete`, { method: "POST" });
      fetchDashboardData();
      fetchAnalytics();
    } catch {}
  };

  const rescheduleOnMap = (task: ScheduledTask) => {
    navigate(`/map?reschedule=${task.id}&lat=${task.location_lat}&lon=${task.location_lon}&name=${encodeURIComponent(task.name)}&date=${task.date}&duration=${task.duration_minutes}`);
  };

  const fetchDashboardData = async () => {
    try {
      const headers: Record<string, string> = {};
      if (user?.user_id) headers["X-User-Id"] = user.user_id;
      const res = await fetch(`${API_BASE}/api/dashboard`, { headers });
      const data = await res.json();
      if (data.success) {
        setDashboardData(data);
        const mappedTasks: ScheduledTask[] = (data.today_tasks || []).map((t: DashboardData["today_tasks"][0]) => ({
          id: t.task_id,
          name: t.task_name,
          location: t.location_name || "—",
          location_lat: t.location_lat || 25.2048,
          location_lon: t.location_lon || 55.2708,
          timeWindow: `${String(t.hour_start).padStart(2, "0")}:00 – ${String(t.hour_end).padStart(2, "0")}:00`,
          shadePercentage: data.avg_shade_coverage || 70,
          status: t.status as ScheduledTask["status"],
          date: t.date || dateStr,
          duration_minutes: t.duration_minutes || 60,
        }));
        setTasks(mappedTasks);
      }
    } catch {}
  };

  const fetchAnalytics = async () => {
    try {
      const headers: Record<string, string> = {};
      if (user?.user_id) headers["X-User-Id"] = user.user_id;
      const res = await fetch(`${API_BASE}/api/analytics?months=6`, { headers });
      const data = await res.json();
      if (data.success) setAnalyticsData(data.analytics || []);
    } catch {}
  };

  // Detect current location on mount
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const { latitude, longitude } = pos.coords;
          if (mode === "personal") {
            setPersonalLat(latitude);
            setPersonalLon(longitude);
          }
          setHeatRiskLat(latitude);
          setHeatRiskLon(longitude);
          try {
            const res = await fetch(`https://api.mapbox.com/search/geocode/v6/reverse?longitude=${longitude}&latitude=${latitude}&access_token=${MAPBOX_TOKEN}`);
            const data = await res.json();
            const name = data.features?.[0]?.properties?.name || data.features?.[0]?.properties?.full_address || `${latitude.toFixed(2)}, ${longitude.toFixed(2)}`;
            setHeatRiskLocationName(name);
            if (mode === "personal") setPersonalLocationName(name);
          } catch {
            const name = `${latitude.toFixed(2)}, ${longitude.toFixed(2)}`;
            setHeatRiskLocationName(name);
            if (mode === "personal") setPersonalLocationName(name);
          }
        },
        () => {
          setHeatRiskLocationName("Dubai Downtown");
          setPersonalLocationName("Dubai");
        }
      );
    }
  }, []);

  useEffect(() => {
    const id = setInterval(() => setCurrentMinutes(getDubaiNow().minutes), 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => { fetchDashboardData(); fetchAnalytics(); }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/weather/forecast?lat=${personalLat}&lon=${personalLon}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.hourly?.length) {
          const w = data.hourly.find((h: { hour: number }) => h.hour === Math.floor(currentMinutes / 60));
          if (w) setWeather(w);
        }
      })
      .catch(() => {});
  }, [personalLat, personalLon]);

  const searchHeatRiskLocation = async (val: string) => {
    setHeatRiskSearch(val);
    if (val.trim().length < 2) { setHeatRiskSuggestions([]); return; }
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(val)}&language=en&limit=5&access_token=${MAPBOX_TOKEN}`);
      const data = await res.json();
      setHeatRiskSuggestions(data.suggestions || []);
    } catch { setHeatRiskSuggestions([]); }
  };

  const selectHeatRiskLocation = async (s: {mapbox_id: string; name: string; full_address?: string}) => {
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/retrieve/${s.mapbox_id}?access_token=${MAPBOX_TOKEN}`);
      const data = await res.json();
      const coords = data.features?.[0]?.geometry?.coordinates;
      if (coords) {
        setHeatRiskLat(coords[1]);
        setHeatRiskLon(coords[0]);
        setHeatRiskLocationName(s.full_address || s.name);
        setHeatRiskSearch("");
        setHeatRiskSuggestions([]);
        setHeatRiskChecked(false);
      }
    } catch {}
  };

  const searchPersonalLocation = async (val: string) => {
    setPersonalLocationSearch(val);
    if (val.trim().length < 2) { setPersonalSuggestions([]); return; }
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/suggest?q=${encodeURIComponent(val)}&language=en&limit=5&access_token=${MAPBOX_TOKEN}`);
      const data = await res.json();
      setPersonalSuggestions(data.suggestions || []);
    } catch { setPersonalSuggestions([]); }
  };

  const selectPersonalLocation = async (s: {mapbox_id: string; name: string; full_address?: string}) => {
    try {
      const res = await fetch(`https://api.mapbox.com/search/searchbox/v1/retrieve/${s.mapbox_id}?access_token=${MAPBOX_TOKEN}`);
      const data = await res.json();
      const coords = data.features?.[0]?.geometry?.coordinates;
      if (coords) {
        setPersonalLat(coords[1]);
        setPersonalLon(coords[0]);
        setPersonalLocationName(s.full_address || s.name);
        setPersonalLocationSearch("");
        setPersonalSuggestions([]);
      }
    } catch {}
  };

  const date = dateStr ? new Date(dateStr) : new Date();
  const sunPos = calculateSunPosition(date, Math.floor(currentMinutes / 60), currentMinutes % 60);
  const period = getTimePeriod(sunPos.altitude, sunPos.azimuth);
  const uv = calculateUV(date, currentMinutes);
  const uvCat = getUVCategory(uv);

  const checkHeatRisk = async () => {
    setHeatRiskLoading(true);
    setHeatRiskChecked(false);
    try {
      const hours24 = Math.floor(currentMinutes / 60);
      const mins = currentMinutes % 60;
      const formattedTime = `${String(hours24).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
      const res = await fetch(`${API_BASE}/api/heat-risk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: heatRiskLat, lon: heatRiskLon, date: dateStr, time: formattedTime }),
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      if (data.success) {
        const pred = data.prediction || data;
        const wth = data.weather || {};
        const riskLabel = (pred.risk_label || pred.risk_level || "unknown").toLowerCase();
        setHeatRisk({
          risk_level: riskLabel,
          risk_color: riskLabel === "low" ? "#22c55e" : riskLabel === "medium" ? "#f59e0b" : "#ef4444",
          safety_message: pred.safety_message || (riskLabel === "low" ? "Safe for outdoor activity" : riskLabel === "medium" ? "Take breaks, stay hydrated" : "Avoid outdoor work if possible"),
          temperature: wth.temperature,
          humidity: wth.humidity,
          wind_speed: wth.wind_speed,
          uv_index: wth.uv_index,
          heat_index: pred.heat_index,
          wbgt_estimate: pred.wbgt_estimate,
        });
        setHeatRiskChecked(true);
      }
    } catch (err) {
      setHeatRisk({
        risk_level: "Error",
        risk_color: "#ef4444",
        safety_message: `Unable to check heat risk. Error: ${err instanceof Error ? err.message : "Unknown"}`,
      });
      setHeatRiskChecked(true);
    }
    setHeatRiskLoading(false);
  };

  const riskColor = heatRisk?.risk_color || "#64748b";
  const riskLevel = heatRisk?.risk_level?.toLowerCase() || "";
  const scheduledCount = dashboardData?.scheduled_count ?? tasks.filter((t) => t.status === "scheduled").length;
  const completedCount = dashboardData?.completed_count ?? 0;
  const avgShadeCoverage = dashboardData?.avg_shade_coverage ?? 0;
  const totalDuration = dashboardData?.total_duration_minutes ?? 0;

  const progressSeries = analyticsData.length > 0
    ? analyticsData.slice(0, 6).reverse().map((a) => ({
        label: MONTH_LABELS[parseInt(a.month.split("-")[1]) - 1] || a.month,
        value: a.completed_tasks,
        goal: userTarget,
        total: a.total_tasks,
        shade: a.avg_shade_coverage,
      }))
    : [{ label: "Jan", value: 38, goal: userTarget, total: 45, shade: 72 },
       { label: "Feb", value: 42, goal: userTarget, total: 50, shade: 74 },
       { label: "Mar", value: 35, goal: userTarget, total: 48, shade: 70 },
       { label: "Apr", value: 45, goal: userTarget, total: 55, shade: 78 }];

  const progressTotal = progressSeries.reduce((sum, item) => sum + item.value, 0);
  const progressGoal = progressSeries.length * userTarget;
  const progressMax = Math.max(...progressSeries.map((item) => Math.max(item.goal, item.value)), 1);
  const progressPercent = Math.round((progressTotal / Math.max(progressGoal, 1)) * 100);
  const trendDelta = progressSeries.length > 1 ? progressSeries[progressSeries.length - 1].value - progressSeries[0].value : 0;

  // Best shade slot from accepted recommendations trend data
  const bestShadeSlots = analyticsData.length > 0
    ? analyticsData.filter(a => a.avg_shade_coverage > 0).sort((a, b) => b.avg_shade_coverage - a.avg_shade_coverage)
    : [];
  const bestSlotText = bestShadeSlots.length > 0
    ? `${bestShadeSlots[0].avg_shade_coverage.toFixed(0)}% avg shade (${MONTH_LABELS[parseInt(bestShadeSlots[0].month.split("-")[1]) - 1]})`
    : avgShadeCoverage >= 75 ? "5:00 AM - 9:00 AM (Early Morning)" : "6:00 AM - 10:00 AM (Morning)";

  const CX0 = 40, CX1 = 516, CY0 = 16, CY1 = 148;
  const cxRange = CX1 - CX0, cyRange = CY1 - CY0;
  const cx = (i: number) => CX0 + (i / Math.max(progressSeries.length - 1, 1)) * cxRange;
  const cy = (v: number) => CY0 + (1 - v / progressMax) * cyRange;
  const analyticsPoints = progressSeries.map((p, i) => `${cx(i)},${cy(p.value)}`).join(" ");
  const analyticsGoalPoints = progressSeries.map((p, i) => `${cx(i)},${cy(p.goal)}`).join(" ");
  const analyticsAreaPoints = `${CX0},${CY1} ${analyticsPoints} ${CX1},${CY1}`;

  // ─── COMMERCIAL MODE ───
  if (mode === "commercial") {
    return (
      <AppLayout>
        <div className="space-y-8">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-amber-500/20 shadow-sm ring-1 ring-primary/20">
                <Briefcase className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Task Dashboard</h1>
                <p className="text-muted-foreground mt-1">Manage outdoor tasks with optimal shade and heat protection</p>
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Tasks Today</h3>
                <ClipboardList className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{tasks.length}</div>
              <p className="text-sm text-muted-foreground">{scheduledCount} scheduled</p>
            </div>
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-amber-500/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Avg. Shade Coverage</h3>
                <Sun className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{avgShadeCoverage}%</div>
              <p className="text-sm text-muted-foreground">Across all scheduled tasks</p>
            </div>
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-violet-500/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Best Shade Window</h3>
                <TrendingUp className="w-5 h-5 text-primary" />
              </div>
              <div className="text-lg font-bold text-primary mb-2">{bestSlotText}</div>
              <p className="text-sm text-muted-foreground">Based on past shade trends</p>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.9fr)_minmax(300px,0.85fr)] gap-6 items-start">
            <div className="space-y-6">
              {/* Work Analytics */}
              <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-6 shadow-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <BarChart3 className="w-5 h-5 text-primary" />
                      <h2 className="text-xl font-semibold text-foreground">Work Analytics</h2>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">Task completion trends overview</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {(["monthly", "weekly", "daily"] as ChartScale[]).map((s) => (
                      <button key={s} onClick={() => setChartScale(s)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium ${chartScale === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground"}`}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-6">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70">Total Completed</p>
                    <div className="mt-1 flex items-end gap-2">
                      <span className="text-4xl font-bold text-foreground">{progressTotal}</span>
                      <span className={`mb-1 rounded-full px-2 py-0.5 text-xs font-semibold ${trendDelta >= 0 ? "bg-emerald-500/15 text-emerald-600" : "bg-red-500/15 text-red-600"}`}>
                        {trendDelta >= 0 ? "+" : ""}{trendDelta}
                      </span>
                    </div>
                  </div>
                  <div className="h-10 w-px bg-border/60" />
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70 flex items-center gap-1">Attainment</p>
                    <p className="mt-1 text-4xl font-bold text-foreground">{progressPercent}%</p>
                  </div>
                  <div className="h-10 w-px bg-border/60" />
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70 flex items-center gap-1">
                      Target
                      {!editingTarget && (
                        <button onClick={() => { setEditingTarget(true); setTempTarget(userTarget); }}
                          className="ml-1 text-muted-foreground hover:text-primary"><Pencil className="w-3 h-3" /></button>
                      )}
                    </p>
                    {editingTarget ? (
                      <div className="mt-1 flex items-center gap-1">
                        <input type="number" min={1} max={999} value={tempTarget}
                          onChange={(e) => setTempTarget(Number(e.target.value))}
                          className="w-20 px-2 py-1 rounded-lg border border-border bg-background text-2xl font-bold" />
                        <button onClick={() => { setUserTarget(tempTarget); setEditingTarget(false); }}
                          className="p-1 rounded bg-primary text-primary-foreground"><Check className="w-4 h-4" /></button>
                        <button onClick={() => setEditingTarget(false)}
                          className="p-1 rounded border border-border"><X className="w-4 h-4" /></button>
                      </div>
                    ) : (
                      <p className="mt-1 text-4xl font-bold text-foreground">{progressGoal}</p>
                    )}
                  </div>
                  <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-6 rounded-full bg-gradient-to-r from-primary to-amber-500" />Completed</span>
                    <span className="flex items-center gap-1.5"><span className="inline-block h-0 w-6 border-t-2 border-dashed border-amber-400/80" />Target</span>
                  </div>
                </div>

                <div className="mt-5 overflow-hidden rounded-2xl border border-primary/10 bg-background/60 px-2 pb-2 pt-4">
                  <svg viewBox="0 0 540 200" className="h-52 w-full" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
                    <defs>
                      <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.22" />
                        <stop offset="88%" stopColor="hsl(var(--primary))" stopOpacity="0" />
                      </linearGradient>
                      <linearGradient id="lineGrad" x1="0" x2="1" y1="0" y2="0">
                        <stop offset="0%" stopColor="hsl(var(--primary))" />
                        <stop offset="100%" stopColor="#f59e0b" />
                      </linearGradient>
                    </defs>
                    {/* Y-axis labels */}
                    {[0, 0.25, 0.5, 0.75, 1].map((t) => {
                      const y = CY0 + (1 - t) * cyRange;
                      const val = Math.round(t * progressMax);
                      return (
                        <g key={t}>
                          <line x1={CX0} y1={y} x2={CX1} y2={y} stroke="currentColor" strokeOpacity="0.07" />
                          <text x={CX0 - 4} y={y + 3} textAnchor="end" fontSize="9" fill="currentColor" opacity="0.4">{val}</text>
                        </g>
                      );
                    })}
                    {/* Y-axis title */}
                    <text x={8} y={CY0 + cyRange / 2} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.4" transform={`rotate(-90, 8, ${CY0 + cyRange / 2})`}>Tasks</text>
                    <polygon points={analyticsAreaPoints} fill="url(#areaFill)" />
                    <polyline points={analyticsGoalPoints} fill="none" stroke="#f59e0b" strokeOpacity="0.75" strokeWidth="1.5" strokeDasharray="6 5" strokeLinecap="round" />
                    <polyline points={analyticsPoints} fill="none" stroke="url(#lineGrad)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                    {progressSeries.map((point, index) => (
                      <g key={point.label}>
                        <text x={cx(index)} y={CY1 + 22} textAnchor="middle" fontSize="11" fill="currentColor" opacity="0.5">{point.label}</text>
                        <text x={cx(index)} y={cy(point.value) - 10} textAnchor="middle" fontSize="10.5" fill="currentColor" opacity="0.65" fontWeight="600">{point.value}</text>
                        <circle cx={cx(index)} cy={cy(point.value)} r="5" fill="hsl(var(--primary))" opacity="0.18" />
                        <circle cx={cx(index)} cy={cy(point.value)} r="3.4" fill="hsl(var(--primary))" stroke="white" strokeWidth="2" />
                      </g>
                    ))}
                    {/* X-axis title */}
                    <text x={CX0 + cxRange / 2} y={CY1 + 38} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.4">{chartScale === "monthly" ? "Month" : chartScale === "weekly" ? "Week" : "Day"}</text>
                  </svg>
                </div>
              </div>

              {/* Today's Tasks */}
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Clock className="w-5 h-5 text-primary" />
                  <h2 className="text-xl font-semibold text-foreground">Today's Tasks</h2>
                </div>
                <div className="grid gap-4">
                  {tasks.map((task) => {
                    const isEditing = editingTaskId === task.id;
                    return (
                      <div key={task.id} className="rounded-2xl border border-primary/10 bg-gradient-to-br from-primary/10 via-background to-accent/5 shadow-sm transition-all hover:shadow-md">
                        {isEditing ? (
                          <div className="p-5 space-y-4">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-semibold text-primary">Editing task</span>
                              <button onClick={cancelEdit} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted"><X className="w-4 h-4" /></button>
                            </div>
                            <div className="space-y-3">
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Task name</label>
                                <input className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm"
                                  value={editForm.name ?? ""} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
                              </div>
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Status</label>
                                <select className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm"
                                  value={editForm.status ?? "scheduled"} onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value as ScheduledTask["status"] }))}>
                                  <option value="scheduled">Scheduled</option>
                                  <option value="in-process">In Progress</option>
                                  <option value="completed">Completed</option>
                                </select>
                              </div>
                              <div className="grid grid-cols-2 gap-3">
                                <div className="opacity-50">
                                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Location (read-only)</label>
                                  <input disabled value={task.location} className="w-full rounded-xl border border-border bg-muted/50 px-3 py-2 text-sm cursor-not-allowed" />
                                </div>
                                <div className="opacity-50">
                                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Time (read-only)</label>
                                  <input disabled value={task.timeWindow} className="w-full rounded-xl border border-border bg-muted/50 px-3 py-2 text-sm cursor-not-allowed" />
                                </div>
                              </div>
                            </div>
                            <div className="flex gap-2 pt-1">
                              <button onClick={saveEdit} className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-amber-500 px-4 py-2 text-sm font-semibold text-primary-foreground">
                                <Save className="w-4 h-4" /> Save
                              </button>
                              <button onClick={() => rescheduleOnMap(task)} className="flex items-center gap-1.5 rounded-xl border border-amber-400 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700">
                                <MapPin className="w-4 h-4" /> Reschedule on Map
                              </button>
                              <button onClick={cancelEdit} className="rounded-xl border border-border px-4 py-2 text-sm font-medium text-muted-foreground">Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <div className="p-6">
                            <div className="mb-4 flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <h3 className="text-lg font-semibold text-foreground">{task.name}</h3>
                                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                                  <span className="flex items-center gap-1"><Navigation2 className="w-3 h-3" /> {task.location}</span>
                                  <span className="flex items-center gap-1 rounded-full border border-primary/10 bg-primary/5 px-2 py-0.5 text-xs font-medium">
                                    <Clock className="w-3 h-3 text-primary" /> {task.duration_minutes}m
                                  </span>
                                </p>
                              </div>
                              <div className="flex shrink-0 items-center gap-2">
                                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${task.shadePercentage >= 75 ? "bg-green-100 text-green-700" : task.shadePercentage >= 50 ? "bg-orange-100 text-orange-700" : "bg-red-100 text-red-700"}`}>
                                  {task.shadePercentage}% shade
                                </span>
                                <button onClick={() => startEdit(task)} className="rounded-lg border border-border p-1.5 text-muted-foreground hover:text-primary" title="Edit">
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                            <div className="grid grid-cols-2 gap-4 border-t border-border/60 pt-4">
                              <div className="flex items-center gap-2">
                                <Clock className="w-4 h-4 text-primary" />
                                <div>
                                  <p className="text-xs text-muted-foreground">Time</p>
                                  <p className="font-semibold text-foreground">{task.timeWindow}</p>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                <CheckCircle className="w-4 h-4 text-primary" />
                                <div>
                                  <p className="text-xs text-muted-foreground">Status</p>
                                  <p className={`font-semibold capitalize ${task.status === "completed" ? "text-green-600" : task.status === "scheduled" ? "text-primary" : "text-amber-500"}`}>
                                    {task.status === "in-process" ? "In Process" : task.status}
                                  </p>
                                </div>
                              </div>
                            </div>
                            {task.status !== "completed" && (
                              <div className="mt-3 flex justify-end">
                                <button onClick={() => markCompleted(task.id)}
                                  className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-500">
                                  <Check className="w-3.5 h-3.5" /> Complete
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Right sidebar: Heat Risk */}
            <div className="space-y-6 xl:sticky xl:top-24">
              <div className="overflow-hidden rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-orange-500/10 shadow-sm">
                <div className="flex items-center gap-3 border-b border-primary/10 bg-background/60 px-6 py-4 backdrop-blur">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500/20 to-red-500/20">
                    <ShieldAlert className="w-5 h-5 text-primary" />
                  </div>
                  <div className="flex-1">
                    <h2 className="text-base font-semibold text-foreground">Outdoor Heat Risk</h2>
                    <p className="text-xs text-muted-foreground">{heatRiskLocationName} · {formatTime(currentMinutes)}</p>
                  </div>
                </div>
                <div className="p-4 border-b border-border/40">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-muted-foreground" />
                    <input value={heatRiskSearch} onChange={(e) => searchHeatRiskLocation(e.target.value)}
                      placeholder="Update location..."
                      className="w-full pl-9 pr-3 py-2 rounded-lg border border-border/60 bg-background/60 text-xs" />
                    {heatRiskSuggestions.length > 0 && (
                      <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-xl z-50 max-h-40 overflow-y-auto">
                        {heatRiskSuggestions.map((s) => (
                          <button key={s.mapbox_id} onClick={() => selectHeatRiskLocation(s)}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-muted border-b border-border/40 last:border-0">
                            <div className="font-medium">{s.name}</div>
                            {s.full_address && <div className="text-[10px] text-muted-foreground">{s.full_address}</div>}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div className="p-6">
                  <button onClick={checkHeatRisk} disabled={heatRiskLoading}
                    className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 py-3 text-sm font-semibold text-white shadow-md disabled:opacity-50">
                    <ShieldAlert className="w-4 h-4" />
                    {heatRiskLoading ? "Checking..." : "Check Heat Risk Now"}
                  </button>
                  {!heatRiskChecked && !heatRiskLoading && (
                    <p className="py-4 text-center text-sm text-muted-foreground">Run a real-time heat check before assigning outdoor work.</p>
                  )}
                  {heatRiskChecked && heatRisk && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between rounded-xl border p-3" style={{ background: `${riskColor}10`, borderColor: `${riskColor}40` }}>
                        <div>
                          <div className="mb-0.5 text-xs uppercase tracking-wide text-muted-foreground">Risk Level</div>
                          <div className="text-xl font-bold uppercase" style={{ color: riskColor }}>{heatRisk.risk_level || "—"}</div>
                        </div>
                        <div className="text-3xl">{riskLevel === "low" ? "✅" : riskLevel === "medium" ? "⚠️" : "🚨"}</div>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-sm">
                        {[
                          { l: "Temp", v: heatRisk.temperature != null ? `${heatRisk.temperature}°C` : "--", c: "text-amber-500" },
                          { l: "Humidity", v: heatRisk.humidity != null ? `${heatRisk.humidity}%` : "--", c: "text-sky-500" },
                          { l: "Wind", v: heatRisk.wind_speed != null ? `${heatRisk.wind_speed}` : "--", c: "text-violet-500" },
                        ].map(({ l, v, c }) => (
                          <div key={l} className="rounded-xl border border-border bg-muted/60 p-2 text-center">
                            <div className="mb-0.5 text-xs text-muted-foreground">{l}</div>
                            <div className={`font-bold ${c}`}>{v}</div>
                          </div>
                        ))}
                      </div>
                      {heatRisk.safety_message && (
                        <div className="rounded-xl border p-3 text-sm" style={{ background: `${riskColor}08`, borderColor: `${riskColor}30`, color: riskColor }}>
                          {heatRisk.safety_message}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded-2xl border border-primary/30 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-6 shadow-sm">
                <div className="mb-4 flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-primary" />
                  <h3 className="font-semibold text-foreground">Today's Safety Tips</h3>
                </div>
                <ul className="space-y-3 text-sm text-muted-foreground">
                  {[
                    "Peak heat 12-3 PM: Only assign shaded tasks",
                    "Early morning (5-9 AM) offers best conditions",
                    "Ensure all workers have hydration stations",
                    "Evening shift (5-8 PM) provides excellent shade",
                  ].map((tip) => (
                    <li key={tip} className="flex items-start gap-2 rounded-xl border border-white/40 bg-background/60 px-3 py-2">
                      <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                      <span>{tip}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  // ─── PERSONAL MODE ───
  const personalSunPos = calculateSunPosition(
    date,
    Math.floor(currentMinutes / 60),
    currentMinutes % 60,
  );

  return (
    <AppLayout>
      <div className="space-y-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Navigation className="w-7 h-7 text-primary" />
            <div>
              <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Route Navigator</h1>
              <p className="text-muted-foreground mt-1">
                Live sun tracking for {personalLocationName} - {period} · Sunrise {sunPos.sunrise ?? "--"} · Sunset {sunPos.sunset ?? "--"}
              </p>
            </div>
          </div>
          <Link to="/map"
            className="hidden sm:flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors shadow">
            <Navigation2 className="w-4 h-4" /> Open Map
          </Link>
        </div>

        {/* Location picker */}
        <div className="bg-card border border-border rounded-2xl p-4 shadow-sm">
          <div className="flex items-center gap-3">
            <Globe className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground text-sm">Tracking Location</h3>
            <span className="text-xs text-muted-foreground">{personalLocationName}</span>
            <div className="flex-1" />
            <button onClick={() => {
              if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(async (pos) => {
                  setPersonalLat(pos.coords.latitude);
                  setPersonalLon(pos.coords.longitude);
                  try {
                    const res = await fetch(`https://api.mapbox.com/search/geocode/v6/reverse?longitude=${pos.coords.longitude}&latitude=${pos.coords.latitude}&access_token=${MAPBOX_TOKEN}`);
                    const data = await res.json();
                    setPersonalLocationName(data.features?.[0]?.properties?.name || `${pos.coords.latitude.toFixed(2)}, ${pos.coords.longitude.toFixed(2)}`);
                  } catch {}
                });
              }
            }} className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border text-xs font-medium hover:bg-muted">
              <Locate className="w-3.5 h-3.5" /> My Location
            </button>
          </div>
          <div className="relative mt-2">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-muted-foreground" />
            <input value={personalLocationSearch} onChange={(e) => searchPersonalLocation(e.target.value)}
              placeholder="Search city or location..."
              className="w-full pl-9 pr-3 py-2 rounded-xl border border-border bg-background text-sm" />
            {personalSuggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-xl shadow-xl z-50 max-h-48 overflow-y-auto">
                {personalSuggestions.map((s) => (
                  <button key={s.mapbox_id} onClick={() => selectPersonalLocation(s)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-muted border-b border-border/40 last:border-0">
                    <div className="font-medium">{s.name}</div>
                    {s.full_address && <div className="text-xs text-muted-foreground">{s.full_address}</div>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Sun stat cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { label: "Sun Altitude", value: `${Math.round(personalSunPos.altitude)}°`, sub: "Angle above horizon", icon: Sun, bar: Math.max(0, (personalSunPos.altitude / 90) * 100), color: "from-amber-500 to-orange-500" },
            { label: "Sun Azimuth", value: `${Math.round(personalSunPos.azimuth)}°`, sub: `Direction - ${period}`, icon: Compass, bar: (personalSunPos.azimuth / 360) * 100, color: "from-indigo-500 to-blue-500" },
            { label: "Local Time", value: formatTime(currentMinutes), sub: new Date().toLocaleDateString("en-AE", { weekday: "long", month: "short", day: "numeric" }), icon: Clock, bar: (currentMinutes / 1440) * 100, color: "from-emerald-500 to-teal-500" },
          ].map(({ label, value, sub, icon: Icon, bar, color }) => (
            <div key={label} className="bg-card border border-border rounded-2xl p-6 shadow-sm hover:shadow-md transition-shadow">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">{label}</h3>
                <Icon className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary font-mono">{value}</div>
              <p className="text-sm text-muted-foreground mt-2">{sub}</p>
              <div className="mt-4 w-full h-2 bg-muted rounded-full overflow-hidden">
                <div className={`h-full bg-gradient-to-r ${color} transition-all duration-500`} style={{ width: `${bar}%` }} />
              </div>
            </div>
          ))}
        </div>

        {/* Sun compass + weather + heat risk */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 bg-gradient-to-br from-primary/10 via-accent/5 to-background border border-border rounded-2xl p-8 shadow-sm">
            <h2 className="text-xl font-semibold text-foreground mb-6">Sun Position - {personalLocationName}</h2>
            <div className="flex items-center justify-center">
              <div className="relative w-52 h-52 rounded-full border-2 border-border bg-card shadow-inner">
                {["N", "E", "S", "W"].map((d, i) => {
                  const positions = ["top-2 left-1/2 -translate-x-1/2", "right-2 top-1/2 -translate-y-1/2", "bottom-2 left-1/2 -translate-x-1/2", "left-2 top-1/2 -translate-y-1/2"];
                  return <div key={d} className={`absolute ${positions[i]} text-xs font-semibold text-muted-foreground`}>{d}</div>;
                })}
                <div className="absolute inset-1/3 bg-primary rounded-full shadow-md flex items-center justify-center">
                  <Sun className={`w-8 h-8 text-primary-foreground ${personalSunPos.isDaylight ? "animate-pulse" : "opacity-30"}`} />
                </div>
                <div className="absolute w-1 h-20 bg-primary/60 origin-bottom transition-all duration-1000" style={{ left: "50%", bottom: "50%", transform: `translate(-50%, 0) rotate(${personalSunPos.azimuth}deg)` }}>
                  <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 bg-primary rounded-full shadow-md" />
                </div>
              </div>
            </div>
            <p className="text-center text-sm text-muted-foreground mt-4">
              {personalSunPos.isDaylight ? `Sun is ${Math.round(personalSunPos.altitude)}° above the horizon` : "Sun is below the horizon"}
            </p>
          </div>

          <div className="space-y-4">
            <div className="bg-card border border-border rounded-2xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold text-foreground text-sm">UV Index</h3>
                <Sun className="w-4 h-4 text-primary" />
              </div>
              <div className="text-3xl font-bold" style={{ color: uvCat.color }}>{uv}</div>
              <p className="text-sm text-muted-foreground mt-1">{uvCat.level}</p>
              <div className="mt-3 w-full h-2 bg-muted rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${(uv / 12) * 100}%`, background: uvCat.color }} />
              </div>
            </div>

            {weather && (
              <div className="bg-card border border-border rounded-2xl p-5 shadow-sm">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold text-foreground text-sm">Weather</h3>
                  <Thermometer className="w-4 h-4 text-primary" />
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-muted-foreground">Temperature</span><span className="font-semibold text-amber-500">{weather.temperature}°C</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Humidity</span><span className="font-semibold text-sky-500">{weather.humidity}%</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Wind</span><span className="font-semibold text-violet-500">{weather.wind_speed} km/h</span></div>
                </div>
              </div>
            )}

            <div className="bg-card border border-border rounded-2xl p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <ShieldAlert className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-foreground text-sm">Heat Risk</h3>
              </div>
              <button onClick={checkHeatRisk} disabled={heatRiskLoading}
                className="w-full py-2 rounded-lg bg-gradient-to-r from-orange-500 to-red-500 text-white text-sm font-semibold disabled:opacity-50 mb-3">
                {heatRiskLoading ? "Checking..." : "Check Now"}
              </button>
              {heatRiskChecked && heatRisk && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold uppercase" style={{ color: riskColor }}>{heatRisk.risk_level}</span>
                    <span>{riskLevel === "low" ? "✅" : riskLevel === "medium" ? "⚠️" : "🚨"}</span>
                  </div>
                  {heatRisk.safety_message && <p className="text-xs text-muted-foreground">{heatRisk.safety_message}</p>}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="bg-gradient-to-br from-primary/10 to-accent/10 border border-primary/30 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <AlertCircle className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Walking Tips</h3>
          </div>
          <ul className="space-y-3 text-sm text-muted-foreground">
            {[
              "Peak sun: 11 AM - 4 PM - Use shade-optimized routes",
              "Shade routes add ~10% to travel time but reduce heat exposure",
              "Wear sunscreen and light-colored, loose clothing",
              "Stay hydrated: Carry water even for short walks",
            ].map((tip) => (
              <li key={tip} className="flex items-start gap-2">
                <TrendingUp className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                <span>{tip}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </AppLayout>
  );
}
