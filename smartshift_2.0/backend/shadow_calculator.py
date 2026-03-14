"""
calculates shadow projections from 3D buildings based on
the sun's position.

Key Concepts:
- Shadow Length: Depends on sun altitude
- Shadow Direction: Opposite to sun azimuth
- Shadow Polygon: 2D projection of building shadow on the ground

Dependencies:
- solar_position.py: For sun position calculations

"""

import math
from datetime import datetime
from typing import List, Tuple, Dict, Optional, Any, Union
from dataclasses import dataclass, field
from solar_position import SolarPositionCalculator, SunPosition

try:
    from shapely.geometry import Polygon as ShapelyPolygon
    from shapely.ops import unary_union
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False

@dataclass
class Building:
    id: str
    footprint: List[Tuple[float, float]]  # [(lon, lat), ...]
    height: float  # meters
    name: Optional[str] = None

    def get_centroid(self) -> Tuple[float, float]:
        if not self.footprint:
            return (0.0, 0.0)

        sum_lon = sum(pt[0] for pt in self.footprint)
        sum_lat = sum(pt[1] for pt in self.footprint)
        n = len(self.footprint)

        return (sum_lon / n, sum_lat / n)


@dataclass
class Shadow:
    building_id: str
    polygon: List[Tuple[float, float]]
    length: float
    direction: float
    sun_altitude: float
    sun_azimuth: float
    timestamp: datetime
    opacity: float = 0.5


@dataclass
class ShadowAnalysis:
    timestamp: datetime
    sun_position: SunPosition
    shadows: List[Shadow]
    total_shadow_area: float = 0.0
    coverage_percentage: float = 0.0


