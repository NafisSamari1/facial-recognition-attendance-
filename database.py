import os
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import DictCursor

BASE_DIR = Path(__file__).resolve().parent

DB_DIR = BASE_DIR / "data" / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "attendance.db"
FACES_DIR = BASE_DIR / "data" / "faces"
FACES_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)


def _prepare_query(query):
    if USE_POSTGRES:
        return query.replace("?", "%s")
    return query


def _execute(conn, query, params=()):
    return conn.execute(_prepare_query(query), params)


def _as_dict(row):
    return dict(row) if row is not None else None


def get_connection():
    if USE_POSTGRES:
        if "sslmode=" in DATABASE_URL.lower():
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
        else:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor, sslmode="require")
        conn.autocommit = False
        return conn

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            course TEXT NOT NULL,
            email TEXT,
            device_id TEXT,
            device_name TEXT,
            device_reset_requested INTEGER DEFAULT 0,
            device_reset_reason TEXT,
            face_samples INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
    )

    for col, col_type in [
        ("email", "TEXT"),
        ("device_id", "TEXT"),
        ("device_name", "TEXT"),
        ("device_reset_requested", "INTEGER DEFAULT 0"),
        ("device_reset_reason", "TEXT"),
    ]:
        try:
            if USE_POSTGRES:
                _execute(conn, f"ALTER TABLE students ADD COLUMN IF NOT EXISTS {col} {col_type}")
            else:
                conn.execute(f"ALTER TABLE students ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """,
    )
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            student_id TEXT NOT NULL,
            full_name TEXT NOT NULL,
            course TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            device_id TEXT,
            location_lat REAL,
            location_lng REAL,
            created_at TEXT NOT NULL
        )
        """,
    )
    for col, col_type in [
        ("location_lat", "REAL"),
        ("location_lng", "REAL"),
        ("created_at", "TEXT"),
    ]:
        try:
            if USE_POSTGRES:
                _execute(conn, f"ALTER TABLE attendance ADD COLUMN IF NOT EXISTS {col} {col_type}")
            else:
                conn.execute(f"ALTER TABLE attendance ADD COLUMN {col} {col_type}")
        except Exception:
            pass
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS recognition_events (
            id SERIAL PRIMARY KEY,
            student_id TEXT,
            matched INTEGER NOT NULL,
            confidence REAL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """,
    )
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS zone_settings (
            id SERIAL PRIMARY KEY,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            radius_meters REAL NOT NULL DEFAULT 100.0,
            name TEXT DEFAULT 'Lecture Hall Zone',
            updated_at TEXT NOT NULL
        )
        """,
    )
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id SERIAL PRIMARY KEY,
            course TEXT NOT NULL,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """,
    )
    _execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
    )
    conn.commit()
    conn.close()


