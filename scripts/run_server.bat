@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (
  echo venv missing - run scripts\setup_windows.bat first
  exit /b 1
)
start "" http://127.0.0.1:8420
venv\Scripts\python -m photoindex serve
endlocal
