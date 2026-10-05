# -*- coding: utf-8 -*-
"""
任务队列与执行器
================
- 全局单 worker 线程串行消费任务队列（避免并发请求把 IGGM 的 IP 搞封）
- 无账号：所有人共享一条队列，提交人只是个可留空的备注名
- 任务状态放内存（前端轮询快），同时落 SQLite（刷新页面不丢历史）
- 复用 core.IGGMCrawler 的 progress / cancel 回调，抓取核心零改动
"""
import csv
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime

import db
import sites

FIELDNAMES = ["site", "page_type", "platform", "category", "title", "quantity",
              "unit", "unit_price", "total_price", "sales", "goods_no", "image",
              "updated", "source_url"]

# ---- 价格字段规范化（导出 CSV 前统一处理）----
# total_price 直接落原始抓取值会有两类问题：
#   1) float 精度尾巴：0.011999999999999999 / 1.9500000000000002
#   2) 来源值可能带前导单引号、$、千分位逗号、空格 → 落表后被当成文本
# 因此在写 CSV 前统一清洗成「纯数字 + 固定小数位」。
PRICE_FIELDS = ("total_price",)  # 需要规范化的字段（要加 unit_price 直接往里加）
PRICE_DECIMALS = 3               # 保留小数位
_PRICE_KEEP = re.compile(r"[^\d.\-]")

MAX_LOG = 400

_tasks = {}
_task_lock = threading.Lock()
_q = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def fmt_price(value, ndigits=PRICE_DECIMALS):
    """把任意来源的价格清洗成「纯数字 + 固定小数位」的字符串。

    处理内容：去前导/包裹的单双引号、货币符号、千分位逗号、空格，
    再统一按 ndigits 位小数输出。清洗失败（空值 / 非数字）时原样返回，
    不瞎造数据，避免把脏值悄悄变成 0。
    """
    if value is None or value == "":
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        s = _PRICE_KEEP.sub("", str(value).strip())
        if not s or s in (".", "-", "-.", ".."):
            return value
        try:
            num = float(s)
        except ValueError:
            return value
    return format(round(num, ndigits), ".%df" % ndigits)


def normalize_rows(rows):
    """导出前就地规范化价格字段，返回被修正的条数"""
    fixed = 0
    for r in rows:
        for k in PRICE_FIELDS:
            if k not in r:
                continue
            old, new = r[k], fmt_price(r[k])
            if new != old:
                fixed += 1
                r[k] = new
    return fixed


# ---------------- 提交 / 查询 ----------------
def submit(url, categories, game="", submitter="", site=""):
    tid = uuid.uuid4().hex[:12]
    task = {
        "id": tid,
        "site": site or (sites.detect_site(url) or ""),
        "game": (game or "").strip()[:80],
        "url": url,
        "submitter": (submitter or "").strip()[:40],
        "categories": list(categories),
        "status": "queued",
        "progress": 0.0,
        "detail": "排队中",
        "rows": 0,
        "file": "",
        "error": "",
        "logs": [],
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished": "",
        "stop": threading.Event(),
    }
    with _task_lock:
        _tasks[tid] = task
    db.insert_task(task)
    _q.put(tid)
    _ensure_worker()
    return tid


def get(task_id):
    with _task_lock:
        return _tasks.get(task_id)


def public(task, queue_pos=None):
    d = {
        "id": task["id"],
        "site": task.get("site", ""),
        "game": task.get("game", ""),
        "url": task["url"],
        "submitter": task.get("submitter", ""),
        "categories": task["categories"],
        "status": task["status"],
        "progress": round(task["progress"] * 100, 1),
        "detail": task["detail"],
        "rows": task["rows"],
        "file": task["file"],
        "error": task.get("error", ""),
        "created": task["created"],
        "finished": task["finished"],
    }
    if queue_pos is not None:
        d["queue_pos"] = queue_pos
    return d


def _from_row(r):
    keys = r.keys()
    return {
        "id": r["id"],
        "site": r["site"] if "site" in keys else "",
        "game": r["game"] if "game" in keys else "",
        "url": r["game_url"],
        "submitter": r["submitter"] if "submitter" in r.keys() else "",
        "categories": r["categories"].split(",") if r["categories"] else [],
        "status": r["status"],
        "progress": round(r["progress"] * 100, 1),
        "detail": r["detail"],
        "rows": r["rows"],
        "file": r["file_name"],
        "error": r["error"] if "error" in r.keys() else "",
        "created": r["created_at"],
        "finished": r["finished_at"],
    }


def snapshot(history_limit=40):
    """返回 正在执行 + 排队中（含排队位次）+ 历史任务"""
    with _task_lock:
        items = list(_tasks.values())
    active = [t for t in items if t["status"] in ("queued", "running")]
    active.sort(key=lambda t: t["created"])
    queued = [t for t in active if t["status"] == "queued"]
    out = []
    for t in active:
        pos = 0 if t["status"] == "running" else queued.index(t) + 1
        out.append(public(t, queue_pos=pos))

    hist = []
    for r in db.list_tasks(history_limit):
        mem = _tasks.get(r["id"])
        # 内存里还活着的用内存态（progress 更实时），否则用库里的
        hist.append(public(mem, queue_pos=0) if mem else _from_row(r))
    return {"active": out, "history": hist,
            "queue_len": len(queued),
            "running": next((t["id"] for t in out if t["status"] == "running"), None)}


