# -*- coding: utf-8 -*-
"""MLB 自动上架桥：hub 采集结果 → p2pah 后台直写（把链路接成一条跑到底）。

═══════════════════════════════════════════════════════════════════════
它在整条链路里的位置
═══════════════════════════════════════════════════════════════════════
    网页提交任务 ──> 执行器(本机) 采集+定价+写 Excel ──回传──> hub(本服务)
                                                              │
                                                    ┌─────────┘
                                                    ▼
                            本模块：把 result.cards[] 交给直写脚本
                                                    │  子进程
                                                    ▼
                        /opt/mlb-admin-write/src/mlb_write_cards.py
                         ①上传卡图 ②建模型 ③回读 ④写icon/zh_title ⑤建产品

结果写回 `tasks.result.write_back`，网页即可看到每张卡的上架落点。

═══════════════════════════════════════════════════════════════════════
为什么用**子进程**而不是 import（三条硬理由）
═══════════════════════════════════════════════════════════════════════
1. **可超时 kill**：写卡要连外网、有 sleep(2)/(4)，一旦挂住，
   进程隔离后 hub 不受影响；import 进同进程就只能干等。
2. **依赖隔离**：直写脚本要 `ddddocr`（过验证码，峰值 RSS 实测 87MB），
   而 hub 跑在 systemd 内存限额下。分开后 hub 的依赖面完全不变。
3. **两边各自演进**：直写脚本有一套独立的离线回归（`mlb-admin` 分组），
   边界就是一个 CLI + 一个 JSON 文件 —— 两边都实跑验证过。

═══════════════════════════════════════════════════════════════════════
三道闸门（任一不满足就不触发）
═══════════════════════════════════════════════════════════════════════
  a. **任务级**：网页提交时勾了「自动上架」（payload.write_back）
  b. **服务级**：`server_config.json` 的 `writeback.enabled` 为 true
  c. **环境级**：直写脚本与后台凭据文件都存在

另外 `writeback.dry_run`（默认 true）**只读**：即便放行也只登录+回读，
不产生任何写入。要真正上线必须显式把它改成 false。

⚠️ 语义红线：`add` / `edit` / `shelves` 出现**未知结果**时绝不重试
（超时≠失败，重试可能建出重复模型）。本模块对任何异常一律只记录、
不重跑，`needs_review` 就是留给人工的信号。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

#: 生产写入必须带的口令（与直写脚本的闸门一致）
DEFAULT_CONFIRM = "mlb26-players"

#: 判为「需要人工介入」的逐卡结论前缀/取值。
#: 前三个是「结果未知，禁止重试」；其余是明确的失败或校验不符。
REVIEW_VERDICTS = (
    "add-unknown", "edit-unknown", "shelves-unknown",
    "add-failed", "edit-failed", "shelves-failed",
    "readback-missing", "mismatch", "exception",
)


def cfg(config):
    """从 server_config 取 `writeback` 段，缺失项给**安全默认值**。

    ⚠️ `enabled` 缺省为 False：配置写漏了宁可不上架，也不能误写线上。
    """
    wb = (config or {}).get("writeback") or {}
    return {
        "enabled": bool(wb.get("enabled", False)),
        "dry_run": bool(wb.get("dry_run", True)),
        "python": wb.get("python") or sys.executable,
        "script": wb.get("script") or "",
        "cred": wb.get("cred") or "",
        "archive_dir": wb.get("archive_dir") or "",
        "confirm": wb.get("confirm") or DEFAULT_CONFIRM,
        "timeout": int(wb.get("timeout") or 900),
    }


def gate(payload, wb):
    """三道闸门。返回 `(是否放行, 原因)`。纯函数 —— 离线用例锁死它。"""
    if not (payload or {}).get("write_back"):
        return False, "任务未勾选「自动上架」"
    if not wb.get("enabled"):
        return False, "服务未开启自动上架（server_config.writeback.enabled）"
    if not wb.get("script") or not os.path.isfile(wb["script"]):
        return False, "写卡脚本不存在：%s" % (wb.get("script") or "(未配置)")
    if not wb.get("cred") or not os.path.isfile(wb["cred"]):
        return False, "后台凭据不存在：%s" % (wb.get("cred") or "(未配置)")
    return True, "ok"


def build_cmd(wb, result_path, out_path, *, archive_dir=None):
    """构造直写脚本的命令行。

    `dry_run` 时不带 `--apply`：脚本在无 `--apply` 时根本不会走到写分支
    （闸门在它自己的 `main()` 里，先于读文件/连网）。
    """
    cmd = [wb["python"], wb["script"],
           "--result", result_path,
           "--cred", wb["cred"],
           "--out", out_path]
    arch = archive_dir or wb.get("archive_dir")
    if arch:
        cmd += ["--archive", arch]
    if wb.get("dry_run"):
        cmd.append("--dry-run")
    else:
        cmd += ["--apply", "--confirm", str(wb["confirm"])]
    return cmd


def summarize(report):
    """把逐卡报告压成结论 —— `needs_review` 就是**不许重试**的信号。"""
    if not isinstance(report, list):
        report = []
    counts = {"ok": 0, "skipped": 0, "dry": 0, "review": 0}
    for r in report:
        v = str((r or {}).get("verdict") or "")
        if v == "ok":
            counts["ok"] += 1
        elif v == "skipped":
            counts["skipped"] += 1
        elif v == "dry-run":
            counts["dry"] += 1
        else:
            counts["review"] += 1
    if counts["review"]:
        status = "needs_review"
    elif counts["dry"]:
        status = "dry_run"
    else:
        status = "ok"
    return {"status": status, "counts": counts, "cards": len(report)}


def run_once(*, tid, cards, wb, workdir, log=print):
    """同步跑一次上架。**永不抛异常** —— 一切失败都变成可入库的结果。"""
    os.makedirs(workdir, exist_ok=True)
    result_path = os.path.join(workdir, "%s.result.json" % tid)
    out_path = os.path.join(workdir, "%s.writeback.json" % tid)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"cards": cards or []}, f, ensure_ascii=False)

    cmd = build_cmd(wb, result_path, out_path)
    started = time.time()
    out = {
        "dry_run": bool(wb.get("dry_run")),
        "started_at": started,
        "script": wb.get("script"),
        "archive_dir": wb.get("archive_dir") or None,
        "cards_in": len(cards or []),
    }
    log("[wb %s] 开始上架：%d 张卡（dry_run=%s）"
        % (tid, len(cards or []), out["dry_run"]))

    stdout, rc, timed_out = "", None, False
    try:
        p = subprocess.run(
            cmd, cwd=os.path.dirname(wb.get("script") or "") or None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=wb.get("timeout") or 900)
        stdout = (p.stdout or b"").decode("utf-8", "replace")
        rc = p.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = (e.stdout or b"").decode("utf-8", "replace") \
            if isinstance(e.stdout, bytes) else (e.stdout or "")
        out["error"] = "超时（>%ss）已 kill，**不重试**" % (wb.get("timeout") or 900)
        log("[wb %s] ⛔ %s" % (tid, out["error"]))
    except Exception as e:                       # noqa: BLE001 —— 兜住一切
        out["error"] = "%s: %r" % (type(e).__name__, e)
        log("[wb %s] ⛔ 启动失败：%s" % (tid, out["error"]))

    report = None
    if os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                report = json.load(f)
        except Exception as e:                   # noqa: BLE001
            out["report_error"] = "%r" % e

    summ = summarize(report)
    if timed_out:
        status = "timeout"
    elif report is None:
        status = "failed"
    else:
        status = summ["status"]

    out.update({
        "status": status,
        "returncode": rc,
        "finished_at": time.time(),
        "elapsed_sec": round(time.time() - started, 1),
        "counts": summ["counts"],
        "cards_out": summ["cards"],
        "report": report,
        "log_tail": [ln for ln in stdout.strip().splitlines() if ln.strip()][-40:],
    })
    log("[wb %s] 结束：status=%s counts=%s（%.1fs）"
        % (tid, status, summ["counts"], out["elapsed_sec"]))
    return out


def start(*, tid, payload, cards, config, update, workdir, log=print):
    """闸门判定 + 起后台线程。返回给网页的即时状态（不阻塞）。

    `update(tid, writeback_dict)` 由 hub 注入 —— 本模块不碰数据库，
    这样它保持纯粹、可离线单测。
    """
    import threading

    wb = cfg(config)
    ok, why = gate(payload, wb)
    if not ok:
        log("[wb %s] 跳过自动上架：%s" % (tid, why))
        return {"status": "skipped", "reason": why}

    update(tid, {"status": "running",
                 "dry_run": wb["dry_run"],
                 "started_at": time.time(),
                 "cards_in": len(cards or [])})

    def _worker():
        try:
            res = run_once(tid=tid, cards=cards, wb=wb,
                           workdir=workdir, log=log)
        except Exception as e:                   # noqa: BLE001
            res = {"status": "failed", "error": "%r" % e,
                   "finished_at": time.time()}
        try:
            update(tid, res)
        except Exception as e:                   # noqa: BLE001
            log("[wb %s] 结果入库失败：%r" % (tid, e))

    t = threading.Thread(target=_worker, name="wb-%s" % tid, daemon=True)
    t.start()
    return {"status": "running", "dry_run": wb["dry_run"]}
