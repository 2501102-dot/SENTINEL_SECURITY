# SENTINEL Smart Security System
# Main entry point - starts Flask server and opens dashboard

import os
import time
import webbrowser
import threading
from app import start_system, socketio, app

print("\n=== SENTINEL Smart Security System ===")
print("Starting up...\n")

port = int(os.environ.get("PORT", 5000))

def open_browser():
    time.sleep(3)
    webbrowser.open(f"http://127.0.0.1:{port}")

threading.Thread(target=open_browser, daemon=True).start()

start_system()
socketio.run(app, host="0.0.0.0", port=port, debug=False)
