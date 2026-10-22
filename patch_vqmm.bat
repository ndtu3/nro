@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   VA LOI AUTO VQMM ^& TU DONG NHAN RUONG PHU
echo ========================================================

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
    if exist "%USERPROFILE%\.uv\uv.exe" (
        "%USERPROFILE%\.uv\uv.exe" run python "%~dp0patch_vqmm.py" %*
        goto :done
    )
    echo [LOI] Khong tim thay Python tren may!
    goto :done
)

"%PY_EXE%" "%~dp0patch_vqmm.py" %*

:done
echo.
pause
