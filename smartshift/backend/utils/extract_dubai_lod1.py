"""
Extract Dubai LOD1 3D building data from GlobalBuildingAtlas format.

This script searches for GlobalBuildingAtlas LOD1 GeoJSON files and extracts
buildings within Dubai's bounding box, creating a single output file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional
import glob

import fiona
from fiona.crs import from_epsg
import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

# Dubai bounding box (approximate)
DUBAI_BBOX = {
    "north": 25.40,
    "south": 24.90,
    "east": 55.60,
    "west": 54.90,
}

# Transform from WGS84 to Web Mercator (EPSG:3857) for processing
transformer_wgs84_to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
transformer_3857_to_wgs84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def bbox_to_3857(bbox: dict) -> tuple:
    """Convert WGS84 bbox to Web Mercator."""
    west, south = transformer_wgs84_to_3857.transform(bbox["west"], bbox["south"])
    east, north = transformer_wgs84_to_3857.transform(bbox["east"], bbox["north"])
    return (west, south, east, north)


def find_globalbuildingatlas_data(search_paths: list[Path]) -> list[Path]:
    """
    Search for GlobalBuildingAtlas LOD1 GeoJSON files.
    
    Args:
        search_paths: List of directories to search
        
    Returns:
        List of GeoJSON file paths
    """
    geojson_files = []
    
    for search_path in search_paths:
        if not search_path.exists():
            continue
            
        # Search for LOD1 GeoJSON files (common patterns)
        patterns = [
            "**/*lod1*.geojson",
            "**/*_lod1.geojson",
            "**/*.geojson",  # Fallback: any GeoJSON
        ]
        
        for pattern in patterns:
            found = list(search_path.rglob(pattern))
            if found:
                geojson_files.extend(found)
                print(f"Found {len(found)} files matching '{pattern}' in {search_path}")
    
    # Remove duplicates
    return list(set(geojson_files))


def extract_from_globalbuildingatlas(
    input_dir: Path, output_path: Path, bbox: dict = DUBAI_BBOX
) -> int:
    """
    Extract Dubai buildings from GlobalBuildingAtlas LOD1 GeoJSON files.
    
    Args:
        input_dir: Directory containing GlobalBuildingAtlas LOD1 GeoJSON files
        output_path: Output GeoJSON path
        bbox: Bounding box dict with north, south, east, west keys
        
    Returns:
        Number of buildings extracted
    """
    bbox_3857 = bbox_to_3857(bbox)
    bbox_geom = box(*bbox_3857)
    
    # Find all GeoJSON files
    geojson_files = find_globalbuildingatlas_data([input_dir])
    
    if not geojson_files:
        raise FileNotFoundError(
            f"No GeoJSON files found in {input_dir}\n"
            "Please ensure GlobalBuildingAtlas LOD1 data is downloaded.\n"
            "Data can be downloaded from: https://mediatum.ub.tum.de/1782307"
        )
    
    print(f"Found {len(geojson_files)} GeoJSON files. Processing...")
    
    # LOD1 schema from GlobalBuildingAtlas
    schema = {
        "geometry": "Polygon",
        "properties": {
            "source": "str",
            "id": "str",
            "height": "float",
            "var": "float",
            "region": "str",
        },
    }
    
    count = 0
    processed_files = 0
    
    with fiona.open(
        output_path,
        "w",
        driver="GeoJSON",
        crs=from_epsg(4326),  # Use WGS84 for web display
        schema=schema,
    ) as dst:
        for geojson_file in geojson_files:
            try:
                with fiona.open(geojson_file, "r") as src:
                    file_count = 0
                    for feature in src:
                        # Get geometry
                        geom = shape(feature["geometry"])
                        
                        # Check if feature CRS is different
                        if src.crs and src.crs.to_string() != "EPSG:4326":
                            # Transform to WGS84 if needed
                            if "EPSG:3857" in str(src.crs):
                                geom = transform(
                                    lambda x, y, z=None: transformer_3857_to_wgs84.transform(x, y),
                                    geom
                                )
                        
                        # Check if within Dubai bbox (in WGS84)
                        bbox_wgs84 = box(bbox["west"], bbox["south"], bbox["east"], bbox["north"])
                        if bbox_wgs84.intersects(geom):
                            # Clip to bbox
                            clipped = bbox_wgs84.intersection(geom)
                            if clipped.is_empty or not clipped.is_valid:
                                continue
                            
                            # Prepare feature
                            props = feature.get("properties", {})
                            feature_out = {
                                "type": "Feature",
                                "geometry": mapping(clipped),
                                "properties": {
                                    "source": props.get("source", "unknown"),
                                    "id": props.get("id", f"bldg_{count}"),
                                    "height": float(props.get("height", -999)),
                                    "var": float(props.get("var", -999)),
                                    "region": props.get("region", "dubai"),
                                },
                            }
                            dst.write(feature_out)
                            count += 1
                            file_count += 1
                            
                            if count % 1000 == 0:
                                print(f"  Extracted {count} buildings...")
                    
                    if file_count > 0:
                        processed_files += 1
                        print(f"  {geojson_file.name}: {file_count} buildings")
                        
            except Exception as e:
                print(f"  Error processing {geojson_file}: {e}")
                continue
    
    print(f"\n✓ Extracted {count} buildings from {processed_files} files")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Dubai LOD1 3D building data from GlobalBuildingAtlas"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Path to GlobalBuildingAtlas data directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("smartshift/data/processed/lod1/dubai_lod1.geojson"),
        help="Output LOD1 GeoJSON path",
    )
    parser.add_argument(
        "--north",
        type=float,
        default=DUBAI_BBOX["north"],
        help="North latitude",
    )
    parser.add_argument(
        "--south",
        type=float,
        default=DUBAI_BBOX["south"],
        help="South latitude",
    )
    parser.add_argument(
        "--east",
        type=float,
        default=DUBAI_BBOX["east"],
        help="East longitude",
    )
    parser.add_argument(
        "--west",
        type=float,
        default=DUBAI_BBOX["west"],
        help="West longitude",
    )
    
    args = parser.parse_args()
    
    bbox = {
        "north": args.north,
        "south": args.south,
        "east": args.east,
        "west": args.west,
    }
    
    # Create output directory
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # Try to find data directory
    data_dir = args.data_dir
    if not data_dir:
        # Try common locations
        possible_paths = [
            Path("C:/Users/hp/Downloads/GlobalBuildingAtlas/data"),
            Path("../GlobalBuildingAtlas/data"),
            Path("GlobalBuildingAtlas/data"),
            Path.home() / "Downloads" / "GlobalBuildingAtlas" / "data",
        ]
        
        for path in possible_paths:
            if path.exists():
                data_dir = path
                print(f"Found data directory: {data_dir}")
                break
        
        if not data_dir:
            print("ERROR: GlobalBuildingAtlas data directory not found.")
            print("\nPlease provide the data directory using --data-dir")
            print("Or download the data from: https://mediatum.ub.tum.de/1782307")
            print("\nExample usage:")
            print("  python extract_dubai_lod1.py --data-dir /path/to/GlobalBuildingAtlas/data")
            return
    
    if not data_dir.exists():
        print(f"ERROR: Data directory does not exist: {data_dir}")
        return
    
    print(f"Extracting Dubai LOD1 buildings from: {data_dir}")
    print(f"Bounding box: {bbox['west']:.2f}°E, {bbox['south']:.2f}°N to {bbox['east']:.2f}°E, {bbox['north']:.2f}°N")
    
    try:
        count = extract_from_globalbuildingatlas(data_dir, args.output, bbox)
        print(f"\n✓ Success! LOD1 data saved to: {args.output}")
        print(f"  Total buildings: {count}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return


if __name__ == "__main__":
    main()

