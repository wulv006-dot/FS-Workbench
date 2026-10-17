@echo off
rem ===================================================================
rem  MLB New Card Agent - Windows launcher
rem
rem  !! KEEP THIS FILE PURE ASCII (7-bit) ON PURPOSE !!
rem  Do NOT add Chinese text to this file. cmd.exe reads .bat files
rem  using the console code page, not UTF-8. Mixing multi-byte text
rem  here corrupts parsing (see DEPLOY_NOTES.md, 2026-10-05).
rem  All Chinese messages are printed by mlb_agent.py instead.
rem
rem  Requirements: CRLF line endings, no BOM.
rem ===================================================================

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   MLB New Card Agent  -  Local Runner
echo ============================================================
echo.
echo   A browser window will pop up for the human-verification
echo   step. Click the verification once on the first run.
echo   Keep both this window and the browser window OPEN.
echo.

rem ---------- 1) locate Python ----------
rem Resolve to a FULL executable path (never a bare command like
rem "py -3"), so every call site can safely quote it even when the
rem path contains spaces. Asking Python for sys.executable is the
rem most reliable way on Windows.
set "PY="

for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not "%%~P"=="" set "PY=%%~P"
)
if not "!PY!"=="" goto :got_python

for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not "%%~P"=="" set "PY=%%~P"
)
if not "!PY!"=="" goto :got_python

for %%D in (
    "%LOCALAPPDATA%\Programs\Python"
    "C:\Python313" "C:\Python312" "C:\Python311" "C:\Python310" "C:\Python39"
    "C:\Program Files\Python313" "C:\Program Files\Python312"
) do (
    if exist "%%~D" (
        for /d %%V in ("%%~D\Python3*") do (
            if exist "%%~V\python.exe" (
                set "PY=%%~V\python.exe"
                goto :got_python
            )
        )
    )
)

echo [X] Python not found. Please install Python 3.8 or newer:
echo     https://www.python.org/downloads/
echo     Tick "Add Python to PATH" during setup.
echo.
pause
exit /b 1

:got_python
echo [*] Python: !PY!
"!PY!" --version
echo.

rem ---------- 2) dependencies ----------
echo [*] Checking dependencies (playwright / openpyxl) ...
"!PY!" -c "import playwright, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo [!] Installing missing dependencies, 1-3 minutes ...
    "!PY!" -m pip install --upgrade pip >nul 2>nul
    "!PY!" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [X] Dependency install failed. Check the network, or run:
        echo     "!PY!" -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo [*] Installing Playwright browser ...
    "!PY!" -m playwright install chromium
    echo [OK] Dependencies installed.
) else (
    echo [OK] Dependencies ready.
)
echo.

rem ---------- 3) password ----------
rem Priority: env var > .mlb_pass file > interactive input.
rem The password is passed via the MLB_AGENT_PASSWORD environment
rem variable, NOT via --password on the command line, so characters
rem like & ^ % ! " < > are never interpreted by cmd.exe.
rem
rem Two cmd.exe pitfalls are deliberately avoided here:
rem   1) `goto` inside a parenthesized if-block is unreliable in cmd
rem      (it can abort the whole block, leaving the file "not found"),
rem      so flow is controlled with a flag variable instead.
rem   2) Notepad forces an extension, so a file the user saved as
rem      ".mlb_pass" actually lands on disk as ".mlb_pass.txt".
rem      Both spellings are accepted; mlb_agent.py knows them too.
set "PASS_SRC="

if not "!MLB_AGENT_PASSWORD!"=="" set "PASS_SRC=env"

if not defined PASS_SRC if exist ".mlb_pass" (
    set /p MLB_AGENT_PASSWORD=<".mlb_pass"
    set "PASS_SRC=file .mlb_pass"
)

if not defined PASS_SRC if exist ".mlb_pass.txt" (
    set /p MLB_AGENT_PASSWORD=<".mlb_pass.txt"
    set "PASS_SRC=file .mlb_pass.txt"
)

if not defined PASS_SRC (
    echo [*] Enter the MLB console password ^(account: wulv^).
    echo     Tip: to skip this next time, put the password on a
    echo     single line in a file named .mlb_pass here.
    echo.
    set /p "MLB_AGENT_PASSWORD=Password: "
    set "PASS_SRC=interactive input"
)

rem No CR/space trimming needed here: mlb_agent.py calls .strip()
rem on whatever it receives, so a trailing CRLF from the password
rem file is harmless.
if "!MLB_AGENT_PASSWORD!"=="" (
    echo [X] Password is empty. Aborted.
    pause
    exit /b 1
)
echo [OK] Password source: !PASS_SRC!

rem ---------- 4) login mode ----------
rem 1 = auto  : read password from .mlb_pass and POST it to the portal
rem 2 = manual: skip the password entirely, pop a Chrome window and
rem             let the human log in by hand. Use this when the portal
rem             rejects the stored password (changed / locked / SSO).
rem The site forces HTTPS on /__auth/, so the URL MUST be https://.
set "MODE=auto"

echo.
echo   Login mode:
echo     [1] Auto   - use the password in .mlb_pass
echo     [2] Manual - open Chrome, you log in yourself  (recommended
echo                   if auto login keeps failing)
echo.
set "CHOICE="
set /p "CHOICE=Select 1 or 2 (Enter = 1): "
if /i "!CHOICE!"=="2" (
    set "MODE=manual"
) else (
    set "MODE=auto"
)

set "PASS_SRC="
set "MLB_AGENT_PASSWORD="

if "!MODE!"=="manual" goto :launch_manual

rem ---------- 5) resolve password (auto mode only) ----------
rem ---------- 6) launch ----------
echo [*] Starting agent (login mode: !MODE!), this window will keep printing logs ...
echo     Success looks like: "connected to server, heartbeat OK"
echo.

if "!MODE!"=="manual" goto :launch_manual

"!PY!" mlb_agent.py --server "https://47.85.224.112" --user wulv --agent "%COMPUTERNAME%" --show
goto :after_launch

:launch_manual
echo[*] Manual login mode: a Chrome window will open on the login page.
echo     Log in inside that window. Cookie is kept for 30 days, so
echo     later runs in auto mode will usually work too.
echo.
"!PY!" mlb_agent.py --server "https://47.85.224.112" --user wulv --agent "%COMPUTERNAME%" --show --manual-login
goto :after_launch

:after_launch
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo [done] Agent exited with code %RC%
    echo.
    echo If the log says 303 / 308 redirect, the site now forces HTTPS.
    echo If login failed again, rerun this file and pick option [2].
) else (
    echo [done] Agent exited normally
)
echo.
pause
endlocal
