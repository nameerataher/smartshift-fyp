"""
Simplified building height pipeline: OSM footprints + GHSL heights only.

No GBA predictions, no OSM tags - just:
1. Building footprints (geometry)
2. GHSL satellite heights sampled at centroids

Usage:
  python ghsl_only_heights.py

This creates a clean GeoJSON with only:
  - id: building identifier
  - height: GHSL-derived height in meters
  - geometry: building footprint polygon
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
GHSL_DIR = DATA_DIR / "ghsl"
GBA_DIR = DATA_DIR / "gba_dubai"
OUTPUT_DIR = DATA_DIR / "ghsl_only"


class GHSLSampler:
    """Samples building heights from merged GHSL tiles (Mollweide projection)."""

    def __init__(self, tif_paths: List[Path], nodata: float = -200.0):
        import rasterio
        from rasterio.merge import merge
        from pyproj import Transformer

        print(f"Loading {len(tif_paths)} GHSL tiles...")
        self.datasets = [rasterio.open(p) for p in tif_paths]
        self.merged_data, self.merged_transform = merge(self.datasets)
        self.merged_data = self.merged_data[0]
        self.src_crs = self.datasets[0].crs
        
        # WGS84 to Mollweide transformer
        self.transformer = Transformer.from_crs(
            "EPSG:4326", self.src_crs, always_xy=True
        )
        self.nodata = nodata
        self.inv_transform = ~self.merged_transform
        
        print(f"GHSL CRS: {self.src_crs}, Shape: {self.merged_data.shape}")

    def sample(self, lon: float, lat: float) -> Optional[float]:
        """Sample height at WGS84 coordinate."""
        try:
            x, y = self.transformer.transform(lon, lat)
            col, row = self.inv_transform * (x, y)
            col, row = int(col), int(row)
            h, w = self.merged_data.shape
            if 0 <= row < h and 0 <= col < w:
                val = float(self.merged_data[row, col])
                if val > self.nodata and val > 0:
                    return val
        except Exception:
            pass
        return None

    def close(self):
        for ds in self.datasets:
            ds.close()


def process_footprints(
    input_path: Path,
    output_path: Path,
    sampler: GHSLSampler,
    default_height: float = 5.0,
    min_height: float = 2.5,
) -> dict:
    """
    Process building footprints, adding GHSL heights.
    
    Args:
        input_path: Input GeoJSON with building polygons
        output_path: Output GeoJSON path
        sampler: GHSL height sampler
        default_height: Height to use when GHSL has no data
        min_height: Minimum height threshold (below this, use default)
    
    Returns:
        Statistics dict
    """
    from shapely.geometry import shape

    print(f"Processing: {input_path.name}")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    output_features = []
    stats = {"ghsl": 0, "default": 0, "total": 0}

    for feat in features:
        stats["total"] += 1
        geom = feat.get("geometry")
        old_props = feat.get("properties", {})

        if not geom:
            continue

        # Get building ID (try various fields)
        building_id = (
            old_props.get("id") or 
            old_props.get("osm_id") or 
            old_props.get("@id") or 
            str(stats["total"])
        )

        # Sample GHSL height at centroid
        try:
            geom_shape = shape(geom)
            centroid = geom_shape.representative_point()
            height = sampler.sample(centroid.x, centroid.y)
        except Exception:
            height = None

        # Apply minimum threshold
        if height is not None and height >= min_height:
            stats["ghsl"] += 1
        else:
            height = default_height
            stats["default"] += 1

        # Create clean output feature
        output_features.append({
            "type": "Feature",
            "properties": {
                "id": str(building_id),
                "height": round(height, 2),
            },
            "geometry": geom,
        })

    # Create output GeoJSON
    output_data = {
        "type": "FeatureCollection",
        "features": output_features,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f)

    return stats


def main() -> int:
    # Find GHSL tiles
    tif_files = list(GHSL_DIR.glob("*.tif"))
    if not tif_files:
        print(f"No GHSL .tif files found in {GHSL_DIR}")
        return 1

    print(f"Found {len(tif_files)} GHSL tiles")
    sampler = GHSLSampler(tif_files)

    # Use GBA merged file as footprint source (it has 600k+ buildings)
    input_file = GBA_DIR / "dubai_merged.geojson"
    if not input_file.exists():
        print(f"Input file not found: {input_file}")
        return 1

    output_file = OUTPUT_DIR / "dubai_buildings_ghsl.geojson"

    print(f"\nInput: {input_file}")
    print(f"Output: {output_file}")

    stats = process_footprints(input_file, output_file, sampler)
    sampler.close()

    print(f"\n{'='*50}")
    print(f"GHSL-Only Height Pipeline Complete")
    print(f"{'='*50}")
    print(f"Total buildings: {stats['total']}")
    print(f"  GHSL heights:  {stats['ghsl']:>6} ({100*stats['ghsl']/stats['total']:.1f}%)")
    print(f"  Default (5m):  {stats['default']:>6} ({100*stats['default']/stats['total']:.1f}%)")
    print(f"\nOutput: {output_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

