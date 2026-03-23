#Validation tests for shade routing, segment shadows, directions modes (walk/run/cycle)
from __future__ import annotations
import json
from unittest.mock import patch
import pytest
import api_server

router_skip = pytest.mark.skipif(
    not api_server.SHADE_ROUTER_AVAILABLE,
    reason="ShadeRouter not available",
)

@router_skip
@patch("api_server.ShadeRouter")
def test_v2_shadow_route_invalid_mode_defaults_to_walking(mock_router_cls, client):
    inst = mock_router_cls.return_value
    inst.find_routes.return_value = {"success": True, "routes": []}
    client.post(
        "/api/v2/shadow-route",
        data=json.dumps(
            {
                "start_lat": 25.2,
                "start_lon": 55.27,
                "end_lat": 25.21,
                "end_lon": 55.28,
                "mode": "driving",
                "date": "2026-06-15",
                "current_minutes": 600,
            }
        ),
        content_type="application/json",
    )
    inst.find_routes.assert_called()
    kwargs = inst.find_routes.call_args.kwargs
    assert kwargs.get("mode") == "walking"

@router_skip
@patch("api_server.ShadeRouter")
def test_v2_shadow_route_accepts_walking_and_cycling(mock_router_cls, client):
    inst = mock_router_cls.return_value
    inst.find_routes.return_value = {"success": True, "routes": []}

    for mode in ("walking", "cycling"):
        r = client.post(
            "/api/v2/shadow-route",
            data=json.dumps(
                {
                    "start_lat": 25.2,
                    "start_lon": 55.27,
                    "end_lat": 25.21,
                    "end_lon": 55.28,
                    "mode": mode,
                    "date": "2026-06-15",
                    "current_minutes": 480,
                }
            ),
            content_type="application/json",
        )
        assert r.status_code == 200
        assert inst.find_routes.call_args.kwargs.get("mode") == mode

