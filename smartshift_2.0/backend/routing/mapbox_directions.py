import requests as http_req
from typing import Dict, List, Optional, Any

MAPBOX_TOKEN = (
    "pk.eyJ1IjoibmFtZWVyYXQiLCJhIjoiY21rdTMzOHFxMXI5MzNmc2U5cTI5Y3phbyJ9"
    ".WI13BJqDyOu6G38-YP6hog"
)

PROFILES = {
    "cycling": "mapbox/cycling",
}


def get_directions(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    mode: str = "cycling",
    alternatives: bool = True,
    steps: bool = True,
    access_token: Optional[str] = None,
) -> Dict[str, Any]:
    token = access_token or MAPBOX_TOKEN
    profile = PROFILES.get(mode.lower(), PROFILES["cycling"])
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"https://api.mapbox.com/directions/v5/{profile}/{coords}"

    params = {
        "geometries": "geojson",
        "overview": "full",
        "access_token": token,
    }
    if alternatives:
        params["alternatives"] = "true"
    if steps:
        params["steps"] = "true"

    try:
        resp = http_req.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "routes": [],
            "waypoints": [],
        }

    if data.get("code") != "Ok":
        return {
            "success": False,
            "error": data.get("message", "Unknown error"),
            "routes": [],
            "waypoints": [],
        }

    routes_out: List[Dict] = []
    for idx, route in enumerate(data.get("routes", [])):
        geom = route.get("geometry") or {}
        coords_list = geom.get("coordinates", [])
        duration_sec = route.get("duration", 0)
        distance_m = route.get("distance", 0)

        legs_out: List[Dict] = []
        for leg in route.get("legs", []):
            steps_out: List[Dict] = []
            for step in leg.get("steps", []):
                maneuver = step.get("maneuver") or {}
                steps_out.append({
                    "instruction": maneuver.get("instruction", ""),
                    "name": step.get("name", ""),
                    "distance": step.get("distance", 0),
                    "duration": step.get("duration", 0),
                })
            legs_out.append({"steps": steps_out})

        routes_out.append({
            "route_index": idx,
            "distance_meters": round(distance_m, 1),
            "duration_seconds": round(duration_sec, 1),
            "distance_km": round(distance_m / 1000, 1),
            "duration_minutes": max(1, round(duration_sec / 60)),
            "geometry": {
                "type": "LineString",
                "coordinates": coords_list,
            },
            "legs": legs_out,
            "label": "Route 1" if idx == 0 else f"Alternative {idx}" if idx > 1 else "Route 2",
        })

    waypoints = [
        {"name": w.get("name", ""), "location": w.get("location", [])}
        for w in data.get("waypoints", [])
    ]

    return {
        "success": True,
        "routes": routes_out,
        "waypoints": waypoints,
        "travel_mode": mode,
    }
