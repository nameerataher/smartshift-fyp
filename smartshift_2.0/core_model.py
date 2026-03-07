"""
core_model.py

unified space-time data model for smartshift 2.0
defines the canonical representation of environmental comfort data
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from enum import Enum
import numpy as np


class HeatRiskClass(Enum):
    """heat risk classification levels"""
    LOW = 0
    MEDIUM = 1
    HIGH = 2


class SpatialResolution(Enum):
    """spatial resolution types for different use cases"""
    NAVIGATION = "navigation"      # paths, routes
    WORK_ZONE = "work_zone"        # building sides, work areas
    HEATMAP_GRID = "heatmap_grid"  # visualization grid


@dataclass
class SpaceTimeCell:
    """
    canonical representation of environmental conditions
    at a specific location and time
    
    this is the fundamental unit of the smartshift system
    """
    # spatial coordinates
    lat: float
    lon: float
    
    # temporal coordinate
    timestamp: datetime
    
    # environmental metrics (raw)
    shadow_ratio: float           # 0 = full sun, 1 = full shade
    heat_risk_class: HeatRiskClass
    heat_risk_score: float        # 0 = safe, 1 = dangerous (continuous)
    
    # derived comfort metric
    comfort_score: float          # composite score (higher = better)
    
    # optional detailed metrics
    wbgt_estimate: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    uv_index: Optional[float] = None
    
    # metadata
    resolution_type: Optional[SpatialResolution] = None
    zone_id: Optional[str] = None  # for work zones
    
    def __repr__(self):
        return (f"SpaceTimeCell(lat={self.lat:.4f}, lon={self.lon:.4f}, "
                f"time={self.timestamp.strftime('%H:%M')}, "
                f"comfort={self.comfort_score:.2f}, "
                f"shadow={self.shadow_ratio:.2f}, "
                f"risk={self.heat_risk_class.name})")


@dataclass
class WorkZone:
    """
    represents a stationary outdoor work area with changing solar exposure
    
    examples:
    - building façade (with orientation)
    - construction site section
    - street segment
    - sidewalk stretch
    - park maintenance area
    - road repair patch
    """
    zone_id: str
    name: str
    
    # location (center point)
    lat: float
    lon: float
    
    # spatial extent
    radius: Optional[float] = None  # meters, for circular zones
    
    # orientation (for façades)
    orientation: Optional[float] = None  # degrees: 0=N, 90=E, 180=S, 270=W
    is_facade: bool = False
    
    # building id (if part of a building)
    building_id: Optional[str] = None
    
    # zone type descriptor
    zone_type: str = "general"  # facade, construction, street, park, etc
    
    # metadata
    description: Optional[str] = None
    
    def get_oriented_name(self) -> str:
        """get human-readable orientation for façades"""
        if not self.is_facade or self.orientation is None:
            return self.name
        
        directions = {
            0: "North", 45: "NE", 90: "East", 135: "SE",
            180: "South", 225: "SW", 270: "West", 315: "NW"
        }
        
        # find closest cardinal direction
        closest = min(directions.keys(), key=lambda x: abs(x - self.orientation % 360))
        return f"{self.name} ({directions[closest]}-facing)"


@dataclass
class TimeWindow:
    """represents a contiguous time period"""
    start: datetime
    end: datetime
    
    def duration_minutes(self) -> int:
        """get duration in minutes"""
        return int((self.end - self.start).total_seconds() / 60)
    
    def contains(self, timestamp: datetime) -> bool:
        """check if timestamp is within this window"""
        return self.start <= timestamp <= self.end
    
    def __repr__(self):
        return f"TimeWindow({self.start.strftime('%H:%M')}–{self.end.strftime('%H:%M')})"


@dataclass
class ComfortWeights:
    """
    tunable weights for comfort score calculation
    allows user preferences and adaptive optimization
    """
    shadow_weight: float = 0.6      # α - importance of shade
    heat_weight: float = 0.4        # β - importance of heat risk
    
    # user preference tracking
    user_id: Optional[str] = None
    learned_from_feedback: bool = False
    
    def normalize(self):
        """ensure weights sum to 1"""
        total = self.shadow_weight + self.heat_weight
        if total > 0:
            self.shadow_weight /= total
            self.heat_weight /= total


def compute_comfort_score(
    shadow_ratio: float,
    heat_risk_score: float,
    weights: Optional[ComfortWeights] = None
) -> float:
    """
    compute the unified comfort score
    
    thermal comfort is a combined function of radiative exposure
    and ambient heat stress
    
    formula: comfort_score = α * shadow_ratio − β * heat_risk_score
    
    normalized to [0, 1] range where:
    - 1.0 = optimal (full shade, low heat)
    - 0.0 = dangerous (full sun, high heat)
    
    args:
        shadow_ratio: 0 (full sun) to 1 (full shade)
        heat_risk_score: 0 (safe) to 1 (dangerous)
        weights: optional tunable weights (default: 60% shadow, 40% heat)
    
    returns:
        comfort_score in [0, 1]
    """
    if weights is None:
        weights = ComfortWeights()
    
    # ensure weights are normalized
    weights.normalize()
    
    # compute composite score
    score = (weights.shadow_weight * shadow_ratio - 
             weights.heat_weight * heat_risk_score)
    
    # normalize to [0, 1] range
    # the formula above gives range [-β, α]
    # we map this to [0, 1]
    min_possible = -weights.heat_weight
    max_possible = weights.shadow_weight
    
    normalized = (score - min_possible) / (max_possible - min_possible)
    
    return np.clip(normalized, 0.0, 1.0)


@dataclass
class SpaceTimeDataset:
    """
    collection of space-time cells representing environmental conditions
    over a spatial and temporal range
    """
    cells: List[SpaceTimeCell] = field(default_factory=list)
    
    # spatial bounds
    min_lat: Optional[float] = None
    max_lat: Optional[float] = None
    min_lon: Optional[float] = None
    max_lon: Optional[float] = None
    
    # temporal bounds
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # resolution metadata
    temporal_resolution_minutes: int = 10  # default: 10-min intervals
    spatial_resolution_type: Optional[SpatialResolution] = None
    
    def add_cell(self, cell: SpaceTimeCell):
        """add a cell and update bounds"""
        self.cells.append(cell)
        
        # update spatial bounds
        if self.min_lat is None or cell.lat < self.min_lat:
            self.min_lat = cell.lat
        if self.max_lat is None or cell.lat > self.max_lat:
            self.max_lat = cell.lat
        if self.min_lon is None or cell.lon < self.min_lon:
            self.min_lon = cell.lon
        if self.max_lon is None or cell.lon > self.max_lon:
            self.max_lon = cell.lon
        
        # update temporal bounds
        if self.start_time is None or cell.timestamp < self.start_time:
            self.start_time = cell.timestamp
        if self.end_time is None or cell.timestamp > self.end_time:
            self.end_time = cell.timestamp
    
    def query_at_location_time(
        self,
        lat: float,
        lon: float,
        timestamp: datetime,
        tolerance_meters: float = 50.0,
        tolerance_minutes: int = 5
    ) -> Optional[SpaceTimeCell]:
        """
        query the nearest cell at a given location and time
        
        uses haversine distance for spatial matching
        and time delta for temporal matching
        """
        from math import radians, cos, sin, asin, sqrt
        
        def haversine(lat1, lon1, lat2, lon2):
            """calculate haversine distance in meters"""
            R = 6371000  # earth radius in meters
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        best_cell = None
        best_distance = float('inf')
        
        for cell in self.cells:
            # check temporal match
            time_diff_minutes = abs((cell.timestamp - timestamp).total_seconds() / 60)
            if time_diff_minutes > tolerance_minutes:
                continue
            
            # check spatial match
            distance = haversine(lat, lon, cell.lat, cell.lon)
            if distance <= tolerance_meters and distance < best_distance:
                best_distance = distance
                best_cell = cell
        
        return best_cell
    
    def get_cells_in_time_window(
        self,
        start: datetime,
        end: datetime,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        tolerance_meters: float = 50.0
    ) -> List[SpaceTimeCell]:
        """
        get all cells within a time window
        optionally filtered by location
        """
        from math import radians, cos, sin, asin, sqrt
        
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        filtered_cells = []
        
        for cell in self.cells:
            # check time window
            if not (start <= cell.timestamp <= end):
                continue
            
            # check location if provided
            if lat is not None and lon is not None:
                distance = haversine(lat, lon, cell.lat, cell.lon)
                if distance > tolerance_meters:
                    continue
            
            filtered_cells.append(cell)
        
        # sort by timestamp
        filtered_cells.sort(key=lambda c: c.timestamp)
        
        return filtered_cells
    
    def to_geojson(self) -> Dict:
        """
        export cells as geojson for visualization
        useful for heatmap layers
        """
        features = []
        
        for cell in self.cells:
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [cell.lon, cell.lat]
                },
                "properties": {
                    "timestamp": cell.timestamp.isoformat(),
                    "comfort_score": float(cell.comfort_score),
                    "shadow_ratio": float(cell.shadow_ratio),
                    "heat_risk_class": cell.heat_risk_class.name,
                    "heat_risk_score": float(cell.heat_risk_score),
                    "wbgt": float(cell.wbgt_estimate) if cell.wbgt_estimate else None,
                    "temperature": float(cell.temperature) if cell.temperature else None,
                }
            }
            features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features
        }
    
    def __len__(self):
        return len(self.cells)
    
    def __repr__(self):
        return (f"SpaceTimeDataset(cells={len(self.cells)}, "
                f"time_range={self.start_time.strftime('%H:%M') if self.start_time else 'N/A'}–"
                f"{self.end_time.strftime('%H:%M') if self.end_time else 'N/A'})")







