@echo off
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (
  echo venv missing - run scripts\setup_windows.bat first
  exit /b 1
)
echo Scanning all active sources... logs go to data\logs\
venv\Scripts\python -m photoindex scan --all
echo Building any missing thumbnails...
venv\Scripts\python -m photoindex thumbnails --missing
echo Done.
endlocal
