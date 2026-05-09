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
    """Only open browser in development mode (localhost)"""
    time.sleep(3)
    webbrowser.open(f"http://127.0.0.1:{port}")

# Check if running in production (Railway or gunicorn)
is_production = os.environ.get('FLASK_ENV') == 'production' or 'gunicorn' in os.environ.get('SERVER_SOFTWARE', '')

if not is_production:
    # Development mode: open browser and use werkzeug
    threading.Thread(target=open_browser, daemon=True).start()

start_system()

if __name__ == '__main__':
    # When run directly (development), use socketio.run with Werkzeug
    # When run via gunicorn (production), gunicorn handles the server
    if not is_production:
        socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
    else:
        # In production (gunicorn), just keep the app running
        # gunicorn will handle the socket.io server
        app.run(host="0.0.0.0", port=port, debug=False)
