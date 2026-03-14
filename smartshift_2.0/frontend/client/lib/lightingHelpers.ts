/**
 * Mapbox 3D lighting helpers: light preset and light properties from sun position.
 * For use with Mapbox Standard style and setLights.
 */

/** Mapbox Standard lightPreset: "dawn" | "day" | "dusk" | "night" */
export function getLightPreset(altitude: number, _azimuth: number): string {
  if (altitude < -6) return "night";
  if (altitude < 0) return "dusk";
  if (altitude < 15) return "dawn";
  if (altitude < 90) return "day";
  return "day";
}

/** Sun directional light color (hex) from altitude/azimuth */
export function getTimeOfDayColor(altitude: number, _azimuth: number): string {
  if (altitude <= 0) return "#1a1a2e";
  if (altitude < 10) return "#ffd89b";
  if (altitude < 25) return "#ffeaa7";
  return "#ffffff";
}

/** Ambient light color */
export function getAmbientColor(altitude: number): string {
  if (altitude <= 0) return "#0a0a12";
  if (altitude < 15) return "#2d2d44";
  return "#a0a0a0";
}

/** Ambient light intensity (0–1) */
export function getAmbientIntensity(altitude: number): number {
  if (altitude <= 0) return 0.2;
  if (altitude < 15) return 0.4;
  return 0.7;
}

/** Sun directional light intensity */
export function getSunIntensity(altitude: number): number {
  if (altitude <= 0) return 0;
  if (altitude < 10) return 0.5;
  if (altitude < 30) return 1.0;
  return 1.2;
}

/** Shadow intensity for directional light */
export function getShadowIntensity(altitude: number): number {
  if (altitude <= 0) return 0;
  if (altitude < 15) return 0.3;
  if (altitude < 45) return 0.6;
  return 0.8;
}
