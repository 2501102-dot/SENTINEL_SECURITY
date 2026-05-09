# SENTINEL - Smart Security Surveillance System

Computer Networks Project, Air University

## What This Project Does
1. Runs 4 camera/demo video feeds in a real-time dashboard.
2. Uses YOLOv8 for AI detection.
3. Sends alerts in ALERT mode (Telegram + WhatsApp if configured).
4. Uses MQTT + SQLite for messaging and logs.

## Project Structure
```text
smart_security/
|- main.py
|- app.py
|- ai_detector.py
|- notifier.py
|- mqtt_client.py
|- database.py
|- camera_sources.txt
|- notification_config.example.json
|- notification_config.json
|- requirements.txt
|- templates/
|  |- index.html
|- videos/
```

## Requirements
1. Python 3.9+
2. Windows 10 or 11
3. Internet for first-time dependency/model download

## Start From Zero (Fresh Machine)

### 1) Clone and enter folder
```powershell
git clone <YOUR_GITHUB_REPO_URL>
cd smart_security
```

### 2) Create virtual environment
```powershell
python -m venv .venv
```

### 3) Activate virtual environment
```powershell
.\.venv\Scripts\Activate.ps1
```

### 4) Install dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5) Configure notification file
```powershell
Copy-Item notification_config.example.json notification_config.json
```

Open notification_config.json and fill your real values:
1. TELEGRAM_BOT_TOKEN
2. TELEGRAM_CHAT_ID
3. ULTRAMSG_INSTANCE_ID
4. ULTRAMSG_TOKEN
5. ULTRAMSG_TO

### 6) Prepare 4 demo sources
camera_sources.txt should contain exactly 4 lines (already provided in this project).

Example:
```text
videos/demo1.mp4
videos/demo2.mp4
videos/demo3.mp4
videos/demo4.mp4
```

## Run Commands

### Run in SIMPLE mode (no push notifications)
```powershell
$env:SMARTSEC_MODE="SIMPLE"
python main.py
```

### Run in ALERT mode (detection + notifications)
```powershell
$env:SMARTSEC_MODE="ALERT"
python main.py
```

Dashboard URL:
```text
http://127.0.0.1:5000
```

## Useful Runtime Commands (Presentation Friendly)

### Check current system state
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/state" -Method Get
```

### Force ALERT mode while app is running
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/mode" -Method Post -ContentType "application/json" -Body '{"mode":"ALERT"}'
```

### Switch back to SIMPLE mode while app is running
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/mode" -Method Post -ContentType "application/json" -Body '{"mode":"SIMPLE"}'
```

### Send a test notification
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5000/api/test_notification" -Method Post
```

## One-Command Startup (After First-Time Setup)

If .venv already exists and config is done:
```powershell
cd <PATH_TO_PROJECT>
.\.venv\Scripts\python.exe main.py
```

## Presentation Day Quick Checklist
1. Open terminal in project folder.
2. Activate .venv.
3. Run ALERT mode command.
4. Open dashboard at http://127.0.0.1:5000.
5. Call /api/test_notification once to prove alerts work.

## Notes
1. Keep notification_config.json private. Do not commit real tokens.
2. If PowerShell blocks activation, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
3. If dependencies fail, re-run pip install -r requirements.txt inside .venv.
