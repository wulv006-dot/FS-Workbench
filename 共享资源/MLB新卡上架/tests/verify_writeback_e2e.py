# -*- coding: utf-8 -*-
"""端到端冒烟：真起一个 hub，走完「建任务 → 采集回传 → 自动上架」。

为什么要有这个脚本
------------------
`test_shelf_tool_offline.py` 只锁**纯函数**（闸门/命令拼装/结论映射）。
但"接线对不对"——`/result` 分支有没有真的调 `WB.start`、线程有没有把结果
写回 `tasks.result.write_back`、网页读到的是不是一个可渲染的结构——那些
用静态文本断言是测不出来的（改个缩进就能骗过）。

所以这里**真起服务、真发 HTTP、真等子进程**，唯一被替换的是最外层那个
写卡脚本（换成一个不碰网络的假脚本）。跑完自动清理，不留残留。

⚠️ 刻意不做成 `test_*.py`：它会起进程，而 pr_fast 的隔离门禁
   把 `subprocess.Popen` 换成了抛断言的桩，放进去必红。

用法
----
    python 共享资源/MLB新卡上架/tests/verify_writeback_e2e.py
退出码 0 = 全通。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
SERVER_DIR = TOOL / "server"
PORT = int(os.environ.get("MLB_SMOKE_PORT", "18897"))
BASE = "http://127.0.0.1:%d" % PORT

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "XX", name,
                           ("  — " + str(extra)) if extra else ""))


def req(path, method="GET", body=None, timeout=20):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        "X-Remote-User": "smoke"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


FAKE_SCRIPT = '''# -*- coding: utf-8 -*-
"""假写卡脚本：不碰网络，只回吐一份可控报告。"""
import argparse, json, sys
ap = argparse.ArgumentParser()
ap.add_argument("--result"); ap.add_argument("--cred"); ap.add_argument("--out")
ap.add_argument("--archive"); ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--apply", action="store_true"); ap.add_argument("--confirm")
a = ap.parse_args()
cards = json.load(open(a.result, encoding="utf-8")).get("cards") or []
print("[fake] 收到 %d 张卡 dry_run=%s apply=%s" % (len(cards), a.dry_run, a.apply))
assert a.cred and __import__("os").path.isfile(a.cred), "凭据文件必须存在"
if a.apply:
    assert a.confirm == "mlb26-players", "口令不对"
rep = []
for i, c in enumerate(cards):
    rep.append({"title": c.get("product_name"), "hash": c.get("hash"),
                "verdict": "dry-run" if a.dry_run else "ok",
                "mid": 9000000 + i, "icon_readback": 7000 + i, "products": 48})
json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
print("[fake] 写了 %d 条报告" % len(rep))
'''


def main():
    tmp = Path(tempfile.mkdtemp(prefix="_hub_smoke_"))
    try:
        # ---- 搭一个隔离的部署目录（不污染仓库里的 server/data）----
        srv = tmp / "server"
        web = tmp / "web"
        (srv / "data").mkdir(parents=True)
        web.mkdir()
        for f in ("mlb_server.py", "mlb_writeback.py"):
            shutil.copyfile(SERVER_DIR / f, srv / f)
        shutil.copyfile(TOOL / "web" / "index.html", web / "index.html")

        fake = tmp / "fake_write_cards.py"
        fake.write_text(FAKE_SCRIPT, encoding="utf-8")
        cred = tmp / "_cred.json"
        cred.write_text('{"P2PAH_USERNAME":"x","P2PAH_PASSWORD":"y"}',
                        encoding="utf-8")

        cfg = srv / "server_config.json"
        cfg.write_text(json.dumps({
            "markup": "1.1", "floor": "0.50", "interval": 120,
            "writeback": {"enabled": True, "dry_run": True,
                          "python": sys.executable, "script": str(fake),
                          "cred": str(cred), "archive_dir": str(tmp / "arch"),
                          "confirm": "mlb26-players", "timeout": 60},
        }, ensure_ascii=False), encoding="utf-8")

        print("=" * 68)
        print("① 起一个真的 hub（%s）" % BASE)
        proc = subprocess.Popen(
            [sys.executable, str(srv / "mlb_server.py"), "--port", str(PORT),
             "--root", str(web), "--config", str(cfg), "--no-auth"],
            cwd=str(srv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(60):
                try:
                    h = req("/api/health", timeout=3)
                    break
                except Exception:
                    time.sleep(0.3)
            else:
                raise RuntimeError("hub 起不来")

            print("② /api/health 暴露自动上架开关（且不泄露路径）")
            wb = h.get("writeback") or {}
            check("health 有 writeback 段", bool(wb), wb)
            check("enabled=True", wb.get("enabled") is True)
            check("dry_run=True", wb.get("dry_run") is True)
            check("script_ok/cred_ok 都为真",
                  wb.get("script_ok") and wb.get("cred_ok"))
            check("health 不回具体路径",
                  "/" not in json.dumps(wb) and "\\\\" not in json.dumps(wb),
                  wb)

            print("③ 建任务（勾了自动上架）")
            tid = req("/api/tasks", "POST", {
                "kind": "collect", "rate": "2.65", "batch": "9-22-26",
                "interval": 120, "write_back": True})["id"]
            check("拿到任务 id", bool(tid), tid)

            print("④ 执行器领任务")
            claimed = req("/api/claim", "POST", {"agent": "smoke"})["task"]
            check("领到的就是刚建的任务", claimed and claimed["id"] == tid)
            check("payload.write_back 落库了",
                  (claimed.get("payload") or {}).get("write_back") is True)

            print("⑤ 回传采集结果（含 2 张卡）")
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
                "status": "done", "agent": "smoke",
                "result": {"batch": "https://x/26/updates/9-22-26", "rate": "2.65",
                           "parsed": 2, "eligible": 2, "added": 2, "duplicates": 0,
                           "cards": cards}})
            check("回传响应带 writeback 即时状态", bool(r.get("writeback")), r.get("writeback"))

            print("⑥ 等后台线程把上架结果写回任务记录")
            wbv, t = None, 0
            for _ in range(120):
                t = req("/api/tasks/" + tid)
                wbv = (t.get("result") or {}).get("write_back")
                if wbv and wbv.get("status") not in ("running", None):
                    break
                time.sleep(0.5)
            check("结果已回写（不再是 running）",
                  wbv and wbv.get("status") != "running", wbv and wbv.get("status"))
            check("dry_run 模式 → 结论 dry_run",
                  wbv and wbv.get("status") == "dry_run", wbv and wbv.get("status"))
            rep = (wbv or {}).get("report") or []
            check("报告含 2 张卡", len(rep) == 2, len(rep))
            check("每张卡带回 mid",
                  all(x.get("mid") for x in rep), [x.get("mid") for x in rep])
            check("统计计数正确", (wbv or {}).get("counts", {}).get("dry") == 2,
                  (wbv or {}).get("counts"))

            print("⑦ 没勾「自动上架」的任务不得触发")
            tid2 = req("/api/tasks", "POST", {
                "kind": "collect", "rate": "2.65", "write_back": False})["id"]
            req("/api/claim", "POST", {"agent": "smoke"})
            r2 = req("/api/tasks/%s/result" % tid2, "POST", {
                "status": "done", "agent": "smoke",
                "result": {"cards": cards, "eligible": 2}})
            check("未勾选 → 不触发",
                  (r2.get("writeback") or {}).get("status") == "skipped",
                  r2.get("writeback"))

            print("⑧ 状态落库形态可直接给网页渲染")
            check("result 里有 write_back 键", "write_back" in (t.get("result") or {}))
            check("write_back 有 status/counts/report 三件套",
                  all(k in ((t.get("result") or {}).get("write_back") or {})
                      for k in ("status", "counts", "report")))
        finally:
            proc.terminate()
            try:
                out = proc.communicate(timeout=10)[0] or b""
            except Exception:
                proc.kill()
                out = b""
            log = out.decode("utf-8", "replace")
            if any(k in log for k in ("Traceback", "Error", "error")):
                print("\n--- hub 输出（含错误关键字）---")
                print("\n".join(log.splitlines()[-25:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 68)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  XX " + b)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
