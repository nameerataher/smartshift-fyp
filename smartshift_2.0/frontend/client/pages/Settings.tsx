import { AppLayout } from "@/components/AppLayout";
import { Settings as SettingsIcon, Bell, Shield, User, MapPin, Briefcase, Navigation, ChevronLeft, ChevronRight, Globe, Palette, Accessibility, Keyboard, SkipForward, Landmark, Focus } from "lucide-react";
import { useState } from "react";
import { useMode } from "@/hooks/useMode";
import { useAuth } from "@/hooks/useAuth";
import { useTheme, type ThemeValue } from "@/hooks/useTheme";
import { useFontSize, type FontSizeValue } from "@/hooks/useFontSize";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";

interface Setting {
  id: string;
  label: string;
  description: string;
  value: string | boolean;
  type: "toggle" | "select" | "text";
  options?: string[];
}

const SECTIONS = [
  { id: "mode", label: "User Mode", icon: Briefcase },
  { id: "appearance", label: "Appearance & Accessibility", icon: Accessibility },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "safety", label: "Safety", icon: Shield },
  { id: "preferences", label: "Preferences", icon: Globe },
  { id: "map", label: "Map & API", icon: MapPin },
  { id: "account", label: "Account", icon: User },
];

const THEME_OPTIONS: { value: ThemeValue; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
  { value: "contrast", label: "Contrast" },
];

const FONT_SIZE_OPTIONS: { value: FontSizeValue; label: string; pct: string }[] = [
  { value: "small", label: "Small", pct: "90%" },
  { value: "default", label: "Default", pct: "100%" },
  { value: "large", label: "Large", pct: "115%" },
  { value: "xlarge", label: "Extra Large", pct: "130%" },
];

