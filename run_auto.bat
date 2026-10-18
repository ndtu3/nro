@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" pythonw "%~dp0auto_helper.py"
if errorlevel 1 (
    python "%~dp0auto_helper.py"
    pause
)
