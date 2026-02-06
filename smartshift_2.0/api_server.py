"""
Flask API Server for Dubai Sun-Shadow Simulation
==================================================

This module provides a REST API for the sun-shadow simulation system.
It serves solar position data, shadow calculations, and animation frames
to the frontend Mapbox visualization.

Endpoints:
- GET /api/sun-position     - Current sun position
- GET /api/shadows          - Current shadow data
- GET /api/animation        - Shadow animation frames for a day
- GET /api/buildings        - Available buildings
- GET /api/locations        - Available landmark locations
- GET /api/health           - Server health check

"""

import json
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

# import ml models for heat risk and schedule optimization
try:
    from heat_risk_model import (
        HeatRiskModel, WeatherData, LocationContext, SunExposure,
        HeatRiskPrediction
    )
    from schedule_optimizer import (
        ScheduleOptimizer, Task, ShadeNavigator,
        get_optimal_schedule, get_shaded_route
    )
    ML_MODELS_AVAILABLE = True
except ImportError as e:
    ML_MODELS_AVAILABLE = False
    print(f"Warning: ML models not available. Install dependencies: {e}")

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

# sqlite database for storing schedule feedback and user preferences
DB_PATH = os.path.join(os.path.dirname(__file__), "smartshift.db")

def init_db():
    """initialize sqlite database tables for scheduling feedback."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_requests (
            id TEXT PRIMARY KEY,
            task_name TEXT,
            lat REAL,
            lon REAL,
            date TEXT,
            start_hour INTEGER,
            end_hour INTEGER,
            duration_minutes INTEGER,
            recommended_start TEXT,
            recommended_end TEXT,
            heat_risk_score REAL,
            shade_percentage REAL,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_feedback (
            id TEXT PRIMARY KEY,
            request_id TEXT,
            action TEXT, -- accept or reject
            chosen_start TEXT,
            chosen_end TEXT,
            note TEXT,
            created_at TEXT,
            FOREIGN KEY(request_id) REFERENCES schedule_requests(id)
        )
    """)
    conn.commit()
    conn.close()


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
schedule_optimizer = None
shade_navigator = None

def get_heat_risk_model():
    """lazy load and train heat risk model on first use."""
    global heat_risk_model
    if heat_risk_model is None and ML_MODELS_AVAILABLE:
        print("initializing heat risk model...")
        heat_risk_model = HeatRiskModel()
        if not heat_risk_model.is_trained:
            heat_risk_model.train(n_samples=5000, verbose=False)
    return heat_risk_model

def get_schedule_optimizer():
    """lazy load schedule optimizer on first use."""
    global schedule_optimizer
    if schedule_optimizer is None and ML_MODELS_AVAILABLE:
        print("initializing schedule optimizer...")
        schedule_optimizer = ScheduleOptimizer(heat_risk_model=get_heat_risk_model())
    return schedule_optimizer

