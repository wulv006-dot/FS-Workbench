# -*- coding: utf-8 -*-
"""静默启动 AION2 DD373 本机采集（供 Windows 计划任务调用，无控制台窗口）。

为什么需要它：计划任务直接用 pythonw.exe 跑采集脚本时**没有控制台**，
print 全丢；这个启动器把 stdout/stderr 重定向到 logs/collect_log.txt，
再以 __main__ 方式运行同目录的 dd373_local_collect.py --push。
"""
import datetime
import os
import runpy
import subprocess
import sys
import traceback

# 计划任务环境没有完整用户 PATH：把系统自带 OpenSSH 加进来，
# 否则采集脚本里的 scp / ssh（推送成本用）会找不到可执行文件。
os.environ["PATH"] = r"C:\Windows\System32\OpenSSH;" + os.environ.get("PATH", "")

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, "logs")
os.makedirs(LOGDIR, exist_ok=True)
_log = open(os.path.join(LOGDIR, "collect_log.txt"), "a", encoding="utf-8", buffering=1)
sys.stdout = _log
sys.stderr = _log

print("\n===== %s 本轮开始 =====" % datetime.datetime.now().isoformat(timespec="seconds"))

# 每轮先从服务器同步最新解析代码 + 服务区配置（保证口径与线上一致）；
# 失败就用本目录已有副本，绝不因为同步失败而不采集。
_KEY = r"D:\共享资源\服务器\No1.pem"
_HOST = "root@47.85.224.112"
for _name in ("core_dd373_cost.py", "config.json"):
    try:
        _r = subprocess.run(
            ["ssh", "-i", _KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             _HOST, "cat /opt/d4follow/%s" % _name],
            capture_output=True, timeout=40)
        if _r.returncode == 0 and len(_r.stdout) > 1000:
            with open(os.path.join(HERE, _name), "wb") as _f:
                _f.write(_r.stdout)
            print("[sync] %s 已同步（%d 字节）" % (_name, len(_r.stdout)))
        else:
            _err = (_r.stderr or b"").decode("utf-8", "ignore").strip()[-200:]
            print("[sync] %s 同步失败(用本地副本)：%s" % (_name, _err))
    except Exception as _e:                               # noqa: BLE001
        print("[sync] %s 同步异常(用本地副本)：%r" % (_name, _e))

sys.argv = ["dd373_local_collect.py", "--push", "--gap", "1.5"]
try:
    runpy.run_path(os.path.join(HERE, "dd373_local_collect.py"), run_name="__main__")
    print("===== 本轮结束：正常 =====")
except SystemExit as e:
    print("===== 本轮结束：SystemExit(%s) =====" % e)
except Exception:
    traceback.print_exc(file=_log)
    print("===== 本轮结束：异常 =====")
finally:
    try:
        _log.close()
    except Exception:
        pass
