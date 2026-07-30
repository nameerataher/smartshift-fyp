from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
import math
import requests as http_client

from shadow_calculator import ShadowCalculator, Building, SHAPELY_AVAILABLE
from solar_position import SolarPositionCalculator, SunPosition
from config import DUBAI, SAMPLE_BUILDINGS
from scheduler_optimizations import (
    get_adaptive_sample_interval_minutes,
    get_sun_bucket,
    get_slot_step_for_long_duration,
)

def parse_client_buildings(raw_list: list) -> List[Building]:
    buildings: List[Building] = []
    for b in raw_list:
        fp = b.get("footprint", [])
        if len(fp) < 3:
            continue
        buildings.append(Building(
            id=b.get("id", f"cl_{len(buildings)}"),
            footprint=[(float(p[0]), float(p[1])) for p in fp],
            height=max(1.0, float(b.get("height", 30))),
            name=b.get("name", "building")
        ))
    return buildings


MAPBOX_TOKEN = (
    "pk.eyJ1Ijoibm1ydCIsImEiOiJjbXM0aTlsd2MxdGNqMzByM2E2anhwejFxIn0.-lSbB75uwdyrg2hmBJSZLQ"
)
DEFAULT_BUILDING_HEIGHT = 30.0  # meters – fallback for missing height data
BUILDING_FETCH_RADIUS = 300     # meters around the target point

TIME_STEP_MINUTES = 30 #discretize time at this step (minutes) for shade series + sliding window

@dataclass
class TimeSlot:
    start: datetime
    end: datetime
    shadow_percentage: float
    sun_altitude: float
    sun_azimuth: float
    # Debug breakdown for facade mode
    self_shaded_samples: int = 0
    ext_blocked_samples: int = 0
    sun_hit_samples: int = 0
    total_samples: int = 0
    face_angle_used: Optional[float] = None

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    @property
    def time_label(self) -> str:
        return f"{self.start.strftime('%I:%M %p')} – {self.end.strftime('%I:%M %p')}"

    @property
    def is_always_self_shaded(self) -> bool:
        """True if facade is self-shaded for all samples (sun always behind building)."""
        return self.total_samples > 0 and self.self_shaded_samples == self.total_samples

    @property
    def debug_breakdown(self) -> Dict[str, Any]:
        """Debug info showing how shadow % was computed."""
        if self.total_samples == 0:
            return {}
        return {
            "face_angle": self.face_angle_used,
            "total_samples": self.total_samples,
            "self_shaded": self.self_shaded_samples,
            "ext_blocked": self.ext_blocked_samples,
            "sun_hit": self.sun_hit_samples,
            "self_shaded_pct": round(100 * self.self_shaded_samples / self.total_samples, 1),
            "is_always_self_shaded": self.is_always_self_shaded,
        }

@dataclass
class ScheduleRecommendation:
    task_name: str
    location_name: str
    lat: float
    lon: float

    best_slot: TimeSlot
    alternatives: List[TimeSlot] = field(default_factory=list)

    total_evaluated: int = 0
    recommendation_reason: str = ""
    alternative_reasons: Optional[List[str]] = None  # One reason per alternative slot
    buildings_used: int = 0
    buildings_footprints_geojson: Optional[Dict] = None  # For visual overlay of buildings considered
    all_slots: Optional[List[TimeSlot]] = None  # When requested for debug: every slot with shade % and breakdown

    def to_dict(self, include_all_slots: bool = False) -> Dict:
        """Convert to API response format."""
        alt_reasons = self.alternative_reasons or []

        def slot_to_dict(slot: TimeSlot, reason: str = "") -> Dict:
            d = {
                "start_time": slot.start.isoformat(),
                "end_time": slot.end.isoformat(),
                "shadow_percentage": round(slot.shadow_percentage, 1),
                "sun_altitude": round(slot.sun_altitude, 1),
                "sun_azimuth": round(slot.sun_azimuth, 1),
                "time_label": slot.time_label,
                "recommendation_reason": reason,
            }
            # Include debug breakdown if available (facade mode)
            if slot.total_samples > 0:
                d["debug"] = slot.debug_breakdown
            return d

        out = {
            "task_name": self.task_name,
            "location": {
                "name": self.location_name,
                "lat": self.lat,
                "lon": self.lon
            },
            "best_schedule": slot_to_dict(self.best_slot, self.recommendation_reason),
            "alternatives": [
                slot_to_dict(slot, alt_reasons[i] if i < len(alt_reasons) else "")
                for i, slot in enumerate(self.alternatives)
            ],
            "recommendation_reason": self.recommendation_reason,
            "total_evaluated": self.total_evaluated,
            "buildings_analyzed": self.buildings_used,
            "buildings_footprints_geojson": self.buildings_footprints_geojson,
        }
        if include_all_slots and self.all_slots:
            out["all_slots"] = [slot_to_dict(s, "") for s in self.all_slots]
        return out


def _resolve_face_angle(
    face_angle: Optional[float],
    building_face: Optional[str],
) -> Optional[float]:
    if face_angle is not None and 0 <= face_angle < 360:
        return float(face_angle)
    return None


def _face_angle_to_cardinal(angle: float) -> str:
    a = angle % 360
    if a >= 315 or a < 45:
        return "N"
    if a < 135:
        return "E"
    if a < 225:
        return "S"
    return "W"

def _get_face_point_on_building(
    building: Building,
    face_angle_deg: float,
) -> Tuple[float, float]:
    if not building.footprint or len(building.footprint) < 2:
        clon, clat = building.get_centroid()
        return (clat, clon)
    clon, clat = building.get_centroid()
    cos_lat = math.cos(math.radians(clat))
    face_rad = math.radians(face_angle_deg)
    best_proj = -1e9
    best_pt = (clon, clat)
    for (plon, plat) in building.footprint:
        dlon_m = (plon - clon) * 111320 * cos_lat
        dlat_m = (plat - clat) * 111320
        proj = dlat_m * math.cos(face_rad) + dlon_m * math.sin(face_rad)
        if proj > best_proj:
            best_proj = proj
            best_pt = (plon, plat)
    face_lon = (clon + best_pt[0]) / 2.0
    face_lat = (clat + best_pt[1]) / 2.0
    return (face_lat, face_lon)


def _get_face_sample_points(
    building: Building,
    face_angle_deg: float,
    n: int = 3,
) -> List[Tuple[float, float]]:
    if n <= 1:
        return [_get_face_point_on_building(building, face_angle_deg)]
    face_lat, face_lon = _get_face_point_on_building(building, face_angle_deg)
    clon, clat = building.get_centroid()
    points: List[Tuple[float, float]] = []
    for i in range(n):
        t = (i + 1) / (n + 1)
        lat = clat + t * (face_lat - clat)
        lon = clon + t * (face_lon - clon)
        points.append((lat, lon))
    return points


