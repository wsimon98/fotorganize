@echo off
setlocal
cd /d "%~dp0.."
echo === fotorganize setup ===

echo.
echo [1/5] Checking Python...
python --version || (echo ERROR: python not found on PATH & exit /b 1)

echo.
echo [2/5] Checking npm (not required for Phase 1, informational only)...
call npm --version 2>nul || echo npm not found - OK, frontend has no build step

echo.
echo [3/5] Creating virtual environment at backend\venv ...
if not exist backend\venv (
  python -m venv backend\venv || (echo ERROR: venv creation failed & exit /b 1)
) else (
  echo venv already exists, skipping
)

echo.
echo [4/5] Installing Python requirements...
backend\venv\Scripts\python -m pip install --upgrade pip -q
backend\venv\Scripts\python -m pip install -r backend\requirements.txt || (echo ERROR: pip install failed - see TROUBLESHOOTING.md & exit /b 1)

echo.
echo [5/5] Checking GPU visibility (informational, needed from Phase 3)...
nvidia-smi --query-gpu=name --format=csv,noheader 2>nul || echo nvidia-smi not found

if not exist .env (
  copy .env.example .env >nul
  echo Created .env from .env.example
)

echo.
echo === Setup complete ===
echo Next: run  scripts\run_server.bat  then open http://127.0.0.1:8420
endlocal
