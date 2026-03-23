"""
Flask API Server for Dubai Sun-Shadow Simulation
==================================================

This module provides a REST API for the sun-shadow simulation system.

"""

import os
from pathlib import Path

# Load .env from backend directory so GOOGLE_DIRECTIONS_API_KEY is available
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass
# Log so you can confirm Compare (Google) has a key when starting the server
if os.environ.get("GOOGLE_DIRECTIONS_API_KEY", "").strip():
    print("[api_server] GOOGLE_DIRECTIONS_API_KEY is set (Compare will use Google)")
else:
    print("[api_server] GOOGLE_DIRECTIONS_API_KEY not set — Compare will show Mapbox only")

import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd

# Import our custom modules
from solar_position import SolarPositionCalculator, SunPosition
from shadow_calculator import ShadowCalculator, Building, Shadow
from config import (
    DUBAI, API, SHADOW,
    LANDMARK_LOCATIONS, SAMPLE_BUILDINGS,
    get_location_config, get_all_location_keys
)

# import ml models for heat risk; navigator for shaded routes
try:
    from heat_risk_model import (
        HeatRiskModel, WeatherData, LocationContext, SunExposure,
        HeatRiskPrediction
    )
    ML_MODELS_AVAILABLE = True
except ImportError as e:
    ML_MODELS_AVAILABLE = False
    print(f"Warning: ML models not available. Install dependencies: {e}")

try:
    from schedule_optimizer import ShadeNavigator
    NAVIGATOR_AVAILABLE = True
except ImportError:
    ShadeNavigator = None
    NAVIGATOR_AVAILABLE = False
    print("Warning: ShadeNavigator not available (schedule_optimizer)")

try:
    from shadow_scheduler import ShadowScheduler
    from shadow_scheduler import (
        calculate_shadow_at_time,
        parse_client_buildings,
        recommend_facades_for_fixed_window,
    )
    from solar_position import SunPosition
    SHADOW_SCHEDULER_AVAILABLE = True
except ImportError:
    ShadowScheduler = None
    SHADOW_SCHEDULER_AVAILABLE = False
    print("Warning: ShadowScheduler not available")

try:
    from core_model import (
        SpaceTimeCell, SpaceTimeDataset, WorkZone,
        ComfortWeights, HeatRiskClass, SpatialResolution,
        compute_comfort_score
    )
    CORE_MODEL_AVAILABLE = True
except ImportError as e:
    CORE_MODEL_AVAILABLE = False
    print(f"warning: core_model not available: {e}")

try:
    from comfort_navigator import ComfortNavigator
    COMFORT_NAVIGATOR_AVAILABLE = True
except ImportError:
    ComfortNavigator = None
    COMFORT_NAVIGATOR_AVAILABLE = False
    print("warning: comfort_navigator not available")

try:
    from shade_router import ShadeRouter
    SHADE_ROUTER_AVAILABLE = True
except ImportError as _e:
    ShadeRouter = None
    SHADE_ROUTER_AVAILABLE = False
    print(f"Warning: ShadeRouter not available ({_e}). "
          "Install: pip install networkx")

# weather api configuration
import requests
import os
import sqlite3
import uuid

# open-meteo official sdk with caching and retry
try:
    import openmeteo_requests
    import requests_cache
    from retry_requests import retry
    WEATHER_API_AVAILABLE = True

    # setup open-meteo client with cache and retry
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo = openmeteo_requests.Client(session=retry_session)
except ImportError:
    WEATHER_API_AVAILABLE = False
    openmeteo = None
    print("Warning: openmeteo-requests not available. Install with: pip install openmeteo-requests requests-cache retry-requests")

# database module for PostgreSQL/SQLite
from database import (
    init_database, seed_dummy_data,
    create_task, get_task, get_all_tasks, get_today_tasks, update_task, delete_task,
    create_accepted_recommendation, get_recommendation_by_task, mark_task_completed,
    get_analytics, get_analytics_range, update_analytics_for_month, get_dashboard_summary,
    create_user, get_user_by_email, get_user_by_id, authenticate_user, update_user,
    create_saved_place, get_saved_places, delete_saved_place,
    hash_password,
    UserTask, AcceptedRecommendation, User, SavedPlace
)

# legacy sqlite path for backward compatibility
DB_PATH = os.path.join(os.path.dirname(__file__), "smartshift.db")

def init_db():
    """initialize database tables - now using new database module."""
    init_database()
    seed_dummy_data()


# flask app initialization

app = Flask(__name__, static_folder='.')
CORS(app, origins=API.CORS_ORIGINS)

# Initialize calculators
solar_calculator = SolarPositionCalculator(
    latitude=DUBAI.LATITUDE,
    longitude=DUBAI.LONGITUDE,
    timezone_offset=DUBAI.TIMEZONE_OFFSET
)

shadow_calculator = ShadowCalculator(
    latitude=DUBAI.LATITUDE,
    longitude=DUBAI.LONGITUDE,
    timezone_offset=DUBAI.TIMEZONE_OFFSET
)

# initialize sqlite database for schedule feedback
init_db()

# initialize ml models (lazy loading - trained on first use)
heat_risk_model = None
shade_navigator = None
NEW_ARCH_AVAILABLE = CORE_MODEL_AVAILABLE or SHADOW_SCHEDULER_AVAILABLE or COMFORT_NAVIGATOR_AVAILABLE

def get_heat_risk_model():
    """lazy load and train heat risk model on first use."""
    global heat_risk_model
    if heat_risk_model is None and ML_MODELS_AVAILABLE:
        print("initializing heat risk model...")
        heat_risk_model = HeatRiskModel()
        if not heat_risk_model.is_trained:
            heat_risk_model.train(n_samples=5000, verbose=False)
    return heat_risk_model

def get_shade_navigator():
    """lazy load shade navigator on first use."""
    global shade_navigator
    if shade_navigator is None and NAVIGATOR_AVAILABLE and ShadeNavigator:
        print("initializing shade navigator...")
        shade_navigator = ShadeNavigator()
    return shade_navigator


def get_comfort_navigator_v2(mapbox_token: str):
    """Get comfort navigator with mapbox token for /api/v2/route."""
    if not COMFORT_NAVIGATOR_AVAILABLE or not ComfortNavigator:
        return None
    return ComfortNavigator(
        mapbox_token=mapbox_token,
        sample_interval_meters=15.0
    )


# helper functions

def parse_datetime_param(date_str: Optional[str], time_str: Optional[str]) -> datetime:
    """
    Parse date and time from request parameters.

    Args:
        date_str: Date in YYYY-MM-DD format (optional)
        time_str: Time in HH:MM format (optional)

    Returns:
        Datetime object (defaults to current time if not provided)
    """
    now = datetime.now()

    if date_str:
        try:
            year, month, day = map(int, date_str.split('-'))
            now = now.replace(year=year, month=month, day=day)
        except (ValueError, AttributeError):
            pass  # Use current date

    if time_str:
        try:
            hour, minute = map(int, time_str.split(':'))
            now = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, AttributeError):
            pass  # Use current time

    return now


def _get_heat_risk_level_for_location(lat: float, lon: float, dt: datetime) -> str:
    """
    Get heat risk label from the heat_risk_model for a location and time.
    Returns "low" | "medium" | "high". Falls back to "low" if model unavailable.
    """
    if not ML_MODELS_AVAILABLE or not WEATHER_API_AVAILABLE:
        return "low"
    try:
        forecast = fetch_7day_forecast(lat, lon)
        target_date_str = dt.strftime("%Y-%m-%d")
        hour = dt.hour
        weather_data_from_api = None
        for hourly in forecast["hourly"]:
            if hourly["date"] == target_date_str and hourly["hour"] == hour:
                weather_data_from_api = hourly
                break
        if weather_data_from_api:
            temperature = weather_data_from_api["temperature"]
            humidity = weather_data_from_api["humidity"]
            wind_speed = weather_data_from_api["wind_speed"]
            uv_index = weather_data_from_api["uv_index"]
            cloud_cover = weather_data_from_api.get("cloud_cover", 0)
        else:
            temperature, humidity, wind_speed, uv_index, cloud_cover = 32.0, 50.0, 10.0, 5.0, 20
        sun_pos = solar_calculator.get_sun_position(dt)
        sun_intensity = min(1.0, sun_pos.altitude / 60) if sun_pos.altitude > 0 else 0.0
        weather = WeatherData(
            temperature=temperature, humidity=humidity, wind_speed=wind_speed,
            uv_index=uv_index, cloud_cover=cloud_cover
        )
        location = LocationContext(latitude=lat, longitude=lon, surface_type="mixed", urban_density=0.7)
        sun_exposure = SunExposure(
            is_in_shadow=False,
            current_sun_altitude=max(0, sun_pos.altitude),
            current_sun_azimuth=sun_pos.azimuth,
            minutes_in_sun_last_hour=30.0,
            direct_sun_intensity=sun_intensity,
        )
        model = get_heat_risk_model()
        prediction = model.predict(weather, location, sun_exposure, dt)
        level = int(prediction.risk_level)
        if level == 0:
            return "low"
        if level == 1:
            return "medium"
        return "high"
    except Exception:
        return "low"


def sun_position_to_dict(pos: SunPosition) -> Dict[str, Any]:
    """
    Convert SunPosition object to JSON-serializable dictionary.

    Args:
        pos: SunPosition object

    Returns:
        Dictionary with sun position data
    """
    return {
        "azimuth": round(pos.azimuth, 2),
        "altitude": round(pos.altitude, 2),
        "zenith": round(pos.zenith, 2),
        "is_daylight": pos.is_daylight,
        "sunrise": pos.sunrise.strftime("%H:%M") if pos.sunrise else None,
        "sunset": pos.sunset.strftime("%H:%M") if pos.sunset else None,
        "solar_noon": pos.solar_noon.strftime("%H:%M") if pos.solar_noon else None
    }


