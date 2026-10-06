@echo off
REM ============================================================
REM  DD373 local collector + push  (AION2 Kinah cost)
REM  - uses cached browser cookie; opens Edge only when it expires
REM  - pushes the result to the server /api/dd373_cost
REM  - log: ..\验证\push_log.txt
REM ============================================================
set PY=C:\Users\yi\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%~dp0dd373_local_collect.py" --push >> "%~dp0..\验证\push_log.txt" 2>&1
exit /b %ERRORLEVEL%
