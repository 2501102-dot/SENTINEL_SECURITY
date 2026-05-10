# AI detection engine using YOLOv8
# Captures video frames, runs inference, streams to dashboard, logs alerts

import cv2
import threading
import time
import base64
import numpy as np
import os
from datetime import datetime

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("[AI] YOLOv8 not installed - running in simulation mode")

# Classes to detect (from COCO dataset)
THREAT_CLASSES = {0: "person"}
HIGH_THREAT = {43: "knife", 76: "scissors"}
CONF_THRESHOLD = 0.50


class AIDetector:
    _shared_model = None
    _model_lock = threading.Lock()
    _infer_lock = threading.Lock()

    def __init__(self, source=0, camera_id="CAM-01",
                 alert_callback=None, frame_callback=None):
        # source: webcam index (0) or video file path
        # camera_id: label for this camera
        # alert_callback: called when threat detected
        # frame_callback: called with each frame (base64 JPEG)
        self.source = source
        self.camera_id = camera_id
        self.alert_callback = alert_callback
        self.frame_callback = frame_callback

        self.model = None
        self.cap = None
        self.running = False
        self._thread = None
        self.is_local_file_source = isinstance(self.source, str) and not self.source.lower().startswith(("rtsp://", "http://", "https://"))

        # Alert cooldown - prevent spamming same alert
        self._last_alert_time = {}
        self.ALERT_COOLDOWN = 4  # seconds

        # Performance config (can be tuned via env vars)
        self.fps = 0
        self.detection_count = 0
        self.frame_count = 0
        self.infer_every_n = int(max(1, int(os.getenv('SMARTSEC_INFER_EVERY_N', '4'))))
        self.max_infer_width = int(max(480, int(os.getenv('SMARTSEC_INFER_MAX_WIDTH', '640'))))
        self.stream_max_width = int(max(480, int(os.getenv('SMARTSEC_STREAM_MAX_WIDTH', '640'))))
        self.stream_jpeg_quality = int(max(40, min(95, int(os.getenv('SMARTSEC_STREAM_JPEG_QUALITY', '52')))))
        self.target_loop_fps = float(max(5, int(os.getenv('SMARTSEC_STREAM_FPS', '12'))))
        self.min_loop_fps = float(max(5, int(os.getenv('SMARTSEC_STREAM_MIN_FPS', '8'))))
        self.capture_skip = int(max(0, int(os.getenv('SMARTSEC_CAPTURE_SKIP', '1'))))
        self.adaptive_load_enabled = str(os.getenv('SMARTSEC_ADAPTIVE_LOAD', '1')).strip().lower() not in ('0', 'false', 'no', 'off')
        self.fallback_to_simulation = False  # ALWAYS use real video sources, NEVER fallback
        self.dynamic_loop_fps = self.target_loop_fps
        self.dynamic_infer_every_n = self.infer_every_n
        self._util_ema = 0.0
        self._last_adapt_ts = time.time()
        self._last_detections = []

    # ──────────────────────────────────────────────────────────────────────────
    def load_model(self):
        if YOLO_AVAILABLE:
            with self._model_lock:
                if AIDetector._shared_model is None:
                    print("[AI] Loading YOLOv8n model …")
                    AIDetector._shared_model = YOLO("yolov8n.pt")
                    print("[AI] Model loaded ✓")
            self.model = AIDetector._shared_model
        else:
            self.model = None

    def start(self):
        self.load_model()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[AI] Detection started on source={self.source}")

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()

    # ──────────────────────────────────────────────────────────────────────────
    def _run(self):
        if YOLO_AVAILABLE:
            self._run_yolo()
        else:
            self._run_simulation()

    # ── REAL mode ─────────────────────────────────────────────────────────────
    def _run_yolo(self):
        if isinstance(self.source, str) and not self.source.lower().startswith(("rtsp://", "http://", "https://")):
            if not os.path.exists(self.source):
                self._handle_source_failure(f"Source file missing: {self.source}")
                return

        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            self._handle_source_failure(f"Cannot open source: {self.source}")
            return

        t_prev = time.time()
        while self.running:
            loop_start = time.time()
            ret, frame = self.cap.read()
            if not ret:
                # Loop video / retry webcam
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.02)
                continue

            annotated = frame.copy()
            self.frame_count += 1
            if self.frame_count % self.dynamic_infer_every_n == 0 or not self._last_detections:
                detections = self._run_inference(frame)
                self._last_detections = detections
            else:
                detections = self._last_detections

            for cls_id, label, conf, threat_level, x1, y1, x2, y2 in detections:
                if threat_level == "HIGH":
                    color = (0, 0, 255)
                elif threat_level == "MEDIUM":
                    color = (0, 200, 255)
                else:
                    color = (0, 255, 100)

                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.rectangle(annotated, (x1, y1-28), (x1 + len(label)*12 + 60, y1), color, -1)
                cv2.putText(annotated, f"{label} {conf:.0%}",
                            (x1+4, y1-8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                            (0,0,0), 2)

            # Overlay HUD
            annotated = self._draw_hud(annotated, len(detections))

            # Reduce network/encoder load by sending a smaller frame than the
            # source video when possible.
            send_frame = annotated
            H, W = annotated.shape[:2]
            if W > self.stream_max_width:
                new_w = self.stream_max_width
                new_h = int(H * (new_w / W))
                send_frame = cv2.resize(annotated, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Encode and send frame
            self._send_frame(send_frame)

            # Fire alerts (with cooldown)
            for cls_id, label, conf, threat_level, *_ in detections:
                if cls_id in THREAT_CLASSES or cls_id in HIGH_THREAT:
                    self._maybe_alert(label, conf, threat_level)

            # FPS
            now = time.time()
            self.fps = 1.0 / max(now - t_prev, 1e-6)
            t_prev = now

            if self.is_local_file_source and self.capture_skip > 0:
                for _ in range(self.capture_skip):
                    if not self.cap.grab():
                        break

            # Throttle the loop so the four demo sources don't run flat-out.
            target_interval = 1.0 / self.dynamic_loop_fps
            elapsed = time.time() - loop_start

            if self.adaptive_load_enabled:
                util = elapsed / max(target_interval, 1e-6)
                self._util_ema = (0.88 * self._util_ema) + (0.12 * util)
                now_adapt = time.time()
                if now_adapt - self._last_adapt_ts >= 2.0:
                    if self._util_ema > 1.10:
                        self.dynamic_loop_fps = max(self.min_loop_fps, self.dynamic_loop_fps - 1.0)
                        self.dynamic_infer_every_n = min(8, self.dynamic_infer_every_n + 1)
                    elif self._util_ema < 0.72:
                        self.dynamic_loop_fps = min(self.target_loop_fps, self.dynamic_loop_fps + 1.0)
                        self.dynamic_infer_every_n = max(self.infer_every_n, self.dynamic_infer_every_n - 1)
                    self._last_adapt_ts = now_adapt

            if elapsed < target_interval:
                time.sleep(target_interval - elapsed)

        self.cap.release()

    def _handle_source_failure(self, reason):
        print(f"[AI] {reason}")
        if self.fallback_to_simulation:
            print(f"[AI] {self.camera_id}: switching to simulation fallback")
            self._run_simulation(source_failed=True)
            return
        self._run_no_signal(reason)

    def _run_inference(self, frame):
        """Run detection on resized frame and map boxes back to original resolution."""
        H, W = frame.shape[:2]
        infer_frame = frame
        scale_x = 1.0
        scale_y = 1.0

        if W > self.max_infer_width:
            new_w = self.max_infer_width
            new_h = int(H * (new_w / W))
            infer_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            scale_x = W / float(new_w)
            scale_y = H / float(new_h)

        with self._infer_lock:
            results = self.model(infer_frame, verbose=False)[0]

        detections = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            if conf < CONF_THRESHOLD:
                continue

            label = results.names[cls_id]
            rx1, ry1, rx2, ry2 = map(int, box.xyxy[0])
            x1 = int(rx1 * scale_x)
            y1 = int(ry1 * scale_y)
            x2 = int(rx2 * scale_x)
            y2 = int(ry2 * scale_y)

            if cls_id in HIGH_THREAT:
                threat_level = "HIGH"
            elif cls_id in THREAT_CLASSES:
                threat_level = "MEDIUM"
            else:
                threat_level = "LOW"

            detections.append((cls_id, label, conf, threat_level, x1, y1, x2, y2))

        return detections

    def _run_no_signal(self, reason):
        """Show a clear source failure frame instead of fake simulation feed."""
        print(f"[AI] {reason}")
        W, H = 640, 480
        while self.running:
            frame = np.zeros((H, W, 3), dtype=np.uint8)
            cv2.rectangle(frame, (30, 160), (610, 320), (0, 0, 180), 2)
            cv2.putText(frame, self.camera_id, (40, 205),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 200), 2)
            cv2.putText(frame, "NO VIDEO SOURCE", (40, 245),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
            cv2.putText(frame, "Check camera_sources.txt path", (40, 280),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 160, 160), 1)
            self._send_frame(frame)
            time.sleep(0.5)

    # ── SIMULATION mode (no webcam / no YOLO) ─────────────────────────────────
    def _run_simulation(self, source_failed=False):
        """Generates a fake camera feed with animated objects for demo."""
        import random, math
        W, H = 640, 480
        frame_n = 0

        persons = [
            {"x": 100, "y": 200, "vx": 1.5, "vy": 0.5, "label": "person", "conf": 0.91}
        ]
        alert_tick = 0

        while self.running:
            frame = np.zeros((H, W, 3), dtype=np.uint8)

            # Faint grid background
            for gx in range(0, W, 40):
                cv2.line(frame, (gx, 0), (gx, H), (20,20,20), 1)
            for gy in range(0, H, 40):
                cv2.line(frame, (0, gy), (W, gy), (20,20,20), 1)

            # Move simulated persons
            for p in persons:
                p["x"] += p["vx"] + random.uniform(-0.3, 0.3)
                p["y"] += p["vy"] + random.uniform(-0.3, 0.3)
                p["x"] = max(60, min(W-60, p["x"]))
                p["y"] = max(80, min(H-80, p["y"]))

                x, y = int(p["x"]), int(p["y"])
                color = (0, 200, 255)
                cv2.rectangle(frame, (x-40, y-70), (x+40, y+70), color, 2)
                cv2.rectangle(frame, (x-40, y-98), (x+40+60, y-70), color, -1)
                cv2.putText(frame, f"person {p['conf']:.0%}",
                            (x-36, y-78), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 2)

                # Alert every 4 s
                alert_tick += 1
                if alert_tick > 120:
                    self._maybe_alert("person", p["conf"], "MEDIUM")
                    alert_tick = 0

            if source_failed:
                cv2.rectangle(frame, (14, 42), (420, 72), (0, 90, 160), -1)
                cv2.putText(frame, "DEMO MODE - SOURCE UNAVAILABLE",
                            (20, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

            frame = self._draw_hud(frame, len(persons))
            self._send_frame(frame)
            frame_n += 1
            self.fps = 20
            time.sleep(0.05)

    # ──────────────────────────────────────────────────────────────────────────
    def _draw_hud(self, frame, n_detections):
        H, W = frame.shape[:2]

        # Corner brackets
        blen, bthick = 20, 2
        col = (0, 230, 200)
        for (cx, cy) in [(0,0),(W,0),(0,H),(W,H)]:
            sx = 1 if cx == 0 else -1
            sy = 1 if cy == 0 else -1
            cv2.line(frame,(cx,cy),(cx+sx*blen,cy),col,bthick)
            cv2.line(frame,(cx,cy),(cx,cy+sy*blen),col,bthick)

        # Top bar
        cv2.rectangle(frame,(0,0),(W,32),(10,10,10),-1)
        cv2.putText(frame, f"  {self.camera_id}  |  AI ACTIVE  |  FPS:{self.fps:.0f}  |  DETECTIONS:{n_detections}",
                    (4,22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,230,200), 1)

        # Timestamp
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        cv2.putText(frame, ts, (W-200, H-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0,230,200), 1)

        # Recording dot
        if int(time.time()) % 2 == 0:
            cv2.circle(frame, (W-20, 16), 7, (0,0,255), -1)

        return frame

    def _send_frame(self, frame):
        if self.frame_callback:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.stream_jpeg_quality])
            b64 = base64.b64encode(buf).decode("utf-8")
            self.frame_callback(self.camera_id, b64)

    def _maybe_alert(self, label, conf, threat_level):
        now = time.time()
        last = self._last_alert_time.get(label, 0)
        if now - last < self.ALERT_COOLDOWN:
            return
        self._last_alert_time[label] = now
        self.detection_count += 1
        if self.alert_callback:
            self.alert_callback(
                self.camera_id, label, conf,
                f"Detected by AI model (conf={conf:.2f})",
                threat_level
            )
