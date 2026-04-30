@echo off
cd /d "%~dp0"
python -m pip install flask pandas openpyxl pystray pillow
python app.py
pause
