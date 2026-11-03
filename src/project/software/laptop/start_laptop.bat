@echo off
setlocal
cd /d "%~dp0"
set "ORDER_PYTHON=D:\hand\.venv\Scripts\python.exe"
if exist "%ORDER_PYTHON%" goto use_workspace
where py >nul 2>nul
if errorlevel 1 goto missing_python
py -3 laptop_app.py --board http://192.168.3.1:8765 --open-browser
goto finished
:use_workspace
"%ORDER_PYTHON%" laptop_app.py --board http://192.168.3.1:8765 --open-browser
goto finished
:missing_python
echo Python was not found. Read README_laptop.md for installation steps.
:finished
echo.
echo This console must stay open while the ordering application runs.
echo If an error appeared above, copy it before closing this window.
pause
