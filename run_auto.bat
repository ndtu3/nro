@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYW_EXE="
set "PY_EXE="
where pythonw >nul 2>nul && set "PYW_EXE=pythonw"
python -c "import sys" >nul 2>nul && set "PY_EXE=python"

if not defined PY_EXE (
    for /d %%D in ("%APPDATA%\uv\python\cpython-*") do (
        if exist "%%~fD\pythonw.exe" set "PYW_EXE=%%~fD\pythonw.exe"
        if exist "%%~fD\python.exe" set "PY_EXE=%%~fD\python.exe"
    )
)
if not defined PY_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%~fD\pythonw.exe" set "PYW_EXE=%%~fD\pythonw.exe"
        if exist "%%~fD\python.exe" set "PY_EXE=%%~fD\python.exe"
    )
)

if defined PYW_EXE (
    start "" "%PYW_EXE%" "%~dp0auto_helper.py"
    exit /b 0
)
if defined PY_EXE (
    "%PY_EXE%" "%~dp0auto_helper.py"
    pause
    exit /b 0
)
echo [LOI] Khong tim thay Python tren may!
pause
