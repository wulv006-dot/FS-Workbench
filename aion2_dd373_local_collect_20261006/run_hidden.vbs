' ============================================================
'  静默启动 AION2 DD373 本机采集（不弹黑窗口）
'  由 Windows 计划任务 AION2_DD373_LocalCollect 调用
' ============================================================
Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c cd /d ""D:\PlayRent\服务器\AION2_DD373抓取"" && run_collect_push.bat", 0, False
