/**
 * Sun position, time, and UV utilities for Dubai (Asia/Dubai, ~25.2°N, 55.3°E).
 */

const DUBAI_LAT = 25.2048;
const DUBAI_LON = 55.2708;
const DUBAI_UTC_OFFSET_HOURS = 4;

export interface SunPosition {
  altitude: number; // degrees above horizon (0–90+)
  azimuth: number;  // degrees from N, clockwise (0–360)
}

/** Current time in Dubai: minutes since midnight (0–1439) and date string YYYY-MM-DD */
export function getDubaiNow(): { minutes: number; dateStr: string } {
  const now = new Date();
  const dubai = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Dubai" }));
  const dateStr = dubai.toISOString().slice(0, 10);
  const minutes = dubai.getHours() * 60 + dubai.getMinutes();
  return { minutes, dateStr };
}

/** Format minutes since midnight (0–1439) as "H:MM" or "HH:MM" */
export function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60) % 24;
  const m = minutes % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

/**
 * Simplified solar position for a given date and time (local Dubai).
 * altitude: degrees above horizon, azimuth: degrees from north clockwise.
 */
export function calculateSunPosition(
  date: Date,
  hour: number,
  minute: number
): SunPosition {
  const d = new Date(date);
  d.setUTCFullYear(date.getFullYear(), date.getMonth(), date.getDate());
  d.setUTCHours(hour - DUBAI_UTC_OFFSET_HOURS, minute, 0, 0);
  const jd = julianDay(d);
  const n = jd - 2451545.0;
  const g = (357.529 + 0.98560028 * n) % 360;
  const q = 280.459 + 0.98564736 * n;
  const L = (q + 1.915 * Math.sin((g * Math.PI) / 180) + 0.02 * Math.sin((2 * g * Math.PI) / 180)) % 360;
  const e = 23.439 - 0.00000036 * n;
  const ra = (Math.atan2(Math.cos((e * Math.PI) / 180) * Math.sin((L * Math.PI) / 180), Math.cos((L * Math.PI) / 180)) * 180) / Math.PI / 15;
  const dec = (Math.asin(Math.sin((e * Math.PI) / 180) * Math.sin((L * Math.PI) / 180)) * 180) / Math.PI;
  const gmst = (280.460 + 360.98564736 * (d.getTime() / 86400000 - 2451545.0)) % 360;
  let lha = (gmst - ra * 15 + DUBAI_LON) % 360;
  if (lha > 180) lha -= 360;
  if (lha < -180) lha += 360;
  const latRad = (DUBAI_LAT * Math.PI) / 180;
  const decRad = (dec * Math.PI) / 180;
  const lhaRad = (lha * Math.PI) / 180;
  const sinAlt = Math.sin(decRad) * Math.sin(latRad) + Math.cos(decRad) * Math.cos(latRad) * Math.cos(lhaRad);
  const altitude = (Math.asin(Math.max(-1, Math.min(1, sinAlt))) * 180) / Math.PI;
  let azimuth = (Math.atan2(-Math.cos(decRad) * Math.cos(latRad) * Math.sin(lhaRad), Math.sin(decRad) - Math.sin(latRad) * sinAlt) * 180) / Math.PI + 180;
  if (azimuth < 0) azimuth += 360;
  if (azimuth >= 360) azimuth -= 360;
  return { altitude, azimuth };
}

function julianDay(d: Date): number {
  const t = d.getTime();
  return t / 86400000 + 2440587.5;
}

/** Time-of-day label from sun altitude/azimuth */
export function getTimePeriod(altitude: number, _azimuth: number): string {
  if (altitude < -6) return "Night";
  if (altitude < 0) return "Twilight";
  if (altitude < 15) return "Morning";
  if (altitude < 75) return "Midday";
  if (altitude < 90) return "Afternoon";
  return "Noon";
}

/** Approximate UV index (0–12) from date and minutes since midnight in Dubai */
export function calculateUV(date: Date, minutesSinceMidnight: number): number {
  const hour = Math.floor(minutesSinceMidnight / 60);
  const minute = minutesSinceMidnight % 60;
  const pos = calculateSunPosition(date, hour, minute);
  if (pos.altitude <= 0) return 0;
  const factor = Math.sin((pos.altitude * Math.PI) / 180);
  return Math.min(12, Math.max(0, Math.round(factor * 12 * 10) / 10));
}

/** UV category label from UV index */
export function getUVCategory(uv: number): string {
  if (uv <= 2) return "Low";
  if (uv <= 5) return "Moderate";
  if (uv <= 7) return "High";
  if (uv <= 10) return "Very High";
  return "Extreme";
}

/** Approximate shadow coverage (0–100%) from sun altitude; higher sun = less shade from vertical structures */
export function calculateShadowCoverage(altitudeDeg: number): number {
  if (altitudeDeg <= 0) return 100;
  const rad = (altitudeDeg * Math.PI) / 180;
  const tanAlt = Math.tan(rad);
  if (tanAlt <= 0) return 100;
  const shade = Math.min(100, Math.max(0, 100 - (tanAlt * 25)));
  return Math.round(shade);
}
