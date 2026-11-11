@echo off
rem Build one file: dist\TelegramSuggest.exe (no Python needed on the target PC).
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
    echo The virtual environment is missing. Run:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    pause
    exit /b 1
)

echo [1/5] Tests
"%PY%" -m pytest -q || goto :failed

echo [2/5] UI Automation wrappers (generated once, then bundled)
"%PY%" -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')" || goto :failed

echo [3/5] Icon and version information
"%PY%" scripts\make_icon.py build\icon.ico || goto :failed
"%PY%" scripts\version_info.py build\version_info.txt || goto :failed

echo [4/5] Packing
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN TelegramSuggest.spec || goto :failed

echo [5/5] Start check
"dist\TelegramSuggest.exe" --db "%TEMP%\TelegramSuggest-buildcheck.db" --exit-after 3
if errorlevel 1 goto :failed
del /q "%TEMP%\TelegramSuggest-buildcheck.db*" 2>nul

echo.
echo Done: dist\TelegramSuggest.exe
for %%F in (dist\TelegramSuggest.exe) do echo Size: %%~zF bytes
exit /b 0

:failed
echo.
echo BUILD FAILED
exit /b 1
