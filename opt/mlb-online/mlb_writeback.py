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
四道闸门（任一不满足就不触发）
═══════════════════════════════════════════════════════════════════════
  a. **任务级**：网页提交时勾了「自动上架」（payload.write_back）
  b. **服务级**：`server_config.json` 的 `writeback.enabled` 为 true
  c. **环境级**：直写脚本与后台凭据文件都存在
  d. **人工放行**（2026-10-12 新增，`writeback.require_approval = true` 时生效）：
     采集跑完后**不直接写**，而是把"将要写的那批卡"**冻结**下来，状态置
     `awaiting_review`，等人到网页上逐条核对、点「确认放行」才起写卡子进程。

另外 `writeback.dry_run`（默认 true）**只读**：即便放行也只登录+回读，
不产生任何写入。要真正上线必须显式把它改成 false。

⚠️ 语义红线：`add` / `edit` / `shelves` 出现**未知结果**时绝不重试
（超时≠失败，重试可能建出重复模型）。本模块对任何异常一律只记录、
不重跑，`needs_review` 就是留给人工的信号。

───────────────────────────────────────────────────────────────────────
人工放行为什么要「冻结快照」而不是读 DB 里的 cards
───────────────────────────────────────────────────────────────────────
`tasks.result.cards` 会被后续 `/result` 覆盖（任务被重跑、执行器补传）。
若人工核对的是 A、真写的是 B，这道闸门就等于没装。

所以放行前把待写卡片**整份落盘**（`<workdir>/<tid>.pending.json`，
含 `sha256`），放行时只从这份快照取卡片交集。新结果进来会**整份替换**
快照，旧确认随之作废 —— 不会出现"看到的和写的不一致"。

★ 并发安全：hub 是 `ThreadingHTTPServer`，双击「放行」会并发进来。
`读状态 → 判状态 → 落盘 → 起线程` 整段用 `APPROVE_LOCK` 互斥，
且状态从 `awaiting_review` 迁到 `running` 是**一次性**的 ——
第二个请求只会拿到 `noop`，绝不会起第二个子进程（那会建重复模型）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time

#: 生产写入必须带的口令（与直写脚本的闸门一致）
DEFAULT_CONFIRM = "mlb26-players"

#: 待人工确认的状态值
AWAITING = "awaiting_review"