def get_app_setting(key, default=None):
    conn = get_connection()
    row = _execute(conn, "SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_app_setting(key, value):
    conn = get_connection()
    _execute(
        conn,
        "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_manager_credentials():
    username = get_app_setting("manager_username", os.environ.get("APP_USERNAME", "admin"))
    password = get_app_setting("manager_password", os.environ.get("APP_PASSWORD", "admin123"))
    return username, password


def set_manager_credentials(username, password):
    username = (username or "").strip()
    password = password or ""
    if not username:
        raise ValueError("Username cannot be empty.")
    if not password:
        raise ValueError("Password cannot be empty.")
    set_app_setting("manager_username", username)
    set_app_setting("manager_password", password)


def add_course(course_name):
    if not course_name or not course_name.strip():
        return None
    cleaned = course_name.strip()
    conn = get_connection()
    if USE_POSTGRES:
        _execute(
            conn,
            "INSERT INTO courses (name, created_at) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
            (cleaned, datetime.utcnow().isoformat()),
        )
    else:
        _execute(
            conn,
            "INSERT OR IGNORE INTO courses (name, created_at) VALUES (?, ?)",
            (cleaned, datetime.utcnow().isoformat()),
        )
    conn.commit()
    conn.close()
    return cleaned


def ensure_course(course_name):
    if not course_name or not course_name.strip():
        return None
    return add_course(course_name)


def list_courses():
    conn = get_connection()
    rows = _execute(
        conn,
        """
        SELECT DISTINCT course FROM (
            SELECT name AS course FROM courses
            UNION ALL
            SELECT course FROM students
        )
        ORDER BY course
        """,
    ).fetchall()
    conn.close()
    return [row["course"] for row in rows if row["course"]]


def delete_course(course_name):
    if not course_name or not course_name.strip():
        return False
    cleaned = course_name.strip()
    conn = get_connection()
    in_use = _execute(conn, "SELECT COUNT(*) AS c FROM students WHERE course = ?", (cleaned,)).fetchone()["c"]
    if in_use:
        conn.close()
        return False
    _execute(conn, "DELETE FROM courses WHERE name = ?", (cleaned,))
    conn.commit()
    conn.close()
    return True


def add_student(student_id, full_name, course, email, device_id=None, device_name=None):
    ensure_course(course)
    conn = get_connection()
    _execute(
        conn,
        "INSERT INTO students (student_id, full_name, course, email, device_id, device_name, face_samples, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (student_id, full_name, course, email, device_id, device_name, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_student(student_id):
    conn = get_connection()
    row = _execute(conn, "SELECT * FROM students WHERE student_id = ?", (student_id,)).fetchone()
    conn.close()
    return _as_dict(row)


def get_student_by_device(device_id):
    if not device_id:
        return None
    conn = get_connection()
    row = _execute(conn, "SELECT * FROM students WHERE device_id = ?", (device_id,)).fetchone()
    conn.close()
    return _as_dict(row)


def list_students():
    conn = get_connection()
    rows = _execute(conn, "SELECT * FROM students ORDER BY full_name").fetchall()
    conn.close()
    return [_as_dict(r) for r in rows]


def delete_student(student_id):
    conn = get_connection()
    _execute(conn, "DELETE FROM students WHERE student_id = ?", (student_id,))
    conn.commit()
    conn.close()


def set_face_sample_count(student_id, count):
    conn = get_connection()
    _execute(conn, "UPDATE students SET face_samples = ? WHERE student_id = ?", (count, student_id))
    conn.commit()
    conn.close()


def assign_device(student_id, device_id, device_name=None):
    conn = get_connection()
    _execute(
        conn,
        "UPDATE students SET device_id = ?, device_name = ?, device_reset_requested = 0, device_reset_reason = NULL WHERE student_id = ?",
        (device_id, device_name, student_id),
    )
    conn.commit()
    conn.close()


def unbind_student_device(student_id):
    conn = get_connection()
    _execute(
        conn,
        "UPDATE students SET device_id = NULL, device_name = NULL, device_reset_requested = 0, device_reset_reason = NULL WHERE student_id = ?",
        (student_id,),
    )
    conn.commit()
    conn.close()


def request_device_reset(student_id, reason="Lost or changed device"):
    conn = get_connection()
    _execute(
        conn,
        "UPDATE students SET device_reset_requested = 1, device_reset_reason = ? WHERE student_id = ?",
        (reason, student_id),
    )
    conn.commit()
    conn.close()


def list_device_reset_requests():
    conn = get_connection()
    rows = _execute(conn, "SELECT * FROM students WHERE device_reset_requested = 1 ORDER BY full_name").fetchall()
    conn.close()
    return [_as_dict(r) for r in rows]


def log_event(matched, student_id=None, full_name=None, confidence=None, reason="unknown"):
    conn = get_connection()
    _execute(
        conn,
        "INSERT INTO recognition_events (student_id, matched, confidence, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (student_id, 1 if matched else 0, confidence, reason, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def log_attendance(student_id, full_name, course, confidence, status, device_id=None, location_lat=None, location_lng=None):
    now = datetime.utcnow()
    conn = get_connection()
    _execute(
        conn,
        """
        INSERT INTO attendance (student_id, full_name, course, date, time, confidence, status, device_id, location_lat, location_lng, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, full_name, course, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), confidence, status, device_id, location_lat, location_lng, now.isoformat()),
    )
    conn.commit()
    conn.close()


def has_attended_today(student_id, course):
    today = date.today().isoformat()
    conn = get_connection()
    row = _execute(
        conn,
        "SELECT 1 FROM attendance WHERE student_id = ? AND course = ? AND date = ? LIMIT 1",
        (student_id, course, today),
    ).fetchone()
    conn.close()
    return bool(row)


def list_attendance(day=None, course=None, student_id=None, limit=100):
    conn = get_connection()
    query = "SELECT * FROM attendance"
    filters = []
    params = []
    if day:
        filters.append("date = ?")
        params.append(day)
    if course:
        filters.append("course = ?")
        params.append(course)
    if student_id:
        filters.append("student_id = ?")
        params.append(student_id)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = _execute(conn, query, params).fetchall()
    conn.close()
    return [_as_dict(r) for r in rows]


def get_summary_stats():
    conn = get_connection()
    total_students = _execute(conn, "SELECT COUNT(*) AS c FROM students").fetchone()["c"]
    today = date.today().isoformat()
    today_present = _execute(conn, "SELECT COUNT(*) AS c FROM attendance WHERE date = ?", (today,)).fetchone()["c"]
    flagged = _execute(conn, "SELECT COUNT(*) AS c FROM attendance WHERE status = 'flagged'").fetchone()["c"]
    rejected_events = _execute(conn, "SELECT COUNT(*) AS c FROM recognition_events WHERE matched = 0").fetchone()["c"]
    avg_confidence = _execute(conn, "SELECT AVG(confidence) AS c FROM attendance").fetchone()["c"] or 0
    roster = total_students or 1
    attendance_rate = round((today_present / roster) * 100, 1) if roster else 0.0
    conn.close()
    return {
        "total_students": total_students,
        "today_present": today_present,
        "attendance_rate": attendance_rate,
        "avg_confidence": round(avg_confidence, 1),
        "flagged": flagged,
        "rejected_events": rejected_events,
    }


def get_last_7_days_trend():
    conn = get_connection()
    rows = _execute(
        conn,
        """
        SELECT date, COUNT(DISTINCT student_id) AS count
        FROM attendance
        GROUP BY date
        ORDER BY date DESC
        LIMIT 7
        """,
    ).fetchall()
    conn.close()
    return [{"date": row["date"], "count": row["count"]} for row in reversed(rows)]


def get_course_breakdown():
    conn = get_connection()
    rows = _execute(
        conn,
        "SELECT course, COUNT(*) AS count FROM attendance GROUP BY course ORDER BY count DESC",
    ).fetchall()
    conn.close()
    return [{"course": row["course"], "count": row["count"]} for row in rows]


def get_active_zone():
    conn = get_connection()
    row = _execute(conn, "SELECT * FROM zone_settings ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return _as_dict(row)


def set_active_zone(lat, lng, radius_meters=100.0, name="Lecture Hall Zone"):
    conn = get_connection()
    _execute(
        conn,
        "INSERT INTO zone_settings (lat, lng, radius_meters, name, updated_at) VALUES (?, ?, ?, ?, ?)",
        (float(lat), float(lng), float(radius_meters), name, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return get_active_zone()


def _format_session_dict(row):
    if not row:
        return None
    session_dict = _as_dict(row)
    try:
        end_dt = datetime.fromisoformat(session_dict["end_time"])
        now_dt = datetime.utcnow()
        remaining = max(0, int((end_dt - now_dt).total_seconds()))
        session_dict["seconds_remaining"] = remaining
    except Exception:
        session_dict["seconds_remaining"] = 0
    return session_dict


def get_session_by_id(session_id):
    conn = get_connection()
    row = _execute(conn, "SELECT * FROM attendance_sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return _format_session_dict(row)


def create_session(course, duration_minutes=15, title=None):
    now = datetime.utcnow()
    end = now + timedelta(minutes=int(duration_minutes))
    title = title or f"{course if course != 'ALL' else 'General'} Attendance Window"
    conn = get_connection()
    if course == 'ALL':
        _execute(conn, "UPDATE attendance_sessions SET status = 'ended' WHERE status = 'active'")
    else:
        _execute(conn, "UPDATE attendance_sessions SET status = 'ended' WHERE status = 'active' AND (course = ? OR course = 'ALL')", (course,))

    if USE_POSTGRES:
        cursor = _execute(
            conn,
            """
            INSERT INTO attendance_sessions (course, title, start_time, end_time, duration_minutes, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'active', %s)
            RETURNING id
            """,
            (course, title, now.isoformat(), end.isoformat(), int(duration_minutes), now.isoformat()),
        )
        session_id = cursor.fetchone()[0]
    else:
        cursor = _execute(
            conn,
            """
            INSERT INTO attendance_sessions (course, title, start_time, end_time, duration_minutes, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (course, title, now.isoformat(), end.isoformat(), int(duration_minutes), now.isoformat()),
        )
        session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return get_session_by_id(session_id)


def get_active_session(course=None):
    now_iso = datetime.utcnow().isoformat()
    conn = get_connection()
    _execute(conn, "UPDATE attendance_sessions SET status = 'expired' WHERE status = 'active' AND end_time < ?", (now_iso,))
    conn.commit()

    if course:
        row = _execute(
            conn,
            """
            SELECT * FROM attendance_sessions
            WHERE status = 'active' AND end_time >= ? AND (course = ? OR course = 'ALL')
            ORDER BY id DESC LIMIT 1
            """,
            (now_iso, course),
        ).fetchone()
    else:
        row = _execute(
            conn,
            """
            SELECT * FROM attendance_sessions
            WHERE status = 'active' AND end_time >= ?
            ORDER BY id DESC LIMIT 1
            """,
            (now_iso,),
        ).fetchone()
    conn.close()
    return _format_session_dict(row)


def end_session(session_id):
    conn = get_connection()
    _execute(conn, "UPDATE attendance_sessions SET status = 'ended' WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


def list_sessions(limit=20):
    conn = get_connection()
    rows = _execute(conn, "SELECT * FROM attendance_sessions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [_as_dict(r) for r in rows]


def get_student_summary(student_id):
    student = get_student(student_id)
    if not student:
        return None

    conn = get_connection()
    total_scans = _execute(conn, "SELECT COUNT(*) AS c FROM attendance WHERE student_id = ?", (student_id,)).fetchone()["c"]
    today = date.today().isoformat()
    today_row = _execute(conn, "SELECT * FROM attendance WHERE student_id = ? AND date = ? ORDER BY id DESC LIMIT 1", (student_id, today)).fetchone()
    last_row = _execute(conn, "SELECT * FROM attendance WHERE student_id = ? ORDER BY id DESC LIMIT 1", (student_id,)).fetchone()
    conn.close()

    return {
        "student": student,
        "total_scans": total_scans,
        "attended_today": bool(today_row),
        "today_status": _as_dict(today_row)["status"] if today_row else "not_marked",
        "last_scan": f"{_as_dict(last_row)['date']} {_as_dict(last_row)['time']}" if last_row else "Never",
    }
