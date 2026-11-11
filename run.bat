@echo off
rem Start the program without a console window (double click).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo The virtual environment is missing. Run:  python -m venv .venv
    echo and then:  .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m app
