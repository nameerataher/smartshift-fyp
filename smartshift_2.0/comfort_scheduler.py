"""
comfort_scheduler.py

deterministic scheduling engine using sliding window optimization
finds optimal time slots based on unified comfort score
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import numpy as np

from core_model import (
    SpaceTimeCell, SpaceTimeDataset, WorkZone, TimeWindow,
    ComfortWeights, HeatRiskClass, compute_comfort_score
)


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
    2. for each interval, compute comfort_score
    3. slide a window of task duration
    4. pick the window with maximum average comfort_score
    """
    
    def __init__(
        self,
        temporal_resolution_minutes: int = 10,
        comfort_weights: Optional[ComfortWeights] = None
    ):
        """
        initialize scheduler
        
        args:
            temporal_resolution_minutes: time discretization (5, 10, or 15 min)
            comfort_weights: optional custom weights for comfort calculation
        """
        self.temporal_resolution = temporal_resolution_minutes
        self.comfort_weights = comfort_weights or ComfortWeights()
    
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
        rank_by: str = "shade"
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
        
        returns:
            ScheduleRecommendation with best time and alternatives
        """
        # if no dataset provided, generate it
        if dataset is None:
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
                cells_in_window
            )
            
            candidates.append(candidate)
        
        if not candidates:
            raise ValueError(
                f"no feasible schedule found for {task_name} "
                f"on {date.date()} between {start_hour}:00-{end_hour}:00"
            )
        
        # sort candidates by requested ranking metric (descending)
        # default: prioritize higher shade coverage, then comfort score
        if rank_by == "comfort":
            candidates.sort(key=lambda c: (c.avg_comfort_score, c.avg_shadow_ratio), reverse=True)
        else:
            candidates.sort(key=lambda c: (c.avg_shadow_ratio, c.avg_comfort_score), reverse=True)
        
        best_candidate = candidates[0]
        # recommendation_count includes the best slot
        # provide remaining slots as alternatives
        total_recs = max(1, int(recommendation_count))
        alternatives = candidates[1:total_recs]
        
        # generate recommendation reason
        reason = self._generate_recommendation_reason(best_candidate, work_zone)
        
        return ScheduleRecommendation(
            task_name=task_name,
            work_zone=work_zone,
            best_candidate=best_candidate,
            alternative_candidates=alternatives,
            total_candidates_evaluated=len(candidates),
            evaluation_date=date,
            recommendation_reason=reason
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
        cells: List[SpaceTimeCell]
    ) -> ScheduleCandidate:
        """
        evaluate a time window based on its cells
        
        computes aggregate metrics:
        - average comfort score
        - minimum comfort score (worst moment)
        - shadow coverage
        - heat risk distribution
        """
        if not cells:
            # return worst-case candidate if no data
            return ScheduleCandidate(
                window=window,
                cells=[],
                avg_comfort_score=0.0,
                min_comfort_score=0.0,
                avg_shadow_ratio=0.0,
                avg_heat_risk_score=1.0
            )
        
        # compute aggregate metrics
        comfort_scores = [cell.comfort_score for cell in cells]
        shadow_ratios = [cell.shadow_ratio for cell in cells]
        heat_risk_scores = [cell.heat_risk_score for cell in cells]
        
        avg_comfort = np.mean(comfort_scores)
        min_comfort = np.min(comfort_scores)
        avg_shadow = np.mean(shadow_ratios)
        avg_heat = np.mean(heat_risk_scores)
        
        # count risk distribution
        low_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.LOW)
        med_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.MEDIUM)
        high_count = sum(1 for c in cells if c.heat_risk_class == HeatRiskClass.HIGH)
        
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
            ranking_score=avg_comfort
        )
    
    def _generate_recommendation_reason(
        self,
        candidate: ScheduleCandidate,
        zone: WorkZone
    ) -> str:
        """generate human-readable explanation"""
        start_str = candidate.window.start.strftime("%H:%M")
        end_str = candidate.window.end.strftime("%H:%M")
        
        shadow_pct = candidate.avg_shadow_ratio * 100
        comfort_pct = candidate.avg_comfort_score * 100
        
        # determine primary reason
        if candidate.avg_shadow_ratio > 0.6:
            primary_reason = f"{shadow_pct:.0f}% shaded"
        elif candidate.avg_heat_risk_score < 0.3:
            primary_reason = "low heat risk"
        else:
            primary_reason = f"{comfort_pct:.0f}% comfort score"
        
        # risk level description
        if candidate.high_risk_minutes > 0:
            risk_desc = f"⚠️ {candidate.high_risk_minutes} minutes of high heat risk"
        elif candidate.medium_risk_minutes > 0:
            risk_desc = f"moderate heat conditions"
        else:
            risk_desc = "optimal thermal comfort"
        
        zone_name = zone.get_oriented_name()
        
        return (f"recommended {start_str}–{end_str} at {zone_name}. "
                f"{primary_reason}, {risk_desc}.")
    
    def _generate_dataset_for_zone(
        self,
        work_zone: WorkZone,
        date: datetime,
        start_hour: int,
        end_hour: int
    ) -> SpaceTimeDataset:
        """
        generate space-time cells for a work zone
        
        this is a placeholder - in the full system, this would:
        1. query shadow calculator for shadow_ratio
        2. query heat risk model for heat_risk_class and heat_risk_score
        3. compute comfort_score
        
        for now, returns synthetic data
        """
        from heat_risk_model import HeatRiskModel
        from solar_position import SolarPositionCalculator
        
        # initialize models (lazy loading)
        heat_model = HeatRiskModel()
        solar_calc = SolarPositionCalculator(
            latitude=work_zone.lat,
            longitude=work_zone.lon,
            timezone_offset=4.0
        )
        
        dataset = SpaceTimeDataset(
            temporal_resolution_minutes=self.temporal_resolution
        )
        
        # generate cells for each time interval
        time_intervals = self._discretize_time_range(
            date, start_hour, end_hour, self.temporal_resolution
        )
        
        for timestamp in time_intervals:
            # placeholder: in real system, query shadow calculator and weather
            # for now, use simplified simulation
            
            sun_pos = solar_calc.get_sun_position(timestamp)
            
            # simplified shadow estimation based on sun altitude
            if sun_pos.altitude <= 0:
                shadow_ratio = 1.0  # night = full shade
            else:
                # higher sun = less shadow from buildings
                # this is simplified - real version uses 3d shadow calculation
                shadow_ratio = 0.3 + 0.4 * (1 - sun_pos.altitude / 90)
                
                # adjust for orientation if facade
                if work_zone.is_facade and work_zone.orientation is not None:
                    sun_azimuth = sun_pos.azimuth
                    facade_azimuth = work_zone.orientation
                    angle_diff = abs(((sun_azimuth - facade_azimuth + 180) % 360) - 180)
                    
                    # if sun is behind facade, more shade
                    if angle_diff > 90:
                        shadow_ratio = min(1.0, shadow_ratio + 0.3)
            
            # placeholder heat risk (would come from heat_risk_model in real system)
            # for now, use time-based heuristic
            hour = timestamp.hour + timestamp.minute / 60
            if 11 <= hour <= 15:
                heat_risk_score = 0.7
                heat_risk_class = HeatRiskClass.MEDIUM
            elif 10 <= hour <= 16:
                heat_risk_score = 0.5
                heat_risk_class = HeatRiskClass.MEDIUM
            else:
                heat_risk_score = 0.2
                heat_risk_class = HeatRiskClass.LOW
            
            # compute comfort score
            comfort = compute_comfort_score(
                shadow_ratio,
                heat_risk_score,
                self.comfort_weights
            )
            
            # create cell
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

