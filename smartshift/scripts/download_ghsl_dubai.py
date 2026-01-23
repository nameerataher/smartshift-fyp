"""
Download GHSL building height data for Dubai using Google Earth Engine.

Prerequisites:
  1. Install earthengine-api: pip install earthengine-api
  2. Authenticate: earthengine authenticate
  3. Run this script

The script exports the GHSL GHS-BUILT-H raster for the Dubai bounding box
to Google Drive, which you can then download and use with update_heights_from_ghsl.py

Alternative: Download directly from GHSL website:
  https://ghsl.jrc.ec.europa.eu/download.php?ds=buH
  Select tile R4_C22 (covers Middle East including Dubai)
"""

import ee

# Dubai bounding box (approximately covering the metro area)
DUBAI_BBOX = {
    "west": 54.9,
    "south": 24.8,
    "east": 55.6,
    "north": 25.4,
}

# Extended Dubai + surrounding emirates
UAE_BBOX = {
    "west": 54.3,
    "south": 24.4,
    "east": 56.5,
    "north": 25.7,
}


def download_ghsl_for_bbox(
    bbox: dict,
    output_name: str = "ghsl_dubai_built_h",
    scale: int = 100,  # Native GHSL resolution
):
    """
    Export GHSL building height raster for a bounding box.
    
    Args:
        bbox: Dict with west, south, east, north in WGS84
        output_name: Name for the exported file
        scale: Output resolution in meters (100m is native GHSL resolution)
    """
    # Initialize Earth Engine
    ee.Initialize()
    
    # Define region of interest
    roi = ee.Geometry.Rectangle([
        bbox["west"], bbox["south"],
        bbox["east"], bbox["north"]
    ])
    
    # Load GHSL Building Height dataset (P2023A release)
    # Band: built_height (Average Net Building Height in meters)
    ghsl = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_H/2018")
    
    # Select the building height band
    height_band = ghsl.select("built_height")
    
    # Clip to region
    height_clipped = height_band.clip(roi)
    
    # Export to Google Drive
    task = ee.batch.Export.image.toDrive(
        image=height_clipped,
        description=output_name,
        folder="GHSL_Exports",
        fileNamePrefix=output_name,
        region=roi,
        scale=scale,
        crs="EPSG:4326",
        maxPixels=1e10,
    )
    
    task.start()
    print(f"Export task started: {output_name}")
    print(f"Check Google Drive > GHSL_Exports folder for the output")
    print(f"You can monitor progress at: https://code.earthengine.google.com/tasks")
    
    return task


def sample_ghsl_at_points(points: list) -> list:
    """
    Sample GHSL height values at specific lat/lon points.
    
    Args:
        points: List of (lon, lat) tuples
        
    Returns:
        List of height values (or None if no data)
    """
    ee.Initialize()
    
    ghsl = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_H/2018")
    height_band = ghsl.select("built_height")
    
    results = []
    for lon, lat in points:
        point = ee.Geometry.Point([lon, lat])
        value = height_band.sample(point, scale=100).first().get("built_height")
        try:
            results.append(value.getInfo())
        except Exception:
            results.append(None)
    
    return results


def get_ghsl_stats_for_bbox(bbox: dict) -> dict:
    """Get summary statistics of building heights in a bounding box."""
    ee.Initialize()
    
    roi = ee.Geometry.Rectangle([
        bbox["west"], bbox["south"],
        bbox["east"], bbox["north"]
    ])
    
    ghsl = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_H/2018")
    height_band = ghsl.select("built_height")
    
    # Compute statistics
    stats = height_band.reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.max(), sharedInputs=True)
            .combine(ee.Reducer.min(), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=roi,
        scale=100,
        maxPixels=1e10,
    )
    
    return stats.getInfo()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download GHSL building height data for Dubai"
    )
    parser.add_argument(
        "--region",
        choices=["dubai", "uae"],
        default="dubai",
        help="Region to download (default: dubai)"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only print statistics, don't export"
    )
    parser.add_argument(
        "--test-point",
        type=float,
        nargs=2,
        metavar=("LON", "LAT"),
        help="Test sampling at a specific point"
    )
    args = parser.parse_args()
    
    bbox = DUBAI_BBOX if args.region == "dubai" else UAE_BBOX
    
    if args.test_point:
        lon, lat = args.test_point
        print(f"Sampling GHSL at ({lon}, {lat})...")
        heights = sample_ghsl_at_points([(lon, lat)])
        print(f"Height: {heights[0]} meters")
        return 0
    
    if args.stats_only:
        print(f"Computing GHSL statistics for {args.region}...")
        stats = get_ghsl_stats_for_bbox(bbox)
        print(f"Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value:.2f}" if value else f"  {key}: N/A")
        return 0
    
    print(f"Exporting GHSL data for {args.region}...")
    print(f"Bounding box: {bbox}")
    download_ghsl_for_bbox(bbox, output_name=f"ghsl_{args.region}_built_h")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

