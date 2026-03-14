"""
api_v2.py

new api endpoints using the unified core_model architecture
provides comfort-based scheduling and routing with explainable recommendations
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import traceback

# import modules
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
    from comfort_navigator import ComfortNavigator, RouteRecommendation
    NAVIGATOR_AVAILABLE = True
except ImportError:
    ComfortNavigator = None
    NAVIGATOR_AVAILABLE = False
    print("warning: comfort_navigator not available")

try:
    from shadow_scheduler import ShadowScheduler, calculate_shadow_at_time, find_optimal_schedule_for_area, parse_client_buildings
    from solar_position import SunPosition
    SHADOW_SCHEDULER_AVAILABLE = True
except ImportError as e:
    ShadowScheduler = None
    SHADOW_SCHEDULER_AVAILABLE = False
    print(f"warning: shadow_scheduler not available: {e}")

NEW_ARCH_AVAILABLE = CORE_MODEL_AVAILABLE or SHADOW_SCHEDULER_AVAILABLE or NAVIGATOR_AVAILABLE

# create blueprint for v2 api
api_v2 = Blueprint('api_v2', __name__, url_prefix='/api/v2')

# lazy-load singletons
_comfort_navigator = None

def get_comfort_navigator(mapbox_token: str):
    """get comfort navigator with mapbox token"""
    if not NAVIGATOR_AVAILABLE or not ComfortNavigator:
        return None
    return ComfortNavigator(
        mapbox_token=mapbox_token,
        sample_interval_meters=15.0
    )


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
    if not CORE_MODEL_AVAILABLE:
        return jsonify({"error": "core_model not available"}), 500

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
    find optimal schedule for a task using shadow-only scheduler.

    POST /api/v2/schedule
    {
        "task_name": "facade cleaning - south wall",
        "work_zone": {
            "zone_id": "bldg_123_south",
            "name": "burj khalifa south facade",
            "lat": 25.197197,
            "lon": 55.274376,
            ...
        },
        "task_duration_minutes": 120,
        "date": "2026-02-10",
        "start_hour": 9,
        "end_hour": 17,
        "building_face": "S",  // optional: N, E, S, W
        "area_polygon": [...]   // optional: use centroid for area mode
    }
    """
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

        # area_polygon: use centroid if provided
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


@api_v2.route('/schedule/area', methods=['POST'])
def schedule_for_area():
    """
    Schedule task for a polygon area using grid-sampling shadow analysis.

    POST /api/v2/schedule/area
    {
        "task_name": "Road Cleaning",
        "polygon_points": [[25.195, 55.270], [25.195, 55.280], ...],
        "location_name": "Work Zone",
        "task_duration_minutes": 180,
        "date": "2026-03-10",
        "start_hour": 5,
        "end_hour": 20,
        "recommendation_count": 5
    }
    """
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


