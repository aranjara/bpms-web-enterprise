@echo off
cd /d "%~dp0"
python -m pip install flask pandas openpyxl pystray pillow >nul 2>&1
start "" pythonw tray_app.py
