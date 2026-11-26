@echo off
chcp 65001 >nul
rem AI Fight Arena - double-click to start the server on this PC (Windows + Python 3 needed)
cd /d "%~dp0"
where python >nul 2>nul || (echo ไม่พบ Python: ติดตั้งจาก https://www.python.org/downloads/ แล้วติ๊ก "Add python.exe to PATH" & pause & exit /b 1)
python -m pip install -q -r requirements.txt || (echo ติดตั้งแพ็กเกจไม่สำเร็จ & pause & exit /b 1)
python arena.py %*
pause
