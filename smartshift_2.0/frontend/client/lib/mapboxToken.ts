const TOKEN_KEY = "smartshift:mapboxToken";

/** Mapbox token: localStorage override, then VITE_MAPBOX_TOKEN from .env */
export function getMapboxToken(): string {
  try {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored?.trim()) return stored.trim();
  } catch {
    /* private browsing / blocked storage */
  }
  const envToken = import.meta.env.VITE_MAPBOX_TOKEN;
  return typeof envToken === "string" ? envToken.trim() : "";
}

export function setMapboxToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token.trim());
  } catch {
    /* ignore */
  }
}

export { TOKEN_KEY };
