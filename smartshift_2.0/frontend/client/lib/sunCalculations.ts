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

const DUBAI_TZ = "Asia/Dubai";

/** Current time in Dubai: minutes since midnight (0–1439) and date string YYYY-MM-DD. Uses Intl so result is correct in any browser timezone. */
export function getDubaiNow(): { minutes: number; dateStr: string } {
  const now = new Date();
  const dateParts = new Intl.DateTimeFormat("en-CA", { timeZone: DUBAI_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const y = dateParts.find((p) => p.type === "year")?.value ?? "";
  const mo = dateParts.find((p) => p.type === "month")?.value ?? "";
  const d = dateParts.find((p) => p.type === "day")?.value ?? "";
  const dateStr = `${y}-${mo}-${d}`;
  const timeParts = new Intl.DateTimeFormat("en-CA", { timeZone: DUBAI_TZ, hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(now);
  const hour = parseInt(timeParts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const minute = parseInt(timeParts.find((p) => p.type === "minute")?.value ?? "0", 10);
  const minutes = hour * 60 + minute;
  return { minutes, dateStr };
}

/** Format minutes since midnight (0–1439) as "H:MM" or "HH:MM" */
export function formatTime(minutes: number): string {
  const h = Math.floor(minutes / 60) % 24;
  const m = minutes % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

/**
 * Build UTC Date for Dubai local date + time (hour, minute).
 * Uses UTC calendar day from date so that dateStr "YYYY-MM-DD" is correct regardless of user timezone. Dubai = UTC+4.
 */
function dubaiLocalToUTC(date: Date, hour: number, minute: number): Date {
  const y = date.getUTCFullYear();
  const mo = date.getUTCMonth();
  const day = date.getUTCDate();
  const utcH = hour - DUBAI_UTC_OFFSET_HOURS;
  return new Date(Date.UTC(y, mo, day, utcH, minute, 0, 0));
}

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

function toRad(deg: number) { return deg * DEG; }
function toDeg(rad: number) { return rad * RAD; }
function norm360(deg: number) { return ((deg % 360) + 360) % 360; }

function julianDay(d: Date): number {
  return d.getTime() / 86400000 + 2440587.5;
}

/**
 * Solar position for a given date and Dubai local time (hour 0–23, minute 0–59).
 * altitude: degrees above horizon, azimuth: degrees from N clockwise.
 */
export function calculateSunPosition(
  date: Date,
  hour: number,
  minute: number
): SunPosition {
  const utc = dubaiLocalToUTC(date, hour, minute);
  const jd = julianDay(utc);
  // Days since J2000.0
  const n = jd - 2451545.0;

  // Mean anomaly (degrees)
  const g = norm360(357.529 + 0.98560028 * n);
  // Mean longitude (degrees)
  const q = norm360(280.459 + 0.98564736 * n);
  // Ecliptic longitude (degrees)
  const L = norm360(q + 1.915 * Math.sin(toRad(g)) + 0.02 * Math.sin(toRad(2 * g)));
  // Obliquity of ecliptic
  const e = 23.439 - 0.00000036 * n;

  // Right ascension (degrees)
  const raDeg = norm360(toDeg(Math.atan2(Math.cos(toRad(e)) * Math.sin(toRad(L)), Math.cos(toRad(L)))));
  // Declination (degrees)
  const decDeg = toDeg(Math.asin(Math.sin(toRad(e)) * Math.sin(toRad(L))));

  // Greenwich Mean Sidereal Time (degrees) — must use n (JD−J2000), NOT getTime()/86400000
  const gmst = norm360(280.46061837 + 360.98564736629 * n);

  // Local Hour Angle (degrees): positive = west of meridian
  let lha = norm360(gmst + DUBAI_LON - raDeg);
  if (lha > 180) lha -= 360; // range −180 to +180

  const latR = toRad(DUBAI_LAT);
  const decR = toRad(decDeg);
  const lhaR = toRad(lha);

  const sinAlt = Math.sin(decR) * Math.sin(latR) + Math.cos(decR) * Math.cos(latR) * Math.cos(lhaR);
  const altitude = toDeg(Math.asin(Math.max(-1, Math.min(1, sinAlt))));

  const az = toDeg(Math.atan2(
    -Math.cos(decR) * Math.cos(latR) * Math.sin(lhaR),
    Math.sin(decR) - Math.sin(latR) * sinAlt
  )) + 180;
  const azimuth = norm360(az);

  return { altitude, azimuth };
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

/** Sunrise and sunset times for a given date in Dubai (local calculation fallback). */
export function getSunriseSunset(date: Date): { sunrise: string; sunset: string } {
  let sunriseMin = 0;
  let sunsetMin = 1439;
  let prevAlt = -1;
  for (let m = 0; m < 1440; m++) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    const pos = calculateSunPosition(date, h, min);
    if (prevAlt < 0 && pos.altitude >= 0) sunriseMin = m;
    if (pos.altitude >= 0) sunsetMin = m;
    prevAlt = pos.altitude;
  }
  return { sunrise: formatTime(sunriseMin), sunset: formatTime(sunsetMin) };
}

const OPEN_METEO = "https://api.open-meteo.com/v1/forecast";

/**
 * Fetch sunrise and sunset for Dubai (Asia/Dubai) for a given date.
 * Uses Open-Meteo API; returns times in Dubai local time as "H:MM" / "HH:MM".
 */
export async function fetchSunriseSunsetDubai(dateStr: string): Promise<{ sunrise: string; sunset: string }> {
  const url = `${OPEN_METEO}?latitude=${DUBAI_LAT}&longitude=${DUBAI_LON}&daily=sunrise,sunset&timezone=Asia/Dubai&start_date=${dateStr}&end_date=${dateStr}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Sunrise/sunset API error: ${res.status}`);
  const data = await res.json();
  const sunrise = (data.daily?.sunrise?.[0] ?? "") as string;
  const sunset = (data.daily?.sunset?.[0] ?? "") as string;
  const format = (iso: string): string => {
    if (!iso || iso.length < 16) return "--";
    const part = iso.slice(11, 16);
    const [h, m] = part.split(":").map(Number);
    return `${h}:${String(m).padStart(2, "0")}`;
  };
  return { sunrise: format(sunrise), sunset: format(sunset) };
}
