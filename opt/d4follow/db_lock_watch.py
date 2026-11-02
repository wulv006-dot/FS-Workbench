#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG 库锁看门狗（2026-10-26）

为什么要有它
------------
`pricing_monitor_read_failed:OperationalError` 暴露两件事：
  ① 读者被写锁挡住 —— 已通过切 WAL 解决（读者读快照，不再等写者）。
  ② 但**写者之间**仍然互斥：00:07:21~00:12:02 有东西把写锁持了将近 5 分钟，
     期间 gunicorn 的 /api/* 全报 database is locked、srv_exec 主循环也是。
     WAL 治不了这一条，必须先查出「谁持锁」。

做法
----
只读 + 极短写探测，不写业务数据：
  · 每 5 秒用 `BEGIN IMMEDIATE`（timeout=0.2s）试一下写锁，立刻 rollback；
    失败即表示「此刻有别的写事务持有 RESERVED/EXCLUSIVE」。
  · 一旦发现，按 0.5 秒粒度持续探测直到拿到锁，得出**持锁时长**。
  · 持锁 >3 秒就在日志里留一条，并扫描 /proc 找出**打开该库 / -shm / -wal 的进程**，
    记录 pid + 命令行（这就是「持锁者是谁」）。
  · 状态写进 data/db_lock_state.json，rpg_guard 读它决定要不要告警。

日志：logs/db_lock_watch.log（只在下结论时写，不刷屏）
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import datetime

DB = "/opt/d4follow/data/iggm_follow.db"
STATE = "/opt/d4follow/data/db_lock_state.json"
LOG = "/opt/d4follow/logs/db_lock_watch.log"
TICK = 2.0            # 常态探测间隔（越小越不容易漏掉短窗口）
REPORT_S = 3.0        # 超过这么久才记录


def _now():
    return datetime.datetime.now()


def _ts():
    return _now().isoformat(timespec="seconds")


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (_now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def _try_write_lock(timeout=0.2):
    """返回 (是否拿到, 耗时)。拿到就立刻 rollback，不写任何数据。"""
    t = time.time()
    try:
        c = sqlite3.connect(DB, timeout=timeout)
        c.execute("pragma busy_timeout=%d" % int(timeout * 1000))
        c.execute("begin immediate")
        c.rollback()
        c.close()
        return True, time.time() - t
    except sqlite3.OperationalError:
        return False, time.time() - t
    except Exception:
        return True, time.time() - t          # 打不开不算持锁


def _holders():
    """谁打开了这个库（含 -shm / -wal）。返回 [(pid, cmd)]。"""
    targets = {os.path.realpath(DB)}
    for suf in ("-shm", "-wal", "-journal"):
        if os.path.exists(DB + suf):
            targets.add(os.path.realpath(DB + suf))
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fdd = "/proc/%s/fd" % pid
        try:
            for fd in os.listdir(fdd):
                try:
                    tgt = os.readlink(os.path.join(fdd, fd))
                except OSError:
                    continue
                if tgt in targets:
                    try:
                        with open("/proc/%s/cmdline" % pid, "rb") as f:
                            cmd = f.read().replace(b"\x00", b" ").decode("utf-8", "replace")
                        # 压成单行：日志按行读，命令行里可能带换行（python -c 多行脚本）
                        cmd = " ".join(cmd.split())[:200]
                    except OSError:
                        cmd = "?"
                    out[pid] = cmd
                    break
        except OSError:
            continue
    return sorted(((p, c) for p, c in out.items()), key=lambda x: x[0])


def main():
    ok, _dt = _try_write_lock()
    if ok:
        time.sleep(TICK)
    # 常态：等一次锁占用
    while True:
        ok, _ = _try_write_lock()
        if ok:
            time.sleep(TICK)
            continue
        # 进入持锁期
        t0 = time.time()
        hs_during = []
        while True:
            ok, _ = _try_write_lock(0.3)
            if ok:
                break
            if not hs_during and time.time() - t0 >= 1.0:
                # 关键：在**争用期间**抓一次打开该库的进程。
                # 只在事后抓会漏掉短命进程（自测 4.82 秒那次就抓到空列表）。
                hs_during = _holders()
            time.sleep(0.5)
            if time.time() - t0 > 3600:
                break
        held = time.time() - t0
        hs = hs_during or _holders()
        rec = {"ts": _ts(), "held_s": round(held, 2), "holders": hs}
        try:
            with open(STATE + ".tmp", "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(STATE + ".tmp", STATE)
        except OSError:
            pass
        if held >= REPORT_S:
            _log("写锁被占用 %.2fs ｜ 打开该库的进程：%s"
                 % (held, "；".join("%s=%s" % (p, c[:110]) for p, c in hs) or "无（可能已退出）"))
        time.sleep(TICK)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
