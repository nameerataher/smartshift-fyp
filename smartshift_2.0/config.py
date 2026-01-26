from dataclasses import dataclass
from typing import Dict, Tuple, List


# geographic configuration

@dataclass(frozen=True)
class DubaiConfig:
    """
    Geographic and timezone configuration for Dubai.

    These values are used throughout the application for solar
    calculations and coordinate transformations.
    """
    # Dubai's geographic center (Downtown Dubai area)
    LATITUDE: float = 25.2048
    LONGITUDE: float = 55.2708

    # UAE Standard Time (UTC+4, no daylight saving)
    TIMEZONE_OFFSET: float = 4.0
    TIMEZONE_NAME: str = "Asia/Dubai"

    # Elevation above sea level (affects atmospheric calculations)
    ELEVATION_METERS: float = 5.0

    # City bounding box (approximate)
    BOUNDS_NORTH: float = 25.35
    BOUNDS_SOUTH: float = 24.85
    BOUNDS_EAST: float = 55.55
    BOUNDS_WEST: float = 54.90


# Default Dubai configuration instance
DUBAI = DubaiConfig()


# map locations - landmarks and points of interest

# Each entry contains: center (lon, lat), zoom, pitch, bearing
LANDMARK_LOCATIONS: Dict[str, Dict] = {
    "burj_khalifa": {
        "center": [55.274376, 25.197197],
        "zoom": 16.5,
        "pitch": 67,
        "bearing": -145,
        "name": "Burj Khalifa",
        "description": "World's tallest building at 828m"
    },
    "dubai_marina": {
        "center": [55.1386, 25.0805],
        "zoom": 15.5,
        "pitch": 60,
        "bearing": 45,
        "name": "Dubai Marina",
        "description": "Waterfront district with iconic towers"
    },
    "palm_jumeirah": {
        "center": [55.1380, 25.1124],
        "zoom": 14,
        "pitch": 55,
        "bearing": 0,
        "name": "Palm Jumeirah",
        "description": "Iconic palm-shaped island"
    },
    "dubai_frame": {
        "center": [55.3002, 25.2357],
        "zoom": 16,
        "pitch": 65,
        "bearing": -90,
        "name": "Dubai Frame",
        "description": "150m tall picture frame landmark"
    },
    "museum_of_future": {
        "center": [55.2805, 25.2197],
        "zoom": 17,
        "pitch": 60,
        "bearing": 45,
        "name": "Museum of the Future",
        "description": "Torus-shaped architectural marvel"
    },
    "downtown_dubai": {
        "center": [55.2708, 25.2048],
        "zoom": 15,
        "pitch": 55,
        "bearing": -20,
        "name": "Downtown Dubai",
        "description": "Central business and entertainment district"
    },
    "business_bay": {
        "center": [55.2650, 25.1850],
        "zoom": 15,
        "pitch": 55,
        "bearing": 30,
        "name": "Business Bay",
        "description": "Commercial hub with numerous skyscrapers"
    },
    "jbr": {
        "center": [55.1310, 25.0780],
        "zoom": 15.5,
        "pitch": 60,
        "bearing": -30,
        "name": "JBR - The Walk",
        "description": "Jumeirah Beach Residence waterfront"
    }
}


# shadow calculation settings

@dataclass(frozen=True)
class ShadowSettings:

    # Minimum sun altitude to calculate shadows (degrees)
    # Below this, shadows become too long and impractical
    MIN_SUN_ALTITUDE: float = 1.0

    # Maximum shadow length as multiple of building height
    # Prevents extremely long shadows at sunrise/sunset
    MAX_SHADOW_LENGTH_FACTOR: float = 10.0

    # Minimum shadow length to render (meters)
    # Shadows shorter than this are not drawn
    MIN_SHADOW_LENGTH: float = 0.5

    # Default shadow opacity range
    MIN_OPACITY: float = 0.1
    MAX_OPACITY: float = 0.7

    # Shadow color (RGBA for map rendering)
    SHADOW_COLOR: str = "rgba(0, 0, 0, 0.4)"

    # Animation settings
    DEFAULT_ANIMATION_START_HOUR: int = 6
    DEFAULT_ANIMATION_END_HOUR: int = 20
    DEFAULT_ANIMATION_INTERVAL_MINUTES: int = 30
    DEFAULT_ANIMATION_SPEED_MS: int = 500  # Milliseconds per frame


SHADOW = ShadowSettings()


# api server configuration

@dataclass(frozen=True)
class APIConfig:

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = True

    # CORS settings
    CORS_ORIGINS: List[str] = ("*",)

    # Rate limiting (requests per minute)
    RATE_LIMIT: int = 100

    # Cache settings (seconds)
    CACHE_TIMEOUT: int = 300  # 5 minutes

    # API version
    VERSION: str = "1.0.0"


API = APIConfig()


# sample building data

