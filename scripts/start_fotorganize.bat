@echo off
rem Starts fotorganize in the BACKGROUND (no console window stays open).
rem PID is written to data\fotorganize.pid for stop_fotorganize.bat.
rem For a foreground server with live logs, use run_server.bat instead.
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (
  echo venv missing - run scripts\setup_windows.bat first
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pidFile = '..\data\fotorganize.pid';" ^
  "if (Test-Path $pidFile) { $old = Get-Content $pidFile; if (Get-Process -Id $old -ErrorAction SilentlyContinue) { Write-Host \"fotorganize already running with PID $old - http://127.0.0.1:8420\"; exit 0 } };" ^
  "$p = Start-Process -FilePath 'venv\Scripts\python.exe' -ArgumentList '-m','photoindex','serve' -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru;" ^
  "Set-Content -Path $pidFile -Value $p.Id;" ^
  "foreach ($i in 1..15) { try { Invoke-RestMethod http://127.0.0.1:8420/api/health -TimeoutSec 2 | Out-Null; Write-Host \"fotorganize started (PID $($p.Id)) - http://127.0.0.1:8420\"; Start-Process 'http://127.0.0.1:8420'; exit 0 } catch { Start-Sleep 1 } };" ^
  "Write-Host 'WARNING: server did not answer health check yet - check data\logs\app.log'"
endlocal
