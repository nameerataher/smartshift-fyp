"""
database.py - PostgreSQL Database Configuration and Models

This module provides database connectivity and ORM models for the SmartShift system.
Supports both PostgreSQL (production) and SQLite (development fallback).
"""

import os
import hashlib
import secrets
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
import uuid
import json

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("Warning: psycopg2 not available. Install with: pip install psycopg2-binary")

import sqlite3

DATABASE_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", 5432)),
    "database": os.environ.get("DB_NAME", "smartshift"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "postgres"),
}

USE_POSTGRES = os.environ.get("USE_POSTGRES", "false").lower() == "true" and POSTGRES_AVAILABLE
DB_PATH = os.path.join(os.path.dirname(__file__), "smartshift.db")


def get_connection():
    """Get database connection based on configuration."""
    if USE_POSTGRES:
        return psycopg2.connect(
            host=DATABASE_CONFIG["host"],
            port=DATABASE_CONFIG["port"],
            database=DATABASE_CONFIG["database"],
            user=DATABASE_CONFIG["user"],
            password=DATABASE_CONFIG["password"],
            cursor_factory=RealDictCursor
        )
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def get_placeholder():
    """Return placeholder syntax based on database type."""
    return "%s" if USE_POSTGRES else "?"


def hash_password(password: str, salt: str = None) -> tuple:
    """Hash a password with a salt using SHA-256."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return hashed, salt


@dataclass
class User:
    """User account."""
    user_id: str
    email: str
    password_hash: str
    salt: str
    display_name: str
    user_type: str = "personal"  # personal or commercial
    organization: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SavedPlace:
    """User's saved quick-access place."""
    id: str
    user_id: str
    name: str
    lat: float
    lon: float
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UserTask:
    """User-entered task details."""
    task_id: str
    task_name: str
    location_name: str
    location_lat: float
    location_lon: float
    duration_minutes: int
    hour_start: int
    hour_end: int
    date: str
    status: str = "draft"
    user_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AcceptedRecommendation:
    """Recommendation accepted by user."""
    id: str
    task_id: str
    accepted_time_start: str
    accepted_time_end: str
    shade_percentage: float
    shade_slot: str
    completed_status: bool = False
    accepted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None


@dataclass
class WorkAnalytics:
    """Monthly work analytics data."""
    id: str
    month: str  # YYYY-MM format
    total_tasks: int = 0
    completed_tasks: int = 0
    total_duration_minutes: int = 0
    avg_shade_coverage: float = 0.0
    target_tasks: int = 100
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