@router_skip
def test_route_segment_shadows_requires_two_points(client):
    r = client.post(
        "/api/v2/route-segment-shadows",
        data=json.dumps(
            {
                "route_coordinates": [[55.27, 25.2]],
                "departure_time": "2026-06-15T10:00:00",
                "mode": "walking",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

@router_skip
def test_route_segment_shadows_requires_departure_time(client):
    r = client.post(
        "/api/v2/route-segment-shadows",
        data=json.dumps(
            {
                "route_coordinates": [[55.27, 25.2], [55.271, 25.201]],
                "mode": "running",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

@router_skip
@patch("api_server.ShadeRouter")
def test_route_segment_shadows_accepts_z_suffix(mock_router_cls, client):
    inst = mock_router_cls.return_value
    inst.get_route_segment_shadows.return_value = {
        "segments": [{"shadow_fraction": 0.5}],
        "buildings_used": 0,
        "total_route_time_seconds": 120.0,
        "total_shade_time_seconds": 60.0,
        "weighted_shade_fraction": 0.5,
    }

    r = client.post(
        "/api/v2/route-segment-shadows",
        data=json.dumps(
            {
                "route_coordinates": [[55.27, 25.2], [55.28, 25.21]],
                "departure_time": "2026-06-15T10:00:00Z",
                "mode": "running",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True

@router_skip
@patch("api_server.ShadeRouter")
def test_routes_shade_score_invalid_mode_defaults(mock_router_cls, client):
    inst = mock_router_cls.return_value
    inst.get_route_segment_shadows.return_value = {
        "segments": [{"shadow_fraction": 1.0}],
        "total_route_time_seconds": 100.0,
        "total_shade_time_seconds": 80.0,
        "weighted_shade_fraction": 0.8,
    }

    r = client.post(
        "/api/v2/routes-shade-score",
        data=json.dumps(
            {
                "routes": [{"coordinates": [[55.27, 25.2], [55.28, 25.21]]}],
                "date": "2026-06-15",
                "current_minutes": 600,
                "mode": "invalid_mode",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    inst.get_route_segment_shadows.assert_called()
    assert inst.get_route_segment_shadows.call_args.kwargs.get("mode") == "walking"

@router_skip
@patch("api_server.ShadeRouter")
def test_routes_shade_score_requires_routes_and_date(mock_router_cls, client):
    r = client.post(
        "/api/v2/routes-shade-score",
        data=json.dumps({"date": "2026-06-15", "current_minutes": 0}),
        content_type="application/json",
    )
    assert r.status_code == 400

    r2 = client.post(
        "/api/v2/routes-shade-score",
        data=json.dumps({"routes": [{"coordinates": [[0, 0], [1, 1]]}]}),
        content_type="application/json",
    )
    assert r2.status_code == 400

@router_skip
@patch("api_server.ShadeRouter")
def test_routes_shade_score_short_route_zeros(mock_router_cls, client):
    inst = mock_router_cls.return_value
    inst.get_route_segment_shadows.return_value = {"segments": [], "total_route_time_seconds": 0}

    r = client.post(
        "/api/v2/routes-shade-score",
        data=json.dumps(
            {
                "routes": [{"coordinates": [[55.27, 25.2]]}],
                "date": "2026-06-15",
                "current_minutes": 360,
                "mode": "cycling",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200
    scores = r.get_json()["route_scores"]
    assert scores[0]["shade_pct"] == 0

@router_skip
@patch("api_server.ShadeRouter")
def test_v2_shadow_route_update_bad_user_lat_returns_400(mock_router_cls, client):
    r = client.post(
        "/api/v2/shadow-route/update",
        data=json.dumps(
            {
                "route_coordinates": [[55.27, 25.2], [55.28, 25.21]],
                "user_lat": "not-a-float",
                "user_lon": 55.27,
                "departure_time": "2026-06-15T10:00:00",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_google_directions_503_when_unavailable(client):
    if api_server.GOOGLE_DIRECTIONS_AVAILABLE and api_server.google_get_directions:
        pytest.skip("Google directions module present")
    r = client.post(
        "/api/v2/google-directions",
        data=json.dumps({"start_lat": 25.2, "start_lon": 55.27, "end_lat": 25.21, "end_lon": 55.28, "mode": "running"}),
        content_type="application/json",
    )
    assert r.status_code == 503

@patch("api_server.google_get_directions")
def test_google_directions_mode_running(mock_gdir, client):
    if not api_server.GOOGLE_DIRECTIONS_AVAILABLE:
        pytest.skip("Google directions not available")
    mock_gdir.return_value = {"success": True, "routes": []}

    client.post(
        "/api/v2/google-directions",
        data=json.dumps(
            {
                "start_lat": 25.2,
                "start_lon": 55.27,
                "end_lat": 25.21,
                "end_lon": 55.28,
                "mode": "running",
            }
        ),
        content_type="application/json",
    )
    kwargs = mock_gdir.call_args.kwargs
    assert kwargs.get("mode") == "running"

@patch("api_server.google_get_directions")
def test_google_directions_invalid_mode_defaults(mock_gdir, client):
    if not api_server.GOOGLE_DIRECTIONS_AVAILABLE:
        pytest.skip("Google directions not available")
    mock_gdir.return_value = {"success": True}

    client.post(
        "/api/v2/google-directions",
        data=json.dumps(
            {
                "start_lat": 25.2,
                "start_lon": 55.27,
                "end_lat": 25.21,
                "end_lon": 55.28,
                "mode": "scooter",
            }
        ),
        content_type="application/json",
    )
    assert mock_gdir.call_args.kwargs.get("mode") == "walking"

@patch("api_server.mapbox_get_directions")
def test_mapbox_cycling_directions_calls_cycling(mock_mbx, client):
    if not api_server.MAPBOX_DIRECTIONS_AVAILABLE:
        pytest.skip("Mapbox directions not available")
    mock_mbx.return_value = {"success": True, "routes": []}

    client.post(
        "/api/v2/mapbox-cycling-directions",
        data=json.dumps(
            {"start_lat": 25.2, "start_lon": 55.27, "end_lat": 25.21, "end_lon": 55.28}
        ),
        content_type="application/json",
    )
    kwargs = mock_mbx.call_args.kwargs
    assert kwargs.get("mode") == "cycling"
