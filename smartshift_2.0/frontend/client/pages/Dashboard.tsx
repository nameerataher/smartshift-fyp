import { AppLayout } from "@/components/AppLayout";
import { useMode } from "@/hooks/useMode";
import {
  Sun, Clock, Compass, Navigation2, Thermometer, ShieldAlert,
  Briefcase, Navigation, AlertCircle, CheckCircle, Plus, TrendingUp,
  BarChart3, ClipboardList, ShieldCheck, Pencil, Trash2, X, Save, Info, Check,
} from "lucide-react";
import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  calculateSunPosition,
  getDubaiNow,
  getTimePeriod,
  formatTime,
  calculateUV,
  getUVCategory,
} from "@/lib/sunCalculations";

const API_BASE = "http://localhost:8002";

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

// ─── Commercial mode: task data ────────────────────────────────────────────
interface ScheduledTask {
  id: string;
  name: string;
  location: string;
  timeWindow: string;
  shadePercentage: number;
  status: "scheduled" | "in-process" | "completed" | "draft";
}

interface DashboardData {
  today_tasks: Array<{
    task_id: string;
    task_name: string;
    location_name: string;
    hour_start: number;
    hour_end: number;
    status: string;
    duration_minutes: number;
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

const DEFAULT_TASKS: ScheduledTask[] = [];

type ChartRange = "month";

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function getTaskDurationMinutes(timeWindow: string): number {
  const parts = timeWindow.split("–").map((part) => part.trim());
  if (parts.length !== 2) return 0;

  const parse = (value: string) => {
    const [hours, minutes] = value.split(":").map(Number);
    return hours * 60 + minutes;
  };

  const start = parse(parts[0]);
  const end = parse(parts[1]);

  if (Number.isNaN(start) || Number.isNaN(end)) return 0;
  return Math.max(end - start, 0);
}

function formatTaskDuration(totalMinutes: number): string {
  if (totalMinutes <= 0) return "0m";
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}

export default function Dashboard() {
  const { mode } = useMode();
  const { minutes: initMinutes, dateStr: initDate } = getDubaiNow();
  const [currentMinutes, setCurrentMinutes] = useState(initMinutes);
  const [dateStr] = useState(initDate);
  const [weather, setWeather] = useState<{ temperature: number; humidity: number; wind_speed: number } | null>(null);
  const [heatRisk, setHeatRisk] = useState<HeatRisk | null>(null);
  const [heatRiskLoading, setHeatRiskLoading] = useState(false);
  const [heatRiskChecked, setHeatRiskChecked] = useState(false);
  const [tasks, setTasks] = useState<ScheduledTask[]>(DEFAULT_TASKS);
  const [chartRange] = useState<ChartRange>("month");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<ScheduledTask>>({});
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [analyticsData, setAnalyticsData] = useState<AnalyticsData[]>([]);
  const [selectedMonth, setSelectedMonth] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });

  const startEdit = (task: ScheduledTask) => {
    setEditingTaskId(task.id);
    setEditForm({ ...task });
  };
  const cancelEdit = () => { setEditingTaskId(null); setEditForm({}); };
  const saveEdit = async () => {
    if (!editingTaskId) return;
    try {
      await fetch(`${API_BASE}/api/tasks/${editingTaskId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_name: editForm.name,
          location_name: editForm.location,
          status: editForm.status
        })
      });
      fetchDashboardData();
    } catch {}
    cancelEdit();
  };
  const deleteTask = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/tasks/${id}`, { method: "DELETE" });
      setTasks((prev) => prev.filter((t) => t.id !== id));
      fetchDashboardData();
    } catch {}
  };
  const markCompleted = async (id: string) => {
    try {
      await fetch(`${API_BASE}/api/tasks/${id}/complete`, { method: "POST" });
      fetchDashboardData();
      fetchAnalytics();
    } catch {}
  };