@api_v2.route('/schedule/building-face', methods=['POST'])
def schedule_for_building_face():
    """
    Schedule task for a building face (N/E/S/W).

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
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500

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

        scheduler = ShadowScheduler(temporal_resolution_minutes=30)
        recommendation = scheduler.find_optimal_schedule(
            task_name=task_name,
            lat=building_lat,
            lon=building_lon,
            location_name=f"{task_name} - {face} face",
            task_duration_minutes=task_duration,
            date=date,
            start_hour=start_hour,
            end_hour=end_hour,
            building_face=face,
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
    if not NAVIGATOR_AVAILABLE or not ComfortNavigator:
        return jsonify({"error": "comfort navigator not available"}), 500

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
        if not navigator:
            return jsonify({"error": "navigator not available"}), 500

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
    if not CORE_MODEL_AVAILABLE:
        return jsonify({"error": "core_model not available"}), 500

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


@api_v2.route('/shadow-schedule', methods=['POST'])
def shadow_schedule():
    """
    Find optimal schedule based PURELY on shadow exposure.

    This endpoint uses the clean shadow-only scheduler with no heat risk considerations.

    POST /api/v2/shadow-schedule
    {
        "task_name": "Facade Cleaning",
        "lat": 25.197197,
        "lon": 55.274376,
        "location_name": "Downtown Dubai",
        "duration_minutes": 120,
        "date": "2026-03-10",
        "start_hour": 5,
        "end_hour": 20,
        "building_face": "S",  // optional: N, E, S, W
        "recommendation_count": 5
    }

    Returns:
    {
        "success": true,
        "recommendation": {
            "task_name": "...",
            "best_schedule": {
                "start_time": "...",
                "end_time": "...",
                "shadow_percentage": 85,
                "time_label": "7:00 AM - 9:00 AM"
            },
            "alternatives": [...],
            "recommendation_reason": "..."
        }
    }
    """
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
            client_buildings=client_buildings
        )

        return jsonify({
            "success": True,
            "mode": "shadow_only",
            "building_source": "client_map_tiles" if client_buildings else "tilequery_api",
            "buildings_used": recommendation.buildings_used,
            "recommendation": recommendation.to_dict()
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 400


@api_v2.route('/debug/shadow-polygons', methods=['POST'])
def debug_shadow_polygons():
    """
    Debug endpoint: returns raw shadow polygons as GeoJSON for visual validation.

    Accepts buildings extracted from the frontend's rendered map tiles so the
    shadow polygons match what Mapbox visually renders.

    POST /api/v2/debug/shadow-polygons
    {
        "lat": 25.2, "lon": 55.27,
        "time": "2026-03-11T10:00:00",
        "buildings": [{"id": "cl_0", "footprint": [[lon,lat],...], "height": 50, "name": "..."}]
    }
    """
    if not SHADOW_SCHEDULER_AVAILABLE or not ShadowScheduler:
        return jsonify({"error": "shadow scheduler not available"}), 500

    try:
        data = request.get_json()
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

        # Use frontend-provided sun position if available (ensures
        # computed shadows match what Mapbox renders visually)
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

        # Use same direction as Mapbox setLights so overlay shadows match map lighting
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
            # Building footprint (for visualization)
            fp_ring = [[p[0], p[1]] for p in b.footprint]
            if fp_ring and fp_ring[0] != fp_ring[-1]:
                fp_ring.append(fp_ring[0])
            footprint_features.append({
                "type": "Feature",
                "properties": {
                    "building_id": b.id,
                    "height": b.height,
                    "name": b.name or "unknown",
                    "layer": "footprint",
                },
                "geometry": {"type": "Polygon", "coordinates": [fp_ring]}
            })

            # Shadow polygon (use Mapbox light direction when provided so overlay matches map)
            polygon = calc.calculate_shadow_polygon(b, sun, shadow_direction_override)
            if polygon:
                ring = [[p[0], p[1]] for p in polygon]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                shadow_features.append({
                    "type": "Feature",
                    "properties": {
                        "building_id": b.id,
                        "height": b.height,
                        "name": b.name or "unknown",
                        "layer": "shadow",
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
            "shadow_geojson": {
                "type": "FeatureCollection",
                "features": shadow_features
            },
            "footprint_geojson": {
                "type": "FeatureCollection",
                "features": footprint_features
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 400


@api_v2.route('/sun-position', methods=['GET'])
def get_sun_position():
    """
    Get current sun position and shadow percentage at a location.

    GET /api/v2/sun-position?lat=25.2&lon=55.27&time=2026-03-10T14:00:00&face=S
    """
    try:
        lat = float(request.args.get('lat', 25.2048))
        lon = float(request.args.get('lon', 55.2708))
        time_str = request.args.get('time')
        building_face = request.args.get('face')

        if time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.now()

        if not SHADOW_SCHEDULER_AVAILABLE:
            return jsonify({"success": False, "error": "shadow_scheduler not available"}), 500

        result = calculate_shadow_at_time(lat, lon, dt, building_face)

        return jsonify({
            "success": True,
            "location": {"lat": lat, "lon": lon},
            "time": dt.isoformat(),
            "building_face": building_face,
            **result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400


@api_v2.route('/feedback', methods=['POST'])
def submit_feedback():
    """
    submit user feedback (acknowledged; shadow-only scheduler has no adaptive weights).

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
        return jsonify({
            "success": True,
            "message": "feedback received",
            "updated_weights": {"shadow_weight": 1.0, "heat_weight": 0.0}
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

