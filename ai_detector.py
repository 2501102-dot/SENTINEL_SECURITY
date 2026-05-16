"""AI Detection Engine - YOLOv8 Object Detection"""
import cv2
import threading
import time
import base64
import numpy as np
import os

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except:
    YOLO_AVAILABLE = False
    print("[AI] YOLOv8 not installed - detection disabled")

THREAT_CLASSES = {0: "person"}
HIGH_THREAT = {43: "knife", 76: "scissors"}
CONF_THRESHOLD = 0.50

class AIDetector:
    _shared_model = None
    _model_lock = threading.Lock()
    _infer_lock = threading.Lock()

    def __init__(self, source=0, camera_id="CAM-01", alert_callback=None, frame_callback=None):
        self.source = source
        self.camera_id = camera_id
        self.alert_callback = alert_callback
        self.frame_callback = frame_callback
        
        self.model = None
        self.cap = None
        self.running = False
        self._thread = None
        self.fps = 0
        self.frame_count = 0
        self.infer_every_n = 5  # Run inference every 5 frames
        self.stream_width = 1080  # Resize frames to this width
        self.stream_quality = 35  # JPEG quality
        self._last_alert_time = {}
        self.ALERT_COOLDOWN = 4
        self._last_detections = []

    def load_model(self):
        """Load YOLOv8 model"""
        if not YOLO_AVAILABLE:
            return
        
        with self._model_lock:
            if AIDetector._shared_model is None:
                print("[AI] Loading YOLOv8 model...")
                try:
                    AIDetector._shared_model = YOLO("yolov8n.pt")
                    print("[AI] Model loaded ✓")
                except Exception as e:
                    print(f"[AI] Model load failed: {e}")
                    return
        
        self.model = AIDetector._shared_model

    def start(self):
        """Start detection thread"""
        self.load_model()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[AI] {self.camera_id} started (source={self.source})")

    def stop(self):
        """Stop detection"""
        self.running = False
        if self.cap:
            self.cap.release()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        """Main detection loop"""
        self._run_detection()

    def _run_detection(self):
        """Run object detection"""
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            print(f"[AI] Cannot open source: {self.source}")
            return

        t_prev = time.time()
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                time.sleep(0.02)
                continue

            annotated = frame.copy()
            self.frame_count += 1

            # Run inference every N frames
            if self.frame_count % self.infer_every_n == 0:
                if self.model:
                    detections = self._detect(frame)
                    self._last_detections = detections
                else:
                    detections = []
            else:
                detections = self._last_detections

            # Draw boxes
            for cls_id, label, conf, threat_level, x1, y1, x2, y2 in detections:
                color = (0, 0, 255) if threat_level == "HIGH" else (0, 200, 255) if threat_level == "MEDIUM" else (0, 255, 100)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.rectangle(annotated, (x1, y1-28), (x1 + len(label)*12 + 60, y1), color, -1)
                cv2.putText(annotated, f"{label} {conf:.0%}", (x1+4, y1-8),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

            # Add HUD
            annotated = self._draw_hud(annotated, len(detections))

            # Resize for streaming
            H, W = annotated.shape[:2]
            if W > self.stream_width:
                new_w = self.stream_width
                new_h = int(H * (new_w / W))
                annotated = cv2.resize(annotated, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Send frame
            self._send_frame(annotated)

            # Fire alerts
            for cls_id, label, conf, threat_level, *_ in detections:
                if cls_id in THREAT_CLASSES or cls_id in HIGH_THREAT:
                    self._maybe_alert(label, conf, threat_level)

            # FPS
            now = time.time()
            self.fps = 1.0 / max(now - t_prev, 1e-6)
            t_prev = now

            # Throttle
            time.sleep(0.05)

        self.cap.release()

    def _detect(self, frame):
        """Run YOLO inference"""
        try:
            with self._infer_lock:
                results = self.model(frame, verbose=False)[0]
            
            detections = []
            for box in results.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if conf < CONF_THRESHOLD:
                    continue
                
                label = results.names[cls_id]
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                threat_level = "HIGH" if cls_id in HIGH_THREAT else "MEDIUM" if cls_id in THREAT_CLASSES else "LOW"
                detections.append((cls_id, label, conf, threat_level, x1, y1, x2, y2))
            
            return detections
        except Exception as e:
            print(f"[AI] Detection error: {e}")
            return []

    def _draw_hud(self, frame, det_count):
        """Add HUD to frame"""
        H, W = frame.shape[:2]
        cv2.rectangle(frame, (10, 10), (300, 80), (0, 50, 50), -1)
        cv2.putText(frame, f"FPS: {self.fps:.1f}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 200), 1)
        cv2.putText(frame, f"Detections: {det_count}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 200), 1)
        return frame

    def _send_frame(self, frame):
        """Encode and send frame to dashboard"""
        try:
            _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.stream_quality])
            b64 = base64.b64encode(buf).decode('utf-8')
            if self.frame_callback:
                self.frame_callback(self.camera_id, b64)
        except Exception as e:
            print(f"[AI] Frame encode error: {e}")

    def _maybe_alert(self, label, conf, threat_level):
        """Fire alert if not in cooldown"""
        now = time.time()
        last = self._last_alert_time.get(label, 0)
        
        if now - last < self.ALERT_COOLDOWN:
            return
        
        self._last_alert_time[label] = now
        
        if self.alert_callback:
            self.alert_callback(self.camera_id, label, conf, "", threat_level)
