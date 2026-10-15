@echo off
chcp 65001 >nul
title 销售数据看板 - Aion 2
cd /d "%~dp0"

set "PY=C:\Users\yi\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   销售数据看板 (Aion 2) - 本地服务
echo   地址：http://127.0.0.1:8899/
echo   关闭本窗口即停止服务
echo ================================================
echo.
echo [提示] 只想看数据、不想起服务？直接双击：
echo        销售数据看板_AION2_离线版.html
echo.

"%PY%" start.py %*
echo.
echo 服务已结束。
pause
