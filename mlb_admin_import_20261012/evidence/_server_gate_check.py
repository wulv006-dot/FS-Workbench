# -*- coding: utf-8 -*-
"""线上（生产 hub）验证:人工确认闸门 + 金币售价自动取价。

在 **47.85.224.112 本机**跑，走 `127.0.0.1:8897`，绕过 nginx 认证。

═══════════════════════════════════════════════════════════════════════
这一版和上一版（_server_e2e_check.py）的关键差别
═══════════════════════════════════════════════════════════════════════
上一版是「回传完就自动上架」；现在线上开了 `require_approval`，
所以**回传后必须停在 awaiting_review，不能有任何写卡产物**。
这个脚本要证明的就是这条 —— 而且**全程不做任何放行**，
即刻意不触发任何生产写入。

为什么不在这里做"放行→真的写进去"
----------------------------------
上线的是 `dry_run=False` 的生产配置。虽然用那 4 张已存在的卡做放行
在上一轮被证明是幂等 `skipped`（零写入），但**前提是那 4 张卡此刻仍然
完整存在**。只要有一张缺失，放行就变成真实生产写入 —— 这是不可接受的
不确定性。所以：
  · 本脚本：只验「停得住」（生产，零写入）
  · 放行→写入 的完整链路：在同一台服务器的 **Py3.9.18** 上用
    `verify_writeback_e2e.py`（独立临时 hub + 假写卡脚本）验证，
    用的是**同一批已部署字节**，不碰生产数据。

用法（在服务器上）:
    /opt/python39/bin/python3 _server_gate_check.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8897"
DB = "/opt/mlb-online/data/mlb.db"
WORKDIR = "/opt/mlb-online/data/writeback"
RATE_DIR = "/opt/mlb-online/data/pricing"

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "XX", name,
                           ("  — " + str(extra)) if extra else ""))


def req(path, method="GET", body=None, timeout=180):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    tid = "gateself" + str(int(time.time()))[-6:]
    pend = os.path.join(WORKDIR, "%s.pending.json" % tid)
    wout = os.path.join(WORKDIR, "%s.writeback.json" % tid)

    print("=" * 66)
    print("① 服务健康检查")
    h = req("/api/health")
    wb = h.get("writeback") or {}
    cr = h.get("coins_rate") or {}
    print("   version =", h.get("version"))
    print("   writeback =", wb)
    print("   coins_rate =", cr)
    check("服务版本 = 1.2", str(h.get("version")) == "1.2", h.get("version"))
    check("★ 线上已开启人工确认 require_approval=True",
          wb.get("require_approval") is True, wb.get("require_approval"))
    check("线上仍是 dry_run=False（真写入权限）", wb.get("dry_run") is False)
    check("写卡脚本与凭据就位",
          bool(wb.get("script_ok")) and bool(wb.get("cred_ok")))
    check("health 不泄露路径",
          "/" not in json.dumps(wb) and "/" not in json.dumps(cr))
    check("取价开关已开", cr.get("enabled") is True)
    check("取价脚本与订单后台凭据就位",
          bool(cr.get("script_ok")) and bool(cr.get("cred_ok")))
    check("取价 gid/area/multiplier 正确",
          cr.get("gid") == 922 and cr.get("multiplier") == 100.0,
          (cr.get("gid"), cr.get("area"), cr.get("multiplier")))

    print("② 插入一条 running 测试任务（执行器只领 pending，不会抢）")
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    payload = {"kind": "collect", "rate": "2.65", "batch": "gate-selftest",
               "interval": 120, "write_back": True}
    conn.execute("INSERT INTO tasks(id,created_at,submitter,kind,title,payload,"
                 "status,agent) VALUES(?,?,?,?,?,?,?,?)",
                 (tid, time.time(), "gate-selftest", "collect",
                  "闸门自检（勿理）", json.dumps(payload, ensure_ascii=False),
                  "running", "gate-selftest"))
    conn.commit()
    conn.close()
    check("任务已插入", True, tid)

    try:
        print("③ 回传采集结果 → 必须停在 awaiting_review")
        cards = [
            {"name": "Dennis Eckersley", "ovr": "99", "team": "Athletics",
             "position": "CP", "series": "Awards", "hash": "a" * 32,
             "product_name": "Dennis Eckersley/99/CP/Athletics/Awards",
             "sale_price": "1.49", "include": True},
            {"name": "Andy Pettitte", "ovr": "99", "team": "Yankees",
             "position": "SP", "series": "Awards", "hash": "b" * 32,
             "product_name": "Andy Pettitte/99/SP/Yankees/Awards",
             "sale_price": "1.14", "include": True},
        ]
        r = req("/api/tasks/%s/result" % tid, "POST", {
            "status": "done", "agent": "gate-selftest",
            "result": {"batch": "gate-selftest", "rate": "2.65",
                       "parsed": 2, "eligible": 2, "added": 0,
                       "duplicates": 2, "cards": cards}})
        st = r.get("writeback") or {}
        print("   即时状态 =", json.dumps(st, ensure_ascii=False)[:220])
        check("★ 回传后即时状态 = awaiting_review",
              st.get("status") == "awaiting_review", st.get("status"))
        check("带回待审清单（2 张）",
              len(st.get("pending") or []) == 2, len(st.get("pending") or []))
        check("带回快照 sha256", bool(st.get("sha256")))

        print("④ 等 10 秒：状态不许自己变，磁盘上不许有写卡产物")
        time.sleep(10)
        t = req("/api/tasks/" + tid)
        st = (t.get("result") or {}).get("write_back") or {}
        check("★ 10 秒后仍是 awaiting_review（没人自动放行）",
              st.get("status") == "awaiting_review", st.get("status"))
        check("★ 快照文件已落盘", os.path.isfile(pend), pend)
        check("★★ 写卡产物不存在（生产环境上闸门为真）",
              not os.path.isfile(wout), wout)
        check("待审态里没有 report", not st.get("report"))

        print("⑤ 放行名单里塞快照外的卡 → 必须拒绝")
        bad = req("/api/tasks/%s/writeback/approve" % tid, "POST",
                  {"names": ["Ghost Player/99/SP/Nowhere/Awards"]})
        check("越界放行被拒（noop）", bad.get("status") == "noop", bad)
        check("拒绝后仍无写卡产物", not os.path.isfile(wout))

        print("⑥ 空名单 → 必须拒绝")
        empty = req("/api/tasks/%s/writeback/approve" % tid, "POST",
                    {"names": []})
        check("空名单被拒（noop）", empty.get("status") == "noop", empty)
        check("拒绝后仍无写卡产物", not os.path.isfile(wout))

        print("⑦ 取消本次上架（生产零写入收尾）")
        cx = req("/api/tasks/%s/writeback/cancel" % tid, "POST",
                 {"reason": "上线自检：不写入生产"})
        check("取消成功", cx.get("status") == "cancelled", cx)
        t = req("/api/tasks/" + tid)
        st = (t.get("result") or {}).get("write_back") or {}
        check("状态 = cancelled", st.get("status") == "cancelled",
              st.get("status"))
        check("取消留痕 cancelled_by", bool(st.get("cancelled_by")),
              st.get("cancelled_by"))
        check("★ 全程零写卡产物", not os.path.isfile(wout))

        print("⑧ 金币售价自动取价（真登录订单后台 + 真过验证码）")
        t0 = time.time()
        try:
            p = req("/api/coins-rate?force=1", timeout=180)
        except urllib.error.HTTPError as e:
            p = {"ok": False, "http": e.code, "body": e.read()[:300]
                 .decode("utf-8", "replace")}
        dt = time.time() - t0
        print("   耗时 %.1fs" % dt)
        print("   返回 =", json.dumps(p, ensure_ascii=False)[:600])
        check("★ 取价成功 ok=True", p.get("ok") is True, p.get("error") or p.get("step"))
        check("b2c 是数字", isinstance(p.get("b2c"), (int, float)), p.get("b2c"))
        check("单位标注 = USD/1K", p.get("b2c_unit") == "USD/1K",
              p.get("b2c_unit"))
        check("multiplier = 100", p.get("multiplier") == 100.0,
              p.get("multiplier"))
        rate = p.get("rate_usd_per_100k")
        check("★ rate_usd_per_100k 与 b2c×100 一致",
              isinstance(rate, (int, float))
              and abs(rate - float(p.get("b2c", 0)) * 100.0) < 1e-6, rate)
        check("量级合理（0.5 ~ 50 USD/100K）",
              isinstance(rate, (int, float)) and 0.5 <= rate <= 50.0, rate)
        check("gid 命中 922", p.get("gid_matched") is True or
              p.get("gid") == 922, p.get("gid_matched"))
        check("取价落在 data/pricing（不是 files/ 下）",
              os.path.isdir(RATE_DIR), RATE_DIR)
        check("★ 取价失败也绝不影响主链路（服务仍健康）",
              req("/api/health").get("ok") is True)

        print("⑨ 缓存：不 force 时应直接给缓存结果")
        t1 = time.time()
        p2 = req("/api/coins-rate", timeout=180)
        dt2 = time.time() - t1
        print("   缓存命中耗时 %.2fs" % dt2)
        check("缓存命中明显更快（<1.5s）", dt2 < 1.5, dt2)
        check("缓存值仍 ok=True", p2.get("ok") is True)
    finally:
        print("⑩ 清理测试任务与快照")
        conn = sqlite3.connect(DB, timeout=20)
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        for f in (pend, wout, os.path.join(WORKDIR, "%s.result.json" % tid)):
            try:
                os.remove(f)
            except OSError:
                pass
        check("测试任务已删除", True, tid)
        check("测试残留文件已清理",
              not os.path.exists(pend) and not os.path.exists(wout))

    print("=" * 66)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  XX " + b)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
