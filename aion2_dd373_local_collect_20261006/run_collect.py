# -*- coding: utf-8 -*-
"""静默启动 DD373 本机采集 —— AION2 + MSCW 冒险岛（供 Windows 计划任务调用，无控制台窗口）。

为什么需要它：计划任务直接用 pythonw.exe 跑采集脚本时**没有控制台**，
print 全丢；这个启动器把 stdout/stderr 重定向到 logs/collect_log.txt，
再以 __main__ 方式运行同目录的 dd373_local_collect.py --push。

⚠ 2026-10-15（方案 A）：代抓范围必须覆盖服务器采集目标里的**每一个游戏**
（`金币.进货成本.游戏列表 = [AION2, MapleStory Classic World]`）——
服务器的「优先本机推送」是整轮跳过自抓，只推 AION2 会让 MSCW 成本被顺带冻结。
采集脚本默认已按 GAMES_DEFAULT = (MSCW, AION2) 两个游戏各抓一轮、各推一次，
本启动器无需再传 --only-game。
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
_KEY = r"D:\workbuddy文件目录\服务器\fs_admin_20261016_ed25519"
_HOST = "root@47.85.224.112"
# ⚠ 2026-10-07：本脚本由计划任务用 pythonw.exe 启动（无控制台），
#   此时 spawn 控制台程序 ssh.exe 若不指定 CREATE_NO_WINDOW，
#   Windows 会给它新开一个控制台 ⇒ Win11 交给 Windows Terminal ⇒ **弹黑框**。
#   循环 2 次（core_dd373_cost.py + config.json）⇒ 一次弹 2 个，正是老板看到的现象。
_NO_WIN = 0x08000000 if os.name == "nt" else 0
for _name in ("core_dd373_cost.py", "config.json"):
    try:
        _r = subprocess.run(
            ["ssh", "-i", _KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             _HOST, "cat /opt/d4follow/%s" % _name],
            capture_output=True, timeout=40, creationflags=_NO_WIN)
        if _r.returncode == 0 and len(_r.stdout) > 1000:
            with open(os.path.join(HERE, _name), "wb") as _f:
                _f.write(_r.stdout)
            print("[sync] %s 已同步（%d 字节）" % (_name, len(_r.stdout)))
        else:
            _err = (_r.stderr or b"").decode("utf-8", "ignore").strip()[-200:]
            print("[sync] %s 同步失败(用本地副本)：%s" % (_name, _err))
    except Exception as _e:                               # noqa: BLE001
        print("[sync] %s 同步异常(用本地副本)：%r" % (_name, _e))

sys.argv = ["dd373_local_collect.py", "--push", "--gap", "2.5"]
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