def init_database():
    """Initialize database with all required tables."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    if USE_POSTGRES:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(255) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                salt VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                user_type VARCHAR(50) DEFAULT 'personal',
                organization VARCHAR(255) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saved_places (
                id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255) REFERENCES users(user_id),
                name VARCHAR(255) NOT NULL,
                lat DECIMAL(10, 6) NOT NULL,
                lon DECIMAL(10, 6) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS route_history (
                id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255),
                start_lat DECIMAL(10, 6),
                start_lon DECIMAL(10, 6),
                end_lat DECIMAL(10, 6),
                end_lon DECIMAL(10, 6),
                start_name VARCHAR(500),
                end_name VARCHAR(500),
                travel_mode VARCHAR(50),
                distance_km DECIMAL(10, 2),
                duration_min DECIMAL(10, 1),
                shade_coverage DECIMAL(5, 2),
                heat_risk_score DECIMAL(5, 2),
                route_geometry TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                task_id VARCHAR(255) PRIMARY KEY,
                task_name VARCHAR(500) NOT NULL,
                location_name VARCHAR(500),
                location_lat DECIMAL(10, 6),
                location_lon DECIMAL(10, 6),
                duration_minutes INTEGER NOT NULL,
                hour_start INTEGER NOT NULL,
                hour_end INTEGER NOT NULL,
                date DATE NOT NULL,
                status VARCHAR(50) DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id VARCHAR(255) DEFAULT ''
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS accepted_recommendations (
                id VARCHAR(255) PRIMARY KEY,
                task_id VARCHAR(255) REFERENCES user_tasks(task_id) ON DELETE CASCADE,
                accepted_time_start VARCHAR(10) NOT NULL,
                accepted_time_end VARCHAR(10) NOT NULL,
                shade_percentage DECIMAL(5, 2),
                shade_slot VARCHAR(100),
                completed_status BOOLEAN DEFAULT FALSE,
                accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS work_analytics (
                id VARCHAR(255) PRIMARY KEY,
                month VARCHAR(7) NOT NULL UNIQUE,
                total_tasks INTEGER DEFAULT 0,
                completed_tasks INTEGER DEFAULT 0,
                total_duration_minutes INTEGER DEFAULT 0,
                avg_shade_coverage DECIMAL(5, 2) DEFAULT 0,
                target_tasks INTEGER DEFAULT 100,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Legacy tables for backward compatibility
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_requests (
                id VARCHAR(255) PRIMARY KEY,
                task_name VARCHAR(500),
                lat DECIMAL(10, 6),
                lon DECIMAL(10, 6),
                date DATE,
                start_hour INTEGER,
                end_hour INTEGER,
                duration_minutes INTEGER,
                recommended_start VARCHAR(10),
                recommended_end VARCHAR(10),
                heat_risk_score DECIMAL(5, 4),
                shade_percentage DECIMAL(5, 2),
                quality_score DECIMAL(5, 2),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_feedback (
                id VARCHAR(255) PRIMARY KEY,
                request_id VARCHAR(255) REFERENCES schedule_requests(id),
                action VARCHAR(50),
                chosen_start VARCHAR(10),
                chosen_end VARCHAR(10),
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                display_name TEXT NOT NULL,
                user_type TEXT DEFAULT 'personal',
                organization TEXT DEFAULT '',
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saved_places (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                created_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS route_history (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                start_lat REAL,
                start_lon REAL,
                end_lat REAL,
                end_lon REAL,
                start_name TEXT,
                end_name TEXT,
                travel_mode TEXT,
                distance_km REAL,
                duration_min REAL,
                shade_coverage REAL,
                heat_risk_score REAL,
                route_geometry TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                task_id TEXT PRIMARY KEY,
                task_name TEXT NOT NULL,
                location_name TEXT,
                location_lat REAL,
                location_lon REAL,
                duration_minutes INTEGER NOT NULL,
                hour_start INTEGER NOT NULL,
                hour_end INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                created_at TEXT,
                updated_at TEXT,
                user_id TEXT DEFAULT ''
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS accepted_recommendations (
                id TEXT PRIMARY KEY,
                task_id TEXT REFERENCES user_tasks(task_id),
                accepted_time_start TEXT NOT NULL,
                accepted_time_end TEXT NOT NULL,
                shade_percentage REAL,
                shade_slot TEXT,
                completed_status INTEGER DEFAULT 0,
                accepted_at TEXT,
                completed_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS work_analytics (
                id TEXT PRIMARY KEY,
                month TEXT NOT NULL UNIQUE,
                total_tasks INTEGER DEFAULT 0,
                completed_tasks INTEGER DEFAULT 0,
                total_duration_minutes INTEGER DEFAULT 0,
                avg_shade_coverage REAL DEFAULT 0,
                target_tasks INTEGER DEFAULT 100,
                updated_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_requests (
                id TEXT PRIMARY KEY,
                task_name TEXT,
                lat REAL,
                lon REAL,
                date TEXT,
                start_hour INTEGER,
                end_hour INTEGER,
                duration_minutes INTEGER,
                recommended_start TEXT,
                recommended_end TEXT,
                heat_risk_score REAL,
                shade_percentage REAL,
                quality_score REAL,
                created_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_feedback (
                id TEXT PRIMARY KEY,
                request_id TEXT,
                action TEXT,
                chosen_start TEXT,
                chosen_end TEXT,
                note TEXT,
                created_at TEXT,
                FOREIGN KEY(request_id) REFERENCES schedule_requests(id)
            )
        """)

    conn.commit()
    conn.close()
    print(f"[OK] Database initialized ({'PostgreSQL' if USE_POSTGRES else 'SQLite'})")


# ============================================================================
# User Auth Operations
# ============================================================================

