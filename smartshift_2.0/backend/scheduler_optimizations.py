import math

# Cap samples per slot so long durations stay fast (fewer samples = faster)
MAX_SAMPLES_PER_SLOT = 18

# Minimum step is 1 min; for long slots allow up to 10 min to keep total samples low
MIN_SAMPLE_INTERVAL_MINUTES = 1
MAX_SAMPLE_INTERVAL_MINUTES = 10

# Sun cache: merge cast is expensive; reuse when sun moves < this (degrees)
SUN_AZIMUTH_BUCKET_DEG = 10
SUN_ALTITUDE_BUCKET_DEG = 5

def get_sun_bucket(azimuth: float, altitude: float) -> tuple:
    return (
        int(azimuth // SUN_AZIMUTH_BUCKET_DEG),
        int(altitude // SUN_ALTITUDE_BUCKET_DEG),
    )

def get_adaptive_sample_interval_minutes(slot_duration_minutes: int) -> int:
    if slot_duration_minutes <= 0:
        return MIN_SAMPLE_INTERVAL_MINUTES
    ideal = math.ceil(slot_duration_minutes / MAX_SAMPLES_PER_SLOT)
    interval = max(MIN_SAMPLE_INTERVAL_MINUTES, min(MAX_SAMPLE_INTERVAL_MINUTES, ideal))
    return int(interval)


def get_slot_step_for_long_duration(duration_minutes: int, default_resolution_minutes: int) -> int:
    if duration_minutes < 60:
        return default_resolution_minutes
    if duration_minutes >= 180:
        return max(default_resolution_minutes, 45)
    if duration_minutes >= 120:
        return max(default_resolution_minutes, 45)
    return default_resolution_minutes


def get_expected_samples_per_slot(slot_duration_minutes: int) -> int:
    step = get_adaptive_sample_interval_minutes(slot_duration_minutes)
    return 1 + (slot_duration_minutes // step)
