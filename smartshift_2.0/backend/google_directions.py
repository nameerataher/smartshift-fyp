import os
import re
import requests as http_req
from typing import Dict, List, Optional, Any, Tuple

def _decode_polyline(encoded: str) -> List[List[float]]:
    if not encoded:
        return []
    coords: List[Tuple[float, float]] = []
    idx = 0
    lat = 0.0
    lng = 0.0
    n = len(encoded)
    while idx < n:
        shift = result = 0
        while True:
            b = ord(encoded[idx]) - 63
            idx += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        # Signed value: LSB is sign; positive = result>>1, negative = ~(result>>1)
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat * 1e-5

        shift = result = 0
        while idx < n:
            b = ord(encoded[idx]) - 63
            idx += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng * 1e-5

        coords.append((lat, lng))
    return [[lon, lat] for lat, lon in coords]


def _parse_duration_seconds(duration_str: Optional[str]) -> float:
    if not duration_str or not isinstance(duration_str, str):
        return 0.0
    s = duration_str.strip().rstrip("s").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

MODE_MAP = {
    "walking": "WALK",
    "running": "WALK",
    "cycling": "BICYCLE",
}

WALK_SPEED_MS = 1.4
RUN_SPEED_MS = 2.6

def get_directions(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    mode: str = "walking",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call Google Routes API (computeRoutes) and return normalized route(s).
    Returns same shape as mapbox_directions for comparison.
    """
    key = api_key or os.environ.get("GOOGLE_DIRECTIONS_API_KEY", "").strip()
    if not key:
        return {
            "success": False,
            "error": "Google Directions API key not set (GOOGLE_DIRECTIONS_API_KEY)",
            "routes": [],
            "waypoints": [],
        }

    travel_mode = MODE_MAP.get(mode.lower(), "WALK")
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    payload = {
        "origin": {"location": {"latLng": {"latitude": start_lat, "longitude": start_lon}}},
        "destination": {"location": {"latLng": {"latitude": end_lat, "longitude": end_lon}}},
        "travelMode": travel_mode,
        "polylineEncoding": "GEO_JSON_LINESTRING",
        "computeAlternativeRoutes": True,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.polyline.geoJsonLinestring,routes.legs",
    }

    try:
        resp = http_req.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                body = e.response.json()
                err_msg = body.get("error", {}).get("message", body.get("message", err_msg))
            except Exception:
                pass
        return {
            "success": False,
            "error": err_msg,
            "routes": [],
            "waypoints": [],
        }

    routes_in = data.get("routes") or []
    if not routes_in:
        return {
            "success": False,
            "error": data.get("error", {}).get("message", "No routes returned"),
            "routes": [],
            "waypoints": [],
        }

    routes_out: List[Dict] = []
    for idx, route in enumerate(routes_in):
        polyline = route.get("polyline") or {}
        coords: List[List[float]] = []
        geo = polyline.get("geoJsonLinestring")
        if geo:
            if isinstance(geo, dict) and geo.get("type") == "LineString":
                coords = list(geo.get("coordinates") or [])
            elif isinstance(geo, dict) and "coordinates" in geo:
                coords = list(geo.get("coordinates") or [])
            elif isinstance(geo, list):
                coords = list(geo)
        if not coords:
            encoded = polyline.get("encodedPolyline") or ""
            coords = _decode_polyline(encoded)
        distance_m = int(route.get("distanceMeters", 0))
        duration_sec = _parse_duration_seconds(route.get("duration"))
        if mode.lower() == "running":
            duration_sec = duration_sec * (WALK_SPEED_MS / RUN_SPEED_MS)

        legs_out: List[Dict] = []
        for leg in route.get("legs", []):
            steps_out: List[Dict] = []
            for step in leg.get("steps", []):
                instr = (step.get("navigationInstruction") or {}).get("instructions", "")
                if isinstance(instr, dict):
                    instr = instr.get("text", "") or ""
                instr = re.sub(r"<[^>]+>", "", instr).strip()
                step_dist = step.get("distanceMeters") if isinstance(step.get("distanceMeters"), (int, float)) else 0
                step_dur = _parse_duration_seconds(step.get("duration"))
                if mode.lower() == "running":
                    step_dur = step_dur * (WALK_SPEED_MS / RUN_SPEED_MS)
                steps_out.append({
                    "instruction": instr,
                    "name": "",
                    "distance": step_dist,
                    "duration": step_dur,
                })
            legs_out.append({"steps": steps_out})

        routes_out.append({
            "route_index": idx,
            "distance_meters": round(distance_m, 1),
            "duration_seconds": round(duration_sec, 1),
            "distance_km": round(distance_m / 1000, 1),
            "duration_minutes": max(1, round(duration_sec / 60)),
            "geometry": {"type": "LineString", "coordinates": coords},
            "legs": legs_out,
            "label": "Route 1" if idx == 0 else f"Route {idx + 1}",
        })

    waypoints: List[Dict] = []
    if routes_out and routes_out[0]["geometry"]["coordinates"]:
        coords = routes_out[0]["geometry"]["coordinates"]
        waypoints = [{"name": "Origin", "location": coords[0]}, {"name": "Destination", "location": coords[-1]}]

    return {
        "success": True,
        "routes": routes_out,
        "waypoints": waypoints,
        "travel_mode": mode,
    }