  const fetchDashboardData = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard`);
      const data = await res.json();
      if (data.success) {
        setDashboardData(data);
        const mappedTasks: ScheduledTask[] = (data.today_tasks || []).map((t: DashboardData["today_tasks"][0]) => ({
          id: t.task_id,
          name: t.task_name,
          location: t.location_name || "—",
          timeWindow: `${String(t.hour_start).padStart(2, "0")}:00 – ${String(t.hour_end).padStart(2, "0")}:00`,
          shadePercentage: data.avg_shade_coverage || 70,
          status: t.status as ScheduledTask["status"]
        }));
        setTasks(mappedTasks);
      }
    } catch {}
  };

  const fetchAnalytics = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/analytics?months=4`);
      const data = await res.json();
      if (data.success) {
        setAnalyticsData(data.analytics || []);
      }
    } catch {}
  };

  // tick every minute
  useEffect(() => {
    const id = setInterval(() => setCurrentMinutes(getDubaiNow().minutes), 60_000);
    return () => clearInterval(id);
  }, []);

  // fetch dashboard and analytics on mount
  useEffect(() => {
    fetchDashboardData();
    fetchAnalytics();
  }, []);

  // fetch weather once
  useEffect(() => {
    fetch(`${API_BASE}/api/weather/forecast`)
      .then((r) => r.json())
      .then((data) => {
        if (data.success && data.hourly?.length) {
          const w = data.hourly.find((h: { hour: number }) => h.hour === Math.floor(currentMinutes / 60));
          if (w) setWeather(w);
        }
      })
      .catch(() => {});
  }, []);

  const date = dateStr ? new Date(dateStr) : new Date();
  const sunPos = calculateSunPosition(date, Math.floor(currentMinutes / 60), currentMinutes % 60);
  const period = getTimePeriod(sunPos.altitude, sunPos.azimuth);
  const uv = calculateUV(date, currentMinutes);
  const uvCat = getUVCategory(uv);

  const checkHeatRisk = async () => {
    setHeatRiskLoading(true);
    setHeatRiskChecked(false);
    try {
      const timeStr = formatTime(currentMinutes).replace(" AM", "").replace(" PM", "");
      const hours24 = currentMinutes >= 720 ? Math.floor(currentMinutes / 60) : Math.floor(currentMinutes / 60);
      const mins = currentMinutes % 60;
      const formattedTime = `${String(hours24).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
      
      const res = await fetch(`${API_BASE}/api/heat-risk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: 25.2048, lon: 55.2708, date: dateStr, time: formattedTime }),
      });
      
      if (!res.ok) {
        throw new Error(`API error: ${res.status}`);
      }
      
      const data = await res.json();
      if (data.success) {
        const pred = data.prediction || data;
        const wth = data.weather || data.weather_data || data;
        const riskLabel = (pred.risk_label || pred.risk_level || "unknown").toLowerCase();
        setHeatRisk({
          risk_level: riskLabel,
          risk_color: riskLabel === "low" ? "#22c55e" : riskLabel === "medium" ? "#f59e0b" : "#ef4444",
          safety_message: data.safety_message || pred.safety_message || (riskLabel === "low" ? "Safe for outdoor activity" : riskLabel === "medium" ? "Take breaks, stay hydrated" : "Avoid outdoor work if possible"),
          temperature: wth.temperature,
          humidity: wth.humidity,
          wind_speed: wth.wind_speed,
          uv_index: wth.uv_index,
          heat_index: pred.heat_index,
          wbgt_estimate: pred.wbgt_estimate,
        });
        setHeatRiskChecked(true);
      } else {
        throw new Error(data.error || "Heat risk check failed");
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Unknown error";
      setHeatRisk({
        risk_level: "Error",
        risk_color: "#ef4444",
        safety_message: `Unable to check heat risk. Make sure the Python API server is running (python api_server.py). Error: ${errorMessage}`,
      });
      setHeatRiskChecked(true);
    }
    setHeatRiskLoading(false);
  };

  const riskColor = heatRisk?.risk_color || "#64748b";
  const riskLevel = heatRisk?.risk_level?.toLowerCase() || "";
  const scheduledCount = dashboardData?.scheduled_count ?? tasks.filter((t) => t.status === "scheduled").length;
  const completedCount = dashboardData?.completed_count ?? tasks.filter((t) => t.status === "completed").length;
  const avgShadeCoverage = dashboardData?.avg_shade_coverage ?? (tasks.length > 0 ? Math.round(tasks.reduce((a, t) => a + t.shadePercentage, 0) / tasks.length) : 0);
  const totalDuration = dashboardData?.total_duration_minutes ?? tasks.reduce((sum, task) => sum + getTaskDurationMinutes(task.timeWindow), 0);
  
  // Build analytics progress series from backend data or use placeholder
  const progressSeries = analyticsData.length > 0 
    ? analyticsData.slice(0, 4).reverse().map((a) => ({
        label: MONTH_LABELS[parseInt(a.month.split("-")[1]) - 1] || a.month,
        value: a.completed_tasks,
        goal: a.target_tasks || 50,
      }))
    : [
        { label: "Jan", value: 38, goal: 50 },
        { label: "Feb", value: 42, goal: 50 },
        { label: "Mar", value: 35, goal: 50 },
        { label: "Apr", value: 45, goal: 50 },
      ];
  
  const progressTotal = progressSeries.reduce((sum, item) => sum + item.value, 0);
  const progressGoal = progressSeries.reduce((sum, item) => sum + item.goal, 0);
  const progressMax = Math.max(...progressSeries.map((item) => Math.max(item.goal, item.value)), 1);
  const progressPercent = Math.round((progressTotal / Math.max(progressGoal, 1)) * 100);
  const trendDelta = progressSeries.length > 1 ? progressSeries[progressSeries.length - 1].value - progressSeries[0].value : 0;
  // Chart uses viewBox="0 0 540 200": plot area x∈[24,516] y∈[16,148], labels at y=168
  const CX0 = 24, CX1 = 516, CY0 = 16, CY1 = 148;
  const cxRange = CX1 - CX0, cyRange = CY1 - CY0;
  const cx = (i: number) => CX0 + (i / Math.max(progressSeries.length - 1, 1)) * cxRange;
  const cy = (v: number) => CY0 + (1 - v / progressMax) * cyRange;
  const analyticsPoints = progressSeries.map((p, i) => `${cx(i)},${cy(p.value)}`).join(" ");
  const analyticsGoalPoints = progressSeries.map((p, i) => `${cx(i)},${cy(p.goal)}`).join(" ");
  const analyticsAreaPoints = `${CX0},${CY1} ${analyticsPoints} ${CX1},${CY1}`;

  // ─── COMMERCIAL MODE ───────────────────────────────────────────────────────
  if (mode === "commercial") {
    return (
      <AppLayout>
        <div className="space-y-8">
          {/* Header */}
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-amber-500/20 shadow-sm ring-1 ring-primary/20">
                <Briefcase className="w-6 h-6 text-primary" />
              </div>
              <div>
                <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Task Dashboard</h1>
                <p className="text-muted-foreground mt-1">
                  Manage outdoor tasks with optimal shade and heat protection
                </p>
              </div>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Tasks Today</h3>
                <ClipboardList className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{tasks.length}</div>
              <p className="text-sm text-muted-foreground">
                {scheduledCount} scheduled
              </p>
            </div>
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-amber-500/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Avg. Shade Coverage</h3>
                <Sun className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{avgShadeCoverage}%</div>
              <p className="text-sm text-muted-foreground">Across all scheduled tasks</p>
            </div>
            <div className="rounded-2xl border border-green-500/20 bg-gradient-to-br from-emerald-500/10 via-background to-green-500/5 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Worker Safety</h3>
                <ShieldCheck className="w-5 h-5 text-green-600" />
              </div>
              <div className="text-4xl font-bold text-green-600 mb-2">{heatRiskChecked ? "Live" : "Ready"}</div>
              <p className="text-sm text-muted-foreground">
                {heatRiskChecked ? "Heat guidance synced for current Dubai conditions" : "Run a live heat check before dispatch"}
              </p>
            </div>
            <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-violet-500/10 p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Total Duration</h3>
                <TrendingUp className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{totalDuration} mins</div>
              <p className="text-sm text-muted-foreground">Total duration of all tasks</p>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.9fr)_minmax(300px,0.85fr)] gap-6 items-start">
            <div className="space-y-6">
              <div className="rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-6 shadow-sm">
                {/* Card header row */}
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <BarChart3 className="w-5 h-5 text-primary" />
                      <h2 className="text-xl font-semibold text-foreground">Work Analytics</h2>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Task completion trends — past 4 months overview.
                    </p>
                  </div>
                  {/* Month selector */}
                  <div className="flex shrink-0 items-center gap-2">
                    <select
                      value={selectedMonth}
                      onChange={(e) => setSelectedMonth(e.target.value)}
                      className="rounded-xl border border-primary/20 bg-background/80 px-3 py-2 text-sm font-medium text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
                    >
                      {Array.from({ length: 4 }, (_, i) => {
                        const d = new Date();
                        d.setMonth(d.getMonth() - i);
                        const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                        const label = d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
                        return <option key={value} value={value}>{label}</option>;
                      })}
                    </select>
                  </div>
                </div>

                {/* KPI row */}
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
                  <div className="group relative">
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70 flex items-center gap-1">
                      Attainment
                      <span className="cursor-help" title="Percentage of completed tasks vs target. Shows how well you're meeting your task completion goals.">
                        <Info className="w-3 h-3 text-muted-foreground hover:text-primary" />
                      </span>
                    </p>
                    <p className="mt-1 text-4xl font-bold text-foreground">{progressPercent}%</p>
                    <div className="absolute left-0 top-full mt-2 hidden group-hover:block z-50 w-48 rounded-lg border border-border bg-card p-2 text-xs text-muted-foreground shadow-lg">
                      Attainment = (Completed / Target) × 100. Measures task completion efficiency.
                    </div>
                  </div>
                  <div className="h-10 w-px bg-border/60" />
                  <div className="group relative">
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70 flex items-center gap-1">
                      Target
                      <span className="cursor-help" title="Total number of tasks planned to complete across the displayed months.">
                        <Info className="w-3 h-3 text-muted-foreground hover:text-primary" />
                      </span>
                    </p>
                    <p className="mt-1 text-4xl font-bold text-foreground">{progressGoal}</p>
                    <div className="absolute left-0 top-full mt-2 hidden group-hover:block z-50 w-48 rounded-lg border border-border bg-card p-2 text-xs text-muted-foreground shadow-lg">
                      Target = Sum of monthly task goals. Set based on workforce capacity and project needs.
                    </div>
                  </div>
                  <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-6 rounded-full bg-gradient-to-r from-primary to-amber-500" />Actual</span>
                    <span className="flex items-center gap-1.5"><span className="inline-block h-0 w-6 border-t-2 border-dashed border-amber-400/80" />Target</span>
                  </div>
                </div>

                {/* Chart */}
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
                      <filter id="lineGlow" x="-10%" y="-40%" width="120%" height="180%">
                        <feGaussianBlur stdDeviation="2.5" result="blur" />
                        <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                      </filter>
                    </defs>

                    {/* Subtle horizontal grid */}
                    {[0.25, 0.5, 0.75, 1].map((t) => {
                      const y = CY0 + (1 - t) * cyRange;
                      return <line key={t} x1={CX0} y1={y} x2={CX1} y2={y} stroke="currentColor" strokeOpacity="0.07" />;
                    })}

                    {/* Gradient fill under actual line */}
                    <polygon points={analyticsAreaPoints} fill="url(#areaFill)" />

                    {/* Target dashed line */}
                    <polyline
                      points={analyticsGoalPoints}
                      fill="none"
                      stroke="#f59e0b"
                      strokeOpacity="0.75"
                      strokeWidth="1.5"
                      strokeDasharray="6 5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />

                    {/* Actual line */}
                    <polyline
                      points={analyticsPoints}
                      fill="none"
                      stroke="url(#lineGrad)"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      filter="url(#lineGlow)"
                    />

                    {/* Data points + labels */}
                    {progressSeries.map((point, index) => {
                      const x = cx(index);
                      const y = cy(point.value);
                      const pct = Math.round((point.value / point.goal) * 100);
                      return (
                        <g key={point.label}>
                          {/* X-axis label */}
                          <text x={x} y={CY1 + 22} textAnchor="middle" fontSize="11" fill="currentColor" opacity="0.5" fontFamily="inherit">{point.label}</text>
                          {/* Value tooltip above dot */}
                          <text x={x} y={y - 10} textAnchor="middle" fontSize="10.5" fill="currentColor" opacity="0.65" fontFamily="inherit" fontWeight="600">{point.value}</text>
                          {/* Dot: outer glow ring */}
                          <circle cx={x} cy={y} r="5" fill="hsl(var(--primary))" opacity="0.18" />
                          {/* Dot: solid */}
                          <circle cx={x} cy={y} r="3.4" fill="hsl(var(--primary))" stroke="white" strokeWidth="2" />
                          {/* Attainment % below x-label */}
                          <text x={x} y={CY1 + 36} textAnchor="middle" fontSize="9.5" fill="currentColor" opacity="0.38" fontFamily="inherit">{pct}%</text>
                        </g>
                      );
                    })}
                  </svg>
                </div>

                {/* "Current Window" summary at bottom */}
                <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-4">
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70">Completed tasks</p>
                    <p className="mt-1 text-2xl font-bold text-foreground">{completedCount}</p>
                  </div>
                  <div className="rounded-xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-accent/10 p-4">
                    <p className="text-xs font-semibold uppercase tracking-widest text-primary/70">Best shade slot</p>
                    <p className="mt-1 text-2xl font-bold text-foreground">{avgShadeCoverage >= 80 ? "Evening" : "Morning"}</p>
                  </div>
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
                          /* ── Inline edit form ── */
                          <div className="p-5 space-y-4">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-semibold text-primary">Editing task</span>
                              <button type="button" onClick={cancelEdit} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                                <X className="w-4 h-4" />
                              </button>
                            </div>
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                              <div className="sm:col-span-2">
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Task name</label>
                                <input
                                  className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
                                  value={editForm.name ?? ""}
                                  onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                                />
                              </div>
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Location</label>
                                <input
                                  className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
                                  value={editForm.location ?? ""}
                                  onChange={(e) => setEditForm((f) => ({ ...f, location: e.target.value }))}
                                />
                              </div>
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Time window</label>
                                <input
                                  className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
                                  value={editForm.timeWindow ?? ""}
                                  onChange={(e) => setEditForm((f) => ({ ...f, timeWindow: e.target.value }))}
                                />
                              </div>
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Shade % (0–100)</label>
                                <input
                                  type="number" min={0} max={100}
                                  className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
                                  value={editForm.shadePercentage ?? 0}
                                  onChange={(e) => setEditForm((f) => ({ ...f, shadePercentage: Number(e.target.value) }))}
                                />
                              </div>
                              <div>
                                <label className="mb-1 block text-xs font-medium text-muted-foreground">Status</label>
                                <select
                                  className="w-full rounded-xl border border-border bg-background/80 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30"
                                  value={editForm.status ?? "scheduled"}
                                  onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value as ScheduledTask["status"] }))}
                                >
                                  <option value="scheduled">Scheduled</option>
                                  <option value="in-progress">In Progress</option>
                                  <option value="completed">Completed</option>
                                </select>
                              </div>
                            </div>
                            <div className="flex gap-2 pt-1">
                              <button
                                type="button"
                                onClick={saveEdit}
                                className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-primary to-amber-500 px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
                              >
                                <Save className="w-4 h-4" /> Save
                              </button>
                              <button type="button" onClick={cancelEdit} className="rounded-xl border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          /* ── Normal display ── */
                          <div className="p-6">
                            <div className="mb-4 flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1">
                                <h3 className="text-lg font-semibold text-foreground">{task.name}</h3>
                                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                                  <span className="flex items-center gap-1">
                                    <Navigation2 className="w-3 h-3" /> {task.location}
                                  </span>
                                  <span className="flex items-center gap-1 rounded-full border border-primary/10 bg-primary/5 px-2 py-0.5 text-xs font-medium text-foreground/80">
                                    <Clock className="w-3 h-3 text-primary" />
                                    {formatTaskDuration(getTaskDurationMinutes(task.timeWindow))}
                                  </span>
                                </p>
                              </div>
                              <div className="flex shrink-0 items-center gap-2">
                                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${task.shadePercentage >= 75 ? "bg-green-100 text-green-700" : task.shadePercentage >= 50 ? "bg-orange-100 text-orange-700" : "bg-red-100 text-red-700"}`}>
                                  {task.shadePercentage}% shade
                                </span>
                                <button
                                  type="button"
                                  onClick={() => startEdit(task)}
                                  className="rounded-lg border border-border p-1.5 text-muted-foreground transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
                                  title="Edit task"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => deleteTask(task.id)}
                                  className="rounded-lg border border-border p-1.5 text-muted-foreground transition-all hover:border-red-400/40 hover:bg-red-500/5 hover:text-red-500"
                                  title="Delete task"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
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
                              <button
                                type="button"
                                onClick={() => markCompleted(task.id)}
                                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:-translate-y-0.5 hover:bg-green-500 hover:shadow-md"
                              >
                                <Check className="w-4 h-4" /> Mark Completed
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="space-y-6 xl:sticky xl:top-24">
              <div className="overflow-hidden rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/10 via-background to-orange-500/10 shadow-sm">
                <div className="flex items-center gap-3 border-b border-primary/10 bg-background/60 px-6 py-4 backdrop-blur">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500/20 to-red-500/20">
                    <ShieldAlert className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <h2 className="text-base font-semibold text-foreground">Outdoor Heat Risk</h2>
                    <p className="text-xs text-muted-foreground">Dubai Downtown · {formatTime(currentMinutes)}</p>
                  </div>
                </div>
                <div className="p-6">
                  <button
                    onClick={checkHeatRisk}
                    disabled={heatRiskLoading}
                    className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 py-3 text-sm font-semibold text-white shadow-md transition-all hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-50"
                  >
                    <ShieldAlert className="w-4 h-4" />
                    {heatRiskLoading ? "Checking..." : "Check Heat Risk Now"}
                  </button>
                  {!heatRiskChecked && !heatRiskLoading && (
                    <p className="py-4 text-center text-sm text-muted-foreground">Run a real-time heat check before assigning exposed outdoor work.</p>
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
                    "Peak heat 12–3 PM: Only assign shaded tasks",
                    "Early morning (5–9 AM) offers best conditions across all sites",
                    "Ensure all workers have hydration stations at each site",
                    "Evening shift (5–8 PM) provides excellent shade coverage",
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

  // ─── PERSONAL MODE ─────────────────────────────────────────────────────────
  return (
    <AppLayout>
      <div className="space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Navigation className="w-7 h-7 text-primary" />
            <div>
              <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Route Navigator</h1>
              <p className="text-muted-foreground mt-1">
                Live sun tracking for Dubai — {period} · Sunrise {sunPos.sunrise ?? "--"} · Sunset {sunPos.sunset ?? "--"}
              </p>
            </div>
          </div>
          <Link
            to="/map"
            className="hidden sm:flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors shadow"
          >
            <Navigation2 className="w-4 h-4" />
            Open Map
          </Link>
        </div>

        {/* Sun stat cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { label: "Sun Altitude", value: `${Math.round(sunPos.altitude)}°`, sub: "Angle above horizon", icon: Sun, bar: Math.max(0, (sunPos.altitude / 90) * 100), color: "from-amber-500 to-orange-500" },
            { label: "Sun Azimuth", value: `${Math.round(sunPos.azimuth)}°`, sub: `Direction — ${period}`, icon: Compass, bar: (sunPos.azimuth / 360) * 100, color: "from-indigo-500 to-blue-500" },
            { label: "Dubai Time", value: formatTime(currentMinutes), sub: new Date().toLocaleDateString("en-AE", { weekday: "long", month: "short", day: "numeric", timeZone: "Asia/Dubai" }), icon: Clock, bar: (currentMinutes / 1440) * 100, color: "from-emerald-500 to-teal-500" },
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
          {/* Compass */}
          <div className="lg:col-span-2 bg-gradient-to-br from-primary/10 via-accent/5 to-background border border-border rounded-2xl p-8 shadow-sm">
            <h2 className="text-xl font-semibold text-foreground mb-6">Sun Position — Dubai</h2>
            <div className="flex items-center justify-center">
              <div className="relative w-52 h-52 rounded-full border-2 border-border bg-card shadow-inner">
                {["N", "E", "S", "W"].map((d, i) => {
                  const positions = ["top-2 left-1/2 -translate-x-1/2", "right-2 top-1/2 -translate-y-1/2", "bottom-2 left-1/2 -translate-x-1/2", "left-2 top-1/2 -translate-y-1/2"];
                  return <div key={d} className={`absolute ${positions[i]} text-xs font-semibold text-muted-foreground`}>{d}</div>;
                })}
                <div className="absolute inset-1/3 bg-primary rounded-full shadow-md flex items-center justify-center">
                  <Sun className={`w-8 h-8 text-primary-foreground ${sunPos.isDaylight ? "animate-pulse" : "opacity-30"}`} />
                </div>
                <div className="absolute w-1 h-20 bg-primary/60 origin-bottom transition-all duration-1000" style={{ left: "50%", bottom: "50%", transform: `translate(-50%, 0) rotate(${sunPos.azimuth}deg)` }}>
                  <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 bg-primary rounded-full shadow-md" />
                </div>
              </div>
            </div>
            <p className="text-center text-sm text-muted-foreground mt-4">
              {sunPos.isDaylight ? `Sun is ${Math.round(sunPos.altitude)}° above the horizon` : "Sun is below the horizon"}
            </p>
          </div>

          {/* Side: UV + Weather + Heat Risk */}
          <div className="space-y-4">
            {/* UV Index */}
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
                  <h3 className="font-semibold text-foreground text-sm">Weather — Dubai</h3>
                  <Thermometer className="w-4 h-4 text-primary" />
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-muted-foreground">Temperature</span><span className="font-semibold text-amber-500">{weather.temperature}°C</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Humidity</span><span className="font-semibold text-sky-500">{weather.humidity}%</span></div>
                  <div className="flex justify-between"><span className="text-muted-foreground">Wind</span><span className="font-semibold text-violet-500">{weather.wind_speed} km/h</span></div>
                </div>
              </div>
            )}

            {/* Heat Risk for personal mode */}
            <div className="bg-card border border-border rounded-2xl p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-3">
                <ShieldAlert className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-foreground text-sm">Heat Risk</h3>
              </div>
              <button
                onClick={checkHeatRisk}
                disabled={heatRiskLoading}
                className="w-full py-2 rounded-lg bg-gradient-to-r from-orange-500 to-red-500 text-white text-sm font-semibold hover:from-orange-400 hover:to-red-400 transition-all disabled:opacity-50 mb-3"
              >
                {heatRiskLoading ? "Checking…" : "🌡️ Check Now"}
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

        {/* Walking Tips */}
        <div className="bg-gradient-to-br from-primary/10 to-accent/10 border border-primary/30 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <AlertCircle className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Walking Tips</h3>
          </div>
          <ul className="space-y-3 text-sm text-muted-foreground">
            {[
              "Peak sun: 11 AM – 4 PM — Use shade-optimized routes",
              "Shade-optimized routes add ~10% to travel time but reduce heat exposure significantly",
              "Wear sunscreen and light-colored, loose clothing on sunny days",
              "Stay hydrated: Carry water even for short walks in heat",
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
