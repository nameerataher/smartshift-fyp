import os
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd

from solar_position import SolarPositionCalculator, SunPosition
from shadow_calculator import ShadowCalculator, Shadow
from config import (
    DUBAI, API,
    LANDMARK_LOCATIONS,
)

# import ml models for heat risk
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
    from shadow_scheduler import ShadowScheduler, parse_client_buildings, _point_in_polygon
    SHADOW_SCHEDULER_AVAILABLE = True
except ImportError:
    ShadowScheduler = None
    parse_client_buildings = None
    _point_in_polygon = None
    SHADOW_SCHEDULER_AVAILABLE = False
    print("Warning: ShadowScheduler not available")

try:
    from routing.shade_router import ShadeRouter
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

DB_PATH = os.path.join(os.path.dirname(__file__), "smartshift.db")

def init_db():
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

def get_heat_risk_model():
    global heat_risk_model
    if heat_risk_model is None and ML_MODELS_AVAILABLE:
        print("initializing heat risk model...")
        heat_risk_model = HeatRiskModel()
        if not heat_risk_model.is_trained:
            heat_risk_model.train(n_samples=5000, verbose=False)
    return heat_risk_model

def get_shade_navigator():
    global shade_navigator
    if shade_navigator is None and NAVIGATOR_AVAILABLE and ShadeNavigator:
        print("initializing shade navigator...")
        shade_navigator = ShadeNavigator()
    return shade_navigator


# helper functions
def parse_datetime_param(date_str: Optional[str], time_str: Optional[str]) -> datetime:
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
    # convert SunPosition object to JSON-serializable dictionary.
    return {
        "azimuth": round(pos.azimuth, 2),
        "altitude": round(pos.altitude, 2),
        "zenith": round(pos.zenith, 2),
        "is_daylight": pos.is_daylight,
        "sunrise": pos.sunrise.strftime("%H:%M") if pos.sunrise else None,
        "sunset": pos.sunset.strftime("%H:%M") if pos.sunset else None,
        "solar_noon": pos.solar_noon.strftime("%H:%M") if pos.solar_noon else None
    }


@app.route('/api/sun-position', methods=['GET'])
def get_sun_position():
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

@app.route('/api/locations', methods=['GET'])
def get_locations():
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
    # Check if a specific point is in shadow at a given time.
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


@app.route('/api/shadow-density', methods=['POST'])
def get_shadow_density():
    # Compute a grid-based shadow density map for a bounding box.

    try:
        from shadow_density import ShadowDensityCalculator
        from shadow_scheduler import parse_client_buildings
    except ImportError as e:
        return jsonify({"success": False, "error": f"Module not available: {e}"}), 500

    try:
        data = request.get_json()
        bbox = data.get("bbox", {})
        required = ("min_lat", "max_lat", "min_lon", "max_lon")
        if not all(k in bbox for k in required):
            return jsonify({"success": False, "error": f"bbox must include {required}"}), 400

        bbox = {k: float(bbox[k]) for k in required}
        grid_size = float(data.get("grid_size_meters", 20))

        date_str = data.get("date")
        time_str = data.get("time")
        dt = parse_datetime_param(date_str, time_str)

        client_buildings = None
        if data.get("buildings"):
            client_buildings = parse_client_buildings(data["buildings"])

        calc = ShadowDensityCalculator()
        result = calc.compute_density_grid(
            bbox=bbox,
            dt=dt,
            grid_size_m=grid_size,
            client_buildings=client_buildings,
        )

        return jsonify({
            "success": True,
            "grid": result,
            "metadata": result.get("metadata", {}),
        })

    except Exception as e:
        import traceback
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


# global cache for 7-day hourly forecast
weather_forecast_cache = {
    "data": None,
    "fetched_at": None,
    "lat": None,
    "lon": None
}

def fetch_7day_forecast(lat, lon):
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


# -----------------------------------------------------------------------------
@app.route('/api/weather/forecast', methods=['GET'])
def get_weather_forecast():
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

@app.route('/api/heat-risk', methods=['GET', 'POST'])
def get_heat_risk():
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

