"""
api_v2.py

new api endpoints using the unified core_model architecture
provides comfort-based scheduling and routing with explainable recommendations
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import traceback

# import new architecture modules
try:
    from core_model import (
        SpaceTimeCell, SpaceTimeDataset, WorkZone, TimeWindow,
        ComfortWeights, HeatRiskClass, SpatialResolution,
        compute_comfort_score
    )
    from comfort_scheduler import (
        ComfortScheduler, ScheduleRecommendation,
        SchedulingMode, BuildingFace, AreaPolygon
    )
    from comfort_navigator import ComfortNavigator, RouteRecommendation
    from heat_risk_model import HeatRiskModel, WeatherData, LocationContext, SunExposure
    NEW_ARCH_AVAILABLE = True
except ImportError as e:
    NEW_ARCH_AVAILABLE = False
    print(f"warning: new architecture not available: {e}")

# create blueprint for v2 api
api_v2 = Blueprint('api_v2', __name__, url_prefix='/api/v2')

# lazy-load singletons
_comfort_scheduler = None
_comfort_navigator = None
_heat_risk_model = None

def get_comfort_scheduler(mode: str = "shadow_only") -> ComfortScheduler:
    """get comfort scheduler with specified mode"""
    # Map string mode to enum
    mode_map = {
        "shadow_only": SchedulingMode.SHADOW_ONLY,
        "comfort": SchedulingMode.COMFORT,
        "area": SchedulingMode.AREA,
        "building_face": SchedulingMode.BUILDING_FACE
    }
    scheduling_mode = mode_map.get(mode.lower(), SchedulingMode.SHADOW_ONLY)
    
    return ComfortScheduler(
        temporal_resolution_minutes=10,
        mode=scheduling_mode
    )

def get_comfort_navigator(mapbox_token: str) -> ComfortNavigator:
    """get comfort navigator with mapbox token"""
    return ComfortNavigator(
        mapbox_token=mapbox_token,
        sample_interval_meters=15.0
    )

def get_heat_risk_model() -> HeatRiskModel:
    """lazy-load heat risk model"""
    global _heat_risk_model
    if _heat_risk_model is None:
        _heat_risk_model = HeatRiskModel()
    return _heat_risk_model


# =============================================================================
# v2 endpoints
# =============================================================================

@api_v2.route('/health', methods=['GET'])
def health_check():
    """health check for v2 api"""
    return jsonify({
        "status": "healthy",
        "version": "2.0",
        "architecture": "unified_space_time_model",
        "new_arch_available": NEW_ARCH_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    })


@api_v2.route('/comfort-score', methods=['POST'])
def compute_comfort():
    """
    compute comfort score for given shadow and heat risk

    POST /api/v2/comfort-score
    {
        "shadow_ratio": 0.7,
        "heat_risk_score": 0.3,
        "shadow_weight": 0.6,  // optional
        "heat_weight": 0.4     // optional
    }

    returns:
    {
        "comfort_score": 0.75,
        "shadow_ratio": 0.7,
        "heat_risk_score": 0.3,
        "interpretation": "optimal comfort"
    }
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500

    try:
        data = request.get_json()

        shadow_ratio = float(data.get('shadow_ratio', 0))
        heat_risk_score = float(data.get('heat_risk_score', 0))

        # optional custom weights
        weights = None
        if 'shadow_weight' in data and 'heat_weight' in data:
            weights = ComfortWeights(
                shadow_weight=float(data['shadow_weight']),
                heat_weight=float(data['heat_weight'])
            )

        # compute comfort score
        comfort = compute_comfort_score(shadow_ratio, heat_risk_score, weights)

        # interpretation
        if comfort > 0.75:
            interpretation = "optimal comfort"
        elif comfort > 0.5:
            interpretation = "acceptable conditions"
        elif comfort > 0.3:
            interpretation = "moderate discomfort"
        else:
            interpretation = "uncomfortable / unsafe"

        return jsonify({
            "success": True,
            "comfort_score": float(comfort),
            "shadow_ratio": float(shadow_ratio),
            "heat_risk_score": float(heat_risk_score),
            "interpretation": interpretation,
            "weights_used": {
                "shadow_weight": weights.shadow_weight if weights else 0.6,
                "heat_weight": weights.heat_weight if weights else 0.4
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/schedule', methods=['POST'])
def find_optimal_schedule():
    """
    find optimal schedule for a task using deterministic sliding window
    
    Supports three modes:
    - shadow_only: Only consider shadow exposure (default)
    - area: Polygon area mode for batch tasks
    - building_face: Building face orientation mode (N/E/S/W)

    POST /api/v2/schedule
    {
        "task_name": "facade cleaning - south wall",
        "mode": "shadow_only",  // shadow_only, area, building_face
        "work_zone": {
            "zone_id": "bldg_123_south",
            "name": "burj khalifa south facade",
            "lat": 25.197197,
            "lon": 55.274376,
            "radius": 25,
            "is_facade": true,
            "orientation": 180
        },
        "task_duration_minutes": 120,
        "date": "2026-02-10",
        "start_hour": 9,
        "end_hour": 17,
        "building_face": "S",  // optional: N, E, S, W for building_face mode
        "area_polygon": [      // optional: for area mode
            [25.195, 55.270],
            [25.195, 55.280],
            [25.200, 55.280],
            [25.200, 55.270]
        ]
    }

    returns schedule recommendation with best time and alternatives
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500

    try:
        data = request.get_json()

        # parse scheduling mode (default: shadow_only as per requirement)
        mode = data.get('mode', 'shadow_only')
        
        # parse task info
        task_name = data.get('task_name', 'outdoor task')
        task_duration = int(data.get('task_duration_minutes', 60))

        # parse work zone
        zone_data = data.get('work_zone', {})
        work_zone = WorkZone(
            zone_id=zone_data.get('zone_id', 'default'),
            name=zone_data.get('name', 'work area'),
            lat=float(zone_data.get('lat')),
            lon=float(zone_data.get('lon')),
            radius=float(zone_data.get('radius', 50.0)),
            is_facade=zone_data.get('is_facade', False),
            orientation=zone_data.get('orientation'),
            zone_type=zone_data.get('zone_type', 'general')
        )

        # parse date and time window
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 9))
        end_hour = int(data.get('end_hour', 17))
        recommendation_count = int(data.get('recommendation_count', 5))
        rank_by = data.get('rank_by', 'shade')
        
        # parse building face for building_face mode
        building_face = data.get('building_face')
        
        # parse area polygon for area mode
        area_polygon = None
        if data.get('area_polygon'):
            polygon_points = [(p[0], p[1]) for p in data['area_polygon']]
            area_polygon = AreaPolygon(points=polygon_points, name=task_name)

        # get scheduler with appropriate mode
        scheduler = get_comfort_scheduler(mode)

        # find optimal schedule
        recommendation = scheduler.find_optimal_schedule(
            task_name=task_name,
            work_zone=work_zone,
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count,
            rank_by=rank_by,
            building_face=building_face,
            area_polygon=area_polygon
        )

        return jsonify({
            "success": True,
            "mode": mode,
            "recommendation": recommendation.to_dict()
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/schedule/area', methods=['POST'])
def schedule_for_area():
    """
    Schedule task for a polygon area (batch tasks like municipality cleaning).
    Only considers shadow exposure.
    
    POST /api/v2/schedule/area
    {
        "task_name": "Road Cleaning",
        "polygon_points": [
            [25.195, 55.270],
            [25.195, 55.280],
            [25.200, 55.280],
            [25.200, 55.270]
        ],
        "task_duration_minutes": 180,
        "date": "2026-03-10",
        "start_hour": 5,
        "end_hour": 20
    }
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500
    
    try:
        data = request.get_json()
        
        task_name = data.get('task_name', 'area task')
        polygon_points = [(p[0], p[1]) for p in data.get('polygon_points', [])]
        task_duration = int(data.get('task_duration_minutes', 60))
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 5))
        end_hour = int(data.get('end_hour', 20))
        recommendation_count = int(data.get('recommendation_count', 5))
        
        scheduler = get_comfort_scheduler('shadow_only')
        
        recommendation = scheduler.find_optimal_for_area(
            task_name=task_name,
            polygon_points=polygon_points,
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count
        )
        
        return jsonify({
            "success": True,
            "mode": "area",
            "recommendation": recommendation.to_dict()
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/schedule/building-face', methods=['POST'])
def schedule_for_building_face():
    """
    Schedule task for a building face (N/E/S/W).
    Only considers shadow exposure on that specific face.
    
    POST /api/v2/schedule/building-face
    {
        "task_name": "Facade Cleaning",
        "building_lat": 25.197197,
        "building_lon": 55.274376,
        "face": "S",
        "task_duration_minutes": 240,
        "date": "2026-03-10",
        "start_hour": 5,
        "end_hour": 20
    }
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500
    
    try:
        data = request.get_json()
        
        task_name = data.get('task_name', 'facade task')
        building_lat = float(data.get('building_lat'))
        building_lon = float(data.get('building_lon'))
        face = data.get('face', 'S')
        task_duration = int(data.get('task_duration_minutes', 60))
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 5))
        end_hour = int(data.get('end_hour', 20))
        recommendation_count = int(data.get('recommendation_count', 5))
        
        scheduler = get_comfort_scheduler('shadow_only')
        
        recommendation = scheduler.find_optimal_for_building_face(
            task_name=task_name,
            building_lat=building_lat,
            building_lon=building_lon,
            face=face,
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count
        )
        
        return jsonify({
            "success": True,
            "mode": "building_face",
            "face": face,
            "recommendation": recommendation.to_dict()
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/route', methods=['POST'])
def find_comfortable_route():
    """
    find comfortable route using mapbox routing + environmental re-ranking

    POST /api/v2/route
    {
        "start": {"lat": 25.2048, "lon": 55.2708},
        "end": {"lat": 25.1972, "lon": 55.2744},
        "mode": "walking",  // walking, cycling
        "departure_time": "2026-02-10T10:30:00",  // optional
        "mapbox_token": "pk.xxx",
        "alternatives": 3
    }

    returns route recommendation with environmental comfort scores
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500

    try:
        data = request.get_json()

        # parse locations
        start = data.get('start', {})
        end = data.get('end', {})

        start_lat = float(start.get('lat'))
        start_lon = float(start.get('lon'))
        end_lat = float(end.get('lat'))
        end_lon = float(end.get('lon'))

        # parse options
        mode = data.get('mode', 'walking').lower()
        if mode not in ['walking', 'cycling']:
            mode = 'walking'

        # parse departure time
        departure_str = data.get('departure_time')
        if departure_str:
            departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))
        else:
            departure_time = datetime.now()

        # get mapbox token
        mapbox_token = data.get('mapbox_token')
        if not mapbox_token:
            return jsonify({"error": "mapbox_token required"}), 400

        alternatives = int(data.get('alternatives', 3))

        # get navigator
        navigator = get_comfort_navigator(mapbox_token)

        # find comfortable route
        recommendation = navigator.find_comfortable_route(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            mode=mode,
            departure_time=departure_time,
            alternatives=alternatives
        )

        return jsonify({
            "success": True,
            "recommendation": recommendation.to_dict()
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/heatmap', methods=['POST'])
def generate_heatmap():
    """
    generate heatmap geojson for visualization

    POST /api/v2/heatmap
    {
        "bbox": {
            "min_lat": 25.19,
            "max_lat": 25.21,
            "min_lon": 55.26,
            "max_lon": 55.28
        },
        "grid_size_meters": 25,
        "time": "2026-02-10T14:00:00"
    }

    returns geojson with comfort scores for visualization
    """
    if not NEW_ARCH_AVAILABLE:
        return jsonify({"error": "new architecture not available"}), 500

    try:
        data = request.get_json()

        # parse bounding box
        bbox = data.get('bbox', {})
        min_lat = float(bbox.get('min_lat', 25.19))
        max_lat = float(bbox.get('max_lat', 25.21))
        min_lon = float(bbox.get('min_lon', 55.26))
        max_lon = float(bbox.get('max_lon', 55.28))

        grid_size = float(data.get('grid_size_meters', 25))

        # parse time
        time_str = data.get('time')
        if time_str:
            timestamp = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.now()

        # generate grid cells
        # this is simplified - in production, would use actual shadow/heat calculations
        dataset = SpaceTimeDataset(
            spatial_resolution_type=SpatialResolution.HEATMAP_GRID
        )

        # create grid (simplified - just demo structure)
        lat_step = grid_size / 111000  # approx meters to degrees
        lon_step = grid_size / (111000 * 0.9)  # approximate for UAE latitude

        lat = min_lat
        while lat <= max_lat:
            lon = min_lon
            while lon <= max_lon:
                # placeholder: in reality, query shadow calculator and heat model
                shadow_ratio = 0.4 + 0.3 * ((lat - min_lat) / (max_lat - min_lat))
                heat_risk_score = 0.3 + 0.4 * ((lon - min_lon) / (max_lon - min_lon))

                comfort = compute_comfort_score(shadow_ratio, heat_risk_score)

                cell = SpaceTimeCell(
                    lat=lat,
                    lon=lon,
                    timestamp=timestamp,
                    shadow_ratio=shadow_ratio,
                    heat_risk_class=HeatRiskClass.MEDIUM,
                    heat_risk_score=heat_risk_score,
                    comfort_score=comfort
                )
                dataset.add_cell(cell)

                lon += lon_step
            lat += lat_step

        # convert to geojson
        geojson = dataset.to_geojson()

        return jsonify({
            "success": True,
            "geojson": geojson,
            "metadata": {
                "grid_size_meters": grid_size,
                "num_cells": len(dataset),
                "timestamp": timestamp.isoformat()
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/work-zones', methods=['GET', 'POST'])
def manage_work_zones():
    """
    create or list work zones

    GET /api/v2/work-zones - list all work zones
    POST /api/v2/work-zones - create new work zone
    {
        "zone_id": "burj_south",
        "name": "burj khalifa south facade",
        "lat": 25.197197,
        "lon": 55.274376,
        "radius": 25,
        "is_facade": true,
        "orientation": 180,
        "zone_type": "facade"
    }
    """
    if request.method == 'POST':
        try:
            data = request.get_json()

            zone = WorkZone(
                zone_id=data.get('zone_id', f'zone_{datetime.now().timestamp()}'),
                name=data.get('name', 'unnamed zone'),
                lat=float(data.get('lat')),
                lon=float(data.get('lon')),
                radius=float(data.get('radius', 50.0)),
                is_facade=data.get('is_facade', False),
                orientation=data.get('orientation'),
                zone_type=data.get('zone_type', 'general'),
                building_id=data.get('building_id'),
                description=data.get('description')
            )

            # in production, save to database
            # for now, just return the created zone

            return jsonify({
                "success": True,
                "zone": {
                    "zone_id": zone.zone_id,
                    "name": zone.get_oriented_name(),
                    "lat": zone.lat,
                    "lon": zone.lon,
                    "radius": zone.radius,
                    "is_facade": zone.is_facade,
                    "orientation": zone.orientation,
                    "zone_type": zone.zone_type
                }
            })

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    else:  # GET
        # return sample work zones for demonstration
        sample_zones = [
            {
                "zone_id": "burj_south",
                "name": "burj khalifa south facade",
                "lat": 25.197197,
                "lon": 55.274376,
                "is_facade": True,
                "orientation": 180
            },
            {
                "zone_id": "construction_site_1",
                "name": "downtown construction site",
                "lat": 25.195,
                "lon": 55.275,
                "is_facade": False,
                "zone_type": "construction"
            }
        ]

        return jsonify({
            "success": True,
            "zones": sample_zones
        })


@api_v2.route('/feedback', methods=['POST'])
def submit_feedback():
    """
    submit user feedback to adapt comfort weights

    POST /api/v2/feedback
    {
        "user_id": "user_123",
        "schedule_id": "sched_456",
        "accepted": true,
        "shadow_preference": 0.7,
        "heat_preference": 0.3
    }
    """
    try:
        data = request.get_json()

        user_id = data.get('user_id', 'anonymous')
        accepted = data.get('accepted', False)
        shadow_pref = float(data.get('shadow_preference', 0.6))
        heat_pref = float(data.get('heat_preference', 0.4))

        # update scheduler weights (in production, per-user)
        scheduler = get_comfort_scheduler()
        scheduler.update_weights_from_feedback(
            user_id=user_id,
            accepted=accepted,
            shadow_preference=shadow_pref,
            heat_preference=heat_pref
        )

        return jsonify({
            "success": True,
            "message": "feedback received, weights updated",
            "updated_weights": {
                "shadow_weight": scheduler.comfort_weights.shadow_weight,
                "heat_weight": scheduler.comfort_weights.heat_weight
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

