#API validation tests for auth, saved places, and tasks CRUD
from __future__ import annotations
import json
import uuid
from unittest.mock import patch
import pytest
import api_server

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json().get("status") == "healthy"

def test_login_requires_email_password(client):
    r = client.post("/api/auth/login", data=json.dumps({}), content_type="application/json")
    assert r.status_code == 400

def test_login_invalid_credentials(client):
    r = client.post(
        "/api/auth/login",
        data=json.dumps({"email": "nobody@example.com", "password": "wrong"}),
        content_type="application/json",
    )
    assert r.status_code == 401

def test_register_requires_fields(client):
    r = client.post(
        "/api/auth/register",
        data=json.dumps({"email": "a@b.com", "password": "x"}),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_register_and_login_roundtrip(client):
    email = f"pytest_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/auth/register",
        data=json.dumps(
            {"email": email, "password": "secret123", "display_name": "Py Test", "user_type": "personal"}
        ),
        content_type="application/json",
    )
    assert reg.status_code == 200
    uid = reg.get_json()["user"]["user_id"]

    dup = client.post(
        "/api/auth/register",
        data=json.dumps(
            {"email": email, "password": "x", "display_name": "Dup", "user_type": "personal"}
        ),
        content_type="application/json",
    )
    assert dup.status_code == 409

    login = client.post(
        "/api/auth/login",
        data=json.dumps({"email": email, "password": "secret123"}),
        content_type="application/json",
    )
    assert login.status_code == 200
    assert login.get_json()["user"]["user_id"] == uid

def test_auth_me_requires_header(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401

def test_saved_places_empty_without_user(client):
    r = client.get("/api/saved-places")
    assert r.status_code == 200
    assert r.get_json()["places"] == []

def test_saved_place_create_delete_scoped(client):
    email = f"place_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/auth/register",
        data=json.dumps(
            {"email": email, "password": "p", "display_name": "P", "user_type": "personal"}
        ),
        content_type="application/json",
    )
    uid = reg.get_json()["user"]["user_id"]

    cre = client.post(
        "/api/saved-places",
        data=json.dumps({"name": "Spot", "lat": 25.2, "lon": 55.27}),
        content_type="application/json",
        headers={"X-User-Id": uid},
    )
    assert cre.status_code == 200
    pid = cre.get_json()["place_id"]

    lst = client.get("/api/saved-places", headers={"X-User-Id": uid})
    assert len(lst.get_json()["places"]) >= 1

    bad_del = client.delete(f"/api/saved-places/{pid}", headers={"X-User-Id": "wrong-user"})
    assert bad_del.status_code == 404

    ok_del = client.delete(f"/api/saved-places/{pid}", headers={"X-User-Id": uid})
    assert ok_del.status_code == 200

@patch("api_server._task_end_is_in_past", return_value=True)
def test_create_task_rejects_past_non_completed(_mock_past, client):
    r = client.post(
        "/api/tasks",
        data=json.dumps(
            {
                "task_name": "Past task",
                "date": "2030-01-05",
                "hour_end": 10,
                "hour_start": 8,
                "status": "draft",
                "duration_minutes": 60,
                "location_lat": 25.2,
                "location_lon": 55.27,
                "location_name": "X",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert "past" in r.get_json().get("error", "").lower()

@patch("api_server._task_end_is_in_past", return_value=True)
def test_create_task_allows_completed_in_past(_mock_past, client):
    r = client.post(
        "/api/tasks",
        data=json.dumps(
            {
                "task_name": "Done old",
                "date": "2030-01-05",
                "hour_end": 10,
                "hour_start": 8,
                "status": "completed",
                "duration_minutes": 60,
                "location_lat": 25.2,
                "location_lon": 55.27,
                "location_name": "X",
            }
        ),
        content_type="application/json",
    )
    assert r.status_code == 200

def test_update_task_no_valid_fields(client):
    tid = f"task_ut_{uuid.uuid4().hex[:10]}"
    client.post(
        "/api/tasks",
        data=json.dumps(
            {
                "task_id": tid,
                "task_name": "Updatable",
                "date": "2035-06-01",
                "hour_start": 9,
                "hour_end": 17,
                "duration_minutes": 60,
                "location_lat": 25.2,
                "location_lon": 55.27,
                "location_name": "Y",
                "status": "draft",
            }
        ),
        content_type="application/json",
    )
    r = client.put(
        f"/api/tasks/{tid}",
        data=json.dumps({"not_a_field": 1}),
        content_type="application/json",
    )
    assert r.status_code == 400

def test_task_crud_roundtrip(client):
    tid = f"task_crud_{uuid.uuid4().hex[:10]}"
    post = client.post(
        "/api/tasks",
        data=json.dumps(
            {
                "task_id": tid,
                "task_name": "CRUD",
                "date": "2035-07-01",
                "hour_start": 8,
                "hour_end": 12,
                "duration_minutes": 120,
                "location_lat": 25.2,
                "location_lon": 55.27,
                "location_name": "Site",
                "analysis_mode": "facade",
                "work_zone_polygon": "[]",
            }
        ),
        content_type="application/json",
    )
    assert post.status_code == 200

    get_r = client.get(f"/api/tasks/{tid}")
    assert get_r.status_code == 200
    assert get_r.get_json()["task"]["task_name"] == "CRUD"

    put_r = client.put(
        f"/api/tasks/{tid}",
        data=json.dumps({"task_name": "Renamed", "analysis_mode": "workzone"}),
        content_type="application/json",
    )
    assert put_r.status_code == 200

    get2 = client.get(f"/api/tasks/{tid}")
    assert get2.get_json()["task"]["task_name"] == "Renamed"

    del_r = client.delete(f"/api/tasks/{tid}")
    assert del_r.status_code == 200
    assert client.get(f"/api/tasks/{tid}").status_code == 404

def test_complete_nonexistent_task_still_success(client):
    r = client.post(f"/api/tasks/nonexistent_{uuid.uuid4().hex}/complete")
    assert r.status_code == 200
    assert r.get_json()["success"] is True

def test_get_task_not_found(client):
    assert client.get(f"/api/tasks/missing_{uuid.uuid4().hex}").status_code == 404

def test_task_end_is_in_past_helper():
    assert api_server._task_end_is_in_past("2035-01-01", 23) is False
    assert api_server._task_end_is_in_past("2000-01-01", 23) is True