def cancel(task_id):
    task = get(task_id)
    if not task:
        return False, "任务不存在"
    if task["status"] in ("done", "failed", "cancelled"):
        return False, "任务已结束"
    task["stop"].set()
    if task["status"] == "queued":
        task["status"] = "cancelled"
        task["detail"] = "排队中已取消"
        task["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _sync(task)
        return True, "已取消（尚未开始）"
    task["detail"] = "正在停止…（等待当前请求结束）"
    return True, "已请求停止"


def recover_pending():
    """服务重启时把上次遗留的 queued/running 标为中断，避免永远卡在队列里"""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT id FROM tasks WHERE status IN ('queued','running')").fetchall()
    finally:
        conn.close()
    for r in rows:
        db.update_task(r["id"], status="failed",
                       detail="服务重启，任务中断", finished_at=db.now_str())
    return len(rows)


# ---------------- worker ----------------
def _ensure_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True).start()
            _worker_started = True


def _worker():
    while True:
        tid = _q.get()
        task = get(tid)
        if task:
            _run(task)
        _q.task_done()


def _sync(task):
    db.update_task(task["id"], status=task["status"],
                   progress=task["progress"], detail=task["detail"],
                   rows=task["rows"], file_name=task["file"],
                   error=task["error"], finished_at=task["finished"])


def _run(task):
    if task["stop"].is_set():
        task["status"] = "cancelled"
        task["detail"] = "已取消"
        task["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _sync(task)
        return

    task["status"] = "running"
    task["progress"] = 0.0
    task["detail"] = "开始抓取"
    _sync(task)

    def log(msg):
        msg = str(msg)
        task["logs"].append(msg)
        if len(task["logs"]) > MAX_LOG:
            task["logs"] = task["logs"][-MAX_LOG:]

    def progress(frac, label=""):
        task["progress"] = max(0.0, min(1.0, float(frac)))
        if label:
            task["detail"] = str(label)[:160]

    site_key = task.get("site") or sites.detect_site(task["url"]) or ""
    site_label = sites.site_name(site_key)

    rows, total, t0 = [], len(task["categories"]), time.time()
    ok_n = fail_n = 0
    try:
        for i, cat in enumerate(task["categories"]):
            if task["stop"].is_set():
                log("■ 已请求停止，剩余品类不再抓取")
                break
            base, span = i / total, 1.0 / total

            def prog(frac, label="", base=base, span=span, i=i):
                progress(base + frac * span, f"({i + 1}/{total}) {label}")

            log(f"■ 抓取 {cat}")
            try:
                part = sites.scrape(cat, log=log, progress=prog,
                                    cancel=lambda: task["stop"].is_set())
                for r in part:
                    r.setdefault("site", site_label)
                rows.extend(part)
                ok_n += 1
                log(f"  完成 {len(part)} 行")
            except Exception as e:
                fail_n += 1
                log(f"  失败: {e}")

        os.makedirs(db.EXPORT_DIR, exist_ok=True)
        slug = (task["url"].rstrip("/").split("/")[-1] or "game").replace("/", "_")
        slug = re.sub(r"[^\w\-]+", "_", slug)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{site_key or 'site'}_{slug}_{stamp}_{task['id']}.csv"
        path = os.path.join(db.EXPORT_DIR, fname)
        # 写 CSV 前统一清洗 total_price：去引号/货币符/千分位，并固定 3 位小数
        fixed = normalize_rows(rows)
        if fixed:
            log(f"已规范化 total_price {fixed} 条"
                f"（保留 {PRICE_DECIMALS} 位小数）")

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

        task["file"] = fname
        task["rows"] = len(rows)
        warn = f"（{fail_n}/{total} 个品类失败，见日志）" if fail_n else ""
        if not rows and fail_n and not ok_n:
            # 一个都没抓到：多半是 URL 不对或页面结构变了，别假装成功
            task["status"] = "failed"
            task["error"] = f"{fail_n} 个品类全部失败"
            task["detail"] = f"没有抓到数据：{fail_n} 个品类全部失败，请核对 URL 或看日志"
        elif task["stop"].is_set():
            task["status"] = "cancelled"
            task["detail"] = f"已中止，已导出 {len(rows)} 行"
        else:
            task["status"] = "done"
            task["progress"] = 1.0
            task["detail"] = (f"完成 {len(rows)} 行 {warn}"
                              f"耗时 {int(time.time() - t0)}s")
        log(f"已导出: {path}")
    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        task["detail"] = f"失败：{e}"
        log(f"任务异常: {e}")
    finally:
        task["finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _sync(task)
