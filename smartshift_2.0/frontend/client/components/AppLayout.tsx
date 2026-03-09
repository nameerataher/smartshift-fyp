import { Link } from "react-router-dom";
import { Sun, Map, CheckSquare, Settings, Briefcase, Navigation, LayoutDashboard } from "lucide-react";
import { cn } from "../lib/utils";
import { useLocation } from "react-router-dom";
import { useMode } from "@/hooks/useMode";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const location = useLocation();
  const { mode, setMode } = useMode();

  const isActive = (path: string) => location.pathname === path;

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    {
      path: "/map",
      label: mode === "commercial" ? "Task Map" : "Route Map",
      icon: Map,
    },
    {
      path: "/tasks",
      label: mode === "commercial" ? "Tasks" : "Saved Routes",
      icon: mode === "commercial" ? CheckSquare : Navigation,
    },
    { path: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border bg-card sticky top-0 z-50 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <Link to="/" className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-amber-400 flex items-center justify-center">
                <Sun className="w-6 h-6 text-primary-foreground" />
              </div>
              <span className="text-xl font-bold text-foreground hidden sm:block">
                SmartShift
              </span>
            </Link>

            {/* Mode Toggle */}
            <div className="hidden sm:flex items-center gap-2 bg-muted rounded-lg p-1">
              <button
                onClick={() => setMode("commercial")}
                className={cn(
                  "px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5",
                  mode === "commercial"
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Briefcase className="w-4 h-4" />
                <span className="hidden lg:inline">Commercial</span>
              </button>
              <button
                onClick={() => setMode("personal")}
                className={cn(
                  "px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5",
                  mode === "personal"
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Navigation className="w-4 h-4" />
                <span className="hidden lg:inline">Personal</span>
              </button>
            </div>

            {/* Navigation */}
            <nav className="flex items-center gap-1">
              {navItems.map(({ path, label, icon: Icon }) => (
                <Link
                  key={path}
                  to={path}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200",
                    isActive(path)
                      ? "bg-primary text-primary-foreground"
                      : "text-foreground hover:bg-muted"
                  )}
                >
                  <Icon className="w-5 h-5" />
                  <span className="hidden sm:inline text-sm font-medium">
                    {label}
                  </span>
                </Link>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
    </div>
  );
}
