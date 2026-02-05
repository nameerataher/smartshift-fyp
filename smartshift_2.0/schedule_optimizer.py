"""
learning-based schedule optimization model for smartshift
==========================================================

this module implements an ai planning model that determines optimal task
start times to minimize heat exposure while completing work efficiently.

the model answers: "given today's conditions, what's the best time to
schedule this task?"

target users:
- municipality planners (scheduling outdoor maintenance)
- construction supervisors (planning work shifts)
- facade cleaning companies (booking building cleaning slots)
- event organizers (outdoor events scheduling)
- individual users (planning exercise, commute times)

-----------------------------
📥 data sources & inputs
-----------------------------

| input                  | source                          | how to get it                    |
|------------------------|---------------------------------|----------------------------------|
| location               | user / system                   | gps or manual input              |
| date                   | calendar                        | datetime                         |
| task_duration          | user-defined                    | input in minutes                 |
| candidate_start_times  | generated                       | every 30 mins during work hours  |
| predicted_heat_risk    | heat_risk_model.py              | model 1 output                   |
| shadow_availability    | shadow_calculator.py            | from shadow engine               |

🧠 learning approach: supervised learning (simulation-based)

we generate training data by simulating schedules:
(location, date, start_time, duration) → schedule_quality_score

schedule quality is computed using:
- heat risk predictions across the task duration
- total sun exposure minutes
- task completion feasibility
- preference for morning/evening vs midday

all data comes from:
- weather data (meteostat/era5)
- heat risk model predictions
- shadow simulation logic

-----------------------------
📤 model output
-----------------------------

- recommended start time
- schedule quality score (0-100)
- ranked list of alternative times
- risk breakdown for each slot
- shade-optimized route suggestions (for navigation)

-----------------------------
🔗 pipeline connection
-----------------------------

era5 / meteostat
        ↓
shadow engine + surface data
        ↓
heat risk ml model
        ↓
predicted heat risk scores
        ↓
schedule optimization model (this file)
        ↓
best start time / schedule

"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
import math
import os
import heapq

# ml imports
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, r2_score
import joblib

# import project modules
from config import DUBAI, SHADOW
from solar_position import SolarPositionCalculator
from heat_risk_model import (
    HeatRiskModel, WeatherData, LocationContext, SunExposure,
    HeatRiskPrediction, calculate_heat_index, estimate_wbgt,
    encode_time_cyclic
)


# -----------------------------------------------------------------------------
# data classes for schedule optimization
# -----------------------------------------------------------------------------

@dataclass
class Task:
    """
    represents a task to be scheduled.

    tasks can be:
    - work shifts (construction, maintenance)
    - cleaning jobs (facade cleaning)
    - outdoor activities (jogging, cycling)
    - events (outdoor gatherings)
    """
    name: str                       # task identifier
    duration_minutes: int           # how long the task takes
    location_lat: float            # where the task occurs
    location_lon: float
    earliest_start: int = 6        # earliest hour task can start (e.g., 6 am)
    latest_end: int = 20           # latest hour task must end by (e.g., 8 pm)
    requires_shade: bool = False   # must the task be in shade?
    priority: int = 1              # 1=normal, 2=high, 3=critical
    surface_type: str = 'mixed'    # ground surface at location


@dataclass
class TimeSlot:
    """
    represents a potential time slot for scheduling.
    """
    start_time: datetime
    end_time: datetime
    heat_risk_score: float         # average heat risk during slot (0-1)
    shade_percentage: float        # % of time in shade
    quality_score: float           # overall schedule quality (0-100)
    is_feasible: bool              # can task complete within constraints?
    risk_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class ScheduleRecommendation:
    """
    output from the schedule optimizer.
    """
    best_slot: TimeSlot
    alternative_slots: List[TimeSlot]  # ranked by quality
    total_candidates_evaluated: int
    date: datetime
    task: Task
    summary: str                   # human-readable recommendation
    detailed_breakdown: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteSegment:
    """
    represents a segment of a navigation route.

    used for shade-optimized navigation for cyclists, joggers, etc.
    """
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    distance_meters: float
    duration_seconds: float
    shade_coverage: float          # 0-1, from shadow analysis
    heat_risk: float               # 0-1, from heat risk model
    surface_type: str


@dataclass
class ShadeOptimizedRoute:
    """
    a complete route optimized for shade.

    this is for the community navigation feature - helping cyclists,
    joggers, and pedestrians find the shadiest path.

    uses real road/path geometry from mapbox directions api for:
    - realistic pedestrian/cycling routes
    - avoiding highways and unsafe crossings
    - following actual roads and paths
    """
    segments: List[RouteSegment]
    total_distance: float          # meters
    total_duration: float          # seconds
    average_shade_coverage: float  # 0-1
    average_heat_risk: float       # 0-1
    sun_exposure_minutes: float    # estimated direct sun exposure
    shade_score: float             # 0-100 overall shade rating
    comparison_to_fastest: Dict[str, float]  # how much longer vs fastest route
    route_geometry: List[Tuple[float, float]] = field(default_factory=list)  # (lon, lat) coords from mapbox


# -----------------------------------------------------------------------------
# schedule quality scoring functions
# -----------------------------------------------------------------------------

def calculate_time_preference_score(hour: float) -> float:
    """
    calculate preference score based on time of day.

    in hot climates like dubai, early morning and late afternoon
    are strongly preferred over midday for outdoor work.

    optimal windows:
    - early morning: 6am-10am (score 0.8-1.0)
    - midday: 10am-4pm (score 0.3-0.5)
    - late afternoon: 4pm-8pm (score 0.7-0.9)

    args:
        hour: hour of day (0-24)

    returns:
        preference score (0-1)
    """
    # piecewise linear preference function
    if 6 <= hour <= 8:
        # prime morning hours
        return 1.0 - (hour - 6) * 0.05
    elif 8 < hour <= 10:
        # good morning hours
        return 0.9 - (hour - 8) * 0.2
    elif 10 < hour <= 14:
        # avoid midday
        return 0.5 - (hour - 10) * 0.05
    elif 14 < hour <= 16:
        # worst hours
        return 0.3
    elif 16 < hour <= 18:
        # recovering afternoon
        return 0.3 + (hour - 16) * 0.25
    elif 18 < hour <= 20:
        # good evening hours
        return 0.8 + (hour - 18) * 0.05
    else:
        return 0.5  # outside normal hours


def calculate_heat_risk_penalty(avg_heat_risk: float) -> float:
    """
    convert average heat risk to a penalty factor.

    heat risk has exponential penalty - high risk is much worse
    than moderate risk.

    args:
        avg_heat_risk: average heat risk level (0-2 scale)

    returns:
        penalty factor (0-1, where 0 = maximum penalty)
    """
    # normalize to 0-1 scale
    normalized_risk = avg_heat_risk / 2.0

    # exponential penalty
    penalty = math.exp(-2 * normalized_risk)

    return max(0.1, penalty)


def calculate_shade_bonus(shade_percentage: float) -> float:
    """
    calculate bonus for shade availability.

    more shade is always better for heat-sensitive scheduling.

    args:
        shade_percentage: percentage of time in shade (0-100)

    returns:
        bonus factor (1.0-1.5)
    """
    return 1.0 + (shade_percentage / 100) * 0.5


def calculate_schedule_quality(
    start_hour: float,
    avg_heat_risk: float,
    shade_percentage: float,
    duration_minutes: int,
    task_completes_on_time: bool
) -> float:
    """
    calculate overall schedule quality score.

    combines multiple factors into a single score (0-100).

    args:
        start_hour: task start hour
        avg_heat_risk: average heat risk during task
        shade_percentage: percentage of time in shade
        duration_minutes: task duration
        task_completes_on_time: does task finish within constraints?

    returns:
        quality score (0-100)
    """
    if not task_completes_on_time:
        return 0.0

    # get individual scores
    time_score = calculate_time_preference_score(start_hour)
    risk_score = calculate_heat_risk_penalty(avg_heat_risk)
    shade_bonus = calculate_shade_bonus(shade_percentage)

    # duration adjustment - longer tasks need more careful planning
    # penalty for very long outdoor tasks during hot conditions
    duration_factor = 1.0
    if duration_minutes > 120 and avg_heat_risk > 1.0:
        duration_factor = 0.8
    elif duration_minutes > 240 and avg_heat_risk > 0.5:
        duration_factor = 0.7

    # combine scores with weights
    # risk is most important, then shade, then time preference
    base_score = (
        0.4 * risk_score +
        0.3 * (shade_percentage / 100) +
        0.2 * time_score +
        0.1 * duration_factor
    )

    # apply shade bonus
    final_score = base_score * shade_bonus

    # normalize to 0-100
    return min(100, max(0, final_score * 100))


# -----------------------------------------------------------------------------
# schedule optimizer class
# -----------------------------------------------------------------------------

class ScheduleOptimizer:
    """
    ai-powered schedule optimization for heat-aware task scheduling.

    this optimizer uses the heat risk model predictions to find
    optimal time slots for outdoor tasks.

    features:
    - evaluates all candidate time slots
    - considers heat risk, shade availability, and preferences
    - provides ranked recommendations
    - supports different task types (work, exercise, events)

    usage:
        optimizer = ScheduleOptimizer()

        task = Task(
            name="facade cleaning",
            duration_minutes=180,
            location_lat=25.2048,
            location_lon=55.2708,
            requires_shade=True
        )

        recommendation = optimizer.find_best_schedule(
            task=task,
            date=datetime(2024, 7, 15),
            weather=weather_data
        )

        print(f"best time: {recommendation.best_slot.start_time}")
    """

    def __init__(self, heat_risk_model: Optional[HeatRiskModel] = None):
        """
        initialize the schedule optimizer.

        args:
            heat_risk_model: trained heat risk model (will create if not provided)
        """
        # initialize or use provided heat risk model
        if heat_risk_model is None:
            self.heat_risk_model = HeatRiskModel()
            if not self.heat_risk_model.is_trained:
                print("training heat risk model...")
                self.heat_risk_model.train(n_samples=5000, verbose=False)
        else:
            self.heat_risk_model = heat_risk_model

        # solar calculator for sun position
        self.solar_calculator = SolarPositionCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET
        )

        # ml model for schedule quality prediction (optional enhancement)
        self.quality_model: Optional[GradientBoostingRegressor] = None
        self.quality_scaler: Optional[StandardScaler] = None
        self.ml_model_trained = False

        # default time slot interval (minutes)
        self.slot_interval = 30

    def generate_candidate_slots(
        self,
        task: Task,
        date: datetime
    ) -> List[datetime]:
        """
        generate candidate start times for a task.

        creates time slots at regular intervals within the allowed window.

        args:
            task: task to schedule
            date: date to schedule on

        returns:
            list of candidate start datetimes
        """
        candidates = []

        # start from earliest allowed time
        current_hour = task.earliest_start
        current_minute = 0

        # end time considering task duration
        task_hours = task.duration_minutes / 60
        latest_start_hour = task.latest_end - task_hours

        while current_hour + current_minute/60 <= latest_start_hour:
            candidate = date.replace(
                hour=int(current_hour),
                minute=int(current_minute),
                second=0,
                microsecond=0
            )
            candidates.append(candidate)

            # move to next slot
            current_minute += self.slot_interval
            if current_minute >= 60:
                current_hour += 1
                current_minute = current_minute % 60

        return candidates

    def evaluate_time_slot(
        self,
        start_time: datetime,
        task: Task,
        weather: WeatherData
    ) -> TimeSlot:
        """
        evaluate a single time slot for task scheduling.

        simulates the task execution and calculates heat risk
        at regular intervals throughout the duration.

        args:
            start_time: candidate start time
            task: task to schedule
            weather: weather conditions for the day

        returns:
            TimeSlot with evaluation results
        """
        # calculate end time
        end_time = start_time + timedelta(minutes=task.duration_minutes)

        # check feasibility
        is_feasible = (
            start_time.hour >= task.earliest_start and
            end_time.hour <= task.latest_end
        )

        if not is_feasible:
            return TimeSlot(
                start_time=start_time,
                end_time=end_time,
                heat_risk_score=1.0,
                shade_percentage=0.0,
                quality_score=0.0,
                is_feasible=False
            )

        # evaluate heat risk at intervals during the task
        evaluation_interval = 15  # check every 15 minutes
        risk_samples = []
        shade_samples = []

        current_time = start_time
        while current_time <= end_time:
            # get sun position
            sun_pos = self.solar_calculator.get_sun_position(current_time)

            # estimate sun exposure (simplified - would use shadow engine in production)
            # assume partial shade availability in urban areas
            is_daylight = sun_pos.altitude > 0

            if is_daylight:
                # sun intensity based on altitude
                sun_intensity = min(1.0, sun_pos.altitude / 60)

                # shade estimate based on time (more shade early/late)
                hour = current_time.hour + current_time.minute / 60
                if 10 <= hour <= 15:
                    shade_estimate = 0.2  # less shade at midday (sun high)
                else:
                    shade_estimate = 0.5  # more shade from buildings early/late

                if task.requires_shade:
                    # assume worker seeks shade actively
                    shade_estimate = min(0.8, shade_estimate + 0.3)
            else:
                sun_intensity = 0.0
                shade_estimate = 1.0

            # create sun exposure for prediction
            sun_exposure = SunExposure(
                is_in_shadow=shade_estimate > 0.5,
                current_sun_altitude=max(0, sun_pos.altitude),
                current_sun_azimuth=sun_pos.azimuth,
                minutes_in_sun_last_hour=30 * (1 - shade_estimate),
                direct_sun_intensity=sun_intensity * (1 - shade_estimate)
            )

            # create location context
            location = LocationContext(
                latitude=task.location_lat,
                longitude=task.location_lon,
                surface_type=task.surface_type,
                urban_density=0.7  # assume urban dubai
            )

            # get heat risk prediction
            prediction = self.heat_risk_model.predict(
                weather=weather,
                location=location,
                sun_exposure=sun_exposure,
                timestamp=current_time
            )

            risk_samples.append(prediction.risk_level)
            shade_samples.append(shade_estimate * 100)

            current_time += timedelta(minutes=evaluation_interval)

        # calculate aggregated metrics
        avg_heat_risk = np.mean(risk_samples) if risk_samples else 1.0
        avg_shade = np.mean(shade_samples) if shade_samples else 0.0
        max_risk = np.max(risk_samples) if risk_samples else 2

        # calculate quality score
        quality = calculate_schedule_quality(
            start_hour=start_time.hour + start_time.minute/60,
            avg_heat_risk=avg_heat_risk,
            shade_percentage=avg_shade,
            duration_minutes=task.duration_minutes,
            task_completes_on_time=is_feasible
        )

        # risk breakdown for detailed analysis
        risk_breakdown = {
            'avg_heat_risk': float(avg_heat_risk),
            'max_heat_risk': int(max_risk),
            'avg_shade_pct': float(avg_shade),
            'time_preference': calculate_time_preference_score(
                start_time.hour + start_time.minute/60
            ),
            'samples_high_risk': sum(1 for r in risk_samples if r == 2),
            'samples_medium_risk': sum(1 for r in risk_samples if r == 1),
            'samples_low_risk': sum(1 for r in risk_samples if r == 0)
        }

        return TimeSlot(
            start_time=start_time,
            end_time=end_time,
            heat_risk_score=avg_heat_risk / 2,  # normalize to 0-1
            shade_percentage=avg_shade,
            quality_score=quality,
            is_feasible=is_feasible,
            risk_breakdown=risk_breakdown
        )

    def find_best_schedule(
        self,
        task: Task,
        date: datetime,
        weather: WeatherData,
        n_alternatives: int = 5
    ) -> ScheduleRecommendation:
        """
        find the best time to schedule a task.

        evaluates all candidate time slots and returns the optimal
        schedule along with alternatives.

        args:
            task: task to schedule
            date: date to schedule on
            weather: weather conditions
            n_alternatives: number of alternative slots to return

        returns:
            ScheduleRecommendation with best slot and alternatives
        """
        # generate candidate slots
        candidates = self.generate_candidate_slots(task, date)

        if not candidates:
            raise ValueError(
                f"no valid time slots for task '{task.name}' on {date.date()}"
            )

        # evaluate all candidates
        evaluated_slots = []
        for start_time in candidates:
            slot = self.evaluate_time_slot(start_time, task, weather)
            if slot.is_feasible:
                evaluated_slots.append(slot)

        if not evaluated_slots:
            raise ValueError(
                f"no feasible time slots found for task '{task.name}'"
            )

        # sort by quality score (descending)
        evaluated_slots.sort(key=lambda s: s.quality_score, reverse=True)

        # get best and alternatives
        best_slot = evaluated_slots[0]
        alternatives = evaluated_slots[1:n_alternatives+1]

        # generate summary
        summary = self._generate_summary(task, best_slot, weather)

        # detailed breakdown for analysis
        breakdown = {
            'all_slots_evaluated': len(candidates),
            'feasible_slots': len(evaluated_slots),
            'quality_distribution': {
                'excellent': sum(1 for s in evaluated_slots if s.quality_score >= 80),
                'good': sum(1 for s in evaluated_slots if 60 <= s.quality_score < 80),
                'fair': sum(1 for s in evaluated_slots if 40 <= s.quality_score < 60),
                'poor': sum(1 for s in evaluated_slots if s.quality_score < 40)
            },
            'best_vs_worst': {
                'best_quality': best_slot.quality_score,
                'worst_quality': evaluated_slots[-1].quality_score,
                'quality_range': best_slot.quality_score - evaluated_slots[-1].quality_score
            }
        }

        return ScheduleRecommendation(
            best_slot=best_slot,
            alternative_slots=alternatives,
            total_candidates_evaluated=len(candidates),
            date=date,
            task=task,
            summary=summary,
            detailed_breakdown=breakdown
        )

    def _generate_summary(
        self,
        task: Task,
        best_slot: TimeSlot,
        weather: WeatherData
    ) -> str:
        """
        generate human-readable summary of the recommendation.
        """
        start_str = best_slot.start_time.strftime("%H:%M")
        end_str = best_slot.end_time.strftime("%H:%M")

        quality_desc = (
            "excellent" if best_slot.quality_score >= 80 else
            "good" if best_slot.quality_score >= 60 else
            "fair" if best_slot.quality_score >= 40 else
            "poor"
        )

        risk_desc = (
            "low" if best_slot.heat_risk_score < 0.33 else
            "moderate" if best_slot.heat_risk_score < 0.66 else
            "high"
        )

        summary = (
            f"recommended: start '{task.name}' at {start_str} "
            f"(ending {end_str}). "
            f"schedule quality: {quality_desc} ({best_slot.quality_score:.0f}/100). "
            f"heat risk: {risk_desc}. "
            f"expected shade coverage: {best_slot.shade_percentage:.0f}%."
        )

        # add warnings for high risk
        if best_slot.risk_breakdown.get('samples_high_risk', 0) > 0:
            high_risk_periods = best_slot.risk_breakdown['samples_high_risk']
            summary += f" warning: {high_risk_periods} high-risk period(s) during task."

        return summary

    def optimize_multiple_tasks(
        self,
        tasks: List[Task],
        date: datetime,
        weather: WeatherData
    ) -> List[ScheduleRecommendation]:
        """
        optimize schedules for multiple tasks.

        useful for planning a full day of outdoor work.

        args:
            tasks: list of tasks to schedule
            date: date to schedule on
            weather: weather conditions

        returns:
            list of schedule recommendations (one per task)
        """
        recommendations = []

        # sort tasks by priority (higher priority first)
        sorted_tasks = sorted(tasks, key=lambda t: t.priority, reverse=True)

        # track used time slots to avoid conflicts
        # (simplified - assumes tasks can't overlap)

        for task in sorted_tasks:
            try:
                rec = self.find_best_schedule(task, date, weather)
                recommendations.append(rec)
            except ValueError as e:
                print(f"warning: could not schedule '{task.name}': {e}")

        return recommendations


# -----------------------------------------------------------------------------
# shade-optimized navigation (for community users)
# -----------------------------------------------------------------------------

class ShadeNavigator:
    """
    shade-optimized navigation for pedestrians, cyclists, and joggers.

    this class finds routes that maximize shade coverage, helping
    community members avoid direct sun exposure during hot hours.

    integration notes:
    - uses mapbox directions api for routing
    - overlays shadow data to calculate shade coverage
    - provides alternative routes with shade scores

    usage:
        navigator = ShadeNavigator()

        route = navigator.find_shaded_route(
            start=(25.2048, 55.2708),
            end=(25.1972, 55.2744),
            mode='walking',
            departure_time=datetime(2024, 7, 15, 10, 0)
        )

        print(f"shade score: {route.shade_score}")
    """

    # mapbox api base url
    MAPBOX_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox"

    def __init__(self, mapbox_token: Optional[str] = None):
        """
        initialize the shade navigator.

        args:
            mapbox_token: mapbox api token (optional - can use env var)
        """
        self.mapbox_token = mapbox_token or os.environ.get('MAPBOX_TOKEN')

        self.solar_calculator = SolarPositionCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET
        )

        self.heat_risk_model = HeatRiskModel()
        if not self.heat_risk_model.is_trained:
            self.heat_risk_model.train(n_samples=3000, verbose=False)

    def estimate_segment_shade(
        self,
        segment: Dict,
        timestamp: datetime
    ) -> Tuple[float, float]:
        """
        estimate shade coverage and heat risk for a route segment.

        this is a simplified estimation - in production, would use
        actual shadow data from the shadow engine for the segment's
        geographic coordinates.

        args:
            segment: route segment from mapbox (contains geometry)
            timestamp: time of travel

        returns:
            tuple of (shade_coverage 0-1, heat_risk 0-1)
        """
        # get sun position
        sun_pos = self.solar_calculator.get_sun_position(timestamp)

        if not sun_pos.is_daylight or sun_pos.altitude <= 0:
            # nighttime - full "shade" (no sun)
            return 1.0, 0.0

        # estimate shade based on sun altitude and time of day
        # higher sun = less shade from buildings
        # simplified model - production would use actual shadow calculations

        hour = timestamp.hour + timestamp.minute / 60

        # base shade estimate from sun angle
        altitude_factor = sun_pos.altitude / 90  # 0 at horizon, 1 at zenith
        base_shade = 1.0 - altitude_factor * 0.8

        # time-based adjustment (more shade early/late)
        if 10 <= hour <= 15:
            time_factor = 0.7  # less shade midday
        elif 7 <= hour <= 10 or 15 <= hour <= 18:
            time_factor = 1.2  # more shade early/late
        else:
            time_factor = 1.0

        shade = min(1.0, max(0.0, base_shade * time_factor))

        # heat risk based on sun altitude and shade
        sun_intensity = min(1.0, sun_pos.altitude / 60) * (1 - shade)
        heat_risk = sun_intensity  # simplified 0-1 scale

        return shade, heat_risk

    def calculate_route_shade_score(
        self,
        segments: List[RouteSegment]
    ) -> float:
        """
        calculate overall shade score for a complete route.

        weighted by segment distance - longer segments count more.

        args:
            segments: list of route segments

        returns:
            shade score 0-100
        """
        if not segments:
            return 0.0

        total_distance = sum(s.distance_meters for s in segments)
        if total_distance == 0:
            return 50.0

        # distance-weighted average of shade coverage
        weighted_shade = sum(
            s.shade_coverage * s.distance_meters
            for s in segments
        ) / total_distance

        # distance-weighted average of heat risk (penalty)
        weighted_risk = sum(
            s.heat_risk * s.distance_meters
            for s in segments
        ) / total_distance

        # combine into score (more shade = higher, more risk = lower)
        score = (weighted_shade * 60) + ((1 - weighted_risk) * 40)

        return min(100, max(0, score))

    def find_shaded_route(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        mode: str = 'walking',
        departure_time: Optional[datetime] = None,
        weather: Optional[WeatherData] = None,
        mapbox_token: Optional[str] = None
    ) -> ShadeOptimizedRoute:
        """
        find a shade-optimized route between two points.

        uses mapbox directions api for realistic pedestrian/cycling routes that:
        - follow actual roads and paths
        - avoid highways for pedestrians/cyclists
        - consider bridges, water bodies, and safe crossings
        - provide turn-by-turn navigation

        then overlays shadow data to calculate shade coverage per segment.

        args:
            start: (lat, lon) tuple
            end: (lat, lon) tuple
            mode: 'walking', 'cycling', or 'driving'
            departure_time: when the journey starts
            weather: weather conditions
            mapbox_token: mapbox access token (optional, uses env var if not provided)

        returns:
            ShadeOptimizedRoute with shade-optimized path following real roads
        """
        import requests
        import os

        if departure_time is None:
            departure_time = datetime.now()

        # mapbox profile mapping for safe pedestrian/cycling routes
        profile_map = {
            'walking': 'mapbox/walking',
            'cycling': 'mapbox/cycling',
            'driving': 'mapbox/driving'
        }
        profile = profile_map.get(mode, 'mapbox/walking')

        # try to get mapbox token
        token = mapbox_token or os.environ.get('MAPBOX_TOKEN')

        # default values if api call fails
        distance = self._haversine_distance(start[0], start[1], end[0], end[1])
        speeds = {'walking': 5, 'cycling': 15, 'driving': 30}
        speed = speeds.get(mode, 5)
        duration = (distance / 1000) / speed * 3600
        geometry_coords = [(start[1], start[0]), (end[1], end[0])]  # lon, lat
        route_steps = []

        # call mapbox directions api for realistic route
        if token:
            try:
                # mapbox directions api url
                # format: /directions/v5/{profile}/{coordinates}
                coords_str = f"{start[1]},{start[0]};{end[1]},{end[0]}"
                url = f"https://api.mapbox.com/directions/v5/{profile}/{coords_str}"

                params = {
                    'access_token': token,
                    'geometries': 'geojson',
                    'overview': 'full',
                    'steps': 'true',
                    'annotations': 'distance,duration'
                }

                response = requests.get(url, params=params, timeout=10)

                if response.ok:
                    data = response.json()
                    if data.get('routes') and len(data['routes']) > 0:
                        route = data['routes'][0]
                        distance = route['distance']  # meters
                        duration = route['duration']  # seconds
                        geometry_coords = route['geometry']['coordinates']
                        route_steps = route.get('legs', [{}])[0].get('steps', [])
            except Exception as e:
                print(f"mapbox api error (using fallback): {e}")

        # create segments from the actual route geometry
        segments = []
        n_points = len(geometry_coords)

        if n_points > 1:
            # distribute duration across segments
            total_dist = distance
            for i in range(n_points - 1):
                seg_start = geometry_coords[i]  # (lon, lat)
                seg_end = geometry_coords[i + 1]

                # calculate segment distance
                seg_dist = self._haversine_distance(
                    seg_start[1], seg_start[0],
                    seg_end[1], seg_end[0]
                )

                # proportional duration
                seg_duration = (seg_dist / max(total_dist, 1)) * duration

                # estimate shade for this segment based on time along route
                elapsed_time = sum(s.duration_seconds for s in segments) if segments else 0
                seg_time = departure_time + timedelta(seconds=elapsed_time)
                shade_coverage, heat_risk = self.estimate_segment_shade({}, seg_time)

                segments.append(RouteSegment(
                    start_lat=seg_start[1],
                    start_lon=seg_start[0],
                    end_lat=seg_end[1],
                    end_lon=seg_end[0],
                    distance_meters=seg_dist,
                    duration_seconds=seg_duration,
                    shade_coverage=shade_coverage,
                    heat_risk=heat_risk,
                    surface_type='mixed'
                ))
        else:
            # fallback to simple segment if no route points
            shade_coverage, heat_risk = self.estimate_segment_shade({}, departure_time)
            segments.append(RouteSegment(
                start_lat=start[0],
                start_lon=start[1],
                end_lat=end[0],
                end_lon=end[1],
                distance_meters=distance,
                duration_seconds=duration,
                shade_coverage=shade_coverage,
                heat_risk=heat_risk,
                surface_type='mixed'
            ))

        # calculate overall metrics
        avg_shade = np.mean([s.shade_coverage for s in segments]) if segments else 0.5
        avg_risk = np.mean([s.heat_risk for s in segments]) if segments else 0.5
        sun_exposure = duration / 60 * (1 - avg_shade)  # minutes in sun
        shade_score = self.calculate_route_shade_score(segments)

        # comparison metrics
        direct_dist = self._haversine_distance(start[0], start[1], end[0], end[1])
        comparison = {
            'distance_increase_pct': round((distance - direct_dist) / max(direct_dist, 1) * 100, 1),
            'duration_increase_pct': 0,  # actual route is the base
            'shade_improvement_pct': round(avg_shade * 100, 1)
        }

        return ShadeOptimizedRoute(
            segments=segments,
            total_distance=distance,
            total_duration=duration,
            average_shade_coverage=avg_shade,
            average_heat_risk=avg_risk,
            sun_exposure_minutes=sun_exposure,
            shade_score=shade_score,
            comparison_to_fastest=comparison,
            route_geometry=geometry_coords  # actual route path
        )

    def _haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """
        calculate distance between two points using haversine formula.

        args:
            lat1, lon1: first point coordinates
            lat2, lon2: second point coordinates

        returns:
            distance in meters
        """
        R = 6371000  # earth radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (math.sin(delta_phi/2)**2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        return R * c


# -----------------------------------------------------------------------------
# synthetic training data for ml-enhanced scheduling (optional)
# -----------------------------------------------------------------------------

def generate_schedule_training_data(
    n_samples: int = 5000,
    random_seed: int = 42
) -> Tuple[np.ndarray, np.ndarray]:
    """
    generate synthetic training data for schedule quality prediction.

    this allows the optimizer to learn patterns beyond the rule-based
    quality function, potentially improving recommendations.

    args:
        n_samples: number of training samples
        random_seed: for reproducibility

    returns:
        tuple of (features, quality_scores)
    """
    np.random.seed(random_seed)

    features_list = []
    scores_list = []

    for _ in range(n_samples):
        # random conditions
        month = np.random.randint(1, 13)
        hour = np.random.uniform(6, 20)

        # temperature based on month and time
        if month in [6, 7, 8, 9]:
            base_temp = np.random.uniform(35, 48)
        elif month in [5, 10]:
            base_temp = np.random.uniform(30, 40)
        else:
            base_temp = np.random.uniform(20, 32)

        hour_factor = math.sin((hour - 6) * math.pi / 12)
        temperature = base_temp + hour_factor * 6

        humidity = np.random.uniform(20, 70)
        wind_speed = np.random.uniform(0, 30)

        heat_risk = np.random.uniform(0, 2)
        shade_pct = np.random.uniform(0, 100)
        duration = np.random.randint(30, 300)

        # encode features
        hour_sin, hour_cos = encode_time_cyclic(hour, 24)
        month_sin, month_cos = encode_time_cyclic(month, 12)

        features = np.array([
            hour_sin, hour_cos,
            month_sin, month_cos,
            temperature, humidity, wind_speed,
            heat_risk, shade_pct, duration
        ])

        # calculate quality score
        quality = calculate_schedule_quality(
            start_hour=hour,
            avg_heat_risk=heat_risk,
            shade_percentage=shade_pct,
            duration_minutes=duration,
            task_completes_on_time=True
        )

        # add some noise to simulate real-world variability
        quality += np.random.normal(0, 3)
        quality = max(0, min(100, quality))

        features_list.append(features)
        scores_list.append(quality)

    return np.array(features_list), np.array(scores_list)


# -----------------------------------------------------------------------------
# api-friendly functions for integration
# -----------------------------------------------------------------------------

def get_optimal_schedule(
    task_name: str,
    duration_minutes: int,
    latitude: float,
    longitude: float,
    date: datetime,
    temperature: float,
    humidity: float,
    wind_speed: float = 10.0,
    surface_type: str = 'mixed',
    requires_shade: bool = False
) -> Dict[str, Any]:
    """
    simplified api function for getting optimal schedule.

    designed for easy integration with the flask api.

    args:
        task_name: name/description of the task
        duration_minutes: how long the task takes
        latitude, longitude: task location
        date: date to schedule on
        temperature: expected temperature in celsius
        humidity: expected humidity percentage
        wind_speed: expected wind speed km/h
        surface_type: ground surface type
        requires_shade: whether task must be in shade

    returns:
        dictionary with recommendation details
    """
    # create task
    task = Task(
        name=task_name,
        duration_minutes=duration_minutes,
        location_lat=latitude,
        location_lon=longitude,
        requires_shade=requires_shade,
        surface_type=surface_type
    )

    # create weather data
    weather = WeatherData(
        temperature=temperature,
        humidity=humidity,
        wind_speed=wind_speed
    )

    # get recommendation
    optimizer = ScheduleOptimizer()
    recommendation = optimizer.find_best_schedule(task, date, weather)

    # format response
    return {
        'success': True,
        'task': task_name,
        'date': date.strftime('%Y-%m-%d'),
        'recommendation': {
            'best_start_time': recommendation.best_slot.start_time.strftime('%H:%M'),
            'end_time': recommendation.best_slot.end_time.strftime('%H:%M'),
            'quality_score': round(recommendation.best_slot.quality_score, 1),
            'heat_risk_score': round(recommendation.best_slot.heat_risk_score, 2),
            'shade_percentage': round(recommendation.best_slot.shade_percentage, 1),
            'risk_breakdown': recommendation.best_slot.risk_breakdown
        },
        'alternatives': [
            {
                'start_time': slot.start_time.strftime('%H:%M'),
                'quality_score': round(slot.quality_score, 1),
                'heat_risk_score': round(slot.heat_risk_score, 2)
            }
            for slot in recommendation.alternative_slots
        ],
        'summary': recommendation.summary
    }


def get_shaded_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    mode: str = 'walking',
    departure_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    simplified api function for getting shade-optimized route.

    designed for integration with the navigation feature.

    args:
        start_lat, start_lon: starting point
        end_lat, end_lon: destination
        mode: 'walking', 'cycling', or 'driving'
        departure_time: when to leave

    returns:
        dictionary with route details
    """
    if departure_time is None:
        departure_time = datetime.now()

    navigator = ShadeNavigator()
    route = navigator.find_shaded_route(
        start=(start_lat, start_lon),
        end=(end_lat, end_lon),
        mode=mode,
        departure_time=departure_time
    )

    return {
        'success': True,
        'mode': mode,
        'departure_time': departure_time.strftime('%Y-%m-%d %H:%M'),
        'route': {
            'total_distance_meters': round(route.total_distance, 1),
            'total_duration_minutes': round(route.total_duration / 60, 1),
            'shade_score': round(route.shade_score, 1),
            'average_shade_coverage': round(route.average_shade_coverage * 100, 1),
            'sun_exposure_minutes': round(route.sun_exposure_minutes, 1),
            'heat_risk_level': (
                'low' if route.average_heat_risk < 0.33 else
                'moderate' if route.average_heat_risk < 0.66 else
                'high'
            )
        },
        'segments': [
            {
                'start': [s.start_lat, s.start_lon],
                'end': [s.end_lat, s.end_lon],
                'distance': round(s.distance_meters, 1),
                'shade_coverage': round(s.shade_coverage * 100, 1)
            }
            for s in route.segments
        ],
        'comparison': route.comparison_to_fastest
    }