export default function SettingsPage() {
  const { mode, setMode, isPersonalUser } = useMode();
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { fontSize, setFontSize } = useFontSize();
  const navigate = useNavigate();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const visibleSections = SECTIONS.filter((s) => !(isPersonalUser && s.id === "mode"));
  const [activeSection, setActiveSection] = useState(visibleSections[0]?.id ?? "notifications");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [settings, setSettings] = useState<Setting[]>([
    { id: "heat-alerts", label: "Heat Alerts", description: "Receive notifications when temperature exceeds threshold", value: true, type: "toggle" },
    { id: "uv-warnings", label: "UV Warnings", description: "Get alerts for high UV exposure levels", value: true, type: "toggle" },
    { id: "shift-reminders", label: "Shift Reminders", description: "Reminder notifications for upcoming shifts", value: true, type: "toggle" },
    { id: "temp-threshold", label: "Heat Alert Threshold", description: "Temperature level to trigger alerts (°C)", value: "40", type: "select", options: ["35", "38", "40", "42", "45"] },
    { id: "language", label: "Language", description: "Select your preferred language", value: "English", type: "select", options: ["English", "Arabic", "French", "German"] },
    { id: "organization", label: "Organization", description: "Your organization or team name", value: user?.organization || "Construction Co.", type: "text" },
    { id: "mapbox-token", label: "Mapbox API Token", description: "Override the default Mapbox access token for the map", value: "", type: "text" },
  ]);

  const handleToggle = (id: string) => {
    setSettings((prev) => prev.map((s) => (s.id === id && s.type === "toggle" ? { ...s, value: !s.value } : s)));
  };
  const handleSelect = (id: string, value: string) => {
    setSettings((prev) => prev.map((s) => (s.id === id ? { ...s, value } : s)));
  };
  const handleText = (id: string, value: string) => {
    setSettings((prev) => prev.map((s) => (s.id === id ? { ...s, value } : s)));
  };
  const handleSave = () => {
    const tokenSetting = settings.find((s) => s.id === "mapbox-token");
    if (tokenSetting && typeof tokenSetting.value === "string" && tokenSetting.value.trim()) {
      try { localStorage.setItem("smartshift:mapboxToken", tokenSetting.value.trim()); } catch {}
    }
    alert("Settings saved!");
  };

  const displaySettings = isPersonalUser
    ? settings.filter((s) => !["shift-reminders", "organization"].includes(s.id))
    : settings;

  const renderSection = () => {
    switch (activeSection) {
      case "mode":
        if (isPersonalUser) return null;
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <SettingsIcon className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">User Mode</h2>
            </div>
            <p className="text-sm text-muted-foreground mb-4">
              Switch between Commercial (task management for teams) and Personal (route navigation for individuals).
            </p>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setMode("commercial")}
                className={cn(
                  "flex items-center justify-center gap-2 p-4 rounded-xl border-2 transition-all",
                  mode === "commercial" ? "bg-primary/10 border-primary text-primary" : "bg-background border-border text-muted-foreground hover:bg-muted"
                )}>
                <Briefcase className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-semibold text-sm">Commercial</div>
                  <div className="text-xs opacity-70">Team scheduling</div>
                </div>
              </button>
              <button
                onClick={() => setMode("personal")}
                className={cn(
                  "flex items-center justify-center gap-2 p-4 rounded-xl border-2 transition-all",
                  mode === "personal" ? "bg-primary/10 border-primary text-primary" : "bg-background border-border text-muted-foreground hover:bg-muted"
                )}>
                <Navigation className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-semibold text-sm">Personal</div>
                  <div className="text-xs opacity-70">Route navigation</div>
                </div>
              </button>
            </div>
          </div>
        );
      case "appearance":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-6">
            <div className="flex items-center gap-3 mb-6">
              <Accessibility className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Appearance & Accessibility</h2>
            </div>

            {/* Theme */}
            <div>
              <h3 className="font-medium text-foreground mb-1">Theme</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Choose how SmartShift looks. Light and Dark follow your preference; Contrast increases contrast for easier reading.
              </p>
              <div className="flex flex-wrap gap-2">
                {THEME_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setTheme(opt.value)}
                    className={cn(
                      "px-4 py-2 rounded-lg font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      theme === opt.value ? "bg-primary text-primary-foreground" : "bg-muted text-foreground hover:bg-muted/80"
                    )}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Font size */}
            <div>
              <h3 className="font-medium text-foreground mb-1">Font size</h3>
              <p className="text-sm text-muted-foreground mb-3">
                Adjust text size across the app. Larger sizes can help reduce eye strain and improve readability.
              </p>
              <div className="flex flex-wrap gap-2">
                {FONT_SIZE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setFontSize(opt.value)}
                    className={cn(
                      "px-4 py-2 rounded-lg font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      fontSize === opt.value ? "bg-primary text-primary-foreground" : "bg-muted text-foreground hover:bg-muted/80"
                    )}>
                    {opt.label} ({opt.pct})
                  </button>
                ))}
              </div>
            </div>

            {/* Keyboard shortcuts */}
            <div className="p-4 rounded-xl border border-border bg-muted/30">
              <div className="flex items-center gap-2 mb-2">
                <Keyboard className="w-4 h-4 text-primary" />
                <h3 className="font-medium text-foreground">Keyboard shortcuts</h3>
              </div>
              <p className="text-sm text-muted-foreground mb-3">
                SmartShift supports full keyboard navigation. Press Tab to move between elements, Enter/Space to activate. Dialogs close with Escape. Press ? to view all shortcuts.
              </p>
              <button
                onClick={() => setShortcutsOpen(true)}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                View shortcuts
              </button>
            </div>

            {/* Skip to content */}
            <div className="p-4 rounded-xl border border-border bg-muted/30">
              <div className="flex items-center gap-2 mb-2">
                <SkipForward className="w-4 h-4 text-primary" />
                <h3 className="font-medium text-foreground">Skip to content</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                When using the keyboard, the first Tab takes you to a &quot;Skip to content&quot; link that jumps past the navigation to the main content.
              </p>
            </div>

            {/* Semantic landmarks */}
            <div className="p-4 rounded-xl border border-border bg-muted/30">
              <div className="flex items-center gap-2 mb-2">
                <Landmark className="w-4 h-4 text-primary" />
                <h3 className="font-medium text-foreground">Semantic landmarks</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                The app uses landmarks (header, navigation, main content) so screen readers can jump between sections quickly.
              </p>
            </div>

            {/* Focus management */}
            <div className="p-4 rounded-xl border border-border bg-muted/30">
              <div className="flex items-center gap-2 mb-2">
                <Focus className="w-4 h-4 text-primary" />
                <h3 className="font-medium text-foreground">Focus management</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                When you open a dialog or panel, focus stays inside it until you close it. Focus is always visible with a clear ring around the active element.
              </p>
            </div>

            {shortcutsOpen && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShortcutsOpen(false)}>
                <div
                  className="bg-card border border-border rounded-2xl p-6 max-w-md w-full mx-4 shadow-xl"
                  onClick={(e) => e.stopPropagation()}
                  role="dialog"
                  aria-labelledby="shortcuts-title"
                  aria-modal="true">
                  <h2 id="shortcuts-title" className="text-xl font-semibold text-foreground mb-4">Keyboard shortcuts</h2>
                  <ul className="space-y-2 text-sm text-muted-foreground">
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">?</kbd> — View shortcuts</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Tab</kbd> — Move between elements</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Enter</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Space</kbd> — Activate</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">Escape</kbd> — Close dialog</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">d</kbd> — Go to Dashboard</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">m</kbd> — Go to Map</li>
                    <li><kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">g</kbd> then <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-foreground">s</kbd> — Go to Settings</li>
                  </ul>
                  <button
                    onClick={() => setShortcutsOpen(false)}
                    className="mt-4 w-full py-2 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      case "notifications":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <Bell className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Notifications</h2>
            </div>
            <div className="space-y-4">
              {displaySettings.filter((s) => ["heat-alerts", "uv-warnings", "shift-reminders"].includes(s.id)).map((setting) => (
                <div key={setting.id} className="flex items-center justify-between p-4 hover:bg-muted/50 rounded-lg transition-colors">
                  <div className="flex-1">
                    <h3 className="font-medium text-foreground">{setting.label}</h3>
                    <p className="text-sm text-muted-foreground">{setting.description}</p>
                  </div>
                  <button
                    onClick={() => handleToggle(setting.id)}
                    className={`relative w-12 h-7 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${setting.value ? "bg-primary" : "bg-muted"}`}
                    aria-label={setting.value ? `Disable ${setting.label}` : `Enable ${setting.label}`}>
                    <div className={`absolute top-1 left-1 w-5 h-5 bg-white rounded-full shadow transition-transform ${setting.value ? "translate-x-5" : "translate-x-0"}`} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        );
      case "safety":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <Shield className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Safety Settings</h2>
            </div>
            {displaySettings.filter((s) => s.id === "temp-threshold").map((setting) => (
              <div key={setting.id} className="p-4 hover:bg-muted/50 rounded-lg transition-colors">
                <h3 className="font-medium text-foreground mb-2">{setting.label}</h3>
                <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                <div className="flex gap-2 flex-wrap">
                  {setting.options?.map((option) => (
                    <button key={option} onClick={() => handleSelect(setting.id, option)}
                      className={`px-4 py-2 rounded-lg font-medium transition-all ${setting.value === option ? "bg-primary text-primary-foreground" : "bg-muted text-foreground hover:bg-muted/80"}`}>
                      {option}°C
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );
      case "preferences":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <Globe className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Preferences</h2>
            </div>
            <div className="space-y-4">
              {displaySettings.filter((s) => ["language", "organization"].includes(s.id)).map((setting) => (
                <div key={setting.id} className="p-4 hover:bg-muted/50 rounded-lg transition-colors">
                  <label className="block">
                    <h3 className="font-medium text-foreground mb-1">{setting.label}</h3>
                    <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                    {setting.type === "select" && setting.options ? (
                      <select value={setting.value as string} onChange={(e) => handleSelect(setting.id, e.target.value)}
                        className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary">
                        {setting.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input type="text" value={setting.value as string} onChange={(e) => handleText(setting.id, e.target.value)}
                        className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary" />
                    )}
                  </label>
                </div>
              ))}
            </div>
          </div>
        );
      case "map":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <MapPin className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Map & API</h2>
            </div>
            {displaySettings.filter((s) => s.id === "mapbox-token").map((setting) => (
              <div key={setting.id} className="p-4">
                <h3 className="font-medium text-foreground mb-1">{setting.label}</h3>
                <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                <input type="text" value={typeof setting.value === "string" ? setting.value : ""}
                  onChange={(e) => handleText(setting.id, e.target.value)} placeholder="pk.eyJ1Ijoie..."
                  className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary placeholder-muted-foreground" />
              </div>
            ))}
          </div>
        );
      case "account":
        return (
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <User className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Account</h2>
            </div>

            {/* User profile card */}
            <div className="mb-6 p-5 rounded-xl border border-border bg-gradient-to-br from-primary/5 to-muted/30">
              <div className="flex items-center gap-4">
                <div
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-primary text-lg font-semibold text-primary-foreground"
                  aria-hidden="true">
                  {user?.display_name
                    ? user.display_name
                        .split(/\s+/)
                        .map((s) => s[0])
                        .join("")
                        .slice(0, 2)
                        .toUpperCase()
                    : "?"}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-foreground truncate">{user?.display_name || "Guest"}</h3>
                  <p className="text-sm text-muted-foreground truncate">{user?.email || "Not signed in"}</p>
                  <p className="mt-0.5 text-xs font-medium text-primary capitalize">{user?.user_type || "Personal"} account</p>
                </div>
              </div>
            </div>

            <p className="text-sm font-medium text-muted-foreground mb-2">Account details</p>
            <div className="space-y-3">
              <div className="p-4 bg-muted/30 rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Email</p>
                <p className="font-medium text-foreground">{user?.email || "Not signed in"}</p>
              </div>
              <div className="p-4 bg-muted/30 rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Display name</p>
                <p className="font-medium text-foreground">{user?.display_name || "Guest"}</p>
              </div>
              <div className="p-4 bg-muted/30 rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Account type</p>
                <p className="font-medium text-foreground capitalize">{user?.user_type || "Personal"}</p>
              </div>
              {user?.organization && (
                <div className="p-4 bg-muted/30 rounded-lg">
                  <p className="text-sm text-muted-foreground mb-1">Organization</p>
                  <p className="font-medium text-foreground">{user.organization}</p>
                </div>
              )}
              {user ? (
                <button
                  onClick={() => { logout(); navigate("/"); }}
                  className="w-full mt-2 px-6 py-3 border-2 border-red-300 text-red-600 rounded-xl font-semibold hover:bg-red-500/10 dark:hover:bg-red-500/20 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                  Sign out
                </button>
              ) : (
                <button
                  onClick={() => navigate("/login")}
                  className="w-full mt-2 px-6 py-3 bg-primary text-primary-foreground rounded-xl font-semibold hover:bg-primary/90 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                  Sign in
                </button>
              )}
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <AppLayout>
      <div className="flex flex-col sm:flex-row gap-6 min-w-0">
        {/* Left sidebar */}
        <div className={cn(
          "shrink-0 transition-all duration-300",
          sidebarCollapsed ? "w-14" : "w-full sm:w-56"
        )}>
          <div className="sticky top-24 space-y-1">
            <button onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs font-medium text-muted-foreground hover:bg-muted mb-2"
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
              {!sidebarCollapsed && <span>Collapse</span>}
            </button>
            {visibleSections.map(({ id, label, icon: Icon }) => (
              <button key={id} onClick={() => setActiveSection(id)}
                className={cn(
                  "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium transition-all",
                  activeSection === id
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
                title={sidebarCollapsed ? label : undefined}>
                <Icon className="w-5 h-5 shrink-0" />
                {!sidebarCollapsed && <span>{label}</span>}
              </button>
            ))}
          </div>
        </div>

        {/* Right content */}
        <div className="flex-1 min-w-0 max-w-2xl space-y-6">
          <div>
            <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Settings</h1>
            <p className="text-muted-foreground mt-2">Customize your SmartShift experience</p>
          </div>

          {renderSection()}

          <div className="flex gap-3">
            <button
              onClick={handleSave}
              className="flex-1 bg-primary text-primary-foreground py-3 rounded-lg font-semibold hover:bg-primary/90 transition-colors shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              Save changes
            </button>
            <button
              onClick={() => window.location.reload()}
              className="flex-1 border-2 border-border text-foreground py-3 rounded-lg font-semibold hover:bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
              Reset to defaults
            </button>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
