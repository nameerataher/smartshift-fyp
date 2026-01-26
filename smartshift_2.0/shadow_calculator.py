"""
Shadow Projection Calculator for Dubai Sun-Shadow Simulation
=============================================================

This module calculates shadow projections from 3D buildings based on
the sun's position. It computes shadow lengths, directions, and
generates shadow polygons that can be rendered on the map.

Key Concepts:
- Shadow Length: Depends on sun altitude
- Shadow Direction: Opposite to sun azimuth
- Shadow Polygon: 2D projection of building shadow on the ground

Dependencies:
- solar_position.py: For sun position calculations

"""

import math
from datetime import datetime
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass, field
from solar_position import SolarPositionCalculator, SunPosition


@dataclass
class Building:
    """
    Represents a building for shadow calculation.

    Attributes:
        id: Unique identifier for the building
        footprint: List of (lon, lat) coordinates forming the building footprint
        height: Building height in meters
        name: Optional building name for reference
    """
    id: str
    footprint: List[Tuple[float, float]]  # [(lon, lat), ...]
    height: float  # meters
    name: Optional[str] = None

    def get_centroid(self) -> Tuple[float, float]:
        """
        Calculate the centroid of the building footprint.

        Returns:
            (longitude, latitude) of the centroid
        """
        if not self.footprint:
            return (0.0, 0.0)

        sum_lon = sum(pt[0] for pt in self.footprint)
        sum_lat = sum(pt[1] for pt in self.footprint)
        n = len(self.footprint)

        return (sum_lon / n, sum_lat / n)


@dataclass
class Shadow:
    """
    Represents a calculated shadow.

    Attributes:
        building_id: ID of the building casting the shadow
        polygon: List of (lon, lat) coordinates forming the shadow polygon
        length: Shadow length in meters
        direction: Shadow direction in degrees from North
        sun_altitude: Sun altitude when shadow was calculated
        sun_azimuth: Sun azimuth when shadow was calculated
        timestamp: Time of calculation
        opacity: Suggested shadow opacity (0.0 - 1.0)
    """
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
    """
    Complete shadow analysis for a specific time.

    Attributes:
        timestamp: Analysis time
        sun_position: Sun position data
        shadows: List of calculated shadows
        total_shadow_area: Estimated total shadow area in square meters
        coverage_percentage: Estimated percentage of area in shadow
    """
    timestamp: datetime
    sun_position: SunPosition
    shadows: List[Shadow]
    total_shadow_area: float = 0.0
    coverage_percentage: float = 0.0