@app.route('/api/v2/schedule/area', methods=['POST'])
def v2_schedule_area():
    """
    Find optimal work schedule for a drawn area (polygon). Uses shadow-only
    scheduler; buildings can come from client map tiles or Tilequery API.
    """
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler or not parse_client_buildings:
        return jsonify({"success": False, "error": "shadow scheduler not available"}), 500
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
            client_buildings=client_buildings,
        )
        grid_pts = scheduler._sample_polygon_grid(polygon_tuples)
        return jsonify({
            "success": True,
            "mode": "area_grid",
            "building_source": "client_map_tiles" if client_buildings else "tilequery_api",
            "buildings_used": recommendation.buildings_used,
            "grid_samples": len(grid_pts),
            "recommendation": recommendation.to_dict(),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/shadow-schedule', methods=['POST'])
def v2_shadow_schedule():
    """
    Find optimal time windows for an outdoor task by shadow only (no heat risk).
    Used by Map page for site analysis.
    """
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler or not parse_client_buildings:
        return jsonify({"success": False, "error": "shadow scheduler not available"}), 500
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
        recommendation_count = int(data.get('recommendation_count', 5))
        raw_buildings = data.get('buildings')
        client_buildings = parse_client_buildings(raw_buildings) if raw_buildings else None
        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
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
            recommendation_count=recommendation_count,
            client_buildings=client_buildings,
        )
        return jsonify({
            "success": True,
            "mode": "shadow_only",
            "building_source": "client_map_tiles" if client_buildings else "tilequery_api",
            "buildings_used": recommendation.buildings_used,
            "recommendation": recommendation.to_dict(),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/v2/debug/shadow-polygons', methods=['POST'])
def v2_debug_shadow_polygons():
    """
    Return shadow polygons as GeoJSON for the map overlay. Uses client-provided
    buildings and optional sun azimuth/altitude so shadows match Mapbox view.
    """
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler or _point_in_polygon is None:
        return jsonify({"success": False, "error": "shadow scheduler not available"}), 500
    try:
        data = request.get_json() or {}
        lat = float(data.get('lat', 25.2048))
        lon = float(data.get('lon', 55.2708))
        time_str = data.get('time')
        if time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.now()
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
        shadow_features = []
        footprint_features = []
        shadow_length_m = shadow_calculator.calculate_shadow_length(30.0, sun.altitude) if sun.altitude > 0 else 0
        shadow_dir = shadow_calculator.calculate_shadow_direction(sun.azimuth) if sun.altitude > 0 else 0
        for b in buildings:
            fp_ring = [[p[0], p[1]] for p in b.footprint]
            if fp_ring and fp_ring[0] != fp_ring[-1]:
                fp_ring.append(fp_ring[0])
            footprint_features.append({
                "type": "Feature",
                "properties": {"building_id": b.id, "height": b.height, "name": b.name or "unknown", "layer": "footprint"},
                "geometry": {"type": "Polygon", "coordinates": [fp_ring]},
            })
            polygon = shadow_calculator.calculate_shadow_polygon(b, sun)
            if polygon:
                ring = [[p[0], p[1]] for p in polygon]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                shadow_features.append({
                    "type": "Feature",
                    "properties": {"building_id": b.id, "height": b.height, "name": b.name or "unknown", "layer": "shadow"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                })
        target_in_shadow = any(
            shadow_calculator.calculate_shadow_polygon(b, sun)
            and _point_in_polygon(lon, lat, shadow_calculator.calculate_shadow_polygon(b, sun))
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
            "footprint_geojson": {"type": "FeatureCollection", "features": footprint_features},
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 400


try:
    from routing.mapbox_directions import get_directions as mapbox_get_directions
    MAPBOX_DIRECTIONS_AVAILABLE = True
except ImportError:
    mapbox_get_directions = None
    MAPBOX_DIRECTIONS_AVAILABLE = False

try:
    from routing.google_directions import get_directions as google_get_directions
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

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return jsonify({
        "success": False,
        "error": "Endpoint not found",
        "available_endpoints": [
            "/api/health",
            "/api/sun-position",
            "/api/sun-path",
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

if __name__ == "__main__":
    app.run(
        host=API.HOST,
        port=API.PORT,
        debug=API.DEBUG
    )
