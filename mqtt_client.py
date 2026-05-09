"""
mqtt_client.py - MQTT Publisher & Subscriber
Smart Security Surveillance System
Uses: broker.hivemq.com (public broker, no install needed on Windows)
"""

import paho.mqtt.client as mqtt
import json
import time
import threading

BROKER   = "broker.hivemq.com"
PORT     = 1883
TOPIC_ALERT   = "smartsec/alerts"
TOPIC_STATUS  = "smartsec/status"
TOPIC_COMMAND = "smartsec/command"

_client = None
_connected = False
_message_callback = None


def on_connect(client, userdata, flags, rc, props=None):
    global _connected
    if rc == 0:
        _connected = True
        print(f"[MQTT] Connected to broker: {BROKER}")
        client.subscribe(TOPIC_COMMAND)
        client.subscribe(TOPIC_ALERT)
    else:
        print(f"[MQTT] Connection failed, code: {rc}")


def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    print(f"[MQTT] Received on {msg.topic}: {payload}")
    if _message_callback:
        try:
            data = json.loads(payload)
            _message_callback(msg.topic, data)
        except Exception:
            _message_callback(msg.topic, {"raw": payload})


def on_disconnect(client, userdata, rc, props=None):
    global _connected
    _connected = False
    print("[MQTT] Disconnected")


def init_mqtt(message_callback=None):
    global _client, _message_callback
    _message_callback = message_callback
    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    _client.on_connect    = on_connect
    _client.on_message    = on_message
    _client.on_disconnect = on_disconnect
    try:
        _client.connect(BROKER, PORT, keepalive=60)
        _client.loop_start()
    except Exception as e:
        print(f"[MQTT] Could not connect: {e}  — running in offline mode")


def publish_alert(camera_id, event_type, confidence, details="", threat_level="LOW"):
    payload = json.dumps({
        "camera_id"   : camera_id,
        "event_type"  : event_type,
        "confidence"  : round(confidence, 2),
        "details"     : details,
        "threat_level": threat_level,
        "timestamp"   : time.strftime("%Y-%m-%d %H:%M:%S")
    })
    if _client and _connected:
        _client.publish(TOPIC_ALERT, payload)
        print(f"[MQTT] Alert published: {event_type} @ {camera_id}")
    else:
        print(f"[MQTT] Offline — alert not sent: {payload}")
    return payload


def publish_status(cameras_active, total_alerts):
    payload = json.dumps({
        "cameras_active": cameras_active,
        "total_alerts"  : total_alerts,
        "timestamp"     : time.strftime("%Y-%m-%d %H:%M:%S")
    })
    if _client and _connected:
        _client.publish(TOPIC_STATUS, payload)


def is_connected():
    return _connected


def stop():
    if _client:
        _client.loop_stop()
        _client.disconnect()
