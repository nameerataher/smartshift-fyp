import { useEffect, useState } from "react";

export type FontSizeValue = "small" | "default" | "large" | "xlarge";

const STORAGE_KEY = "smartshift-font-size";

const SCALE_MAP: Record<FontSizeValue, number> = {
  small: 0.9,
  default: 1,
  large: 1.15,
  xlarge: 1.3,
};

export function useFontSize() {
  const [fontSize, setFontSizeState] = useState<FontSizeValue>(() => {
    if (typeof window === "undefined") return "default";
    const stored = localStorage.getItem(STORAGE_KEY) as FontSizeValue | null;
    if (stored && ["small", "default", "large", "xlarge"].includes(stored)) return stored;
    return "default";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, fontSize);
    const scale = SCALE_MAP[fontSize];
    document.documentElement.style.setProperty("--font-scale", String(scale));
  }, [fontSize]);

  const setFontSize = (value: FontSizeValue) => setFontSizeState(value);

  return { fontSize, setFontSize };
}