def create_user(user: User) -> str:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    try:
        cur.execute(f"""
            INSERT INTO users (user_id, email, password_hash, salt, display_name, user_type, organization, created_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (user.user_id, user.email, user.password_hash, user.salt,
              user.display_name, user.user_type, user.organization, user.created_at))
        conn.commit()
    finally:
        conn.close()
    return user.user_id


def get_user_by_email(email: str) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    cur.execute(f"SELECT * FROM users WHERE email = {ph}", (email,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    cur.execute(f"SELECT * FROM users WHERE user_id = {ph}", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def authenticate_user(email: str, password: str) -> Optional[Dict]:
    user = get_user_by_email(email)
    if not user:
        return None
    hashed, _ = hash_password(password, user["salt"])
    if hashed == user["password_hash"]:
        return user
    return None


def update_user(user_id: str, updates: Dict) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    set_clause = ", ".join([f"{k} = {ph}" for k in updates.keys()])
    values = list(updates.values()) + [user_id]
    cur.execute(f"UPDATE users SET {set_clause} WHERE user_id = {ph}", values)
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


# ============================================================================
# Saved Places Operations
# ============================================================================

def create_saved_place(place: SavedPlace) -> str:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    cur.execute(f"""
        INSERT INTO saved_places (id, user_id, name, lat, lon, created_at)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})
    """, (place.id, place.user_id, place.name, place.lat, place.lon, place.created_at))
    conn.commit()
    conn.close()
    return place.id


def get_saved_places(user_id: str) -> List[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    cur.execute(f"SELECT * FROM saved_places WHERE user_id = {ph} ORDER BY created_at DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_saved_place(place_id: str, user_id: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    cur.execute(f"DELETE FROM saved_places WHERE id = {ph} AND user_id = {ph}", (place_id, user_id))
    affected = cur.rowcount
    conn.commit()
    conn.close()
    return affected > 0


# ============================================================================
# Task CRUD Operations
# ============================================================================

def create_task(task: UserTask) -> str:
    """Create a new task."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"""
        INSERT INTO user_tasks
        (task_id, task_name, location_name, location_lat, location_lon,
         duration_minutes, hour_start, hour_end, date, status, created_at, updated_at, user_id)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
    """, (
        task.task_id, task.task_name, task.location_name, task.location_lat,
        task.location_lon, task.duration_minutes, task.hour_start, task.hour_end,
        task.date, task.status, task.created_at, task.updated_at,
        getattr(task, 'user_id', None) or ''
    ))

    conn.commit()
    conn.close()
    return task.task_id


def get_task(task_id: str) -> Optional[Dict]:
    """Get a task by ID."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"SELECT * FROM user_tasks WHERE task_id = {ph}", (task_id,))
    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None


def get_all_tasks(date_filter: Optional[str] = None, status_filter: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict]:
    """Get all tasks, optionally filtered by date, status, or user_id."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    query = "SELECT * FROM user_tasks"
    params = []
    conditions = []

    if user_id:
        conditions.append(f"user_id = {ph}")
        params.append(user_id)

    if date_filter:
        conditions.append(f"date = {ph}")
        params.append(date_filter)

    if status_filter:
        conditions.append(f"status = {ph}")
        params.append(status_filter)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY date DESC, created_at DESC"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_today_tasks(user_id: Optional[str] = None) -> List[Dict]:
    """Get tasks for today."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_all_tasks(date_filter=today, user_id=user_id)


def update_task(task_id: str, updates: Dict) -> bool:
    """Update a task."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    updates["updated_at"] = datetime.now().isoformat()

    set_clause = ", ".join([f"{k} = {ph}" for k in updates.keys()])
    values = list(updates.values()) + [task_id]

    cur.execute(f"UPDATE user_tasks SET {set_clause} WHERE task_id = {ph}", values)
    affected = cur.rowcount
    conn.commit()
    conn.close()

    return affected > 0


def delete_task(task_id: str) -> bool:
    """Delete a task."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"DELETE FROM user_tasks WHERE task_id = {ph}", (task_id,))
    affected = cur.rowcount
    conn.commit()
    conn.close()

    return affected > 0


# ============================================================================
# Accepted Recommendations
# ============================================================================

