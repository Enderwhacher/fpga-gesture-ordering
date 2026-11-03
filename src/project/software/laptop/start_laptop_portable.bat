@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" laptop_app.py --board http://192.168.3.1:8765 --open-browser
) else (
  py -3 laptop_app.py --board http://192.168.3.1:8765 --open-browser
)
echo.
echo Keep this console open while ordering. Press Ctrl+C to stop and save logs.
pause
