# SENTINEL Smart Security System
# Main entry point - starts Flask server and opens dashboard

import time
import webbrowser
import threading
from app import start_system, socketio, app

print("\n=== SENTINEL Smart Security System ===")
print("Starting up...\n")

def open_browser():
    time.sleep(3)
    webbrowser.open("http://127.0.0.1:5000")

threading.Thread(target=open_browser, daemon=True).start()

start_system()
socketio.run(app, host="0.0.0.0", port=5000, debug=False)
