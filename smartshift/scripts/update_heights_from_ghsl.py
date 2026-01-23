"""
Update OSM building heights using GHSL (Global Human Settlement Layer) data.

This script samples building heights from the GHS-BUILT-H raster (100m resolution)
and merges them with existing building footprints, using GHSL as a fallback
when OSM/GBA heights are unavailable or unreliable.

Data Source:
  GHSL GHS-BUILT-H 2018 (P2023A) - 100m resolution global building heights
  https://ghsl.jrc.ec.europa.eu/download.php?ds=buH

Usage:
  1. Download GHSL GeoTIFF for your region from:
     https://ghsl.jrc.ec.europa.eu/download.php?ds=buH
     (Select your tile, e.g., R4_C22 for Middle East)

  2. Run this script:
     python update_heights_from_ghsl.py --input buildings.geojson --ghsl GHS_BUILT_H.tif --output buildings_ghsl.geojson

Height priority (configurable):
  1. Manual overrides (if provided)
  2. OSM explicit height tag
  3. OSM building:levels (converted to meters)
  4. GHSL raster height (fallback)
  5. GBA predicted height (last resort)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _to_float_maybe(value: Any) -> Optional[float]:
    """Convert various inputs to float, handling OSM quirks."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    s = str(value).strip()
    if not s:
        return None
    # Handle "12 m", "12m", "12.5", "12;13", "12,5"
    import re
    s = s.replace(",", ".")
    s = s.split(";")[0].strip()
    s = re.sub(r"[^0-9.\-]+", "", s)
    if not s:
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except ValueError:
        return None


class GHSLHeightSampler:
    """Samples building heights from GHSL GeoTIFF raster."""

    def __init__(self, ghsl_path: Path, nodata: float = -200.0):
        import rasterio
        self.src = rasterio.open(ghsl_path)
        self.nodata = nodata
        self.band = self.src.read(1)  # ANBH band
        print(f"Loaded GHSL raster: {self.src.width}x{self.src.height}, CRS: {self.src.crs}")

    def sample(self, lon: float, lat: float) -> Optional[float]:
        """Sample height at a given WGS84 coordinate."""
        try:
            # Transform lon/lat to raster pixel coordinates
            row, col = self.src.index(lon, lat)
            if 0 <= row < self.src.height and 0 <= col < self.src.width:
                val = float(self.band[row, col])
                if val > self.nodata and val > 0:
                    return val
        except Exception:
            pass
        return None

    def sample_polygon(self, geometry: Dict, method: str = "centroid") -> Optional[float]:
        """
        Sample height for a polygon.
        
        Methods:
          - centroid: Sample at the polygon centroid (fast)
          - max: Maximum value within the polygon bounds (more accurate for large buildings)
          - mean: Mean value within the polygon bounds
        """
        from shapely.geometry import shape
        geom = shape(geometry)
        
        if method == "centroid":
            c = geom.representative_point()
            return self.sample(c.x, c.y)
        
        # For max/mean, sample multiple points within bounds
        minx, miny, maxx, maxy = geom.bounds
        
        # Sample at ~10m intervals within bounds
        step = 0.0001  # ~10m at equator
        samples = []
        
        x = minx
        while x <= maxx:
            y = miny
            while y <= maxy:
                from shapely.geometry import Point
                if geom.contains(Point(x, y)):
                    val = self.sample(x, y)
                    if val is not None:
                        samples.append(val)
                y += step
            x += step
        
        if not samples:
            # Fallback to centroid
            c = geom.representative_point()
            return self.sample(c.x, c.y)
        
        if method == "max":
            return max(samples)
        elif method == "mean":
            return sum(samples) / len(samples)
        
        return samples[0] if samples else None

    def close(self):
        self.src.close()


