# Main Flask server - handles dashboard, WebSocket streams, API endpoints

import time
import threading
import os
import urllib.request
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

import database as db
import mqtt_client as mqtt
from ai_detector import AIDetector
from notifier import NotificationService

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "smartsec_2025"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global state
state = {
    "cameras": {},
    "alerts": [],
    "threat_level": "SAFE",
    "mqtt_connected": False,
    "total_alerts": 0,
    "system_start": time.time(),
    "mode": os.getenv("SMARTSEC_MODE", "SIMPLE").strip().upper(),
}
_lock = threading.Lock()
FRAME_EMIT_INTERVAL_SECONDS = 1.0 / 12.0  # 12 FPS

ALLOWED_MODES = {"SIMPLE", "ALERT"}

CAMERAS_CONFIG = [
    {"id": "CAM-01", "label": "Main Entrance", "source": "videos/demo-01.mp4"},
    {"id": "CAM-02", "label": "Parking Zone", "source": "videos/demo-02.mp4"},
    {"id": "CAM-03", "label": "Server Room", "source": "videos/demo-03.mp4"},
    {"id": "CAM-04", "label": "Emergency Exit", "source": "videos/demo-04.mp4"},
]

DEMO_VIDEO_URLS = [
    "https://raw.githubusercontent.com/mediaelement/mediaelement-files/master/big_buck_bunny.mp4",
    "https://raw.githubusercontent.com/mediaelement/mediaelement-files/master/echo-hereweare.mp4",
    "https://raw.githubusercontent.com/mediaelement/mediaelement-files/master/big_buck_bunny.mp4",
    "https://raw.githubusercontent.com/mediaelement/mediaelement-files/master/echo-hereweare.mp4",
]

DEMO_VIDEO_FILES = [
    "videos/demo-01.mp4",
    "videos/demo-02.mp4",
    "videos/demo-03.mp4",
    "videos/demo-04.mp4",
]

def _coerce_camera_source(value):
    # Convert string numbers to int, keep paths/URLs as strings
    s = str(value).strip()
    return int(s) if s.isdigit() else s


def _resolve_source_path(source):
    # Handle webcam index, RTSP, HTTP, or local file path
    if isinstance(source, int):
        return source

    s = str(source).strip()
    lower = s.lower()
    if lower.startswith(("rtsp://", "http://", "https://")):
        return s

    if os.path.isabs(s):
        return os.path.normpath(s)

    base_dir = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(base_dir, s))


def _download_file(url, dst_path):
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as response, open(dst_path, "wb") as out:
        out.write(response.read())


def ensure_demo_videos():
    base_dir = os.path.dirname(__file__)
    download_ok = True

    for rel_path, url in zip(DEMO_VIDEO_FILES, DEMO_VIDEO_URLS):
        abs_path = os.path.normpath(os.path.join(base_dir, rel_path))
        if os.path.exists(abs_path) and os.path.getsize(abs_path) > 1024 * 1024:
            continue

        print(f"[APP] Downloading demo video: {rel_path}")
        try:
            _download_file(url, abs_path)
            print(f"[APP] Saved demo video: {rel_path}")
        except Exception as exc:
            download_ok = False
            print(f"[APP] Failed to download {url}: {exc}")

    return download_ok


def load_camera_sources():
    # Load camera sources from camera_sources.txt (one per line)
    # Can be: 0 (webcam), /path/to/video.mp4, or rtsp://...
    raw_sources = []

    cfg_path = os.path.join(os.path.dirname(__file__), "camera_sources.txt")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw_sources = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]

    env_value = os.getenv("SMARTSEC_CAMERA_SOURCES", "").strip()
    if env_value:
        print("[APP] SMARTSEC_CAMERA_SOURCES env var is set but camera_sources.txt takes priority")

    if not raw_sources:
        raw_sources = DEMO_VIDEO_FILES[:]

    sources = [_resolve_source_path(_coerce_camera_source(v)) for v in raw_sources]
    for idx, cam in enumerate(CAMERAS_CONFIG):
        cam["source"] = sources[idx] if idx < len(sources) else sources[-1]

    print(f"[APP] Loaded {len(sources)} camera source(s)")
    for cam in CAMERAS_CONFIG:
        src = cam["source"]
        if isinstance(src, str) and not src.lower().startswith(("rtsp://", "http://", "https://")):
            exists = os.path.exists(src)
            print(f"[APP]  {cam['id']}: {src} (exists={exists})")
        else:
            print(f"[APP]  {cam['id']}: {src}")

detectors = []
notifier = NotificationService()


def _normalize_mode(value):
    mode = str(value or "").strip().upper()
    return mode if mode in ALLOWED_MODES else "SIMPLE"

state["mode"] = _normalize_mode(state["mode"])