def _compute_building_edges(footprint: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    if len(footprint) < 3:
        return []

    # Ensure closed ring
    ring = list(footprint)
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    # Compute centroid for determining outward direction
    n = len(ring) - 1
    cx = sum(p[0] for p in ring[:-1]) / n
    cy = sum(p[1] for p in ring[:-1]) / n

    edges = []
    for i in range(len(ring) - 1):
        p1 = ring[i]
        p2 = ring[i + 1]

        # Edge midpoint
        mx = (p1[0] + p2[0]) / 2
        my = (p1[1] + p2[1]) / 2

        # Edge direction (tangent)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-9:
            continue

        # Perpendicular (rotate 90° clockwise: (dx, dy) → (dy, -dx))
        # This gives "right side" normal
        nx = dy / length
        ny = -dx / length

        # Check if this normal points outward (away from centroid)
        to_centroid_x = cx - mx
        to_centroid_y = cy - my
        dot = nx * to_centroid_x + ny * to_centroid_y
        if dot > 0:
            # Normal points toward centroid, flip it
            nx, ny = -nx, -ny

        # Convert to compass bearing (0=N, 90=E, 180=S, 270=W)
        # atan2(dx, dy) where dx=east, dy=north
        bearing = math.degrees(math.atan2(nx, ny)) % 360

        # Nearest cardinal
        if bearing >= 315 or bearing < 45:
            cardinal = "N"
        elif bearing < 135:
            cardinal = "E"
        elif bearing < 225:
            cardinal = "S"
        else:
            cardinal = "W"

        edges.append({
            "bearing": round(bearing, 1),
            "cardinal": cardinal,
            "midpoint_lon": mx,
            "midpoint_lat": my,
            "p1": (p1[0], p1[1]),
            "p2": (p2[0], p2[1]),
        })

    return edges

def _edge_segment_sample_points(
    p1: Tuple[float, float], p2: Tuple[float, float], n: int = 5
) -> List[Tuple[float, float]]:
    """Lon/lat points along one footprint edge (inclusive endpoints)."""
    if n <= 1:
        return [((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)]
    return [
        (
            p1[0] + (p2[0] - p1[0]) * (i / (n - 1)),
            p1[1] + (p2[1] - p1[1]) * (i / (n - 1)),
        )
        for i in range(n)
    ]

class ShadowScheduler:
    TIMEZONE_OFFSET = 4  # UTC+4 (Dubai)
    SLOT_SAMPLE_INTERVAL_MINUTES = 1

    def __init__(
        self,
        mapbox_token: Optional[str] = None,
        temporal_resolution_minutes: int = 30,
        search_radius_meters: int = BUILDING_FETCH_RADIUS
    ):
        self.resolution = temporal_resolution_minutes
        self.mapbox_token = mapbox_token or MAPBOX_TOKEN
        self.search_radius = search_radius_meters

        self._shadow_calc = ShadowCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET
        )

        self._building_cache: Dict[str, List[Building]] = {}

    #Public API

    def find_optimal_schedule(
        self,
        task_name: str,
        lat: float,
        lon: float,
        location_name: str,
        task_duration_minutes: int,
        date: datetime,
        start_hour: int = 5,
        end_hour: int = 20,
        building_face: Optional[str] = None,
        face_angle: Optional[float] = None,
        recommendation_count: int = 5,
        client_buildings: Optional[List[Building]] = None
    ) -> ScheduleRecommendation:
        buildings = client_buildings if client_buildings else self._fetch_nearby_buildings(lat, lon)
        effective_face = _resolve_face_angle(face_angle, building_face)
        facade_mode = effective_face is not None

        print(f"[schedule] mode={'facade' if facade_mode else 'point'} "
              f"face_angle={effective_face} building_face={building_face} buildings={len(buildings)} "
              f"source={'client' if client_buildings else 'tilequery'}")
        for i, b in enumerate(buildings[:10]):
            print(f"  bldg[{i}] id={b.id} h={b.height:.0f}m pts={len(b.footprint)}")

        if facade_mode and effective_face is not None:
            face_points: List[Tuple[float, float]] = [(lat, lon)]
            facade_height = 30.0
            for b in buildings:
                bc_lon = sum(p[0] for p in b.footprint) / len(b.footprint)
                bc_lat = sum(p[1] for p in b.footprint) / len(b.footprint)
                if abs(bc_lat - lat) < 0.0005 and abs(bc_lon - lon) < 0.0005:
                    facade_height = b.height
                    face_points = _get_face_sample_points(b, effective_face, n=5)
                    break
            shade_series = self._build_shade_series_facade(
                date, start_hour, end_hour, TIME_STEP_MINUTES,
                lat, lon, effective_face, face_points, facade_height, buildings,
            )
            print(f"[schedule] pipeline: time_step={TIME_STEP_MINUTES}min steps={len(shade_series)}")
            slots = self._sliding_window_slots(
                shade_series, task_duration_minutes, TIME_STEP_MINUTES,
                effective_face, lat, lon,
            )
        else:
            slots = self._generate_time_slots(
                date, start_hour, end_hour, task_duration_minutes,
                lat, lon, buildings, building_face, face_angle
            )

        if not slots:
            raise ValueError(
                f"No valid time slots for {task_name} on {date.date()} "
                f"between {start_hour}:00-{end_hour}:00"
            )

        # Check if all slots are always-self-shaded (e.g., North-facing facade)
        all_self_shaded = all(s.is_always_self_shaded for s in slots if s.total_samples > 0)

        if all_self_shaded and facade_mode:
            # When all slots have 100% natural shade, rank by sun altitude (lower = cooler)
            # This gives early morning and late afternoon slots preference
            slots.sort(key=lambda s: s.sun_altitude)
            print(f"[schedule] All slots self-shaded, ranking by sun altitude (lower=better)")
        else:
            # Normal ranking: highest shade percentage first
            slots.sort(key=lambda s: s.shadow_percentage, reverse=True)

        best = slots[0]
        alternatives = self._pick_diversified_alternatives(
            slots, best, recommendation_count - 1
        )

        display_face = building_face or ( _face_angle_to_cardinal(effective_face) if effective_face is not None else None )
        reason = self._generate_reason(best, location_name, display_face, len(buildings))
        alternative_reasons = [
            self._generate_reason(slot, location_name, display_face, len(buildings))
            for slot in alternatives
        ]

        return ScheduleRecommendation(
            task_name=task_name,
            location_name=location_name,
            lat=lat,
            lon=lon,
            best_slot=best,
            alternatives=alternatives,
            total_evaluated=len(slots),
            recommendation_reason=reason,
            alternative_reasons=alternative_reasons,
            buildings_used=len(buildings),
            all_slots=slots,
        )

    def find_optimal_schedule_for_area(
        self,
        task_name: str,
        polygon_points: List[Tuple[float, float]],
        location_name: str,
        task_duration_minutes: int,
        date: datetime,
        start_hour: int = 5,
        end_hour: int = 20,
        recommendation_count: int = 5,
        client_buildings: Optional[List[Building]] = None
    ) -> ScheduleRecommendation:
        grid = self._sample_polygon_grid(polygon_points)
        if not grid:
            raise ValueError("Could not generate sample points inside the polygon")

        centroid_lat = sum(p[0] for p in polygon_points) / len(polygon_points)
        centroid_lon = sum(p[1] for p in polygon_points) / len(polygon_points)

        buildings = client_buildings if client_buildings else self._fetch_nearby_buildings(centroid_lat, centroid_lon)

        heights = [b.height for b in buildings]
        use_merged = SHAPELY_AVAILABLE and len(polygon_points) >= 3
        mode_str = "merged full-shadow area" if use_merged else f"{len(grid)} grid points"
        print(
            f"[area-schedule] {mode_str}, {len(buildings)} buildings "
            + (f"(heights: {min(heights):.0f}-{max(heights):.0f}m avg {sum(heights)/len(heights):.0f}m)" if heights else "")
        )

        # Use merged full-shadow area coverage when Shapely available (not just footprint)
        target_polygon_lonlat = [(p[1], p[0]) for p in polygon_points]  # (lon, lat) for Shapely
        slots = self._generate_area_time_slots(
            date, start_hour, end_hour, task_duration_minutes,
            grid, buildings,
            target_polygon_lonlat=target_polygon_lonlat,
        )

        if not slots:
            raise ValueError(
                f"No valid time slots for {task_name} on {date.date()} "
                f"between {start_hour}:00-{end_hour}:00"
            )

        slots.sort(key=lambda s: s.shadow_percentage, reverse=True)
        best = slots[0]
        alternatives = self._pick_diversified_alternatives(
            slots, best, recommendation_count - 1
        )
        reason = self._generate_reason(best, location_name, None, len(buildings))
        alternative_reasons = [
            self._generate_reason(slot, location_name, None, len(buildings))
            for slot in alternatives
        ]

        # Build footprint GeoJSON for frontend overlay ("buildings considered for this polygon")
        footprint_features = []
        for b in buildings:
            fp_ring = [[p[0], p[1]] for p in b.footprint]
            if len(fp_ring) >= 3:
                if fp_ring[0] != fp_ring[-1]:
                    fp_ring.append(fp_ring[0])
                footprint_features.append({
                    "type": "Feature",
                    "properties": {"building_id": b.id, "height": b.height, "name": b.name or "building"},
                    "geometry": {"type": "Polygon", "coordinates": [fp_ring]},
                })
        buildings_footprints_geojson = (
            {"type": "FeatureCollection", "features": footprint_features}
            if footprint_features else None
        )

        return ScheduleRecommendation(
            task_name=task_name,
            location_name=location_name,
            lat=centroid_lat,
            lon=centroid_lon,
            best_slot=best,
            alternatives=alternatives,
            total_evaluated=len(slots),
            recommendation_reason=reason,
            alternative_reasons=alternative_reasons,
            buildings_used=len(buildings),
            buildings_footprints_geojson=buildings_footprints_geojson,
        )

    def _pick_diversified_alternatives(
        self,
        slots: List[TimeSlot],
        best: TimeSlot,
        count: int,
    ) -> List[TimeSlot]:
        if count <= 0:
            return []
        rest = [s for s in slots if (s.start, s.end) != (best.start, best.end)]
        if not rest:
            return []

        # Time-of-day buckets (hour of slot start): early AM, late AM, early PM, late PM
        def bucket(slot: TimeSlot) -> int:
            h = slot.start.hour + slot.start.minute / 60.0
            if h < 8:
                return 0
            if h < 12:
                return 1
            if h < 15:
                return 2
            return 3

        # Best slot per bucket (by shadow %)
        by_bucket: Dict[int, TimeSlot] = {}
        for s in rest:
            b = bucket(s)
            if b not in by_bucket or s.shadow_percentage > by_bucket[b].shadow_percentage:
                by_bucket[b] = s

        # Take one per bucket in order, then fill with next best by shadow %
        chosen: List[TimeSlot] = []
        for b in range(4):
            if len(chosen) >= count:
                break
            if b in by_bucket and by_bucket[b] not in chosen:
                chosen.append(by_bucket[b])

        # Fill remaining with highest shadow % not yet chosen
        by_pct = sorted(rest, key=lambda s: s.shadow_percentage, reverse=True)
        for s in by_pct:
            if len(chosen) >= count:
                break
            if s not in chosen:
                chosen.append(s)

        return chosen[:count]

    # ─── Polygon grid sampling ─────────────────────────────────────

    def _sample_polygon_grid(
        self,
        polygon: List[Tuple[float, float]],
        target_count: int = 50
    ) -> List[Tuple[float, float]]:
        """
        Generate a grid of sample points inside the polygon.

        Creates a bounding-box grid and filters to points that pass the
        ray-casting point-in-polygon test. Aims for ~target_count points.
        """
        if len(polygon) < 3:
            return []

        lats = [p[0] for p in polygon]
        lons = [p[1] for p in polygon]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)

        side = max(4, int(target_count ** 0.5))
        lat_step = (max_lat - min_lat) / side if max_lat != min_lat else 0.0001
        lon_step = (max_lon - min_lon) / side if max_lon != min_lon else 0.0001

        poly_lonlat = [(p[1], p[0]) for p in polygon]

        grid: List[Tuple[float, float]] = []
        lat = min_lat + lat_step / 2
        while lat < max_lat:
            lon = min_lon + lon_step / 2
            while lon < max_lon:
                if _point_in_polygon(lon, lat, poly_lonlat):
                    grid.append((lat, lon))
                lon += lon_step
            lat += lat_step

        if not grid:
            grid.append((
                (min_lat + max_lat) / 2,
                (min_lon + max_lon) / 2
            ))

        return grid

    def _calculate_slot_shadow_merged_area(
        self,
        start: datetime,
        end: datetime,
        target_polygon_lonlat: List[Tuple[float, float]],
        buildings: List[Building],
    ) -> Tuple[float, float, float]:
        """
        Compute shadow coverage for a slot using merged full shadow polygons over
        the target area: (merged_shadow ∩ target).area / target.area * 100.
        Samples at adaptive intervals over the slot; returns the average coverage
        so the reported shade % reflects typical conditions as the sun moves.
        """
        if not SHAPELY_AVAILABLE or not target_polygon_lonlat or len(target_polygon_lonlat) < 3:
            return 0.0, 0.0, 0.0
        centroid_lon = sum(p[0] for p in target_polygon_lonlat) / len(target_polygon_lonlat)
        centroid_lat = sum(p[1] for p in target_polygon_lonlat) / len(target_polygon_lonlat)
        # Footprints are sun-invariant; include them so area on buildings counts as shaded (matches visual)
        merged_footprints = self._shadow_calc.get_merged_footprint_geometry(buildings)
        slot_minutes = int((end - start).total_seconds() / 60)
        step_min = get_adaptive_sample_interval_minutes(slot_minutes)
        coverages: List[float] = []
        altitudes: List[float] = []
        azimuths: List[float] = []
        # Cache merged cast by sun bucket so we don't recompute Shapely for every minute
        cast_cache: Dict[tuple, Any] = {}
        t = start
        interval = timedelta(minutes=step_min)
        while t <= end:
            sun = self._get_sun_position(t, centroid_lat, centroid_lon)
            altitudes.append(sun.altitude)
            azimuths.append(sun.azimuth)
            if sun.is_daylight and sun.altitude > 0:
                bucket = get_sun_bucket(sun.azimuth, sun.altitude)
                if bucket not in cast_cache:
                    cast_cache[bucket] = self._shadow_calc.get_merged_cast_shadow_geometry(
                        buildings, sun, shadow_direction_override=None
                    )
                merged_cast = cast_cache[bucket]
                if merged_cast is not None and merged_cast.is_valid and not merged_cast.is_empty:
                    cov = self._shadow_calc.shadow_coverage_over_area(
                        merged_cast, target_polygon_lonlat, merged_footprint_geom=merged_footprints
                    )
                    coverages.append(cov)
                else:
                    cov = self._shadow_calc.shadow_coverage_over_area(
                        None, target_polygon_lonlat, merged_footprint_geom=merged_footprints
                    ) if merged_footprints else 0.0
                    coverages.append(cov)
            else:
                coverages.append(100.0)  # night = fully shaded
            t += interval
        n = len(coverages)
        if n == 0:
            return 0.0, 0.0, 0.0
        # Average coverage over the slot so shade % reflects typical conditions as sun moves
        avg_shadow = sum(coverages) / n
        avg_alt = sum(altitudes) / n
        avg_az = sum(azimuths) / n
        return avg_shadow, avg_alt, avg_az

    def _generate_area_time_slots(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        duration_minutes: int,
        grid_points: List[Tuple[float, float]],
        buildings: List[Building],
        target_polygon_lonlat: Optional[List[Tuple[float, float]]] = None,
    ) -> List[TimeSlot]:
        """
        Generate time slots. When target_polygon_lonlat is provided and Shapely
        is available, use merged full-shadow area coverage over the polygon;
        otherwise average shadow over grid points (point-in-polygon).
        """
        slots: List[TimeSlot] = []
        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_limit = datetime(date.year, date.month, date.day, end_hour, 0, 0)
        use_merged_area = (
            SHAPELY_AVAILABLE
            and target_polygon_lonlat is not None
            and len(target_polygon_lonlat) >= 3
        )
        # Fewer slots when duration is long (e.g. 45 min step for 120 min duration)
        slot_step = get_slot_step_for_long_duration(duration_minutes, self.resolution)

        while current + timedelta(minutes=duration_minutes) <= end_limit:
            slot_end = current + timedelta(minutes=duration_minutes)

            if use_merged_area:
                avg_shadow, avg_alt, avg_az = self._calculate_slot_shadow_merged_area(
                    current, slot_end, target_polygon_lonlat, buildings
                )
            else:
                point_shadows: List[float] = []
                all_alts: List[float] = []
                all_azs: List[float] = []
                for lat, lon in grid_points:
                    pct, alt, az, _ = self._calculate_slot_shadow(
                        current, slot_end, lat, lon, buildings
                    )
                    point_shadows.append(pct)
                    all_alts.append(alt)
                    all_azs.append(az)
                avg_shadow = sum(point_shadows) / len(point_shadows)
                avg_alt = sum(all_alts) / len(all_alts)
                avg_az = sum(all_azs) / len(all_azs)

            slots.append(TimeSlot(
                start=current,
                end=slot_end,
                shadow_percentage=avg_shadow,
                sun_altitude=avg_alt,
                sun_azimuth=avg_az
            ))

            current += timedelta(minutes=slot_step)

        return slots

    # ─── Building data fetching ─────────────────────────────────────

    def _fetch_nearby_buildings(self, lat: float, lon: float) -> List[Building]:
        """
        Fetch real building footprints and heights from Mapbox Tilequery API.
        Falls back to SAMPLE_BUILDINGS from config if the API is unavailable.
        """
        cache_key = f"{round(lat, 4)},{round(lon, 4)}"
        if cache_key in self._building_cache:
            return self._building_cache[cache_key]

        buildings = self._query_mapbox_buildings(lat, lon)

        if not buildings:
            buildings = self._get_fallback_buildings(lat, lon)

        self._building_cache[cache_key] = buildings
        return buildings

    def _query_mapbox_buildings(self, lat: float, lon: float) -> List[Building]:
        """
        Query Mapbox Tilequery API for building polygons near a point.

        Uses the mapbox-streets-v8 tileset which includes the `building` layer
        with `height` / `min_height` extrusion attributes.
        """
        url = (
            f"https://api.mapbox.com/v4/mapbox.mapbox-streets-v8/tilequery/"
            f"{lon},{lat}.json"
        )
        params = {
            "radius": self.search_radius,
            "layers": "building",
            "limit": 50,
            "access_token": self.mapbox_token
        }

        try:
            resp = http_client.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"mapbox tilequery failed ({e}), using fallback buildings")
            return []

        buildings: List[Building] = []
        for i, feature in enumerate(data.get("features", [])):
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
                id=f"mb_{i}",
                footprint=footprint,
                height=effective_height,
                name=props.get("type", "building")
            ))

        return buildings

    def _get_fallback_buildings(self, lat: float, lon: float) -> List[Building]:
        """Return SAMPLE_BUILDINGS from config that are within range."""
        nearby: List[Building] = []
        for bdata in SAMPLE_BUILDINGS:
            fp = bdata["footprint"]
            centroid_lon = sum(p[0] for p in fp) / len(fp)
            centroid_lat = sum(p[1] for p in fp) / len(fp)
            dist = _haversine(lat, lon, centroid_lat, centroid_lon)
            if dist <= self.search_radius * 3:
                nearby.append(Building(
                    id=bdata["id"],
                    footprint=[(p[0], p[1]) for p in fp],
                    height=bdata["height"],
                    name=bdata.get("name")
                ))
        return nearby

    # ─── Pipeline: discretize time → shade series → sliding window ────────

    def _effective_shade_at_time_facade(
        self,
        t: datetime,
        lat: float,
        lon: float,
        face_angle: float,
        face_points: List[Tuple[float, float]],
        facade_height: float,
        buildings: List[Building],
        debug_at_times: Optional[List[datetime]] = None,
    ) -> float:
        """
        Shade score for facade: continuous formula, no hard cap.
        Fractional cast_shadow = fraction of face points blocked; exposure = cos(angle_diff).
        effective_shade = cast_shadow + (1 - cast_shadow) * (1 - exposure).
        """
        sun = self._get_sun_position(t, lat, lon)
        if not sun.is_daylight or sun.altitude <= 0:
            return 1.0

        angle_diff = abs(sun.azimuth - face_angle)
        angle_diff = min(angle_diff, 360.0 - angle_diff)
        exposure = max(0.0, math.cos(math.radians(angle_diff)))

        # Fraction of face points in shadow (0..1). Only skip neighbor checks when the sun
        # is strictly behind the vertical plane (obtuse horizontal angle). At exactly 90°
        # (grazing) we still sample neighbors — e.g. West can sit in a tall building's shadow
        # while East stays sunlit at midday.
        if angle_diff > 90:
            fraction_blocked = 1.0
        else:
            blocked = sum(
                1 for (face_lat, face_lon) in face_points
                if self._is_face_blocked(face_lat, face_lon, facade_height, buildings, sun, verbose=False)
            )
            fraction_blocked = blocked / len(face_points) if face_points else 0.0

        effective_shade = fraction_blocked + (1.0 - fraction_blocked) * (1.0 - exposure)

        do_debug = debug_at_times and any(
            abs((t - tt).total_seconds()) < 60 for tt in debug_at_times
        )
        if do_debug:
            print("---- DEBUG ----")
            print("Time:", t.strftime("%H:%M"))
            print("Facade:", face_angle)
            print("Sun:", sun.azimuth)
            print("Angle diff:", angle_diff)
            print("Exposure:", exposure)
            print("Cast shadow (fraction, %d pts):" % len(face_points), round(fraction_blocked, 4))
            print("Effective shade:", round(effective_shade, 4))
        return effective_shade

    def _build_shade_series_facade(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        time_step_minutes: int,
        lat: float,
        lon: float,
        face_angle: float,
        face_points: List[Tuple[float, float]],
        facade_height: float,
        buildings: List[Building],
    ) -> List[Tuple[datetime, float]]:
        """Step 1–3: Discretize time at time_step_minutes, compute shade at each step (Option C: avg over face_points)."""
        series: List[Tuple[datetime, float]] = []
        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_limit = datetime(date.year, date.month, date.day, end_hour, 0, 0)
        step = timedelta(minutes=time_step_minutes)
        debug_times = [
            datetime(date.year, date.month, date.day, 9, 0, 0),
            datetime(date.year, date.month, date.day, 11, 30, 0),
            datetime(date.year, date.month, date.day, 14, 0, 0),
            datetime(date.year, date.month, date.day, 14, 30, 0),
            datetime(date.year, date.month, date.day, 15, 0, 0),
            datetime(date.year, date.month, date.day, 15, 30, 0),
        ]
        while current <= end_limit:
            shade = self._effective_shade_at_time_facade(
                current, lat, lon, face_angle, face_points, facade_height, buildings,
                debug_at_times=debug_times,
            )
            series.append((current, shade))
            current += step
        return series

    def _sliding_window_slots(
        self,
        shade_series: List[Tuple[datetime, float]],
        duration_minutes: int,
        time_step_minutes: int,
        face_angle_used: Optional[float],
        lat: float,
        lon: float,
    ) -> List[TimeSlot]:
        """Step 4: Sliding window over shade series; each window = one candidate slot.
        Uses shade at slot start (not window average) so the displayed % matches the map
        when the user sets the time to the slot start (e.g. 11:30 slot shows shade at 11:30).
        """
        if not shade_series:
            return []
        steps_per_window = max(1, duration_minutes // time_step_minutes)
        slots: List[TimeSlot] = []
        times = [s[0] for s in shade_series]
        shades = [s[1] for s in shade_series]
        for i in range(len(shade_series) - steps_per_window + 1):
            window_shades = shades[i : i + steps_per_window]
            shade_at_start = window_shades[0]
            start_dt = times[i]
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            mid_dt = start_dt + timedelta(minutes=duration_minutes // 2)
            sun = self._get_sun_position(mid_dt, lat, lon)
            slots.append(
                TimeSlot(
                    start=start_dt,
                    end=end_dt,
                    shadow_percentage=shade_at_start * 100.0,
                    sun_altitude=sun.altitude,
                    sun_azimuth=sun.azimuth,
                    self_shaded_samples=0,
                    ext_blocked_samples=0,
                    sun_hit_samples=0,
                    total_samples=len(window_shades),
                    face_angle_used=face_angle_used,
                )
            )
        return slots

    def _generate_time_slots(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        duration_minutes: int,
        lat: float,
        lon: float,
        buildings: List[Building],
        building_face: Optional[str] = None,
        face_angle: Optional[float] = None
    ) -> List[TimeSlot]:
        """Generate all candidate time slots with real shadow percentages."""
        slots: List[TimeSlot] = []
        slot_step = get_slot_step_for_long_duration(duration_minutes, self.resolution)

        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_limit = datetime(date.year, date.month, date.day, end_hour, 0, 0)

        effective_face = _resolve_face_angle(face_angle, building_face)

        while current + timedelta(minutes=duration_minutes) <= end_limit:
            slot_end = current + timedelta(minutes=duration_minutes)

            shadow_pct, avg_alt, avg_az, debug_info = self._calculate_slot_shadow(
                current, slot_end, lat, lon, buildings, building_face, face_angle
            )

            slots.append(TimeSlot(
                start=current,
                end=slot_end,
                shadow_percentage=shadow_pct,
                sun_altitude=avg_alt,
                sun_azimuth=avg_az,
                self_shaded_samples=debug_info.get("self_shaded", 0),
                ext_blocked_samples=debug_info.get("ext_blocked", 0),
                sun_hit_samples=debug_info.get("sun_hit", 0),
                total_samples=debug_info.get("total_samples", 0),
                face_angle_used=effective_face,
            ))

            current += timedelta(minutes=slot_step)

        return slots

    def _calculate_slot_shadow(
        self,
        start: datetime,
        end: datetime,
        lat: float,
        lon: float,
        buildings: List[Building],
        building_face: Optional[str] = None,
        face_angle: Optional[float] = None
    ) -> Tuple[float, float, float, Dict[str, Any]]:
        """
        Calculate shadow coverage for a time slot. Samples at adaptive intervals
        over the slot; returns the average coverage so the reported shade %
        reflects typical conditions as the sun moves.

        For AREA/POINT mode: uses ground-plane shadow polygons and PIP tests.
        For FACADE mode: uses 3D elevation-aware analysis with full face angle (0-360).

        Returns: (shadow_percentage 0-100, avg_sun_altitude, avg_sun_azimuth, debug_info)
        """
        per_sample_pct: List[float] = []
        altitudes: List[float] = []
        azimuths: List[float] = []

        effective_face_angle = _resolve_face_angle(face_angle, building_face)
        facade_mode = effective_face_angle is not None

        # For facade mode: find the selected building and a point ON the selected face (not center)
        facade_height = 0.0
        face_lat, face_lon = lat, lon  # default for non-facade
        if facade_mode:
            for b in buildings:
                bc_lon = sum(p[0] for p in b.footprint) / len(b.footprint)
                bc_lat = sum(p[1] for p in b.footprint) / len(b.footprint)
                if abs(bc_lat - lat) < 0.0005 and abs(bc_lon - lon) < 0.0005:
                    facade_height = b.height
                    face_lat, face_lon = _get_face_point_on_building(b, effective_face_angle)
                    break
            if facade_height == 0:
                facade_height = 30.0

        self_shaded = 0
        ext_blocked = 0
        sun_hit = 0
        night_samples = 0
        slot_minutes = int((end - start).total_seconds() / 60)
        step_min = get_adaptive_sample_interval_minutes(slot_minutes)
        interval = timedelta(minutes=step_min)

        current = start
        while current <= end:
            sun = self._get_sun_position(current, lat, lon)
            altitudes.append(sun.altitude)
            azimuths.append(sun.azimuth)

            if not sun.is_daylight or sun.altitude <= 0:
                per_sample_pct.append(100.0)
                night_samples += 1
                current += interval
                continue

            in_shadow = False
            sample_pct = 100.0
            if facade_mode and effective_face_angle is not None:
                # ── Facade mode: orientation exposure + cast shadow → effective_shade ──
                angle_diff = abs(sun.azimuth - effective_face_angle)
                angle_diff = min(angle_diff, 360.0 - angle_diff)
                exposure = max(0.0, math.cos(math.radians(angle_diff)))
                if angle_diff > 90:
                    cast_shadow = 1.0
                    self_shaded += 1
                    in_shadow = True
                else:
                    do_verbose = len(per_sample_pct) < 2
                    if self._is_face_blocked(
                        face_lat, face_lon, facade_height, buildings, sun,
                        verbose=do_verbose,
                    ):
                        cast_shadow = 1.0
                        ext_blocked += 1
                        in_shadow = True
                    else:
                        cast_shadow = 0.0
                        sun_hit += 1
                effective_shade = cast_shadow + (1.0 - cast_shadow) * (1.0 - exposure)
                sample_pct = 100.0 * effective_shade
            else:
                # ── Area / point mode: ground-plane shadow PIP ──
                in_shadow = self._is_point_in_any_shadow(lat, lon, buildings, sun)
                sample_pct = 100.0 if in_shadow else 0.0

            per_sample_pct.append(sample_pct)
            current += interval

        total_samples = len(per_sample_pct)
        # Average coverage over the slot so shade % reflects typical conditions as sun moves
        shadow_pct = (sum(per_sample_pct) / total_samples) if total_samples > 0 else 0.0
        avg_alt = sum(altitudes) / len(altitudes) if altitudes else 0
        avg_az = sum(azimuths) / len(azimuths) if azimuths else 0

        # Debug info for facade mode
        debug_info = {
            "face_angle": effective_face_angle,
            "total_samples": total_samples,
            "self_shaded": self_shaded,
            "ext_blocked": ext_blocked,
            "sun_hit": sun_hit,
            "night": night_samples,
        }

        if facade_mode and total_samples > 0:
            display_face = building_face or _face_angle_to_cardinal(effective_face_angle)
            print(
                f"  [{start.strftime('%H:%M')}-{end.strftime('%H:%M')}] "
                f"face={display_face}({effective_face_angle:.0f}deg) "
                f"h={facade_height:.0f}m midpt={facade_height/2:.0f}m | "
                f"self-shaded={self_shaded} ext-blocked={ext_blocked} "
                f"sun-hit={sun_hit} night={night_samples} "
                f"/ {total_samples} -> shadow={shadow_pct:.0f}% "
                f"| sun az={avg_az:.0f} alt={avg_alt:.0f}"
            )

        return shadow_pct, avg_alt, avg_az, debug_info

    def _is_face_blocked(
        self,
        face_lat: float,
        face_lon: float,
        face_building_height: float,
        buildings: List[Building],
        sun: SunPosition,
        verbose: bool = False,
    ) -> bool:
        """
        3D check: can any nearby building block the sun from reaching
        the face at its mid-height?

        From the face midpoint (at half building height), we look toward
        the sun. If a neighboring building's top rises above the sun's
        elevation angle as seen from the face midpoint, it blocks the sun.
        """
        view_height = face_building_height / 2
        cos_lat = math.cos(math.radians(face_lat))

        for b in buildings:
            bc_lon = sum(p[0] for p in b.footprint) / len(b.footprint)
            bc_lat = sum(p[1] for p in b.footprint) / len(b.footprint)

            dx = (bc_lon - face_lon) * 111320 * cos_lat
            dy = (bc_lat - face_lat) * 111320
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 5:
                continue

            bearing = math.degrees(math.atan2(dx, dy)) % 360
            angle_to_sun = abs(((bearing - sun.azimuth + 180) % 360) - 180)
            if angle_to_sun > 30:
                continue

            height_diff = b.height - view_height
            if height_diff <= 0:
                continue

            apparent_elev = math.degrees(math.atan2(height_diff, dist))
            if apparent_elev > sun.altitude:
                if verbose:
                    print(
                        f"    BLOCKED by {b.id} ({b.height:.0f}m) "
                        f"dist={dist:.0f}m bearing={bearing:.0f}deg "
                        f"apparent_elev={apparent_elev:.1f}deg > sun_alt={sun.altitude:.1f}deg"
                    )
                return True

        return False

    def _is_point_in_any_shadow(
        self,
        lat: float,
        lon: float,
        buildings: List[Building],
        sun: SunPosition
    ) -> bool:
        """
        Check if (lat, lon) falls inside any building's projected shadow polygon.

        For each building the ShadowCalculator computes the ground-plane shadow
        polygon from its footprint, height, and current sun position. We then
        run a ray-casting point-in-polygon test.
        """
        for building in buildings:
            polygon = self._shadow_calc.calculate_shadow_polygon(building, sun)
            if polygon and _point_in_polygon(lon, lat, polygon):
                return True
        return False

    # ─── Sun position helper ────────────────────────────────────────
    # Uses the same simplified NOAA algorithm as the frontend
    # (sunCalculations.ts) so computed shadow polygons match
    # Mapbox's rendered 3D shadows exactly.

    def _get_sun_position(self, dt: datetime, lat: float, lon: float) -> SunPosition:
        import math
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

    # ─── Recommendation text ────────────────────────────────────────

    def _generate_reason(
        self,
        slot: TimeSlot,
        location_name: str,
        building_face: Optional[str] = None,
        building_count: int = 0
    ) -> str:
        """Generate human-readable recommendation based on real shadow data."""
        time_range = slot.time_label
        shadow = round(slot.shadow_percentage)
        alt = round(slot.sun_altitude, 1)

        source = (
            f"based on 3D shadow projection from {building_count} nearby buildings"
            if building_count
            else "based on sun position analysis"
        )

        if building_face:
            face_name = {"N": "North", "E": "East", "S": "South", "W": "West"}.get(
                building_face.upper(), building_face
            )

            # Explain WHY the facade has this shade percentage
            if slot.total_samples > 0:
                self_pct = round(100 * slot.self_shaded_samples / slot.total_samples)
                ext_pct = round(100 * slot.ext_blocked_samples / slot.total_samples)
                sun_pct = round(100 * slot.sun_hit_samples / slot.total_samples)

                if slot.is_always_self_shaded:
                    # Facade never receives direct sun (e.g., North face in Northern Hemisphere)
                    return (
                        f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                        f"This facade never receives direct sunlight (sun always behind building). "
                        f"All time slots have 100% natural shade. Sun altitude {alt}deg."
                    )
                elif self_pct > 0 and ext_pct > 0:
                    return (
                        f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                        f"{shadow}% shade ({self_pct}% self-shaded, {ext_pct}% blocked by buildings). "
                        f"{source}, sun altitude {alt}deg."
                    )
                elif ext_pct > 0:
                    return (
                        f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                        f"{shadow}% shade (blocked by nearby buildings). {source}, sun altitude {alt}deg."
                    )
                elif sun_pct > 0:
                    return (
                        f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                        f"{shadow}% shade ({sun_pct}% direct sun exposure). {source}, sun altitude {alt}deg."
                    )

            return (
                f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                f"{shadow}% shadow coverage ({source}, sun altitude {alt}deg)."
            )

        if shadow >= 81:
            desc = "Very High Shade"
        elif shadow >= 61:
            desc = "High Shade"
        elif shadow >= 41:
            desc = "Moderate Shade"
        elif shadow >= 21:
            desc = "Low Shade"
        else:
            desc = "Very Low Shade"

        return (
            f"Recommended {time_range} at {location_name}. "
            f"{shadow}% shadow coverage ({desc}). {source.capitalize()}."
        )


# ─── Geometry helpers (module-level for reuse) ──────────────────────────────

def _point_in_polygon(
    x: float, y: float,
    polygon: List[Tuple[float, float]]
) -> bool:
    """
    Ray-casting point-in-polygon test.

    Casts a horizontal ray from (x, y) in the +x direction and counts edge
    crossings. An odd count means the point is inside.

    Args:
        x: longitude of test point
        y: latitude of test point
        polygon: list of (lon, lat) vertices
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _window_sample_times(t_start: datetime, duration_minutes: int) -> List[datetime]:
    """Evenly spaced sample times from window start through end (inclusive).

    Uses about one sample every **10 minutes** (not every 5) so a 60 min task has
    ~7 time steps (edge×time counts scale accordingly), while keeping a floor of
    3 samples and a cap for performance.
    """
    if duration_minutes <= 0:
        return [t_start]
    n = max(3, min(25, duration_minutes // 10 + 1))
    if n == 1:
        return [t_start]
    return [
        t_start + timedelta(minutes=duration_minutes * (i / (n - 1)))
        for i in range(n)
    ]


def _circular_mean_azimuth_deg(azimuths: List[float]) -> float:
    if not azimuths:
        return 0.0
    sx = sum(math.sin(math.radians(a)) for a in azimuths)
    cx = sum(math.cos(math.radians(a)) for a in azimuths)
    return _normalize_azimuth_deg(math.degrees(math.atan2(sx, cx)))


def _circular_abs_diff_deg(a: float, b: float) -> float:
    """Smallest angle between two compass bearings in [0, 180]."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _normalize_azimuth_deg(azimuth: float) -> float:
    """Compass azimuth in [0, 360)."""
    x = azimuth % 360.0
    return x + 360.0 if x < 0 else x


# Cardinal outward normals (same convention as _resolve_face_angle / api_v2)
_FACADE_CARDINALS: List[Tuple[str, float]] = [
    ("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0),
]

_FACE_FULL_NAME = {"N": "North", "E": "East", "S": "South", "W": "West"}


def _pick_building_for_facade(
    lat: float, lon: float, buildings: List[Building], max_dist_m: float = 120.0
) -> Optional[Building]:
    """Building whose footprint centroid is closest to the site, within max_dist_m."""
    if not buildings:
        return None
    best: Optional[Building] = None
    best_d = max_dist_m + 1.0
    for b in buildings:
        clon, clat = b.get_centroid()
        d = _haversine(lat, lon, clat, clon)
        if d < best_d:
            best_d = d
            best = b
    return best if best is not None and best_d <= max_dist_m else None


def recommend_facades_for_fixed_window(
    lat: float,
    lon: float,
    date: datetime,
    start_hour: int,
    start_minute: int,
    duration_minutes: int,
    buildings: Optional[List[Building]] = None,
) -> Dict[str, Any]:
    """
    Rank N/E/S/W for a fixed same-day work window.

    Shade and neighbor occlusion are **averaged** over evenly spaced samples from
    ``window_start`` through ``window_end`` so sun position and shadows from
    nearby buildings change over the interval.

    When ``buildings`` is provided and a target footprint is found near (lat, lon),
    uses the same effective shade model as facade scheduling: self-shade when the sun
    is behind the wall, plus neighbor-building occlusion along sun rays at sample
    points on each cardinal face.

    Facades are ranked by **effective shade** (geometry plus neighbor shadows).
    Sun–wall separation is only a tie-breaker, not a rule that the sun-facing
    cardinal must rank last.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")

    t_start = datetime(date.year, date.month, date.day, start_hour, start_minute, 0)
    t_end = t_start + timedelta(minutes=duration_minutes)
    if t_end.date() != t_start.date():
        raise ValueError("Work window must start and end on the same calendar day")

    sample_times = _window_sample_times(t_start, duration_minutes)
    scheduler = ShadowScheduler()
    b_list = buildings if buildings else []
    target = _pick_building_for_facade(lat, lon, b_list) if b_list else None
    ranking_model = "building_3d" if target is not None else "sun_geometry"

    acc_shade: Dict[str, List[float]] = {face: [] for face, _ in _FACADE_CARDINALS}
    acc_neighbor: Dict[str, List[float]] = {face: [] for face, _ in _FACADE_CARDINALS}
    acc_sep: Dict[str, List[float]] = {face: [] for face, _ in _FACADE_CARDINALS}
    acc_ad: Dict[str, List[float]] = {face: [] for face, _ in _FACADE_CARDINALS}
    sun_azimuths: List[float] = []
    sun_alts: List[float] = []
    daylight_samples = 0

    for t in sample_times:
        sun = scheduler._get_sun_position(t, lat, lon)
        if not sun.is_daylight or sun.altitude <= 0:
            continue
        daylight_samples += 1
        sun_azimuths.append(float(sun.azimuth))
        sun_alts.append(float(sun.altitude))
        sun_az = _normalize_azimuth_deg(sun.azimuth)
        for face, fn in _FACADE_CARDINALS:
            sep = _circular_abs_diff_deg(sun_az, fn)
            if target is not None:
                h = max(1.0, float(target.height))
                face_points = _get_face_sample_points(target, fn, n=5)
            else:
                h = DEFAULT_BUILDING_HEIGHT
                face_points = [(lat, lon)]

            ad = abs(sun_az - fn)
            ad = min(ad, 360.0 - ad)

            npt = len(face_points)
            if npt == 0:
                neighbor_pct = 0.0
            else:
                blocked = sum(
                    1
                    for (flat, flon) in face_points
                    if scheduler._is_face_blocked(flat, flon, h, b_list, sun, verbose=False)
                )
                neighbor_pct = round(100.0 * blocked / npt, 1)

            exposure = max(0.0, math.cos(math.radians(ad)))
            neighbor_frac = neighbor_pct / 100.0
            shade_pct = round(
                100.0 * (neighbor_frac + (1.0 - neighbor_frac) * (1.0 - exposure)), 1
            )

            acc_shade[face].append(shade_pct)
            acc_neighbor[face].append(neighbor_pct)
            acc_sep[face].append(sep)
            acc_ad[face].append(ad)

    def _mean(xs: List[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    def _mean_round(xs: List[float], nd: int = 1) -> float:
        return round(_mean(xs), nd) if xs else 0.0

    t_mid = t_start + timedelta(minutes=duration_minutes / 2.0)
    rows: List[Dict[str, Any]] = []

    if daylight_samples == 0:
        t_sample = t_start
        sun = scheduler._get_sun_position(t_sample, lat, lon)
        sun_az = _normalize_azimuth_deg(sun.azimuth)
        print(
            f"\n[facade-recommend] no daylight in window; snapshot sun_az={sun_az:.1f}° "
            f"alt={sun.altitude:.1f}° at {t_sample.strftime('%H:%M')}"
        )
        for face, fn in _FACADE_CARDINALS:
            sep = _circular_abs_diff_deg(sun_az, fn)
            if target is not None:
                h = max(1.0, float(target.height))
                face_points = _get_face_sample_points(target, fn, n=5)
            else:
                h = DEFAULT_BUILDING_HEIGHT
                face_points = [(lat, lon)]
            ad = abs(sun_az - fn)
            ad = min(ad, 360.0 - ad)
            npt = len(face_points)
            if npt == 0:
                neighbor_pct = 0.0
            else:
                blocked = sum(
                    1
                    for (flat, flon) in face_points
                    if scheduler._is_face_blocked(flat, flon, h, b_list, sun, verbose=False)
                )
                neighbor_pct = round(100.0 * blocked / npt, 1)
            exposure = max(0.0, math.cos(math.radians(ad)))
            neighbor_frac = neighbor_pct / 100.0
            shade_pct = round(100.0 * (neighbor_frac + (1.0 - neighbor_frac) * (1.0 - exposure)), 1)
            self_shaded = ad > 90.0
            print(
                f"  {face}({fn}°): sep={sep:.1f}° ad={ad:.1f}° self_shaded={self_shaded} "
                f"shade={shade_pct}% neighbor={neighbor_pct}%"
            )
            rows.append({
                "face": face,
                "normal_deg": fn,
                "separation_deg": round(sep, 1),
                "shade_score_pct": shade_pct,
                "self_shaded": self_shaded,
                "neighbor_blocked_pct": neighbor_pct,
            })

        base = {
            "sample_time": t_mid.isoformat(),
            "window_start": t_start.isoformat(),
            "window_end": t_end.isoformat(),
            "window_schedule_points": len(sample_times),
            "window_average_samples": 0,
            "shade_averaged_over_window": False,
            "sun_azimuth": round(sun_az, 1),
            "sun_altitude": round(sun.altitude, 1),
            "ranking_model": ranking_model,
            "buildings_used": len(b_list),
            "is_daylight": bool(sun.is_daylight and sun.altitude > 0),
        }
        rows.sort(
            key=lambda x: (
                -x["shade_score_pct"],
                -float(x["neighbor_blocked_pct"]),
                -float(x["separation_deg"]),
                x["face"],
            ),
        )
        for i, r in enumerate(rows, start=1):
            r["rank"] = i
        base["ranked"] = rows
        base["recommended"] = None
        base["avoid"] = None
        base["second_best"] = None
        base["reason"] = (
            f"Across {t_start.strftime('%H:%M')}–{t_end.strftime('%H:%M')} the sun stays below the horizon. "
            "Direct-sun facade preference does not apply; cardinal facades are similar for this simple model."
        )
        return base

    sun_az_mean = _circular_mean_azimuth_deg(sun_azimuths)
    alt_mean = round(_mean(sun_alts), 1)

    for face, fn in _FACADE_CARDINALS:
        avg_shade = _mean_round(acc_shade[face], 1)
        avg_neighbor = _mean_round(acc_neighbor[face], 1)
        avg_sep = _mean_round(acc_sep[face], 1)
        avg_ad = _mean(acc_ad[face])
        self_shaded = avg_ad > 90.0
        print(
            f"  {face}({fn}°): avg sep={avg_sep:.1f}° avg ad={avg_ad:.1f}° self_shaded={self_shaded} "
            f"shade={avg_shade}% neighbor={avg_neighbor}% (n={daylight_samples})"
        )
        rows.append({
            "face": face,
            "normal_deg": fn,
            "separation_deg": avg_sep,
            "shade_score_pct": avg_shade,
            "self_shaded": self_shaded,
            "neighbor_blocked_pct": avg_neighbor,
        })

    print(
        f"\n[facade-recommend] window {t_start.strftime('%H:%M')}–{t_end.strftime('%H:%M')}: "
        f"{daylight_samples} daylight samples / {len(sample_times)} schedule points | "
        f"mean sun_az={sun_az_mean:.1f}° alt={alt_mean:.1f}°"
    )

    base = {
        "sample_time": t_mid.isoformat(),
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
        "window_schedule_points": len(sample_times),
        "window_average_samples": daylight_samples,
        "shade_averaged_over_window": True,
        "sun_azimuth": round(sun_az_mean, 1),
        "sun_altitude": alt_mean,
        "ranking_model": ranking_model,
        "buildings_used": len(b_list),
        "is_daylight": True,
    }

    # Rank by effective shade (geometry + neighbor shadows); separation tie-breaks only.
    _facade_rank_key = lambda r: (
        -r["shade_score_pct"],
        -float(r["neighbor_blocked_pct"]),
        -float(r["separation_deg"]),
        r["face"],
    )
    ordered = sorted(rows, key=_facade_rank_key)
    for i, r in enumerate(ordered, start=1):
        r["rank"] = i

    shade_worst = min(
        rows,
        key=lambda r: (
            r["shade_score_pct"],
            float(r["separation_deg"]),
            r["face"],
        ),
    )
    avoid_face = shade_worst["face"]

    print(f"  shade_worst={avoid_face} | ranking: {[r['face'] for r in ordered]}")
    base["ranked"] = ordered
    base["recommended"] = ordered[0]["face"]
    base["avoid"] = avoid_face
    second = ordered[1]["face"] if len(ordered) > 1 else None
    base["second_best"] = second
    print(f"  => recommended={base['recommended']} second_best={second} avoid={avoid_face}")

    # Complex buildings: average each edge's shade over daylight samples in the window.
    # cardinal_summary total_count / shaded_count are edge×time slots (e.g. 5 edges × 6 samples = 30).
    if target is not None and target.footprint and len(target.footprint) >= 3:
        edges = _compute_building_edges(target.footprint)
        if len(edges) > 4:
            h = max(1.0, float(target.height))
            edge_shades: List[List[float]] = [[] for _ in edges]
            edge_ad: List[List[float]] = [[] for _ in edges]
            edge_neighbor_blocked: List[List[bool]] = [[] for _ in edges]

            for t in sample_times:
                sun = scheduler._get_sun_position(t, lat, lon)
                if not sun.is_daylight or sun.altitude <= 0:
                    continue
                sun_az_edge = _normalize_azimuth_deg(sun.azimuth)
                for ei, edge in enumerate(edges):
                    bearing = edge["bearing"]
                    ad = abs(sun_az_edge - bearing)
                    ad = min(ad, 360.0 - ad)
                    # Same model as N/E/S/W cardinals: several points along the wall + continuous shade
                    # (single midpoint missed neighbor shadow on long façades vs map polygons).
                    p1 = edge["p1"]
                    p2 = edge["p2"]
                    pts = _edge_segment_sample_points(p1, p2, n=5)
                    npt = len(pts)
                    blocked = 0
                    for (plon, plat) in pts:
                        if scheduler._is_face_blocked(plat, plon, h, b_list, sun, verbose=False):
                            blocked += 1
                    neighbor_pct = round(100.0 * blocked / npt, 1)
                    exposure = max(0.0, math.cos(math.radians(ad)))
                    neighbor_frac = neighbor_pct / 100.0
                    shade_pct = round(
                        100.0 * (neighbor_frac + (1.0 - neighbor_frac) * (1.0 - exposure)), 1
                    )
                    edge_shades[ei].append(shade_pct)
                    edge_ad[ei].append(ad)
                    edge_neighbor_blocked[ei].append(neighbor_pct >= 50.0)

            edge_rows: List[Dict[str, Any]] = []
            for ei, edge in enumerate(edges):
                shades = edge_shades[ei]
                if not shades:
                    continue
                avg_shade = round(_mean(shades), 1)
                avg_ad = round(_mean(edge_ad[ei]), 1)
                nb = edge_neighbor_blocked[ei]
                nb_frac = sum(1 for b in nb if b) / len(nb)
                neighbor_blocked_maj = nb_frac >= 0.5
                self_shaded = avg_ad > 90.0
                edge_rows.append({
                    "bearing": edge["bearing"],
                    "cardinal": edge["cardinal"],
                    "separation_deg": avg_ad,
                    "shade_score_pct": avg_shade,
                    "self_shaded": self_shaded,
                    "neighbor_blocked": neighbor_blocked_maj,
                })

            SHADE_OK = 80.0
            ALL_SHADED_RATIO = 0.9
            CARDINAL_ORDER = ("N", "E", "S", "W")

            n_edges = len(edge_rows)
            n_time = max((len(s) for s in edge_shades), default=0)
            base["facade_edge_time_samples"] = n_time

            global_shaded = sum(1 for e in edge_rows if e["shade_score_pct"] >= SHADE_OK)

            cardinal_summary: List[Dict[str, Any]] = []
            for c in CARDINAL_ORDER:
                slot_total = 0
                slot_shaded = 0
                shade_sum = 0.0
                for ei, edge in enumerate(edges):
                    if edge["cardinal"] != c:
                        continue
                    shades_t = edge_shades[ei]
                    if not shades_t:
                        continue
                    slot_total += len(shades_t)
                    shade_sum += sum(shades_t)
                    slot_shaded += sum(1 for v in shades_t if v >= SHADE_OK)
                if slot_total == 0:
                    continue
                avg_shade = shade_sum / slot_total
                ratio = slot_shaded / slot_total
                cardinal_summary.append({
                    "cardinal": c,
                    "total_count": slot_total,
                    "shaded_count": slot_shaded,
                    "avg_shade_pct": round(avg_shade, 1),
                    "ratio": round(ratio, 3),
                })

            all_faces_largely_shaded = n_edges > 0 and (global_shaded / n_edges) >= ALL_SHADED_RATIO

            if all_faces_largely_shaded:
                recommended_cardinals = [c for c in CARDINAL_ORDER if any(e["cardinal"] == c for e in edge_rows)]
            else:
                # Rank by mean shade over the window, not by fraction of ≥80% slots (which favored
                # “spiky” directions and could rank North above a consistently shaded South wall).
                sorted_all = sorted(
                    cardinal_summary,
                    key=lambda r: (
                        -r["avg_shade_pct"],
                        -r["ratio"],
                        CARDINAL_ORDER.index(r["cardinal"]),
                    ),
                )
                recommended_cardinals = [r["cardinal"] for r in sorted_all[:2]]

            base["cardinal_summary"] = cardinal_summary
            base["recommended_cardinals"] = recommended_cardinals
            base["all_faces_largely_shaded"] = all_faces_largely_shaded

            avoid_row = min(
                cardinal_summary,
                key=lambda r: (
                    r["avg_shade_pct"],
                    -r["ratio"],
                    -r["shaded_count"],
                    CARDINAL_ORDER.index(r["cardinal"]),
                ),
            )
            avoid_c = avoid_row["cardinal"]
            base["avoid"] = avoid_c
            avoid_edges_c = [e for e in edge_rows if e["cardinal"] == avoid_c]
            if avoid_edges_c:
                worst_e = min(avoid_edges_c, key=lambda e: e["shade_score_pct"])
                base["avoid_edges"] = [{
                    "bearing": worst_e["bearing"],
                    "cardinal": worst_e["cardinal"],
                    "shade_score_pct": worst_e["shade_score_pct"],
                }]
                base["avoid_bearing"] = worst_e["bearing"]

            print(
                f"  complex building: {n_edges} edges x {n_time} time samples, "
                f"cardinal_summary={[ (r['cardinal'], r['shaded_count'], r['total_count']) for r in cardinal_summary ]} "
                f"recommended={recommended_cardinals} avoid(aggregate)={avoid_c} all_shaded={all_faces_largely_shaded}"
            )
    best = ordered[0]
    worst = shade_worst
    sb_line = ""
    if len(ordered) > 1:
        sb = ordered[1]
        extra = " — partly from nearby buildings" if sb["neighbor_blocked_pct"] > 5 else ""
        sb_line = (
            f" Second best: {_FACE_FULL_NAME[sb['face']]} (~{sb['shade_score_pct']}% average shade{extra})."
        )

    win_label = f"{t_start.strftime('%H:%M')}–{t_end.strftime('%H:%M')}"
    if base.get("cardinal_summary") and base.get("avoid"):
        _avoid_avg = next(
            (r["avg_shade_pct"] for r in base["cardinal_summary"] if r["cardinal"] == base["avoid"]),
            0.0,
        )
        _nts = base.get("facade_edge_time_samples") or 0
        _av_row = next((r for r in base["cardinal_summary"] if r["cardinal"] == base["avoid"]), None)
        _n_edge = (_av_row["total_count"] // _nts) if _av_row and _nts else None
        _slot_h = (
            f" ({_n_edge} edges × {_nts} time samples = {_av_row['total_count']} edge×time slots)"
            if _n_edge and _nts and _av_row
            else (f" ({_nts} time samples per edge)" if _nts else "")
        )
        avoid_expl = (
            f"{_FACE_FULL_NAME[base['avoid']]} has the lowest average shade on this footprint over {win_label}"
            f"{_slot_h} (~{_avoid_avg}% mean shade across those samples, including neighbor shadows)."
        )
    else:
        nb = float(worst["neighbor_blocked_pct"])
        nb_note = (
            ", including shading along sun rays from nearby buildings"
            if nb > 5.0
            else ""
        )
        avoid_expl = (
            f"{_FACE_FULL_NAME[worst['face']]} has the lowest shade score "
            f"(~{worst['shade_score_pct']}%{nb_note}; rank {worst['rank']})"
        )

    base["reason"] = (
        f"Averaged over {win_label} ({daylight_samples} daylight samples). "
        f"Mean sun ~{round(sun_az_mean, 1)}° az ({alt_mean}° alt). {avoid_expl}; "
        f"{_FACE_FULL_NAME[best['face']]} scores highest for shade "
        f"({best['shade_score_pct']}% average"
        f"{' including shadows from other buildings' if best['neighbor_blocked_pct'] > 5 and not best['self_shaded'] else ''}"
        f"{' — mostly self-shaded' if best['self_shaded'] else ''})."
        f"{sb_line}"
    )
    return base


def calculate_shadow_at_time(
    lat: float,
    lon: float,
    dt: datetime,
    building_face: Optional[str] = None,
    face_angle: Optional[float] = None
) -> Dict:
    """Calculate shadow state at a specific time and location using real 3D data."""
    scheduler = ShadowScheduler()
    buildings = scheduler._fetch_nearby_buildings(lat, lon)
    sun = scheduler._get_sun_position(dt, lat, lon)

    if not sun.is_daylight or sun.altitude <= 0:
        shadow_pct = 100.0
    else:
        is_self_shaded = False
        effective_face_angle = _resolve_face_angle(face_angle, building_face)
        if effective_face_angle is not None:
            angle_diff = abs(((sun.azimuth - effective_face_angle + 180) % 360) - 180)
            is_self_shaded = angle_diff > 90

        if is_self_shaded:
            shadow_pct = 100.0
        elif scheduler._is_point_in_any_shadow(lat, lon, buildings, sun):
            shadow_pct = 100.0
        else:
            shadow_pct = 0.0

    sunrise_str = sun.sunrise.strftime('%H:%M') if sun.sunrise else None
    sunset_str = sun.sunset.strftime('%H:%M') if sun.sunset else None

    return {
        "shadow_percentage": round(shadow_pct, 1),
        "sun_altitude": round(sun.altitude, 1),
        "sun_azimuth": round(sun.azimuth, 1),
        "is_daylight": sun.is_daylight,
        "sunrise": sunrise_str,
        "sunset": sunset_str,
        "buildings_analyzed": len(buildings)
    }
