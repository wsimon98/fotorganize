@echo off
rem Runs the GPU worker loop (processes caption/face/cluster jobs). Ctrl+C to stop.
rem Run this in its OWN window alongside the web server.
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (echo run setup_windows.bat first & exit /b 1)
echo fotorganize worker starting - processes AI jobs. Ctrl+C to stop.
venv\Scripts\python -m photoindex worker
endlocal
