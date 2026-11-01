@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title CLI comparison
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python virtual environment .venv not found.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -u "%~dp0cli_comparison.py"
if errorlevel 1 pause
