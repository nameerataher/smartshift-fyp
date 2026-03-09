import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AppLayout } from "@/components/AppLayout";
import { useMode } from "@/hooks/useMode";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "sonner";
import {
  Plus, Clock, MapPin, Calendar, Trash2, Pencil, CheckCircle,
  ExternalLink, Filter, RefreshCw, AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API_BASE = "http://localhost:8002";

interface Task {
  task_id: string;
  task_name: string;
  location_name: string;
  location_lat: number;
  location_lon: number;
  duration_minutes: number;
  hour_start: number;
  hour_end: number;
  date: string;
  status: "draft" | "scheduled" | "in-process" | "completed";
  created_at: string;
  recommendation?: {
    accepted_time_start: string;
    accepted_time_end: string;
    shade_percentage: number;
    shade_slot: string;
  };
}

const STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  draft: { bg: "bg-slate-100", text: "text-slate-700", label: "Draft" },
  scheduled: { bg: "bg-blue-100", text: "text-blue-700", label: "Scheduled" },
  "in-process": { bg: "bg-amber-100", text: "text-amber-700", label: "In Process" },
  completed: { bg: "bg-green-100", text: "text-green-700", label: "Completed" },
};

export default function Tasks() {
  const navigate = useNavigate();
  const { mode } = useMode();
  const { user } = useAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ task_name: string; date: string }>({ task_name: "", date: "" });

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (user?.user_id) headers["X-User-Id"] = user.user_id;
      const res = await fetch(`${API_BASE}/api/tasks`, { headers });
      const data = await res.json();
      if (data.success) setTasks(data.tasks || []);
    } catch {
      toast.error("Failed to load tasks. Make sure the API server is running.");
    }
    setLoading(false);
  };

  useEffect(() => { fetchTasks(); }, [user]);

  // Redirect personal mode away from tasks
  if (mode === "personal") {
    navigate("/map");
    return null;
  }

  const filteredTasks = tasks.filter((t) => filter === "all" || t.status === filter);

  const deleteTask = async (taskId: string) => {
    if (!confirm("Are you sure you want to delete this task?")) return;
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, { method: "DELETE" });
      if (res.ok) { toast.success("Task deleted"); fetchTasks(); }
      else toast.error("Failed to delete task");
    } catch { toast.error("Failed to delete task"); }
  };

  const markCompleted = async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}/complete`, { method: "POST" });
      if (res.ok) { toast.success("Task marked as completed!"); fetchTasks(); }
    } catch { toast.error("Failed to update task"); }
  };

  const startEdit = (task: Task) => {
    setEditingId(task.task_id);
    setEditForm({ task_name: task.task_name, date: task.date });
  };

  const saveEdit = async () => {
    if (!editingId) return;
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_name: editForm.task_name, date: editForm.date }),
      });
      if (res.ok) { toast.success("Task updated"); setEditingId(null); fetchTasks(); }
      else toast.error("Failed to update task");
    } catch { toast.error("Failed to update task"); }
  };

  const redirectToMapForReschedule = (task: Task) => {
    navigate(`/map?reschedule=${task.task_id}&lat=${task.location_lat}&lon=${task.location_lon}&name=${encodeURIComponent(task.task_name)}&date=${task.date}&duration=${task.duration_minutes}`);
  };

  const formatTimeWindow = (task: Task): string => {
    if (task.recommendation) return `${task.recommendation.accepted_time_start} – ${task.recommendation.accepted_time_end}`;
    return `${String(task.hour_start).padStart(2, "0")}:00 – ${String(task.hour_end).padStart(2, "0")}:00`;
  };

  return (
    <AppLayout>
      <div className="space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground">Tasks</h1>
            <p className="text-muted-foreground mt-1">Manage all scheduled outdoor tasks</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={fetchTasks}
              className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted">
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            <button onClick={() => navigate("/map?newTask=true")}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
              <Plus className="w-4 h-4" /> New Task
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2 border-b border-border pb-2">
          <Filter className="w-4 h-4 text-muted-foreground" />
          {["all", "scheduled", "in-process", "completed", "draft"].map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                filter === f ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              {f === "all" ? "All" : f === "in-process" ? "In Process" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>

        {loading && (
          <div className="text-center py-12">
            <RefreshCw className="w-8 h-8 text-primary animate-spin mx-auto mb-3" />
            <p className="text-muted-foreground">Loading tasks...</p>
          </div>
        )}

        {!loading && filteredTasks.length === 0 && (
          <div className="text-center py-12 rounded-2xl border border-dashed border-border">
            <AlertTriangle className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
            <p className="text-lg font-medium text-foreground mb-1">No tasks found</p>
            <p className="text-sm text-muted-foreground mb-4">Create a new task from the Task Map.</p>
            <button onClick={() => navigate("/map?newTask=true")}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">
              <Plus className="w-4 h-4" /> Create Task
            </button>
          </div>
        )}

        {!loading && filteredTasks.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredTasks.map((task) => {
              const statusStyle = STATUS_COLORS[task.status] || STATUS_COLORS.draft;
              const isEditing = editingId === task.task_id;

              return (
                <div key={task.task_id} className="rounded-2xl border border-border bg-card shadow-sm hover:shadow-md transition-shadow overflow-hidden">
                  {isEditing ? (
                    <div className="p-4 space-y-3">
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">Task Name</label>
                        <input type="text" value={editForm.task_name}
                          onChange={(e) => setEditForm((f) => ({ ...f, task_name: e.target.value }))}
                          className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm" />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-muted-foreground mb-1">Date</label>
                        <input type="date" value={editForm.date}
                          onChange={(e) => setEditForm((f) => ({ ...f, date: e.target.value }))}
                          className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm" />
                      </div>
                      <div className="opacity-50">
                        <label className="block text-xs font-medium text-muted-foreground mb-1">Location (read-only)</label>
                        <input type="text" disabled value={task.location_name || "—"}
                          className="w-full px-3 py-2 rounded-lg border border-border bg-muted/50 text-sm cursor-not-allowed" />
                      </div>
                      <div className="opacity-50">
                        <label className="block text-xs font-medium text-muted-foreground mb-1">Hours (read-only)</label>
                        <input type="text" disabled value={formatTimeWindow(task)}
                          className="w-full px-3 py-2 rounded-lg border border-border bg-muted/50 text-sm cursor-not-allowed" />
                      </div>
                      <div className="flex gap-2 pt-2">
                        <button onClick={saveEdit}
                          className="flex-1 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold">Save</button>
                        <button onClick={() => setEditingId(null)}
                          className="flex-1 py-2 rounded-lg border border-border text-sm font-medium">Cancel</button>
                      </div>
                      <button onClick={() => { setEditingId(null); redirectToMapForReschedule(task); }}
                        className="w-full py-2 rounded-lg border border-amber-400 bg-amber-50 text-amber-700 text-sm font-medium flex items-center justify-center gap-2">
                        <ExternalLink className="w-4 h-4" /> Reschedule on Map
                      </button>
                    </div>
                  ) : (
                    <>
                      <div className="p-4">
                        <div className="flex items-start justify-between gap-2 mb-3">
                          <h3 className="font-semibold text-foreground line-clamp-2">{task.task_name}</h3>
                          <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs font-medium", statusStyle.bg, statusStyle.text)}>
                            {statusStyle.label}
                          </span>
                        </div>
                        <div className="space-y-2 text-sm text-muted-foreground">
                          <div className="flex items-center gap-2">
                            <MapPin className="w-4 h-4 text-primary" />
                            <span className="truncate">{task.location_name || "—"}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Clock className="w-4 h-4 text-primary" />
                            <span>{formatTimeWindow(task)}</span>
                            <span className="text-xs">({task.duration_minutes} min)</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <Calendar className="w-4 h-4 text-primary" />
                            <span>{new Date(task.date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</span>
                          </div>
                          {task.recommendation && (
                            <div className="flex items-center gap-2 text-green-600">
                              <CheckCircle className="w-4 h-4" />
                              <span className="font-medium">{task.recommendation.shade_percentage}% shade</span>
                              <span className="text-xs">· {task.recommendation.shade_slot}</span>
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="border-t border-border px-4 py-3 flex items-center justify-between bg-muted/30">
                        <div className="flex items-center gap-1">
                          <button onClick={() => startEdit(task)}
                            className="p-2 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground" title="Edit">
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button onClick={() => deleteTask(task.task_id)}
                            className="p-2 rounded-lg hover:bg-red-100 text-muted-foreground hover:text-red-600" title="Delete">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                        {task.status !== "completed" && (
                          <button onClick={() => markCompleted(task.task_id)}
                            className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-green-500">
                            <CheckCircle className="w-3.5 h-3.5" /> Complete
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {!loading && tasks.length > 0 && (
          <div className="rounded-2xl border border-border bg-muted/30 p-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
              <div>
                <div className="text-2xl font-bold text-foreground">{tasks.length}</div>
                <div className="text-xs text-muted-foreground">Total Tasks</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-blue-600">{tasks.filter((t) => t.status === "scheduled").length}</div>
                <div className="text-xs text-muted-foreground">Scheduled</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-amber-600">{tasks.filter((t) => t.status === "in-process").length}</div>
                <div className="text-xs text-muted-foreground">In Process</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-green-600">{tasks.filter((t) => t.status === "completed").length}</div>
                <div className="text-xs text-muted-foreground">Completed</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
