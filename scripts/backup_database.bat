@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (
  echo venv missing - run scripts\setup_windows.bat first
  exit /b 1
)
venv\Scripts\python -m photoindex backup
endlocal
