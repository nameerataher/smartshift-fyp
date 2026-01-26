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

# Import our custom modules
from solar_position import SolarPositionCalculator, SunPosition
from shadow_calculator import ShadowCalculator, Building, Shadow
from config import (
    DUBAI, API, SHADOW,
    LANDMARK_LOCATIONS, SAMPLE_BUILDINGS,
    get_location_config, get_all_location_keys
)


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
            "/api/shadow-at-point"
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
    print("-" * 60)
    print("Endpoints:")
    print("  GET /api/health       - Server status")
    print("  GET /api/sun-position - Current sun position")
    print("  GET /api/shadows      - Current shadow data")
    print("  GET /api/animation    - Day animation frames")
    print("  GET /api/sun-path     - Sun path across sky")
    print("  GET /api/buildings    - Building list")
    print("  GET /api/locations    - Landmark locations")
    print("=" * 60)

    app.run(
        host=API.HOST,
        port=API.PORT,
        debug=API.DEBUG
    )


