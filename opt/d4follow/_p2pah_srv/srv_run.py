# -*- coding: utf-8 -*-
"""服务器执行器 · 容器内执行入口（在 p2pah-srv:1 里跑）

作用
----
把「本机执行器」那套真实业务逻辑原样搬到服务器容器里执行：

    python /srv/srv_run.py write     --plan /srv/_jobs/Jxxx.json --confirm \
           --config /srv/_cfg/config.json --profile /srv/_srv_profile
    python /srv/srv_run.py writegold --plan /srv/_jobs/Jxxx.json --confirm ...

设计原则（与 p2pah_srv_trial.py 一致，这是「生产版」）
------------------------------------------------------
1. **一行都不改业务逻辑**：只把 p2pah_local.Session 换成容器版 SrvSession，
   然后直接调 p2pah_local.main()。所以 p2pah_local.py 以后升级（复核、推送、
   清缓存、金币两步）服务器侧**自动跟着变**，不存在两份逻辑跑偏。
2. 容器差异只有三处（全部集中在 SrvSession）：
     · 去掉 channel="msedge" —— 容器里只有 playwright 自带 chromium，没有 Edge；
     · headless=True —— 容器无 X；
     · 补 --no-sandbox / --disable-dev-shm-usage / --disable-gpu / --no-zygote
       （容器内以 root 跑 chromium 必须给）。
3. 不在这里做任何「安全绕行」：要不要清缓存、要不要推送，依旧由工单里的
   clearcache 字段 + config 决定，与在本机执行时完全同一套判据。

⚠ 单实例：同一个 profile 目录不能被两个容器同时开（chromium profile 会锁冲突），
  宿主侧的 srv_exec.py 已保证串行执行。
"""
import os
import json
import sys
import time

# 时区：基础镜像（jammy）里没装 tzdata，`TZ=Asia/Shanghai` 不起作用，
# 日志会写成 UTC（差 8 小时，排障时会误判）。用 POSIX 时区串钉死 UTC+8，
# 这个格式由 glibc 直接解析、不依赖 tzdata。
os.environ["TZ"] = "CST-8"
try:
    time.tzset()
except Exception:
    pass

sys.path.insert(0, "/srv")

import p2pah_local as P  # noqa: E402



EXECUTION = {"job_id": os.environ.get("FS_RPG_JOB_ID"), "write_attempts": 0, "finished": False}


def save_execution():
    path = os.environ.get("FS_RPG_EXECUTION_RECEIPT")
    if not path:
        raise RuntimeError("execution_receipt_required")
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(EXECUTION, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def before_write():
    EXECUTION["write_attempts"] += 1
    save_execution()


def run_job():
    path = os.environ.get("FS_RPG_EXECUTION_RECEIPT")
    if not path and (len(sys.argv) < 2 or sys.argv[1] not in ("write", "writegold")):
        return P.main()
    if not path or not EXECUTION["job_id"]:
        raise RuntimeError("execution_identity_required")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as stream:
            previous = json.load(stream)
        if previous.get("job_id") != EXECUTION["job_id"] or previous.get("write_attempts", 0):
            raise RuntimeError("reconcile_original_execution_before_retry")
    save_execution()
    try:
        return P.main()
    finally:
        EXECUTION["finished"] = True
        save_execution()


class SrvSession(P.Session):
    """容器版会话：只改「浏览器怎么起」，业务逻辑一行没改。"""

    def __init__(self, profile, show=False):
        self._p = P.sync_playwright().start()
        self.ctx = self._p.chromium.launch_persistent_context(
            profile,
            headless=not show,
            viewport={"width": 1400, "height": 950},
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--no-zygote"])
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self._inject_saved_cookies()
        self.auto_login = bool(P.AUTO_LOGIN[0]) and (P.autologin is not None)
        try:
            _a = P.autologin.accounts()["order"]
            self.user = _a.get("username") or ""
            self.pw = _a.get("password") or ""
        except Exception:
            self.user = self.pw = ""


    def write_rows(self, rows):
        before_write()
        return super().write_rows(rows)

    def set_gold_cost(self, row_id, value):
        before_write()
        return super().set_gold_cost(row_id, value)


P.Session = SrvSession

if __name__ == "__main__":
    sys.exit(run_job())
