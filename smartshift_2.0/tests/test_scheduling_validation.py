#Validation tests for polygon area scheduling and facade recommendations
from __future__ import annotations
import json
from unittest.mock import MagicMock, patch
import pytest
import api_server

pytestmark = pytest.mark.skipif(
    not api_server.SHADOW_SCHEDULER_AVAILABLE,
    reason="shadow_scheduler not available",
)

def test_schedule_area_requires_three_vertices(client):
    r = client.post(
        "/api/v2/schedule/area",
        data=json.dumps({"polygon_points": [[25.0, 55.0], [25.01, 55.01]]}),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "polygon" in r.get_json().get("error", "").lower()

def test_schedule_area_rejects_non_numeric_polygon(client):
    r = client.post(
        "/api/v2/schedule/area",
        data=json.dumps(
            {
                "polygon_points": [[25.0, 55.0], ["a", 55.0], [25.01, 55.02]],
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_schedule_area_success_with_client_buildings(client, sample_polygon_points, sample_client_buildings):
    r = client.post(
        "/api/v2/schedule/area",
        data=json.dumps(
            {
                "task_name": "Unit test area task",
                "polygon_points": sample_polygon_points,
                "location_name": "Test zone",
                "task_duration_minutes": 60,
                "date": "2026-06-15",
                "start_hour": 6,
                "end_hour": 18,
                "recommendation_count": 3,
                "buildings": sample_client_buildings,
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["success"] is True
    assert data["mode"] == "area_grid"
    assert "recommendation" in data
    assert data["recommendation"].get("task_name") == "Unit test area task"

def test_facade_recommend_invalid_start_time(client):
    r = client.post(
        "/api/v2/facade-recommend-time",
        data=json.dumps(
            {
                "lat": 25.2048,
                "lon": 55.2708,
                "date": "2026-06-15",
                "duration_minutes": 60,
                "start_hour": 24,
                "start_minute": 0,
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_facade_recommend_zero_duration_valueerror(client):
    r = client.post(
        "/api/v2/facade-recommend-time",
        data=json.dumps(
            {
                "lat": 25.2048,
                "lon": 55.2708,
                "date": "2026-06-15",
                "duration_minutes": 0,
                "start_time": "09:00",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_facade_recommend_hhmm_success(client, sample_client_buildings):
    r = client.post(
        "/api/v2/facade-recommend-time",
        data=json.dumps(
            {
                "lat": 25.205,
                "lon": 55.271,
                "date": "2026-06-15",
                "duration_minutes": 120,
                "start_time": "08:30",
                "buildings": sample_client_buildings,
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert "ranking" in data or "facades" in data or "recommended" in data

def test_shadow_schedule_maps_cardinal_to_face_angle(client, sample_client_buildings):
    r = client.post(
        "/api/v2/shadow-schedule",
        data=json.dumps(
            {
                "task_name": "Facade test",
                "lat": 25.205,
                "lon": 55.271,
                "location_name": "Test",
                "duration_minutes": 60,
                "date": "2026-06-15",
                "start_hour": 6,
                "end_hour": 12,
                "building_face": "E",
                "buildings": sample_client_buildings,
                "include_all_slots": False,
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    rec = data.get("recommendation", {})
    assert rec.get("task_name") == "Facade test"

@patch("api_server.ShadowScheduler")
def test_v2_schedule_post_uses_scheduler(mock_sched_class, client):
    """Avoid live Tilequery: mock ShadowScheduler.find_optimal_schedule."""
    mock_rec = MagicMock()
    mock_rec.to_dict.return_value = {"task_name": "Point schedule", "best": "mock"}
    mock_sched_class.return_value.find_optimal_schedule.return_value = mock_rec

    r = client.post(
        "/api/v2/schedule",
        data=json.dumps(
            {
                "task_name": "Point schedule",
                "task_duration_minutes": 60,
                "date": "2026-06-15",
                "start_hour": 6,
                "end_hour": 20,
                "work_zone": {"lat": 25.205, "lon": 55.271, "name": "Site"},
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["recommendation"]["task_name"] == "Point schedule"
