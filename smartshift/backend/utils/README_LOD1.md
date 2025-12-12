# Dubai LOD1 3D Building Data Extraction

This guide explains how to extract Dubai-specific LOD1 (Level of Detail 1) 3D building data from GlobalBuildingAtlas.

## What is LOD1?

LOD1 (Level of Detail 1) represents buildings as simple extruded boxes with:
- **Footprint**: Building polygon from above
- **Height**: Building height in meters
- **Variance**: Uncertainty measure for the height estimate

This is perfect for shadow calculations and heat exposure modeling.

## Getting the Data

### Option 1: Download from mediaTUM (Recommended)

The full GlobalBuildingAtlas LOD1 data can be downloaded from:
**https://mediatum.ub.tum.de/1782307**

After downloading, extract the data to a directory (e.g., `C:\Users\hp\Downloads\GlobalBuildingAtlas\data`).

### Option 2: Generate from Code

If you have the required input data (building footprints + height maps), you can generate LOD1 data using the code in `GlobalBuildingAtlas/make_lod1/`.

## Using the Extraction Script

### Basic Usage

```bash
python smartshift/backend/utils/extract_dubai_lod1.py --data-dir "C:\Users\hp\Downloads\GlobalBuildingAtlas\data"
```

### Custom Bounding Box

```bash
python smartshift/backend/utils/extract_dubai_lod1.py \
  --data-dir "C:\Users\hp\Downloads\GlobalBuildingAtlas\data" \
  --north 25.40 \
  --south 24.90 \
  --east 55.60 \
  --west 54.90 \
  --output smartshift/data/processed/lod1/dubai_lod1.geojson
```

### Output

The script will create:
- `smartshift/data/processed/lod1/dubai_lod1.geojson` - GeoJSON file with Dubai LOD1 buildings

Each building feature contains:
- `geometry`: Polygon footprint
- `properties.height`: Building height in meters
- `properties.var`: Height uncertainty/variance
- `properties.source`: Data source (e.g., "osm", "ms", "google")
- `properties.id`: Unique building identifier

## Data Format

The output GeoJSON follows the GlobalBuildingAtlas LOD1 schema:

```json
{
  "type": "Feature",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[...]]
  },
  "properties": {
    "source": "osm",
    "id": "12345",
    "height": 45.2,
    "var": 2.1,
    "region": "dubai"
  }
}
```

## Next Steps

Once you have the LOD1 data:
1. Use it in the 3D viewer (`smartshift/frontend/prototypes/dubai_3d_viewer.html`)
2. Calculate shadow patterns for different times of day
3. Generate heat exposure maps
4. Create optimized work schedules

## Troubleshooting

**Error: "No GeoJSON files found"**
- Ensure the data directory path is correct
- Check that LOD1 data files are actually downloaded (not just the code repository)
- The script searches for files matching `*lod1*.geojson` patterns

**Error: "ModuleNotFoundError: No module named 'fiona'"**
- Install dependencies: `pip install fiona geopandas shapely pyproj`

**No buildings extracted**
- Check that the bounding box coordinates are correct for Dubai
- Verify that the data files actually contain buildings in that region
- Try a larger bounding box to test