def create_accepted_recommendation(rec: AcceptedRecommendation) -> str:
    """Create a new accepted recommendation."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"""
        INSERT INTO accepted_recommendations
        (id, task_id, accepted_time_start, accepted_time_end, shade_percentage,
         shade_slot, completed_status, accepted_at)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
    """, (
        rec.id, rec.task_id, rec.accepted_time_start, rec.accepted_time_end,
        rec.shade_percentage, rec.shade_slot, rec.completed_status, rec.accepted_at
    ))

    conn.commit()
    conn.close()
    return rec.id


def get_recommendation_by_task(task_id: str) -> Optional[Dict]:
    """Get accepted recommendation for a task."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"SELECT * FROM accepted_recommendations WHERE task_id = {ph}", (task_id,))
    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None


def mark_task_completed(task_id: str) -> bool:
    """Mark a task and its recommendation as completed."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()
    now = datetime.now().isoformat()

    cur.execute(f"UPDATE user_tasks SET status = 'completed', updated_at = {ph} WHERE task_id = {ph}", (now, task_id))
    cur.execute(f"UPDATE accepted_recommendations SET completed_status = {ph}, completed_at = {ph} WHERE task_id = {ph}",
                (True if USE_POSTGRES else 1, now, task_id))

    conn.commit()
    conn.close()

    # Update analytics
    update_analytics_for_month(datetime.now().strftime("%Y-%m"))
    return True


# ============================================================================
# Work Analytics
# ============================================================================

def get_analytics(month: str) -> Optional[Dict]:
    """Get analytics for a specific month."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    cur.execute(f"SELECT * FROM work_analytics WHERE month = {ph}", (month,))
    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None