# Sample building data for Dubai landmarks
# In production, this would come from OpenStreetMap or a building database
SAMPLE_BUILDINGS: List[Dict] = [
    {
        "id": "burj_khalifa",
        "name": "Burj Khalifa",
        "height": 828.0,
        "footprint": [
            [55.2740, 25.1972],
            [55.2747, 25.1968],
            [55.2754, 25.1972],
            [55.2747, 25.1978],
        ]
    },
    {
        "id": "dubai_frame",
        "name": "Dubai Frame",
        "height": 150.0,
        "footprint": [
            [55.2998, 25.2354],
            [55.3006, 25.2354],
            [55.3006, 25.2360],
            [55.2998, 25.2360],
        ]
    },
    {
        "id": "museum_of_future",
        "name": "Museum of the Future",
        "height": 77.0,
        "footprint": [
            [55.2800, 25.2192],
            [55.2812, 25.2188],
            [55.2820, 25.2195],
            [55.2812, 25.2202],
        ]
    },
    {
        "id": "emirates_towers",
        "name": "Emirates Towers",
        "height": 355.0,
        "footprint": [
            [55.2820, 25.2170],
            [55.2830, 25.2170],
            [55.2830, 25.2180],
            [55.2820, 25.2180],
        ]
    },
    {
        "id": "princess_tower",
        "name": "Princess Tower",
        "height": 414.0,
        "footprint": [
            [55.1390, 25.0920],
            [55.1400, 25.0920],
            [55.1400, 25.0930],
            [55.1390, 25.0930],
        ]
    },
    {
        "id": "cayan_tower",
        "name": "Cayan Tower (Infinity Tower)",
        "height": 306.0,
        "footprint": [
            [55.1375, 25.0870],
            [55.1385, 25.0870],
            [55.1385, 25.0880],
            [55.1375, 25.0880],
        ]
    },
    {
        "id": "rose_tower",
        "name": "Rose Tower",
        "height": 333.0,
        "footprint": [
            [55.2550, 25.2250],
            [55.2560, 25.2250],
            [55.2560, 25.2260],
            [55.2550, 25.2260],
        ]
    },
    {
        "id": "address_downtown",
        "name": "Address Downtown",
        "height": 302.0,
        "footprint": [
            [55.2755, 25.1940],
            [55.2765, 25.1940],
            [55.2765, 25.1950],
            [55.2755, 25.1950],
        ]
    },
]


# ui theme configuration

@dataclass(frozen=True)
class UITheme:
    """
    UI theme colors and styles for the shadow simulation interface.
    """
    # Primary colors
    PRIMARY_BG: str = "rgba(15, 23, 42, 0.88)"
    SECONDARY_BG: str = "#1e293b"
    BORDER_COLOR: str = "#1f2937"

    # Text colors
    TEXT_PRIMARY: str = "#e2e8f0"
    TEXT_SECONDARY: str = "#94a3b8"
    TEXT_MUTED: str = "#64748b"

    # Accent colors
    ACCENT_BLUE: str = "#3b82f6"
    ACCENT_GREEN: str = "#22c55e"
    ACCENT_ORANGE: str = "#f59e0b"
    ACCENT_RED: str = "#ef4444"

    # Map overlay colors
    SHADOW_COLOR: str = "rgba(0, 0, 0, 0.4)"
    SUNLIGHT_COLOR: str = "rgba(255, 200, 100, 0.1)"


THEME = UITheme()


# heat safety thresholds (for future integration)

@dataclass(frozen=True)
class HeatSafetyConfig:
    """
    Configuration for heat safety calculations.

    These thresholds are used to determine safe working conditions
    based on temperature, humidity, and sun exposure.
    """
    # Temperature thresholds (Celsius)
    TEMP_CAUTION: float = 32.0
    TEMP_WARNING: float = 38.0
    TEMP_DANGER: float = 42.0

    # Heat index thresholds
    HEAT_INDEX_CAUTION: float = 35.0
    HEAT_INDEX_WARNING: float = 40.0
    HEAT_INDEX_DANGER: float = 48.0

    # Maximum recommended sun exposure (minutes)
    MAX_SUN_EXPOSURE_CAUTION: int = 60
    MAX_SUN_EXPOSURE_WARNING: int = 30
    MAX_SUN_EXPOSURE_DANGER: int = 15


HEAT_SAFETY = HeatSafetyConfig()


# utility functions

def get_location_config(location_key: str) -> Dict:
    """
    Get configuration for a specific landmark location.

    Args:
        location_key: Key from LANDMARK_LOCATIONS

    Returns:
        Location configuration dictionary

    Raises:
        KeyError: If location_key is not found
    """
    if location_key not in LANDMARK_LOCATIONS:
        raise KeyError(f"Unknown location: {location_key}. "
                      f"Available: {list(LANDMARK_LOCATIONS.keys())}")
    return LANDMARK_LOCATIONS[location_key]


def get_all_location_keys() -> List[str]:
    """
    Get all available location keys.

    Returns:
        List of location key strings
    """
    return list(LANDMARK_LOCATIONS.keys())


# =============================================================================
# MODULE INFO
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SmartShift Configuration Module")
    print("=" * 60)
    print(f"\nDubai Configuration:")
    print(f"  Latitude:  {DUBAI.LATITUDE}°")
    print(f"  Longitude: {DUBAI.LONGITUDE}°")
    print(f"  Timezone:  UTC+{DUBAI.TIMEZONE_OFFSET}")
    print(f"\nAvailable Landmarks: {len(LANDMARK_LOCATIONS)}")
    for key, loc in LANDMARK_LOCATIONS.items():
        print(f"  - {key}: {loc['name']}")
    print(f"\nSample Buildings: {len(SAMPLE_BUILDINGS)}")
    for bldg in SAMPLE_BUILDINGS:
        print(f"  - {bldg['name']}: {bldg['height']}m")
    print(f"\nAPI Server: http://{API.HOST}:{API.PORT}")
    print("=" * 60)