# Callbacks for AI detector
def on_alert(camera_id, event_type, confidence, details, threat_level):
    # Called when AI detector finds a threat
    if state["mode"] != "ALERT":
        return

    with _lock:
        state["total_alerts"] += 1
        if threat_level == "HIGH":
            state["threat_level"] = "CRITICAL"
        elif threat_level == "MEDIUM" and state["threat_level"] == "SAFE":
            state["threat_level"] = "WARNING"

        alert = {
            "id": state["total_alerts"],
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "camera_id": camera_id,
            "event_type": event_type,
            "confidence": round(confidence * 100),
            "details": details,
            "threat_level": threat_level,
        }
        state["alerts"].insert(0, alert)
        state["alerts"] = state["alerts"][:100]

    # Log to database
    db.log_alert(camera_id, event_type, confidence, details, threat_level)

    # Publish to MQTT
    mqtt.publish_alert(camera_id, event_type, confidence, details, threat_level)

    # Send notifications if enabled
    if str(event_type).lower() == "person":
        notifier.notify_intrusion(camera_id, confidence, threat_level, details)

    # Broadcast to dashboard clients
    socketio.emit("new_alert", alert)
    socketio.emit("threat_update", {
        "level": state["threat_level"],
        "total": state["total_alerts"]
    })


def on_frame(camera_id, frame_b64):
    # Called by AI detector with each frame (base64 encoded JPEG)
    now = time.time()
    with _lock:
        if camera_id not in state["cameras"]:
            state["cameras"][camera_id] = {"last_emit_ts": 0.0}
        state["cameras"][camera_id]["frame"] = frame_b64
        state["cameras"][camera_id]["ts"] = now

        last_emit = state["cameras"][camera_id].get("last_emit_ts", 0.0)
        should_emit = (now - last_emit) >= FRAME_EMIT_INTERVAL_SECONDS
        if should_emit:
            state["cameras"][camera_id]["last_emit_ts"] = now

    if should_emit:
        socketio.emit("frame_update", {"camera_id": camera_id, "frame": frame_b64})

# API Routes
@app.route("/")
def index():
    return render_template("index.html", cameras=CAMERAS_CONFIG)

@app.route("/api/state")
def api_state():
    uptime = int(time.time() - state["system_start"])
    h, rem = divmod(uptime, 3600)
    m, s = divmod(rem, 60)
    return jsonify({
        "threat_level": state["threat_level"],
        "mode": state["mode"],
        "total_alerts": state["total_alerts"],
        "alerts_today": db.get_alert_count_today(),
        "mqtt_connected": mqtt.is_connected(),
        "cameras_active": len(CAMERAS_CONFIG),
        "uptime": f"{h:02d}:{m:02d}:{s:02d}",
        "notifier_ready": notifier.enabled,
        "recent_alerts": state["alerts"][:20],
    })


@app.route("/api/reset_threat")
def reset_threat():
    with _lock:
        state["threat_level"] = "SAFE"
    socketio.emit("threat_update", {"level": "SAFE", "total": state["total_alerts"]})
    return jsonify({"ok": True})

@app.route("/api/mode", methods=["GET", "POST"])
def api_mode():
    if request.method == "GET":
        return jsonify({"mode": state["mode"]})

    payload = request.get_json(silent=True) or {}
    mode = _normalize_mode(payload.get("mode"))
    with _lock:
        state["mode"] = mode
        if mode == "SIMPLE":
            state["threat_level"] = "SAFE"

    socketio.emit("mode_update", {"mode": state["mode"]})
    socketio.emit("threat_update", {
        "level": state["threat_level"],
        "total": state["total_alerts"]
    })
    return jsonify({"ok": True, "mode": state["mode"]})

@app.route("/api/alerts")
def api_alerts():
    limit = int(request.args.get("limit", 200))
    limit = max(1, min(limit, 500))
    rows = db.get_recent_alerts(limit=limit)

    alerts = []
    for r in rows:
        alerts.append({
            "id": r[0],
            "timestamp": r[1],
            "camera_id": r[3],
            "event_type": r[4],
            "confidence": round(float(r[5]) * 100) if r[5] is not None else 0,
            "details": r[6] or "",
            "threat_level": r[7] or "LOW",
        })
    return jsonify({"alerts": alerts})

@app.route("/api/test_notification", methods=["POST"])
def api_test_notification():
    result = notifier.send_test_message()
    code = 200 if result.get("ok") else 400
    return jsonify(result), code

# WebSocket events
@socketio.on("connect")
def on_connect():
    emit("mode_update", {"mode": state["mode"]})
    emit("threat_update", {
        "level": state["threat_level"],
        "total": state["total_alerts"]
    })


def start_detectors():
    # Start one AI detector per camera in parallel
    for cfg in CAMERAS_CONFIG:
        d = AIDetector(
            source=cfg["source"],
            camera_id=cfg["id"],
            alert_callback=on_alert,
            frame_callback=on_frame,
        )
        d.start()
        detectors.append(d)
        time.sleep(0.4)

def start_system():
    ensure_demo_videos()
    load_camera_sources()
    db.init_db()
    db.log_system_event("System started")
    mqtt.init_mqtt()
    notifier.log_status()
    time.sleep(1)

    # Start AI detectors in background
    t = threading.Thread(target=start_detectors, daemon=True)
    t.start()

    print("\n" + "="*55)
    print("  🛡  SMART SECURITY SYSTEM — DASHBOARD READY")
    print("  Open your browser:  http://127.0.0.1:5000")
    print("="*55 + "\n")


if __name__ == "__main__":
    start_system()
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
