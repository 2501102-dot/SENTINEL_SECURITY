"""MQTT Client - Publish alerts to broker"""
import paho.mqtt.client as mqtt
import json
import time
import threading

BROKER = "broker.hivemq.com"
BROKER_BACKUP = "test.mosquitto.org"
PORT = 1883
TOPIC_ALERT = "smartsec/alerts"
TOPIC_STATUS = "smartsec/status"

_client = None
_connected = False
_reconnect_thread = None
_stop_reconnect = False
_reconnect_delay = 5

def on_connect(client, userdata, flags, rc, props=None):
    global _connected
    _connected = (rc == 0)
    if _connected:
        print(f"[MQTT] ✓ Connected to {BROKER}")
        client.subscribe(TOPIC_ALERT)
    else:
        print(f"[MQTT] Connection failed: code {rc}")

def on_disconnect(client, userdata, rc, props=None):
    global _connected
    _connected = False
    if rc != 0:
        print(f"[MQTT] Unexpected disconnection: code {rc}")

def on_message(client, userdata, msg):
    """Handle incoming messages"""
    try:
        payload = json.loads(msg.payload.decode())
        print(f"[MQTT] Received: {payload}")
    except:
        pass

def reconnect_mqtt():
    """Auto-reconnect logic with exponential backoff"""
    global _client, _connected, _reconnect_delay, _stop_reconnect
    
    while not _stop_reconnect:
        if not _connected and _client:
            try:
                print(f"[MQTT] Attempting reconnect in {_reconnect_delay}s...")
                time.sleep(_reconnect_delay)
                _client.reconnect()
                _reconnect_delay = 5  # Reset delay on success
            except Exception as e:
                print(f"[MQTT] Reconnect failed: {e}")
                _reconnect_delay = min(_reconnect_delay * 1.5, 60)  # Max 60s
        else:
            time.sleep(2)

def init_mqtt(message_callback=None):
    global _client, _reconnect_thread, _stop_reconnect
    _stop_reconnect = False
    
    try:
        _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"smartsec-{int(time.time())}")
        _client.on_connect = on_connect
        _client.on_disconnect = on_disconnect
        _client.on_message = on_message
        
        print(f"[MQTT] Connecting to {BROKER}...")
        _client.connect(BROKER, PORT, keepalive=60)
        _client.loop_start()
        
        # Start auto-reconnect thread
        _reconnect_thread = threading.Thread(target=reconnect_mqtt, daemon=True)
        _reconnect_thread.start()
        
        print("[MQTT] Initialization complete")
    except Exception as e:
        print(f"[MQTT] Init error: {e}")
        # Try backup broker
        try_backup_broker()

def try_backup_broker():
    """Fallback to backup broker"""
    global _client, _connected
    try:
        print(f"[MQTT] Trying backup broker: {BROKER_BACKUP}")
        _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"smartsec-{int(time.time())}")
        _client.on_connect = on_connect
        _client.on_disconnect = on_disconnect
        _client.on_message = on_message
        _client.connect(BROKER_BACKUP, PORT, keepalive=60)
        _client.loop_start()
    except Exception as e:
        print(f"[MQTT] Backup broker also failed: {e}")

def publish_alert(camera_id, event_type, confidence, details="", threat_level="LOW"):
    """Publish alert to MQTT broker"""
    if not _client or not _connected:
        return False
    
    try:
        payload = json.dumps({
            "camera_id": camera_id,
            "event_type": event_type,
            "confidence": round(confidence, 2),
            "threat_level": threat_level,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        _client.publish(TOPIC_ALERT, payload, qos=1)
        return True
    except Exception as e:
        print(f"[MQTT] Publish error: {e}")
        return False

def is_connected():
    return _connected

def stop():
    """Stop MQTT client"""
    global _client, _stop_reconnect
    _stop_reconnect = True
    if _client:
        _client.loop_stop()
        _client.disconnect()
