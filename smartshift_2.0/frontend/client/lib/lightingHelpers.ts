/**
 * Mapbox 3D lighting helpers: light preset and light properties from sun position.
 * For use with Mapbox Standard style and setLights.
 */

function clamp(v: number, min: number, max: number) { return Math.max(min, Math.min(max, v)); }
function lerp(a: number, b: number, t: number) { return a + (b - a) * clamp(t, 0, 1); }

/**
 * Mapbox Standard lightPreset: "dawn" | "day" | "dusk" | "night".
 * altitude: degrees above horizon (positive = day, negative = below horizon).
 * azimuth: 0=N, 90=E, 180=S, 270=W (morning sun ~90-120°, evening ~240-270°).
 * Afternoon = sun has passed solar south (azimuth > 180°).
 */
export function getLightPreset(altitude: number, azimuth: number): string {
  const isAfternoon = azimuth > 180;
  if (altitude < -6) return "night";
  if (altitude < 0) return isAfternoon ? "dusk" : "dawn";
  if (altitude < 10) return isAfternoon ? "dusk" : "dawn";
  return "day";
}

/** Sun directional light color (hex) — warm sunrise to white midday; soft blue at night (moon/starlight) */
export function getTimeOfDayColor(altitude: number, _azimuth: number): string {
  if (altitude <= -6) return "#6b7a9e";   // soft blue-grey (moonlight), was too dark
  if (altitude <= 0) return "#4a5078";
  if (altitude <= 5) return "#ff7b54";
  if (altitude <= 15) return "#ffb347";
  if (altitude <= 30) return "#ffe4b5";
  return "#ffffff";
}

/** Ambient light color — readable night blue, warm at dawn/dusk, neutral day */
export function getAmbientColor(altitude: number): string {
  if (altitude <= -6) return "#2a2d45";   // night: visible but still blue
  if (altitude <= 0) return "#3a3d55";
  if (altitude <= 10) return "#4a4a60";
  if (altitude <= 25) return "#7a7a90";
  return "#a0a0b0";
}

/** Ambient light intensity (0–1) — higher at night so map stays readable */
export function getAmbientIntensity(altitude: number): number {
  if (altitude <= -6) return 0.42;        // night: was 0.15, now readable
  if (altitude <= 0) return lerp(0.42, 0.38, (altitude + 6) / 6);
  if (altitude <= 30) return lerp(0.38, 0.6, altitude / 30);
  return 0.65;
}

/** Sun/moon directional light intensity — ramps up at sunrise; small value at night for shape */
export function getSunIntensity(altitude: number): number {
  if (altitude <= -6) return 0.06;        // night: faint moonlight so buildings have shape
  if (altitude <= 0) return lerp(0.06, 0.12, (altitude + 6) / 6);
  if (altitude <= 10) return lerp(0.2, 0.7, altitude / 10);
  if (altitude <= 30) return lerp(0.7, 1.0, (altitude - 10) / 20);
  return 1.0;
}

/** Shadow intensity — stronger shadows when sun is higher but not overhead */
export function getShadowIntensity(altitude: number): number {
  if (altitude <= 0) return 0;
  if (altitude <= 10) return lerp(0.1, 0.4, altitude / 10);
  if (altitude <= 45) return lerp(0.4, 0.85, (altitude - 10) / 35);
  if (altitude <= 70) return lerp(0.85, 0.7, (altitude - 45) / 25);
  return 0.6;
}
