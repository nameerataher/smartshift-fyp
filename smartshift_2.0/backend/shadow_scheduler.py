"""
shadow_scheduler.py

Shadow-based scheduling engine for SmartShift.
Finds optimal work windows based SOLELY on shadow exposure.
No heat risk considerations - pure shadow coverage optimization.

The engine:
1. Takes location, duration, and work hours
2. Calculates shadow exposure at each time slot
3. Recommends times with maximum shadow percentage
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from enum import Enum
import math


@dataclass
class SunPosition:
    """Sun position at a specific time."""
    azimuth: float      # Degrees from north (0-360)
    altitude: float     # Degrees above horizon (-90 to 90)
    is_daylight: bool
    sunrise: Optional[str] = None
    sunset: Optional[str] = None


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
            "total_evaluated": self.total_evaluated
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
        """Parse face from string."""
        mapping = {'N': cls.NORTH, 'E': cls.EAST, 'S': cls.SOUTH, 'W': cls.WEST}
        return mapping.get(s.upper())


class ShadowScheduler:
    """
    Shadow-based scheduling engine.
    
    Finds optimal time windows by maximizing shadow exposure.
    Shadow exposure is calculated using sun position (altitude & azimuth).
    """
    
    # Dubai coordinates and timezone
    DEFAULT_LAT = 25.2048
    DEFAULT_LON = 55.2708
    TIMEZONE_OFFSET = 4  # UTC+4
    
    def __init__(self, temporal_resolution_minutes: int = 10):
        """
        Initialize scheduler.
        
        Args:
            temporal_resolution_minutes: Time step for evaluation (5, 10, or 15 min)
        """
        self.resolution = temporal_resolution_minutes
    
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
        recommendation_count: int = 5
    ) -> ScheduleRecommendation:
        """
        Find optimal work window based on maximum shadow exposure.
        
        Args:
            task_name: Name of the task
            lat: Latitude
            lon: Longitude
            location_name: Human-readable location name
            task_duration_minutes: Duration of task in minutes
            date: Date for scheduling
            start_hour: Earliest start (default 5am)
            end_hour: Latest end (default 8pm)
            building_face: Optional face direction (N/E/S/W)
            recommendation_count: Number of alternatives to return
        
        Returns:
            ScheduleRecommendation with best slot and alternatives
        """
        # Generate all possible time slots
        slots = self._generate_time_slots(
            date, start_hour, end_hour, task_duration_minutes, lat, lon, building_face
        )
        
        if not slots:
            raise ValueError(
                f"No valid time slots for {task_name} on {date.date()} "
                f"between {start_hour}:00-{end_hour}:00"
            )
        
        # Sort by shadow percentage (descending)
        slots.sort(key=lambda s: s.shadow_percentage, reverse=True)
        
        best = slots[0]
        alternatives = slots[1:recommendation_count]
        
        # Generate explanation
        reason = self._generate_reason(best, location_name, building_face)
        
        return ScheduleRecommendation(
            task_name=task_name,
            location_name=location_name,
            lat=lat,
            lon=lon,
            best_slot=best,
            alternatives=alternatives,
            total_evaluated=len(slots),
            recommendation_reason=reason
        )
    
    def _generate_time_slots(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        duration_minutes: int,
        lat: float,
        lon: float,
        building_face: Optional[str] = None
    ) -> List[TimeSlot]:
        """Generate all possible time slots with their shadow coverage."""
        slots = []
        
        # Iterate through all possible start times
        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_limit = datetime(date.year, date.month, date.day, end_hour, 0, 0)
        
        while current + timedelta(minutes=duration_minutes) <= end_limit:
            slot_end = current + timedelta(minutes=duration_minutes)
            
            # Calculate average shadow coverage for this slot
            shadow_pct, avg_alt, avg_az = self._calculate_slot_shadow(
                current, slot_end, lat, lon, building_face
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
        building_face: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """
        Calculate average shadow coverage for a time slot.
        
        Returns: (shadow_percentage, avg_altitude, avg_azimuth)
        """
        shadow_values = []
        altitudes = []
        azimuths = []
        
        current = start
        while current <= end:
            sun = self._calculate_sun_position(current, lat, lon)
            altitudes.append(sun.altitude)
            azimuths.append(sun.azimuth)
            
            if building_face:
                shadow = self._calculate_facade_shadow(sun, building_face)
            else:
                shadow = self._calculate_general_shadow(sun)
            
            shadow_values.append(shadow)
            current += timedelta(minutes=5)  # Sample every 5 min
        
        avg_shadow = sum(shadow_values) / len(shadow_values) if shadow_values else 0
        avg_alt = sum(altitudes) / len(altitudes) if altitudes else 0
        avg_az = sum(azimuths) / len(azimuths) if azimuths else 0
        
        return avg_shadow, avg_alt, avg_az
    
    def _calculate_general_shadow(self, sun: SunPosition) -> float:
        """
        Calculate shadow percentage for general outdoor work.
        
        Lower sun = more shadow from surrounding buildings/structures.
        Night = 100% shadow (no sun).
        """
        if not sun.is_daylight or sun.altitude <= 0:
            return 100.0  # Night = full shade
        
        # Shadow decreases as sun altitude increases
        # At low altitude (10°): ~85% shadow
        # At high altitude (70°): ~15% shadow
        shadow_pct = max(10, 100 - (sun.altitude / 90) * 90)
        
        return shadow_pct
    
    def _calculate_facade_shadow(self, sun: SunPosition, face: str) -> float:
        """
        Calculate shadow on a specific building face.
        
        A face is shadowed when sun is behind it (angle > 90° from face normal).
        """
        if not sun.is_daylight or sun.altitude <= 0:
            return 100.0  # Night = full shade
        
        face_enum = BuildingFace.from_string(face)
        if not face_enum:
            return self._calculate_general_shadow(sun)
        
        face_azimuth = face_enum.azimuth
        
        # Angle between sun direction and face normal
        angle_diff = abs(((sun.azimuth - face_azimuth + 180) % 360) - 180)
        
        if angle_diff > 90:
            # Sun is behind the face - face is in shadow
            shadow_pct = 85 + 15 * (angle_diff - 90) / 90
        elif angle_diff > 60:
            # Sun at oblique angle - partial shadow
            shadow_pct = 40 + 45 * (angle_diff - 60) / 30
        else:
            # Sun facing the facade - some shadow from other structures
            shadow_pct = 15 + 25 * (angle_diff / 60)
        
        # Lower sun = more shadow from adjacent buildings
        altitude_factor = 1 - (sun.altitude / 90) * 0.3
        shadow_pct = min(100, shadow_pct * altitude_factor)
        
        return shadow_pct
    
    def _calculate_sun_position(self, dt: datetime, lat: float, lon: float) -> SunPosition:
        """
        Calculate sun position using NOAA algorithms.
        
        Based on dubai_shadow_simulation.html implementation.
        """
        tz = self.TIMEZONE_OFFSET
        hour = dt.hour
        minute = dt.minute
        
        # Day of year
        start_of_year = datetime(dt.year, 1, 1)
        day_of_year = (dt - start_of_year).days + 1
        
        # Solar declination (angle between sun and equator)
        declination = 23.45 * math.sin(math.radians(360 / 365 * (284 + day_of_year)))
        
        # Equation of Time
        B = math.radians(360 / 365 * (day_of_year - 81))
        EoT = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
        
        # Solar time and hour angle
        solar_time = hour * 60 + minute + EoT + 4 * (lon - tz * 15)
        hour_angle = solar_time / 4 - 180
        
        # Convert to radians
        lat_rad = math.radians(lat)
        dec_rad = math.radians(declination)
        ha_rad = math.radians(hour_angle)
        
        # Calculate altitude
        sin_alt = (math.sin(lat_rad) * math.sin(dec_rad) +
                   math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
        sin_alt = max(-1, min(1, sin_alt))
        altitude = math.degrees(math.asin(sin_alt))
        
        # Calculate azimuth
        cos_az = (math.sin(dec_rad) - math.sin(lat_rad) * sin_alt) / \
                 (math.cos(lat_rad) * math.cos(math.asin(sin_alt)))
        cos_az = max(-1, min(1, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        
        if hour_angle > 0:
            azimuth = 360 - azimuth
        
        # Sunrise/sunset times
        cos_ha_sunrise = -math.tan(lat_rad) * math.tan(dec_rad)
        sunrise = None
        sunset = None
        
        if -1 <= cos_ha_sunrise <= 1:
            ha_sunrise = math.degrees(math.acos(cos_ha_sunrise))
            noon_minutes = 720 - 4 * lon - EoT + tz * 60
            sunrise_min = noon_minutes - ha_sunrise * 4
            sunset_min = noon_minutes + ha_sunrise * 4
            sunrise = self._format_minutes(round(sunrise_min))
            sunset = self._format_minutes(round(sunset_min))
        
        return SunPosition(
            azimuth=azimuth,
            altitude=altitude,
            is_daylight=altitude > 0,
            sunrise=sunrise,
            sunset=sunset
        )
    
    def _format_minutes(self, total_minutes: int) -> str:
        """Format minutes since midnight to HH:MM."""
        normalized = ((total_minutes % 1440) + 1440) % 1440
        hours = normalized // 60
        minutes = normalized % 60
        return f"{hours:02d}:{minutes:02d}"
    
    def _generate_reason(
        self,
        slot: TimeSlot,
        location_name: str,
        building_face: Optional[str] = None
    ) -> str:
        """Generate human-readable recommendation reason."""
        time_range = slot.time_label
        shadow = round(slot.shadow_percentage)
        
        if building_face:
            face_name = {"N": "North", "E": "East", "S": "South", "W": "West"}.get(
                building_face.upper(), building_face
            )
            return (
                f"Recommended {time_range} for {face_name}-facing work. "
                f"{shadow}% shadow coverage during this window when sun is "
                f"{'behind' if shadow > 70 else 'at oblique angle to'} the facade."
            )
        
        if shadow >= 80:
            desc = "excellent shadow coverage"
        elif shadow >= 60:
            desc = "good shadow coverage"
        elif shadow >= 40:
            desc = "moderate shadow coverage"
        else:
            desc = "limited shadow coverage"
        
        return (
            f"Recommended {time_range} at {location_name}. "
            f"{shadow}% shadow coverage ({desc}) based on sun position analysis."
        )


# Convenience functions for API compatibility

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
    """
    Convenience function to find optimal schedule.
    
    Returns dictionary suitable for API response.
    """
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


def calculate_shadow_at_time(
    lat: float,
    lon: float,
    dt: datetime,
    building_face: Optional[str] = None
) -> Dict:
    """
    Calculate shadow percentage at a specific time and location.
    """
    scheduler = ShadowScheduler()
    sun = scheduler._calculate_sun_position(dt, lat, lon)
    
    if building_face:
        shadow_pct = scheduler._calculate_facade_shadow(sun, building_face)
    else:
        shadow_pct = scheduler._calculate_general_shadow(sun)
    
    return {
        "shadow_percentage": round(shadow_pct, 1),
        "sun_altitude": round(sun.altitude, 1),
        "sun_azimuth": round(sun.azimuth, 1),
        "is_daylight": sun.is_daylight,
        "sunrise": sun.sunrise,
        "sunset": sun.sunset
    }
