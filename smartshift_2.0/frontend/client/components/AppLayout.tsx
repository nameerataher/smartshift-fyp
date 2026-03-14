import { Link, useNavigate } from "react-router-dom";
import { Sun, Map, CheckSquare, Settings, Briefcase, Navigation, LayoutDashboard, LogOut, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocation } from "react-router-dom";
import { useMode } from "@/hooks/useMode";
import { useAuth } from "@/hooks/useAuth";
import { ThemeSelect } from "@/components/ThemeSelect";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode, setMode } = useMode();
  const { user, logout } = useAuth();

  const isActive = (path: string) => location.pathname === path;

  const handleModeSwitch = (newMode: "commercial" | "personal") => {
    if (newMode === "personal" && mode === "commercial") {
      setMode("personal");
      navigate("/map");
      return;
    }
    setMode(newMode);
  };

  const { isPersonalUser } = useMode();

  const navItems = [
    { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    {
      path: "/map",
      label: isPersonalUser ? "Route Map" : mode === "commercial" ? "Task Map" : "Route Map",
      icon: Map,
    },
    ...(!isPersonalUser && mode === "commercial"
      ? [{ path: "/tasks", label: "Tasks", icon: CheckSquare }]
      : []),
    { path: "/settings", label: "Settings", icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main-content" className="skip-link bg-primary text-primary-foreground font-medium">
        Skip to content
      </a>
      <header className="border-b border-border bg-card sticky top-0 z-50 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between gap-4">
            <Link to="/" className="flex items-center gap-3 shrink-0">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-primary to-amber-400 flex items-center justify-center">
                <Sun className="w-6 h-6 text-primary-foreground" />
              </div>
              <span className="text-xl font-bold text-foreground hidden sm:block">SmartShift</span>
            </Link>

            {!isPersonalUser && (
              <div className="hidden sm:flex items-center gap-2 bg-muted rounded-lg p-1">
                <button
                  onClick={() => handleModeSwitch("commercial")}
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
                  onClick={() => handleModeSwitch("personal")}
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
            )}

            <div className="flex items-center gap-2 shrink-0">
              <ThemeSelect variant="compact" />
              <nav className="flex items-center gap-1" aria-label="Main navigation">
                {navItems.map(({ path, label, icon: Icon }) => (
                  <Link key={path} to={path}
                    className={cn(
                      "flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200",
                      isActive(path)
                        ? "bg-primary text-primary-foreground"
                        : "text-foreground hover:bg-muted"
                    )}>
                    <Icon className="w-5 h-5" />
                    <span className="hidden sm:inline text-sm font-medium">{label}</span>
                  </Link>
                ))}
              </nav>
              {user && (
                <div className="flex items-center gap-1 ml-2 border-l border-border pl-2">
                  <span className="hidden lg:inline text-xs text-muted-foreground">{user.display_name}</span>
                  <button onClick={() => { logout(); navigate("/"); }}
                    className="p-2 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
                    aria-label="Sign out"
                    title="Sign out">
                    <LogOut className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <main id="main-content" className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
