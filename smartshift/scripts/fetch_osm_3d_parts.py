"""
Fetch OSM building:part data for Dubai - these are detailed 3D building components.

OSM Simple 3D Buildings schema allows modeling complex buildings with:
- building:part=yes (sub-components of buildings)
- roof:shape (dome, pyramidal, etc.)
- height, min_height (per-part heights)

This can give us LOD2-like detail for some buildings.
"""

import requests
import json
from pathlib import Path

# Focus on Downtown Dubai where complex buildings are
BBOX = (55.26, 25.18, 55.30, 25.22)  # (west, south, east, north)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "processed" / "dubai_3d_parts.json"


def main():
    print(f"Fetching OSM building:part data for Dubai...")
    print(f"Bounding box: {BBOX}")
    
    # Query for building:part elements
    query = f"""
    [out:json][timeout:300];
    (
      way["building:part"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
      relation["building:part"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
      way["building"]["roof:shape"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});
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
    print(f"Received {len(elements)} 3D building parts")
    
    if elements:
        # Analyze what we got
        with_height = sum(1 for el in elements if el.get("tags", {}).get("height"))
        with_min_height = sum(1 for el in elements if el.get("tags", {}).get("min_height"))
        with_roof = sum(1 for el in elements if el.get("tags", {}).get("roof:shape"))
        
        print(f"  With height: {with_height}")
        print(f"  With min_height: {with_min_height}")
        print(f"  With roof:shape: {with_roof}")
        
        # Show some examples
        print("\nSample building parts:")
        for el in elements[:10]:
            tags = el.get("tags", {})
            name = tags.get("name", "")
            h = tags.get("height", "-")
            min_h = tags.get("min_height", "-")
            roof = tags.get("roof:shape", "-")
            safe_name = (name or "(unnamed)").encode("ascii", "replace").decode()[:40]
            print(f"  height={h}, min_height={min_h}, roof={roof}, name={safe_name}")
    
    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    print(f"\nSaved to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

