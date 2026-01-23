"""
Fetch OSM building heights for Dubai from Overpass API.

Covers the full Dubai metro area to get all tall buildings including:
- Burj Khalifa (828m)
- Marina 101 (427m)
- Princess Tower (414m)
- All downtown and Marina skyscrapers
"""

import requests
import json
from pathlib import Path

# Full Dubai metro bounding box
# South: 24.8, North: 25.4, West: 54.9, East: 55.6
BBOX = (54.9, 24.8, 55.6, 25.4)  # (west, south, east, north)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "processed" / "dubai_overpass.json"

def main():
    print(f"Fetching OSM buildings with heights for Dubai...")
    print(f"Bounding box: {BBOX}")
    
    # Overpass query for buildings with height or levels
    query = f"""
    [out:json][timeout:300];
    (
      way["building"]["height"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
      way["building"]["building:levels"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
      relation["building"]["height"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
      relation["building"]["building:levels"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
    );
    out body geom;
    """
    
    print("Querying Overpass API...")
    r = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        timeout=360,
    )
    r.raise_for_status()
    data = r.json()
    
    elements = data.get("elements", [])
    print(f"Received {len(elements)} buildings")
    
    # Count what we got
    with_height = sum(1 for el in elements if el.get("tags", {}).get("height"))
    with_levels = sum(1 for el in elements if el.get("tags", {}).get("building:levels"))
    
    print(f"  With height tag: {with_height}")
    print(f"  With levels tag: {with_levels}")
    
    # Find tallest
    heights = []
    for el in elements:
        tags = el.get("tags", {})
        h = tags.get("height", "")
        name = tags.get("name", "")
        try:
            h_val = float(str(h).replace("m", "").strip())
            heights.append((h_val, name))
        except:
            pass
    
    heights.sort(reverse=True)
    print(f"\nTop 10 tallest buildings:")
    for h, name in heights[:10]:
        # Handle Unicode for Windows console
        safe_name = (name or "(unnamed)").encode("ascii", "replace").decode()
        print(f"  {h:>6.1f}m - {safe_name}")
    
    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    print(f"\nSaved to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