def get_shade_navigator():
    """lazy load shade navigator on first use."""
    global shade_navigator
    if shade_navigator is None and ML_MODELS_AVAILABLE:
        print("initializing shade navigator...")
        shade_navigator = ShadeNavigator()
    return shade_navigator


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
        return jsonify({
            "success": True,
            "timestamp": dt.isoformat(),
            "location": {"lat": lat, "lon": lon},

            # real-time weather data from open-meteo
            "weather": {
                "temperature": round(temperature, 1),
                "humidity": round(humidity, 1),
                "wind_speed": round(wind_speed, 1),
                "uv_index": round(uv_index, 1),
                "source": "open-meteo" if weather_data_from_api else "fallback"
            },

            # ml model prediction
            "prediction": {
                "risk_level": prediction.risk_level,
                "risk_label": prediction.risk_label,
                "confidence": round(prediction.risk_probability * 100, 1),
                "class_probabilities": {
                    k: round(v * 100, 1) for k, v in prediction.class_probabilities.items()
                },
                "wbgt_estimate": round(prediction.wbgt_estimate, 1),
                "heat_index": round(prediction.heat_index, 1)
            },

            # safety recommendation for workers and community
            "safety_message": prediction.safety_message,
            "is_safe_outside": prediction.risk_level == 0,  # true if low risk

            # sun position data
            "sun_position": {
                "altitude": round(sun_pos.altitude, 1),
                "azimuth": round(sun_pos.azimuth, 1),
                "is_daylight": sun_pos.is_daylight,
                "in_shadow": in_shadow
            }
        })

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

    uses ai planning to determine the best start time for outdoor work,
    maximizing shadow exposure and minimizing heat risk.

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
        and heat risk breakdown for each time slot
    """
    if not ML_MODELS_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "ml models not available. install scikit-learn and numpy."
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

        # time bounds - user can specify working hours window
        # e.g., start_hour=9, end_hour=17 for 9am-5pm window
        earliest_start = int(data.get('start_hour', data.get('earliest_start', 6)))
        latest_end = int(data.get('end_hour', data.get('latest_end', 18)))

        # fetch real weather forecast from open-meteo for this date
        forecast = fetch_7day_forecast(lat, lon)
        target_date_str = date.strftime("%Y-%m-%d")

        # get average weather for the day from hourly forecast
        day_hours = [h for h in forecast["hourly"]
                     if h["date"] == target_date_str and earliest_start <= h["hour"] <= latest_end]

        if day_hours:
            # use real weather data from forecast
            temperature = sum(h["temperature"] for h in day_hours) / len(day_hours)
            humidity = sum(h["humidity"] for h in day_hours) / len(day_hours)
            wind_speed = sum(h["wind_speed"] for h in day_hours) / len(day_hours)
            weather_source = "open-meteo"
        else:
            # fallback defaults
            temperature = 35.0
            humidity = 50.0
            wind_speed = 10.0
            weather_source = "fallback"

        # constraints
        requires_shade = str(data.get('requires_shade', 'true')).lower() == 'true'
        surface_type = data.get('surface_type', 'mixed')

        # optional bounding box for area-based scheduling
        # if provided, sample center + corners for shadow coverage
        area_points = None
        if all(k in data for k in ['bbox_min_lat', 'bbox_min_lon', 'bbox_max_lat', 'bbox_max_lon']):
            try:
                min_lat = float(data.get('bbox_min_lat'))
                min_lon = float(data.get('bbox_min_lon'))
                max_lat = float(data.get('bbox_max_lat'))
                max_lon = float(data.get('bbox_max_lon'))
                center_lat = (min_lat + max_lat) / 2
                center_lon = (min_lon + max_lon) / 2
                area_points = [
                    (min_lon, min_lat),
                    (min_lon, max_lat),
                    (max_lon, min_lat),
                    (max_lon, max_lat),
                    (center_lon, center_lat)
                ]
            except Exception:
                area_points = None

        # create task
        task = Task(
            name=task_name,
            duration_minutes=duration,
            location_lat=lat,
            location_lon=lon,
            earliest_start=earliest_start,
            latest_end=latest_end,
            requires_shade=requires_shade,
            surface_type=surface_type,
            area_points=area_points
        )

        # create weather
        weather = WeatherData(
            temperature=temperature,
            humidity=humidity,
            wind_speed=wind_speed
        )

        # get recommendation
        optimizer = get_schedule_optimizer()
        recommendation = optimizer.find_best_schedule(task, date, weather)

        # store schedule request in sqlite for learning from user feedback
        request_id = str(uuid.uuid4())
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
            recommendation.best_slot.start_time.strftime('%H:%M'),
            recommendation.best_slot.end_time.strftime('%H:%M'),
            float(recommendation.best_slot.heat_risk_score),
            float(recommendation.best_slot.shade_percentage),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

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
            "conditions": {
                "temperature": temperature,
                "humidity": humidity,
                "wind_speed": wind_speed
            },
            "recommendation": {
                "best_start_time": recommendation.best_slot.start_time.strftime('%H:%M'),
                "end_time": recommendation.best_slot.end_time.strftime('%H:%M'),
                "quality_score": round(recommendation.best_slot.quality_score, 1),
                "heat_risk_score": round(recommendation.best_slot.heat_risk_score, 2),
                "shade_percentage": round(recommendation.best_slot.shade_percentage, 1),
                "is_feasible": recommendation.best_slot.is_feasible,
                "location": f"{lat:.4f}, {lon:.4f}",
                "risk_breakdown": recommendation.best_slot.risk_breakdown
            },
            "alternatives": [
                {
                    "start_time": slot.start_time.strftime('%H:%M'),
                    "end_time": slot.end_time.strftime('%H:%M'),
                    "quality_score": round(slot.quality_score, 1),
                    "heat_risk_score": round(slot.heat_risk_score, 2),
                    "shade_percentage": round(slot.shade_percentage, 1)
                }
                for slot in recommendation.alternative_slots
            ],
            "summary": recommendation.summary,
            "analysis": recommendation.detailed_breakdown
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
                    "recommended_end": r[9], "heat_risk_score": r[10],
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
    if not ML_MODELS_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "ml models not available. install scikit-learn and numpy."
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

        # build response with route geometry for map display
        result = {
            "success": True,
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


@app.route('/api/ml-status', methods=['GET'])
def get_ml_status():
    """
    check status of ml models.

    returns information about which ml models are loaded and trained.
    """
    global heat_risk_model, schedule_optimizer, shade_navigator

    return jsonify({
        "success": True,
        "ml_available": ML_MODELS_AVAILABLE,
        "models": {
            "heat_risk_model": {
                "loaded": heat_risk_model is not None,
                "trained": heat_risk_model.is_trained if heat_risk_model else False
            },
            "schedule_optimizer": {
                "loaded": schedule_optimizer is not None
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
    print(f"Weather API: Open-Meteo ✓ (Free, No API Key)")
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
    print("  GET/POST /api/heat-risk    - Heat risk prediction")
    print("  GET/POST /api/schedule     - Optimal task scheduling")
    print("  GET/POST /api/shaded-route - Shade-optimized navigation")
    print("  GET /api/ml-status         - ML models status")
    print("=" * 60)

    app.run(
        host=API.HOST,
        port=API.PORT,
        debug=API.DEBUG
    )
