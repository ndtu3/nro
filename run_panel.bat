@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY_EXE="
python -c "import sys" >nul 2>nul && set "PY_EXE=python"

if not defined PY_EXE (
    for /d %%D in ("%APPDATA%\uv\python\cpython-*") do (
        if exist "%%~fD\python.exe" set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%~fD\python.exe" set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    echo [LOI] Khong tim thay Python tren may! Dung dist\ControlPanel.exe (khong can Python).
    pause
    exit /b 1
)

"%PY_EXE%" "%~dp0control_panel.py"
if errorlevel 1 pause
