# -*- coding: utf-8 -*-
"""端到端冒烟：真起 hub，走完「建任务 → 采集回传 → 停下等人放行 → 写入」。

为什么要有这个脚本
------------------
`test_shelf_tool_offline.py` 只锁**纯函数**（闸门/命令拼装/结论映射）。
但"接线对不对"——`/result` 分支有没有真的调 `WB.start`、线程有没有把结果
写回 `tasks.result.write_back`、`/writeback/approve` 有没有真的只写勾选的那几张、
网页读到的是不是一个可渲染的结构——那些用静态文本断言是测不出来的
（改个缩进就能骗过）。

所以这里**真起服务、真发 HTTP、真等子进程**，唯一被替换的是最外层那个
写卡脚本（换成一个不碰网络的假脚本）。跑完自动清理，不留残留。

本轮新增覆盖（相对 v1）
----------------------
* ① 人工确认闸门：采集回传后必须停在 `awaiting_review`，
  **放行前磁盘上不能出现写卡产物**（这是"闸门是真的"的唯一硬证据）；
* ② 只写勾选的那几张：放行 1 张 → 报告里就只能有 1 张；
* ③ 幂等：连点两次「放行」只跑一次；
* ④ 越界拒绝：放行名单里塞快照外的卡 → 拒绝，不写；
* ⑤ 取消：待审态可取消；已在跑则不可取消；
* ⑥ 关掉闸门时回到旧的自动行为（不能因为加了闸门就把老路径弄坏）；
* ⑦ `/api/coins-rate`：没配置时**必须**快速失败且绝不起进程。

⚠️ 刻意不做成 `test_*.py`：它会起进程，而 pr_fast 的隔离门禁把
   `subprocess.Popen` 换成了抛断言的桩，放进去必红。

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
PORT_A = int(os.environ.get("MLB_SMOKE_PORT_A", "18897"))
PORT_B = int(os.environ.get("MLB_SMOKE_PORT_B", "18898"))

OK, BAD = [], []


def check(name, cond, extra=""):
    (OK if cond else BAD).append(name)
    print("  [%s] %s%s" % ("OK" if cond else "XX", name,
                           ("  — " + str(extra)) if extra else ""))


class Hub:
    """一个隔离部署目录 + 一个真跑的 hub 进程。"""

    def __init__(self, tmp, port, wb_extra):
        self.port = port
        self.base = "http://127.0.0.1:%d" % port
        self.srv = tmp / ("server_%d" % port)
        self.web = tmp / ("web_%d" % port)
        (self.srv / "data").mkdir(parents=True)
        self.web.mkdir()
        for f in ("mlb_server.py", "mlb_writeback.py", "mlb_coins_rate.py"):
            shutil.copyfile(SERVER_DIR / f, self.srv / f)
        shutil.copyfile(TOOL / "web" / "index.html", self.web / "index.html")

        self.fake = tmp / "fake_write_cards.py"
        self.fake.write_text(FAKE_SCRIPT, encoding="utf-8")
        self.cred = tmp / "_cred.json"
        self.cred.write_text('{"P2PAH_USERNAME":"x","P2PAH_PASSWORD":"y"}',
                             encoding="utf-8")

        wb = {"enabled": True, "dry_run": True, "python": sys.executable,
              "script": str(self.fake), "cred": str(self.cred),
              "archive_dir": str(tmp / ("arch_%d" % port)),
              "confirm": "mlb26-players", "timeout": 60}
        wb.update(wb_extra)
        self.cfg = self.srv / "server_config.json"
        self.cfg.write_text(json.dumps({
            "markup": "1.1", "floor": "0.50", "interval": 120,
            "writeback": wb,
        }, ensure_ascii=False), encoding="utf-8")
        self.workdir = self.srv / "data" / "writeback"
        self.proc = None

    # ---- HTTP ----
    def req(self, path, method="GET", body=None, timeout=20):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json",
                     "X-Remote-User": "smoke"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(self.srv / "mlb_server.py"),
             "--port", str(self.port), "--root", str(self.web),
             "--config", str(self.cfg), "--no-auth"],
            cwd=str(self.srv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                return self.req("/api/health", timeout=3)
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("hub 起不来（port %d）" % self.port)

    def stop(self):
        if not self.proc:
            return
        self.proc.terminate()
        try:
            out = self.proc.communicate(timeout=10)[0] or b""
        except Exception:
            self.proc.kill()
            out = b""
        log = out.decode("utf-8", "replace")
        if "Traceback" in log:
            print("\n--- hub 输出（含 Traceback）---")
            print("\n".join(log.splitlines()[-25:]))

    # ---- 业务 ----
    def make_task(self, write_back=True, rate="2.65", batch="9-22-26"):
        return self.req("/api/tasks", "POST", {
            "kind": "collect", "rate": rate, "batch": batch,
            "interval": 120, "write_back": write_back})["id"]

    def claim(self, agent="smoke"):
        return self.req("/api/claim", "POST", {"agent": agent})["task"]

    def post_result(self, tid, cards):
        return self.req("/api/tasks/%s/result" % tid, "POST", {
            "status": "done", "agent": "smoke",
            "result": {"batch": "https://x/26/updates/9-22-26", "rate": "2.65",
                       "parsed": len(cards), "eligible": len(cards),
                       "added": len(cards), "duplicates": 0, "cards": cards}})

    def wb(self, tid):
        t = self.req("/api/tasks/" + tid)
        return (t.get("result") or {}).get("write_back") or {}

    def wait_wb(self, tid, done, timeout=60):
        """等到 write_back.status 满足 done(status) 为止。"""
        wbv = {}
        for _ in range(int(timeout / 0.4)):
            wbv = self.wb(tid)
            if wbv and done(wbv.get("status")):
                return wbv
            time.sleep(0.4)
        return wbv

    def out_file(self, tid):
        return self.workdir / ("%s.writeback.json" % tid)

    def pending_file(self, tid):
        return self.workdir / ("%s.pending.json" % tid)


FAKE_SCRIPT = '''# -*- coding: utf-8 -*-
"""假写卡脚本：不碰网络，只回吐一份可控报告。"""
import argparse, json, os, sys
ap = argparse.ArgumentParser()
ap.add_argument("--result"); ap.add_argument("--cred"); ap.add_argument("--out")
ap.add_argument("--archive"); ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--apply", action="store_true"); ap.add_argument("--confirm")
a = ap.parse_args()
cards = json.load(open(a.result, encoding="utf-8")).get("cards") or []
assert a.cred and os.path.isfile(a.cred), "凭据文件必须存在"
if a.apply:
    assert a.confirm == "mlb26-players", "口令不对"
rep = []
for i, c in enumerate(cards):
    rep.append({"title": c.get("product_name"), "hash": c.get("hash"),
                "verdict": "dry-run" if a.dry_run else "ok",
                "mid": 9000000 + i, "icon_readback": 7000 + i, "products": 48})
json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
print("[fake] %d cards dry_run=%s apply=%s" % (len(cards), a.dry_run, a.apply))
'''


def cards_two():
    return [
        {"name": "Dennis Eckersley", "ovr": "99", "team": "Athletics",
         "position": "CP", "series": "Awards", "hash": "a" * 32,
         "product_name": "Dennis Eckersley/99/CP/Athletics/Awards",
         "sale_price": "1.49", "include": True},
        {"name": "Andy Pettitte", "ovr": "99", "team": "Yankees",
         "position": "SP", "series": "Awards", "hash": "b" * 32,
         "product_name": "Andy Pettitte/99/SP/Yankees/Awards",
         "sale_price": "1.14", "include": True},
    ]


A, B = "Dennis Eckersley/99/CP/Athletics/Awards", "Andy Pettitte/99/SP/Yankees/Awards"


# =====================================================================
#  A 段：闸门开启（require_approval = True）—— 这是本轮的主戏
# =====================================================================
def phase_a(tmp):
    hub = Hub(tmp, PORT_A, {"require_approval": True})
    print("=" * 68)
    print("A① 起 hub（闸门开启，%s）" % hub.base)
    h = hub.start()
    try:
        wb = h.get("writeback") or {}
        check("health 有 writeback 段", bool(wb), wb)
        check("enabled=True / dry_run=True",
              wb.get("enabled") is True and wb.get("dry_run") is True)
        check("health 暴露 require_approval=True",
              wb.get("require_approval") is True)
        check("health 不回具体路径",
              "/" not in json.dumps(wb) and "\\\\" not in json.dumps(wb), wb)

        print("A② /api/coins-rate 未配置 → 快速失败且不起进程")
        cr = hub.req("/api/coins-rate")
        check("coins-rate 返回 ok=False（未配置）",
              cr.get("ok") is False, cr.get("step") or cr.get("error"))
        check("coins-rate 未配置时不带 rate",
              "rate_usd_per_100k" not in cr)
        check("health 暴露 coins_rate 段（仅布尔）",
              isinstance(h.get("coins_rate"), dict)
              and "enabled" in (h.get("coins_rate") or {}),
              h.get("coins_rate"))

        print("A③ 建任务 → 领任务 → 回传采集结果")
        tid = hub.make_task(write_back=True)
        check("拿到任务 id", bool(tid), tid)
        claimed = hub.claim()
        check("领到的就是刚建的任务", claimed and claimed["id"] == tid)
        check("payload.write_back 落库了",
              (claimed.get("payload") or {}).get("write_back") is True)
        r = hub.post_result(tid, cards_two())
        check("回传响应带 writeback 即时状态", bool(r.get("writeback")),
              r.get("writeback"))
        check("即时状态 = awaiting_review",
              (r.get("writeback") or {}).get("status") == "awaiting_review",
              (r.get("writeback") or {}).get("status"))

        print("A④ 闸门必须真的停机：等 4 秒，磁盘上不许有写卡产物")
        time.sleep(4)
        st = hub.wb(tid)
        check("状态仍是 awaiting_review（没被谁偷偷放行）",
              st.get("status") == "awaiting_review", st.get("status"))
        check("★ 写卡产物不存在（闸门是真的）",
              not hub.out_file(tid).exists(), str(hub.out_file(tid)))
        check("待审快照已落盘", hub.pending_file(tid).is_file())
        check("待审态带回 preview 与待写张数",
              st.get("cards_in") == 2 and len(st.get("pending") or []) == 2,
              (st.get("cards_in"), len(st.get("pending") or [])))
        check("待审态带快照 sha256", bool(st.get("sha256")))
        check("待审态里没有 report（还没跑）", not st.get("report"))

        print("A⑤ 放行**名单外的卡** → 必须拒绝")
        bad = hub.req("/api/tasks/%s/writeback/approve" % tid, "POST",
                      {"names": ["Ghost Player/99/SP/Nowhere/Awards"]})
        check("越界放行被拒", bad.get("status") == "noop", bad)
        check("拒了就不许有产物", not hub.out_file(tid).exists())
        check("状态仍是 awaiting_review",
              hub.wb(tid).get("status") == "awaiting_review")

        print("A⑥ 空名单 → 必须拒绝")
        empty = hub.req("/api/tasks/%s/writeback/approve" % tid, "POST",
                        {"names": []})
        check("空名单被拒", empty.get("status") == "noop", empty)

        print("A⑦ 放行**只勾 1 张** → 只写那 1 张")
        ap = hub.req("/api/tasks/%s/writeback/approve" % tid, "POST",
                     {"names": [A]})
        check("放行被接受（running）", ap.get("status") == "running", ap)
        fin = hub.wait_wb(tid, lambda s: s and s != "running")
        check("上架跑完（dry_run）", fin.get("status") == "dry_run",
              fin.get("status"))
        rep = fin.get("report") or []
        check("★ 只写了勾选的那 1 张", len(rep) == 1, len(rep))
        check("★ 写的正是勾选的那张",
              bool(rep) and rep[0].get("title") == A, rep and rep[0])
        check("留痕：approved_by", bool(fin.get("approved_by")),
              fin.get("approved_by"))
        check("留痕：approved_cards 计数 = 1", fin.get("approved_cards") == 1,
              fin.get("approved_cards"))
        check("★ 留痕：approved_names 记下放行了哪一张",
              fin.get("approved_names") == [A], fin.get("approved_names"))
        check("留痕：sha256 与快照一致",
              bool(fin.get("sha256")) and fin.get("sha256") == st.get("sha256"))
        check("★ 留痕没有篡改运行结论（状态仍是 dry_run 不是别的）",
              fin.get("status") == "dry_run")

        print("A⑧ 幂等：对同一任务再点一次「放行」")
        again = hub.req("/api/tasks/%s/writeback/approve" % tid, "POST",
                        {"names": [B]})
        check("二次放行 → noop", again.get("status") == "noop", again)
        time.sleep(2)
        rep2 = (hub.wb(tid).get("report") or [])
        check("报告仍是 1 张（没被第二次改写）", len(rep2) == 1, len(rep2))

        print("A⑨ 取消：待审态可取消 / 已在跑不可取消")
        tid2 = hub.make_task(write_back=True)
        hub.claim()
        hub.post_result(tid2, cards_two())
        hub.wait_wb(tid2, lambda s: s == "awaiting_review", timeout=20)
        cx = hub.req("/api/tasks/%s/writeback/cancel" % tid2, "POST",
                     {"reason": "smoke: 人工核对后决定不写"})
        check("待审态取消成功", cx.get("status") == "cancelled", cx)
        st2 = hub.wb(tid2)
        check("取消后没有产物", not hub.out_file(tid2).exists())
        check("取消留痕 cancelled_by", bool(st2.get("cancelled_by")), st2.get("cancelled_by"))
        check("取消后状态 = cancelled", st2.get("status") == "cancelled", st2.get("status"))

        # 已在跑 → 不可取消
        tid3 = hub.make_task(write_back=True)
        hub.claim()
        hub.post_result(tid3, cards_two())
        hub.wait_wb(tid3, lambda s: s == "awaiting_review", timeout=20)
        hub.req("/api/tasks/%s/writeback/approve" % tid3, "POST", {"names": None})
        running = hub.wb(tid3)
        cx3 = hub.req("/api/tasks/%s/writeback/cancel" % tid3, "POST", {})
        if running.get("status") == "running":
            check("跑动中取消 → noop", cx3.get("status") == "noop", cx3)
        else:
            check("（假脚本太快，跑动中取消这条跳过）", True)
        hub.wait_wb(tid3, lambda s: s and s != "running")

        print("A⑩ 未勾选「走上架」的任务不得触发")
        tid4 = hub.make_task(write_back=False)
        hub.claim()
        r4 = hub.post_result(tid4, cards_two())
        check("未勾选 → skipped",
              (r4.get("writeback") or {}).get("status") == "skipped",
              r4.get("writeback"))

        print("A⑪ 网页能渲染待审态所需字段")
        t = hub.req("/api/tasks/" + tid)
        wbv = (t.get("result") or {}).get("write_back") or {}
        check("result.write_back 存在", "write_back" in (t.get("result") or {}))
        check("write_back 三件套齐全",
              all(k in wbv for k in ("status", "counts", "report")))
        idx = (TOOL / "web" / "index.html").read_text(encoding="utf-8")
        for frag, label in (("awaiting_review", "状态词"), ("wbSelBox", "勾选框渲染"),
                            ("wbAck", "已核对复选框"), ("wbGo", "放行按钮"),
                            ("approveWriteback", "放行调用"),
                            ("/writeback/approve", "放行端点"),
                            ("去确认上架", "历史跳转"),
                            ("refreshCoinsRate", "取价调用")):
            check("index.html 含 %s" % label, frag in idx)
    finally:
        hub.stop()


# =====================================================================
#  B 段：闸门关闭 —— 老路径不能因为加闸门而坏掉
# =====================================================================
def phase_b(tmp):
    hub = Hub(tmp, PORT_B, {"require_approval": False})
    print("=" * 68)
    print("B① 起 hub（闸门关闭，%s）" % hub.base)
    h = hub.start()
    try:
        wb = h.get("writeback") or {}
        check("health 反映 require_approval=False",
              wb.get("require_approval") is False, wb.get("require_approval"))

        print("B② 回传后**自动**上架（旧行为）")
        tid = hub.make_task(write_back=True)
        hub.claim()
        r = hub.post_result(tid, cards_two())
        check("即时状态 = running（不再停下等人）",
              (r.get("writeback") or {}).get("status") == "running",
              (r.get("writeback") or {}).get("status"))
        fin = hub.wait_wb(tid, lambda s: s and s != "running")
        check("自动跑完 → dry_run", fin.get("status") == "dry_run",
              fin.get("status"))
        check("报告含 2 张卡", len(fin.get("report") or []) == 2,
              len(fin.get("report") or []))
        check("统计计数正确", (fin.get("counts") or {}).get("dry") == 2,
              fin.get("counts"))
        check("★ 关闸门时不留待审快照", not hub.pending_file(tid).exists())

        print("B③ 关闸门时 /writeback/approve 应无事可做")
        ap = hub.req("/api/tasks/%s/writeback/approve" % tid, "POST",
                     {"names": [A]})
        check("关闸门 → approve 返回 noop", ap.get("status") == "noop", ap)
    finally:
        hub.stop()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="_hub_smoke_"))
    try:
        phase_a(tmp)
        phase_b(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 68)
    print("通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    for b in BAD:
        print("  XX " + b)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