class ShadowCalculator:
    """
    Calculates building shadows based on sun position.

    This calculator uses geometric projection to determine how
    buildings cast shadows on the ground plane. The shadows are
    calculated as 2D polygons that can be rendered on a map.

    Note on coordinate systems:
    - Geographic coordinates (lon, lat) are used for input/output
    - Internal calculations convert to local meters for accuracy
    - Dubai's latitude (~25°N) is used for the conversion factor
    """

    # Conversion factors for Dubai's latitude
    # 1 degree latitude ≈ 111,320 meters
    # 1 degree longitude ≈ 111,320 * cos(25°) ≈ 100,856 meters at Dubai's latitude
    METERS_PER_DEGREE_LAT = 111320.0
    METERS_PER_DEGREE_LON = 100856.0  # Adjusted for Dubai's latitude

    def __init__(self, latitude: float = 25.2048, longitude: float = 55.2708,
                 timezone_offset: float = 4.0):
        """
        Initialize the shadow calculator.

        Args:
            latitude: Reference latitude (default: Dubai)
            longitude: Reference longitude (default: Dubai)
            timezone_offset: Hours offset from UTC (default: Dubai +4)
        """
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
        """
        Convert meter offsets to degree offsets.

        Args:
            dx_meters: East-West offset in meters (positive = East)
            dy_meters: North-South offset in meters (positive = North)

        Returns:
            (dlon, dlat) offset in degrees
        """
        dlon = dx_meters / self.meters_per_degree_lon
        dlat = dy_meters / self.METERS_PER_DEGREE_LAT
        return (dlon, dlat)

    def calculate_shadow_length(self, building_height: float, sun_altitude: float) -> float:
        """
        Calculate the shadow length for a given building height and sun altitude.

        The shadow length is calculated using basic trigonometry:
        shadow_length = height / tan(altitude)

        When the sun is low, shadows are long. When the sun is high, shadows are short.
        At solar noon in summer, shadows may be very short or even non-existent.

        Args:
            building_height: Height of the building in meters
            sun_altitude: Sun altitude angle in degrees (0-90)

        Returns:
            Shadow length in meters (0 if sun is at/below horizon)
        """
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
        """
        Calculate the direction in which the shadow falls.

        The shadow falls in the opposite direction of the sun's azimuth.

        Args:
            sun_azimuth: Sun azimuth in degrees (0 = North, clockwise)

        Returns:
            Shadow direction in degrees (0 = North, clockwise)
        """
        # Shadow is opposite to sun direction
        shadow_direction = (sun_azimuth + 180.0) % 360.0
        return shadow_direction

    def calculate_shadow_offset(self, shadow_length: float, shadow_direction: float) -> Tuple[float, float]:
        """
        Calculate the (x, y) offset for shadow projection in meters.

        Args:
            shadow_length: Length of shadow in meters
            shadow_direction: Direction of shadow in degrees from North

        Returns:
            (dx, dy) offset in meters where:
            - dx is East-West offset (positive = East)
            - dy is North-South offset (positive = North)
        """
        # Convert direction to radians (measured from North, clockwise)
        direction_rad = math.radians(shadow_direction)

        # Calculate offsets
        # sin gives East-West component (positive for East)
        # cos gives North-South component (positive for North)
        dx = shadow_length * math.sin(direction_rad)
        dy = shadow_length * math.cos(direction_rad)

        return (dx, dy)

    def calculate_shadow_polygon(self, building: Building, sun_position: SunPosition) -> Optional[List[Tuple[float, float]]]:
        """
        Calculate the shadow polygon for a building.

        The shadow polygon is created by projecting each vertex of the
        building footprint in the shadow direction by the shadow length.
        The resulting polygon connects the original footprint with the
        projected vertices.

        Args:
            building: Building object with footprint and height
            sun_position: Current sun position

        Returns:
            List of (lon, lat) coordinates forming the shadow polygon,
            or None if no shadow (sun below horizon or directly overhead)
        """
        # No shadow if sun is below horizon
        if not sun_position.is_daylight or sun_position.altitude <= 0:
            return None

        # Calculate shadow parameters
        shadow_length = self.calculate_shadow_length(building.height, sun_position.altitude)

        # No significant shadow if very short
        if shadow_length < 0.5:
            return None

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

    def calculate_shadow(self, building: Building, dt: datetime) -> Optional[Shadow]:
        """
        Calculate the complete shadow for a building at a specific time.

        Args:
            building: Building object
            dt: Datetime for shadow calculation

        Returns:
            Shadow object or None if no shadow
        """
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
        """
        Calculate shadow opacity based on sun altitude.

        Shadows are more defined (higher contrast) when the sun is higher.
        At low sun angles, atmospheric scattering softens shadows.

        Args:
            sun_altitude: Sun altitude in degrees

        Returns:
            Opacity value between 0.1 and 0.7
        """
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

    def calculate_shadows_for_buildings(self, buildings: List[Building],
                                         dt: datetime) -> ShadowAnalysis:
        """
        Calculate shadows for multiple buildings at a specific time.

        Args:
            buildings: List of Building objects
            dt: Datetime for shadow calculation

        Returns:
            ShadowAnalysis object with all calculated shadows
        """
        sun_position = self.solar_calculator.get_sun_position(dt)
        shadows = []

        for building in buildings:
            shadow = self.calculate_shadow(building, dt)
            if shadow:
                shadows.append(shadow)

        return ShadowAnalysis(
            timestamp=dt,
            sun_position=sun_position,
            shadows=shadows
        )

    def calculate_shadow_animation_frames(self, buildings: List[Building],
                                          date: datetime,
                                          start_hour: int = 6,
                                          end_hour: int = 20,
                                          interval_minutes: int = 30) -> List[ShadowAnalysis]:
        """
        Calculate shadow positions throughout a day for animation.

        This generates a series of shadow calculations at regular intervals,
        suitable for creating animated shadow visualizations.

        Args:
            buildings: List of Building objects
            date: Date for the animation
            start_hour: Starting hour (default 6 AM)
            end_hour: Ending hour (default 8 PM)
            interval_minutes: Time between frames (default 30 min)

        Returns:
            List of ShadowAnalysis objects for each time frame
        """
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
        """
        Convert a shadow to GeoJSON format for map rendering.

        Args:
            shadow: Shadow object

        Returns:
            GeoJSON Feature dictionary
        """
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
        """
        Convert multiple shadows to a GeoJSON FeatureCollection.

        Args:
            shadows: List of Shadow objects

        Returns:
            GeoJSON FeatureCollection dictionary
        """
        features = [self.shadow_to_geojson(s) for s in shadows]

        return {
            "type": "FeatureCollection",
            "features": features
        }

    def analysis_to_json(self, analysis: ShadowAnalysis) -> Dict[str, Any]:
        """
        Convert a complete shadow analysis to JSON-serializable format.

        Args:
            analysis: ShadowAnalysis object

        Returns:
            Dictionary with complete analysis data
        """
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
    """
    Create sample building data for Dubai landmarks.

    These are approximate footprints for demonstration purposes.
    In production, real building data would come from OpenStreetMap or similar.

    Returns:
        List of Building objects for major Dubai landmarks
    """
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

    print("=" * 70)
    print("Dubai Shadow Calculator - Test Results")
    print("=" * 70)
    print(f"Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 70)

    # Calculate shadows
    analysis = calculator.calculate_shadows_for_buildings(buildings, now)

    print(f"Sun Position:")
    print(f"  Azimuth:  {analysis.sun_position.azimuth:.2f}°")
    print(f"  Altitude: {analysis.sun_position.altitude:.2f}°")
    print(f"  Daylight: {analysis.sun_position.is_daylight}")
    print("-" * 70)

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

    print("=" * 70)



