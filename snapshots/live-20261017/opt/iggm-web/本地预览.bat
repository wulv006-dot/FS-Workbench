@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Users\ch864\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "PYV=C:\Users\ch864\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%PYV%" (
  set "PY=%PYV%"
) else (
  "%PY%" -c "import flask" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo [!] Flask not found, installing...
    "%PY%" -m pip install -q flask
  )
)

if not exist data mkdir data
set IGGM_DATA=%CD%\data
set IGGM_EXPORTS=%CD%\data\exports
set IGGM_PORT=8787

echo.
echo   IGGM Price Scraper - Web Edition (local preview)
echo   ------------------------------------------------
echo   Open in browser:  http://127.0.0.1:8787/
echo   Close this window to stop the server.
echo.
start "" http://127.0.0.1:8787/
"%PY%" app.py
pause
