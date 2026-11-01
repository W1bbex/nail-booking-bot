@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===================================================
echo [i] Zapusk testov pytest...
echo ===================================================
call "%~dp0.venv\Scripts\python.exe" -u -m pytest -v
echo.
pause
