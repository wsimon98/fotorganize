@echo off
rem Stops the background fotorganize server started by start_fotorganize.bat.
rem Falls back to killing whatever listens on port 8420 if the PID file is stale.
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$stopped = $false; $pidFile = 'data\fotorganize.pid';" ^
  "if (Test-Path $pidFile) {" ^
  "  $sPid = Get-Content $pidFile;" ^
  "  if (Get-Process -Id $sPid -ErrorAction SilentlyContinue) { taskkill /PID $sPid /T /F | Out-Null; Write-Host \"fotorganize stopped (PID $sPid)\"; $stopped = $true };" ^
  "  Remove-Item $pidFile -ErrorAction SilentlyContinue };" ^
  "if (-not $stopped) {" ^
  "  $conns = Get-NetTCPConnection -LocalPort 8420 -State Listen -ErrorAction SilentlyContinue;" ^
  "  foreach ($c in ($conns.OwningProcess | Select-Object -Unique)) { taskkill /PID $c /T /F | Out-Null; Write-Host \"fotorganize stopped - port 8420, PID $c\"; $stopped = $true } };" ^
  "if (-not $stopped) { Write-Host 'fotorganize was not running.' }"
endlocal