def get_analytics_range(months: int = 4) -> List[Dict]:
    """Get analytics for the past N months."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM work_analytics
        ORDER BY month DESC
        LIMIT ?
    """.replace("?", get_placeholder()), (months,))

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def update_analytics_for_month(month: str) -> Dict:
    """Update analytics for a specific month based on actual data."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    # Calculate stats from user_tasks
    cur.execute(f"""
        SELECT
            COUNT(*) as total_tasks,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
            COALESCE(SUM(duration_minutes), 0) as total_duration
        FROM user_tasks
        WHERE date LIKE {ph}
    """, (f"{month}%",))

    stats = cur.fetchone()
    total_tasks = stats["total_tasks"] if stats else 0
    completed_tasks = stats["completed_tasks"] if stats else 0
    total_duration = stats["total_duration"] if stats else 0

    # Calculate average shade coverage
    cur.execute(f"""
        SELECT AVG(ar.shade_percentage) as avg_shade
        FROM accepted_recommendations ar
        JOIN user_tasks ut ON ar.task_id = ut.task_id
        WHERE ut.date LIKE {ph}
    """, (f"{month}%",))

    shade_row = cur.fetchone()
    avg_shade = shade_row["avg_shade"] if shade_row and shade_row["avg_shade"] else 0

    # Upsert analytics
    analytics_id = f"analytics_{month}"
    now = datetime.now().isoformat()

    if USE_POSTGRES:
        cur.execute(f"""
            INSERT INTO work_analytics
            (id, month, total_tasks, completed_tasks, total_duration_minutes, avg_shade_coverage, updated_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            ON CONFLICT (month) DO UPDATE SET
                total_tasks = EXCLUDED.total_tasks,
                completed_tasks = EXCLUDED.completed_tasks,
                total_duration_minutes = EXCLUDED.total_duration_minutes,
                avg_shade_coverage = EXCLUDED.avg_shade_coverage,
                updated_at = EXCLUDED.updated_at
        """, (analytics_id, month, total_tasks, completed_tasks, total_duration, avg_shade, now))
    else:
        cur.execute(f"""
            INSERT OR REPLACE INTO work_analytics
            (id, month, total_tasks, completed_tasks, total_duration_minutes, avg_shade_coverage, updated_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        """, (analytics_id, month, total_tasks, completed_tasks, total_duration, avg_shade, now))

    conn.commit()
    conn.close()

    return {
        "month": month,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "total_duration_minutes": total_duration,
        "avg_shade_coverage": round(avg_shade, 1) if avg_shade else 0
    }


def get_dashboard_summary(user_id: Optional[str] = None) -> Dict:
    """Get summary data for dashboard."""
    today = datetime.now().strftime("%Y-%m-%d")

    today_tasks = get_today_tasks(user_id=user_id)

    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    if user_id:
        cur.execute(f"SELECT COALESCE(SUM(duration_minutes), 0) as total FROM user_tasks WHERE user_id = {ph}", (user_id,))
    else:
        cur.execute("SELECT COALESCE(SUM(duration_minutes), 0) as total FROM user_tasks")
    total_duration = cur.fetchone()["total"]

    if user_id:
        cur.execute(f"SELECT COUNT(*) as count FROM user_tasks WHERE status = 'completed' AND user_id = {ph}", (user_id,))
    else:
        cur.execute("SELECT COUNT(*) as count FROM user_tasks WHERE status = 'completed'")
    completed_count = cur.fetchone()["count"]

    cur.execute("SELECT AVG(shade_percentage) as avg FROM accepted_recommendations")
    avg_shade_row = cur.fetchone()
    avg_shade = round(avg_shade_row["avg"], 1) if avg_shade_row and avg_shade_row["avg"] else 0

    conn.close()

    return {
        "today_tasks": today_tasks,
        "today_task_count": len(today_tasks),
        "total_duration_minutes": total_duration,
        "completed_count": completed_count,
        "avg_shade_coverage": avg_shade,
        "scheduled_count": len([t for t in today_tasks if t["status"] == "scheduled"]),
        "in_process_count": len([t for t in today_tasks if t["status"] == "in-process"]),
    }


# ============================================================================
# Seed dummy data for testing
# ============================================================================

def seed_dummy_data():
    """Insert dummy data for development/testing including users."""
    conn = get_connection()
    cur = conn.cursor()
    ph = get_placeholder()

    # Check if users exist already
    cur.execute("SELECT COUNT(*) as count FROM users")
    user_count = cur.fetchone()["count"]
    conn.close()

    if user_count == 0:
        # Create dummy users
        dummy_users = [
            ("user_commercial_1", "ahmed@constructco.com", "password123", "Ahmed Al-Rashid", "commercial", "ConstructCo LLC"),
            ("user_commercial_2", "sara@buildfast.com", "password123", "Sara Khan", "commercial", "BuildFast Industries"),
            ("user_personal_1", "mike@gmail.com", "password123", "Mike Johnson", "personal", ""),
            ("user_personal_2", "fatima@outlook.com", "password123", "Fatima Noor", "personal", ""),
        ]
        for uid, email, pwd, name, utype, org in dummy_users:
            hashed, salt = hash_password(pwd)
            create_user(User(
                user_id=uid, email=email, password_hash=hashed, salt=salt,
                display_name=name, user_type=utype, organization=org
            ))

        # Saved places for users
        default_places = [
            SavedPlace(id="sp_1", user_id="user_commercial_1", name="Marina", lat=25.0805, lon=55.1386),
            SavedPlace(id="sp_2", user_id="user_commercial_1", name="Downtown", lat=25.2048, lon=55.2708),
            SavedPlace(id="sp_3", user_id="user_commercial_1", name="Business Bay", lat=25.1850, lon=55.2650),
            SavedPlace(id="sp_4", user_id="user_personal_1", name="JBR Beach", lat=25.0780, lon=55.1340),
            SavedPlace(id="sp_5", user_id="user_personal_1", name="Dubai Mall", lat=25.1972, lon=55.2744),
        ]
        for place in default_places:
            create_saved_place(place)

        print("[OK] Dummy users and saved places seeded")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM user_tasks")
    if cur.fetchone()["count"] > 0:
        conn.close()
        return
    conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

    dummy_tasks = [
        UserTask(task_id="task_001", task_name="Facade Cleaning - North Wing", location_name="Downtown Dubai",
                 location_lat=25.2048, location_lon=55.2708, duration_minutes=240, hour_start=5, hour_end=9,
                 date=today, status="scheduled", user_id="user_commercial_1"),
        UserTask(task_id="task_002", task_name="Foundation Inspection", location_name="North Industrial Zone",
                 location_lat=25.2200, location_lon=55.2850, duration_minutes=180, hour_start=18, hour_end=20,
                 date=today, status="scheduled", user_id="user_commercial_1"),
        UserTask(task_id="task_003", task_name="Road Maintenance", location_name="Dubai Marina",
                 location_lat=25.0805, location_lon=55.1386, duration_minutes=300, hour_start=6, hour_end=11,
                 date=today, status="in-process", user_id="user_commercial_1"),
        UserTask(task_id="task_004", task_name="Exterior Painting", location_name="Business Bay",
                 location_lat=25.1850, location_lon=55.2650, duration_minutes=360, hour_start=5, hour_end=18,
                 date=yesterday, status="completed", user_id="user_commercial_1"),
        UserTask(task_id="task_005", task_name="Scaffolding Setup", location_name="JLT Cluster",
                 location_lat=25.0760, location_lon=55.1470, duration_minutes=180, hour_start=6, hour_end=10,
                 date=today, status="scheduled", user_id="user_commercial_2"),
        UserTask(task_id="task_006", task_name="Window Installation", location_name="DIFC Gate",
                 location_lat=25.2100, location_lon=55.2790, duration_minutes=240, hour_start=7, hour_end=14,
                 date=today, status="in-process", user_id="user_commercial_2"),
    ]
    for task in dummy_tasks:
        create_task(task)

    dummy_recs = [
        AcceptedRecommendation(id="rec_001", task_id="task_001", accepted_time_start="05:30",
                               accepted_time_end="09:30", shade_percentage=78.5, shade_slot="Early Morning"),
        AcceptedRecommendation(id="rec_002", task_id="task_002", accepted_time_start="18:00",
                               accepted_time_end="21:00", shade_percentage=85.0, shade_slot="Evening"),
        AcceptedRecommendation(id="rec_003", task_id="task_003", accepted_time_start="06:30",
                               accepted_time_end="11:30", shade_percentage=65.0, shade_slot="Morning"),
        AcceptedRecommendation(id="rec_004", task_id="task_004", accepted_time_start="06:00",
                               accepted_time_end="12:00", shade_percentage=72.0, shade_slot="Morning",
                               completed_status=True, completed_at=yesterday),
        AcceptedRecommendation(id="rec_005", task_id="task_005", accepted_time_start="06:00",
                               accepted_time_end="09:00", shade_percentage=80.0, shade_slot="Early Morning"),
        AcceptedRecommendation(id="rec_006", task_id="task_006", accepted_time_start="07:00",
                               accepted_time_end="11:00", shade_percentage=70.0, shade_slot="Morning"),
    ]
    for rec in dummy_recs:
        create_accepted_recommendation(rec)

    for i in range(6):
        month_date = datetime.now() - __import__('datetime').timedelta(days=30*i)
        month = month_date.strftime("%Y-%m")
        analytics = WorkAnalytics(
            id=f"analytics_{month}", month=month,
            total_tasks=45 + i * 5, completed_tasks=38 + i * 3,
            total_duration_minutes=2400 + i * 200,
            avg_shade_coverage=72.5 + i * 2, target_tasks=50
        )
        conn = get_connection()
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(f"""
                    INSERT INTO work_analytics (id, month, total_tasks, completed_tasks,
                    total_duration_minutes, avg_shade_coverage, target_tasks, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (month) DO NOTHING
                """, (analytics.id, analytics.month, analytics.total_tasks, analytics.completed_tasks,
                      analytics.total_duration_minutes, analytics.avg_shade_coverage,
                      analytics.target_tasks, analytics.updated_at))
            else:
                cur.execute(f"""
                    INSERT OR IGNORE INTO work_analytics (id, month, total_tasks, completed_tasks,
                    total_duration_minutes, avg_shade_coverage, target_tasks, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                """, (analytics.id, analytics.month, analytics.total_tasks, analytics.completed_tasks,
                      analytics.total_duration_minutes, analytics.avg_shade_coverage,
                      analytics.target_tasks, analytics.updated_at))
            conn.commit()
        except Exception as e:
            print(f"Analytics insert warning: {e}")
        finally:
            conn.close()

    print("[OK] Dummy data seeded successfully")


if __name__ == "__main__":
    print("Initializing SmartShift database...")
    init_database()
    seed_dummy_data()

    # Test queries
    print("\n--- Dashboard Summary ---")
    summary = get_dashboard_summary()
    print(f"Today's tasks: {summary['today_task_count']}")
    print(f"Total duration: {summary['total_duration_minutes']} minutes")
    print(f"Completed: {summary['completed_count']}")
    print(f"Avg shade: {summary['avg_shade_coverage']}%")