#: 「读状态 → 判状态 → 落盘 → 起线程」必须整段原子。
#: hub 是 ThreadingHTTPServer，双击/并发「放行」会起两个写卡子进程 ——
#: 后果是**建出重复的商品模型**，属于不能自动回滚的破坏。
APPROVE_LOCK = threading.Lock()

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
    ⚠️ `require_approval` 缺省为 **True**：配置写漏了就往「停下来等人」
       的方向倒 —— 多停一次只是多点一下，少停一次就是未经确认的线上写入。
    """
    wb = (config or {}).get("writeback") or {}
    return {
        "enabled": bool(wb.get("enabled", False)),
        "dry_run": bool(wb.get("dry_run", True)),
        "require_approval": bool(wb.get("require_approval", True)),
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


def cards_sha(cards):
    """待写卡片的**规范化**指纹。用于证明「人工核对的就是将要写的」。"""
    norm = json.dumps(cards or [], ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def pending_path(workdir, tid):
    """待审快照的落点。重启后仍要能放行，所以必须落盘、不能只放内存。"""
    return os.path.join(workdir, "%s.pending.json" % tid)


def review_preview(cards):
    """给人工核对用的逐卡清单。

    ⚠️ 这里**只做本地静态校验**，不判断"后台是否已存在"—— 那要连网读，
       是写卡脚本的职责。`issues` 是**提示**，不是放行判据：有 issue 的卡
       仍可能被放行（比如售价缺失但人工确认可接受），所以不在这里拦截。
    """
    out, seen = [], {}
    for c in (cards or []):
        if not isinstance(c, dict):
            continue
        nm = str(c.get("product_name") or "")
        issues = []
        if not nm:
            issues.append("缺 product_name")
        if not c.get("hash"):
            issues.append("缺卡图 hash")
        if not c.get("sale_price"):
            issues.append("缺售价")
        if nm and nm in seen:
            issues.append("与本批第 %d 条同名" % (seen[nm] + 1))
        if nm:
            seen.setdefault(nm, len(out))
        out.append({
            "product_name": nm,
            "name": c.get("name"), "ovr": c.get("ovr"),
            "position": c.get("position"), "team": c.get("team"),
            "series": c.get("series"),
            "sale_price": c.get("sale_price"), "hash": c.get("hash"),
            "include": bool(c.get("include")),
            "issues": issues,
        })
    return out


def freeze(*, tid, cards, wb, workdir, log=print):
    """把「待写卡片」冻结落盘，返回待审状态。

    ★ 每次 `/result` 进来都会**整份替换**快照 —— 这是刻意的：新结果意味着
      旧的人工确认已经过期，必须重新核对，不能沿用。
    """
    os.makedirs(workdir, exist_ok=True)
    cards = [c for c in (cards or []) if isinstance(c, dict)]
    snap = {
        "tid": tid,
        "frozen_at": time.time(),
        "dry_run": bool(wb.get("dry_run")),
        "confirm": wb.get("confirm"),
        "sha256": cards_sha(cards),
        "cards": cards,
    }
    p = pending_path(workdir, tid)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    pre = review_preview(cards)
    log("[wb %s] 采集完成 → 冻结 %d 张卡待人工确认（快照 %s）"
        % (tid, len(cards), os.path.basename(p)))
    return {
        "status": AWAITING,
        "dry_run": bool(wb.get("dry_run")),
        "require_approval": True,
        "awaiting_since": snap["frozen_at"],
        "cards_in": len(cards),
        "sha256": snap["sha256"],
        "pending": pre,
        "default_selected": sum(1 for x in pre if x["include"]),
        "issues_total": sum(len(x["issues"]) for x in pre),
        "reason": "采集已完成，尚未写入后台 —— 请逐条核对后点「确认放行」。",
    }


def read_pending(workdir, tid):
    """读待审快照。文件不在/坏了就返回 None（→ 上层拒绝放行，不猜）。"""
    p = pending_path(workdir, tid)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            snap = json.load(f)
        return snap if isinstance(snap, dict) else None
    except Exception:                                 # noqa: BLE001
        return None                                   # 坏了就当没有 —— 由上层拒绝放行


def _start_worker(*, tid, cards, wb, update, workdir, log, extra=None):
    """起写卡后台线程（fire & forget）。**调用方必须已经落好 running 状态。**"""
    def _worker():
        try:
            res = run_once(tid=tid, cards=cards, wb=wb, workdir=workdir,
                           log=log, extra=extra)
        except Exception as e:                        # noqa: BLE001
            res = {"status": "failed", "error": "%r" % e,
                   "finished_at": time.time()}
        try:
            update(tid, res)
        except Exception as e:                        # noqa: BLE001
            log("[wb %s] 结果入库失败：%r" % (tid, e))

    t = threading.Thread(target=_worker, name="wb-%s" % tid, daemon=True)
    t.start()
    return t


def run_once(*, tid, cards, wb, workdir, log=print, extra=None):
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
    if extra:
        # 审批留痕（谁在什么时候放行了哪一版快照）。
        # ⚠️ 用 setdefault：这些只做**补充**，绝不能覆盖上面的运行结论。
        for k, v in extra.items():
            out.setdefault(k, v)
    log("[wb %s] 结束：status=%s counts=%s（%.1fs）"
        % (tid, status, summ["counts"], out["elapsed_sec"]))
    return out


def start(*, tid, payload, cards, config, update, workdir, log=print, read=None):
    """闸门判定 + **停下等人放行** 或 直接起后台线程。

    `update(tid, writeback_dict)` / `read(tid) -> dict` 由 hub 注入 ——
    本模块不碰数据库，保持纯粹、可离线单测。

    返回给调用方的即时状态（不阻塞）：
      - `skipped`          闸门没过
      - `awaiting_review`  已冻结快照、等人放行（require_approval 时）
      - `running`          已起线程（require_approval=false 时）
    """
    wb = cfg(config)
    ok, why = gate(payload, wb)
    if not ok:
        log("[wb %s] 跳过自动上架：%s" % (tid, why))
        return {"status": "skipped", "reason": why}

    with APPROVE_LOCK:
        cur = (read(tid) if read else None) or {}
        if cur.get("status") == "running":
            # 重复触发（执行器补传一次结果）不能起第二个进程：会建重复模型
            log("[wb %s] 已有上架在跑，忽略本次重复触发" % tid)
            return {"status": "running", "reason": "已有上架在跑，忽略重复触发"}

        if wb["require_approval"]:
            state = freeze(tid=tid, cards=cards, wb=wb, workdir=workdir, log=log)
            update(tid, state)
            return state

        update(tid, {"status": "running",
                     "dry_run": wb["dry_run"],
                     "started_at": time.time(),
                     "cards_in": len(cards or [])})

    _start_worker(tid=tid, cards=cards, wb=wb, update=update,
                  workdir=workdir, log=log)
    return {"status": "running", "dry_run": wb["dry_run"]}


def approve(*, tid, names, config, update, read, workdir, by="", log=print):
    """人工放行：**只有走到这里才会真的写后台**。

    `names`：本次要写的 `product_name` 列表（网页上勾选的）。
    `None` 表示全选（等价于整份快照）。

    返回一个字典（**永不抛异常**），`status` 取值：
      - `running` 已起线程
      - `noop`    状态不允许放行 / 快照丢失 / 选择非法（`reason` 说明原因）

    ⚠️ 幂等：从 `awaiting_review` 迁到 `running` 只成功一次。
       第二次点（或网络重发）只会拿到 `noop`，**不会再起一个写卡进程**。
    """
    with APPROVE_LOCK:
        cur = (read(tid) if read else None) or {}
        st = cur.get("status")
        if st != AWAITING:
            return {"status": "noop", "current": st,
                    "reason": "当前状态是「%s」，无需（或不能）放行" % (st or "无")}

        snap = read_pending(workdir, tid)
        if not snap:
            return {"status": "noop", "current": st,
                    "reason": "待审快照文件不存在（可能被清理），请重跑采集后再放行"}

        cards = [c for c in (snap.get("cards") or []) if isinstance(c, dict)]
        by_name = {}
        for c in cards:
            by_name.setdefault(str(c.get("product_name") or ""), c)

        if names is None:
            picked = list(cards)
        else:
            if not isinstance(names, (list, tuple)):
                return {"status": "noop", "current": st,
                        "reason": "names 必须是数组"}
            wanted = [str(n) for n in names if str(n or "").strip()]
            if not wanted:
                return {"status": "noop", "current": st,
                        "reason": "没有勾选任何卡片，已拒绝放行"}
            unknown = [n for n in wanted if n not in by_name]
            if unknown:
                # 前端传了快照里没有的名字 → 要么 UI 过期、要么被人为构造
                return {"status": "noop", "current": st,
                        "reason": "选择里含待审快照外的卡片（%d 个，如 %r），已拒绝"
                                  % (len(unknown), unknown[0])}
            picked = [by_name[n] for n in wanted]
        if not picked:
            return {"status": "noop", "current": st, "reason": "待审清单为空，拒绝放行"}

        wb = cfg(config)
        approved_at = time.time()
        # ⚠️ `approved_cards` 是**计数**（前端在用它渲染「写 N / 待审 M 张」），
        #    所以另起一个 `approved_names` 存**名单**。
        #    光有计数 + sha256 还不够：事后想回答「到底放行了哪几张」，
        #    只有 sha256 就得把快照翻出来重算；名单直接可读、可对账。
        names_picked = [str(c.get("product_name") or "") for c in picked]
        audit = {
            "approved_by": by or "unknown",
            "approved_at": approved_at,
            "approved_cards": len(picked),
            "approved_names": names_picked,
            "reviewed_cards": len(cards),
            "sha256": snap.get("sha256"),
        }
        state = {
            "status": "running",
            "dry_run": wb["dry_run"],
            "started_at": approved_at,
            "pending": review_preview(picked),
        }
        state.update(audit)
        update(tid, state)
        log("[wb %s] ✅ 人工放行（%s）：写 %d / 待审 %d 张"
            % (tid, by or "unknown", len(picked), len(cards)))

    _start_worker(tid=tid, cards=picked, wb=wb, update=update,
                  workdir=workdir, log=log, extra=audit)
    out = {"status": "running", "dry_run": wb["dry_run"]}
    out.update(audit)
    return out


def cancel(*, tid, read, update, workdir, by="", log=print, reason=""):
    """人工取消本次上架。**只允许从 `awaiting_review` 取消** ——
    已经在跑的（`running`）不提供取消：写卡子进程中途 kill 会留下
    状态未知的模型，属于更危险的操作，必须去后台人工核对。"""
    with APPROVE_LOCK:
        cur = (read(tid) if read else None) or {}
        st = cur.get("status")
        if st != AWAITING:
            return {"status": "noop", "current": st,
                    "reason": "当前状态是「%s」，不可取消" % (st or "无")}
        update(tid, {
            "status": "cancelled",
            "cancelled_at": time.time(),
            "cancelled_by": by or "unknown",
            "sha256": (read_pending(workdir, tid) or {}).get("sha256"),
            "reason": reason or "人工取消：本次不写入后台（采集产物仍可下载）",
        })
    log("[wb %s] ⛔ 人工取消上架（%s）" % (tid, by or "unknown"))
    return {"status": "cancelled"}
