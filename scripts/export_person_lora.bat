@echo off
rem Export a LoRA dataset for a person.
rem Usage: export_person_lora.bat "George Clooney" [trigger_word]
rem   trigger_word defaults to <name>_person inside the app if omitted.
setlocal
cd /d "%~dp0..\backend"
if not exist venv\Scripts\python.exe (echo run setup_windows.bat first & exit /b 1)
if "%~1"=="" (echo Usage: export_person_lora.bat "PersonName" [trigger_word] & exit /b 1)

if "%~2"=="" (
  venv\Scripts\python -m photoindex export-lora --person "%~1" --zip
) else (
  venv\Scripts\python -m photoindex export-lora --person "%~1" --trigger "%~2" --zip
)
echo Output is under data\exports\
endlocal