def load_buildings() -> List[Building]:
    """
    Load building data from configuration.

    Returns:
        List of Building objects
    """
    buildings = []
    for bldg_data in SAMPLE_BUILDINGS:
        building = Building(
            id=bldg_data["id"],
            name=bldg_data.get("name"),
            height=bldg_data["height"],
            footprint=[(pt[0], pt[1]) for pt in bldg_data["footprint"]]
        )
        buildings.append(building)
    return buildings


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/v2/health', methods=['GET'])
def health_check_v2():
    """Health check for v2 API."""
    return jsonify({
        "status": "healthy",
        "version": "2.0",
        "architecture": "unified_space_time_model",
        "new_arch_available": NEW_ARCH_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/v2/comfort-score', methods=['POST'])
def compute_comfort_v2():
    if not CORE_MODEL_AVAILABLE:
        return jsonify({"error": "core_model not available"}), 500
    try:
        data = request.get_json()
        shadow_ratio = float(data.get('shadow_ratio', 0))
        heat_risk_score = float(data.get('heat_risk_score', 0))

        weights = None
        if 'shadow_weight' in data and 'heat_weight' in data:
            weights = ComfortWeights(
                shadow_weight=float(data['shadow_weight']),
                heat_weight=float(data['heat_weight'])
            )
        comfort = compute_comfort_score(shadow_ratio, heat_risk_score, weights)
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


@app.route('/api/v2/schedule', methods=['POST'])
def find_optimal_schedule_v2():
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json()
        task_name = data.get('task_name', 'outdoor task')
        task_duration = int(data.get('task_duration_minutes', 60))
        zone_data = data.get('work_zone', {})
        lat = float(zone_data.get('lat', 25.2048))
        lon = float(zone_data.get('lon', 55.2708))
        location_name = zone_data.get('name', 'work area')
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 9))
        end_hour = int(data.get('end_hour', 17))
        recommendation_count = int(data.get('recommendation_count', 5))
        building_face = data.get('building_face')
        if data.get('area_polygon'):
            points = data['area_polygon']
            lat = sum(p[0] for p in points) / len(points)
            lon = sum(p[1] for p in points) / len(points)

        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
        recommendation = scheduler.find_optimal_schedule(
            task_name=task_name,
            lat=lat,
            lon=lon,
            location_name=location_name,
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            building_face=building_face,
            recommendation_count=recommendation_count
        )
        return jsonify({
            "success": True,
            "mode": "shadow_only",
            "recommendation": recommendation.to_dict()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@app.route('/api/v2/schedule/area', methods=['POST'])
def schedule_for_area_v2():
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json()
        task_name = data.get('task_name', 'area task')
        polygon_points = data.get('polygon_points', [])
        if not polygon_points or len(polygon_points) < 3:
            return jsonify({"success": False, "error": "polygon_points requires at least 3 vertices"}), 400
        location_name = data.get('location_name', task_name)
        task_duration = int(data.get('task_duration_minutes', 60))
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 5))
        end_hour = int(data.get('end_hour', 20))
        recommendation_count = int(data.get('recommendation_count', 5))
        polygon_tuples = [(float(p[0]), float(p[1])) for p in polygon_points]
        raw_buildings = data.get('buildings')
        client_buildings = parse_client_buildings(raw_buildings) if raw_buildings else None

        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
        recommendation = scheduler.find_optimal_schedule_for_area(
            task_name=task_name,
            polygon_points=polygon_tuples,
            location_name=location_name,
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            recommendation_count=recommendation_count,
            client_buildings=client_buildings
        )
        grid_pts = scheduler._sample_polygon_grid(polygon_tuples)
        return jsonify({
            "success": True,
            "mode": "area_grid",
            "building_source": "client_map_tiles" if client_buildings else "tilequery_api",
            "buildings_used": recommendation.buildings_used,
            "grid_samples": len(grid_pts),
            "recommendation": recommendation.to_dict()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@app.route('/api/v2/route', methods=['POST'])
def find_comfortable_route_v2():
    if not COMFORT_NAVIGATOR_AVAILABLE or not ComfortNavigator:
        return jsonify({"error": "comfort navigator not available"}), 500
    try:
        data = request.get_json()
        start = data.get('start', {})
        end = data.get('end', {})
        start_lat = float(start.get('lat'))
        start_lon = float(start.get('lon'))
        end_lat = float(end.get('lat'))
        end_lon = float(end.get('lon'))
        mode = data.get('mode', 'walking').lower()
        if mode not in ['walking', 'cycling']:
            mode = 'walking'
        departure_str = data.get('departure_time')
        departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00')) if departure_str else datetime.now()
        mapbox_token = data.get('mapbox_token')
        if not mapbox_token:
            return jsonify({"error": "mapbox_token required"}), 400
        alternatives = int(data.get('alternatives', 3))
        navigator = get_comfort_navigator_v2(mapbox_token)
        if not navigator:
            return jsonify({"error": "navigator not available"}), 500
        recommendation = navigator.find_comfortable_route(
            start_lat=start_lat, start_lon=start_lon,
            end_lat=end_lat, end_lon=end_lon,
            mode=mode, departure_time=departure_time, alternatives=alternatives
        )
        return jsonify({"success": True, "recommendation": recommendation.to_dict()})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@app.route('/api/v2/heatmap', methods=['POST'])
def generate_heatmap_v2():
    if not CORE_MODEL_AVAILABLE:
        return jsonify({"error": "core_model not available"}), 500
    try:
        data = request.get_json()
        bbox = data.get('bbox', {})
        min_lat = float(bbox.get('min_lat', 25.19))
        max_lat = float(bbox.get('max_lat', 25.21))
        min_lon = float(bbox.get('min_lon', 55.26))
        max_lon = float(bbox.get('max_lon', 55.28))
        grid_size = float(data.get('grid_size_meters', 25))
        time_str = data.get('time')
        timestamp = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else datetime.now()

        dataset = SpaceTimeDataset(spatial_resolution_type=SpatialResolution.HEATMAP_GRID)
        lat_step = grid_size / 111000
        lon_step = grid_size / (111000 * 0.9)
        lat = min_lat
        while lat <= max_lat:
            lon = min_lon
            while lon <= max_lon:
                shadow_ratio = 0.4 + 0.3 * ((lat - min_lat) / (max_lat - min_lat))
                heat_risk_score = 0.3 + 0.4 * ((lon - min_lon) / (max_lon - min_lon))
                comfort = compute_comfort_score(shadow_ratio, heat_risk_score)
                cell = SpaceTimeCell(
                    lat=lat, lon=lon, timestamp=timestamp, shadow_ratio=shadow_ratio,
                    heat_risk_class=HeatRiskClass.MEDIUM, heat_risk_score=heat_risk_score,
                    comfort_score=comfort
                )
                dataset.add_cell(cell)
                lon += lon_step
            lat += lat_step
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


@app.route('/api/v2/work-zones', methods=['GET', 'POST'])
def manage_work_zones_v2():
    if request.method == 'POST':
        if not CORE_MODEL_AVAILABLE:
            return jsonify({"success": False, "error": "core_model not available"}), 500
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
    return jsonify({"success": True, "zones": sample_zones})


@app.route('/api/v2/shadow-schedule', methods=['POST'])
def shadow_schedule_v2():
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json()
        task_name = data.get('task_name', 'outdoor task')
        lat = float(data.get('lat', 25.2048))
        lon = float(data.get('lon', 55.2708))
        location_name = data.get('location_name', 'Dubai')
        duration_minutes = int(data.get('duration_minutes', 60))
        date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')
        start_hour = int(data.get('start_hour', 5))
        end_hour = int(data.get('end_hour', 20))
        building_face = data.get('building_face')
        face_angle_raw = data.get('face_angle')
        face_angle = None
        if face_angle_raw is not None:
            try:
                a = float(face_angle_raw)
                face_angle = max(0.0, min(360.0, a % 360.0)) if a == a else None
            except (TypeError, ValueError):
                pass
        if face_angle is None and building_face in ("N", "E", "S", "W"):
            face_angle = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}[building_face]
        recommendation_count = int(data.get('recommendation_count', 5))
        raw_buildings = data.get('buildings')
        client_buildings = parse_client_buildings(raw_buildings) if raw_buildings else None
        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
        recommendation = scheduler.find_optimal_schedule(
            task_name=task_name, lat=lat, lon=lon, location_name=location_name,
            task_duration_minutes=duration_minutes, date=date,
            start_hour=start_hour, end_hour=end_hour,
            building_face=building_face, face_angle=face_angle,
            recommendation_count=recommendation_count, client_buildings=client_buildings
        )
        include_all_slots = bool(data.get("include_all_slots", False))
        return jsonify({
            "success": True,
            "mode": "shadow_only",
            "building_source": "client_map_tiles" if client_buildings else "tilequery_api",
            "buildings_used": recommendation.buildings_used,
            "recommendation": recommendation.to_dict(include_all_slots=include_all_slots),
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@app.route('/api/v2/facade-recommend-time', methods=['POST'])
def facade_recommend_time_v2():
    if not SHADOW_SCHEDULER_AVAILABLE:
        return jsonify({"success": False, "error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json() or {}
        lat = float(data.get("lat", 25.2048))
        lon = float(data.get("lon", 55.2708))
        date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        date = datetime.strptime(date_str, "%Y-%m-%d")
        duration_minutes = int(data.get("duration_minutes", 60))
        start_time = data.get("start_time")
        if start_time and isinstance(start_time, str) and ":" in start_time:
            parts = start_time.strip().split(":")
            start_hour = int(parts[0])
            start_minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            start_hour = int(data.get("start_hour", 9))
            start_minute = int(data.get("start_minute", 0))
        if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
            return jsonify({"success": False, "error": "Invalid start time"}), 400
        raw_buildings = data.get("buildings")
        client_buildings = parse_client_buildings(raw_buildings) if raw_buildings else None
        result = recommend_facades_for_fixed_window(
            lat=lat, lon=lon, date=date,
            start_hour=start_hour, start_minute=start_minute,
            duration_minutes=duration_minutes, buildings=client_buildings,
        )
        return jsonify({"success": True, **result})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 400


@app.route('/api/v2/debug/shadow-polygons', methods=['POST'])
def debug_shadow_polygons_v2():
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json()
        lat = float(data.get('lat', 25.2048))
        lon = float(data.get('lon', 55.2708))
        time_str = data.get('time')
        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else datetime.now()
        raw_buildings = data.get('buildings')
        scheduler = ShadowScheduler()
        if raw_buildings:
            buildings = parse_client_buildings(raw_buildings)
            building_source = "client_map_tiles"
        else:
            buildings = scheduler._fetch_nearby_buildings(lat, lon)
            building_source = "tilequery_api"
        client_az = data.get('sun_azimuth')
        client_alt = data.get('sun_altitude')
        if client_az is not None and client_alt is not None:
            sun = SunPosition(
                azimuth=float(client_az),
                altitude=float(client_alt),
                zenith=90.0 - float(client_alt),
                is_daylight=float(client_alt) > 0,
            )
        else:
            sun = scheduler._get_sun_position(dt, lat, lon)
        mapbox_light_dir = data.get('mapbox_light_direction')
        shadow_direction_override = float(mapbox_light_dir) if mapbox_light_dir is not None else None
        from shadow_calculator import ShadowCalculator
        from config import DUBAI
        calc = ShadowCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET
        )
        shadow_features = []
        footprint_features = []
        shadow_length_m = calc.calculate_shadow_length(30.0, sun.altitude) if sun.altitude > 0 else 0
        shadow_dir = (shadow_direction_override if shadow_direction_override is not None
                      else calc.calculate_shadow_direction(sun.azimuth)) if sun.altitude > 0 else 0
        for b in buildings:
            fp_ring = [[p[0], p[1]] for p in b.footprint]
            if fp_ring and fp_ring[0] != fp_ring[-1]:
                fp_ring.append(fp_ring[0])
            footprint_features.append({
                "type": "Feature",
                "properties": {
                    "building_id": b.id, "height": b.height,
                    "name": b.name or "unknown", "layer": "footprint",
                },
                "geometry": {"type": "Polygon", "coordinates": [fp_ring]}
            })
            polygon = calc.calculate_shadow_polygon(b, sun, shadow_direction_override)
            if polygon:
                ring = [[p[0], p[1]] for p in polygon]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                shadow_features.append({
                    "type": "Feature",
                    "properties": {
                        "building_id": b.id, "height": b.height,
                        "name": b.name or "unknown", "layer": "shadow",
                    },
                    "geometry": {"type": "Polygon", "coordinates": [ring]}
                })
        from shadow_scheduler import _point_in_polygon
        target_in_shadow = any(
            calc.calculate_shadow_polygon(b, sun, shadow_direction_override) and
            _point_in_polygon(lon, lat, calc.calculate_shadow_polygon(b, sun, shadow_direction_override))
            for b in buildings
        )
        heights = [b.height for b in buildings]
        height_stats = {
            "min": round(min(heights), 1) if heights else 0,
            "max": round(max(heights), 1) if heights else 0,
            "avg": round(sum(heights) / len(heights), 1) if heights else 0,
        }
        return jsonify({
            "success": True,
            "time": dt.isoformat(),
            "building_source": building_source,
            "sun": {
                "azimuth": round(sun.azimuth, 2),
                "altitude": round(sun.altitude, 2),
                "is_daylight": sun.is_daylight,
                "shadow_length_30m": round(shadow_length_m, 1),
                "shadow_direction": round(shadow_dir, 1),
            },
            "target": {"lat": lat, "lon": lon, "in_shadow": target_in_shadow},
            "buildings_found": len(buildings),
            "height_stats": height_stats,
            "shadow_polygons_count": len(shadow_features),
            "shadow_geojson": {"type": "FeatureCollection", "features": shadow_features},
            "footprint_geojson": {"type": "FeatureCollection", "features": footprint_features}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 400


@app.route('/api/v2/sun-position', methods=['GET'])
def get_sun_position_v2():
    try:
        lat = float(request.args.get('lat', 25.2048))
        lon = float(request.args.get('lon', 55.2708))
        time_str = request.args.get('time')
        building_face = request.args.get('face')
        face_angle_raw = request.args.get('face_angle')
        face_angle = None
        if face_angle_raw is not None:
            try:
                a = float(face_angle_raw)
                face_angle = max(0.0, min(360.0, a % 360.0)) if a == a else None
            except (TypeError, ValueError):
                pass
        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00')) if time_str else datetime.now()
        if not SHADOW_SCHEDULER_AVAILABLE:
            return jsonify({"success": False, "error": "shadow_scheduler not available"}), 500
        result = calculate_shadow_at_time(lat, lon, dt, building_face, face_angle)
        return jsonify({
            "success": True,
            "location": {"lat": lat, "lon": lon},
            "time": dt.isoformat(),
            "building_face": building_face,
            "face_angle": face_angle,
            **result
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/feedback', methods=['POST'])
def submit_feedback_v2():
    try:
        request.get_json()
        return jsonify({
            "success": True,
            "message": "feedback received",
            "updated_weights": {"shadow_weight": 1.0, "heat_weight": 0.0}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/')
def index():
    """
    Serve the main HTML page.

    Redirects to the shadow simulation viewer.
    """
    return send_from_directory('.', 'dubai_shadow_simulation.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.

    Returns:
        JSON with server status and version
    """
    return jsonify({
        "status": "healthy",
        "version": API.VERSION,
        "timestamp": datetime.now().isoformat(),
        "location": {
            "city": "Dubai",
            "latitude": DUBAI.LATITUDE,
            "longitude": DUBAI.LONGITUDE,
            "timezone": f"UTC+{DUBAI.TIMEZONE_OFFSET}"
        }
    })


@app.route('/api/sun-position', methods=['GET'])
def get_sun_position():
    """
    Get current or specified sun position.

    Query Parameters:
        date: Date in YYYY-MM-DD format (optional)
        time: Time in HH:MM format (optional)

    Returns:
        JSON with sun position data including azimuth, altitude,
        sunrise, sunset, and solar noon times
    """
    # Parse request parameters
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    dt = parse_datetime_param(date_str, time_str)

    # Calculate sun position
    position = solar_calculator.get_sun_position(dt)

    return jsonify({
        "success": True,
        "timestamp": dt.isoformat(),
        "sun": sun_position_to_dict(position),
        "light_preset": _get_light_preset(position)
    })


@app.route('/api/shadows', methods=['GET'])
def get_shadows():
    """
    Get shadow data for all buildings at current or specified time.

    Query Parameters:
        date: Date in YYYY-MM-DD format (optional)
        time: Time in HH:MM format (optional)

    Returns:
        JSON with GeoJSON shadow polygons and sun position data
    """
    # Parse request parameters
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    dt = parse_datetime_param(date_str, time_str)

    # Load buildings and calculate shadows
    buildings = load_buildings()
    analysis = shadow_calculator.calculate_shadows_for_buildings(buildings, dt)

    # Convert to response format
    shadows_geojson = shadow_calculator.shadows_to_geojson(analysis.shadows)

    return jsonify({
        "success": True,
        "timestamp": dt.isoformat(),
        "sun": sun_position_to_dict(analysis.sun_position),
        "shadows": shadows_geojson,
        "summary": {
            "building_count": len(buildings),
            "shadow_count": len(analysis.shadows),
            "light_preset": _get_light_preset(analysis.sun_position)
        }
    })


@app.route('/api/animation', methods=['GET'])
def get_animation_frames():
    """
    Get shadow animation frames for an entire day.

    Query Parameters:
        date: Date in YYYY-MM-DD format (optional, defaults to today)
        start_hour: Starting hour 0-23 (optional, default 6)
        end_hour: Ending hour 0-23 (optional, default 20)
        interval: Minutes between frames (optional, default 30)

    Returns:
        JSON with array of shadow frames for animation
    """
    # Parse request parameters
    date_str = request.args.get('date')
    dt = parse_datetime_param(date_str, None)

    start_hour = int(request.args.get('start_hour', SHADOW.DEFAULT_ANIMATION_START_HOUR))
    end_hour = int(request.args.get('end_hour', SHADOW.DEFAULT_ANIMATION_END_HOUR))
    interval = int(request.args.get('interval', SHADOW.DEFAULT_ANIMATION_INTERVAL_MINUTES))

    # Validate parameters
    start_hour = max(0, min(23, start_hour))
    end_hour = max(start_hour + 1, min(24, end_hour))
    interval = max(5, min(120, interval))

    # Load buildings and calculate animation frames
    buildings = load_buildings()
    frames = shadow_calculator.calculate_shadow_animation_frames(
        buildings=buildings,
        date=dt,
        start_hour=start_hour,
        end_hour=end_hour,
        interval_minutes=interval
    )

    # Convert frames to response format
    animation_data = []
    for frame in frames:
        animation_data.append({
            "time": frame.timestamp.strftime("%H:%M"),
            "timestamp": frame.timestamp.isoformat(),
            "sun": sun_position_to_dict(frame.sun_position),
            "shadows": shadow_calculator.shadows_to_geojson(frame.shadows),
            "light_preset": _get_light_preset(frame.sun_position)
        })

    return jsonify({
        "success": True,
        "date": dt.strftime("%Y-%m-%d"),
        "frame_count": len(animation_data),
        "interval_minutes": interval,
        "frames": animation_data
    })


@app.route('/api/sun-path', methods=['GET'])
def get_sun_path():
    """
    Get sun path data for visualization (arc across the sky).

    Query Parameters:
        date: Date in YYYY-MM-DD format (optional)
        interval: Minutes between points (optional, default 15)

    Returns:
        JSON with sun positions throughout the day for path visualization
    """
    # Parse request parameters
    date_str = request.args.get('date')
    dt = parse_datetime_param(date_str, None)
    interval = int(request.args.get('interval', 15))

    # Calculate sun positions for daylight hours
    positions = solar_calculator.get_positions_for_day(dt, interval_minutes=interval)

    # Filter to daylight hours and format
    sun_path = []
    for time_key, pos in sorted(positions.items()):
        if pos.is_daylight:
            sun_path.append({
                "time": time_key,
                "azimuth": round(pos.azimuth, 2),
                "altitude": round(pos.altitude, 2)
            })

    # Get sunrise/sunset for reference
    first_pos = list(positions.values())[0] if positions else None

    return jsonify({
        "success": True,
        "date": dt.strftime("%Y-%m-%d"),
        "sunrise": first_pos.sunrise.strftime("%H:%M") if first_pos and first_pos.sunrise else None,
        "sunset": first_pos.sunset.strftime("%H:%M") if first_pos and first_pos.sunset else None,
        "solar_noon": first_pos.solar_noon.strftime("%H:%M") if first_pos and first_pos.solar_noon else None,
        "path": sun_path
    })


@app.route('/api/buildings', methods=['GET'])
def get_buildings():
    """
    Get list of available buildings with their data.

    Returns:
        JSON with building list including heights and footprints
    """
    buildings = []
    for bldg in SAMPLE_BUILDINGS:
        buildings.append({
            "id": bldg["id"],
            "name": bldg.get("name", bldg["id"]),
            "height": bldg["height"],
            "footprint": bldg["footprint"],
            "centroid": _calculate_centroid(bldg["footprint"])
        })

    return jsonify({
        "success": True,
        "count": len(buildings),
        "buildings": buildings
    })


@app.route('/api/locations', methods=['GET'])
def get_locations():
    """
    Get list of available landmark locations for map navigation.

    Returns:
        JSON with landmark locations and camera configurations
    """
    locations = []
    for key, loc in LANDMARK_LOCATIONS.items():
        locations.append({
            "id": key,
            "name": loc["name"],
            "description": loc.get("description", ""),
            "center": loc["center"],
            "zoom": loc["zoom"],
            "pitch": loc["pitch"],
            "bearing": loc["bearing"]
        })

    return jsonify({
        "success": True,
        "count": len(locations),
        "locations": locations
    })


@app.route('/api/shadow-at-point', methods=['GET'])
def get_shadow_at_point():
    """
    Check if a specific point is in shadow at a given time.

    Query Parameters:
        lat: Latitude of the point
        lon: Longitude of the point
        date: Date in YYYY-MM-DD format (optional)
        time: Time in HH:MM format (optional)

    Returns:
        JSON with shadow status for the specified point
    """
    # Parse required parameters
    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "lat and lon parameters are required and must be numbers"
        }), 400

    # Parse time parameters
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    dt = parse_datetime_param(date_str, time_str)

    # Get sun position
    position = solar_calculator.get_sun_position(dt)

    # Note: Full point-in-shadow calculation would require ray casting
    # This is a simplified response indicating sun conditions
    return jsonify({
        "success": True,
        "point": {"lat": lat, "lon": lon},
        "timestamp": dt.isoformat(),
        "sun": sun_position_to_dict(position),
        "note": "Full shadow intersection requires 3D building data"
    })


# global cache for 7-day hourly forecast
weather_forecast_cache = {
    "data": None,
    "fetched_at": None,
    "lat": None,
    "lon": None
}

def fetch_7day_forecast(lat, lon):
    """
    fetch 7-day hourly forecast from open-meteo.
    caches the result to avoid repeated api calls.
    """
    global weather_forecast_cache

    # check if we have cached data for this location (cache for 30 minutes)
    now = datetime.now()
    if (weather_forecast_cache["data"] is not None and
        weather_forecast_cache["fetched_at"] is not None and
        weather_forecast_cache["lat"] == lat and
        weather_forecast_cache["lon"] == lon and
        (now - weather_forecast_cache["fetched_at"]).total_seconds() < 1800):
        return weather_forecast_cache["data"]

    # open-meteo api parameters for 7-day hourly forecast
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": [
            "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
            "wind_direction_10m", "cloud_cover", "uv_index", "is_day",
            "wet_bulb_temperature_2m", "apparent_temperature", "precipitation"
        ],
        "daily": [
            "temperature_2m_max", "temperature_2m_min", "sunrise", "sunset",
            "uv_index_max"
        ],
        "timezone": "auto",
        "forecast_days": 7
    }

    # fetch using sdk
    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    # extract hourly data
    hourly = response.Hourly()

    # get numpy arrays and convert to python lists
    hourly_temp = hourly.Variables(0).ValuesAsNumpy().tolist()
    hourly_humidity = hourly.Variables(1).ValuesAsNumpy().tolist()
    hourly_wind_speed = hourly.Variables(2).ValuesAsNumpy().tolist()
    hourly_wind_dir = hourly.Variables(3).ValuesAsNumpy().tolist()
    hourly_cloud = hourly.Variables(4).ValuesAsNumpy().tolist()
    hourly_uv = hourly.Variables(5).ValuesAsNumpy().tolist()
    hourly_is_day = hourly.Variables(6).ValuesAsNumpy().tolist()
    hourly_wet_bulb = hourly.Variables(7).ValuesAsNumpy().tolist()
    hourly_feels_like = hourly.Variables(8).ValuesAsNumpy().tolist()
    hourly_precip = hourly.Variables(9).ValuesAsNumpy().tolist()

    # build hourly data with timestamps
    utc_offset = response.UtcOffsetSeconds()
    start_time = hourly.Time() + utc_offset
    interval = hourly.Interval()

    hourly_data = []
    for i in range(len(hourly_temp)):
        timestamp = start_time + (i * interval)
        dt = datetime.utcfromtimestamp(timestamp)
        hourly_data.append({
            "datetime": dt.isoformat(),
            "date": dt.strftime("%Y-%m-%d"),
            "hour": dt.hour,
            "day_offset": (dt.date() - datetime.utcnow().date()).days,
            "temperature": round(hourly_temp[i], 1) if hourly_temp[i] == hourly_temp[i] else 25.0,
            "humidity": round(hourly_humidity[i], 1) if hourly_humidity[i] == hourly_humidity[i] else 50.0,
            "wind_speed": round(hourly_wind_speed[i], 1) if hourly_wind_speed[i] == hourly_wind_speed[i] else 10.0,
            "wind_direction": round(hourly_wind_dir[i], 0) if hourly_wind_dir[i] == hourly_wind_dir[i] else 180,
            "cloud_cover": round(hourly_cloud[i], 0) if hourly_cloud[i] == hourly_cloud[i] else 20,
            "uv_index": round(hourly_uv[i], 1) if hourly_uv[i] == hourly_uv[i] else 0,
            "is_day": bool(hourly_is_day[i]) if hourly_is_day[i] == hourly_is_day[i] else True,
            "wet_bulb_temperature": round(hourly_wet_bulb[i], 1) if hourly_wet_bulb[i] == hourly_wet_bulb[i] else 20.0,
            "apparent_temperature": round(hourly_feels_like[i], 1) if hourly_feels_like[i] == hourly_feels_like[i] else 25.0,
            "precipitation": round(hourly_precip[i], 2) if hourly_precip[i] == hourly_precip[i] else 0.0
        })

    # extract daily data
    daily = response.Daily()
    daily_max = daily.Variables(0).ValuesAsNumpy().tolist()
    daily_min = daily.Variables(1).ValuesAsNumpy().tolist()
    daily_sunrise = daily.Variables(2).ValuesInt64AsNumpy().tolist()
    daily_sunset = daily.Variables(3).ValuesInt64AsNumpy().tolist()
    daily_uv_max = daily.Variables(4).ValuesAsNumpy().tolist()

    daily_start = daily.Time() + utc_offset
    daily_interval = daily.Interval()

    daily_data = []
    for i in range(len(daily_max)):
        timestamp = daily_start + (i * daily_interval)
        dt = datetime.utcfromtimestamp(timestamp)
        daily_data.append({
            "date": dt.strftime("%Y-%m-%d"),
            "day_offset": i,
            "temp_max": round(daily_max[i], 1) if daily_max[i] == daily_max[i] else 35.0,
            "temp_min": round(daily_min[i], 1) if daily_min[i] == daily_min[i] else 20.0,
            "sunrise": datetime.utcfromtimestamp(daily_sunrise[i] + utc_offset).strftime("%H:%M") if daily_sunrise[i] else "06:00",
            "sunset": datetime.utcfromtimestamp(daily_sunset[i] + utc_offset).strftime("%H:%M") if daily_sunset[i] else "18:00",
            "uv_index_max": round(daily_uv_max[i], 1) if daily_uv_max[i] == daily_uv_max[i] else 10.0
        })

    forecast_data = {
        "location": {
            "latitude": float(response.Latitude()),
            "longitude": float(response.Longitude()),
            "elevation": float(response.Elevation()),
            "timezone": response.Timezone().decode() if isinstance(response.Timezone(), bytes) else str(response.Timezone())
        },
        "hourly": hourly_data,
        "daily": daily_data
    }

    # cache the result
    weather_forecast_cache["data"] = forecast_data
    weather_forecast_cache["fetched_at"] = now
    weather_forecast_cache["lat"] = lat
    weather_forecast_cache["lon"] = lon

    return forecast_data


@app.route('/api/weather/forecast', methods=['GET'])
def get_weather_forecast():
    """
    get 7-day hourly weather forecast from open-meteo.

    this endpoint returns comprehensive hourly data for the next 7 days,
    which the frontend caches and uses to update weather as the time slider moves.

    query parameters:
        lat: latitude (optional, defaults to dubai)
        lon: longitude (optional, defaults to dubai)

    returns:
        json with hourly and daily forecast data for 7 days
    """
    if not WEATHER_API_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "open-meteo sdk not available"
        }), 503

    try:
        lat = float(request.args.get('lat', DUBAI.LATITUDE))
        lon = float(request.args.get('lon', DUBAI.LONGITUDE))

        forecast = fetch_7day_forecast(lat, lon)

        return jsonify({
            "success": True,
            "source": "open-meteo",
            **forecast
        })

    except Exception as e:
        print(f"forecast api error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/weather', methods=['GET'])
def get_weather():
    """
    get weather data for a specific date and hour using 7-day forecast.

    uses cached 7-day forecast data to return weather for any hour
    within the next 7 days.

    query parameters:
        date: date in yyyy-mm-dd format (optional, defaults to today)
        hour: hour 0-23 (optional, defaults to current hour)
        lat: latitude (optional, defaults to dubai)
        lon: longitude (optional, defaults to dubai)

    returns:
        json with weather data for the specified time
    """
    if not WEATHER_API_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "open-meteo sdk not available"
        }), 503

    try:
        # parse request parameters
        lat = float(request.args.get('lat', DUBAI.LATITUDE))
        lon = float(request.args.get('lon', DUBAI.LONGITUDE))
        date_str = request.args.get('date')
        hour = request.args.get('hour', type=int)

        # determine target datetime
        now = datetime.now()
        if date_str:
            try:
                year, month, day = map(int, date_str.split('-'))
                target_date = datetime(year, month, day).date()
            except (ValueError, AttributeError):
                target_date = now.date()
        else:
            target_date = now.date()

        if hour is None:
            hour = now.hour

        # fetch 7-day forecast
        forecast = fetch_7day_forecast(lat, lon)

        # find matching hour in forecast
        target_date_str = target_date.strftime("%Y-%m-%d")
        weather_at_time = None

        for hourly in forecast["hourly"]:
            if hourly["date"] == target_date_str and hourly["hour"] == hour:
                weather_at_time = hourly
                break

        if weather_at_time:
            return jsonify({
                "success": True,
                "timestamp": weather_at_time["datetime"],
                "source": "open-meteo",
                "temperature": weather_at_time["temperature"],
                "humidity": weather_at_time["humidity"],
                "pressure": 1013.0,  # open-meteo doesn't include in hourly
                "wind_speed": weather_at_time["wind_speed"],
                "wind_direction": weather_at_time["wind_direction"],
                "cloud_cover": weather_at_time["cloud_cover"],
                "apparent_temperature": weather_at_time["apparent_temperature"],
                "precipitation": weather_at_time["precipitation"],
                "uv_index": weather_at_time["uv_index"],
                "is_day": weather_at_time["is_day"],
                "wet_bulb_temperature": weather_at_time["wet_bulb_temperature"]
            })
        else:
            # date/hour not in forecast range - return closest match
            return jsonify({
                "success": True,
                "timestamp": f"{target_date_str}T{hour:02d}:00:00",
                "source": "open-meteo",
                "temperature": forecast["hourly"][0]["temperature"] if forecast["hourly"] else 25.0,
                "humidity": forecast["hourly"][0]["humidity"] if forecast["hourly"] else 50.0,
                "note": "requested time outside 7-day forecast range, using current"
            })

    except Exception as e:
        print(f"weather api error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =============================================================================
# ML-POWERED ENDPOINTS (HEAT RISK & SCHEDULE OPTIMIZATION)
# =============================================================================

@app.route('/api/heat-risk', methods=['GET', 'POST'])
def get_heat_risk():
    """
    predict heat risk for a specific location and time.

    answers the question: "is it safe to be outside right now?"

    target users:
    - community workers (facade cleaners, construction, road maintenance)
    - joggers, cyclists, pedestrians seeking low-heat routes

    automatically fetches real weather data from open-meteo for accurate predictions.

    query parameters (get) or json body (post):
        lat: latitude
        lon: longitude
        date: date in yyyy-mm-dd format (optional, defaults to today)
        time: time in hh:mm format (optional, defaults to now)
        surface_type: 'asphalt', 'concrete', 'grass', etc. (optional)
        in_shadow: whether currently in shadow (optional, boolean)

    returns:
        json with heat risk prediction, weather data, and safety recommendations
    """
    if not ML_MODELS_AVAILABLE:
                return jsonify({
            "success": False,
            "error": "ml models not available. install scikit-learn and numpy."
        }), 503

    try:
        # parse parameters from get or post
        if request.method == 'POST':
            data = request.get_json() or {}
        else:
            data = request.args.to_dict()

        # location (defaults to dubai)
        lat = float(data.get('lat', DUBAI.LATITUDE))
        lon = float(data.get('lon', DUBAI.LONGITUDE))

        # parse datetime
        date_str = data.get('date')
        time_str = data.get('time')
        dt = parse_datetime_param(date_str, time_str)

        # fetch real weather data from open-meteo (7-day forecast cache)
        forecast = fetch_7day_forecast(lat, lon)
        target_date_str = dt.strftime("%Y-%m-%d")
        hour = dt.hour

        # find weather for this specific hour
        weather_data_from_api = None
        for hourly in forecast["hourly"]:
            if hourly["date"] == target_date_str and hourly["hour"] == hour:
                weather_data_from_api = hourly
                break

        # use real weather data or fallback
        if weather_data_from_api:
            temperature = weather_data_from_api["temperature"]
            humidity = weather_data_from_api["humidity"]
            wind_speed = weather_data_from_api["wind_speed"]
            uv_index = weather_data_from_api["uv_index"]
            cloud_cover = weather_data_from_api.get("cloud_cover", 0)
        else:
            # fallback to provided params or defaults
            temperature = float(data.get('temperature', 30.0))
            humidity = float(data.get('humidity', 50.0))
            wind_speed = float(data.get('wind_speed', 10.0))
            uv_index = float(data.get('uv_index', 5.0))
            cloud_cover = 0

        surface_type = data.get('surface_type', 'mixed')
        in_shadow = str(data.get('in_shadow', 'false')).lower() == 'true'

        # get sun position for this datetime
        sun_pos = solar_calculator.get_sun_position(dt)

        # calculate sun intensity based on altitude
        if sun_pos.altitude > 0:
            sun_intensity = min(1.0, sun_pos.altitude / 60)
        else:
            sun_intensity = 0.0

        # create input objects for the ml model
        weather = WeatherData(
            temperature=temperature,
            humidity=humidity,
            wind_speed=wind_speed,
            uv_index=uv_index,
            cloud_cover=cloud_cover
        )

        location = LocationContext(
            latitude=lat,
            longitude=lon,
            surface_type=surface_type,
            urban_density=0.7  # dubai is densely urban
        )

        sun_exposure = SunExposure(
            is_in_shadow=in_shadow,
            current_sun_altitude=max(0, sun_pos.altitude),
            current_sun_azimuth=sun_pos.azimuth,
            minutes_in_sun_last_hour=30.0 if not in_shadow else 10.0,
            direct_sun_intensity=0.0 if in_shadow else sun_intensity
        )

        # get prediction from trained ml model
        model = get_heat_risk_model()
        prediction = model.predict(weather, location, sun_exposure, dt)

        # build response with weather data and prediction
        # this answers: "is it safe to be outside right now?"
        response_payload = {
                    "success": True,
                    "timestamp": dt.isoformat(),
            "location": {"lat": lat, "lon": lon},
        }

        # include nested objects for frontend compatibility
        # (frontend expects data.prediction and data.weather)
        response_payload["weather"] = {
            "temperature": round(float(temperature), 1),
            "humidity": round(float(humidity), 1),
            "wind_speed": round(float(wind_speed), 1),
            "uv_index": round(float(uv_index), 1),
            "cloud_cover": round(float(cloud_cover), 1),
        }

        response_payload["prediction"] = {
            "risk_level": int(prediction.risk_level),
            "risk_label": str(prediction.risk_label),
            "risk_score": round(float(getattr(prediction, "risk_score", prediction.risk_probability)), 4),
            "risk_probability": round(float(prediction.risk_probability), 4),
            "confidence": round(float(prediction.risk_probability) * 100, 1),
            "class_probabilities": {
                k: round(float(v), 4) for k, v in prediction.class_probabilities.items()
            },
            "class_probabilities_percent": {
                k: round(float(v) * 100, 1) for k, v in prediction.class_probabilities.items()
            },
            "wbgt_estimate": round(float(prediction.wbgt_estimate), 1),
            "heat_index": round(float(prediction.heat_index), 1),
            "recommended_max_exposure": int(getattr(prediction, "recommended_max_exposure", 0)),
            "safety_message": str(getattr(prediction, "safety_message", "")),
        }

        # keep backward-compatible top-level fields too
        response_payload.update({
            "risk_level": response_payload["prediction"]["risk_level"],
            "risk_label": response_payload["prediction"]["risk_label"],
            "risk_score": response_payload["prediction"]["risk_score"],
            "confidence": response_payload["prediction"]["confidence"],
            "class_probabilities": response_payload["prediction"]["class_probabilities_percent"],
            "wbgt_estimate": response_payload["prediction"]["wbgt_estimate"],
            "heat_index": response_payload["prediction"]["heat_index"],
        })

        return jsonify(response_payload)

    except Exception as e:
            return jsonify({
                "success": False,
            "error": str(e)
        }), 400


@app.route('/api/schedule', methods=['GET', 'POST'])
def get_optimal_task_schedule():
    """
    find the optimal time to schedule an outdoor task.

    answers: "given today's conditions, what's the best time to schedule this task?"

    uses sun position analysis to determine the best start time for outdoor work,
    maximizing shadow coverage at the given building/area.

    target users:
    - municipality planners (scheduling outdoor maintenance)
    - construction supervisors (planning work shifts)
    - facade cleaning companies (booking building cleaning slots)
    - joggers, cyclists (planning exercise times)

    query parameters (get) or json body (post):
        task_name: name/description of the task
        duration: duration in minutes (e.g., 60, 120)
        lat: latitude of task location
        lon: longitude of task location
        date: date in yyyy-mm-dd format
        start_hour: earliest allowed start hour (default 6)
        end_hour: latest allowed end hour (default 18)
        requires_shade: whether task must be in shade (default false)
        surface_type: ground surface type (default 'mixed')

    returns:
        json with optimal schedule recommendation, ranked alternatives,
        and shadow coverage breakdown for each time slot
    """
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({
            "success": False,
            "error": "shadow scheduler not available."
        }), 503

    try:
        # parse parameters from request
        if request.method == 'POST':
            data = request.get_json() or {}
        else:
            data = request.args.to_dict()

        # task parameters
        task_name = data.get('task_name', 'outdoor task')
        duration = int(data.get('duration', 60))
        lat = float(data.get('lat', DUBAI.LATITUDE))
        lon = float(data.get('lon', DUBAI.LONGITUDE))

        # date selection
        date_str = data.get('date')
        if date_str:
            year, month, day = map(int, date_str.split('-'))
            date = datetime(year, month, day)
        else:
            date = datetime.now()

        # time bounds
        earliest_start = int(data.get('start_hour', data.get('earliest_start', 6)))
        latest_end = int(data.get('end_hour', data.get('latest_end', 18)))
        requires_shade = str(data.get('requires_shade', 'true')).lower() == 'true'
        building_face = data.get('building_face')
        face_angle_raw = data.get('face_angle')
        face_angle = None
        if face_angle_raw is not None:
            try:
                a = float(face_angle_raw)
                face_angle = max(0.0, min(360.0, a % 360.0)) if a == a else None
            except (TypeError, ValueError):
                pass

        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
        recommendation = scheduler.find_optimal_schedule(
            task_name=task_name,
            lat=lat,
            lon=lon,
            location_name=task_name,
            task_duration_minutes=duration,
            date=date,
            start_hour=earliest_start,
            end_hour=latest_end,
            building_face=building_face,
            face_angle=face_angle,
            recommendation_count=5
        )

        best = recommendation.best_slot

        # store schedule request in sqlite for learning from user feedback
        request_id = str(uuid.uuid4())
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO schedule_requests (
                    id, task_name, lat, lon, date, start_hour, end_hour,
                    duration_minutes, recommended_start, recommended_end,
                    heat_risk_score, shade_percentage, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id,
                task_name,
                lat,
                lon,
                date.strftime('%Y-%m-%d'),
                earliest_start,
                latest_end,
                duration,
                best.start.strftime('%H:%M'),
                best.end.strftime('%H:%M'),
                0.0,  # unused legacy column
                float(best.shadow_percentage),
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()
        except Exception as db_err:
            print(f"warning: could not store schedule request: {db_err}")

        return jsonify({
            "success": True,
            "request_id": request_id,
            "task": task_name,
            "date": date.strftime('%Y-%m-%d'),
            "constraints": {
                "duration_minutes": duration,
                "earliest_start": earliest_start,
                "latest_end": latest_end,
                "requires_shade": requires_shade
            },
            "recommendation": {
                "best_start_time": best.start.strftime('%H:%M'),
                "end_time": best.end.strftime('%H:%M'),
                "quality_score": round(best.shadow_percentage, 1),
                "shade_percentage": round(best.shadow_percentage, 1),
                "is_feasible": True,
                "location": f"{lat:.4f}, {lon:.4f}"
            },
            "alternatives": [
                {
                    "start_time": slot.start.strftime('%H:%M'),
                    "end_time": slot.end.strftime('%H:%M'),
                    "quality_score": round(slot.shadow_percentage, 1),
                    "shade_percentage": round(slot.shadow_percentage, 1)
                }
                for slot in recommendation.alternatives
            ],
            "summary": recommendation.recommendation_reason,
            "analysis": recommendation.recommendation_reason
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/schedule/feedback', methods=['POST'])
def save_schedule_feedback():
    """
    store user feedback for schedule recommendations.

    this data is used to learn user preferences over time.
    """
    try:
        data = request.get_json() or {}
        request_id = data.get('request_id')
        action = data.get('action')  # accept or reject
        chosen_start = data.get('chosen_start')
        chosen_end = data.get('chosen_end')
        note = data.get('note', '')

        if not request_id or action not in ['accept', 'reject']:
            return jsonify({"success": False, "error": "invalid request_id or action"}), 400

        feedback_id = str(uuid.uuid4())
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO schedule_feedback (
                id, request_id, action, chosen_start, chosen_end, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback_id,
            request_id,
            action,
            chosen_start,
            chosen_end,
            note,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "feedback_id": feedback_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/schedule/history', methods=['GET'])
def get_schedule_history():
    """
    return recent schedule requests and feedback.

    this can be used to analyze user preferences and improve recommendations.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("""
            SELECT id, task_name, lat, lon, date, start_hour, end_hour,
                   duration_minutes, recommended_start, recommended_end,
                   heat_risk_score, shade_percentage, created_at
            FROM schedule_requests
            ORDER BY created_at DESC
            LIMIT 50
        """)
        requests_rows = cur.fetchall()

        cur.execute("""
            SELECT id, request_id, action, chosen_start, chosen_end, note, created_at
            FROM schedule_feedback
            ORDER BY created_at DESC
            LIMIT 50
        """)
        feedback_rows = cur.fetchall()

        conn.close()

        return jsonify({
            "success": True,
            "requests": [
                {
                    "id": r[0], "task_name": r[1], "lat": r[2], "lon": r[3],
                    "date": r[4], "start_hour": r[5], "end_hour": r[6],
                    "duration_minutes": r[7], "recommended_start": r[8],
                    "recommended_end": r[9],
                    "shade_percentage": r[11], "created_at": r[12]
                } for r in requests_rows
            ],
            "feedback": [
                {
                    "id": f[0], "request_id": f[1], "action": f[2],
                    "chosen_start": f[3], "chosen_end": f[4], "note": f[5],
                    "created_at": f[6]
                } for f in feedback_rows
            ]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/shaded-route', methods=['GET', 'POST'])
def get_shaded_navigation_route():
    """
    find a shade-optimized route between two points.

    uses mapbox directions api for realistic pedestrian/cycling routes that:
    - follow actual roads and paths (not straight lines)
    - avoid highways for pedestrians and cyclists
    - consider bridges, water bodies, and safe crossings
    - provide turn-by-turn navigation geometry

    this endpoint is for community users (cyclists, joggers, pedestrians)
    who want to minimize sun exposure during their journey.

    query parameters (get) or json body (post):
        start_lat: starting point latitude
        start_lon: starting point longitude
        end_lat: destination latitude
        end_lon: destination longitude
        mode: 'walking', 'cycling', or 'driving' (default 'walking')
        departure_time: departure time in hh:mm format (optional)
        departure_date: departure date in yyyy-mm-dd format (optional)
        mapbox_token: mapbox access token for directions api (optional)

    returns:
        json with shade-optimized route, segments, and geometry
    """
    if not NAVIGATOR_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "shade navigator not available (schedule_optimizer module)."
        }), 503

    try:
        # parse parameters
        if request.method == 'POST':
            data = request.get_json() or {}
        else:
            data = request.args.to_dict()

        # coordinates
        start_lat = float(data.get('start_lat', DUBAI.LATITUDE))
        start_lon = float(data.get('start_lon', DUBAI.LONGITUDE))
        end_lat = float(data.get('end_lat', DUBAI.LATITUDE + 0.01))
        end_lon = float(data.get('end_lon', DUBAI.LONGITUDE + 0.01))

        # mode (walking/cycling are safe for pedestrians, driving for vehicles)
        mode = data.get('mode', 'walking')
        if mode not in ['walking', 'cycling', 'driving']:
            mode = 'walking'

        # mapbox token for realistic routing
        mapbox_token = data.get('mapbox_token')

        # departure time
        date_str = data.get('departure_date')
        time_str = data.get('departure_time')
        departure_time = parse_datetime_param(date_str, time_str)

        # get shade navigator and find route
        navigator = get_shade_navigator()
        route = navigator.find_shaded_route(
            start=(start_lat, start_lon),
            end=(end_lat, end_lon),
            mode=mode,
            departure_time=departure_time,
            mapbox_token=mapbox_token
        )

        # store route in database for learning and history
        route_id = str(uuid.uuid4())
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO route_history (id, start_lat, start_lon, end_lat, end_lon,
                    start_name, end_name, travel_mode, distance_km, duration_min,
                    shade_coverage, heat_risk_score, route_geometry, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                route_id,
                start_lat, start_lon,
                end_lat, end_lon,
                data.get('start_name', ''),
                data.get('end_name', ''),
                mode,
                round(route.total_distance, 2),
                round(route.total_duration, 1),
                round(route.average_shade_coverage, 2),
                round(route.average_heat_risk, 2),
                json.dumps(route.route_geometry) if route.route_geometry else '',
                datetime.now().isoformat()
            ))
            conn.commit()
            conn.close()
        except Exception as db_err:
            print(f"warning: could not store route in database: {db_err}")

        # build response with route geometry for map display
        result = {
            "success": True,
            "route_id": route_id,
            "mode": mode,
            "departure_time": departure_time.isoformat(),
            "total_distance": round(route.total_distance, 1),
            "total_duration": round(route.total_duration, 1),
            "average_shade_coverage": round(route.average_shade_coverage * 100, 1),
            "average_heat_risk": round(route.average_heat_risk * 100, 1),
            "sun_exposure_minutes": round(route.sun_exposure_minutes, 1),
            "shade_score": round(route.shade_score, 1),
            "comparison": route.comparison_to_fastest,
            "geometry": route.route_geometry,  # actual route path from mapbox
            "segments": [
                {
                    "start": [seg.start_lat, seg.start_lon],
                    "end": [seg.end_lat, seg.end_lon],
                    "distance": round(seg.distance_meters, 1),
                    "duration": round(seg.duration_seconds, 1),
                    "shade_coverage": round(seg.shade_coverage * 100, 1),
                    "heat_risk": round(seg.heat_risk * 100, 1)
                }
                for seg in route.segments[:50]  # limit to 50 segments for response size
            ]
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@app.route('/api/v2/shadow-route', methods=['POST'])
def get_shadow_optimized_route():
    """
    Shadow-optimised routing: up to 3 recommendations.

    Uses ShadeRouter: road graph from Mapbox Tilequery + direction candidates
    from Mapbox Directions; pathfinding is A* and Yen's k-shortest on that
    graph (no Mapbox API used for the final route choice).
    """
    if not SHADE_ROUTER_AVAILABLE or not ShadeRouter:
        return jsonify({
            "success": False,
            "error": ("ShadeRouter not available. "
                      "Install: pip install networkx")
        }), 503

    try:
        data = request.get_json() or {}

        start_lat = float(data.get('start_lat', DUBAI.LATITUDE))
        start_lon = float(data.get('start_lon', DUBAI.LONGITUDE))
        end_lat = float(data.get('end_lat', DUBAI.LATITUDE + 0.01))
        end_lon = float(data.get('end_lon', DUBAI.LONGITUDE + 0.01))

        mode = data.get('mode', 'walking')
        if mode not in ['walking', 'cycling']:
            mode = 'walking'

        date_str = data.get('date')
        current_minutes = data.get('current_minutes')
        client_buildings = data.get('buildings')

        router = ShadeRouter()
        result = router.find_routes(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            mode=mode,
            k=3,
            client_buildings=client_buildings,
            date_str=date_str,
            current_minutes=(int(current_minutes)
                             if current_minutes is not None else None),
        )

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/shadow-route/update', methods=['POST'])
def update_shadow_route():
    """
    Real-time shadow update for a route in progress.

    Evaluates current shadow state at the user's position and remaining
    route shade coverage.  Suggests reroute if coverage drops below 25 %.
    """
    if not SHADE_ROUTER_AVAILABLE or not ShadeRouter:
        return jsonify({
            "success": False,
            "error": "ShadeRouter not available."
        }), 503

    try:
        data = request.get_json() or {}

        route_coordinates = data.get('route_coordinates', [])
        user_lat = float(data.get('user_lat'))
        user_lon = float(data.get('user_lon'))
        departure_time_str = data.get('departure_time')
        elapsed_seconds = float(data.get('elapsed_seconds', 0))
        mode = data.get('mode', 'walking')
        total_duration = float(data.get('total_duration_seconds', 0))
        client_buildings = data.get('buildings')

        departure_time = datetime.fromisoformat(departure_time_str)

        router = ShadeRouter()
        result = router.update_route_shadows(
            route_coordinates=route_coordinates,
            user_lat=user_lat,
            user_lon=user_lon,
            departure_time=departure_time,
            elapsed_seconds=elapsed_seconds,
            mode=mode,
            total_duration_seconds=total_duration,
            client_buildings=client_buildings,
        )

        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/route-segment-shadows', methods=['POST'])
def get_route_segment_shadows():
    """
    Debug/validation: return per-segment shadow fraction for a route.

    POST body:
        route_coordinates: [[lon, lat], ...]
        departure_time: ISO datetime string
        mode: "walking" or "cycling" (optional)
        buildings: optional client buildings

    Returns:
        {"segments": [{"lon", "lat", "shadow_fraction", "segment_index"}, ...], ...}
    """
    if not SHADE_ROUTER_AVAILABLE or not ShadeRouter:
        return jsonify({
            "success": False,
            "error": "ShadeRouter not available."
        }), 503

    try:
        data = request.get_json() or {}
        route_coordinates = data.get("route_coordinates", [])
        departure_time_str = data.get("departure_time")
        mode = data.get("mode", "walking")
        client_buildings = data.get("buildings")

        if not route_coordinates or len(route_coordinates) < 2:
            return jsonify({"success": False, "error": "route_coordinates must have at least 2 points"}), 400
        if not departure_time_str:
            return jsonify({"success": False, "error": "departure_time required"}), 400

        departure_time = datetime.fromisoformat(departure_time_str.replace("Z", "+00:00"))

        router = ShadeRouter()
        result = router.get_route_segment_shadows(
            route_coordinates=route_coordinates,
            departure_time=departure_time,
            mode=mode,
            client_buildings=client_buildings,
        )

        return jsonify({"success": True, **result})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/routes-shade-score', methods=['POST'])
def get_routes_shade_score():
    """
    Compute shade percentage for each of several routes (e.g. Google/Mapbox alternatives).
    Samples each route every 5m and tests points against building shadow polygons.

    POST body:
        routes: [{ "coordinates": [[lon, lat], ...] }, ...]
        date: "YYYY-MM-DD"
        current_minutes: 0–1439
        mode: "walking" | "running" | "cycling"
        buildings: optional client buildings (same shape as shadow-route)

    Returns:
        { "route_scores": [ { "route_index", "shade_pct" }, ... ] }
    """
    if not SHADE_ROUTER_AVAILABLE or not ShadeRouter:
        return jsonify({
            "success": False,
            "error": "ShadeRouter not available.",
        }), 503

    try:
        data = request.get_json() or {}
        routes = data.get("routes", [])
        date_str = data.get("date")
        current_minutes = data.get("current_minutes")
        mode = data.get("mode", "walking")
        if mode not in ("walking", "running", "cycling"):
            mode = "walking"
        client_buildings = data.get("buildings")

        if not routes:
            return jsonify({"success": False, "error": "routes required"}), 400
        if date_str is None or current_minutes is None:
            return jsonify({"success": False, "error": "date and current_minutes required"}), 400

        try:
            dep_date = datetime.strptime(str(date_str), "%Y-%m-%d")
            mins = int(current_minutes)
            departure_time = dep_date.replace(
                hour=mins // 60,
                minute=mins % 60,
                second=0,
                microsecond=0,
            )
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid date or current_minutes"}), 400

        # Use actual mode so run uses run speed for time-along-route (different sun at each segment than walk).
        router = ShadeRouter(segment_length=5.0)

        route_scores = []
        for idx, r in enumerate(routes):
            coords = r.get("coordinates") or r.get("geometry", {}).get("coordinates", [])
            if not coords or len(coords) < 2:
                route_scores.append({"route_index": idx, "shade_pct": 0, "score": 0, "sun_exposure_minutes": 0, "heat_risk": "low"})
                continue
            result = router.get_route_segment_shadows(
                route_coordinates=coords,
                departure_time=departure_time,
                mode=mode,
                client_buildings=client_buildings,
            )
            segments = result.get("segments", [])
            if not segments:
                route_scores.append({"route_index": idx, "shade_pct": 0, "score": 0, "sun_exposure_minutes": 0, "heat_risk": "low"})
                continue
            total_route = result.get("total_route_time_seconds") or 0
            total_shade = result.get("total_shade_time_seconds") or 0
            weighted = result.get("weighted_shade_fraction")
            if weighted is None and total_route > 0:
                weighted = total_shade / total_route
            elif weighted is None:
                weighted = 0.0
            shade_pct = round(weighted * 100, 1)
            sun_exposure_minutes = round((total_route - total_shade) / 60.0, 1)
            score = min(100, max(0, round(weighted * 100)))
            # Heat risk from heat_risk_model (location + departure time)
            mid_lat = sum(c[1] for c in coords) / len(coords)
            mid_lon = sum(c[0] for c in coords) / len(coords)
            heat_risk = _get_heat_risk_level_for_location(mid_lat, mid_lon, departure_time)
            route_scores.append({
                "route_index": idx,
                "shade_pct": shade_pct,
                "score": score,
                "sun_exposure_minutes": sun_exposure_minutes,
                "heat_risk": heat_risk,
            })

        return jsonify({
            "success": True,
            "route_scores": route_scores,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


try:
    from mapbox_directions import get_directions as mapbox_get_directions
    MAPBOX_DIRECTIONS_AVAILABLE = True
except ImportError:
    mapbox_get_directions = None
    MAPBOX_DIRECTIONS_AVAILABLE = False


try:
    from google_directions import get_directions as google_get_directions
    GOOGLE_DIRECTIONS_AVAILABLE = True
except ImportError:
    google_get_directions = None
    GOOGLE_DIRECTIONS_AVAILABLE = False


@app.route('/api/v2/google-directions', methods=['POST'])
def get_google_directions():
    """
    Google Directions API: route with geometry and steps.
    Requires GOOGLE_DIRECTIONS_API_KEY environment variable.

    POST body: start_lat, start_lon, end_lat, end_lon, mode ("walking"|"running"|"cycling")
    """
    if not GOOGLE_DIRECTIONS_AVAILABLE or not google_get_directions:
        return jsonify({
            "success": False,
            "error": "Google directions module not available.",
        }), 503

    try:
        data = request.get_json() or {}
        start_lat = float(data.get("start_lat", DUBAI.LATITUDE))
        start_lon = float(data.get("start_lon", DUBAI.LONGITUDE))
        end_lat = float(data.get("end_lat", DUBAI.LATITUDE + 0.01))
        end_lon = float(data.get("end_lon", DUBAI.LONGITUDE + 0.01))
        mode = data.get("mode", "walking")
        if mode not in ("walking", "running", "cycling"):
            mode = "walking"

        result = google_get_directions(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            mode=mode,
        )
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/mapbox-cycling-directions', methods=['POST'])
def get_mapbox_cycling_directions():
    """
    Mapbox Directions API with cycling profile only. Returns multiple routes (alternatives).
    POST body: start_lat, start_lon, end_lat, end_lon (mode ignored; always cycling).
    """
    if not MAPBOX_DIRECTIONS_AVAILABLE or not mapbox_get_directions:
        return jsonify({
            "success": False,
            "error": "Mapbox directions module not available.",
        }), 503

    try:
        data = request.get_json() or {}
        start_lat = float(data.get("start_lat", DUBAI.LATITUDE))
        start_lon = float(data.get("start_lon", DUBAI.LONGITUDE))
        end_lat = float(data.get("end_lat", DUBAI.LATITUDE + 0.01))
        end_lon = float(data.get("end_lon", DUBAI.LONGITUDE + 0.01))

        result = mapbox_get_directions(
            start_lon=start_lon,
            start_lat=start_lat,
            end_lon=end_lon,
            end_lat=end_lat,
            mode="cycling",
            alternatives=True,
            steps=True,
        )
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/route/history', methods=['GET'])
def get_route_history():
    """
    retrieve route history for analytics and learning.

    returns recent route requests and their outcomes.
    """
    try:
        limit = int(request.args.get('limit', 50))
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, start_lat, start_lon, end_lat, end_lon,
                   start_name, end_name, travel_mode, distance_km, duration_min,
                   shade_coverage, heat_risk_score, created_at
            FROM route_history
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()

        routes = []
        for row in rows:
            routes.append({
                "id": row[0],
                "start": {"lat": row[1], "lon": row[2], "name": row[5]},
                "end": {"lat": row[3], "lon": row[4], "name": row[6]},
                "mode": row[7],
                "distance_km": row[8],
                "duration_min": row[9],
                "shade_coverage": row[10],
                "heat_risk_score": row[11],
                "created_at": row[12]
            })

        return jsonify({
            "success": True,
            "count": len(routes),
            "routes": routes
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/ml-status', methods=['GET'])
def get_ml_status():
    """
    check status of ml models.

    returns information about which ml models are loaded and trained.
    """
    global heat_risk_model, shade_navigator

    return jsonify({
        "success": True,
        "ml_available": ML_MODELS_AVAILABLE,
        "models": {
            "heat_risk_model": {
                "loaded": heat_risk_model is not None,
                "trained": heat_risk_model.is_trained if heat_risk_model else False
            },
            "shadow_scheduler": {
                "loaded": SHADOW_SCHEDULER_AVAILABLE
            },
            "shade_navigator": {
                "loaded": shade_navigator is not None
            }
        },
        "endpoints": [
            "/api/heat-risk",
            "/api/schedule",
            "/api/shaded-route"
        ]
    })


# =============================================================================
# AUTH API ENDPOINTS
# =============================================================================

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Authenticate user and return user data."""
    try:
        data = request.get_json() or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({"success": False, "error": "Email and password required"}), 400
        user = authenticate_user(email, password)
        if not user:
            return jsonify({"success": False, "error": "Invalid email or password"}), 401
        return jsonify({
            "success": True,
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "display_name": user["display_name"],
                "user_type": user["user_type"],
                "organization": user.get("organization", ""),
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Register a new user."""
    try:
        data = request.get_json() or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        display_name = data.get('display_name', '')
        user_type = data.get('user_type', 'personal')
        organization = data.get('organization', '')
        if not email or not password or not display_name:
            return jsonify({"success": False, "error": "Email, password, and name required"}), 400
        existing = get_user_by_email(email)
        if existing:
            return jsonify({"success": False, "error": "Email already registered"}), 409
        hashed, salt = hash_password(password)
        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            password_hash=hashed,
            salt=salt,
            display_name=display_name,
            user_type=user_type,
            organization=organization,
        )
        create_user(user)
        return jsonify({
            "success": True,
            "user": {
                "user_id": user.user_id,
                "email": user.email,
                "display_name": user.display_name,
                "user_type": user.user_type,
                "organization": user.organization,
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/auth/me', methods=['GET'])
def api_get_me():
    """Get current user data from user_id header."""
    user_id = request.headers.get('X-User-Id', '')
    if not user_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404
    return jsonify({
        "success": True,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "user_type": user["user_type"],
            "organization": user.get("organization", ""),
        }
    })


@app.route('/api/auth/update', methods=['PUT'])
def api_update_user():
    """Update user profile."""
    try:
        user_id = request.headers.get('X-User-Id', '')
        if not user_id:
            return jsonify({"success": False, "error": "Not authenticated"}), 401
        data = request.get_json() or {}
        allowed = ['display_name', 'user_type', 'organization']
        updates = {k: v for k, v in data.items() if k in allowed}
        if updates:
            update_user(user_id, updates)
        return jsonify({"success": True, "message": "User updated"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# SAVED PLACES API ENDPOINTS
# =============================================================================

@app.route('/api/saved-places', methods=['GET'])
def api_get_saved_places():
    user_id = request.headers.get('X-User-Id', request.args.get('user_id', ''))
    if not user_id:
        return jsonify({"success": True, "places": []})
    places = get_saved_places(user_id)
    return jsonify({"success": True, "places": places})


@app.route('/api/saved-places', methods=['POST'])
def api_create_saved_place():
    try:
        data = request.get_json() or {}
        user_id = request.headers.get('X-User-Id', data.get('user_id', ''))
        place = SavedPlace(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=data.get('name', 'Saved Place'),
            lat=float(data.get('lat', 0)),
            lon=float(data.get('lon', 0)),
        )
        place_id = create_saved_place(place)
        return jsonify({"success": True, "place_id": place_id, "place": {
            "id": place.id, "name": place.name, "lat": place.lat, "lon": place.lon
        }})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/saved-places/<place_id>', methods=['DELETE'])
def api_delete_saved_place(place_id):
    user_id = request.headers.get('X-User-Id', '')
    success = delete_saved_place(place_id, user_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Place not found"}), 404


# =============================================================================
# TASK MANAGEMENT API ENDPOINTS
# =============================================================================

@app.route('/api/tasks', methods=['GET'])
def api_get_tasks():
    """Get all tasks, optionally filtered by date, status, or user."""
    try:
        date_filter = request.args.get('date')
        status_filter = request.args.get('status')
        user_id = request.headers.get('X-User-Id') or request.args.get('user_id')
        tasks = get_all_tasks(date_filter=date_filter, status_filter=status_filter, user_id=user_id)
        return jsonify({"success": True, "tasks": tasks, "count": len(tasks)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/today', methods=['GET'])
def api_get_today_tasks():
    """Get tasks for today."""
    try:
        user_id = request.headers.get('X-User-Id') or request.args.get('user_id')
        tasks = get_today_tasks(user_id=user_id)
        return jsonify({"success": True, "tasks": tasks, "count": len(tasks)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks', methods=['POST'])
def api_create_task():
    """Create a new task."""
    try:
        data = request.get_json() or {}

        user_id = data.get('user_id') or request.headers.get('X-User-Id', '')
        task = UserTask(
            task_id=data.get('task_id', str(uuid.uuid4())),
            task_name=data.get('task_name', 'Untitled Task'),
            location_name=data.get('location_name', ''),
            location_lat=float(data.get('location_lat', DUBAI.LATITUDE)),
            location_lon=float(data.get('location_lon', DUBAI.LONGITUDE)),
            duration_minutes=int(data.get('duration_minutes', 60)),
            hour_start=int(data.get('hour_start', 6)),
            hour_end=int(data.get('hour_end', 18)),
            date=data.get('date', datetime.now().strftime('%Y-%m-%d')),
            status=data.get('status', 'draft'),
            user_id=user_id
        )

        task_id = create_task(task)
        return jsonify({"success": True, "task_id": task_id, "message": "Task created"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/tasks/<task_id>', methods=['GET'])
def api_get_task(task_id):
    """Get a specific task."""
    try:
        task = get_task(task_id)
        if task:
            rec = get_recommendation_by_task(task_id)
            task['recommendation'] = rec
            return jsonify({"success": True, "task": task})
        return jsonify({"success": False, "error": "Task not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/<task_id>', methods=['PUT', 'PATCH'])
def api_update_task(task_id):
    """Update a task."""
    try:
        data = request.get_json() or {}

        allowed_fields = ['task_name', 'location_name', 'location_lat', 'location_lon',
                         'duration_minutes', 'hour_start', 'hour_end', 'date', 'status']
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return jsonify({"success": False, "error": "No valid fields to update"}), 400

        success = update_task(task_id, updates)
        if success:
            return jsonify({"success": True, "message": "Task updated"})
        return jsonify({"success": False, "error": "Task not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    """Delete a task."""
    try:
        success = delete_task(task_id)
        if success:
            return jsonify({"success": True, "message": "Task deleted"})
        return jsonify({"success": False, "error": "Task not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/<task_id>/complete', methods=['POST'])
def api_complete_task(task_id):
    """Mark a task as completed."""
    try:
        success = mark_task_completed(task_id)
        if success:
            return jsonify({"success": True, "message": "Task marked as completed"})
        return jsonify({"success": False, "error": "Task not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tasks/<task_id>/accept', methods=['POST'])
def api_accept_recommendation(task_id):
    """Accept a recommendation for a task."""
    try:
        data = request.get_json() or {}

        rec = AcceptedRecommendation(
            id=str(uuid.uuid4()),
            task_id=task_id,
            accepted_time_start=data.get('accepted_time_start', ''),
            accepted_time_end=data.get('accepted_time_end', ''),
            shade_percentage=float(data.get('shade_percentage', 0)),
            shade_slot=data.get('shade_slot', '')
        )

        rec_id = create_accepted_recommendation(rec)

        update_task(task_id, {'status': 'scheduled'})

        return jsonify({"success": True, "recommendation_id": rec_id, "message": "Recommendation accepted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# =============================================================================
# ANALYTICS API ENDPOINTS
# =============================================================================

@app.route('/api/dashboard', methods=['GET'])
def api_get_dashboard():
    """Get dashboard summary data."""
    try:
        user_id = request.headers.get('X-User-Id') or request.args.get('user_id')
        summary = get_dashboard_summary(user_id=user_id)
        return jsonify({"success": True, **summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analytics', methods=['GET'])
def api_get_analytics():
    """Get work analytics for past months."""
    try:
        months = int(request.args.get('months', 4))
        analytics = get_analytics_range(months)
        return jsonify({"success": True, "analytics": analytics})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analytics/<month>', methods=['GET'])
def api_get_month_analytics(month):
    """Get analytics for a specific month (YYYY-MM format)."""
    try:
        analytics = get_analytics(month)
        if analytics:
            return jsonify({"success": True, "analytics": analytics})

        updated = update_analytics_for_month(month)
        return jsonify({"success": True, "analytics": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/analytics/refresh', methods=['POST'])
def api_refresh_analytics():
    """Refresh analytics for current month."""
    try:
        month = datetime.now().strftime("%Y-%m")
        updated = update_analytics_for_month(month)
        return jsonify({"success": True, "analytics": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# HELPER FUNCTIONS FOR API
# =============================================================================

def _get_light_preset(sun_position: SunPosition) -> str:
    """
    Determine appropriate Mapbox light preset based on sun position.

    Args:
        sun_position: Current sun position

    Returns:
        Light preset name: 'day', 'dawn', 'dusk', or 'night'
    """
    if not sun_position.is_daylight:
        return "night"

    altitude = sun_position.altitude

    if altitude < 6:
        # Very low sun - dawn or dusk
        # Determine based on azimuth (morning: E, evening: W)
        if sun_position.azimuth < 180:
            return "dawn"
        else:
            return "dusk"
    elif altitude < 15:
        # Low sun - could be either
        if sun_position.azimuth < 180:
            return "dawn"
        else:
            return "dusk"
    else:
        return "day"


def _calculate_centroid(footprint: List[List[float]]) -> Dict[str, float]:
    """
    Calculate centroid of a building footprint.

    Args:
        footprint: List of [lon, lat] coordinates

    Returns:
        Dictionary with lon and lat of centroid
    """
    if not footprint:
        return {"lon": 0, "lat": 0}

    sum_lon = sum(pt[0] for pt in footprint)
    sum_lat = sum(pt[1] for pt in footprint)
    n = len(footprint)

    return {
        "lon": round(sum_lon / n, 6),
        "lat": round(sum_lat / n, 6)
    }


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "available_endpoints": [
            "/api/health",
            "/api/sun-position",
            "/api/shadows",
            "/api/animation",
            "/api/sun-path",
            "/api/buildings",
            "/api/locations",
            "/api/shadow-at-point",
            "/api/weather",
            "/api/heat-risk",
            "/api/schedule",
            "/api/shaded-route",
            "/api/ml-status"
        ]
    }), 404


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    return jsonify({
        "success": False,
        "error": "Internal server error",
        "message": str(e)
    }), 500


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SmartShift Sun-Shadow Simulation API Server")
    print("=" * 60)
    print(f"Location: Dubai ({DUBAI.LATITUDE}°N, {DUBAI.LONGITUDE}°E)")
    print(f"Timezone: UTC+{DUBAI.TIMEZONE_OFFSET}")
    print(f"Server:   http://{API.HOST}:{API.PORT}")
    print(f"ML Models: {'Available' if ML_MODELS_AVAILABLE else 'Not Available'}")
    print(f"Weather API: Open-Meteo [OK] (Free, No API Key)")
    print("-" * 60)
    print("Shadow & Sun Endpoints:")
    print("  GET /api/health       - Server status")
    print("  GET /api/sun-position - Current sun position")
    print("  GET /api/shadows      - Current shadow data")
    print("  GET /api/animation    - Day animation frames")
    print("  GET /api/sun-path     - Sun path across sky")
    print("  GET /api/buildings    - Building list")
    print("  GET /api/locations    - Landmark locations")
    print("  GET /api/weather      - Weather data (Open-Meteo)")
    print("-" * 60)
    print("ML-Powered Endpoints:")
    print("  GET/POST /api/heat-risk    - Heat risk prediction (dashboard)")
    print("  GET/POST /api/schedule     - Shadow-based task scheduling")
    print("  GET/POST /api/shaded-route - Shade-optimized navigation")
    print("  GET /api/ml-status         - ML models status")
    print("=" * 60)

    app.run(
        host=API.HOST,
        port=API.PORT,
        debug=API.DEBUG
    )
