"""
Split a large GeoJSON FeatureCollection into multiple smaller FeatureCollections,
without third-party deps (no ijson required).

This is a streaming splitter that scans for the top-level "features": [ ... ] array
and then extracts each feature object by brace matching, respecting strings.

Usage (PowerShell):
  python smartshift/scripts/split_geojson_featurecollection.py ^
    --in smartshift/data/gba_dubai/dubai_merged.geojson ^
    --out_dir smartshift/data/gba_dubai ^
    --prefix dubai_p ^
    --chunk_size 5000
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator, Optional


def iter_top_level_feature_objects(path: Path, *, buf_size: int = 1024 * 1024) -> Iterator[str]:
    """
    Yield each top-level feature object JSON string from a GeoJSON FeatureCollection.
    Assumes the file contains a top-level key "features" whose value is an array of objects.
    """
    with path.open("r", encoding="utf-8") as f:
        # Find the start of the features array: ..."features": [
        window = ""
        found = False
        while True:
            chunk = f.read(buf_size)
            if not chunk:
                break
            window += chunk
            idx = window.find('"features"')
            if idx != -1:
                # find the '[' after "features"
                bracket = window.find("[", idx)
                if bracket != -1:
                    window = window[bracket + 1 :]
                    found = True
                    break
            # keep tail to avoid unbounded growth
            window = window[-2000:]

        if not found:
            raise ValueError('Could not find top-level "features" array')

        # Now parse objects within the features array.
        in_str = False
        esc = False
        depth = 0
        obj_start: Optional[int] = None

        while True:
            if not window:
                chunk = f.read(buf_size)
                if not chunk:
                    break
                window = chunk

            i = 0
            while i < len(window):
                ch = window[i]

                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    i += 1
                    continue

                # not in string
                if ch == '"':
                    in_str = True
                    i += 1
                    continue

                if ch == "{":
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and obj_start is not None:
                        obj = window[obj_start : i + 1]
                        yield obj
                        obj_start = None
                elif ch == "]" and depth == 0:
                    # end of features array
                    return

                i += 1

            # If we are mid-object, keep only from its start; else clear buffer.
            if obj_start is not None:
                window = window[obj_start:]
                obj_start = 0
            else:
                window = ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True, help="Input GeoJSON FeatureCollection")
    ap.add_argument("--out_dir", required=True, help="Output directory")
    ap.add_argument("--prefix", default="part_", help="Filename prefix (e.g., dubai_p)")
    ap.add_argument("--chunk_size", type=int, default=5000, help="Features per output file")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chunk = []
    part = 0
    total = 0

    def flush():
        nonlocal part, chunk
        out_path = out_dir / f"{args.prefix}{part:03d}.geojson"
        out_path.write_text(
            json.dumps({"type": "FeatureCollection", "features": [json.loads(x) for x in chunk]}),
            encoding="utf-8",
        )
        part += 1
        chunk = []

    for obj in iter_top_level_feature_objects(in_path):
        chunk.append(obj)
        total += 1
        if len(chunk) >= args.chunk_size:
            flush()

    if chunk:
        flush()

    print(f"Split {total} features into {part} files in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


