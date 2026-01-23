"""
Process GHSL building height tiles and update Dubai building footprints.

This script:
1. Merges multiple GHSL tiles
2. Handles Mollweide (EPSG:54009) to WGS84 (EPSG:4326) coordinate transformation
3. Samples heights at building centroids
4. Updates the GeoJSON files with GHSL heights as fallback

Usage:
  python process_ghsl_heights.py
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Paths relative to script location
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
GHSL_DIR = DATA_DIR / "ghsl"
DUBAI_DIR = DATA_DIR / "dubai"
GBA_DIR = DATA_DIR / "gba_dubai"


def _to_float_maybe(value: Any) -> Optional[float]:
    """Convert various inputs to float, handling OSM quirks."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    import re
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
        return v if math.isfinite(v) else None
    except ValueError:
        return None


class GHSLMollweideSampler:
    """
    Samples building heights from GHSL GeoTIFF tiles in Mollweide projection.
    Handles coordinate transformation from WGS84 to Mollweide for sampling.
    """

    def __init__(self, tif_paths: List[Path], nodata: float = -200.0):
        import rasterio
        from rasterio.merge import merge
        from rasterio.crs import CRS
        from pyproj import Transformer

        print(f"Loading {len(tif_paths)} GHSL tiles...")

        # Open all tiles
        self.datasets = [rasterio.open(p) for p in tif_paths]

        # Merge tiles into a single array
        self.merged_data, self.merged_transform = merge(self.datasets)
        self.merged_data = self.merged_data[0]  # First band

        # Get CRS from first dataset (should be Mollweide EPSG:54009)
        self.src_crs = self.datasets[0].crs
        print(f"GHSL CRS: {self.src_crs}")

        # Create transformer from WGS84 to Mollweide
        self.transformer = Transformer.from_crs(
            "EPSG:4326",  # WGS84 (lon, lat)
            self.src_crs,  # Mollweide
            always_xy=True
        )

        self.nodata = nodata

        # Compute inverse transform for pixel lookup
        self.inv_transform = ~self.merged_transform

        print(f"Merged raster shape: {self.merged_data.shape}")
        print(f"Merged bounds (Mollweide): {self._get_bounds()}")

    def _get_bounds(self) -> Tuple[float, float, float, float]:
        """Get bounds in Mollweide coordinates."""
        h, w = self.merged_data.shape
        left, top = self.merged_transform * (0, 0)
        right, bottom = self.merged_transform * (w, h)
        return (left, bottom, right, top)

    def sample(self, lon: float, lat: float) -> Optional[float]:
        """Sample height at a given WGS84 coordinate."""
        try:
            # Transform WGS84 to Mollweide
            x, y = self.transformer.transform(lon, lat)

            # Convert to pixel coordinates
            col, row = self.inv_transform * (x, y)
            col, row = int(col), int(row)

            h, w = self.merged_data.shape
            if 0 <= row < h and 0 <= col < w:
                val = float(self.merged_data[row, col])
                if val > self.nodata and val > 0:
                    return val
        except Exception as e:
            pass
        return None

    def close(self):
        for ds in self.datasets:
            ds.close()


