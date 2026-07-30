import os
from typing import Optional


def get_mapbox_token(override: Optional[str] = None) -> str:
    """Return Mapbox access token from override, then MAPBOX_ACCESS_TOKEN env."""
    if override and str(override).strip():
        return str(override).strip()
    return os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
