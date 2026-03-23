"""
Shared pytest fixtures: temp SQLite DB, Flask app, and scheduling test data.

Must set database.DB_PATH before importing api_server (init_db runs on import).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("USE_POSTGRES", "false")

_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_fd)

import database  # noqa: E402

database.DB_PATH = _TEST_DB_PATH
database.init_database()

import api_server  # noqa: E402

api_server.DB_PATH = database.DB_PATH


@pytest.fixture
def app():
    api_server.app.config.update(TESTING=True)
    return api_server.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def sample_polygon_points():
    return [
        [25.2040, 55.2700],
        [25.2060, 55.2700],
        [25.2060, 55.2720],
        [25.2040, 55.2720],
    ]


@pytest.fixture
def sample_client_buildings():
    return [
        {
            "id": "test_bldg_1",
            "name": "Test Tower",
            "height": 45.0,
            "footprint": [
                [55.2705, 25.2045],
                [55.2715, 25.2045],
                [55.2715, 25.2055],
                [55.2705, 25.2055],
            ],
        }
    ]


def pytest_sessionfinish(session, exitstatus):
    try:
        os.unlink(_TEST_DB_PATH)
    except OSError:
        pass