class ShadowCalculator:
    # Conversion factors for Dubai's latitude
    # 1 degree latitude ≈ 111,320 meters
    # 1 degree longitude ≈ 111,320 * cos(25°) ≈ 100,856 meters at Dubai's latitude
    METERS_PER_DEGREE_LAT = 111320.0
    METERS_PER_DEGREE_LON = 100856.0  # Adjusted for Dubai's latitude

    def __init__(self, latitude: float = 25.2048, longitude: float = 55.2708,
                 timezone_offset: float = 4.0):

        self.latitude = latitude
        self.longitude = longitude
        self.timezone_offset = timezone_offset

        # Initialize solar position calculator
        self.solar_calculator = SolarPositionCalculator(
            latitude=latitude,
            longitude=longitude,
            timezone_offset=timezone_offset
        )

        # Update meters per degree based on latitude
        self.meters_per_degree_lon = self.METERS_PER_DEGREE_LAT * math.cos(math.radians(latitude))

    def _meters_to_degrees_offset(self, dx_meters: float, dy_meters: float) -> Tuple[float, float]:
        dlon = dx_meters / self.meters_per_degree_lon
        dlat = dy_meters / self.METERS_PER_DEGREE_LAT
        return (dlon, dlat)

    def calculate_shadow_length(self, building_height: float, sun_altitude: float) -> float:
        # No shadow when sun is at or below horizon
        if sun_altitude <= 0:
            return 0.0

        # Clamp altitude to prevent infinite shadows at very low angles
        # Minimum practical altitude of 1 degree
        effective_altitude = max(1.0, sun_altitude)

        # Calculate shadow length using tangent
        altitude_rad = math.radians(effective_altitude)
        shadow_length = building_height / math.tan(altitude_rad)

        # Cap shadow length to reasonable maximum (10x building height)
        max_shadow = building_height * 10
        return min(shadow_length, max_shadow)

    def calculate_shadow_direction(self, sun_azimuth: float) -> float:
        # Shadow is opposite to sun direction
        shadow_direction = (sun_azimuth + 180.0) % 360.0
        return shadow_direction

    def calculate_shadow_offset(self, shadow_length: float, shadow_direction: float) -> Tuple[float, float]:
        # Convert direction to radians (measured from North, clockwise)
        direction_rad = math.radians(shadow_direction)

        # Calculate offsets
        # sin gives East-West component (positive for East)
        # cos gives North-South component (positive for North)
        dx = shadow_length * math.sin(direction_rad)
        dy = shadow_length * math.cos(direction_rad)

        return (dx, dy)

    def calculate_shadow_polygon(
        self,
        building: Building,
        sun_position: SunPosition,
        shadow_direction_override: Optional[float] = None,
    ) -> Optional[List[Tuple[float, float]]]:
        # No shadow if sun is below horizon
        if not sun_position.is_daylight or sun_position.altitude <= 0:
            return None

        # Calculate shadow parameters
        shadow_length = self.calculate_shadow_length(building.height, sun_position.altitude)

        # No significant shadow if very short
        if shadow_length < 0.5:
            return None

        # Use override when provided (e.g. Mapbox light direction so overlay matches map lighting)
        if shadow_direction_override is not None:
            shadow_direction = shadow_direction_override % 360.0
        else:
            shadow_direction = self.calculate_shadow_direction(sun_position.azimuth)
        dx_meters, dy_meters = self.calculate_shadow_offset(shadow_length, shadow_direction)
        dlon, dlat = self._meters_to_degrees_offset(dx_meters, dy_meters)

        # Create shadow polygon
        # The polygon consists of: footprint vertices + projected shadow vertices
        # We create a polygon that represents the shadow cast on the ground

        footprint = building.footprint
        if len(footprint) < 3:
            return None

        # Project each vertex to create shadow endpoints
        shadow_vertices = [(pt[0] + dlon, pt[1] + dlat) for pt in footprint]

        # Create the shadow polygon by connecting footprint to shadow projection
        # This creates a "swept" shadow shape
        shadow_polygon = []

        # Add the shadow endpoints (the far edge of the shadow)
        shadow_polygon.extend(shadow_vertices)

        # Add the footprint in reverse order to close the polygon properly
        shadow_polygon.extend(reversed(footprint))

        return shadow_polygon

    def get_merged_shadow_geometry(
        self,
        buildings: List[Building],
        sun_position: SunPosition,
        shadow_direction_override: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Merge all building shadow polygons (full elongated shadows, not just footprints)
        using Shapely unary_union. Returns a Shapely geometry (Polygon or MultiPolygon)
        or None if no shadows or Shapely unavailable.

        Use this for area-based coverage: coverage = intersection(merged_shadow, target).area / target.area
        """
        if not SHAPELY_AVAILABLE or not sun_position.is_daylight or sun_position.altitude <= 0:
            return None
        polys: List[Any] = []
        for b in buildings:
            if b.height <= 0:
                continue
            poly = self.calculate_shadow_polygon(b, sun_position, shadow_direction_override)
            if poly and len(poly) >= 3:
                try:
                    # Polygon is list of (lon, lat) -> Shapely (x, y) = (lon, lat)
                    if poly[0] != poly[-1]:
                        poly = list(poly) + [poly[0]]
                    polys.append(ShapelyPolygon(poly))
                except Exception:
                    continue
        if not polys:
            return None
        return unary_union(polys)

    def get_merged_cast_shadow_geometry(
        self,
        buildings: List[Building],
        sun_position: SunPosition,
        shadow_direction_override: Optional[float] = None,
    ) -> Optional[Any]:
        """
        Merge only the cast (ground) shadow polygons, excluding building footprints.
        Builds the cast as the band between footprint edge and shadow edge for each
        building, so we count only ground that is in shadow, not the building itself.
        """
        if not SHAPELY_AVAILABLE or not sun_position.is_daylight or sun_position.altitude <= 0:
            return None
        cast_polys: List[Any] = []
        for b in buildings:
            if b.height <= 0:
                continue
            full_poly = self.calculate_shadow_polygon(b, sun_position, shadow_direction_override)
            if not full_poly or len(full_poly) < 3:
                continue
            footprint = b.footprint
            n = len(footprint)
            shadow_vertices = full_poly[:n]  # first n points are the far shadow edge
            try:
                # Cast-only = band quads: (fp[i], fp[i+1], shadow[i+1], shadow[i])
                for i in range(n):
                    j = (i + 1) % n
                    quad = [
                        footprint[i],
                        footprint[j],
                        shadow_vertices[j],
                        shadow_vertices[i],
                        footprint[i],
                    ]
                    poly = ShapelyPolygon(quad)
                    if poly.is_valid and not poly.is_empty and poly.area > 1e-14:
                        cast_polys.append(poly)
            except Exception:
                continue
        if not cast_polys:
            return None
        return unary_union(cast_polys)

    def get_merged_footprint_geometry(self, buildings: List[Building]) -> Optional[Any]:
        """Merge all building footprints so we can count polygon area that is on buildings as shaded."""
        if not SHAPELY_AVAILABLE or not buildings:
            return None
        polys: List[Any] = []
        for b in buildings:
            if not b.footprint or len(b.footprint) < 3:
                continue
            try:
                fp = list(b.footprint)
                if fp[0] != fp[-1]:
                    fp.append(fp[0])
                polys.append(ShapelyPolygon(fp))
            except Exception:
                continue
        if not polys:
            return None
        return unary_union(polys)

    # Below this coverage we report 0% so "no shade" areas don't show small noise (e.g. 12%)
    MIN_COVERAGE_PERCENT = 15.0

    def shadow_coverage_over_area(
        self,
        merged_shadow_geom: Any,
        target_polygon: List[Tuple[float, float]],
        merged_footprint_geom: Optional[Any] = None,
    ) -> float:
        """
        Compute coverage percentage: (shaded area ∩ target) / target area * 100.
        Shaded = cast ground shadow + building footprints (so area on buildings counts as shaded).
        target_polygon: list of (lon, lat) vertices.
        Returns 0-100. Values below MIN_COVERAGE_PERCENT are returned as 0.
        """
        if not SHAPELY_AVAILABLE or len(target_polygon) < 3:
            return 0.0
        try:
            if target_polygon[0] != target_polygon[-1]:
                target_polygon = list(target_polygon) + [target_polygon[0]]
            target = ShapelyPolygon(target_polygon)
            if not target.is_valid or target.is_empty:
                return 0.0
            target_area = target.area
            if target_area <= 0:
                return 0.0
            inter = None
            if merged_shadow_geom is not None and merged_shadow_geom.is_valid and not merged_shadow_geom.is_empty:
                inter = merged_shadow_geom.intersection(target)
            if merged_footprint_geom is not None and merged_footprint_geom.is_valid and not merged_footprint_geom.is_empty:
                inter_fp = merged_footprint_geom.intersection(target)
                if not inter_fp.is_empty:
                    inter = inter_fp if inter is None or inter.is_empty else inter.union(inter_fp)
            if inter is None or inter.is_empty:
                return 0.0
            pct = (inter.area / target_area) * 100.0
            if pct < self.MIN_COVERAGE_PERCENT:
                return 0.0
            return min(100.0, pct)
        except Exception:
            return 0.0

    def calculate_shadow(self, building: Building, dt: datetime) -> Optional[Shadow]:
        # Get sun position
        sun_position = self.solar_calculator.get_sun_position(dt)

        # Calculate shadow polygon
        polygon = self.calculate_shadow_polygon(building, sun_position)

        if polygon is None:
            return None

        # Calculate shadow length and direction
        shadow_length = self.calculate_shadow_length(building.height, sun_position.altitude)
        shadow_direction = self.calculate_shadow_direction(sun_position.azimuth)

        # Calculate opacity based on sun altitude
        # Higher sun = more defined shadows (higher opacity)
        # Lower sun = softer shadows (lower opacity)
        opacity = self._calculate_shadow_opacity(sun_position.altitude)

        return Shadow(
            building_id=building.id,
            polygon=polygon,
            length=shadow_length,
            direction=shadow_direction,
            sun_altitude=sun_position.altitude,
            sun_azimuth=sun_position.azimuth,
            timestamp=dt,
            opacity=opacity
        )

    def _calculate_shadow_opacity(self, sun_altitude: float) -> float:
        if sun_altitude <= 0:
            return 0.0

        # Normalize altitude (0-90 degrees to 0-1)
        normalized = min(sun_altitude / 90.0, 1.0)

        # Apply a curve for more natural-looking shadows
        # Peak opacity around 45-60 degrees
        if sun_altitude < 45:
            opacity = 0.1 + 0.5 * (sun_altitude / 45.0)
        else:
            opacity = 0.6 - 0.2 * ((sun_altitude - 45) / 45.0)

        return max(0.1, min(0.7, opacity))

    def calculate_shadows_for_buildings(
        self,
        buildings: List[Building],
        dt: datetime,
        target_area_polygon: Optional[List[Tuple[float, float]]] = None,
        shadow_direction_override: Optional[float] = None,
    ) -> ShadowAnalysis:
        """
        Build shadow list and optionally set total_shadow_area / coverage_percentage
        from merged full shadow polygons (not footprint area).
        target_area_polygon: optional list of (lon, lat) for coverage_percentage.
        """
        sun_position = self.solar_calculator.get_sun_position(dt)
        shadows = []

        for building in buildings:
            shadow = self.calculate_shadow(building, dt)
            if shadow:
                shadows.append(shadow)

        total_shadow_area = 0.0
        coverage_percentage = 0.0
        if SHAPELY_AVAILABLE and shadows and sun_position.is_daylight and sun_position.altitude > 0:
            merged = self.get_merged_shadow_geometry(
                buildings, sun_position, shadow_direction_override
            )
            if merged is not None and merged.is_valid and not merged.is_empty:
                total_shadow_area = merged.area  # in degree² units
                if target_area_polygon and len(target_area_polygon) >= 3:
                    coverage_percentage = self.shadow_coverage_over_area(
                        merged, target_area_polygon
                    )

        return ShadowAnalysis(
            timestamp=dt,
            sun_position=sun_position,
            shadows=shadows,
            total_shadow_area=total_shadow_area,
            coverage_percentage=coverage_percentage,
        )

    def calculate_shadow_animation_frames(self, buildings: List[Building],
                                          date: datetime,
                                          start_hour: int = 6,
                                          end_hour: int = 20,
                                          interval_minutes: int = 30) -> List[ShadowAnalysis]:

        frames = []

        current_time = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end_time = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        while current_time <= end_time:
            analysis = self.calculate_shadows_for_buildings(buildings, current_time)
            frames.append(analysis)

            # Move to next interval
            total_minutes = current_time.hour * 60 + current_time.minute + interval_minutes
            next_hour = total_minutes // 60
            next_minute = total_minutes % 60

            if next_hour > 23:
                break

            current_time = current_time.replace(hour=next_hour, minute=next_minute)

        return frames

    def shadow_to_geojson(self, shadow: Shadow) -> Dict[str, Any]:
        # Close the polygon by adding the first point at the end
        coordinates = [list(shadow.polygon)]
        if coordinates[0] and coordinates[0][0] != coordinates[0][-1]:
            coordinates[0].append(coordinates[0][0])

        return {
            "type": "Feature",
            "properties": {
                "building_id": shadow.building_id,
                "length": shadow.length,
                "direction": shadow.direction,
                "sun_altitude": shadow.sun_altitude,
                "sun_azimuth": shadow.sun_azimuth,
                "opacity": shadow.opacity,
                "timestamp": shadow.timestamp.isoformat()
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": coordinates
            }
        }

    def shadows_to_geojson(self, shadows: List[Shadow]) -> Dict[str, Any]:
        features = [self.shadow_to_geojson(s) for s in shadows]

        return {
            "type": "FeatureCollection",
            "features": features
        }

    def analysis_to_json(self, analysis: ShadowAnalysis) -> Dict[str, Any]:
        return {
            "timestamp": analysis.timestamp.isoformat(),
            "sun": {
                "azimuth": analysis.sun_position.azimuth,
                "altitude": analysis.sun_position.altitude,
                "is_daylight": analysis.sun_position.is_daylight,
                "sunrise": analysis.sun_position.sunrise.isoformat() if analysis.sun_position.sunrise else None,
                "sunset": analysis.sun_position.sunset.isoformat() if analysis.sun_position.sunset else None
            },
            "shadows": self.shadows_to_geojson(analysis.shadows),
            "summary": {
                "shadow_count": len(analysis.shadows),
                "total_shadow_area": analysis.total_shadow_area,
                "coverage_percentage": analysis.coverage_percentage
            }
        }


def create_sample_dubai_buildings() -> List[Building]:
    buildings = [
        # Burj Khalifa - Approximate triangular footprint
        Building(
            id="burj_khalifa",
            name="Burj Khalifa",
            height=828.0,  # World's tallest building
            footprint=[
                (55.2743, 25.1975),
                (55.2747, 25.1969),
                (55.2751, 25.1975),
                (55.2747, 25.1981),
            ]
        ),

        # Dubai Frame - Rectangular frame structure
        Building(
            id="dubai_frame",
            name="Dubai Frame",
            height=150.0,
            footprint=[
                (55.2998, 25.2354),
                (55.3006, 25.2354),
                (55.3006, 25.2360),
                (55.2998, 25.2360),
            ]
        ),

        # Museum of the Future - Torus-shaped (simplified as oval)
        Building(
            id="museum_of_future",
            name="Museum of the Future",
            height=77.0,
            footprint=[
                (55.2800, 25.2195),
                (55.2810, 25.2192),
                (55.2818, 25.2195),
                (55.2810, 25.2200),
            ]
        ),

        # Sample Marina tower
        Building(
            id="marina_tower_1",
            name="Marina Tower 1",
            height=300.0,
            footprint=[
                (55.1380, 25.0800),
                (55.1385, 25.0800),
                (55.1385, 25.0805),
                (55.1380, 25.0805),
            ]
        ),

        # Sample Downtown building
        Building(
            id="downtown_tower_1",
            name="Downtown Tower 1",
            height=250.0,
            footprint=[
                (55.2700, 25.2040),
                (55.2705, 25.2040),
                (55.2705, 25.2045),
                (55.2700, 25.2045),
            ]
        ),
    ]

    return buildings


# Example usage and testing
if __name__ == "__main__":
    # Create shadow calculator for Dubai
    calculator = ShadowCalculator(
        latitude=25.2048,
        longitude=55.2708,
        timezone_offset=4.0
    )

    # Get sample buildings
    buildings = create_sample_dubai_buildings()

    # Calculate shadows for current time
    now = datetime.now()
    print(f"Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # Calculate shadows
    analysis = calculator.calculate_shadows_for_buildings(buildings, now)

    print(f"Sun Position:")
    print(f"  Azimuth:  {analysis.sun_position.azimuth:.2f}°")
    print(f"  Altitude: {analysis.sun_position.altitude:.2f}°")
    print(f"  Daylight: {analysis.sun_position.is_daylight}")

    print(f"Shadows Calculated: {len(analysis.shadows)}")
    print()

    for shadow in analysis.shadows:
        print(f"Building: {shadow.building_id}")
        print(f"  Shadow Length:    {shadow.length:.1f} m")
        print(f"  Shadow Direction: {shadow.direction:.1f}°")
        print(f"  Shadow Opacity:   {shadow.opacity:.2f}")
        print()

    print("-" * 70)
    print("Sample GeoJSON output for first shadow:")
    if analysis.shadows:
        import json
        geojson = calculator.shadow_to_geojson(analysis.shadows[0])
        print(json.dumps(geojson, indent=2)[:500] + "...")










