import "./global.css";
import "mapbox-gl/dist/mapbox-gl.css";

import { Toaster } from "@/components/ui/toaster";
import { createRoot } from "react-dom/client";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ModeProvider } from "./hooks/useMode";
import { AuthProvider } from "./hooks/useAuth";
import { useTheme } from "./hooks/useTheme";
import { useFontSize } from "./hooks/useFontSize";

function ThemeAndFontInitializer({ children }: { children: React.ReactNode }) {
  useTheme();
  useFontSize();
  return <>{children}</>;
}
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import Dashboard from "./pages/Dashboard";
import Map from "./pages/Map";
import { TasksGuard } from "./components/TasksGuard";
import { KeyboardShortcutsModal } from "./components/KeyboardShortcutsModal";
import Settings from "./pages/Settings";
import Login from "./pages/Login";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <AuthProvider>
        <ModeProvider>
          <Toaster />
          <Sonner />
          <ThemeAndFontInitializer>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<Index />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Login />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/map" element={<Map />} />
              <Route path="/tasks" element={<TasksGuard />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
            <KeyboardShortcutsModal />
          </BrowserRouter>
          </ThemeAndFontInitializer>
        </ModeProvider>
      </AuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

createRoot(document.getElementById("root")!).render(<App />);
