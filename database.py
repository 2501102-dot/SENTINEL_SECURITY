"""SQLite Database - Logs alerts and system events"""
import sqlite3
import time
from datetime import datetime

DB_PATH = "security_logs.db"

def init_db():
    """Create database tables"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        unix_time REAL NOT NULL,
        camera_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        confidence REAL,
        details TEXT,
        threat_level TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

def log_alert(camera_id, event_type, confidence=0.0, details="", threat_level="LOW"):
    """Log alert to database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO alerts (timestamp, unix_time, camera_id, event_type, confidence, details, threat_level)
                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), time.time(), camera_id, event_type, confidence, details, threat_level))
    conn.commit()
    conn.close()

def get_recent_alerts(limit=50):
    """Get recent alerts from database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM alerts ORDER BY unix_time DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_alert_count_today():
    """Count alerts today"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM alerts WHERE timestamp LIKE ?", (f"{today}%",))
    count = c.fetchone()[0]
    conn.close()
    return count
