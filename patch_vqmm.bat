@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   VA LOI AUTO VQMM ^& TU DONG NHAN RUONG PHU
echo ========================================================
python "%~dp0patch_vqmm.py"
echo.
pause
