"""
scheduling_engine.py - core scheduling engine for smartshift 2.0

this module provides the foundational scheduling logic for outdoor task planning.
it calculates shadow coverage, sun exposure, and heat risk for time slots.

the optimizer (schedule_optimizer.py) builds on top of this engine to provide
ml-powered recommendations and learning from user feedback.

target users:
- municipality workers (road work, maintenance)
- construction workers (outdoor labor)
- building facade cleaners (need to work in shade/shadow)
- joggers, cyclists, and pedestrians (want less sunny routes)
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import numpy as np


# -----------------------------------------------------------------------------
# data structures for scheduling
# -----------------------------------------------------------------------------

@dataclass
class SunPosition:
    """represents the sun's position in the sky"""
    azimuth: float          # degrees from north (0-360)
    altitude: float         # degrees above horizon (-90 to 90)
    sunrise: str            # hh:mm format
    sunset: str             # hh:mm format
    is_daylight: bool       # whether sun is above horizon
    solar_noon: str = ""    # time of highest sun position


@dataclass
class TimeSlot:
    """represents a potential time slot for scheduling"""
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    sun_positions: List[SunPosition] = field(default_factory=list)
    
    # calculated metrics
    avg_sun_altitude: float = 0.0
    max_sun_altitude: float = 0.0
    shadow_coverage: float = 0.0      # percentage of area in shadow (0-100)
    sun_exposure_minutes: float = 0.0  # minutes of direct sun exposure
    
    # risk metrics
    heat_risk_score: float = 0.0      # 0 = low, 1 = medium, 2 = high
    heat_risk_level: str = "low"
    uv_index: float = 0.0
    
    # quality metrics
    quality_score: float = 0.0        # overall quality (0-100)
    is_optimal: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class ScheduleRequest:
    """represents a scheduling request from the user"""
    task_name: str
    location_lat: float
    location_lon: float
    location_name: str
    date: datetime
    duration_minutes: int
    earliest_start: int = 0       # hour (0-23)
    latest_end: int = 23          # hour (0-23)
    priority: int = 1             # 1=normal, 2=high, 3=critical
    task_type: str = "general"    # general, construction, cleaning, exercise


@dataclass
class ScheduleResult:
    """result of scheduling calculation"""
    request: ScheduleRequest
    best_slot: TimeSlot
    alternative_slots: List[TimeSlot]
    all_slots: List[TimeSlot]
    summary: str
    created_at: datetime = field(default_factory=datetime.now)


# -----------------------------------------------------------------------------
# solar position calculator
# -----------------------------------------------------------------------------

