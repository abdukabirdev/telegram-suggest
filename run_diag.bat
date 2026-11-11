@echo off
rem Start the program with a console that shows what it sees (for checking).
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" -X utf8 -m app --diag
pause
