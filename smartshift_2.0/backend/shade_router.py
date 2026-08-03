"""
Route shadow scoring for precomputed polylines (e.g. Google/Mapbox directions).

Used by /api/v2/routes-shade-score, /api/v2/route-segment-shadows, and
/api/v2/shadow-route/update. Does not build a custom road graph or optimize paths.
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import requests as http_req

from shadow_calculator import Building, ShadowCalculator
from shadow_scheduler import _haversine, _point_in_polygon, parse_client_buildings
from solar_position import SunPosition
from mapbox_config import get_mapbox_token

MAPBOX_TOKEN = get_mapbox_token()

BUILDING_FETCH_RADIUS = 300
DEFAULT_BUILDING_HEIGHT = 30.0
# Spacing along the input route when sampling buildings from Tilequery.
ROUTE_SAMPLE_SPACING = 150
# Segment length (m) for shadow segment sampling and remaining-shade estimate.
GRAPH_SEGMENT_LENGTH = 5

METERS_PER_DEGREE_LAT = 111320.0
# Step (m) along the shadow axis when testing whether a point is occluded.
SHADOW_SAMPLE_STEP = 4.0
MAX_SHADOW_SAMPLES = 40

# (footprint, height, centroid_lon, centroid_lat, radius_m)
PreparedBuilding = tuple


def _prepare_buildings(buildings: List[Building]) -> List[PreparedBuilding]:
    """Precompute centroid + enclosing radius so point tests can skip far buildings."""
    prepared: List[PreparedBuilding] = []
    for b in buildings:
        fp = b.footprint
        if not fp or len(fp) < 3 or b.height <= 0:
            continue
        cx = sum(p[0] for p in fp) / len(fp)
        cy = sum(p[1] for p in fp) / len(fp)
        m_per_deg_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(cy))
        radius = max(
            math.hypot((p[0] - cx) * m_per_deg_lon, (p[1] - cy) * METERS_PER_DEGREE_LAT)
            for p in fp
        )
        prepared.append((fp, float(b.height), cx, cy, radius))
    return prepared


def _shadow_length(height: float, altitude: float) -> float:
    """Ground length of a building's shadow, matching ShadowCalculator's model."""
    if altitude <= 0:
        return 0.0
    return min(height / math.tan(math.radians(max(1.0, altitude))), height * 10)


def _point_shaded_prepared(lon, lat, sun, prepared: List[PreparedBuilding]) -> bool:
    """
    True if (lon, lat) sits in a building's cast shadow (or on its footprint).

    The shadow of a footprint is that footprint swept along the shadow direction,
    so the test walks the point back toward the sun and checks whether any step
    lands inside a footprint. The previous version built a single polygon from
    "translated vertices + reversed footprint", which self-intersects for any
    non-convex footprint and made the ray-casting test flip shaded points to
    unshaded — one reason the reported percentages disagreed with the map.
    """
    if not sun.is_daylight or sun.altitude <= 0:
        return True

    direction = math.radians((sun.azimuth + 180.0) % 360.0)
    ux = math.sin(direction)  # east component
    uy = math.cos(direction)  # north component
    m_per_deg_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat)) or 1e-9

    for fp, height, cx, cy, radius in prepared:
        length = _shadow_length(height, sun.altitude)
        if length < 0.5:
            continue
        dist = math.hypot((lon - cx) * m_per_deg_lon, (lat - cy) * METERS_PER_DEGREE_LAT)
        if dist > radius + length:
            continue
        steps = max(1, min(MAX_SHADOW_SAMPLES, int(length / SHADOW_SAMPLE_STEP)))
        for i in range(steps + 1):
            t = length * i / steps
            px = lon - (t * ux) / m_per_deg_lon
            py = lat - (t * uy) / METERS_PER_DEGREE_LAT
            if _point_in_polygon(px, py, fp):
                return True
    return False


# Tilequery results keyed by rounded lat/lon. Shared across instances because a
# ShadeRouter is constructed per request, and refetching the same tiles on every
# request was the bulk of the scoring latency.
_TILEQUERY_CACHE: Dict[str, List[Building]] = {}
_TILEQUERY_CACHE_MAX = 4000


class ShadeRouter:
    TZ = 4.0
    WALK_SPEED = 1.4
    RUN_SPEED = 2.6  # m/s
    CYCLE_SPEED = 4.0

    def __init__(self, segment_length: float = GRAPH_SEGMENT_LENGTH):
        self.seg_len = segment_length
        self._sc = ShadowCalculator()
        self._bldg_cache = _TILEQUERY_CACHE

    def update_route_shadows(
        self,
        route_coordinates: List[List[float]],
        user_lat: float,
        user_lon: float,
        departure_time: datetime,
        elapsed_seconds: float,
        mode: str = "walking",
        total_duration_seconds: float = 0,
        client_buildings: Optional[List[Dict]] = None,
    ) -> Dict:
        parsed = parse_client_buildings(client_buildings) if client_buildings else []
        now = departure_time + timedelta(seconds=elapsed_seconds)
        buildings = self._gather_route_buildings(route_coordinates, parsed)
        sun = self._sun(now, user_lat, user_lon)

        in_shadow = self._point_shaded(user_lat, user_lon, sun, buildings)

        closest = min(
            range(len(route_coordinates)),
            key=lambda i: _haversine(
                user_lat,
                user_lon,
                route_coordinates[i][1],
                route_coordinates[i][0],
            ),
        )
        remaining = route_coordinates[closest:]
        rem_dur = max(0, total_duration_seconds - elapsed_seconds)

        pct = self._estimate_remaining_shade_pct(remaining, now, rem_dur, buildings)
        progress = min(100, elapsed_seconds / max(1, total_duration_seconds) * 100)

        return {
            "success": True,
            "current_in_shadow": in_shadow,
            "remaining_shade_pct": round(pct, 1),
            "reroute_suggested": pct < 25,
            "progress_pct": round(progress, 1),
            "sun_altitude": round(sun.altitude, 1),
            "sun_azimuth": round(sun.azimuth, 1),
        }

    def get_route_segment_shadows(
        self,
        route_coordinates: List[List[float]],
        departure_time: datetime,
        mode: str = "walking",
        client_buildings: Optional[List[Dict]] = None,
        buildings: Optional[List[Building]] = None,
    ) -> Dict:
        """
        Return per-segment shadow fraction for a route polyline.

        route_coordinates: list of [lon, lat] points.
        buildings: pre-gathered building set. Pass this when scoring several routes
        against each other (see gather_buildings_for_routes) — gathering per route
        gives each one a different set of obstacles and makes the resulting shade
        percentages non-comparable.
        """
        if buildings is None:
            parsed = parse_client_buildings(client_buildings) if client_buildings else []
            buildings = self._gather_route_buildings(route_coordinates, parsed)
        if mode == "walking":
            speed = self.WALK_SPEED
        elif mode == "running":
            speed = self.RUN_SPEED
        else:
            speed = self.CYCLE_SPEED

        sampled = self._sample_polyline(route_coordinates, self.seg_len)
        if len(sampled) < 2:
            return {"segments": [], "buildings_used": len(buildings)}

        prepared = _prepare_buildings(buildings)
        segments_out: List[Dict] = []
        elapsed_seconds = 0.0
        total_time = 0.0
        total_shade_time = 0.0
        spd = max(speed, 0.1)

        for idx in range(len(sampled) - 1):
            lon1, lat1 = sampled[idx]
            lon2, lat2 = sampled[idx + 1]
            seg_d = _haversine(lat1, lon1, lat2, lon2)
            mid_lon = (lon1 + lon2) / 2
            mid_lat = (lat1 + lat2) / 2
            segment_time = seg_d / spd
            total_time += segment_time

            edge_time = departure_time + timedelta(seconds=elapsed_seconds + segment_time)

            sun = self._sun(edge_time, mid_lat, mid_lon)
            shadow_fraction = 1.0 if _point_shaded_prepared(mid_lon, mid_lat, sun, prepared) else 0.0

            total_shade_time += shadow_fraction * segment_time
            segments_out.append(
                {
                    "lon": round(mid_lon, 6),
                    "lat": round(mid_lat, 6),
                    "shadow_fraction": round(shadow_fraction, 3),
                    "segment_index": idx,
                }
            )
            elapsed_seconds += segment_time

        weighted_shade_fraction = total_shade_time / total_time if total_time > 0 else 0.0
        return {
            "segments": segments_out,
            "buildings_used": len(buildings),
            "departure_time": departure_time.isoformat(),
            "weighted_shade_fraction": round(weighted_shade_fraction, 4),
            "total_route_time_seconds": round(total_time, 1),
            "total_shade_time_seconds": round(total_shade_time, 1),
        }

    def gather_buildings_for_routes(
        self,
        routes_coordinates: List[List[List[float]]],
        client_buildings: Optional[List[Dict]] = None,
    ) -> List[Building]:
        """Union of the buildings near every given route, so a set of alternatives
        can all be scored against identical obstacles."""
        parsed = parse_client_buildings(client_buildings) if client_buildings else []
        buildings: List[Building] = []
        seen: Set[str] = set()
        for coords in routes_coordinates:
            if not coords or len(coords) < 2:
                continue
            for building in self._gather_route_buildings(coords, parsed):
                if building.id not in seen:
                    seen.add(building.id)
                    buildings.append(building)
        return buildings

    def _gather_route_buildings(self, route_coordinates, parsed):
        buildings: List[Building] = []
        seen: Set[str] = set()

        for building in parsed:
            if building.id not in seen:
                seen.add(building.id)
                buildings.append(building)

        for lon, lat in self._sample_polyline(route_coordinates, ROUTE_SAMPLE_SPACING):
            for building in self._fetch_buildings(lat, lon):
                if building.id not in seen:
                    seen.add(building.id)
                    buildings.append(building)

        return buildings

    def _sample_polyline(self, coords, spacing_m):
        if not coords:
            return []
        if len(coords) == 1:
            return [(coords[0][0], coords[0][1])]

        cum = [0.0]
        for idx in range(1, len(coords)):
            seg_d = _haversine(
                coords[idx - 1][1],
                coords[idx - 1][0],
                coords[idx][1],
                coords[idx][0],
            )
            cum.append(cum[-1] + seg_d)

        total = cum[-1]
        if total < 1:
            return [(coords[0][0], coords[0][1]), (coords[-1][0], coords[-1][1])]

        targets = [0.0]
        cursor = spacing_m
        while cursor < total:
            targets.append(cursor)
            cursor += spacing_m
        if total - targets[-1] > 1.0:
            targets.append(total)

        sampled = []
        seg_idx = 0
        for target in targets:
            while seg_idx < len(cum) - 2 and cum[seg_idx + 1] < target:
                seg_idx += 1

            leg = max(cum[seg_idx + 1] - cum[seg_idx], 1e-10)
            frac = max(0.0, min(1.0, (target - cum[seg_idx]) / leg))
            next_idx = min(seg_idx + 1, len(coords) - 1)
            lon = coords[seg_idx][0] + frac * (coords[next_idx][0] - coords[seg_idx][0])
            lat = coords[seg_idx][1] + frac * (coords[next_idx][1] - coords[seg_idx][1])
            point = (lon, lat)
            if not sampled or _haversine(lat, lon, sampled[-1][1], sampled[-1][0]) > 0.5:
                sampled.append(point)

        if sampled[-1] != (coords[-1][0], coords[-1][1]):
            sampled.append((coords[-1][0], coords[-1][1]))
        return sampled

    def _point_shaded(self, lat, lon, sun, buildings):
        return _point_shaded_prepared(lon, lat, sun, _prepare_buildings(buildings))

    def _estimate_remaining_shade_pct(self, remaining, now, rem_dur, buildings):
        if len(remaining) < 2:
            return 100.0

        sampled = self._sample_polyline(remaining, self.seg_len)
        if len(sampled) < 2:
            return 100.0

        total_distance = 0.0
        segment_distances = []
        for idx in range(len(sampled) - 1):
            seg_d = _haversine(
                sampled[idx][1],
                sampled[idx][0],
                sampled[idx + 1][1],
                sampled[idx + 1][0],
            )
            segment_distances.append(seg_d)
            total_distance += seg_d

        prepared = _prepare_buildings(buildings)
        shaded = 0
        total = 0
        walked = 0.0
        for idx, seg_d in enumerate(segment_distances):
            mid_lon = (sampled[idx][0] + sampled[idx + 1][0]) / 2
            mid_lat = (sampled[idx][1] + sampled[idx + 1][1]) / 2
            t = now + timedelta(
                seconds=(rem_dur * ((walked + seg_d / 2) / max(total_distance, 1.0)))
            )
            s = self._sun(t, mid_lat, mid_lon)
            if _point_shaded_prepared(mid_lon, mid_lat, s, prepared):
                shaded += 1
            total += 1
            walked += seg_d

        return (shaded / max(total, 1)) * 100

    def _fetch_buildings(self, lat, lon) -> List[Building]:
        ck = f"{round(lat, 3)},{round(lon, 3)}"
        if ck in self._bldg_cache:
            return self._bldg_cache[ck]

        url = (
            f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/"
            f"tilequery/{lon},{lat}.json"
        )
        params = {
            "radius": BUILDING_FETCH_RADIUS,
            "layers": "building",
            "limit": 50,
            "access_token": MAPBOX_TOKEN,
        }
        try:
            resp = http_req.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # Not cached: a transient failure must not blank out this tile for the
            # rest of the process now that the cache is shared.
            return []

        buildings: List[Building] = []
        for idx, feat in enumerate(data.get("features", [])):
            geom = feat.get("geometry", {})
            props = feat.get("properties", {})
            gtype = geom.get("type", "")

            if gtype == "Polygon":
                ring = geom.get("coordinates", [[]])[0]
                footprint = [(coord[0], coord[1]) for coord in ring]
                if len(footprint) < 3:
                    continue
            elif gtype == "Point":
                gc = geom.get("coordinates", [])
                if len(gc) < 2:
                    continue
                cx, cy = gc[0], gc[1]
                size = 0.00015
                footprint = [
                    (cx - size, cy - size),
                    (cx + size, cy - size),
                    (cx + size, cy + size),
                    (cx - size, cy + size),
                    (cx - size, cy - size),
                ]
            else:
                continue

            height = max(
                1.0,
                float(props.get("height") or DEFAULT_BUILDING_HEIGHT)
                - float(props.get("min_height") or 0),
            )
            buildings.append(
                Building(
                    id=f"b_{ck}_{idx}",
                    footprint=footprint,
                    height=height,
                    name=props.get("type", "building"),
                )
            )

        if len(self._bldg_cache) >= _TILEQUERY_CACHE_MAX:
            self._bldg_cache.clear()
        self._bldg_cache[ck] = buildings
        return buildings

    def _sun(self, dt, lat, lon) -> SunPosition:
        tz = self.TZ
        doy = dt.timetuple().tm_yday
        dec = 23.45 * math.sin(math.radians(360 / 365 * (284 + doy)))
        b_angle = math.radians(360 / 365 * (doy - 81))
        eot = 9.87 * math.sin(2 * b_angle) - 7.53 * math.cos(b_angle) - 1.5 * math.sin(b_angle)
        solar_time = dt.hour * 60 + dt.minute + eot + 4 * (lon - tz * 15)
        ha = solar_time / 4 - 180
        lat_r = math.radians(lat)
        dec_r = math.radians(dec)
        ha_r = math.radians(ha)
        sin_alt = (
            math.sin(lat_r) * math.sin(dec_r)
            + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
        )
        sin_alt = max(-1.0, min(1.0, sin_alt))
        alt = math.degrees(math.asin(sin_alt))
        cos_az = (math.sin(dec_r) - math.sin(lat_r) * sin_alt) / (
            math.cos(lat_r) * math.cos(math.asin(sin_alt)) + 1e-10
        )
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        if ha > 0:
            az = 360 - az
        return SunPosition(
            azimuth=az,
            altitude=alt,
            zenith=90 - alt,
            is_daylight=alt > 0,
        )
