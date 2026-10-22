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
    echo [LOI] Khong tim thay Python tren may!
    pause
    exit /b 1
)

rem Python cua uv khong cho pip cai thang vao -> cai frida vao thu muc .deps canh tool
"%PY_EXE%" -c "import sys; sys.path.insert(0, r'%~dp0.deps'); import frida" >nul 2>nul
if errorlevel 1 (
    echo Dang cai thu vien frida...
    "%PY_EXE%" -m pip install --target "%~dp0.deps" frida
)

"%PY_EXE%" "%~dp0boss_hunter.py"
if errorlevel 1 pause
