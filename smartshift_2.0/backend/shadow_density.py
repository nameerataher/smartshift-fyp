"""
shadow_density.py — grid-based shadow density calculator

Given a bounding box and a time, produces a GeoJSON grid where each cell
carries a shadow_pct value (0 = full sun, 100 = full shade).  The grid is
consumed by the frontend as a colour-ramped fill layer for the split-view
shadow-density heatmap.

Pipeline
--------
1. Accept bbox, grid spacing (metres), datetime, optional client buildings
2. Fetch buildings (Mapbox Tilequery or client-provided)
3. Compute sun position and shadow polygons for every building
4. Build a lightweight spatial index (grid cell → nearby shadow polygons)
5. For each grid cell centre, ray-cast against shadow polygons
6. Return GeoJSON FeatureCollection of rectangular cells
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from shadow_calculator import Building, ShadowCalculator
from shadow_scheduler import (
    ShadowScheduler,
    _point_in_polygon,
    parse_client_buildings,
    MAPBOX_TOKEN,
)
from solar_position import SolarPositionCalculator
from config import DUBAI

MAX_GRID_CELLS = 5000
DEFAULT_GRID_SIZE_M = 20.0
SPATIAL_CELL_DEG = 0.003  # ~330 m – for the polygon spatial index


class ShadowDensityCalculator:
    """Compute a shadow-density grid for an arbitrary bounding box."""

    def __init__(self, mapbox_token: Optional[str] = None):
        self._shadow_calc = ShadowCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET,
        )
        self._scheduler = ShadowScheduler(mapbox_token=mapbox_token or MAPBOX_TOKEN)

    def compute_density_grid(
        self,
        bbox: Dict[str, float],
        dt: datetime,
        grid_size_m: float = DEFAULT_GRID_SIZE_M,
        client_buildings: Optional[List[Building]] = None,
    ) -> Dict:
        """
        Main entry point.

        Args:
            bbox: {"min_lat", "max_lat", "min_lon", "max_lon"}
            dt: local datetime for shadow computation
            grid_size_m: approximate cell size in metres
            client_buildings: optional pre-parsed Building list from frontend

        Returns:
            dict with "type": "FeatureCollection" and rectangular features
        """
        min_lat = bbox["min_lat"]
        max_lat = bbox["max_lat"]
        min_lon = bbox["min_lon"]
        max_lon = bbox["max_lon"]

        dlat = grid_size_m / self._shadow_calc.METERS_PER_DEGREE_LAT
        dlon = grid_size_m / self._shadow_calc.meters_per_degree_lon

        rows = max(1, int((max_lat - min_lat) / dlat))
        cols = max(1, int((max_lon - min_lon) / dlon))

        if rows * cols > MAX_GRID_CELLS:
            scale = math.sqrt((rows * cols) / MAX_GRID_CELLS)
            dlat *= scale
            dlon *= scale
            rows = max(1, int((max_lat - min_lat) / dlat))
            cols = max(1, int((max_lon - min_lon) / dlon))

        # --- buildings ---
        buildings = client_buildings or self._fetch_buildings_for_bbox(
            min_lat, max_lat, min_lon, max_lon,
        )

        # --- sun + shadow polygons ---
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        solar = SolarPositionCalculator(
            latitude=center_lat,
            longitude=center_lon,
            timezone_offset=DUBAI.TIMEZONE_OFFSET,
        )
        sun = solar.get_sun_position(dt)

        shadow_polys: List[List[Tuple[float, float]]] = []
        if sun.is_daylight and sun.altitude > 0:
            for b in buildings:
                poly = self._shadow_calc.calculate_shadow_polygon(b, sun)
                if poly:
                    shadow_polys.append(poly)

        # --- spatial index ---
        sp_idx: Dict[Tuple[int, int], List[int]] = {}
        for idx, poly in enumerate(shadow_polys):
            cells = _polygon_cells(poly, SPATIAL_CELL_DEG)
            for cell in cells:
                sp_idx.setdefault(cell, []).append(idx)

        # --- grid evaluation ---
        features = []
        points = []
        for r in range(rows):
            lat_lo = min_lat + r * dlat
            lat_hi = lat_lo + dlat
            lat_c = lat_lo + dlat / 2
            for c in range(cols):
                lon_lo = min_lon + c * dlon
                lon_hi = lon_lo + dlon
                lon_c = lon_lo + dlon / 2

                in_shadow = _is_point_in_indexed_shadows(
                    lon_c, lat_c, shadow_polys, sp_idx, SPATIAL_CELL_DEG,
                )
                shadow_pct = 100.0 if in_shadow else 0.0

                points.append({
                    "lat": lat_c,
                    "lon": lon_c,
                    "shadow_pct": shadow_pct,
                })

                features.append({
                    "type": "Feature",
                    "properties": {
                        "shadow_pct": shadow_pct,
                        "row": r,
                        "col": c,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [lon_lo, lat_lo],
                            [lon_hi, lat_lo],
                            [lon_hi, lat_hi],
                            [lon_lo, lat_hi],
                            [lon_lo, lat_lo],
                        ]],
                    },
                })

        meta = {
            "rows": rows,
            "cols": cols,
            "cell_size_m": grid_size_m,
            "buildings_used": len(buildings),
            "shadow_polys": len(shadow_polys),
            "sun_altitude": round(sun.altitude, 1),
            "sun_azimuth": round(sun.azimuth, 1),
            "is_daylight": sun.is_daylight,
        }

        return {
            "type": "FeatureCollection",
            "features": features,
            "points": points,
            "metadata": meta,
        }

    # ------------------------------------------------------------------
    # Building fetching
    # ------------------------------------------------------------------

    def _fetch_buildings_for_bbox(
        self, min_lat: float, max_lat: float, min_lon: float, max_lon: float,
    ) -> List[Building]:
        """Sample a few points inside the bbox and fetch buildings around each."""
        seen_ids: set = set()
        buildings: List[Building] = []

        sample_points = _bbox_sample_points(min_lat, max_lat, min_lon, max_lon)
        for lat, lon in sample_points:
            for b in self._scheduler._fetch_nearby_buildings(lat, lon):
                if b.id not in seen_ids:
                    seen_ids.add(b.id)
                    buildings.append(b)
        return buildings


# ------------------------------------------------------------------
# Helpers (module-level)
# ------------------------------------------------------------------

def _polygon_cells(
    poly: List[Tuple[float, float]], cell_size: float,
) -> List[Tuple[int, int]]:
    """Return the set of spatial-index cells a polygon overlaps."""
    cells: set = set()
    for lon, lat in poly:
        cells.add((int(lat // cell_size), int(lon // cell_size)))
    if not cells:
        return []
    min_r = min(c[0] for c in cells)
    max_r = max(c[0] for c in cells)
    min_c = min(c[1] for c in cells)
    max_c = max(c[1] for c in cells)
    return [
        (r, c)
        for r in range(min_r, max_r + 1)
        for c in range(min_c, max_c + 1)
    ]


def _is_point_in_indexed_shadows(
    lon: float,
    lat: float,
    shadow_polys: List[List[Tuple[float, float]]],
    sp_idx: Dict[Tuple[int, int], List[int]],
    cell_size: float,
) -> bool:
    """Check if (lon, lat) falls inside any shadow polygon using the spatial index."""
    cell = (int(lat // cell_size), int(lon // cell_size))
    checked: set = set()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            for poly_idx in sp_idx.get((cell[0] + dr, cell[1] + dc), []):
                if poly_idx in checked:
                    continue
                checked.add(poly_idx)
                if _point_in_polygon(lon, lat, shadow_polys[poly_idx]):
                    return True
    return False


def _bbox_sample_points(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float,
    max_samples: int = 9,
) -> List[Tuple[float, float]]:
    """Generate a grid of sample points inside the bbox for building fetch."""
    dlat = max_lat - min_lat
    dlon = max_lon - min_lon
    side = max(1, min(3, int(max_samples ** 0.5)))
    points = []
    for r in range(side):
        for c in range(side):
            lat = min_lat + dlat * (r + 0.5) / side
            lon = min_lon + dlon * (c + 0.5) / side
            points.append((lat, lon))
    return points
