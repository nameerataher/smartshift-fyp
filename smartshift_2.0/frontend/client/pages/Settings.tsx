import { AppLayout } from "@/components/AppLayout";
import { Settings as SettingsIcon, Bell, Shield, User, MapPin, Briefcase, Navigation } from "lucide-react";
import { useState } from "react";
import { useMode } from "@/hooks/useMode";

interface Setting {
  id: string;
  label: string;
  description: string;
  value: string | boolean;
  type: "toggle" | "select" | "text";
  options?: string[];
}

export default function SettingsPage() {
  const { mode, setMode } = useMode();

  const [settings, setSettings] = useState<Setting[]>([
    {
      id: "heat-alerts",
      label: "Heat Alerts",
      description: "Receive notifications when temperature exceeds threshold",
      value: true,
      type: "toggle",
    },
    {
      id: "uv-warnings",
      label: "UV Warnings",
      description: "Get alerts for high UV exposure levels",
      value: true,
      type: "toggle",
    },
    {
      id: "shift-reminders",
      label: "Shift Reminders",
      description: "Reminder notifications for upcoming shifts",
      value: true,
      type: "toggle",
    },
    {
      id: "temp-threshold",
      label: "Heat Alert Threshold",
      description: "Temperature level to trigger alerts (°C)",
      value: "40",
      type: "select",
      options: ["35", "38", "40", "42", "45"],
    },
    {
      id: "language",
      label: "Language",
      description: "Select your preferred language",
      value: "English",
      type: "select",
      options: ["English", "Arabic", "French", "German"],
    },
    {
      id: "organization",
      label: "Organization",
      description: "Your organization or team name",
      value: "Construction Co.",
      type: "text",
    },
    {
      id: "mapbox-token",
      label: "Mapbox API Token",
      description: "Override the default Mapbox access token for the map",
      value: "",
      type: "text",
    },
  ]);

  const handleToggle = (id: string) => {
    setSettings((prev) =>
      prev.map((s) => (s.id === id && s.type === "toggle" ? { ...s, value: !s.value } : s))
    );
  };

  const handleSelect = (id: string, value: string) => {
    setSettings((prev) => prev.map((s) => (s.id === id ? { ...s, value } : s)));
  };

  const handleText = (id: string, value: string) => {
    setSettings((prev) => prev.map((s) => (s.id === id ? { ...s, value } : s)));
  };

  const handleSave = () => {
    // Save Mapbox token to localStorage if provided
    const tokenSetting = settings.find((s) => s.id === "mapbox-token");
    if (tokenSetting && typeof tokenSetting.value === "string" && tokenSetting.value.trim()) {
      try { localStorage.setItem("smartshift:mapboxToken", tokenSetting.value.trim()); } catch {}
    }
    alert("Settings saved!");
  };

  return (
    <AppLayout>
      <div className="space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold text-foreground">Settings</h1>
          <p className="text-muted-foreground mt-2">
            Customize your SmartShift experience and preferences
          </p>
        </div>

        <div className="max-w-2xl space-y-6">
          {/* User Mode */}
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
                className={`flex items-center justify-center gap-2 p-4 rounded-xl border-2 transition-all ${
                  mode === "commercial"
                    ? "bg-primary/10 border-primary text-primary"
                    : "bg-background border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                <Briefcase className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-semibold text-sm">Commercial</div>
                  <div className="text-xs opacity-70">Team scheduling</div>
                </div>
              </button>
              <button
                onClick={() => setMode("personal")}
                className={`flex items-center justify-center gap-2 p-4 rounded-xl border-2 transition-all ${
                  mode === "personal"
                    ? "bg-primary/10 border-primary text-primary"
                    : "bg-background border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                <Navigation className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-semibold text-sm">Personal</div>
                  <div className="text-xs opacity-70">Route navigation</div>
                </div>
              </button>
            </div>
          </div>

          {/* Notifications */}
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <Bell className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Notifications</h2>
            </div>
            <div className="space-y-4">
              {settings.slice(0, 3).map((setting) => (
                <div key={setting.id} className="flex items-center justify-between p-4 hover:bg-muted/50 rounded-lg transition-colors">
                  <div className="flex-1">
                    <h3 className="font-medium text-foreground">{setting.label}</h3>
                    <p className="text-sm text-muted-foreground">{setting.description}</p>
                  </div>
                  <button
                    onClick={() => handleToggle(setting.id)}
                    className={`relative w-12 h-7 rounded-full transition-colors ${setting.value ? "bg-primary" : "bg-muted"}`}
                  >
                    <div className={`absolute top-1 left-1 w-5 h-5 bg-white rounded-full shadow transition-transform ${setting.value ? "translate-x-5" : "translate-x-0"}`} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Safety */}
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <Shield className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Safety Settings</h2>
            </div>
            {settings.slice(3, 4).map((setting) => (
              <div key={setting.id} className="p-4 hover:bg-muted/50 rounded-lg transition-colors">
                <h3 className="font-medium text-foreground mb-2">{setting.label}</h3>
                <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                <div className="flex gap-2 flex-wrap">
                  {setting.options?.map((option) => (
                    <button
                      key={option}
                      onClick={() => handleSelect(setting.id, option)}
                      className={`px-4 py-2 rounded-lg font-medium transition-all ${
                        setting.value === option
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-foreground hover:bg-muted/80"
                      }`}
                    >
                      {option}°C
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Map & API */}
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <MapPin className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Map & API</h2>
            </div>
            {settings.slice(6).map((setting) => (
              <div key={setting.id} className="p-4">
                <h3 className="font-medium text-foreground mb-1">{setting.label}</h3>
                <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                <input
                  type="text"
                  value={typeof setting.value === "string" ? setting.value : ""}
                  onChange={(e) => handleText(setting.id, e.target.value)}
                  placeholder="pk.eyJ1Ijoie..."
                  className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary placeholder-muted-foreground"
                />
              </div>
            ))}
          </div>

          {/* Preferences */}
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <SettingsIcon className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Preferences</h2>
            </div>
            <div className="space-y-4">
              {settings.slice(4, 6).map((setting) => (
                <div key={setting.id} className="p-4 hover:bg-muted/50 rounded-lg transition-colors">
                  <label className="block">
                    <h3 className="font-medium text-foreground mb-1">{setting.label}</h3>
                    <p className="text-sm text-muted-foreground mb-3">{setting.description}</p>
                    {setting.type === "select" && setting.options ? (
                      <select
                        value={setting.value as string}
                        onChange={(e) => handleSelect(setting.id, e.target.value)}
                        className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                      >
                        {setting.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={setting.value as string}
                        onChange={(e) => handleText(setting.id, e.target.value)}
                        className="w-full px-4 py-2 border border-border rounded-lg bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                      />
                    )}
                  </label>
                </div>
              ))}
            </div>
          </div>

          {/* Account */}
          <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <User className="w-5 h-5 text-primary" />
              <h2 className="text-xl font-semibold text-foreground">Account</h2>
            </div>
            <div className="space-y-4">
              <div className="p-4 bg-muted/30 rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Email</p>
                <p className="font-medium text-foreground">manager@constructionco.com</p>
              </div>
              <div className="p-4 bg-muted/30 rounded-lg">
                <p className="text-sm text-muted-foreground mb-1">Role</p>
                <p className="font-medium text-foreground">Site Manager</p>
              </div>
              <button className="w-full mt-4 px-6 py-3 border-2 border-red-300 text-red-600 rounded-lg font-semibold hover:bg-red-50 transition-colors">
                Sign Out
              </button>
            </div>
          </div>

          {/* Save */}
          <div className="flex gap-3">
            <button
              onClick={handleSave}
              className="flex-1 bg-primary text-primary-foreground py-3 rounded-lg font-semibold hover:bg-primary/90 transition-colors shadow-md"
            >
              Save Changes
            </button>
            <button
              onClick={() => window.location.reload()}
              className="flex-1 border-2 border-border text-foreground py-3 rounded-lg font-semibold hover:bg-muted transition-colors"
            >
              Reset to Defaults
            </button>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
