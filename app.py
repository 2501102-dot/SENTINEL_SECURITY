# SENTINEL Smart Security System - Flask Dashboard & API
import time
import threading
import os
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

state = {
    "cameras": {}, "alerts": [], "threat_level": "SAFE",
    "mqtt_connected": False, "total_alerts": 0,
    "system_start": time.time(),
    "mode": os.getenv("SMARTSEC_MODE", "SIMPLE").strip().upper(),
}

_lock = threading.Lock()
_emit_lock = threading.Lock()
FRAME_EMIT_FPS = 5
FRAME_EMIT_INTERVAL = 1.0 / FRAME_EMIT_FPS

ALLOWED_MODES = {"SIMPLE", "ALERT"}
CAMERAS_CONFIG = [
    {"id": "CAM-01", "label": "Main Entrance", "source": "videos/demo1.mp4"},
    {"id": "CAM-02", "label": "Parking Zone", "source": "videos/demo2.mp4"},
    {"id": "CAM-03", "label": "Server Room", "source": "videos/demo3.mp4"},
    {"id": "CAM-04", "label": "Emergency Exit", "source": "videos/demo4.mp4"},
]

def load_source_path(source):
    """Convert source string to absolute path"""
    if isinstance(source, int) or str(source).lower().startswith(("rtsp://", "http://")):
        return source
    path = str(source).strip()
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    return os.path.normpath(path)

detectors = []
notifier = NotificationService()

def stop_detectors():
    """Stop all AI detectors"""
    global detectors
    for d in list(detectors):
        try:
            d.stop()
        except:
            pass
    detectors = []

state["mode"] = state["mode"] if state["mode"] in ALLOWED_MODES else "SIMPLE"

# Callbacks
def on_alert(camera_id, event_type, confidence, details, threat_level):
    """Handle alert from AI detector"""
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

    db.log_alert(camera_id, event_type, confidence, details, threat_level)
    mqtt.publish_alert(camera_id, event_type, confidence, details, threat_level)
    
    if str(event_type).lower() == "person":
        notifier.notify_intrusion(camera_id, confidence, threat_level, details)

    with _emit_lock:
        socketio.emit("new_alert", alert)
        socketio.emit("threat_update", {"level": state["threat_level"], "total": state["total_alerts"]})


def on_frame(camera_id, frame_b64):
    """Handle frame from AI detector"""
    now = time.time()
    with _lock:
        if camera_id not in state["cameras"]:
            state["cameras"][camera_id] = {"last_emit_ts": 0.0}
        state["cameras"][camera_id]["frame"] = frame_b64
        state["cameras"][camera_id]["ts"] = now
        
        last_emit = state["cameras"][camera_id].get("last_emit_ts", 0.0)
        should_emit = (now - last_emit) >= FRAME_EMIT_INTERVAL

    if should_emit:
        state["cameras"][camera_id]["last_emit_ts"] = now
        with _emit_lock:
            socketio.emit("frame_update", {"camera_id": camera_id, "frame": frame_b64})

# Routes
@app.route("/")
def index():
    return render_template("index.html", cameras=CAMERAS_CONFIG)

@app.route("/api/state")
def api_state():
    uptime = int(time.time() - state["system_start"])
    h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
    return jsonify({
        "threat_level": state["threat_level"],
        "mode": state["mode"],
        "total_alerts": state["total_alerts"],
        "alerts_today": db.get_alert_count_today(),
        "mqtt_connected": mqtt.is_connected(),
        "cameras_active": len(CAMERAS_CONFIG),
        "uptime": f"{h:02d}:{m:02d}:{s:02d}",
    })

@app.route("/api/reset_threat")
def reset_threat():
    with _lock:
        state["threat_level"] = "SAFE"
    with _emit_lock:
        socketio.emit("threat_update", {"level": "SAFE", "total": state["total_alerts"]})
    return jsonify({"ok": True})

@app.route("/api/mode", methods=["GET", "POST"])
def api_mode():
    if request.method == "GET":
        return jsonify({"mode": state["mode"]})
    
    mode = request.get_json(silent=True).get("mode", "SIMPLE").upper() if request.get_json(silent=True) else "SIMPLE"
    mode = mode if mode in ALLOWED_MODES else "SIMPLE"
    
    with _lock:
        state["mode"] = mode
        if mode == "SIMPLE":
            state["threat_level"] = "SAFE"
    
    with _emit_lock:
        socketio.emit("mode_update", {"mode": state["mode"]})
        socketio.emit("threat_update", {"level": state["threat_level"], "total": state["total_alerts"]})
    
    return jsonify({"ok": True, "mode": state["mode"]})

@app.route("/api/alerts")
def api_alerts():
    limit = min(int(request.args.get("limit", 200)), 500)
    rows = db.get_recent_alerts(limit)
    alerts = [{
        "id": r[0], "timestamp": r[1], "camera_id": r[3],
        "event_type": r[4], "confidence": round(float(r[5] or 0) * 100),
        "details": r[6] or "", "threat_level": r[7] or "LOW",
    } for r in rows]
    return jsonify({"alerts": alerts})

@app.route("/api/health")
def api_health():
    """Health check for deployment"""
    return jsonify({
        "status": "ok",
        "mode": state["mode"],
        "detectors": len(detectors),
        "mqtt": mqtt.is_connected(),
    })

# WebSocket
@socketio.on("connect")
def on_connect():
    emit("mode_update", {"mode": state["mode"]})
    emit("threat_update", {"level": state["threat_level"], "total": state["total_alerts"]})
    emit("mqtt_status", {"connected": mqtt.is_connected()})

# System Startup
def start_detectors():
    """Start AI detectors for all cameras"""
    for cfg in CAMERAS_CONFIG:
        d = AIDetector(
            source=cfg["source"], camera_id=cfg["id"],
            alert_callback=on_alert, frame_callback=on_frame,
        )
        d.start()
        detectors.append(d)
        time.sleep(0.3)

def start_system():
    """Initialize and start all services"""
    db.init_db()
    mqtt.init_mqtt()
    notifier.log_status()
    time.sleep(0.5)
    
    t = threading.Thread(target=start_detectors, daemon=True)
    t.start()
    
    # Start MQTT status broadcast thread
    def broadcast_mqtt_status():
        while True:
            time.sleep(5)
            with _emit_lock:
                socketio.emit("mqtt_status", {"connected": mqtt.is_connected()})
    
    t_mqtt = threading.Thread(target=broadcast_mqtt_status, daemon=True)
    t_mqtt.start()
    
    print("\n" + "="*50)
    print("  🛡  SMART SECURITY SYSTEM — READY")
    print("  http://127.0.0.1:5000")
    print("="*50 + "\n")


if __name__ == "__main__":
    start_system()
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)


@app.route('/admin/refresh_videos', methods=['POST'])
def admin_refresh_videos():
    """Admin endpoint: refresh detectors without downloading videos.

    Call this to restart the AI detector threads without redeploying.
    """
    stop_detectors()
    t = threading.Thread(target=start_detectors, daemon=True)
    t.start()
    return jsonify({"ok": True})
