"""
Merge supplied community GeoJSON files into a single LOD1-ready dataset.

Inputs: any *.geojson placed under smartshift/data/raw/ that contain building
        footprints with height/var fields (e.g., the three community files).
Outputs:
- smartshift/data/processed/lod1/dubai_lod1_custom.geojson
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import geopandas as gpd
import numpy as np
import pandas as pd

RAW_DIR = Path("smartshift/data/raw")
OUT_PATH = Path("smartshift/data/processed/lod1/dubai_lod1_custom.geojson")
DEFAULT_HEIGHT = 12.0


def find_geojson_files() -> List[Path]:
    return sorted(RAW_DIR.glob("*buildings*.geojson"))


def normalize_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf.set_crs("EPSG:4326", inplace=True)
    if gdf.crs.to_string().lower() != "epsg:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # height
    height_cols = [c for c in gdf.columns if "height" in c.lower()]
    if height_cols:
        height = gdf[height_cols[0]].apply(pd.to_numeric, errors="coerce")
    else:
        height = pd.Series(np.nan, index=gdf.index)
    # fill missing or non-finite
    height = height.fillna(DEFAULT_HEIGHT)
    height = height.mask(~np.isfinite(height), DEFAULT_HEIGHT)
    height = height.clip(lower=0.1)  # ensure positive extrusion

    # variance
    var_cols = [c for c in gdf.columns if c.lower() == "var"]
    if var_cols:
        var = gdf[var_cols[0]].apply(pd.to_numeric, errors="coerce").fillna(-999.0)
    else:
        var = pd.Series(-999.0, index=gdf.index)
    var = var.mask(~np.isfinite(var), -999.0)

    # source/id/name/region
    def first_present(cols, default=""):
        for c in cols:
            if c in gdf.columns:
                return gdf[c]
        return np.full(len(gdf), default)

    source = first_present(["source"], "custom")
    bid = first_present(["id", "building_id", "ogc_fid"], "").astype(str)
    name = first_present(["name"], "")
    region = first_present(["region"], "dubai_custom")

    return gpd.GeoDataFrame(
        {
            "source": source,
            "id": bid,
            "height": height,
            "var": var,
            "region": region,
            "name": name,
        },
        geometry=gdf.geometry,
        crs="EPSG:4326",
    )


def merge_files(files: List[Path], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for fp in files:
        print(f"Reading {fp}")
        gdf = gpd.read_file(fp)
        frames.append(normalize_gdf(gdf))
    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    merged.to_file(output, driver="GeoJSON")
    print(f"Saved {len(merged)} features -> {output}")
    return len(merged)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge custom community GeoJSONs into LOD1 dataset")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUT_PATH,
        help="Output GeoJSON path",
    )
    args = parser.parse_args()

    files = find_geojson_files()
    if not files:
        raise SystemExit(f"No GeoJSON files found under {RAW_DIR}")
    merge_files(files, args.output)


if __name__ == "__main__":
    import pandas as pd

    main()

