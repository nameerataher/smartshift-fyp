"""
Override GlobalBuildingAtlas computed heights with raw OSM tag heights/levels.

Inputs:
  1) GBA Dubai GeoJSON (has properties: id, height, var, region, source)
  2) Raw OSM building GeoJSON export (from osmium export) that contains OSM tags

Output:
  - A new GeoJSON with added properties:
      height_gba, height_var, height_osm, levels_m, height_final, height_src
  - A CSV with building id, height_final, height_src, lat, lon

Example raw OSM export creation (osmium):
  osmium extract -b 55.25090,25.17069,55.29405,25.20328 -o dubai_bbox.pbf middleeast.osm.pbf
  osmium tags-filter dubai_bbox.pbf nwr/building -o dubai_buildings.pbf
  osmium export dubai_buildings.pbf -o dubai_osm_buildings.geojson
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _to_float_maybe(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    s = str(value).strip()
    if not s:
        return None
    # handle things like "12 m", "12m", "12.5", "12;13", "12,5"
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


def _extract_tags(props: Dict[str, Any]) -> Dict[str, Any]:
    # osmium export commonly nests tags under "tags"
    tags = props.get("tags")
    if isinstance(tags, dict):
        return tags
    # sometimes exports flatten tags directly in properties
    return props


def _extract_osm_id(props: Dict[str, Any]) -> Optional[str]:
    # GBA uses "id" as a string
    for key in ("id", "@id", "osm_id", "osmid"):
        if key in props and props[key] not in (None, ""):
            return str(props[key])
    # osmium sometimes uses type+id
    if "type" in props and "id" in props:
        return str(props["id"])
    return None


def _compute_height_from_tags(tags: Dict[str, Any], levels_to_m: float) -> Tuple[Optional[float], Optional[float], str]:
    # Returns (height_osm_m, levels_m, src)
    h = _to_float_maybe(tags.get("height"))
    if h is not None and h > 0:
        return h, None, "osm_height"
    levels = _to_float_maybe(tags.get("building:levels"))
    if levels is not None and levels > 0:
        return None, levels * levels_to_m, "osm_levels"
    return None, None, "gba"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gba", required=True, help="Path to GBA dubai_merged.geojson")
    parser.add_argument("--osm", required=True, help="Path to raw OSM buildings geojson (osmium export)")
    parser.add_argument("--out", required=True, help="Output GeoJSON path")
    parser.add_argument("--out_csv", required=True, help="Output CSV path")
    parser.add_argument("--levels_to_m", type=float, default=3.6, help="Meters per building level")
    args = parser.parse_args()

    gba_path = Path(args.gba)
    osm_path = Path(args.osm)
    out_path = Path(args.out)
    out_csv = Path(args.out_csv)

    if not gba_path.exists():
        raise SystemExit(f"GBA file not found: {gba_path}")
    if not osm_path.exists():
        raise SystemExit(f"OSM file not found: {osm_path}")

    # Fiona is used for streaming (GeoJSON is huge)
    import fiona
    from shapely.geometry import shape

    # Build OSM id -> (height_osm, levels_m, src)
    osm_lookup: Dict[str, Tuple[Optional[float], Optional[float], str]] = {}
    with fiona.open(osm_path, "r") as src:
        for feat in src:
            props = dict(feat.get("properties") or {})
            osm_id = _extract_osm_id(props)
            if not osm_id:
                continue
            tags = _extract_tags(props)
            h_osm, levels_m, src_name = _compute_height_from_tags(tags, args.levels_to_m)
            if h_osm is None and levels_m is None:
                continue
            osm_lookup[osm_id] = (h_osm, levels_m, src_name)

    # Prepare output schema (add new fields)
    with fiona.open(gba_path, "r") as gba_src:
        meta = gba_src.meta
        schema = meta["schema"]
        schema_props = dict(schema.get("properties") or {})
        schema_props.update(
            {
                "height_gba": "float",
                "height_var": "float",
                "height_osm": "float",
                "levels_m": "float",
                "height_final": "float",
                "height_src": "str",
            }
        )
        schema["properties"] = schema_props

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_csv.parent.mkdir(parents=True, exist_ok=True)

        with fiona.open(out_path, "w", driver="GeoJSON", crs=meta.get("crs"), schema=schema) as dst, open(
            out_csv, "w", newline="", encoding="utf-8"
        ) as csvf:
            writer = csv.DictWriter(csvf, fieldnames=["id", "height_final", "height_src", "lat", "lon"])
            writer.writeheader()

            for feat in gba_src:
                props = dict(feat.get("properties") or {})
                osm_id = _extract_osm_id(props)

                height_gba = _to_float_maybe(props.get("height"))
                height_var = _to_float_maybe(props.get("var"))

                height_osm = None
                levels_m = None
                height_src = "gba"

                if osm_id and osm_id in osm_lookup:
                    height_osm, levels_m, height_src = osm_lookup[osm_id]

                # Decide final height
                height_final = height_gba
                if height_src == "osm_height" and height_osm is not None:
                    height_final = height_osm
                elif height_src == "osm_levels" and levels_m is not None:
                    height_final = levels_m

                # Compute centroid lat/lon from geometry (in CRS84/WGS84 expected)
                geom = shape(feat["geometry"])
                c = geom.representative_point()
                lon, lat = c.x, c.y

                props.update(
                    {
                        "height_gba": height_gba,
                        "height_var": height_var,
                        "height_osm": height_osm,
                        "levels_m": levels_m,
                        "height_final": height_final,
                        "height_src": height_src,
                    }
                )

                feat["properties"] = props
                dst.write(feat)

                writer.writerow(
                    {
                        "id": osm_id or props.get("id"),
                        "height_final": height_final,
                        "height_src": height_src,
                        "lat": lat,
                        "lon": lon,
                    }
                )

    print(f"Wrote: {out_path}")
    print(f"Wrote: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


