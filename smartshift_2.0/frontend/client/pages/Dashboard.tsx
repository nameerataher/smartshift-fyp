import { AppLayout } from "@/components/AppLayout";
import { useMode } from "@/hooks/useMode";
import {
  Sun, Clock, Compass, Navigation2, Thermometer, ShieldAlert,
  Briefcase, Navigation, AlertCircle, CheckCircle, Plus, TrendingUp,
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
  status: "scheduled" | "in-progress" | "completed";
}

const DEFAULT_TASKS: ScheduledTask[] = [
  { id: "1", name: "Facade Cleaning – North Wing", location: "Downtown Site", timeWindow: "05:00 – 09:00", shadePercentage: 75, status: "scheduled" },
  { id: "2", name: "Foundation Inspection", location: "North Industrial Zone", timeWindow: "18:00 – 20:00", shadePercentage: 85, status: "scheduled" },
];

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

  // tick every minute
  useEffect(() => {
    const id = setInterval(() => setCurrentMinutes(getDubaiNow().minutes), 60_000);
    return () => clearInterval(id);
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
      const res = await fetch(`${API_BASE}/api/heat-risk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: 25.2048, lon: 55.2708, date: dateStr, time: formatTime(currentMinutes) }),
      });
      const data = await res.json();
      if (data.success) {
        const pred = data.prediction || data;
        const wth = data.weather || data.weather_data || data;
        setHeatRisk({
          risk_level: pred.risk_label || pred.risk_level,
          risk_color: pred.risk_label === "low" ? "#22c55e" : pred.risk_label === "medium" ? "#f59e0b" : "#ef4444",
          safety_message: data.safety_message || (pred.risk_label === "low" ? "Safe for outdoor activity" : pred.risk_label === "medium" ? "Take breaks, stay hydrated" : "Avoid outdoor work if possible"),
          temperature: wth.temperature,
          humidity: wth.humidity,
          wind_speed: wth.wind_speed,
          uv_index: wth.uv_index,
          heat_index: pred.heat_index,
          wbgt_estimate: pred.wbgt_estimate,
        });
        setHeatRiskChecked(true);
      }
    } catch {
      alert("Could not connect to API server.\nMake sure the server is running: python api_server.py");
    }
    setHeatRiskLoading(false);
  };

  const riskColor = heatRisk?.risk_color || "#64748b";
  const riskLevel = heatRisk?.risk_level?.toLowerCase() || "";

  // ─── COMMERCIAL MODE ───────────────────────────────────────────────────────
  if (mode === "commercial") {
    return (
      <AppLayout>
        <div className="space-y-8">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Briefcase className="w-7 h-7 text-primary" />
              <div>
                <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Task Scheduler</h1>
                <p className="text-muted-foreground mt-1">
                  Manage outdoor tasks with optimal shade and heat protection · {period}
                </p>
              </div>
            </div>
            <Link
              to="/tasks"
              className="hidden sm:flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors shadow"
            >
              <Plus className="w-4 h-4" />
              Schedule Task
            </Link>
          </div>

          {/* Quick Stats */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Tasks Today</h3>
                <Briefcase className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">{tasks.length}</div>
              <p className="text-sm text-muted-foreground">
                {tasks.filter((t) => t.status === "scheduled").length} scheduled
              </p>
            </div>
            <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Avg. Shade Coverage</h3>
                <Sun className="w-5 h-5 text-primary" />
              </div>
              <div className="text-4xl font-bold text-primary mb-2">
                {Math.round(tasks.reduce((a, t) => a + t.shadePercentage, 0) / tasks.length)}%
              </div>
              <p className="text-sm text-muted-foreground">Across all tasks</p>
            </div>
            <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Worker Safety</h3>
                <CheckCircle className="w-5 h-5 text-green-600" />
              </div>
              <div className="text-4xl font-bold text-green-600 mb-2">Good</div>
              <p className="text-sm text-muted-foreground">All tasks within safe parameters</p>
            </div>
          </div>

          {/* Create Task CTA */}
          <Link
            to="/tasks"
            className="flex w-full bg-gradient-to-r from-primary to-accent text-primary-foreground py-4 rounded-2xl font-semibold hover:shadow-lg transition-all items-center justify-center gap-2 group"
          >
            <Plus className="w-5 h-5 group-hover:scale-110 transition-transform" />
            Find Optimal Time for New Task
          </Link>

          {/* Today's Tasks */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Today's Tasks</h2>
            </div>
            <div className="grid gap-4">
              {tasks.map((task) => (
                <div key={task.id} className="bg-card border border-border rounded-2xl p-6 hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h3 className="font-semibold text-foreground text-lg">{task.name}</h3>
                      <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1">
                        <Navigation2 className="w-3 h-3" /> {task.location}
                      </p>
                    </div>
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${task.shadePercentage >= 75 ? "bg-green-100 text-green-700" : task.shadePercentage >= 50 ? "bg-orange-100 text-orange-700" : "bg-red-100 text-red-700"}`}>
                      {task.shadePercentage}% shade
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-4 py-4 border-t border-border">
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
                        <p className="font-semibold text-foreground capitalize">{task.status}</p>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Heat Risk Check */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-card border border-border rounded-2xl shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-border bg-muted/30 flex items-center gap-2">
                <ShieldAlert className="w-5 h-5 text-primary" />
                <div>
                  <h2 className="text-base font-semibold text-foreground">Outdoor Heat Risk</h2>
                  <p className="text-xs text-muted-foreground">Dubai Downtown · {formatTime(currentMinutes)}</p>
                </div>
              </div>
              <div className="p-6">
                <button
                  onClick={checkHeatRisk}
                  disabled={heatRiskLoading}
                  className="w-full py-3 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white font-semibold text-sm transition-all disabled:opacity-50 shadow-md mb-4"
                >
                  {heatRiskLoading ? "⏳ Checking…" : "🌡️ Check Heat Risk Now"}
                </button>
                {!heatRiskChecked && !heatRiskLoading && (
                  <p className="text-center text-sm text-muted-foreground py-4">Click above to check real-time outdoor heat risk</p>
                )}
                {heatRiskChecked && heatRisk && (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between p-3 rounded-xl border" style={{ background: `${riskColor}10`, borderColor: `${riskColor}40` }}>
                      <div>
                        <div className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">Risk Level</div>
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
                        <div key={l} className="text-center p-2 rounded-xl bg-muted/60 border border-border">
                          <div className="text-xs text-muted-foreground mb-0.5">{l}</div>
                          <div className={`font-bold ${c}`}>{v}</div>
                        </div>
                      ))}
                    </div>
                    {heatRisk.safety_message && (
                      <div className="p-3 rounded-xl border text-sm" style={{ background: `${riskColor}08`, borderColor: `${riskColor}30`, color: riskColor }}>
                        💬 {heatRisk.safety_message}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Safety Guidelines */}
            <div className="bg-gradient-to-br from-primary/10 to-accent/10 border border-primary/30 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-4">
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
                  <li key={tip} className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 mt-0.5 shrink-0" />
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
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
