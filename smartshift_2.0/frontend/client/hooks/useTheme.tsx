import { useEffect, useState } from "react";

export type ThemeValue = "light" | "dark" | "system" | "contrast";

const STORAGE_KEY = "smartshift-theme";

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeValue>(() => {
    if (typeof window === "undefined") return "system";
    const stored = localStorage.getItem(STORAGE_KEY) as ThemeValue | null;
    if (stored && ["light", "dark", "system", "contrast"].includes(stored)) return stored;
    return "system";
  });

  const [systemTheme, setSystemTheme] = useState<"light" | "dark">(getSystemTheme);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setSystemTheme(getSystemTheme());
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, theme);
    const root = document.documentElement;
    root.classList.remove("dark", "contrast");

    let effective: "light" | "dark" = "light";
    if (theme === "system") {
      effective = systemTheme;
    } else if (theme === "dark" || theme === "light") {
      effective = theme;
    } else if (theme === "contrast") {
      effective = systemTheme;
      root.classList.add("contrast");
    }

    if (effective === "dark") {
      root.classList.add("dark");
    }
  }, [theme, systemTheme]);

  const setTheme = (value: ThemeValue) => setThemeState(value);

  const isDark =
    theme === "dark" || (theme === "system" && systemTheme === "dark") || (theme === "contrast" && systemTheme === "dark");

  return { theme, setTheme, isDark };
}
