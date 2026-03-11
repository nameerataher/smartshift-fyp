import { useState, useRef, useEffect } from "react";
import { Sun, Moon, Monitor, Contrast } from "lucide-react";
import { useTheme, type ThemeValue } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

const OPTIONS: { value: ThemeValue; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
  { value: "contrast", label: "Contrast", icon: Contrast },
];

interface ThemeSelectProps {
  variant?: "compact" | "full";
  className?: string;
}

export function ThemeSelect({ variant = "compact", className }: ThemeSelectProps) {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, []);

  if (variant === "full") {
    return (
      <div className={cn("flex flex-wrap gap-2", className)}>
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setTheme(opt.value)}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all",
              theme === opt.value ? "bg-primary text-primary-foreground" : "bg-muted text-foreground hover:bg-muted/80"
            )}
            aria-label={`Set theme to ${opt.label}`}
            aria-pressed={theme === opt.value}>
            <opt.icon className="w-4 h-4" />
            {opt.label}
          </button>
        ))}
      </div>
    );
  }

  const current = OPTIONS.find((o) => o.value === theme) ?? OPTIONS[0];
  const Icon = current.icon;

  return (
    <div className={cn("relative", className)} ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="p-2 rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        aria-label={`Theme: ${current.label}. Click to change.`}
        aria-haspopup="listbox"
        aria-expanded={open}>
        <Icon className="w-4 h-4" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 py-1 bg-card border border-border rounded-lg shadow-lg z-50 min-w-[120px]"
          role="listbox"
          aria-label="Theme options">
          {OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                setTheme(opt.value);
                setOpen(false);
              }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                theme === opt.value ? "bg-primary/10 text-primary font-medium" : "text-foreground"
              )}
              role="option"
              aria-selected={theme === opt.value}>
              <opt.icon className="w-4 h-4 shrink-0" />
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
