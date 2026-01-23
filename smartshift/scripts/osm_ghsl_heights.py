"""
Accurate building heights: OSM tags first, GHSL as fallback.

Uses SPATIAL MATCHING to find OSM height data for buildings.

Priority:
1. OSM height tag (accurate, explicit) - spatially matched
2. OSM building:levels × 3.5m (estimated from floors)
3. GHSL satellite average (coarse fallback)
4. Default 5m (last resort)
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
GHSL_DIR = DATA_DIR / "ghsl"
GBA_DIR = DATA_DIR / "gba_dubai"
OUTPUT_DIR = DATA_DIR / "final"

# Known landmark heights (OSM often has levels but not accurate heights)
# Format: (lat, lon, height_m, name) - will match buildings within ~50m
LANDMARK_HEIGHTS = [
    # Downtown Dubai
    (25.1972, 55.2744, 828.0, "Burj Khalifa"),
    (25.2048, 55.2708, 333.0, "Address Downtown"),
    (25.2000, 55.2700, 306.0, "Index Tower"),
    (25.1970, 55.2810, 285.0, "Boulevard Plaza Tower 1"),
    # Dubai Marina / JBR
    (25.0921, 55.1471, 413.4, "Princess Tower"),
    (25.0935, 55.1469, 392.4, "23 Marina"),
    (25.1002, 55.1515, 352.0, "Marina 101"),
    (25.0871, 55.1482, 331.1, "Cayan Tower"),
    (25.0850, 55.1445, 310.0, "Ocean Heights"),
    (25.0760, 55.1340, 348.0, "The Torch"),
    (25.0770, 55.1355, 360.0, "Elite Residence"),
    (25.0880, 55.1420, 281.0, "Sulafa Tower"),
    (25.0913, 55.1398, 306.0, "The Address Dubai Marina"),
    (25.0820, 55.1520, 279.0, "Botanica Tower"),
    # Emirates Towers / DIFC
    (25.2167, 55.2833, 355.0, "Emirates Office Tower"),
    (25.2167, 55.2806, 309.0, "Emirates Hotel Tower"),
    (25.2130, 55.2780, 229.0, "Gate Building DIFC"),
    # JLT
    (25.0700, 55.1420, 360.0, "Almas Tower"),
    # Business Bay
    (25.1850, 55.2650, 336.0, "SLS Dubai Hotel"),
    (25.1870, 55.2630, 356.0, "Il Primo"),
    (25.1880, 55.2700, 281.0, "Executive Towers"),
    (25.1820, 55.2680, 307.0, "Al Habtoor City"),
    # Palm Jumeirah
    (25.1130, 55.1380, 250.0, "Atlantis The Palm"),
    # Other notable towers
    (25.2550, 55.3260, 281.0, "Deira Tower"),
    (25.0750, 55.1200, 243.0, "JBR Bahar Tower"),
    (25.1600, 55.2380, 255.0, "FIVE Jumeirah Village"),
    (25.1940, 55.2760, 251.0, "Vida Downtown"),
]


def parse_height(value: Any) -> Optional[float]:
    """Parse OSM height value."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) and v > 0 else None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", ".")
    s = s.split(";")[0].strip()
    s = re.sub(r"[^0-9.\-]+", "", s)
    if not s:
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) and v > 0 else None
    except ValueError:
        return None


def levels_to_height(levels: float) -> float:
    """
    Convert building levels to height in meters.
    
    Uses a variable floor height that increases for taller buildings:
    - 1-10 floors: 3.0m per floor (residential/low-rise)
    - 11-30 floors: 3.5m per floor (mid-rise)
    - 31-60 floors: 4.0m per floor (high-rise commercial)
    - 61-100 floors: 4.5m per floor (skyscraper)
    - 100+ floors: 5.0m per floor (supertall, accounts for mechanical floors)
    """
    if levels <= 10:
        return levels * 3.0
    elif levels <= 30:
        return 10 * 3.0 + (levels - 10) * 3.5
    elif levels <= 60:
        return 10 * 3.0 + 20 * 3.5 + (levels - 30) * 4.0
    elif levels <= 100:
        return 10 * 3.0 + 20 * 3.5 + 30 * 4.0 + (levels - 60) * 4.5
    else:
        return 10 * 3.0 + 20 * 3.5 + 30 * 4.0 + 40 * 4.5 + (levels - 100) * 5.0


