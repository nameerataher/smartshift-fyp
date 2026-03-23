#Validation tests for sun position and shadow simulation
from __future__ import annotations
from datetime import datetime
from unittest.mock import patch
import pytest
import api_server
from shadow_calculator import ShadowAnalysis

def test_sun_position_success(client):
    r = client.get("/api/sun-position", query_string={"date": "2026-06-21", "time": "12:00"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "sun" in data
    for key in ("azimuth", "altitude", "zenith", "is_daylight"):
        assert key in data["sun"]

def test_sun_position_malformed_date_falls_back(client):
    r = client.get(
        "/api/sun-position",
        query_string={"date": "not-a-date", "time": "99:xx"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True

def test_shadows_success_structure(client):
    dt = datetime(2026, 6, 21, 10, 0, 0)
    sun = api_server.solar_calculator.get_sun_position(dt)
    fake = ShadowAnalysis(timestamp=dt, sun_position=sun, shadows=[])

    with patch.object(
        api_server.shadow_calculator,
        "calculate_shadows_for_buildings",
        return_value=fake,
    ):
        r = client.get("/api/shadows", query_string={"date": "2026-06-21", "time": "10:00"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "shadows" in data
    assert data["summary"]["building_count"] >= 1

def test_animation_clamps_interval_and_hours(client):
    def _fake_analysis(buildings, dt, **kwargs):
        sun = api_server.solar_calculator.get_sun_position(dt)
        return ShadowAnalysis(timestamp=dt, sun_position=sun, shadows=[])

    with patch.object(
        api_server.shadow_calculator,
        "calculate_shadows_for_buildings",
        side_effect=_fake_analysis,
    ):
        r = client.get(
            "/api/animation",
            query_string={
                "date": "2026-06-21",
                "start_hour": "-5",
                "end_hour": "10",
                "interval": "3",
            },
        )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["interval_minutes"] >= 5
    frames = data["frames"]
    assert len(frames) >= 1
    assert "sun" in frames[0] and "shadows" in frames[0]

def test_sun_path_daylight_entries(client):
    r = client.get("/api/sun-path", query_string={"date": "2026-06-21", "interval": "60"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert isinstance(data["path"], list)

def test_shadow_at_point_requires_numeric_lat_lon(client):
    r = client.get("/api/shadow-at-point", query_string={"lat": "x", "lon": "y"})
    assert r.status_code == 400
    assert r.get_json()["success"] is False

def test_shadow_at_point_success(client):
    r = client.get(
        "/api/shadow-at-point",
        query_string={"lat": "25.2", "lon": "55.27", "date": "2026-06-21", "time": "08:00"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["point"]["lat"] == 25.2

@pytest.mark.skipif(
    not api_server.SHADOW_SCHEDULER_AVAILABLE,
    reason="shadow_scheduler not available",
)
def test_v2_sun_position_iso_time_and_result_keys(client):
    r = client.get(
        "/api/v2/sun-position",
        query_string={
            "lat": "25.2048",
            "lon": "55.2708",
            "time": "2026-06-21T10:00:00",
            "face": "N",
            "face_angle": "370",
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "location" in data

def test_parse_datetime_param_helpers():
    dt = api_server.parse_datetime_param("2026-03-01", "14:30")
    assert dt.year == 2026 and dt.month == 3 and dt.day == 1
    assert dt.hour == 14 and dt.minute == 30
    _ = api_server.parse_datetime_param(None, None)
    assert _ is not None
