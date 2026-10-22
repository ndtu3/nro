@echo off
rem Chay game o che do nhe cho VPS yeu (1 core / 1 GB RAM): cua so nho, khong toan man hinh.
rem Dat file nay cung thu muc voi NgocRongViet.exe. Doi kich thuoc o duoi neu muon.
cd /d "%~dp0"
start "" /belownormal "%~dp0NgocRongViet.exe" -screen-fullscreen 0 -screen-width 400 -screen-height 240
