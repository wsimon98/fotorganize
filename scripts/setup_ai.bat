@echo off
rem Installs AI dependencies (Phases 3-5) in the correct order for a Blackwell GPU.
rem Run AFTER setup_windows.bat.
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (echo run setup_windows.bat first & exit /b 1)

echo [1/4] Installing torch + torchvision (CUDA cu128 - required for RTX 50xx)...
venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 || (echo torch install failed & exit /b 1)

echo [2/4] Installing captioning + face deps...
venv\Scripts\python -m pip install -r requirements-ai.txt || (echo AI deps failed & exit /b 1)

echo [3/4] Removing CPU onnxruntime (insightface pulls it in; keep only -gpu)...
venv\Scripts\python -m pip uninstall -y onnxruntime 2>nul

echo [4/4] Re-pinning torch cu128 (AI deps may have pulled a CPU build)...
venv\Scripts\python -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128

echo.
echo Verifying GPU...
venv\Scripts\python -c "import torch,onnxruntime as o; print('torch cuda:', torch.cuda.is_available()); print('onnx providers:', o.get_available_providers())"
echo.
echo Done. First caption/face run downloads models (~1-2 GB) to the HF cache.
echo Start the worker with:  scripts\start_worker.bat
endlocal