def process_buildings(
    input_path: Path,
    ghsl_sampler: GHSLHeightSampler,
    output_path: Path,
    sample_method: str = "centroid",
    min_ghsl_height: float = 3.0,
    levels_to_m: float = 3.6,
) -> Dict[str, int]:
    """
    Process buildings and update heights using GHSL.
    
    Returns statistics dict with counts of height sources.
    """
    from shapely.geometry import shape
    
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    features = data.get("features", [])
    stats = {"osm_height": 0, "osm_levels": 0, "ghsl": 0, "gba": 0, "none": 0, "total": 0}
    
    for feat in features:
        stats["total"] += 1
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        
        # Get existing heights
        height_gba = _to_float_maybe(props.get("height"))
        height_osm = _to_float_maybe(props.get("height_osm"))
        levels = _to_float_maybe(props.get("building:levels") or props.get("levels"))
        
        # Sample GHSL height
        height_ghsl = None
        if geom:
            height_ghsl = ghsl_sampler.sample_polygon(geom, method=sample_method)
            # Filter out very low GHSL values (noise)
            if height_ghsl is not None and height_ghsl < min_ghsl_height:
                height_ghsl = None
        
        # Determine final height with priority
        height_final = None
        height_src = "none"
        
        # 1. OSM explicit height
        if height_osm is not None and height_osm > 0:
            height_final = height_osm
            height_src = "osm_height"
        # 2. OSM building levels
        elif levels is not None and levels > 0:
            height_final = levels * levels_to_m
            height_src = "osm_levels"
        # 3. GHSL raster height
        elif height_ghsl is not None and height_ghsl > 0:
            height_final = height_ghsl
            height_src = "ghsl"
        # 4. GBA predicted height
        elif height_gba is not None and height_gba > 0:
            height_final = height_gba
            height_src = "gba"
        
        # Update properties
        props["height_ghsl"] = height_ghsl
        props["height_final"] = height_final
        props["height_src"] = height_src
        
        # Keep original height as height_gba if not already present
        if "height_gba" not in props and height_gba is not None:
            props["height_gba"] = height_gba
        
        feat["properties"] = props
        stats[height_src] += 1
    
    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update building heights using GHSL raster data"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input GeoJSON with building footprints"
    )
    parser.add_argument(
        "--ghsl", "-g",
        required=True,
        help="Path to GHSL GHS-BUILT-H GeoTIFF file"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output GeoJSON path"
    )
    parser.add_argument(
        "--sample-method",
        choices=["centroid", "max", "mean"],
        default="centroid",
        help="How to sample GHSL for each building (default: centroid)"
    )
    parser.add_argument(
        "--min-ghsl-height",
        type=float,
        default=3.0,
        help="Minimum GHSL height to consider valid (default: 3.0m)"
    )
    parser.add_argument(
        "--levels-to-m",
        type=float,
        default=3.6,
        help="Meters per building level (default: 3.6)"
    )
    args = parser.parse_args()
    
    input_path = Path(args.input)
    ghsl_path = Path(args.ghsl)
    output_path = Path(args.output)
    
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    if not ghsl_path.exists():
        raise SystemExit(f"GHSL file not found: {ghsl_path}")
    
    print(f"Loading GHSL raster: {ghsl_path}")
    sampler = GHSLHeightSampler(ghsl_path)
    
    print(f"Processing buildings: {input_path}")
    stats = process_buildings(
        input_path,
        sampler,
        output_path,
        sample_method=args.sample_method,
        min_ghsl_height=args.min_ghsl_height,
        levels_to_m=args.levels_to_m,
    )
    
    sampler.close()
    
    print(f"\nResults:")
    print(f"  Total buildings: {stats['total']}")
    print(f"  Height sources:")
    print(f"    - OSM height tag: {stats['osm_height']}")
    print(f"    - OSM levels: {stats['osm_levels']}")
    print(f"    - GHSL raster: {stats['ghsl']}")
    print(f"    - GBA prediction: {stats['gba']}")
    print(f"    - No height: {stats['none']}")
    print(f"\nWrote: {output_path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

