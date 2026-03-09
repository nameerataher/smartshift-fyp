import { useState, useRef } from "react";
import { AppLayout } from "@/components/AppLayout";
import { getDubaiNow, formatTime } from "@/lib/sunCalculations";

const API_BASE = "http://localhost:8002";

const HOURS = Array.from({ length: 24 }, (_, i) => {
  const period = i < 12 ? "AM" : "PM";
  const h = i === 0 ? 12 : i > 12 ? i - 12 : i;
  return { value: i, label: `${h}:00 ${period}` };
});

interface ScheduleResult {
  bestStart: string;
  bestEnd: string;
  shadowPct: number;
  heatRiskLabel: string;
  heatRiskColor: string;
  comfortScore: number;
  reason?: string;
  area: string;
  alternatives: Alternative[];
  requestId: string | null;
}

interface Alternative {
  startTime: string;
  shadePct: number;
  heatRiskLabel: string;
  heatRiskColor: string;
  rawStartTime: string;
  rawEndTime?: string;
}

export default function Tasks() {
  const { dateStr: todayDate } = getDubaiNow();

  const [taskName, setTaskName] = useState("");
  const [taskLocation, setTaskLocation] = useState("");
  const [taskLocationCoords, setTaskLocationCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [duration, setDuration] = useState(60);
  const [startHour, setStartHour] = useState(6);
  const [endHour, setEndHour] = useState(18);
  const [date, setDate] = useState(todayDate);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScheduleResult | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [locationSearchVal, setLocationSearchVal] = useState("");
  const [geoSuggestions, setGeoSuggestions] = useState<{ place_name: string; center: [number, number] }[]>([]);
  const geoTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Geocode search for task location
  const handleGeoSearch = (val: string) => {
    setLocationSearchVal(val);
    if (geoTimeoutRef.current) clearTimeout(geoTimeoutRef.current);
    if (val.length < 2) { setGeoSuggestions([]); return; }
    geoTimeoutRef.current = setTimeout(async () => {
      try {
        const MAPBOX_TOKEN = "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9.WI13BJqDyOu6G38-YP6hog";
        const res = await fetch(
          `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(val)}.json?access_token=${MAPBOX_TOKEN}&proximity=55.2708,25.2048&types=poi,address,place&limit=5`
        );
        const data = await res.json();
        setGeoSuggestions(data.features || []);
      } catch {}
    }, 300);
  };

  const selectGeoSuggestion = (s: { place_name: string; center: [number, number] }) => {
    setTaskLocation(s.place_name);
    setTaskLocationCoords({ lat: s.center[1], lng: s.center[0] });
    setLocationSearchVal("");
    setGeoSuggestions([]);
  };

  // GPS location
  const useGPS = () => {
    if (!navigator.geolocation) { alert("GPS not available in your browser."); return; }
    setGpsLoading(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        setTaskLocationCoords({ lat: latitude, lng: longitude });
        setTaskLocation(`${latitude.toFixed(4)}°N, ${longitude.toFixed(4)}°E`);
        setGpsLoading(false);
      },
      () => {
        alert("Could not get GPS location.");
        setGpsLoading(false);
      }
    );
  };

  // Find optimal schedule
  const findOptimalSchedule = async () => {
    setLoading(true);
    setResult(null);
    setAccepted(false);
    try {
      const location = taskLocationCoords || { lat: 25.2048, lng: 55.2708 };
      const payload = {
        task_name: taskName || "outdoor task",
        task_duration_minutes: duration,
        date,
        start_hour: startHour,
        end_hour: endHour,
        recommendation_count: 5,
        rank_by: "shade",
        work_zone: {
          zone_id: `ui_zone_${Date.now()}`,
          name: taskLocation || "selected work zone",
          lat: location.lat,
          lon: location.lng,
          radius: 50,
          is_facade: false,
          zone_type: "general",
        },
      };
      const res = await fetch(`${API_BASE}/api/v2/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.error || "Scheduling failed");

      const rec = data.recommendation || {};
      const isV2 = !!rec.best_schedule;
      const best = isV2 ? rec.best_schedule : rec;

      const bestStart = isV2
        ? new Date(best.start_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : best.best_start_time;
      const bestEnd = isV2
        ? new Date(best.end_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : best.end_time;

      const comfortScore = isV2 ? Math.round((best.comfort_score || 0) * 100) : Math.round((rec.quality_score || 0));
      const heatRiskPct = (isV2 ? (best.heat_risk_score || 0) : (rec.heat_risk_score || 0)) * 100;
      const heatRiskLabel = heatRiskPct <= 30 ? "LOW" : heatRiskPct <= 60 ? "MEDIUM" : "HIGH";
      const heatRiskColor = heatRiskLabel === "LOW" ? "#22c55e" : heatRiskLabel === "MEDIUM" ? "#f59e0b" : "#ef4444";
      const shadowPct = isV2 ? Math.round(best.shadow_percentage || 0) : Math.round(rec.shade_percentage || 0);
      const area = (rec.work_zone?.name) || taskLocation || "map center";
      const reason = isV2 ? rec.recommendation_reason : undefined;

      const rawAlts = (isV2 ? rec.alternatives : data.alternatives) || [];
      const alternatives: Alternative[] = rawAlts.slice(0, 4).map((alt: Record<string, unknown>) => {
        const altHeatPct = ((alt.heat_risk_score as number) || 0) * 100;
        const altLabel = altHeatPct <= 30 ? "LOW" : altHeatPct <= 60 ? "MED" : "HIGH";
        const altColor = altLabel === "LOW" ? "#22c55e" : altLabel === "MED" ? "#f59e0b" : "#ef4444";
        const altStart = isV2
          ? new Date(alt.start_time as string).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
          : (alt.start_time as string);
        const altShade = isV2 ? Math.round((alt.shadow_percentage as number) || 0) : Math.round((alt.shade_percentage as number) || 0);
        return { startTime: altStart, shadePct: altShade, heatRiskLabel: altLabel, heatRiskColor: altColor, rawStartTime: alt.start_time as string, rawEndTime: alt.end_time as string };
      });

      setResult({
        bestStart,
        bestEnd,
        shadowPct,
        heatRiskLabel,
        heatRiskColor,
        comfortScore,
        reason,
        area,
        alternatives,
        requestId: data.request_id || null,
      });
    } catch (err) {
      alert(`Scheduling failed: ${(err as Error).message}\n\nMake sure the server is running: python api_server.py`);
    }
    setLoading(false);
  };

  // Send feedback
  const sendFeedback = async (action: "accept" | "reject", startTime?: string, endTime?: string) => {
    if (!result?.requestId) return;
    try {
      await fetch(`${API_BASE}/api/schedule/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: result.requestId,
          action,
          chosen_start: startTime || null,
          chosen_end: endTime || null,
          note: "",
        }),
      });
    } catch {}
  };

  const acceptSchedule = async (startTime?: string, endTime?: string) => {
    await sendFeedback("accept", startTime, endTime);
    setAccepted(true);
  };

  const rejectSchedule = async () => {
    await sendFeedback("reject");
    setResult(null);
  };

  const comfortColor = result
    ? result.comfortScore >= 70 ? "#22c55e" : result.comfortScore >= 50 ? "#f59e0b" : "#ef4444"
    : "#22c55e";

  return (
    <AppLayout>
      <div className="space-y-8">
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Tasks</h1>
          <p className="text-muted-foreground mt-2">
            Schedule outdoor tasks at the optimal time using shadow coverage and heat risk analysis
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Schedule Form */}
          <div className="bg-card border border-border rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-border bg-muted/30">
              <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                🕐 Schedule Outdoor Task
              </h2>
              <p className="text-sm text-muted-foreground mt-0.5">
                Find the best time window considering shade and heat risk
              </p>
            </div>

            <div className="p-6 space-y-5">
              {/* Task name */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">Task Name</label>
                <input
                  type="text"
                  value={taskName}
                  onChange={(e) => setTaskName(e.target.value)}
                  placeholder="e.g., facade cleaning, rooftop inspection"
                  className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-foreground text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                />
              </div>

              {/* Location */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">📍 Task Location</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={taskLocation}
                    readOnly
                    placeholder="Location (search below or use GPS)"
                    className="flex-1 px-3 py-2.5 rounded-lg border border-border bg-muted text-foreground text-sm placeholder-muted-foreground"
                  />
                  <button
                    onClick={useGPS}
                    disabled={gpsLoading}
                    className="px-3 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 shrink-0"
                    title="Use GPS location"
                  >
                    {gpsLoading ? "…" : "📡 GPS"}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type="text"
                    value={locationSearchVal}
                    onChange={(e) => handleGeoSearch(e.target.value)}
                    placeholder="Search building or area name"
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                  />
                  {geoSuggestions.length > 0 && (
                    <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border rounded-lg shadow-xl z-50 max-h-48 overflow-y-auto">
                      {geoSuggestions.map((s, i) => (
                        <button
                          key={i}
                          onClick={() => selectGeoSuggestion(s)}
                          className="w-full text-left px-3 py-2.5 text-sm text-foreground hover:bg-muted transition-colors border-b border-border last:border-0"
                        >
                          {s.place_name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {taskLocationCoords && (
                  <p className="text-xs text-muted-foreground mt-1">
                    📍 {taskLocationCoords.lat.toFixed(4)}°N, {taskLocationCoords.lng.toFixed(4)}°E
                  </p>
                )}
              </div>

              {/* Duration */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">
                  Duration: <span className="text-primary font-bold">{duration} minutes</span>
                </label>
                <input
                  type="range"
                  min={15}
                  max={480}
                  step={15}
                  value={duration}
                  onChange={(e) => setDuration(parseInt(e.target.value))}
                  className="w-full accent-primary h-2 cursor-pointer"
                />
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>15 min</span>
                  <span>2 hr</span>
                  <span>4 hr</span>
                  <span>8 hr</span>
                </div>
              </div>

              {/* Date */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">Date</label>
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                />
              </div>

              {/* Working hours */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-1.5">Working Hours Window</label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">From</label>
                    <select
                      value={startHour}
                      onChange={(e) => setStartHour(parseInt(e.target.value))}
                      className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                    >
                      {HOURS.map(({ value, label }) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">To</label>
                    <select
                      value={endHour}
                      onChange={(e) => setEndHour(parseInt(e.target.value))}
                      className="w-full px-3 py-2.5 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                    >
                      {HOURS.map(({ value, label }) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <button
                onClick={findOptimalSchedule}
                disabled={loading}
                className="w-full py-3 rounded-xl bg-gradient-to-r from-green-600 to-emerald-500 hover:from-green-500 hover:to-emerald-400 text-white font-semibold text-sm transition-all disabled:opacity-50 shadow-md"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="animate-spin">⏳</span> Analyzing shadow & heat risk…
                  </span>
                ) : (
                  "🕐 Find Optimal Time (Shadow + Heat)"
                )}
              </button>
            </div>
          </div>

          {/* Result Panel */}
          <div className="bg-card border border-border rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-border bg-muted/30">
              <h2 className="text-lg font-semibold text-foreground">📊 Recommendation</h2>
              <p className="text-sm text-muted-foreground mt-0.5">
                AI-optimized scheduling based on real-time conditions
              </p>
            </div>

            {!result && !loading && (
              <div className="p-12 flex flex-col items-center justify-center text-center min-h-64">
                <div className="text-5xl mb-4">🕐</div>
                <p className="text-muted-foreground text-sm max-w-xs">
                  Fill in the task details and click "Find Optimal Time" to get an AI-powered schedule recommendation
                </p>
              </div>
            )}

            {loading && (
              <div className="p-12 flex flex-col items-center justify-center text-center min-h-64">
                <div className="text-4xl mb-4 animate-spin">⏳</div>
                <p className="text-muted-foreground text-sm">
                  Analyzing shadow coverage and heat risk…
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  📍 {taskLocationCoords ? `${taskLocationCoords.lat.toFixed(4)}, ${taskLocationCoords.lng.toFixed(4)}` : "Map center"} ·
                  ⏱ {startHour}:00–{endHour}:00 window
                </p>
              </div>
            )}

            {result && !accepted && (
              <div className="p-6 space-y-5">
                {/* Best time */}
                <div className="rounded-xl bg-green-50 border border-green-200 p-4">
                  <div className="text-xs font-semibold text-green-700 mb-2">✓ Recommended Schedule</div>
                  <div className="text-2xl font-bold text-green-800">
                    ⏰ {result.bestStart} – {result.bestEnd}
                  </div>
                  {result.area && (
                    <div className="text-xs text-green-600 mt-1">📍 {result.area}</div>
                  )}
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-3">
                  <div className="text-center p-3 rounded-xl bg-muted/60 border border-border">
                    <div className="text-xs text-muted-foreground mb-1">SHADOW</div>
                    <div className="text-xl font-bold text-foreground">{result.shadowPct}%</div>
                  </div>
                  <div className="text-center p-3 rounded-xl bg-muted/60 border border-border">
                    <div className="text-xs text-muted-foreground mb-1">HEAT RISK</div>
                    <div className="text-lg font-bold" style={{ color: result.heatRiskColor }}>
                      {result.heatRiskLabel}
                    </div>
                  </div>
                  <div className="text-center p-3 rounded-xl bg-muted/60 border border-border">
                    <div className="text-xs text-muted-foreground mb-1">COMFORT</div>
                    <div className="text-xl font-bold" style={{ color: comfortColor }}>
                      {result.comfortScore}/100
                    </div>
                  </div>
                </div>

                {result.reason && (
                  <p className="text-sm text-muted-foreground bg-muted/40 rounded-lg px-3 py-2">
                    💡 {result.reason}
                  </p>
                )}

                {/* Accept / Reject */}
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => acceptSchedule()}
                    className="py-2.5 rounded-xl bg-green-600 hover:bg-green-500 text-white font-semibold text-sm transition-colors"
                  >
                    ✓ Accept
                  </button>
                  <button
                    onClick={rejectSchedule}
                    className="py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-white font-semibold text-sm transition-colors"
                  >
                    ✕ Reject
                  </button>
                </div>

                {/* Alternatives */}
                {result.alternatives.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                      📅 Alternative Times
                    </div>
                    <div className="space-y-2">
                      {result.alternatives.map((alt, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-3 rounded-xl bg-muted/40 border border-border hover:bg-muted/70 transition-colors"
                        >
                          <div>
                            <div className="text-sm font-semibold text-foreground">{alt.startTime}</div>
                            <div className="text-xs text-muted-foreground">
                              🌥️ {alt.shadePct}% shade ·{" "}
                              <span style={{ color: alt.heatRiskColor }}>🌡️ {alt.heatRiskLabel}</span>
                            </div>
                          </div>
                          <button
                            onClick={() => acceptSchedule(alt.rawStartTime, alt.rawEndTime)}
                            className="px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-medium transition-colors"
                          >
                            ✓ Accept
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {result && accepted && (
              <div className="p-12 flex flex-col items-center justify-center text-center min-h-64">
                <div className="text-5xl mb-4">✅</div>
                <div className="text-xl font-bold text-foreground mb-2">Schedule Accepted!</div>
                <div className="text-lg text-primary font-semibold mb-1">
                  {result.bestStart} – {result.bestEnd}
                </div>
                <p className="text-sm text-muted-foreground mt-2">Saved to your task history</p>
                <button
                  onClick={() => { setResult(null); setAccepted(false); }}
                  className="mt-4 px-4 py-2 rounded-lg bg-muted hover:bg-muted/80 text-foreground text-sm transition-colors"
                >
                  Schedule Another Task
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Info section */}
        <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground mb-3">How It Works</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm text-muted-foreground">
            <div className="flex gap-3">
              <span className="text-2xl shrink-0">🌥️</span>
              <div>
                <div className="font-medium text-foreground mb-0.5">Shadow Analysis</div>
                Calculates real shadow coverage using NOAA solar position algorithms for your exact location and date
              </div>
            </div>
            <div className="flex gap-3">
              <span className="text-2xl shrink-0">🌡️</span>
              <div>
                <div className="font-medium text-foreground mb-0.5">Heat Risk Model</div>
                Fetches live weather from Open-Meteo and runs an ML model to predict heat risk and WBGT
              </div>
            </div>
            <div className="flex gap-3">
              <span className="text-2xl shrink-0">⏰</span>
              <div>
                <div className="font-medium text-foreground mb-0.5">Optimal Timing</div>
                Ranks every time slot in your window by combined comfort score and shows the best options
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