def process_geojson_file(
    input_path: Path,
    output_path: Path,
    sampler: GHSLMollweideSampler,
    min_height: float = 2.0,
    levels_to_m: float = 3.6,
) -> Dict[str, int]:
    """
    Process a single GeoJSON file and add GHSL heights.

    Returns statistics dict.
    """
    from shapely.geometry import shape

    print(f"Processing: {input_path.name}")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    stats = {"osm_height": 0, "osm_levels": 0, "ghsl": 0, "gba": 0, "none": 0, "total": 0}

    for feat in features:
        stats["total"] += 1
        props = feat.get("properties", {})
        geom = feat.get("geometry")

        if not geom:
            stats["none"] += 1
            continue

        # Get existing heights from various sources
        height_gba = _to_float_maybe(props.get("height"))
        height_osm = _to_float_maybe(props.get("height_osm"))
        height_tag = _to_float_maybe(props.get("height_tag"))  # Direct OSM height tag
        levels = _to_float_maybe(props.get("building:levels") or props.get("levels"))

        # Sample GHSL height at centroid
        try:
            geom_shape = shape(geom)
            centroid = geom_shape.representative_point()
            height_ghsl = sampler.sample(centroid.x, centroid.y)
        except Exception:
            height_ghsl = None

        # Filter out very low GHSL values (noise)
        if height_ghsl is not None and height_ghsl < min_height:
            height_ghsl = None

        # Determine final height with priority
        height_final = None
        height_src = "none"

        # Priority 1: OSM explicit height tag
        if height_osm is not None and height_osm > 0:
            height_final = height_osm
            height_src = "osm_height"
        elif height_tag is not None and height_tag > 0:
            height_final = height_tag
            height_src = "osm_height"
        # Priority 2: OSM building levels
        elif levels is not None and levels > 0:
            height_final = levels * levels_to_m
            height_src = "osm_levels"
        # Priority 3: GHSL raster height
        elif height_ghsl is not None and height_ghsl > 0:
            height_final = height_ghsl
            height_src = "ghsl"
        # Priority 4: GBA predicted height
        elif height_gba is not None and height_gba > 0:
            height_final = height_gba
            height_src = "gba"

        # Update properties
        props["height_ghsl"] = height_ghsl
        props["height_final"] = height_final if height_final else (height_gba or 5.0)  # Default 5m
        props["height_src"] = height_src

        feat["properties"] = props
        stats[height_src] += 1

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return stats


def main() -> int:
    import glob

    # Find all GHSL tiles
    tif_files = list(GHSL_DIR.glob("*.tif"))
    if not tif_files:
        print(f"No GHSL .tif files found in {GHSL_DIR}")
        return 1

    print(f"Found {len(tif_files)} GHSL tiles:")
    for f in tif_files:
        print(f"  - {f.name}")

    # Initialize sampler
    sampler = GHSLMollweideSampler(tif_files)

    # Test sampling at Dubai coordinates
    test_lon, test_lat = 55.2708, 25.2048  # Burj Khalifa area
    test_height = sampler.sample(test_lon, test_lat)
    print(f"\nTest sample at Burj Khalifa ({test_lon}, {test_lat}): {test_height}m")

    # Process GBA dubai merged file
    gba_input = GBA_DIR / "dubai_merged.geojson"
    gba_output = GBA_DIR / "dubai_merged_ghsl.geojson"

    total_stats = {"osm_height": 0, "osm_levels": 0, "ghsl": 0, "gba": 0, "none": 0, "total": 0}

    if gba_input.exists():
        print(f"\n--- Processing GBA Dubai file ---")
        stats = process_geojson_file(gba_input, gba_output, sampler)
        for k, v in stats.items():
            total_stats[k] += v
        print(f"  Wrote: {gba_output}")

    # Process individual Dubai partition files
    dubai_files = sorted(DUBAI_DIR.glob("dubai_p*.geojson"))
    if dubai_files:
        print(f"\n--- Processing {len(dubai_files)} Dubai partition files ---")
        output_dir = DUBAI_DIR / "ghsl_updated"
        output_dir.mkdir(exist_ok=True)

        for input_file in dubai_files:
            output_file = output_dir / input_file.name
            stats = process_geojson_file(input_file, output_file, sampler)
            for k, v in stats.items():
                total_stats[k] += v

        print(f"  Wrote updated files to: {output_dir}")

    sampler.close()

    # Print summary
    print(f"\n{'='*50}")
    print(f"GHSL Height Update Complete")
    print(f"{'='*50}")
    print(f"Total buildings processed: {total_stats['total']}")
    print(f"Height sources:")
    print(f"  - OSM height tag:  {total_stats['osm_height']:>6}")
    print(f"  - OSM levels:      {total_stats['osm_levels']:>6}")
    print(f"  - GHSL raster:     {total_stats['ghsl']:>6}")
    print(f"  - GBA prediction:  {total_stats['gba']:>6}")
    print(f"  - No height:       {total_stats['none']:>6}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

