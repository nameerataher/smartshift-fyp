"""
shadow_scheduler.py

Shadow-based scheduling engine for SmartShift.
Completely independent of the heat risk model (which lives on the dashboard).

Uses REAL 3D building data and shadow projection to determine shadow coverage:
1. Fetches nearby building footprints + heights from Mapbox vector tiles
2. Projects 3D shadow polygons using the ShadowCalculator (sun geometry + building height)
3. Uses ray-casting point-in-polygon tests to determine if the target location
   falls inside any shadow at each sampled time
4. Reports the fraction of time the location is in shadow during each candidate slot
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
import math
import requests as http_client

from shadow_calculator import ShadowCalculator, Building, SHAPELY_AVAILABLE
from solar_position import SolarPositionCalculator, SunPosition
from config import DUBAI, SAMPLE_BUILDINGS

def parse_client_buildings(raw_list: list) -> List[Building]:
    """Parse building dicts sent from the frontend into Building objects."""
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
    "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9"
    ".WI13BJqDyOu6G38-YP6hog"
)
DEFAULT_BUILDING_HEIGHT = 30.0  # meters – fallback for missing height data
BUILDING_FETCH_RADIUS = 300     # meters around the target point


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class TimeSlot:
    """A time slot with its shadow coverage."""
    start: datetime
    end: datetime
    shadow_percentage: float  # 0-100
    sun_altitude: float
    sun_azimuth: float

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    @property
    def time_label(self) -> str:
        return f"{self.start.strftime('%I:%M %p')} – {self.end.strftime('%I:%M %p')}"


@dataclass
class ScheduleRecommendation:
    """Scheduling recommendation with best and alternative slots."""
    task_name: str
    location_name: str
    lat: float
    lon: float

    best_slot: TimeSlot
    alternatives: List[TimeSlot] = field(default_factory=list)

    total_evaluated: int = 0
    recommendation_reason: str = ""
    buildings_used: int = 0

    def to_dict(self) -> Dict:
        """Convert to API response format."""
        return {
            "task_name": self.task_name,
            "location": {
                "name": self.location_name,
                "lat": self.lat,
                "lon": self.lon
            },
            "best_schedule": {
                "start_time": self.best_slot.start.isoformat(),
                "end_time": self.best_slot.end.isoformat(),
                "shadow_percentage": round(self.best_slot.shadow_percentage, 1),
                "sun_altitude": round(self.best_slot.sun_altitude, 1),
                "sun_azimuth": round(self.best_slot.sun_azimuth, 1),
                "time_label": self.best_slot.time_label
            },
            "alternatives": [
                {
                    "start_time": slot.start.isoformat(),
                    "end_time": slot.end.isoformat(),
                    "shadow_percentage": round(slot.shadow_percentage, 1),
                    "sun_altitude": round(slot.sun_altitude, 1),
                    "time_label": slot.time_label
                }
                for slot in self.alternatives
            ],
            "recommendation_reason": self.recommendation_reason,
            "total_evaluated": self.total_evaluated,
            "buildings_analyzed": self.buildings_used
        }


class BuildingFace(Enum):
    """Building face orientations."""
    NORTH = "N"
    EAST = "E"
    SOUTH = "S"
    WEST = "W"

    @property
    def azimuth(self) -> float:
        """Azimuth angle for face normal (degrees from north)."""
        return {"N": 0, "E": 90, "S": 180, "W": 270}[self.value]

    @classmethod
    def from_string(cls, s: str) -> Optional['BuildingFace']:
        mapping = {'N': cls.NORTH, 'E': cls.EAST, 'S': cls.SOUTH, 'W': cls.WEST}
        return mapping.get(s.upper()) if s else None


# ─── Main scheduler ────────────────────────────────────────────────────────

class ShadowScheduler:
    """
    Shadow-based scheduling engine using real 3D building data.

    Fetches actual building footprints and heights from Mapbox, then uses
    the ShadowCalculator to project accurate shadow polygons. A ray-casting
    point-in-polygon test determines whether the target location is shaded
    at each sampled time.
    """

    TIMEZONE_OFFSET = 4  # UTC+4 (Dubai)
    # Sample every 1 min within a slot so short periods of full coverage aren't missed
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

    # ─── Public API ─────────────────────────────────────────────────

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
        recommendation_count: int = 5,
        client_buildings: Optional[List[Building]] = None
    ) -> ScheduleRecommendation:
        """
        Find optimal work window based on real 3D shadow projection.

        1. Fetches nearby buildings (footprints + heights)
        2. For every candidate time slot, samples shadow state every 5 min
        3. At each sample: projects shadow polygons, ray-casts to check coverage
        4. Ranks slots by shadow percentage descending

        If client_buildings is provided, uses those directly (extracted from
        Mapbox's rendered vector tiles on the frontend) instead of querying
        the Tilequery API.
        """
        buildings = client_buildings if client_buildings else self._fetch_nearby_buildings(lat, lon)

        print(f"[schedule] mode={'facade' if building_face else 'point'} "
              f"face={building_face} buildings={len(buildings)} "
              f"source={'client' if client_buildings else 'tilequery'}")
        for i, b in enumerate(buildings[:10]):
            print(f"  bldg[{i}] id={b.id} h={b.height:.0f}m pts={len(b.footprint)}")

        slots = self._generate_time_slots(
            date, start_hour, end_hour, task_duration_minutes,
            lat, lon, buildings, building_face
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

        reason = self._generate_reason(best, location_name, building_face, len(buildings))

        return ScheduleRecommendation(
            task_name=task_name,
            location_name=location_name,
            lat=lat,
            lon=lon,
            best_slot=best,
            alternatives=alternatives,
            total_evaluated=len(slots),
            recommendation_reason=reason,
            buildings_used=len(buildings)
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
        """
        Find optimal work window for a polygon area using grid sampling.

        Generates a grid of sample points inside the polygon, fetches buildings
        near the centroid, then for each candidate time slot averages the shadow
        state across all grid points — giving a true "what fraction of this area
        is in shadow" answer.
        """
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

        return ScheduleRecommendation(
            task_name=task_name,
            location_name=location_name,
            lat=centroid_lat,
            lon=centroid_lon,
            best_slot=best,
            alternatives=alternatives,
            total_evaluated=len(slots),
            recommendation_reason=reason,
            buildings_used=len(buildings)
        )

    def _pick_diversified_alternatives(
        self,
        slots: List[TimeSlot],
        best: TimeSlot,
        count: int,
    ) -> List[TimeSlot]:
        """
        Pick up to `count` alternative slots spread across the day so recommendations
        aren't all clustered in 9–10 and 3–5. Uses time-of-day buckets and takes the
        best slot per bucket, then fills with next best by shadow % if needed.
        """
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
        Samples every SLOT_SAMPLE_INTERVAL_MINUTES (e.g. 1 min); reports max coverage
        over the period so short full-coverage windows aren't missed.
        """
        if not SHAPELY_AVAILABLE or not target_polygon_lonlat or len(target_polygon_lonlat) < 3:
            return 0.0, 0.0, 0.0
        centroid_lon = sum(p[0] for p in target_polygon_lonlat) / len(target_polygon_lonlat)
        centroid_lat = sum(p[1] for p in target_polygon_lonlat) / len(target_polygon_lonlat)
        # Footprints are sun-invariant; include them so area on buildings counts as shaded (matches visual)
        merged_footprints = self._shadow_calc.get_merged_footprint_geometry(buildings)
        coverages: List[float] = []
        altitudes: List[float] = []
        azimuths: List[float] = []
        t = start
        interval = timedelta(minutes=self.SLOT_SAMPLE_INTERVAL_MINUTES)
        while t <= end:
            sun = self._get_sun_position(t, centroid_lat, centroid_lon)
            altitudes.append(sun.altitude)
            azimuths.append(sun.azimuth)
            if sun.is_daylight and sun.altitude > 0:
                merged_cast = self._shadow_calc.get_merged_cast_shadow_geometry(
                    buildings, sun, shadow_direction_override=None
                )
                if merged_cast is not None and merged_cast.is_valid and not merged_cast.is_empty:
                    cov = self._shadow_calc.shadow_coverage_over_area(
                        merged_cast, target_polygon_lonlat, merged_footprint_geom=merged_footprints
                    )
                    coverages.append(cov)
                else:
                    # Cast is empty (e.g. no shadow) but footprint overlap still counts
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
        # Max so short periods of full coverage aren't missed; avg_alt/avg_az over slot
        max_shadow = max(coverages)
        avg_alt = sum(altitudes) / n
        avg_az = sum(azimuths) / n
        return max_shadow, avg_alt, avg_az

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
                    pct, alt, az = self._calculate_slot_shadow(
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

            current += timedelta(minutes=self.resolution)

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

    # ─── Real shadow computation ────────────────────────────────────

    def _generate_time_slots(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        duration_minutes: int,
        lat: float,
        lon: float,
        buildings: List[Building],
        building_face: Optional[str] = None
    ) -> List[TimeSlot]:
        """Generate all candidate time slots with real shadow percentages."""
        slots: List[TimeSlot] = []

        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_limit = datetime(date.year, date.month, date.day, end_hour, 0, 0)

        while current + timedelta(minutes=duration_minutes) <= end_limit:
            slot_end = current + timedelta(minutes=duration_minutes)

            shadow_pct, avg_alt, avg_az = self._calculate_slot_shadow(
                current, slot_end, lat, lon, buildings, building_face
            )

            slots.append(TimeSlot(
                start=current,
                end=slot_end,
                shadow_percentage=shadow_pct,
                sun_altitude=avg_alt,
                sun_azimuth=avg_az
            ))

            current += timedelta(minutes=self.resolution)

        return slots

    def _calculate_slot_shadow(
        self,
        start: datetime,
        end: datetime,
        lat: float,
        lon: float,
        buildings: List[Building],
        building_face: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """
        Calculate shadow coverage for a time slot. Samples every
        SLOT_SAMPLE_INTERVAL_MINUTES (e.g. 1 min); reports max coverage over
        the period so short full-coverage windows aren't missed.

        For AREA/POINT mode: uses ground-plane shadow polygons and PIP tests.
        For FACADE mode: uses 3D elevation-aware analysis.

        Returns: (shadow_percentage 0-100, avg_sun_altitude, avg_sun_azimuth)
        """
        per_sample_pct: List[float] = []
        altitudes: List[float] = []
        azimuths: List[float] = []

        # For facade mode: find the selected building's height
        facade_height = 0.0
        face_enum = None
        if building_face:
            face_enum = BuildingFace.from_string(building_face)
            for b in buildings:
                bc_lon = sum(p[0] for p in b.footprint) / len(b.footprint)
                bc_lat = sum(p[1] for p in b.footprint) / len(b.footprint)
                if abs(bc_lat - lat) < 0.0005 and abs(bc_lon - lon) < 0.0005:
                    facade_height = b.height
                    break
            if facade_height == 0:
                facade_height = 30.0

        self_shaded = 0
        ext_blocked = 0
        sun_hit = 0
        interval = timedelta(minutes=self.SLOT_SAMPLE_INTERVAL_MINUTES)

        current = start
        while current <= end:
            sun = self._get_sun_position(current, lat, lon)
            altitudes.append(sun.altitude)
            azimuths.append(sun.azimuth)

            if not sun.is_daylight or sun.altitude <= 0:
                per_sample_pct.append(100.0)
                current += interval
                continue

            in_shadow = False
            if building_face and face_enum:
                # ── Facade mode ──
                angle_diff = abs(((sun.azimuth - face_enum.azimuth + 180) % 360) - 180)
                if angle_diff >= 90:
                    in_shadow = True
                    self_shaded += 1
                else:
                    do_verbose = len(per_sample_pct) < 2
                    if self._is_face_blocked(
                        lat, lon, facade_height, buildings, sun,
                        verbose=do_verbose,
                    ):
                        in_shadow = True
                        ext_blocked += 1
                    else:
                        sun_hit += 1
            else:
                # ── Area / point mode: ground-plane shadow PIP ──
                in_shadow = self._is_point_in_any_shadow(lat, lon, buildings, sun)

            per_sample_pct.append(100.0 if in_shadow else 0.0)
            current += interval

        total_samples = len(per_sample_pct)
        # Max so short periods of full coverage aren't missed
        shadow_pct = max(per_sample_pct) if total_samples > 0 else 0.0
        avg_alt = sum(altitudes) / len(altitudes) if altitudes else 0
        avg_az = sum(azimuths) / len(azimuths) if azimuths else 0

        if building_face and total_samples > 0:
            print(
                f"  [{start.strftime('%H:%M')}-{end.strftime('%H:%M')}] "
                f"face={building_face}({face_enum.azimuth if face_enum else '?'}deg) "
                f"h={facade_height:.0f}m midpt={facade_height/2:.0f}m | "
                f"self-shaded={self_shaded} ext-blocked={ext_blocked} "
                f"sun-hit={sun_hit} night={total_samples - self_shaded - ext_blocked - sun_hit} "
                f"/ {total_samples} -> shadow={shadow_pct:.0f}% "
                f"| sun az={avg_az:.0f} alt={avg_alt:.0f}"
            )

        return shadow_pct, avg_alt, avg_az

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
            return (
                f"Recommended {time_range} for {face_name}-facing work at {location_name}. "
                f"{shadow}% shadow coverage ({source}, sun altitude {alt}deg)."
            )

        if shadow >= 80:
            desc = "excellent — area is mostly shaded by surrounding buildings"
        elif shadow >= 60:
            desc = "good — significant building shadow cover"
        elif shadow >= 40:
            desc = "moderate — partial sun exposure expected"
        else:
            desc = "limited — high direct sun exposure"

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


# ─── Convenience functions (API compatibility) ──────────────────────────────

def find_optimal_schedule(
    task_name: str,
    lat: float,
    lon: float,
    location_name: str,
    duration_minutes: int,
    date: datetime,
    start_hour: int = 5,
    end_hour: int = 20,
    building_face: Optional[str] = None,
    recommendation_count: int = 5
) -> Dict:
    """Convenience wrapper returning a dict suitable for API responses."""
    scheduler = ShadowScheduler()
    recommendation = scheduler.find_optimal_schedule(
        task_name=task_name,
        lat=lat,
        lon=lon,
        location_name=location_name,
        task_duration_minutes=duration_minutes,
        date=date,
        start_hour=start_hour,
        end_hour=end_hour,
        building_face=building_face,
        recommendation_count=recommendation_count
    )
    return recommendation.to_dict()


def find_optimal_schedule_for_area(
    task_name: str,
    polygon_points: List[Tuple[float, float]],
    location_name: str,
    duration_minutes: int,
    date: datetime,
    start_hour: int = 5,
    end_hour: int = 20,
    recommendation_count: int = 5
) -> Dict:
    """Convenience wrapper for area-based scheduling returning an API dict."""
    scheduler = ShadowScheduler()
    recommendation = scheduler.find_optimal_schedule_for_area(
        task_name=task_name,
        polygon_points=polygon_points,
        location_name=location_name,
        task_duration_minutes=duration_minutes,
        date=date,
        start_hour=start_hour,
        end_hour=end_hour,
        recommendation_count=recommendation_count
    )
    return recommendation.to_dict()


def calculate_shadow_at_time(
    lat: float,
    lon: float,
    dt: datetime,
    building_face: Optional[str] = None
) -> Dict:
    """Calculate shadow state at a specific time and location using real 3D data."""
    scheduler = ShadowScheduler()
    buildings = scheduler._fetch_nearby_buildings(lat, lon)
    sun = scheduler._get_sun_position(dt, lat, lon)

    if not sun.is_daylight or sun.altitude <= 0:
        shadow_pct = 100.0
    else:
        is_self_shaded = False
        if building_face:
            face_enum = BuildingFace.from_string(building_face)
            if face_enum:
                angle_diff = abs(((sun.azimuth - face_enum.azimuth + 180) % 360) - 180)
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