class SolarCalculator:
    """
    calculates sun position for any location and time.
    uses standard astronomical formulas for accurate sun position.
    """
    
    def __init__(self, latitude: float = 25.2048, longitude: float = 55.2708, 
                 timezone_offset: int = 4):
        """
        initialize calculator with location.
        
        args:
            latitude: location latitude (default: dubai)
            longitude: location longitude (default: dubai)
            timezone_offset: hours offset from utc (default: +4 for dubai)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_offset = timezone_offset
    
    def get_sun_position(self, dt: datetime) -> SunPosition:
        """
        calculate sun position for a specific datetime.
        
        args:
            dt: datetime to calculate sun position for
            
        returns:
            SunPosition with azimuth, altitude, and daylight info
        """
        # day of year (1-366)
        day_of_year = dt.timetuple().tm_yday
        
        # calculate solar declination angle
        # this is the angle between sun rays and earth's equatorial plane
        declination = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
        
        # convert to radians
        lat_rad = math.radians(self.latitude)
        dec_rad = math.radians(declination)
        
        # calculate sunrise/sunset times
        try:
            # hour angle at sunrise/sunset
            cos_hour_angle = -math.tan(lat_rad) * math.tan(dec_rad)
            cos_hour_angle = max(-1, min(1, cos_hour_angle))  # clamp to valid range
            hour_angle = math.degrees(math.acos(cos_hour_angle))
            
            # sunrise and sunset times (in hours from midnight)
            sunrise_hour = 12 - (hour_angle / 15)
            sunset_hour = 12 + (hour_angle / 15)
            
            # format as hh:mm
            sunrise_str = f"{int(sunrise_hour):02d}:{int((sunrise_hour % 1) * 60):02d}"
            sunset_str = f"{int(sunset_hour):02d}:{int((sunset_hour % 1) * 60):02d}"
        except:
            sunrise_str = "06:00"
            sunset_str = "18:00"
            sunrise_hour = 6
            sunset_hour = 18
        
        # current time in hours
        current_hour = dt.hour + dt.minute / 60 + dt.second / 3600
        
        # calculate hour angle (degrees from solar noon)
        # negative = morning, positive = afternoon
        solar_noon = 12 - (self.longitude - 15 * self.timezone_offset) / 15
        hour_angle_now = 15 * (current_hour - solar_noon)
        
        # calculate sun altitude (elevation angle)
        sin_altitude = (math.sin(lat_rad) * math.sin(dec_rad) + 
                       math.cos(lat_rad) * math.cos(dec_rad) * 
                       math.cos(math.radians(hour_angle_now)))
        altitude = math.degrees(math.asin(max(-1, min(1, sin_altitude))))
        
        # calculate sun azimuth (compass direction)
        cos_azimuth = ((math.sin(dec_rad) - math.sin(lat_rad) * sin_altitude) / 
                      (math.cos(lat_rad) * math.cos(math.radians(altitude))))
        cos_azimuth = max(-1, min(1, cos_azimuth))
        azimuth = math.degrees(math.acos(cos_azimuth))
        
        # adjust azimuth for afternoon (west)
        if hour_angle_now > 0:
            azimuth = 360 - azimuth
        
        # determine if sun is up
        is_daylight = altitude > 0
        
        return SunPosition(
            azimuth=round(azimuth, 1),
            altitude=round(altitude, 1),
            sunrise=sunrise_str,
            sunset=sunset_str,
            is_daylight=is_daylight,
            solar_noon=f"{int(solar_noon):02d}:{int((solar_noon % 1) * 60):02d}"
        )
    
    def get_sun_positions_for_period(self, start: datetime, end: datetime, 
                                     interval_minutes: int = 15) -> List[SunPosition]:
        """
        get sun positions for a time period.
        
        args:
            start: start datetime
            end: end datetime
            interval_minutes: time between position calculations
            
        returns:
            list of SunPosition objects
        """
        positions = []
        current = start
        while current <= end:
            positions.append(self.get_sun_position(current))
            current += timedelta(minutes=interval_minutes)
        return positions


# -----------------------------------------------------------------------------
# shadow coverage calculator
# -----------------------------------------------------------------------------

class ShadowCalculator:
    """
    calculates shadow coverage based on sun position and urban environment.
    
    uses simplified urban geometry model to estimate shadow coverage
    at different times of day.
    """
    
    def __init__(self, urban_density: float = 0.7):
        """
        initialize shadow calculator.
        
        args:
            urban_density: 0-1 scale of how built-up the area is
                          higher = more buildings = more potential shade
        """
        self.urban_density = urban_density
    
    def calculate_shadow_coverage(self, sun_position: SunPosition, 
                                  building_heights: Optional[List[float]] = None) -> float:
        """
        estimate shadow coverage percentage for given sun position.
        
        args:
            sun_position: current sun position
            building_heights: optional list of nearby building heights
            
        returns:
            shadow coverage as percentage (0-100)
        """
        if not sun_position.is_daylight:
            return 100.0  # full shadow at night
        
        altitude = sun_position.altitude
        
        # shadow length factor - lower sun = longer shadows
        if altitude <= 0:
            shadow_factor = 1.0
        elif altitude >= 90:
            shadow_factor = 0.0
        else:
            # shadow length = building height / tan(altitude)
            # higher altitude = shorter shadows
            shadow_factor = 1.0 / max(0.1, math.tan(math.radians(max(5, altitude))))
            shadow_factor = min(1.0, shadow_factor / 10)  # normalize
        
        # time-based shadow patterns in urban areas
        # early morning and late afternoon have more shade from buildings
        hour = (sun_position.azimuth / 15) % 24  # rough hour estimate
        
        # base coverage from urban density
        base_coverage = self.urban_density * 30  # 0-30% base from buildings
        
        # altitude-based coverage
        if altitude < 15:
            altitude_coverage = 60  # very long shadows at low altitude
        elif altitude < 30:
            altitude_coverage = 40
        elif altitude < 45:
            altitude_coverage = 25
        elif altitude < 60:
            altitude_coverage = 15
        else:
            altitude_coverage = 8  # minimal shadows when sun is overhead
        
        # combine factors
        total_coverage = min(95, base_coverage + altitude_coverage * shadow_factor)
        
        return round(total_coverage, 1)
    
    def calculate_sun_exposure(self, sun_positions: List[SunPosition], 
                               interval_minutes: int = 15) -> float:
        """
        calculate total sun exposure in minutes for a period.
        
        args:
            sun_positions: list of sun positions for the period
            interval_minutes: time between each position sample
            
        returns:
            minutes of direct sun exposure
        """
        exposure_minutes = 0.0
        
        for pos in sun_positions:
            if pos.is_daylight:
                # higher altitude = more direct exposure
                shadow_coverage = self.calculate_shadow_coverage(pos) / 100
                exposure_factor = 1.0 - shadow_coverage
                exposure_minutes += interval_minutes * exposure_factor
        
        return round(exposure_minutes, 1)


# -----------------------------------------------------------------------------
# heat risk calculator
# -----------------------------------------------------------------------------

class HeatRiskCalculator:
    """
    calculates heat risk based on weather conditions and sun exposure.
    
    uses osha/niosh guidelines for heat stress thresholds.
    """
    
    # heat risk thresholds based on wbgt (wet bulb globe temperature)
    WBGT_LOW = 25.0      # below this = low risk
    WBGT_MEDIUM = 28.0   # below this = medium risk
    WBGT_HIGH = 31.0     # above this = high risk
    
    def __init__(self):
        pass
    
    def calculate_wbgt(self, temperature: float, humidity: float, 
                       sun_altitude: float, wind_speed: float = 5.0,
                       in_shadow: bool = False) -> float:
        """
        estimate wet bulb globe temperature (wbgt).
        
        wbgt is the standard heat stress index used by osha/niosh.
        simplified formula: wbgt ≈ 0.7*tw + 0.2*tg + 0.1*ta
        
        args:
            temperature: air temperature in celsius
            humidity: relative humidity percentage
            sun_altitude: sun altitude in degrees
            wind_speed: wind speed in km/h
            in_shadow: whether the location is in shadow
            
        returns:
            estimated wbgt in celsius
        """
        # wet bulb temperature estimation
        # approximation: tw ≈ t * atan(0.151977 * sqrt(h + 8.313659))
        tw = temperature * math.atan(0.151977 * math.sqrt(humidity + 8.313659))
        tw += math.atan(temperature + humidity)
        tw -= math.atan(humidity - 1.676331)
        tw += 0.00391838 * pow(humidity, 1.5) * math.atan(0.023101 * humidity)
        tw -= 4.686035
        
        # globe temperature estimation
        # higher when in direct sun, lower in shade
        if in_shadow or sun_altitude <= 0:
            solar_load = 0
        else:
            solar_load = min(1.0, sun_altitude / 60) * 10
        
        # wind reduces perceived heat
        wind_factor = max(0.5, 1 - (wind_speed / 30))
        
        tg = temperature + solar_load * wind_factor
        
        # wbgt calculation
        wbgt = 0.7 * tw + 0.2 * tg + 0.1 * temperature
        
        return round(wbgt, 1)
    
    def get_risk_level(self, wbgt: float) -> Tuple[int, str]:
        """
        get heat risk level from wbgt.
        
        returns:
            tuple of (risk_level: 0-2, risk_label: low/medium/high)
        """
        if wbgt < self.WBGT_LOW:
            return (0, "low")
        elif wbgt < self.WBGT_MEDIUM:
            return (1, "medium")
        else:
            return (2, "high")
    
    def calculate_heat_risk(self, temperature: float, humidity: float,
                           sun_altitude: float, wind_speed: float = 5.0,
                           shadow_coverage: float = 50.0,
                           uv_index: float = 5.0) -> Dict[str, Any]:
        """
        comprehensive heat risk calculation.
        
        args:
            temperature: air temperature in celsius
            humidity: relative humidity percentage
            sun_altitude: sun altitude in degrees
            wind_speed: wind speed in km/h
            shadow_coverage: percentage of area in shadow
            uv_index: uv index (0-11+)
            
        returns:
            dict with risk metrics and recommendations
        """
        # determine if effectively in shadow
        in_shadow = shadow_coverage > 50
        
        # calculate wbgt
        wbgt = self.calculate_wbgt(temperature, humidity, sun_altitude, 
                                   wind_speed, in_shadow)
        
        # get risk level
        risk_level, risk_label = self.get_risk_level(wbgt)
        
        # calculate risk score (0-2 continuous)
        if wbgt < self.WBGT_LOW:
            risk_score = wbgt / self.WBGT_LOW
        elif wbgt < self.WBGT_MEDIUM:
            risk_score = 1 + (wbgt - self.WBGT_LOW) / (self.WBGT_MEDIUM - self.WBGT_LOW)
        else:
            risk_score = min(2.0, 2 + (wbgt - self.WBGT_MEDIUM) / 10)
        
        # uv risk adjustment
        uv_risk = 0
        if uv_index >= 11:
            uv_risk = 0.3
            uv_label = "extreme"
        elif uv_index >= 8:
            uv_risk = 0.2
            uv_label = "very high"
        elif uv_index >= 6:
            uv_risk = 0.1
            uv_label = "high"
        elif uv_index >= 3:
            uv_risk = 0.05
            uv_label = "moderate"
        else:
            uv_label = "low"
        
        combined_risk = min(2.0, risk_score + uv_risk)
        
        # generate safety message
        if risk_label == "low":
            message = "safe for extended outdoor activity"
        elif risk_label == "medium":
            message = "take breaks every 30-45 minutes, stay hydrated"
        else:
            message = "avoid prolonged outdoor exposure if possible"
        
        # add uv warning if needed
        if uv_index >= 8:
            message += f". uv index is {uv_label} - use sun protection"
        
        return {
            "wbgt": wbgt,
            "risk_level": risk_level,
            "risk_label": risk_label,
            "risk_score": round(combined_risk, 2),
            "uv_index": uv_index,
            "uv_label": uv_label,
            "in_shadow": in_shadow,
            "safety_message": message,
            "max_exposure_minutes": self._calculate_max_exposure(risk_level)
        }
    
    def _calculate_max_exposure(self, risk_level: int) -> int:
        """calculate recommended maximum exposure time"""
        if risk_level == 0:
            return 240  # 4 hours
        elif risk_level == 1:
            return 120  # 2 hours
        else:
            return 45   # 45 minutes


# -----------------------------------------------------------------------------
# core scheduling engine
# -----------------------------------------------------------------------------

class SchedulingEngine:
    """
    core scheduling engine that calculates optimal time slots.
    
    this is the foundation that the ml optimizer builds upon.
    it provides deterministic calculations of shadow coverage,
    sun exposure, and heat risk for any time slot.
    """
    
    def __init__(self, latitude: float = 25.2048, longitude: float = 55.2708,
                 timezone_offset: int = 4, urban_density: float = 0.7):
        """
        initialize scheduling engine.
        
        args:
            latitude: location latitude
            longitude: location longitude
            timezone_offset: utc offset in hours
            urban_density: 0-1 scale of urban development
        """
        self.solar_calculator = SolarCalculator(latitude, longitude, timezone_offset)
        self.shadow_calculator = ShadowCalculator(urban_density)
        self.heat_calculator = HeatRiskCalculator()
        
        self.latitude = latitude
        self.longitude = longitude
    
    def generate_time_slots(self, date: datetime, earliest_hour: int = 0,
                           latest_hour: int = 23, duration_minutes: int = 60,
                           slot_interval: int = 30) -> List[TimeSlot]:
        """
        generate all possible time slots for a day.
        
        args:
            date: the date to generate slots for
            earliest_hour: earliest start hour (0-23)
            latest_hour: latest end hour (0-23)
            duration_minutes: task duration in minutes
            slot_interval: minutes between slot start times
            
        returns:
            list of TimeSlot objects
        """
        slots = []
        
        # generate start times
        current_hour = earliest_hour
        current_minute = 0
        
        while True:
            start_time = date.replace(hour=current_hour, minute=current_minute, 
                                     second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # check if slot fits within allowed window
            if end_time.hour > latest_hour or (end_time.hour == latest_hour and 
                                                end_time.minute > 0 and
                                                latest_hour < 23):
                break
            
            slot = TimeSlot(
                start_time=start_time,
                end_time=end_time,
                duration_minutes=duration_minutes
            )
            slots.append(slot)
            
            # move to next slot
            current_minute += slot_interval
            while current_minute >= 60:
                current_minute -= 60
                current_hour += 1
            
            if current_hour > latest_hour:
                break
        
        return slots
    
    def evaluate_time_slot(self, slot: TimeSlot, temperature: float = 30.0,
                          humidity: float = 50.0, wind_speed: float = 10.0,
                          uv_index: float = 6.0) -> TimeSlot:
        """
        evaluate a time slot and calculate all metrics.
        
        args:
            slot: the time slot to evaluate
            temperature: air temperature in celsius
            humidity: relative humidity percentage
            wind_speed: wind speed in km/h
            uv_index: uv index
            
        returns:
            the same TimeSlot with calculated metrics
        """
        # get sun positions throughout the slot
        slot.sun_positions = self.solar_calculator.get_sun_positions_for_period(
            slot.start_time, slot.end_time, interval_minutes=15
        )
        
        if not slot.sun_positions:
            return slot
        
        # calculate sun metrics
        altitudes = [p.altitude for p in slot.sun_positions]
        slot.avg_sun_altitude = round(np.mean(altitudes), 1)
        slot.max_sun_altitude = round(max(altitudes), 1)
        
        # calculate shadow coverage for each position
        shadow_coverages = [
            self.shadow_calculator.calculate_shadow_coverage(p) 
            for p in slot.sun_positions
        ]
        slot.shadow_coverage = round(np.mean(shadow_coverages), 1)
        
        # calculate sun exposure
        slot.sun_exposure_minutes = self.shadow_calculator.calculate_sun_exposure(
            slot.sun_positions, interval_minutes=15
        )
        
        # calculate heat risk
        avg_altitude = slot.avg_sun_altitude if slot.avg_sun_altitude > 0 else 0
        heat_result = self.heat_calculator.calculate_heat_risk(
            temperature=temperature,
            humidity=humidity,
            sun_altitude=avg_altitude,
            wind_speed=wind_speed,
            shadow_coverage=slot.shadow_coverage,
            uv_index=uv_index
        )
        
        slot.heat_risk_score = heat_result["risk_score"]
        slot.heat_risk_level = heat_result["risk_label"]
        slot.uv_index = uv_index
        
        # calculate quality score (0-100)
        # higher is better
        slot.quality_score = self._calculate_quality_score(slot, heat_result)
        
        # generate warnings
        slot.warnings = self._generate_warnings(slot, heat_result)
        
        return slot
    
    def _calculate_quality_score(self, slot: TimeSlot, 
                                  heat_result: Dict[str, Any]) -> float:
        """
        calculate overall quality score for a time slot.
        
        considers:
        - shadow coverage (higher = better)
        - heat risk (lower = better)
        - uv index (lower = better)
        - sun exposure (lower = better for shade-seeking tasks)
        """
        score = 100.0
        
        # shadow coverage contribution (0-40 points)
        # more shadow = higher score
        shadow_score = (slot.shadow_coverage / 100) * 40
        
        # heat risk penalty (0-35 points deducted)
        heat_penalty = slot.heat_risk_score * 17.5
        
        # uv penalty (0-15 points deducted)
        uv_penalty = min(15, slot.uv_index * 1.5)
        
        # sun exposure penalty (0-10 points deducted)
        # penalize if sun exposure > 50% of slot duration
        exposure_ratio = slot.sun_exposure_minutes / slot.duration_minutes
        exposure_penalty = min(10, exposure_ratio * 10)
        
        # time of day bonus/penalty
        # early morning (5-8) and late afternoon (16-19) get bonus
        hour = slot.start_time.hour
        if 5 <= hour <= 8 or 16 <= hour <= 19:
            time_bonus = 5
        elif 11 <= hour <= 14:
            time_bonus = -5  # penalty for midday
        else:
            time_bonus = 0
        
        score = shadow_score + (60 - heat_penalty - uv_penalty - exposure_penalty) + time_bonus
        
        return round(max(0, min(100, score)), 1)
    
    def _generate_warnings(self, slot: TimeSlot, 
                           heat_result: Dict[str, Any]) -> List[str]:
        """generate warning messages for the time slot"""
        warnings = []
        
        if slot.heat_risk_level == "high":
            warnings.append("high heat risk - consider rescheduling")
        elif slot.heat_risk_level == "medium":
            warnings.append("moderate heat risk - take regular breaks")
        
        if slot.uv_index >= 8:
            warnings.append("very high uv - sun protection required")
        
        if slot.shadow_coverage < 30:
            warnings.append("low shade availability")
        
        if slot.sun_exposure_minutes > slot.duration_minutes * 0.7:
            warnings.append("high sun exposure expected")
        
        return warnings
    
    def find_best_slots(self, request: ScheduleRequest,
                       temperature: float = 30.0, humidity: float = 50.0,
                       wind_speed: float = 10.0, uv_index: float = 6.0,
                       top_n: int = 5) -> ScheduleResult:
        """
        find the best time slots for a scheduling request.
        
        args:
            request: the scheduling request
            temperature: air temperature in celsius
            humidity: relative humidity percentage
            wind_speed: wind speed in km/h
            uv_index: uv index
            top_n: number of alternative slots to return
            
        returns:
            ScheduleResult with best slot and alternatives
        """
        # generate all possible slots
        all_slots = self.generate_time_slots(
            date=request.date,
            earliest_hour=request.earliest_start,
            latest_hour=request.latest_end,
            duration_minutes=request.duration_minutes,
            slot_interval=30
        )
        
        if not all_slots:
            # no valid slots - return empty result
            return ScheduleResult(
                request=request,
                best_slot=TimeSlot(
                    start_time=request.date,
                    end_time=request.date,
                    duration_minutes=request.duration_minutes,
                    quality_score=0,
                    warnings=["no valid time slots found"]
                ),
                alternative_slots=[],
                all_slots=[],
                summary="no valid time slots available for this request"
            )
        
        # evaluate each slot
        evaluated_slots = []
        for slot in all_slots:
            evaluated_slot = self.evaluate_time_slot(
                slot, temperature, humidity, wind_speed, uv_index
            )
            evaluated_slots.append(evaluated_slot)
        
        # sort by quality score (highest first)
        evaluated_slots.sort(key=lambda s: s.quality_score, reverse=True)
        
        # mark the best slot
        best_slot = evaluated_slots[0]
        best_slot.is_optimal = True
        
        # get alternatives (excluding the best)
        alternatives = evaluated_slots[1:top_n+1] if len(evaluated_slots) > 1 else []
        
        # generate summary
        summary = self._generate_summary(request, best_slot, evaluated_slots)
        
        return ScheduleResult(
            request=request,
            best_slot=best_slot,
            alternative_slots=alternatives,
            all_slots=evaluated_slots,
            summary=summary
        )
    
    def _generate_summary(self, request: ScheduleRequest, best_slot: TimeSlot,
                          all_slots: List[TimeSlot]) -> str:
        """generate human-readable summary of the scheduling result"""
        start_str = best_slot.start_time.strftime("%H:%M")
        end_str = best_slot.end_time.strftime("%H:%M")
        date_str = request.date.strftime("%b %d, %Y")
        
        summary = f"recommended: {start_str} - {end_str} on {date_str}. "
        summary += f"shadow coverage: {best_slot.shadow_coverage}%. "
        summary += f"heat risk: {best_slot.heat_risk_level}. "
        summary += f"quality score: {best_slot.quality_score}/100. "
        
        if best_slot.warnings:
            summary += f"note: {'; '.join(best_slot.warnings)}"
        
        return summary


# -----------------------------------------------------------------------------
# utility functions
# -----------------------------------------------------------------------------

def calculate_quality_score(start_hour: float, avg_heat_risk: float,
                           shade_percentage: float, duration_minutes: int,
                           task_completes_on_time: bool) -> float:
    """
    standalone quality score calculation for compatibility.
    
    this function is used by the optimizer for training data generation.
    """
    if not task_completes_on_time:
        return 0.0
    
    score = 100.0
    
    # shade contribution (0-40 points)
    shadow_score = (shade_percentage / 100) * 40
    
    # heat risk penalty (0-35 points)
    heat_penalty = avg_heat_risk * 17.5
    
    # time of day bonus
    if 5 <= start_hour <= 8 or 16 <= start_hour <= 19:
        time_bonus = 5
    elif 11 <= start_hour <= 14:
        time_bonus = -5
    else:
        time_bonus = 0
    
    score = shadow_score + (60 - heat_penalty) + time_bonus
    
    return max(0, min(100, score))


# -----------------------------------------------------------------------------
# test/demo
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== smartshift scheduling engine test ===\n")
    
    # create engine for dubai
    engine = SchedulingEngine(
        latitude=25.2048,
        longitude=55.2708,
        timezone_offset=4,
        urban_density=0.7
    )
    
    # create a test request
    tomorrow = datetime.now() + timedelta(days=1)
    request = ScheduleRequest(
        task_name="facade cleaning",
        location_lat=25.2048,
        location_lon=55.2708,
        location_name="downtown dubai",
        date=tomorrow.replace(hour=0, minute=0, second=0, microsecond=0),
        duration_minutes=120,
        earliest_start=6,
        latest_end=18,
        task_type="cleaning"
    )
    
    # find best slots with realistic dubai weather
    result = engine.find_best_slots(
        request=request,
        temperature=35.0,  # typical dubai summer
        humidity=60.0,
        wind_speed=15.0,
        uv_index=9.0
    )
    
    # print results
    print(f"task: {request.task_name}")
    print(f"location: {request.location_name}")
    print(f"date: {request.date.strftime('%Y-%m-%d')}")
    print(f"duration: {request.duration_minutes} minutes")
    print(f"\n--- best time slot ---")
    best = result.best_slot
    print(f"time: {best.start_time.strftime('%H:%M')} - {best.end_time.strftime('%H:%M')}")
    print(f"quality score: {best.quality_score}/100")
    print(f"shadow coverage: {best.shadow_coverage}%")
    print(f"heat risk: {best.heat_risk_level} ({best.heat_risk_score:.2f})")
    print(f"sun exposure: {best.sun_exposure_minutes} minutes")
    
    if best.warnings:
        print(f"warnings: {', '.join(best.warnings)}")
    
    print(f"\n--- alternatives ---")
    for i, alt in enumerate(result.alternative_slots[:3], 1):
        print(f"{i}. {alt.start_time.strftime('%H:%M')} - {alt.end_time.strftime('%H:%M')} "
              f"(score: {alt.quality_score}, shadow: {alt.shadow_coverage}%)")
    
    print(f"\n--- summary ---")
    print(result.summary)