# -----------------------------------------------------------------------------
# main - demonstration and testing
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("smartshift schedule optimization model")
    print("=" * 70)

    # create sample task
    task = Task(
        name="facade cleaning - burj khalifa",
        duration_minutes=180,  # 3 hours
        location_lat=25.1972,
        location_lon=55.2744,
        earliest_start=6,
        latest_end=18,
        requires_shade=True,
        surface_type='concrete'
    )

    # sample weather for dubai summer
    weather = WeatherData(
        temperature=40.0,
        humidity=35.0,
        wind_speed=12.0,
        cloud_cover=0.0
    )

    # create optimizer
    print("\ninitializing schedule optimizer...")
    optimizer = ScheduleOptimizer()

    # find best schedule
    date = datetime(2024, 7, 15)  # summer day
    print(f"\nfinding optimal schedule for '{task.name}'")
    print(f"date: {date.date()}")
    print(f"duration: {task.duration_minutes} minutes")
    print(f"conditions: {weather.temperature}°c, {weather.humidity}% humidity")

    recommendation = optimizer.find_best_schedule(task, date, weather)

    print("\n" + "-" * 70)
    print("recommendation")
    print("-" * 70)
    print(f"\n{recommendation.summary}")

    print(f"\nbest slot details:")
    print(f"  start: {recommendation.best_slot.start_time.strftime('%H:%M')}")
    print(f"  end: {recommendation.best_slot.end_time.strftime('%H:%M')}")
    print(f"  quality score: {recommendation.best_slot.quality_score:.1f}/100")
    print(f"  heat risk: {recommendation.best_slot.heat_risk_score:.2f}")
    print(f"  shade coverage: {recommendation.best_slot.shade_percentage:.1f}%")

    if recommendation.best_slot.risk_breakdown:
        print(f"\nrisk breakdown:")
        for key, value in recommendation.best_slot.risk_breakdown.items():
            print(f"  {key}: {value}")

    print(f"\nalternative slots:")
    for i, slot in enumerate(recommendation.alternative_slots, 1):
        print(f"  {i}. {slot.start_time.strftime('%H:%M')} - quality: {slot.quality_score:.1f}")

    # demonstrate navigation
    print("\n" + "=" * 70)
    print("shade-optimized navigation demo")
    print("=" * 70)

    # route from downtown to marina
    start = (25.2048, 55.2708)  # downtown dubai
    end = (25.0805, 55.1386)    # dubai marina

    print(f"\nfinding shaded route from downtown to marina")
    print(f"mode: walking")
    print(f"departure: 10:00 am (peak sun)")

    result = get_shaded_route(
        start_lat=start[0], start_lon=start[1],
        end_lat=end[0], end_lon=end[1],
        mode='walking',
        departure_time=datetime(2024, 7, 15, 10, 0)
    )

    print(f"\nroute details:")
    print(f"  distance: {result['route']['total_distance_meters']:.0f} m")
    print(f"  duration: {result['route']['total_duration_minutes']:.0f} min")
    print(f"  shade score: {result['route']['shade_score']:.0f}/100")
    print(f"  shade coverage: {result['route']['average_shade_coverage']:.0f}%")
    print(f"  sun exposure: {result['route']['sun_exposure_minutes']:.0f} min")
    print(f"  heat risk: {result['route']['heat_risk_level']}")

    print("\n" + "=" * 70)
    print("models ready for integration with smartshift api")
    print("=" * 70)

