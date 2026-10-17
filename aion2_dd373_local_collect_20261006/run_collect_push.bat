@echo off
REM ============================================================
REM  DD373 本机采集 + 推送（AION2 + MSCW 冒险岛 · 供 Windows 计划任务调用，静默）
REM   - 复用缓存的浏览器 cookie；cookie 过期才开一次 Edge
REM   - 采集 AION2 86 区 + MSCW 1 区 → 分别经 SSH 推到服务器 /api/dd373_cost
REM     （2026-10-15 方案 A：必须覆盖服务器采集目标的每个游戏，否则
REM      服务器「优先本机推送」会让未推送的游戏成本被整轮跳过、长期冻结）
REM   - 日志：<本目录>\logs\collect_log.txt
REM ============================================================
set PY=C:\Users\yi\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -u "%~dp0dd373_local_collect.py" --push --gap 1.5 >> "%~dp0logs\collect_log.txt" 2>&1
exit /b %ERRORLEVEL%
