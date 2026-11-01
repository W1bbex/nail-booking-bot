@echo off
setlocal
cd /d "%~dp0"

:: Force UTF-8 encoding for Python and console
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>nul

if exist "%~dp0.venv\Scripts\python.exe" goto :RUN

echo Preparing Python environment, please wait...

where python >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :VENV
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :VENV
)

echo [ERROR] Python was not found on this computer.
echo Please download and install Python 3.11+ from: https://www.python.org
echo IMPORTANT: Check the box "Add Python to PATH" during installation!
echo.
pause
exit /b 1

:VENV
echo Creating virtual environment (.venv)...
%PY_CMD% -m venv "%~dp0.venv"
if errorlevel 1 (
    echo [ERROR] Could not create virtual environment.
    pause
    exit /b 1
)

echo Installing dependencies from requirements.txt...
"%~dp0.venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] Could not install dependencies. Check your internet connection.
    pause
    exit /b 1
)

:RUN
"%~dp0.venv\Scripts\python.exe" -u "%~dp0launcher.py"
if errorlevel 1 (
    pause
    exit /b 1
)