class GHSLSampler:
    """Sample heights from GHSL raster."""

    def __init__(self, tif_paths: List[Path]):
        import rasterio
        from rasterio.merge import merge
        from pyproj import Transformer

        print(f"Loading {len(tif_paths)} GHSL tiles...")
        self.datasets = [rasterio.open(p) for p in tif_paths]
        self.merged_data, self.merged_transform = merge(self.datasets)
        self.merged_data = self.merged_data[0]
        self.transformer = Transformer.from_crs(
            "EPSG:4326", self.datasets[0].crs, always_xy=True
        )
        self.inv_transform = ~self.merged_transform

    def sample(self, lon: float, lat: float) -> Optional[float]:
        try:
            x, y = self.transformer.transform(lon, lat)
            col, row = self.inv_transform * (x, y)
            col, row = int(col), int(row)
            h, w = self.merged_data.shape
            if 0 <= row < h and 0 <= col < w:
                val = float(self.merged_data[row, col])
                return val if val > 0 else None
        except Exception:
            pass
        return None

    def close(self):
        for ds in self.datasets:
            ds.close()


def build_osm_spatial_index(overpass_path: Path):
    """
    Build spatial index from OSM Overpass data.
    Returns: (rtree index, dict of osm_id -> {height, levels, name, centroid})
    """
    from shapely.geometry import shape, Point, Polygon
    from rtree import index
    
    print(f"Building OSM spatial index from: {overpass_path.name}")
    
    with open(overpass_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    osm_buildings = {}
    idx = index.Index()
    
    elements = data.get("elements", [])
    indexed = 0
    
    for el in elements:
        osm_id = str(el.get("id", ""))
        tags = el.get("tags", {})
        
        height = parse_height(tags.get("height"))
        levels = parse_height(tags.get("building:levels"))
        name = tags.get("name", "")
        
        # Skip if no useful data
        if not height and not levels:
            continue
        
        # Get geometry - Overpass returns bounds or geometry
        bounds = el.get("bounds")
        geometry = el.get("geometry")  # List of {lat, lon} for ways
        
        centroid = None
        bbox = None
        
        if geometry and isinstance(geometry, list) and len(geometry) >= 3:
            # Build polygon from way geometry
            try:
                coords = [(pt["lon"], pt["lat"]) for pt in geometry]
                poly = Polygon(coords)
                if poly.is_valid:
                    centroid = poly.centroid
                    bbox = poly.bounds
            except Exception:
                pass
        
        if not centroid and bounds:
            # Use bounds center
            lat = (bounds["minlat"] + bounds["maxlat"]) / 2
            lon = (bounds["minlon"] + bounds["maxlon"]) / 2
            centroid = Point(lon, lat)
            bbox = (bounds["minlon"], bounds["minlat"], bounds["maxlon"], bounds["maxlat"])
        
        if centroid and bbox:
            osm_buildings[osm_id] = {
                "height": height,
                "levels": levels,
                "name": name,
                "centroid": (centroid.x, centroid.y),
            }
            idx.insert(indexed, bbox, obj=osm_id)
            indexed += 1
    
    print(f"  Indexed {indexed} OSM buildings with height/levels")
    with_height = sum(1 for v in osm_buildings.values() if v["height"])
    print(f"  With explicit height: {with_height}")
    
    return idx, osm_buildings


def check_landmark(lat: float, lon: float, threshold: float = 0.0005) -> Optional[Tuple[float, str]]:
    """Check if coordinates are near a known landmark. Returns (height, name) or None."""
    for lm_lat, lm_lon, lm_height, lm_name in LANDMARK_HEIGHTS:
        dist = ((lat - lm_lat)**2 + (lon - lm_lon)**2) ** 0.5
        if dist < threshold:
            return (lm_height, lm_name)
    return None


def find_osm_match(
    centroid: Tuple[float, float],
    osm_index,
    osm_buildings: Dict,
    search_radius: float = 0.0005,  # ~50m in degrees
) -> Optional[Dict]:
    """Find best OSM building match near a centroid."""
    lon, lat = centroid
    bbox = (lon - search_radius, lat - search_radius, lon + search_radius, lat + search_radius)
    
    candidates = list(osm_index.intersection(bbox, objects=True))
    if not candidates:
        return None
    
    # Find closest match
    best_dist = float("inf")
    best_match = None
    
    for item in candidates:
        osm_id = item.object
        osm_data = osm_buildings.get(osm_id)
        if not osm_data:
            continue
        
        osm_centroid = osm_data["centroid"]
        dist = (lon - osm_centroid[0])**2 + (lat - osm_centroid[1])**2
        
        if dist < best_dist:
            best_dist = dist
            best_match = osm_data
    
    return best_match


def process_buildings(
    footprints_path: Path,
    osm_index,
    osm_buildings: Dict,
    ghsl_sampler: GHSLSampler,
    output_path: Path,
    default_height: float = 5.0,
) -> Dict[str, int]:
    """Process buildings with spatial OSM matching."""
    from shapely.geometry import shape

    print(f"Processing: {footprints_path.name}")

    with open(footprints_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    output_features = []
    stats = {"osm_height": 0, "osm_levels": 0, "ghsl": 0, "default": 0, "total": 0}

    for i, feat in enumerate(features):
        if i % 50000 == 0:
            print(f"  Processing {i}/{len(features)}...")
        
        stats["total"] += 1
        geom = feat.get("geometry")
        props = feat.get("properties", {})

        if not geom:
            continue

        building_id = str(props.get("id", stats["total"]))

        # Get centroid
        try:
            geom_shape = shape(geom)
            centroid = geom_shape.representative_point()
            centroid_coords = (centroid.x, centroid.y)
        except Exception:
            centroid_coords = None

        # Try spatial OSM match
        height = None
        height_src = "default"
        name = ""

        if centroid_coords:
            # Priority 0: Known landmarks (Burj Khalifa, etc.)
            landmark = check_landmark(centroid_coords[1], centroid_coords[0])
            if landmark:
                height, name = landmark
                height_src = "landmark"
                if "landmark" not in stats:
                    stats["landmark"] = 0
                stats["landmark"] += 1
            else:
                # Priority 1-2: OSM height/levels
                osm_match = find_osm_match(centroid_coords, osm_index, osm_buildings)
                
                if osm_match:
                    name = osm_match.get("name", "")
                    
                    if osm_match.get("height"):
                        height = osm_match["height"]
                        height_src = "osm_height"
                        stats["osm_height"] += 1
                    elif osm_match.get("levels"):
                        # Use smart floor-to-height conversion
                        height = levels_to_height(osm_match["levels"])
                        height_src = "osm_levels"
                        stats["osm_levels"] += 1

        # Fallback to GHSL
        if height is None and centroid_coords:
            height_ghsl = ghsl_sampler.sample(centroid_coords[0], centroid_coords[1])
            if height_ghsl and height_ghsl >= 2.5:
                height = height_ghsl
                height_src = "ghsl"
                stats["ghsl"] += 1

        # Final fallback
        if height is None:
            height = default_height
            height_src = "default"
            stats["default"] += 1

        output_features.append({
            "type": "Feature",
            "properties": {
                "id": building_id,
                "height": round(height, 1),
                "height_src": height_src,
                "name": name if name else None,
            },
            "geometry": geom,
        })

    output_data = {"type": "FeatureCollection", "features": output_features}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f)

    return stats


def main() -> int:
    # Load GHSL
    tif_files = list(GHSL_DIR.glob("*.tif"))
    if not tif_files:
        print(f"No GHSL tiles in {GHSL_DIR}")
        return 1
    ghsl_sampler = GHSLSampler(tif_files)

    # Build OSM spatial index
    overpass_path = DATA_DIR / "processed" / "dubai_overpass.json"
    if not overpass_path.exists():
        print(f"OSM data not found: {overpass_path}")
        return 1
    osm_index, osm_buildings = build_osm_spatial_index(overpass_path)

    # Process
    footprints_path = GBA_DIR / "dubai_merged.geojson"
    output_path = OUTPUT_DIR / "dubai_buildings.geojson"

    stats = process_buildings(
        footprints_path, osm_index, osm_buildings, ghsl_sampler, output_path
    )

    ghsl_sampler.close()

    print(f"\n{'='*50}")
    print(f"Building Heights Complete")
    print(f"{'='*50}")
    print(f"Total: {stats['total']}")
    if stats.get('landmark'):
        print(f"  Landmarks:   {stats['landmark']:>6} (known heights)")
    print(f"  OSM height:  {stats['osm_height']:>6} ({100*stats['osm_height']/stats['total']:.2f}%)")
    print(f"  OSM levels:  {stats['osm_levels']:>6} ({100*stats['osm_levels']/stats['total']:.2f}%)")
    print(f"  GHSL:        {stats['ghsl']:>6} ({100*stats['ghsl']/stats['total']:.1f}%)")
    print(f"  Default:     {stats['default']:>6} ({100*stats['default']/stats['total']:.1f}%)")
    print(f"\nOutput: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
