@echo off
REM ============================================================
REM  AION2 DD373 本机采集 + 推送（供 Windows 计划任务调用，静默）
REM   - 复用缓存的浏览器 cookie；cookie 过期才开一次 Edge
REM   - 采集 86 区 → 经 SSH 推到服务器 /api/dd373_cost
REM   - 日志：<本目录>\logs\collect_log.txt
REM ============================================================
set PY=C:\Users\yi\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -u "%~dp0dd373_local_collect.py" --push --gap 1.5 >> "%~dp0logs\collect_log.txt" 2>&1
exit /b %ERRORLEVEL%
