@echo off
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
  taskkill /PID %%a /F >nul 2>&1
)
taskkill /IM pythonw.exe /F >nul 2>&1
