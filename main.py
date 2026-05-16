"""SENTINEL Smart Security System - Entry Point"""
import os
import time
import threading
import webbrowser
from app import start_system, socketio, app

port = int(os.environ.get("PORT", 5000))
is_production = os.environ.get('FLASK_ENV') == 'production'

print("\n🛡  SENTINEL — Starting...\n")

# Open browser in development
if not is_production:
    def open_browser():
        time.sleep(3)
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except:
            pass
    threading.Thread(target=open_browser, daemon=True).start()

start_system()

if __name__ == '__main__':
    if is_production:
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
