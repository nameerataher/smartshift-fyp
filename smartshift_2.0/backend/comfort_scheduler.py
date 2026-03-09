"""
comfort_scheduler.py

deterministic scheduling engine using sliding window optimization
finds optimal time slots based on unified comfort score

Supports three scheduling modes:
1. SHADOW_ONLY: Prioritize shadow exposure only (no heat risk considerations)
2. AREA_MODE: Polygon selection for batch tasks (e.g., municipality cleaning)
3. BUILDING_FACE: Select building face (N/E/S/W) for facade work
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Literal
from enum import Enum
import numpy as np

from core_model import (
    SpaceTimeCell, SpaceTimeDataset, WorkZone, TimeWindow,
    ComfortWeights, HeatRiskClass, compute_comfort_score
)


class SchedulingMode(Enum):
    """Scheduling optimization modes."""
    SHADOW_ONLY = "shadow_only"       # Only consider shadow exposure
    COMFORT = "comfort"                # Combined shadow + heat risk (default)
    AREA = "area"                      # Polygon area mode for batch tasks
    BUILDING_FACE = "building_face"   # Building face orientation mode


class BuildingFace(Enum):
    """Building face orientations."""
    NORTH = "N"
    EAST = "E"  
    SOUTH = "S"
    WEST = "W"
    
    @property
    def azimuth(self) -> float:
        """Get azimuth angle for each face (degrees from north)."""
        return {
            BuildingFace.NORTH: 0,
            BuildingFace.EAST: 90,
            BuildingFace.SOUTH: 180,
            BuildingFace.WEST: 270
        }[self]
    
    @classmethod
    def from_string(cls, s: str) -> 'BuildingFace':
        """Parse face from string (N, E, S, W)."""
        mapping = {'N': cls.NORTH, 'E': cls.EAST, 'S': cls.SOUTH, 'W': cls.WEST,
                   'NORTH': cls.NORTH, 'EAST': cls.EAST, 'SOUTH': cls.SOUTH, 'WEST': cls.WEST}
        return mapping.get(s.upper(), cls.NORTH)


@dataclass
class AreaPolygon:
    """Represents a polygon area for area mode scheduling."""
    points: List[Tuple[float, float]]  # List of (lat, lon) points
    name: str = ""
    
    @property
    def centroid(self) -> Tuple[float, float]:
        """Calculate centroid of polygon."""
        if not self.points:
            return (0.0, 0.0)
        avg_lat = sum(p[0] for p in self.points) / len(self.points)
        avg_lon = sum(p[1] for p in self.points) / len(self.points)
        return (avg_lat, avg_lon)
    
    @property
    def bounds(self) -> Dict[str, float]:
        """Get bounding box of polygon."""
        if not self.points:
            return {"min_lat": 0, "max_lat": 0, "min_lon": 0, "max_lon": 0}
        lats = [p[0] for p in self.points]
        lons = [p[1] for p in self.points]
        return {
            "min_lat": min(lats), "max_lat": max(lats),
            "min_lon": min(lons), "max_lon": max(lons)
        }
    
    def sample_points(self, n: int = 5) -> List[Tuple[float, float]]:
        """Sample n points within polygon for shadow analysis."""
        bounds = self.bounds
        centroid = self.centroid
        
        # Return corners + centroid
        return [
            centroid,
            (bounds["min_lat"], bounds["min_lon"]),
            (bounds["min_lat"], bounds["max_lon"]),
            (bounds["max_lat"], bounds["min_lon"]),
            (bounds["max_lat"], bounds["max_lon"]),
        ][:n]


@dataclass
class ScheduleCandidate:
    """represents a candidate time window with its evaluation"""
    window: TimeWindow
    cells: List[SpaceTimeCell]
    
    # aggregate metrics
    avg_comfort_score: float
    min_comfort_score: float
    avg_shadow_ratio: float
    avg_heat_risk_score: float
    
    # risk distribution
    low_risk_minutes: int = 0
    medium_risk_minutes: int = 0
    high_risk_minutes: int = 0
    
    # ranking score (for comparison)
    ranking_score: float = 0.0
    
    # mode-specific metadata
    mode: str = "comfort"
    building_face: Optional[str] = None
    area_coverage: Optional[float] = None
    
    def __repr__(self):
        return (f"ScheduleCandidate({self.window}, "
                f"comfort={self.avg_comfort_score:.2f}, "
                f"shadow={self.avg_shadow_ratio:.0%})")


@dataclass
class ScheduleRecommendation:
    """final scheduling recommendation with alternatives"""
    task_name: str
    work_zone: WorkZone
    
    # best recommendation
    best_candidate: ScheduleCandidate
    
    # alternatives (sorted by score)
    alternative_candidates: List[ScheduleCandidate] = field(default_factory=list)
    
    # evaluation metadata
    total_candidates_evaluated: int = 0
    evaluation_date: Optional[datetime] = None
    
    # explanation
    recommendation_reason: str = ""
    
    def to_dict(self) -> Dict:
        """convert to api-friendly format"""
        return {
            "task_name": self.task_name,
            "work_zone": {
                "id": self.work_zone.zone_id,
                "name": self.work_zone.get_oriented_name(),
                "location": {"lat": self.work_zone.lat, "lon": self.work_zone.lon}
            },
            "best_schedule": {
                "start_time": self.best_candidate.window.start.isoformat(),
                "end_time": self.best_candidate.window.end.isoformat(),
                "comfort_score": float(self.best_candidate.avg_comfort_score),
                "shadow_percentage": float(self.best_candidate.avg_shadow_ratio * 100),
                "heat_risk_score": float(self.best_candidate.avg_heat_risk_score),
                "risk_distribution": {
                    "low_minutes": self.best_candidate.low_risk_minutes,
                    "medium_minutes": self.best_candidate.medium_risk_minutes,
                    "high_minutes": self.best_candidate.high_risk_minutes
                }
            },
            "alternatives": [
                {
                    "start_time": alt.window.start.isoformat(),
                    "end_time": alt.window.end.isoformat(),
                    "comfort_score": float(alt.avg_comfort_score),
                    "shadow_percentage": float(alt.avg_shadow_ratio * 100),
                    "heat_risk_score": float(alt.avg_heat_risk_score)
                }
                for alt in self.alternative_candidates
            ],
            "recommendation_reason": self.recommendation_reason,
            "total_evaluated": self.total_candidates_evaluated
        }


class ComfortScheduler:
    """
    deterministic scheduling engine using sliding window optimization
    
    algorithm:
    1. discretize the day into intervals (e.g. 10 min)
    2. for each interval, compute comfort_score (or shadow_ratio in shadow_only mode)
    3. slide a window of task duration
    4. pick the window with maximum average score
    
    Modes:
    - SHADOW_ONLY: Only consider shadow exposure (no heat risk)
    - COMFORT: Combined shadow + heat risk (default)
    - AREA: Polygon area mode - sample multiple points
    - BUILDING_FACE: Building face orientation mode (N/E/S/W)
    """
    
    def __init__(
        self,
        temporal_resolution_minutes: int = 10,
        comfort_weights: Optional[ComfortWeights] = None,
        mode: SchedulingMode = SchedulingMode.SHADOW_ONLY
    ):
        """
        initialize scheduler
        
        args:
            temporal_resolution_minutes: time discretization (5, 10, or 15 min)
            comfort_weights: optional custom weights for comfort calculation
            mode: scheduling mode (SHADOW_ONLY, COMFORT, AREA, BUILDING_FACE)
        """
        self.temporal_resolution = temporal_resolution_minutes
        self.comfort_weights = comfort_weights or ComfortWeights()
        self.mode = mode
        
        # In shadow-only mode, set weights to prioritize shadow completely
        if mode == SchedulingMode.SHADOW_ONLY:
            self.comfort_weights = ComfortWeights(shadow_weight=1.0, heat_weight=0.0)
    
    def find_optimal_schedule(
        self,
        task_name: str,
        work_zone: WorkZone,
        task_duration_minutes: int,
        date: datetime,
        start_hour: int = 9,
        end_hour: int = 17,
        dataset: Optional[SpaceTimeDataset] = None,
        recommendation_count: int = 5,
        rank_by: str = "shade",
        building_face: Optional[str] = None,
        area_polygon: Optional[AreaPolygon] = None
    ) -> ScheduleRecommendation:
        """
        find the optimal time window for a task
        
        args:
            task_name: name of the task
            work_zone: location and zone info
            task_duration_minutes: how long the task takes
            date: which day
            start_hour: earliest start time (default 9am)
            end_hour: latest end time (default 5pm)
            dataset: pre-computed space-time cells (if None, will generate)
            rank_by: "shade" or "comfort"
            building_face: optional face direction (N/E/S/W) for building face mode
            area_polygon: optional polygon for area mode
        
        returns:
            ScheduleRecommendation with best time and alternatives
        """
        # Determine effective mode based on parameters
        effective_mode = self.mode
        if building_face:
            effective_mode = SchedulingMode.BUILDING_FACE
        elif area_polygon:
            effective_mode = SchedulingMode.AREA
        
        # if no dataset provided, generate it with mode-specific logic
        if dataset is None:
            if effective_mode == SchedulingMode.BUILDING_FACE and building_face:
                dataset = self._generate_dataset_for_building_face(
                    work_zone, date, start_hour, end_hour,
                    BuildingFace.from_string(building_face)
                )
            elif effective_mode == SchedulingMode.AREA and area_polygon:
                dataset = self._generate_dataset_for_area(
                    area_polygon, date, start_hour, end_hour
                )
            else:
                dataset = self._generate_dataset_for_zone(
                    work_zone, date, start_hour, end_hour
                )
        
        # discretize time into intervals
        time_intervals = self._discretize_time_range(
            date, start_hour, end_hour, self.temporal_resolution
        )
        
        # evaluate all possible windows
        candidates = []
        
        for i in range(len(time_intervals)):
            # check if window fits within working hours
            window_start = time_intervals[i]
            window_end = window_start + timedelta(minutes=task_duration_minutes)
            
            if window_end.hour > end_hour or (window_end.hour == end_hour and window_end.minute > 0):
                break  # window extends beyond end hour
            
            # get cells in this window
            cells_in_window = dataset.get_cells_in_time_window(
                window_start,
                window_end,
                lat=work_zone.lat,
                lon=work_zone.lon,
                tolerance_meters=work_zone.radius if work_zone.radius else 50.0
            )
            
            if not cells_in_window:
                continue  # no data for this window
            
            # evaluate this candidate window
            candidate = self._evaluate_window(
                TimeWindow(window_start, window_end),
                cells_in_window,
                mode=effective_mode.value,
                building_face=building_face
            )
            
            candidates.append(candidate)
        
        if not candidates:
            raise ValueError(
                f"no feasible schedule found for {task_name} "
                f"on {date.date()} between {start_hour}:00-{end_hour}:00"
            )
        
        # In shadow-only mode, always sort by shadow ratio first
        if self.mode == SchedulingMode.SHADOW_ONLY or rank_by == "shade":
            candidates.sort(key=lambda c: (c.avg_shadow_ratio, c.avg_comfort_score), reverse=True)
        else:
            candidates.sort(key=lambda c: (c.avg_comfort_score, c.avg_shadow_ratio), reverse=True)
        
        best_candidate = candidates[0]
        total_recs = max(1, int(recommendation_count))
        alternatives = candidates[1:total_recs]
        
        # generate recommendation reason with mode context
        reason = self._generate_recommendation_reason(best_candidate, work_zone, effective_mode, building_face)
        
        return ScheduleRecommendation(
            task_name=task_name,
            work_zone=work_zone,
            best_candidate=best_candidate,
            alternative_candidates=alternatives,
            total_candidates_evaluated=len(candidates),
            evaluation_date=date,
            recommendation_reason=reason
        )
    
    def find_optimal_for_area(
        self,
        task_name: str,
        polygon_points: List[Tuple[float, float]],
        task_duration_minutes: int,
        date: datetime,
        start_hour: int = 9,
        end_hour: int = 17,
        recommendation_count: int = 5
    ) -> ScheduleRecommendation:
        """
        Find optimal schedule for an area (polygon).
        Used for batch tasks like municipality cleaning.
        
        args:
            task_name: name of the task
            polygon_points: list of (lat, lon) points defining the area
            task_duration_minutes: how long the task takes
            date: which day
            start_hour: earliest start time
            end_hour: latest end time
        """
        area = AreaPolygon(points=polygon_points, name=task_name)
        centroid = area.centroid
        
        work_zone = WorkZone(
            zone_id=f"area_{task_name}_{date.strftime('%Y%m%d')}",
            name=task_name,
            lat=centroid[0],
            lon=centroid[1],
            radius=100.0,
            is_facade=False
        )
        
        return self.find_optimal_schedule(
            task_name=task_name,
            work_zone=work_zone,
            task_duration_minutes=task_duration_minutes,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count,
            rank_by="shade",
            area_polygon=area
        )
    
    def find_optimal_for_building_face(
        self,
        task_name: str,
        building_lat: float,
        building_lon: float,
        face: str,
        task_duration_minutes: int,
        date: datetime,
        start_hour: int = 9,
        end_hour: int = 17,
        recommendation_count: int = 5
    ) -> ScheduleRecommendation:
        """
        Find optimal schedule for working on a building face (N/E/S/W).
        Computes shadow exposure on that specific face at different times.
        
        args:
            task_name: name of the task
            building_lat: building latitude
            building_lon: building longitude
            face: face direction (N, E, S, W)
            task_duration_minutes: how long the task takes
            date: which day
            start_hour: earliest start time
            end_hour: latest end time
        """
        face_enum = BuildingFace.from_string(face)
        
        work_zone = WorkZone(
            zone_id=f"face_{face}_{date.strftime('%Y%m%d')}",
            name=f"{task_name} - {face} Face",
            lat=building_lat,
            lon=building_lon,
            radius=20.0,
            is_facade=True,
            orientation=face_enum.azimuth
        )
        
        return self.find_optimal_schedule(
            task_name=task_name,
            work_zone=work_zone,
            task_duration_minutes=task_duration_minutes,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count,
            rank_by="shade",
            building_face=face
        )
    
    def _discretize_time_range(
        self,
        date: datetime,
        start_hour: int,
        end_hour: int,
        interval_minutes: int
    ) -> List[datetime]:
        """create list of discrete time points"""
        intervals = []
        current = datetime(date.year, date.month, date.day, start_hour, 0, 0)
        end_time = datetime(date.year, date.month, date.day, end_hour, 0, 0)
        
        while current <= end_time:
            intervals.append(current)
            current += timedelta(minutes=interval_minutes)
        
        return intervals
    
    def _evaluate_window(
        self,
        window: TimeWindow,
        cells: List[SpaceTimeCell],
        mode: str = "comfort",
        building_face: Optional[str] = None
    ) -> ScheduleCandidate:
        """
        evaluate a time window based on its cells
        
        computes aggregate metrics:
        - average comfort score (or shadow ratio in shadow_only mode)
        - minimum comfort score (worst moment)
        - shadow coverage
        - heat risk distribution
        """
        if not cells:
            return ScheduleCandidate(
                window=window,
                cells=[],
                avg_comfort_score=0.0,
                min_comfort_score=0.0,
                avg_shadow_ratio=0.0,
                avg_heat_risk_score=1.0,
                mode=mode,
                building_face=building_face
            )
        
        shadow_ratios = [cell.shadow_ratio for cell in cells]
        heat_risk_scores = [cell.heat_risk_score for cell in cells]
        
        avg_shadow = np.mean(shadow_ratios)
        avg_heat = np.mean(heat_risk_scores)
        
        # In shadow-only mode, comfort score equals shadow ratio
        if self.mode == SchedulingMode.SHADOW_ONLY or mode == "shadow_only":
            comfort_scores = shadow_ratios
        else:
            comfort_scores = [cell.comfort_score for cell in cells]
        
        avg_comfort = np.mean(comfort_scores)
        min_comfort = np.min(comfort_scores)
        
        # count risk distribution
        low_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.LOW)
        med_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.MEDIUM)
        high_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.HIGH)
        
        # ranking score based on mode
        if self.mode == SchedulingMode.SHADOW_ONLY:
            ranking_score = avg_shadow  # Pure shadow-based ranking
        else:
            ranking_score = avg_comfort
        
        return ScheduleCandidate(
            window=window,
            cells=cells,
            avg_comfort_score=avg_comfort,
            min_comfort_score=min_comfort,
            avg_shadow_ratio=avg_shadow,
            avg_heat_risk_score=avg_heat,
            low_risk_minutes=low_count * self.temporal_resolution,
            medium_risk_minutes=med_count * self.temporal_resolution,
            high_risk_minutes=high_count * self.temporal_resolution,
            ranking_score=ranking_score,
            mode=mode,
            building_face=building_face
        )
    
    def _generate_recommendation_reason(
        self,
        candidate: ScheduleCandidate,
        zone: WorkZone,
        mode: SchedulingMode = SchedulingMode.SHADOW_ONLY,
        building_face: Optional[str] = None
    ) -> str:
        """generate human-readable explanation"""
        start_str = candidate.window.start.strftime("%H:%M")
        end_str = candidate.window.end.strftime("%H:%M")
        
        shadow_pct = candidate.avg_shadow_ratio * 100
        
        # Mode-specific reasoning
        if mode == SchedulingMode.SHADOW_ONLY:
            primary_reason = f"{shadow_pct:.0f}% shadow coverage"
            mode_context = "based on maximum shadow exposure"
        elif mode == SchedulingMode.BUILDING_FACE and building_face:
            face_desc = {"N": "North", "E": "East", "S": "South", "W": "West"}.get(building_face.upper(), building_face)
            primary_reason = f"{shadow_pct:.0f}% shade on {face_desc} face"
            mode_context = f"optimal for {face_desc}-facing facade work"
        elif mode == SchedulingMode.AREA:
            primary_reason = f"{shadow_pct:.0f}% average shadow coverage across area"
            mode_context = "best time for area-wide outdoor work"
        else:
            comfort_pct = candidate.avg_comfort_score * 100
            if candidate.avg_shadow_ratio > 0.6:
                primary_reason = f"{shadow_pct:.0f}% shaded"
            elif candidate.avg_heat_risk_score < 0.3:
                primary_reason = "low heat risk"
            else:
                primary_reason = f"{comfort_pct:.0f}% comfort score"
            mode_context = "combined shadow and heat analysis"
        
        zone_name = zone.get_oriented_name() if hasattr(zone, 'get_oriented_name') else zone.name
        
        return (f"Recommended {start_str}–{end_str} at {zone_name}. "
                f"{primary_reason} ({mode_context}).")
    
    def _generate_dataset_for_building_face(
        self,
        work_zone: WorkZone,
        date: datetime,
        start_hour: int,
        end_hour: int,
        face: BuildingFace
    ) -> SpaceTimeDataset:
        """
        Generate space-time cells for a building face.
        Calculates shadow on the face based on sun position relative to face orientation.
        
        A face is in shadow when the sun is behind it (angle > 90 degrees from face normal).
        """
        from solar_position import SolarPositionCalculator
        
        solar_calc = SolarPositionCalculator(
            latitude=work_zone.lat,
            longitude=work_zone.lon,
            timezone_offset=4.0
        )
        
        dataset = SpaceTimeDataset(
            temporal_resolution_minutes=self.temporal_resolution
        )
        
        time_intervals = self._discretize_time_range(
            date, start_hour, end_hour, self.temporal_resolution
        )
        
        face_azimuth = face.azimuth
        
        for timestamp in time_intervals:
            sun_pos = solar_calc.get_sun_position(timestamp)
            
            if sun_pos.altitude <= 0:
                shadow_ratio = 1.0  # Night = full shade
            else:
                # Calculate angle between sun and face normal
                # Face normal points outward from building
                sun_azimuth = sun_pos.azimuth
                
                # Angle difference between sun direction and face normal
                angle_diff = abs(((sun_azimuth - face_azimuth + 180) % 360) - 180)
                
                if angle_diff > 90:
                    # Sun is behind the face - face is in shadow
                    shadow_ratio = 0.85 + 0.15 * (angle_diff - 90) / 90
                elif angle_diff > 60:
                    # Sun at oblique angle - partial shadow
                    shadow_ratio = 0.4 + 0.45 * (angle_diff - 60) / 30
                else:
                    # Sun facing the facade - minimal shadow
                    # Still some shadow from adjacent structures
                    shadow_ratio = 0.15 + 0.25 * (angle_diff / 60)
                
                # Adjust for sun altitude (lower sun = more shadow from other buildings)
                altitude_factor = 1 - (sun_pos.altitude / 90) * 0.3
                shadow_ratio = min(1.0, shadow_ratio * altitude_factor)
            
            # In shadow-only mode, heat risk is not considered
            heat_risk_score = 0.0
            heat_risk_class = HeatRiskClass.LOW
            
            comfort = shadow_ratio  # Comfort equals shadow in shadow-only mode
            
            cell = SpaceTimeCell(
                lat=work_zone.lat,
                lon=work_zone.lon,
                timestamp=timestamp,
                shadow_ratio=shadow_ratio,
                heat_risk_class=heat_risk_class,
                heat_risk_score=heat_risk_score,
                comfort_score=comfort,
                zone_id=work_zone.zone_id
            )
            
            dataset.add_cell(cell)
        
        return dataset
    
    def _generate_dataset_for_area(
        self,
        area: AreaPolygon,
        date: datetime,
        start_hour: int,
        end_hour: int
    ) -> SpaceTimeDataset:
        """
        Generate space-time cells for a polygon area.
        Samples multiple points within the area to get average shadow coverage.
        """
        from solar_position import SolarPositionCalculator
        
        centroid = area.centroid
        sample_points = area.sample_points(5)
        
        solar_calc = SolarPositionCalculator(
            latitude=centroid[0],
            longitude=centroid[1],
            timezone_offset=4.0
        )
        
        dataset = SpaceTimeDataset(
            temporal_resolution_minutes=self.temporal_resolution
        )
        
        time_intervals = self._discretize_time_range(
            date, start_hour, end_hour, self.temporal_resolution
        )
        
        for timestamp in time_intervals:
            sun_pos = solar_calc.get_sun_position(timestamp)
            
            # Calculate shadow for each sample point and average
            shadow_ratios = []
            
            for lat, lon in sample_points:
                if sun_pos.altitude <= 0:
                    shadow_ratio = 1.0
                else:
                    # Open area shadow depends mainly on sun altitude
                    # Higher sun = less natural shadow
                    base_shadow = 0.2 + 0.5 * (1 - sun_pos.altitude / 90)
                    
                    # Add some variation based on position in area
                    position_factor = abs(hash(f"{lat}{lon}") % 20) / 100
                    shadow_ratio = min(1.0, base_shadow + position_factor)
                
                shadow_ratios.append(shadow_ratio)
            
            avg_shadow = np.mean(shadow_ratios)
            
            # In shadow-only mode, heat risk is not considered
            heat_risk_score = 0.0
            heat_risk_class = HeatRiskClass.LOW
            
            comfort = avg_shadow
            
            cell = SpaceTimeCell(
                lat=centroid[0],
                lon=centroid[1],
                timestamp=timestamp,
                shadow_ratio=avg_shadow,
                heat_risk_class=heat_risk_class,
                heat_risk_score=heat_risk_score,
                comfort_score=comfort,
                zone_id=f"area_{area.name}"
            )
            
            dataset.add_cell(cell)
        
        return dataset
    
    def _generate_dataset_for_zone(
        self,
        work_zone: WorkZone,
        date: datetime,
        start_hour: int,
        end_hour: int
    ) -> SpaceTimeDataset:
        """
        Generate space-time cells for a work zone.
        
        In shadow-only mode, only calculates shadow coverage based on sun position.
        Heat risk is not considered.
        """
        from solar_position import SolarPositionCalculator
        
        solar_calc = SolarPositionCalculator(
            latitude=work_zone.lat,
            longitude=work_zone.lon,
            timezone_offset=4.0
        )
        
        dataset = SpaceTimeDataset(
            temporal_resolution_minutes=self.temporal_resolution
        )
        
        time_intervals = self._discretize_time_range(
            date, start_hour, end_hour, self.temporal_resolution
        )
        
        for timestamp in time_intervals:
            sun_pos = solar_calc.get_sun_position(timestamp)
            
            # Calculate shadow based on sun altitude
            if sun_pos.altitude <= 0:
                shadow_ratio = 1.0  # Night = full shade
            else:
                # Higher sun = less shadow from buildings
                # Lower altitude = more shadow
                shadow_ratio = max(0.1, 1.0 - (sun_pos.altitude / 90) * 0.9)
                
                # Adjust for facade orientation if specified
                if work_zone.is_facade and work_zone.orientation is not None:
                    sun_azimuth = sun_pos.azimuth
                    facade_azimuth = work_zone.orientation
                    angle_diff = abs(((sun_azimuth - facade_azimuth + 180) % 360) - 180)
                    
                    if angle_diff > 90:
                        # Sun is behind the facade - more shade
                        shadow_ratio = min(1.0, shadow_ratio + 0.35)
                    elif angle_diff > 60:
                        # Sun at oblique angle
                        shadow_ratio = min(1.0, shadow_ratio + 0.15)
            
            # In shadow-only mode, heat risk is not considered
            heat_risk_score = 0.0
            heat_risk_class = HeatRiskClass.LOW
            
            # Comfort equals shadow in shadow-only mode
            comfort = shadow_ratio
            
            cell = SpaceTimeCell(
                lat=work_zone.lat,
                lon=work_zone.lon,
                timestamp=timestamp,
                shadow_ratio=shadow_ratio,
                heat_risk_class=heat_risk_class,
                heat_risk_score=heat_risk_score,
                comfort_score=comfort,
                zone_id=work_zone.zone_id
            )
            
            dataset.add_cell(cell)
        
        return dataset
    
    def update_weights_from_feedback(
        self,
        user_id: str,
        accepted: bool,
        shadow_preference: float,
        heat_preference: float
    ):
        """
        adaptive optimization: adjust weights based on user feedback
        
        this implements lightweight preference learning
        without needing deep RL
        
        args:
            user_id: user identifier
            accepted: whether user accepted the recommendation
            shadow_preference: user's stated shadow importance (0-1)
            heat_preference: user's stated heat avoidance importance (0-1)
        """
        if accepted:
            # if user accepted, slightly adjust towards their preferences
            alpha = 0.1  # learning rate
            
            current_shadow = self.comfort_weights.shadow_weight
            current_heat = self.comfort_weights.heat_weight
            
            # move weights towards user preference
            new_shadow = current_shadow + alpha * (shadow_preference - current_shadow)
            new_heat = current_heat + alpha * (heat_preference - current_heat)
            
            self.comfort_weights.shadow_weight = new_shadow
            self.comfort_weights.heat_weight = new_heat
            self.comfort_weights.normalize()
            self.comfort_weights.user_id = user_id
            self.comfort_weights.learned_from_feedback = True

