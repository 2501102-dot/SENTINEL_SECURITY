# Simple SQLite database for logging alerts and system events

import sqlite3
import time
from datetime import datetime


DB_PATH = "security_logs.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            unix_time   REAL    NOT NULL,
            camera_id   TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            confidence  REAL,
            details     TEXT,
            threat_level TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            event       TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_alert(camera_id, event_type, confidence=0.0, details="", threat_level="LOW"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now()
    c.execute("""
        INSERT INTO alerts (timestamp, unix_time, camera_id, event_type, confidence, details, threat_level)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (now.strftime("%Y-%m-%d %H:%M:%S"), time.time(), camera_id, event_type, confidence, details, threat_level))
    conn.commit()
    conn.close()


def get_recent_alerts(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM alerts ORDER BY unix_time DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def get_alert_count_today():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM alerts WHERE timestamp LIKE ?", (f"{today}%",))
    count = c.fetchone()[0]
    conn.close()
    return count


def log_system_event(event):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    conn.execute("INSERT INTO system_events (timestamp, event) VALUES (?, ?)",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event))
    conn.commit()
    conn.close()
