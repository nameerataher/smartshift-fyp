"""
comfort_navigator.py

navigation and routing engine with environmental comfort re-ranking
augments mapbox routing with heat and shade intelligence
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests
import numpy as np
from math import radians, cos, sin, asin, sqrt

from core_model import (
    SpaceTimeCell, SpaceTimeDataset, ComfortWeights,
    HeatRiskClass, compute_comfort_score
)


@dataclass
class RoutePoint:
    """single point along a route with environmental data"""
    lat: float
    lon: float
    timestamp: datetime  # eta at this point

    # environmental metrics
    shadow_ratio: float
    heat_risk_score: float
    comfort_score: float

    # distance along route (meters)
    distance_from_start: float = 0.0


@dataclass
class RouteSegment:
    """segment of a route between two points"""
    start_point: RoutePoint
    end_point: RoutePoint

    # segment metrics
    distance_meters: float
    duration_seconds: float

    # aggregate environmental comfort
    avg_comfort_score: float
    avg_shadow_ratio: float
    avg_heat_risk_score: float


@dataclass
class EvaluatedRoute:
    """a route with environmental comfort evaluation"""
    route_id: int

    # geometry
    coordinates: List[List[float]]  # [[lon, lat], ...]

    # base routing metrics
    distance_meters: float
    duration_seconds: float

    # environmental comfort metrics
    sampled_points: List[RoutePoint]
    avg_comfort_score: float
    min_comfort_score: float  # worst point on route

    # aggregate exposure
    total_sun_exposure_minutes: float
    total_shade_coverage_percentage: float

    # risk distribution along route
    high_risk_segments: int = 0
    medium_risk_segments: int = 0
    low_risk_segments: int = 0

    # multi-objective score
    final_score: float = 0.0

    # metadata
    mode: str = "walking"  # walking, cycling, driving

    def __repr__(self):
        return (f"EvaluatedRoute(id={self.route_id}, "
                f"distance={self.distance_meters/1000:.1f}km, "
                f"comfort={self.avg_comfort_score:.2f})")


@dataclass
class RouteRecommendation:
    """final route recommendation with alternatives"""
    start_location: Dict[str, float]  # {lat, lon, name}
    end_location: Dict[str, float]

    # departure time
    departure_time: datetime

    # recommended route
    recommended_route: EvaluatedRoute

    # alternatives
    alternative_routes: List[EvaluatedRoute] = field(default_factory=list)

    # explanation
    recommendation_reason: str = ""

    # mode
    travel_mode: str = "walking"

    def to_dict(self) -> Dict:
        """convert to api-friendly format"""
        def route_to_dict(route: EvaluatedRoute) -> Dict:
            return {
                "route_id": route.route_id,
                "geometry": {
                    "type": "LineString",
                    "coordinates": route.coordinates
                },
                "distance_meters": float(route.distance_meters),
                "duration_seconds": int(route.duration_seconds),
                "comfort_score": float(route.avg_comfort_score),
                "min_comfort": float(route.min_comfort_score),
                "shade_coverage_percent": float(route.total_shade_coverage_percentage),
                "sun_exposure_minutes": float(route.total_sun_exposure_minutes),
                "risk_distribution": {
                    "high": route.high_risk_segments,
                    "medium": route.medium_risk_segments,
                    "low": route.low_risk_segments
                }
            }

        return {
            "start": self.start_location,
            "end": self.end_location,
            "departure_time": self.departure_time.isoformat(),
            "travel_mode": self.travel_mode,
            "recommended_route": route_to_dict(self.recommended_route),
            "alternative_routes": [route_to_dict(r) for r in self.alternative_routes],
            "recommendation_reason": self.recommendation_reason
        }


class ComfortNavigator:
    """
    navigation engine that re-ranks routes based on environmental comfort

    architecture:
    1. fetch candidate routes from mapbox directions api
    2. sample points along each route
    3. evaluate environmental comfort at each point
    4. compute route-level comfort scores
    5. re-rank routes using multi-objective scoring
    """

    def __init__(
        self,
        mapbox_token: str,
        comfort_weights: Optional[ComfortWeights] = None,
        sample_interval_meters: float = 15.0
    ):
        """
        initialize navigator

        args:
            mapbox_token: mapbox api access token
            comfort_weights: weights for comfort calculation
            sample_interval_meters: distance between sampled points for evaluation
        """
        self.mapbox_token = mapbox_token
        self.comfort_weights = comfort_weights or ComfortWeights()
        self.sample_interval_meters = sample_interval_meters

    def find_comfortable_route(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        mode: str = "walking",
        departure_time: Optional[datetime] = None,
        alternatives: int = 3
    ) -> RouteRecommendation:
        """
        find the most comfortable route between two points

        args:
            start_lat, start_lon: origin coordinates
            end_lat, end_lon: destination coordinates
            mode: travel mode (walking, cycling)
            departure_time: when the journey starts (default: now)
            alternatives: number of alternative routes to fetch

        returns:
            RouteRecommendation with best route and alternatives
        """
        if departure_time is None:
            departure_time = datetime.now()

        # step 1: fetch candidate routes from mapbox
        candidate_routes = self._fetch_mapbox_routes(
            start_lon, start_lat,
            end_lon, end_lat,
            mode,
            alternatives
        )

        if not candidate_routes:
            raise ValueError("no routes found between given points")

        # step 2: evaluate environmental comfort for each route
        evaluated_routes = []

        for i, route in enumerate(candidate_routes):
            evaluated = self._evaluate_route_comfort(
                route,
                i,
                departure_time,
                mode
            )
            evaluated_routes.append(evaluated)

        # step 3: multi-objective ranking
        for route in evaluated_routes:
            route.final_score = self._compute_final_score(route)

        # sort by final score (descending)
        evaluated_routes.sort(key=lambda r: r.final_score, reverse=True)

        best_route = evaluated_routes[0]
        alternatives_list = evaluated_routes[1:]

        # generate explanation
        reason = self._generate_route_recommendation_reason(best_route, mode)

        return RouteRecommendation(
            start_location={
                "lat": start_lat,
                "lon": start_lon,
                "name": "Start"
            },
            end_location={
                "lat": end_lat,
                "lon": end_lon,
                "name": "Destination"
            },
            departure_time=departure_time,
            recommended_route=best_route,
            alternative_routes=alternatives_list,
            recommendation_reason=reason,
            travel_mode=mode
        )

    def _fetch_mapbox_routes(
        self,
        start_lon: float,
        start_lat: float,
        end_lon: float,
        end_lat: float,
        mode: str,
        alternatives: int
    ) -> List[Dict]:
        """
        fetch route candidates from mapbox directions api

        uses correct profiles that automatically:
        - exclude highways & motorways
        - prefer sidewalks, footpaths, internal roads
        - respect pedestrian access rules
        """
        # map mode to mapbox profile
        profile_map = {
            "walking": "mapbox/walking",
            "cycling": "mapbox/cycling",
            "driving": "mapbox/driving"  # included but not recommended for outdoor workers
        }

        profile = profile_map.get(mode, "mapbox/walking")

        # construct coordinates string
        coordinates = f"{start_lon},{start_lat};{end_lon},{end_lat}"

        # build request url
        url = f"https://api.mapbox.com/directions/v5/{profile}/{coordinates}"

        params = {
            "access_token": self.mapbox_token,
            # mapbox expects alternatives as a boolean string ("true"/"false")
            # if true, mapbox returns multiple candidate routes we can re-rank
            "alternatives": "true" if alternatives and alternatives > 1 else "false",
            "geometries": "geojson",
            "overview": "full",
            "steps": "true",
            "annotations": "distance,duration"
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != "Ok":
                print(f"mapbox api error: {data.get('message', 'unknown error')}")
                return []

            return data.get("routes", [])

        except requests.RequestException as e:
            print(f"error fetching routes from mapbox: {e}")
            return []

    def _evaluate_route_comfort(
        self,
        route_data: Dict,
        route_id: int,
        departure_time: datetime,
        mode: str
    ) -> EvaluatedRoute:
        """
        evaluate environmental comfort for a route

        steps:
        1. sample points along route geometry
        2. compute eta for each point
        3. query environmental conditions at each point
        4. aggregate into route-level metrics
        """
        # extract route geometry and metrics
        geometry = route_data.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        distance = route_data.get("distance", 0)  # meters
        duration = route_data.get("duration", 0)  # seconds

        # sample points along route
        sampled_points = self._sample_route_points(
            coordinates,
            distance,
            duration,
            departure_time
        )

        # evaluate environmental conditions at each sampled point
        for point in sampled_points:
            self._evaluate_point_comfort(point)

        # aggregate metrics
        comfort_scores = [p.comfort_score for p in sampled_points]
        shadow_ratios = [p.shadow_ratio for p in sampled_points]

        avg_comfort = np.mean(comfort_scores) if comfort_scores else 0.0
        min_comfort = np.min(comfort_scores) if comfort_scores else 0.0
        avg_shadow = np.mean(shadow_ratios) if shadow_ratios else 0.0

        # calculate sun exposure time
        # assuming average walking speed consideration
        sun_minutes = sum(
            (1 - p.shadow_ratio) * (self.sample_interval_meters / 83.33)  # 83.33 m/min = 5 km/h walking
            for p in sampled_points
        )

        shade_percentage = avg_shadow * 100

        # count risk segments
        high_count = sum(1 for p in sampled_points if p.heat_risk_score > 0.7)
        med_count = sum(1 for p in sampled_points if 0.3 < p.heat_risk_score <= 0.7)
        low_count = sum(1 for p in sampled_points if p.heat_risk_score <= 0.3)

        return EvaluatedRoute(
            route_id=route_id,
            coordinates=coordinates,
            distance_meters=distance,
            duration_seconds=duration,
            sampled_points=sampled_points,
            avg_comfort_score=avg_comfort,
            min_comfort_score=min_comfort,
            total_sun_exposure_minutes=sun_minutes,
            total_shade_coverage_percentage=shade_percentage,
            high_risk_segments=high_count,
            medium_risk_segments=med_count,
            low_risk_segments=low_count,
            mode=mode
        )

    def _sample_route_points(
        self,
        coordinates: List[List[float]],
        total_distance: float,
        total_duration: float,
        departure_time: datetime
    ) -> List[RoutePoint]:
        """
        sample points at regular intervals along route geometry
        and compute eta for each point
        """
        if not coordinates or len(coordinates) < 2:
            return []

        sampled = []
        cumulative_distance = 0.0
        cumulative_time = 0.0

        for i in range(len(coordinates) - 1):
            lon1, lat1 = coordinates[i]
            lon2, lat2 = coordinates[i + 1]

            # distance of this segment
            segment_dist = self._haversine_distance(lat1, lon1, lat2, lon2)

            # add start point of segment if it's the first
            if i == 0:
                eta = departure_time
                sampled.append(RoutePoint(
                    lat=lat1,
                    lon=lon1,
                    timestamp=eta,
                    shadow_ratio=0.0,  # will be filled in
                    heat_risk_score=0.0,
                    comfort_score=0.0,
                    distance_from_start=0.0
                ))

            # sample points along this segment
            num_samples = max(1, int(segment_dist / self.sample_interval_meters))

            for j in range(1, num_samples + 1):
                fraction = j / num_samples

                # interpolate position
                lat = lat1 + fraction * (lat2 - lat1)
                lon = lon1 + fraction * (lon2 - lon1)

                # interpolate distance and time
                sample_dist = cumulative_distance + fraction * segment_dist
                progress = sample_dist / total_distance if total_distance > 0 else 0
                elapsed_seconds = progress * total_duration
                eta = departure_time + timedelta(seconds=elapsed_seconds)

                sampled.append(RoutePoint(
                    lat=lat,
                    lon=lon,
                    timestamp=eta,
                    shadow_ratio=0.0,
                    heat_risk_score=0.0,
                    comfort_score=0.0,
                    distance_from_start=sample_dist
                ))

            cumulative_distance += segment_dist

        return sampled

    def _evaluate_point_comfort(self, point: RoutePoint):
        """
        evaluate environmental comfort at a single point

        in the full system, this would:
        1. query shadow calculator for shadow_ratio at (lat, lon, time)
        2. query heat risk model for heat_risk_score
        3. compute comfort_score

        for now, uses simplified estimation
        """
        from solar_position import SolarPositionCalculator

        # get sun position at this time
        solar_calc = SolarPositionCalculator(
            latitude=point.lat,
            longitude=point.lon,
            timezone_offset=4.0
        )
        sun_pos = solar_calc.get_sun_position(point.timestamp)

        # simplified shadow estimation
        if sun_pos.altitude <= 0:
            shadow_ratio = 1.0  # nighttime
        else:
            # base shadow from buildings (simplified)
            # in reality, this comes from 3d shadow calculator
            shadow_ratio = 0.25 + 0.15 * (1 - sun_pos.altitude / 90)

        # simplified heat risk based on time of day
        hour = point.timestamp.hour + point.timestamp.minute / 60
        if 12 <= hour <= 15:
            heat_risk_score = 0.75
        elif 10 <= hour <= 17:
            heat_risk_score = 0.5
        else:
            heat_risk_score = 0.2

        # compute comfort
        comfort = compute_comfort_score(
            shadow_ratio,
            heat_risk_score,
            self.comfort_weights
        )

        # update point
        point.shadow_ratio = shadow_ratio
        point.heat_risk_score = heat_risk_score
        point.comfort_score = comfort

    def _compute_final_score(
        self,
        route: EvaluatedRoute,
        time_weight: float = 0.3,
        comfort_weight: float = 0.7
    ) -> float:
        """
        compute multi-objective final score

        formula: final_score = w1 * comfort_score − w2 * normalized_time

        this balances:
        - environmental comfort (higher is better)
        - travel time (shorter is better)
        """
        # normalize duration (assuming max reasonable duration is 2 hours = 7200 sec)
        max_duration = 7200
        normalized_time = min(1.0, route.duration_seconds / max_duration)

        # combine scores
        score = (comfort_weight * route.avg_comfort_score -
                 time_weight * normalized_time)

        # normalize to [0, 1]
        # possible range is [−time_weight, comfort_weight]
        min_possible = -time_weight
        max_possible = comfort_weight
        normalized_score = (score - min_possible) / (max_possible - min_possible)

        return np.clip(normalized_score, 0.0, 1.0)

    def _generate_route_recommendation_reason(
        self,
        route: EvaluatedRoute,
        mode: str
    ) -> str:
        """generate human-readable explanation for route recommendation"""
        duration_min = route.duration_seconds / 60
        distance_km = route.distance_meters / 1000

        # primary reason
        if route.total_shade_coverage_percentage > 65:
            primary = f"{route.total_shade_coverage_percentage:.0f}% shaded path"
        elif route.high_risk_segments == 0:
            primary = "minimal heat exposure"
        else:
            primary = f"{route.avg_comfort_score*100:.0f}% comfort score"

        # secondary info
        if route.high_risk_segments > 0:
            warning = f"⚠️ {route.high_risk_segments} high-heat segments"
        else:
            warning = "optimal thermal conditions"

        mode_desc = "walk" if mode == "walking" else "ride"

        return (f"recommended {mode_desc}: {distance_km:.1f}km in {duration_min:.0f} minutes. "
                f"{primary}, {warning}.")

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """calculate haversine distance in meters"""
        R = 6371000  # earth radius in meters
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c
