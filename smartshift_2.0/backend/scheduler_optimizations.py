"""
scheduler_optimizations.py

Performance optimizations for the shadow scheduler. All scheduler-related
optimizations (adaptive sampling, caches, batching) live here so they can
be tuned in one place without cluttering the main scheduler logic.

Why long durations are slow:
- For each candidate time slot we sample at 1-min steps over the slot.
- A 30-min slot => 31 samples; a 120-min slot => 121 samples per slot.
- Each sample does: sun position + merged shadow geometry (Shapely) + coverage.
- So 120-min slots do ~4x more work per slot than 30-min slots.
"""

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
    """Discretize sun position for cache key; same bucket => reuse merged cast geometry."""
    return (
        int(azimuth // SUN_AZIMUTH_BUCKET_DEG),
        int(altitude // SUN_ALTITUDE_BUCKET_DEG),
    )


def get_adaptive_sample_interval_minutes(slot_duration_minutes: int) -> int:
    """
    Return sample interval (minutes) so we use at most MAX_SAMPLES_PER_SLOT samples
    per slot. Keeps 30-min slots at 1-min step; 120-min slots at ~3–4 min step.

    Examples:
        slot_duration 30  => 1 (31 samples)
        slot_duration 60  => 2 (31 samples)
        slot_duration 120 => 4 (31 samples)
        slot_duration 180 => 5 (37 samples, capped by MAX_SAMPLE_INTERVAL)
    """
    if slot_duration_minutes <= 0:
        return MIN_SAMPLE_INTERVAL_MINUTES
    ideal = math.ceil(slot_duration_minutes / MAX_SAMPLES_PER_SLOT)
    interval = max(MIN_SAMPLE_INTERVAL_MINUTES, min(MAX_SAMPLE_INTERVAL_MINUTES, ideal))
    return int(interval)


def get_slot_step_for_long_duration(duration_minutes: int, default_resolution_minutes: int) -> int:
    """
    When task duration is long, use a coarser slot step so we evaluate fewer slots.
    E.g. duration 120 min + default 30 => step stays 30; duration 120 + step 45 => fewer slots.
    """
    if duration_minutes < 60:
        return default_resolution_minutes
    if duration_minutes >= 180:
        return max(default_resolution_minutes, 45)
    if duration_minutes >= 120:
        return max(default_resolution_minutes, 45)
    return default_resolution_minutes


def get_expected_samples_per_slot(slot_duration_minutes: int) -> int:
    """For logging/debug: how many samples we'll take for a given slot duration."""
    step = get_adaptive_sample_interval_minutes(slot_duration_minutes)
    return 1 + (slot_duration_minutes // step)


# -----------------------------------------------------------------------------
# Implemented: sun-bucket cache in shadow_scheduler._calculate_slot_shadow_merged_area
# -----------------------------------------------------------------------------
# Future (add here when needed):
# - Parallel slots: evaluate independent slots in parallel (multiprocessing or ThreadPool).
# - Lazy slot evaluation: stop early when we have enough "good" slots if only top-N matter.
