# -*- coding: utf-8 -*-
"""线上真实链路验证（在服务器本机跑，走 127.0.0.1:8897，绕过 nginx 认证）。

为什么用「直接插 running 任务」而不是「建任务 + 领任务」
--------------------------------------------------------
线上此刻**有真实的执行器在轮询**。若建一个 pending 任务，它可能在
我领走之前先抢到，进而真的去 showdd 采集、并按当期价格**真的上架新卡** ——
那属于未经确认的生产写入。

所以这里直接插入一条 `status='running'` 的任务（执行器只领 pending，
不会碰它），再把**真实采集结果**（4 张已存在的卡）回传上去。
链路除"采集"这一步外**全是真的**：真 hub、真线程、真子进程、
真后台登录、真读写通道。跑完立刻删掉这条测试任务。

安全性：4 张卡都已存在且完整 → 写卡脚本会走幂等分支报 `skipped`，
**不产生任何写入**。
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8897"
DB = "/opt/mlb-online/data/mlb.db"
RESULT_SRC = "/opt/mlb-admin-write/evidence/_result.json"

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "XX", name,
                           ("  — " + str(extra)) if extra else ""))


def req(path, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                              headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    tid = "e2eselftest" + str(int(time.time()))[-6:]
    print("=" * 66)
    print("① 服务健康检查（含自动上架开关）")
    h = req("/api/health")
    wb = h.get("writeback") or {}
    print("   version =", h.get("version"), "| writeback =", wb)
    check("写卡开关已开", wb.get("enabled") is True)
    check("**线上模式：dry_run=False**", wb.get("dry_run") is False,
          "dry_run=%r" % wb.get("dry_run"))
    check("脚本与凭据就位", bool(wb.get("script_ok")) and bool(wb.get("cred_ok")))

    print("② 插入一条 running 测试任务（执行器不会抢）")
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    payload = {"kind": "collect", "rate": "2.65", "batch": "e2e-selftest",
               "interval": 120, "write_back": True}
    conn.execute("INSERT INTO tasks(id,created_at,submitter,kind,title,payload,status,agent)"
                 " VALUES(?,?,?,?,?,?,?,?)",
                 (tid, time.time(), "e2e-selftest", "collect",
                  "E2E 自检（勿理）", json.dumps(payload, ensure_ascii=False),
                  "running", "e2e-selftest"))
    conn.commit()
    conn.close()
    check("任务已插入", True, tid)

    try:
        print("③ 回传真实采集结果（4 张已存在的卡）")
        raw = json.loads(Path(RESULT_SRC).read_text("utf-8"))
        cards = [c for c in raw.get("cards", []) if c.get("include")]
        check("拿到 4 张真实卡", len(cards) == 4, [c["product_name"] for c in cards])
        r = req("/api/tasks/%s/result" % tid, "POST", {
            "status": "done", "agent": "e2e-selftest",
            "result": {"batch": "e2e-selftest", "rate": "2.65",
                       "parsed": len(cards), "eligible": len(cards),
                       "added": 0, "duplicates": len(cards), "cards": cards}})
        print("   即时状态 =", r.get("writeback"))

        print("④ 等自动上架跑完（真登录 + 真后台往返）")
        wbv, t0 = None, time.time()
        while time.time() - t0 < 300:
            t = req("/api/tasks/" + tid)
            wbv = (t.get("result") or {}).get("write_back")
            if wbv and wbv.get("status") not in ("running", None):
                break
            time.sleep(1.0)
        check("已出最终结论", wbv and wbv.get("status") != "running",
              wbv and wbv.get("status"))
        check("结论 = ok（4 张都幂等跳过，无写入）",
              wbv and wbv.get("status") == "ok", wbv and wbv.get("status"))
        check("dry_run 标记为 False（真的开了写入权限）",
              wbv and wbv.get("dry_run") is False)
        cnt = (wbv or {}).get("counts") or {}
        check("4 张全部 skipped", cnt.get("skipped") == 4, cnt)
        rep = (wbv or {}).get("report") or []
        check("报告 4 条", len(rep) == 4, len(rep))
        mids = [x.get("mid") for x in rep]
        check("带回真实 mid（不是伪造的）",
              all(isinstance(m, int) and m > 0 for m in mids), mids)
        print("\n  逐卡结论：")
        for x in rep:
            print("    %-52s %s  mid=%s 产品=%s"
                  % (x.get("title", "")[:50], x.get("verdict"),
                     x.get("mid"), x.get("products")))
        tail = (wbv or {}).get("log_tail") or []
        print("\n  脚本输出尾部：")
        for ln in tail[-8:]:
            print("    " + ln)
        check("脚本 stdout 被捕获（可排查）", len(tail) > 0)

        print("⑤ 存档 / 可还原")
        arc = Path((wbv or {}).get("archive_dir") or "/nonexistent")
        check("存档目录已就位（路径已下发到结果里）", bool(wbv.get("archive_dir")),
              arc)
        if arc.is_dir() and not list(arc.glob("*.before.json")):
            # 本次 4 张全部 skipped ⇒ 一句都没写 ⇒ 按设计**不该**有新基线。
            # 这是正确行为，不是缺陷 —— 基线只在"真要写之前"才落。
            print("    （本次无实际写入，故未产生新基线 —— 符合设计）")

        # 用写权限探针留下的基线做一次**只读**核对：证明基线内容有效、
        # 且线上当前值确实等于基线（也就是 --restore 回得去）。
        probe_arc = Path("/opt/mlb-admin-write/evidence/_archive_wprobe")
        bases = sorted(probe_arc.glob("*.before.json"))
        check("写权限探针留下的基线存在", len(bases) >= 4,
              [p.name for p in bases])
        if bases:
            sys.path.insert(0, "/opt/mlb-admin-write/src")
            from admin_api_client import AdminApiClient
            cred = json.loads(Path("/opt/mlb-admin-write/_cred.json").read_text("utf-8"))
            c = AdminApiClient(log=lambda *a: None)
            c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

            def flat(o, p=""):
                out = {}
                if isinstance(o, dict):
                    for k, v in o.items():
                        out.update(flat(v, ("%s.%s" % (p, k)) if p else str(k)))
                elif isinstance(o, list):
                    for i, v in enumerate(o):
                        out.update(flat(v, "%s[%d]" % (p, i)))
                else:
                    out[p] = o
                return out

            bad = []
            for b in bases:
                mid = int(b.name.split(".")[0])
                base = json.loads(b.read_text("utf-8"))
                cur = (c._json("GET", "/admin/goods.GoodsMould/edit",
                               params={"id": mid}).get("data") or {}).get("row") or {}
                fb, fc = flat(base), flat(cur)
                diff = [k for k in set(fb) | set(fc) if fb.get(k) != fc.get(k)]
                print("    mid=%-10s 基线字段 %3d 个，与线上差异 %d 个"
                      % (mid, len(fb), len(diff)))
                if diff:
                    bad.append((mid, diff[:5]))
            check("4 张卡的线上值 == 写入前基线（→ --restore 能原样回退）",
                  not bad, bad)
    finally:
        print("⑥ 清理测试任务")
        conn = sqlite3.connect(DB, timeout=20)
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        check("测试任务已删除", True, tid)

    print("=" * 66)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  XX " + b)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
