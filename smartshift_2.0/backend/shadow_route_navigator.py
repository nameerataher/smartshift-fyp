"""
shadow_route_navigator.py

Shadow-aware navigation engine for SmartShift.
Generates routes using Mapbox Directions API, then evaluates and re-ranks them
based on real 3D shadow projections from nearby buildings.

Architecture:
1. Fetch candidate routes from Mapbox Directions API (walking/cycling)
2. If fewer than 3, generate additional alternatives via offset waypoints
3. Sample points along each route at regular intervals
4. For each sample point, compute the ETA and fetch nearby buildings
5. Use ShadowCalculator to project building shadows at the ETA time
6. Check if each sample point falls within any shadow polygon (ray-casting PIP)
7. Score routes: final_score = shade_weight * shade + duration_weight * (1-duration)
8. Return ranked alternatives with per-waypoint shadow metadata
9. Support real-time recomputation as user progresses along route
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import math
import requests

from shadow_calculator import ShadowCalculator, Building
from solar_position import SunPosition
from shadow_scheduler import parse_client_buildings, _point_in_polygon, _haversine
from config import SAMPLE_BUILDINGS

MAPBOX_TOKEN = (
    "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9"
    ".WI13BJqDyOu6G38-YP6hog"
)
DEFAULT_BUILDING_HEIGHT = 30.0
BUILDING_FETCH_RADIUS = 300
SAMPLE_INTERVAL_METERS = 50.0
BUILDING_QUERY_INTERVAL_METERS = 250.0


@dataclass
class RouteWaypoint:
    lat: float
    lon: float
    eta: datetime
    distance_from_start: float
    in_shadow: bool = False
    sun_altitude: float = 0.0
    sun_azimuth: float = 0.0
    building_count: int = 0


@dataclass
class ScoredRoute:
    route_id: int
    coordinates: List[List[float]]
    distance_meters: float
    duration_seconds: float
    waypoints: List[RouteWaypoint]
    shade_coverage_pct: float
    sun_exposure_minutes: float
    shade_score: float
    duration_score: float
    final_score: float
    label: str = ""
    risk_level: str = "LOW"
    risk_color: str = "#22c55e"
    reason: str = ""
    steps: List[Dict] = field(default_factory=list)


@dataclass
class RouteResponse:
    routes: List[ScoredRoute]
    departure_time: str
    travel_mode: str
    update_interval_seconds: int

    def to_dict(self) -> Dict:
        routes_data = []
        for r in self.routes:
            routes_data.append({
                "route_id": r.route_id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": r.coordinates
                },
                "distance_meters": r.distance_meters,
                "distance_km": round(r.distance_meters / 1000, 1),
                "duration_seconds": r.duration_seconds,
                "duration_minutes": round(r.duration_seconds / 60),
                "shade_coverage_pct": round(r.shade_coverage_pct, 1),
                "sun_exposure_minutes": round(r.sun_exposure_minutes, 1),
                "shade_score": round(r.shade_score, 3),
                "duration_score": round(r.duration_score, 3),
                "final_score": round(r.final_score, 1),
                "label": r.label,
                "risk_level": r.risk_level,
                "risk_color": r.risk_color,
                "reason": r.reason,
                "steps": r.steps,
                "waypoints_summary": {
                    "total": len(r.waypoints),
                    "in_shadow": sum(1 for w in r.waypoints if w.in_shadow),
                    "in_sun": sum(1 for w in r.waypoints if not w.in_shadow),
                }
            })

        return {
            "success": True,
            "routes": routes_data,
            "departure_time": self.departure_time,
            "travel_mode": self.travel_mode,
            "update_interval_seconds": self.update_interval_seconds,
            "route_count": len(self.routes),
        }


class ShadowRouteNavigator:
    """
    Shadow-aware navigation engine.

    Fetches routes from Mapbox Directions, evaluates shadow coverage at
    sampled points along each route using real 3D building shadow projections,
    then ranks routes with a weighted score favouring shade over duration.
    """

    TIMEZONE_OFFSET = 4.0

    def __init__(
        self,
        mapbox_token: str = MAPBOX_TOKEN,
        sample_interval: float = SAMPLE_INTERVAL_METERS,
        shade_weight: float = 0.75,
        duration_weight: float = 0.25,
    ):
        self.mapbox_token = mapbox_token
        self.sample_interval = sample_interval
        self.shade_weight = shade_weight
        self.duration_weight = duration_weight
        self._shadow_calc = ShadowCalculator()
        self._building_cache: Dict[str, List[Building]] = {}

    # ─── Main entry points ───────────────────────────────────────────

    def find_shadow_routes(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        mode: str = "walking",
        departure_time: Optional[datetime] = None,
        client_buildings: Optional[List[Dict]] = None,
        date_str: Optional[str] = None,
        current_minutes: Optional[int] = None,
    ) -> RouteResponse:
        if departure_time is None:
            if date_str and current_minutes is not None:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                departure_time = d.replace(
                    hour=current_minutes // 60,
                    minute=current_minutes % 60,
                    second=0,
                )
            else:
                departure_time = datetime.now()

        parsed_buildings = None
        if client_buildings:
            parsed_buildings = parse_client_buildings(client_buildings)

        raw_routes = self._fetch_mapbox_routes(
            start_lon, start_lat, end_lon, end_lat, mode
        )
        if not raw_routes:
            raise ValueError("No routes found between the given points")

        if len(raw_routes) < 3:
            extra = self._generate_via_waypoint_routes(
                start_lon, start_lat, end_lon, end_lat, mode, raw_routes
            )
            raw_routes.extend(extra)

        scored_routes: List[ScoredRoute] = []
        for i, route_data in enumerate(raw_routes[:4]):
            scored = self._evaluate_route(
                route_data, i, departure_time, mode, parsed_buildings
            )
            scored_routes.append(scored)

        self._rank_routes(scored_routes)

        avg_duration = sum(r.duration_seconds for r in scored_routes) / len(scored_routes)
        update_interval = max(60, min(300, int(avg_duration / 5)))

        return RouteResponse(
            routes=scored_routes[:3],
            departure_time=departure_time.isoformat(),
            travel_mode=mode,
            update_interval_seconds=update_interval,
        )

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
        """Real-time shadow update for a route in progress."""
        parsed_buildings = None
        if client_buildings:
            parsed_buildings = parse_client_buildings(client_buildings)

        current_time = departure_time + timedelta(seconds=elapsed_seconds)

        remaining_start = self._find_closest_point_index(
            route_coordinates, user_lon, user_lat
        )

        remaining_coords = route_coordinates[remaining_start:]
        if len(remaining_coords) < 2:
            return {
                "success": True,
                "current_in_shadow": False,
                "remaining_shade_pct": 0,
                "reroute_suggested": False,
                "progress_pct": 100,
            }

        remaining_distance = self._compute_path_distance(remaining_coords)
        remaining_duration = total_duration_seconds - elapsed_seconds
        if remaining_duration <= 0:
            remaining_duration = remaining_distance / (1.4 if mode == "walking" else 4.0)

        waypoints = self._sample_and_evaluate(
            remaining_coords, remaining_distance, remaining_duration,
            current_time, parsed_buildings,
        )

        user_in_shadow = waypoints[0].in_shadow if waypoints else False

        if waypoints:
            shaded = sum(1 for w in waypoints if w.in_shadow)
            remaining_shade = (shaded / len(waypoints)) * 100
        else:
            remaining_shade = 0

        progress_pct = min(100, (elapsed_seconds / max(1, total_duration_seconds)) * 100)

        return {
            "success": True,
            "current_in_shadow": user_in_shadow,
            "remaining_shade_pct": round(remaining_shade, 1),
            "reroute_suggested": remaining_shade < 25,
            "progress_pct": round(progress_pct, 1),
            "sun_altitude": waypoints[0].sun_altitude if waypoints else 0,
            "sun_azimuth": waypoints[0].sun_azimuth if waypoints else 0,
            "remaining_waypoints": len(waypoints),
            "shaded_waypoints": sum(1 for w in waypoints if w.in_shadow),
        }

    # ─── Mapbox API ──────────────────────────────────────────────────

    def _fetch_mapbox_routes(
        self,
        start_lon: float, start_lat: float,
        end_lon: float, end_lat: float,
        mode: str,
    ) -> List[Dict]:
        profile = f"mapbox/{'cycling' if mode == 'cycling' else 'walking'}"
        url = (
            f"https://api.mapbox.com/directions/v5/{profile}/"
            f"{start_lon},{start_lat};{end_lon},{end_lat}"
        )
        params = {
            "access_token": self.mapbox_token,
            "alternatives": "true",
            "geometries": "geojson",
            "overview": "full",
            "steps": "true",
            "annotations": "distance,duration",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok":
                print(f"[shadow-route] Mapbox error: {data.get('message')}")
                return []
            return data.get("routes", [])
        except Exception as e:
            print(f"[shadow-route] Failed to fetch routes: {e}")
            return []

    def _generate_via_waypoint_routes(
        self,
        start_lon: float, start_lat: float,
        end_lon: float, end_lat: float,
        mode: str,
        existing_routes: List[Dict],
    ) -> List[Dict]:
        """Generate additional alternatives by adding offset waypoints."""
        mid_lat = (start_lat + end_lat) / 2
        mid_lon = (start_lon + end_lon) / 2
        dx = end_lon - start_lon
        dy = end_lat - start_lat
        dist = math.sqrt(dx ** 2 + dy ** 2)
        if dist < 1e-8:
            return []

        offset = 0.0015
        perpendiculars = [
            (mid_lon - dy / dist * offset, mid_lat + dx / dist * offset),
            (mid_lon + dy / dist * offset, mid_lat - dx / dist * offset),
        ]

        profile = f"mapbox/{'cycling' if mode == 'cycling' else 'walking'}"
        additional: List[Dict] = []

        for via_lon, via_lat in perpendiculars:
            if len(existing_routes) + len(additional) >= 3:
                break
            url = (
                f"https://api.mapbox.com/directions/v5/{profile}/"
                f"{start_lon},{start_lat};{via_lon},{via_lat};{end_lon},{end_lat}"
            )
            params = {
                "access_token": self.mapbox_token,
                "alternatives": "false",
                "geometries": "geojson",
                "overview": "full",
                "steps": "true",
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                routes = data.get("routes", [])
                if routes:
                    additional.append(routes[0])
            except Exception:
                pass

        return additional

    # ─── Route evaluation ────────────────────────────────────────────

    def _evaluate_route(
        self,
        route_data: Dict,
        route_id: int,
        departure_time: datetime,
        mode: str,
        client_buildings: Optional[List[Building]] = None,
    ) -> ScoredRoute:
        geometry = route_data.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        distance = route_data.get("distance", 0)
        duration = route_data.get("duration", 0)
        raw_steps = route_data.get("legs", [{}])[0].get("steps", [])

        waypoints = self._sample_and_evaluate(
            coordinates, distance, duration, departure_time, client_buildings,
        )

        total = len(waypoints)
        shaded = sum(1 for w in waypoints if w.in_shadow)
        shade_pct = (shaded / total * 100) if total > 0 else 0

        walking_speed_mpm = 83.33 if mode == "walking" else 250.0
        sun_exposure_min = sum(
            self.sample_interval / walking_speed_mpm
            for w in waypoints if not w.in_shadow
        )

        step_summaries = []
        for s in raw_steps[:12]:
            step_summaries.append({
                "instruction": s.get("maneuver", {}).get("instruction", ""),
                "distance": s.get("distance", 0),
                "duration": s.get("duration", 0),
            })

        return ScoredRoute(
            route_id=route_id,
            coordinates=coordinates,
            distance_meters=distance,
            duration_seconds=duration,
            waypoints=waypoints,
            shade_coverage_pct=shade_pct,
            sun_exposure_minutes=sun_exposure_min,
            shade_score=shade_pct / 100.0,
            duration_score=0,
            final_score=0,
            steps=step_summaries,
        )

    def _sample_and_evaluate(
        self,
        coordinates: List[List[float]],
        total_distance: float,
        total_duration: float,
        departure_time: datetime,
        client_buildings: Optional[List[Building]] = None,
    ) -> List[RouteWaypoint]:
        if not coordinates or len(coordinates) < 2:
            return []

        waypoints: List[RouteWaypoint] = []
        cumulative_dist = 0.0
        last_bldg_fetch_dist = -BUILDING_QUERY_INTERVAL_METERS
        current_buildings: List[Building] = []

        for i in range(len(coordinates) - 1):
            lon1, lat1 = coordinates[i][0], coordinates[i][1]
            lon2, lat2 = coordinates[i + 1][0], coordinates[i + 1][1]
            segment_dist = _haversine(lat1, lon1, lat2, lon2)

            if segment_dist < 0.1:
                cumulative_dist += segment_dist
                continue

            num_samples = max(1, int(segment_dist / self.sample_interval))

            for j in range(num_samples):
                frac = j / num_samples
                lat = lat1 + frac * (lat2 - lat1)
                lon = lon1 + frac * (lon2 - lon1)
                dist = cumulative_dist + frac * segment_dist

                progress = dist / total_distance if total_distance > 0 else 0
                elapsed = progress * total_duration
                eta = departure_time + timedelta(seconds=elapsed)

                if dist - last_bldg_fetch_dist >= BUILDING_QUERY_INTERVAL_METERS or not current_buildings:
                    if client_buildings:
                        current_buildings = self._filter_nearby(
                            client_buildings, lat, lon, BUILDING_FETCH_RADIUS
                        )
                    else:
                        current_buildings = self._fetch_buildings(lat, lon)
                    last_bldg_fetch_dist = dist

                sun = self._get_sun_position(eta, lat, lon)

                in_shadow = False
                if sun.is_daylight and sun.altitude > 0 and current_buildings:
                    in_shadow = self._is_point_in_shadow(
                        lat, lon, current_buildings, sun
                    )
                elif not sun.is_daylight or sun.altitude <= 0:
                    in_shadow = True

                waypoints.append(RouteWaypoint(
                    lat=lat, lon=lon, eta=eta,
                    distance_from_start=dist,
                    in_shadow=in_shadow,
                    sun_altitude=sun.altitude,
                    sun_azimuth=sun.azimuth,
                    building_count=len(current_buildings),
                ))

            cumulative_dist += segment_dist

        if coordinates:
            final_lon, final_lat = coordinates[-1][0], coordinates[-1][1]
            eta = departure_time + timedelta(seconds=total_duration)
            sun = self._get_sun_position(eta, final_lat, final_lon)
            in_shadow = False
            if sun.is_daylight and sun.altitude > 0 and current_buildings:
                in_shadow = self._is_point_in_shadow(
                    final_lat, final_lon, current_buildings, sun
                )
            elif not sun.is_daylight:
                in_shadow = True
            waypoints.append(RouteWaypoint(
                lat=final_lat, lon=final_lon, eta=eta,
                distance_from_start=total_distance,
                in_shadow=in_shadow,
                sun_altitude=sun.altitude,
                sun_azimuth=sun.azimuth,
                building_count=len(current_buildings),
            ))

        return waypoints

    # ─── Shadow computation ──────────────────────────────────────────

    def _is_point_in_shadow(
        self,
        lat: float, lon: float,
        buildings: List[Building],
        sun: SunPosition,
    ) -> bool:
        for building in buildings:
            polygon = self._shadow_calc.calculate_shadow_polygon(building, sun)
            if polygon and _point_in_polygon(lon, lat, polygon):
                return True
        return False

    def _fetch_buildings(self, lat: float, lon: float) -> List[Building]:
        cache_key = f"{round(lat, 3)},{round(lon, 3)}"
        if cache_key in self._building_cache:
            return self._building_cache[cache_key]

        url = (
            f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
            f"{lon},{lat}.json"
        )
        params = {
            "radius": BUILDING_FETCH_RADIUS,
            "layers": "building",
            "limit": 50,
            "access_token": self.mapbox_token,
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[shadow-route] Building fetch failed at ({lat:.4f},{lon:.4f}): {e}")
            fallback = self._get_fallback_buildings(lat, lon)
            self._building_cache[cache_key] = fallback
            return fallback

        buildings: List[Building] = []
        for idx, feature in enumerate(data.get("features", [])):
            geom = feature.get("geometry", {})
            props = feature.get("properties", {})
            if geom.get("type") != "Polygon":
                continue
            ring = geom.get("coordinates", [[]])[0]
            footprint = [(c[0], c[1]) for c in ring]
            if len(footprint) < 3:
                continue
            height = props.get("height") or DEFAULT_BUILDING_HEIGHT
            min_height = props.get("min_height") or 0
            effective_height = max(1.0, float(height) - float(min_height))
            buildings.append(Building(
                id=f"rt_{cache_key}_{idx}",
                footprint=footprint,
                height=effective_height,
                name=props.get("type", "building"),
            ))

        self._building_cache[cache_key] = buildings
        return buildings

    def _get_fallback_buildings(self, lat: float, lon: float) -> List[Building]:
        nearby: List[Building] = []
        for bdata in SAMPLE_BUILDINGS:
            fp = bdata["footprint"]
            clat = sum(p[1] for p in fp) / len(fp)
            clon = sum(p[0] for p in fp) / len(fp)
            if _haversine(lat, lon, clat, clon) <= BUILDING_FETCH_RADIUS * 3:
                nearby.append(Building(
                    id=bdata["id"],
                    footprint=[(p[0], p[1]) for p in fp],
                    height=bdata["height"],
                    name=bdata.get("name"),
                ))
        return nearby

    def _filter_nearby(
        self,
        buildings: List[Building],
        lat: float, lon: float,
        radius: float,
    ) -> List[Building]:
        nearby = []
        for b in buildings:
            centroid = b.get_centroid()
            d = _haversine(lat, lon, centroid[1], centroid[0])
            if d <= radius:
                nearby.append(b)
        return nearby if nearby else buildings[:25]

    # ─── Scoring and ranking ─────────────────────────────────────────

    def _rank_routes(self, routes: List[ScoredRoute]):
        if not routes:
            return

        max_dur = max(r.duration_seconds for r in routes)
        min_dur = min(r.duration_seconds for r in routes)
        dur_range = max_dur - min_dur if max_dur != min_dur else 1

        for r in routes:
            r.duration_score = 1.0 - (r.duration_seconds - min_dur) / dur_range
            r.final_score = round(
                (self.shade_weight * r.shade_score +
                 self.duration_weight * r.duration_score) * 100,
                1,
            )

        routes.sort(key=lambda r: r.final_score, reverse=True)

        labels = ["Best Shade", "Balanced", "Shortest"]
        for i, r in enumerate(routes):
            r.label = labels[i] if i < len(labels) else f"Option {i + 1}"

            if r.shade_coverage_pct >= 60:
                r.risk_level = "LOW"
                r.risk_color = "#22c55e"
            elif r.shade_coverage_pct >= 30:
                r.risk_level = "MEDIUM"
                r.risk_color = "#f59e0b"
            else:
                r.risk_level = "HIGH"
                r.risk_color = "#ef4444"

            dur_min = round(r.duration_seconds / 60)
            dist_km = round(r.distance_meters / 1000, 1)
            shade = round(r.shade_coverage_pct)
            sun_min = round(r.sun_exposure_minutes)

            if shade >= 70:
                r.reason = (
                    f"{dist_km}km · {dur_min}min · {shade}% shaded – "
                    f"excellent shadow coverage from nearby buildings"
                )
            elif shade >= 40:
                r.reason = (
                    f"{dist_km}km · {dur_min}min · {shade}% shaded – "
                    f"moderate building shadow along path"
                )
            else:
                r.reason = (
                    f"{dist_km}km · {dur_min}min · {shade}% shaded – "
                    f"limited shade, ~{sun_min}min in direct sun"
                )

    # ─── Sun position (same algorithm as shadow_scheduler) ───────────

    def _get_sun_position(self, dt: datetime, lat: float, lon: float) -> SunPosition:
        tz = self.TIMEZONE_OFFSET
        day_of_year = dt.timetuple().tm_yday

        declination = 23.45 * math.sin(math.radians((360 / 365) * (284 + day_of_year)))
        B = math.radians((360 / 365) * (day_of_year - 81))
        EoT = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

        solar_time = dt.hour * 60 + dt.minute + EoT + 4 * (lon - tz * 15)
        hour_angle = solar_time / 4 - 180

        lat_rad = math.radians(lat)
        dec_rad = math.radians(declination)
        ha_rad = math.radians(hour_angle)

        sin_alt = (math.sin(lat_rad) * math.sin(dec_rad) +
                   math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
        sin_alt = max(-1.0, min(1.0, sin_alt))
        altitude = math.degrees(math.asin(sin_alt))

        cos_az = ((math.sin(dec_rad) - math.sin(lat_rad) * sin_alt) /
                  (math.cos(lat_rad) * math.cos(math.asin(sin_alt)) + 1e-10))
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        if hour_angle > 0:
            azimuth = 360 - azimuth

        return SunPosition(
            azimuth=azimuth,
            altitude=altitude,
            zenith=90.0 - altitude,
            is_daylight=altitude > 0,
        )

    # ─── Geometry helpers ────────────────────────────────────────────

    def _find_closest_point_index(
        self,
        coordinates: List[List[float]],
        lon: float, lat: float,
    ) -> int:
        min_dist = float("inf")
        min_idx = 0
        for i, coord in enumerate(coordinates):
            d = _haversine(lat, lon, coord[1], coord[0])
            if d < min_dist:
                min_dist = d
                min_idx = i
        return min_idx

    def _compute_path_distance(self, coordinates: List[List[float]]) -> float:
        total = 0.0
        for i in range(len(coordinates) - 1):
            total += _haversine(
                coordinates[i][1], coordinates[i][0],
                coordinates[i + 1][1], coordinates[i + 1][0],
            )
        return total
