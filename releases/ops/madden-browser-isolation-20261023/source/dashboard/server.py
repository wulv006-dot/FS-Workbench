"""Madden NFL 27 Coins 云端报价工作台 —— 服务端。

设计原则（与参考工作台一致）：**浏览器只负责显示与确认**，
采集、报价、预览、后台写入与恢复全部在服务端执行；页面刷新或关掉都不会中断任务。

安全：
  - 只监听 127.0.0.1；
  - 所有 POST 必须带自定义请求头 `X-Requested-With: MaddenWorkbench`，
    跨源脚本发自定义头必然触发预检，而本服务不返回宽松 CORS 头 —— 挡掉 CSRF；
  - 写价与恢复必须显式带 client_event_id（操作编号），并原样落到审计；
  - 全局只允许一个后台任务在跑（其余排队）：同一 profile 不能并发开两个 Chromium。

进程边界：
  需要后台页面（Playwright）的动作统一通过 `run_pipeline.py` 子进程完成
  （`--snapshot-out` / `--targets-json --write`），本进程只跑纯计算与调度。
"""
from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from madden_nfl_27 import store                                   # noqa: E402
from madden_nfl_27 import workbench                               # noqa: E402
from madden_nfl_27.collect_storefront import load_cached as load_storefront  # noqa: E402
from madden_nfl_27.config import (GAME_ID, GAME_NAME, PLATFORMS,  # noqa: E402
                                  PRICE_ROW_IDS, QUANTITY_K)
from madden_nfl_27.cost_basis import variants_from_provenance     # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
EVIDENCE_FILE = EVIDENCE / "evidence.json"
BASELINE_FILE = EVIDENCE / "backend_baseline.json"
# 监听地址：默认只回环（本机工作台）。服务器部署时由 systemd 传
# MADDEN_HOST/MADDEN_PORT，并保持回环 + 反向代理，不要把 0.0.0.0 直接暴露。
HOST = os.environ.get("MADDEN_HOST") or "127.0.0.1"
try:
    PORT = int(os.environ.get("MADDEN_PORT") or 8792)
except ValueError:
    PORT = 8792
API = "/api/madden/cloud"
CSRF_HEADER = "MaddenWorkbench"

# 写入类接口的来源闸门：默认只接受回环来源（本机浏览器 / 反向代理转发）。
# 这一层不改变页面 —— 它挡的是"绕过反向代理直接打公网端口"的情况。
# 置 0/false/no 可关闭（仅在确认前面有可信鉴权时）。
_WRITE_LOOPBACK_ONLY = (os.environ.get("MADDEN_WRITE_LOOPBACK_ONLY", "1")
                        .strip().lower() not in ("0", "false", "no"))


def _is_loopback(addr: str) -> bool:
    """判断请求来源是不是本机（含 IPv4 映射写法 127.0.0.1 / ::ffff:127.0.0.1 / ::1）。"""
    try:
        return ipaddress.ip_address(addr.split("%")[0]).is_loopback
    except ValueError:
        return False


MANAGED = workbench.MANAGED

_VENV = (pathlib.Path.home() / ".workbuddy" / "binaries" / "python"
         / "envs" / "default" / "Scripts" / "python.exe")
WRITE_PYTHON = os.environ.get("MADDEN_WRITE_PYTHON") or (
    str(_VENV) if _VENV.exists() else sys.executable)


# --------------------------------------------------------------------------- #
# 运行时元信息（供 health / monitor）
# --------------------------------------------------------------------------- #
_META_LOCK = threading.Lock()
_META: dict = {"last_run": None, "last_successful_run": None,
               "p2pah_session": "unknown", "last_snapshot_at": None}


def _meta_set(**patch) -> None:
    with _META_LOCK:
        _META.update(patch)


def _meta_get(key: str, default=None):
    with _META_LOCK:
        return _META.get(key, default)


# --------------------------------------------------------------------------- #
# 任务队列（单并发）
# --------------------------------------------------------------------------- #
class JobError(RuntimeError):
    """带错误码的业务异常 —— 错误码会原样返回给前端做文案映射。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


_PENDING: "queue.Queue[str]" = queue.Queue()
_RUNNERS: dict[str, object] = {}
_RUNNERS_LOCK = threading.Lock()
_CURRENT: str | None = None
_CURRENT_LOCK = threading.Lock()


def _submit(kind: str, request: dict, runner) -> dict:
    job = store.new_job(kind, request)
    store.save_job(job)
    with _RUNNERS_LOCK:
        _RUNNERS[job["job_id"]] = runner
    _PENDING.put(job["job_id"])
    return job


def _submitted_ids() -> list[str]:
    """队列里还没轮到执行的任务（不含正在跑的）。"""
    with _RUNNERS_LOCK:
        return [jid for jid in _RUNNERS if jid != _CURRENT]


def _update(job_id: str, **patch) -> dict:
    job = store.load_job(job_id) or {"job_id": job_id}
    job.update(patch)
    store.save_job(job)
    return job


def _worker_loop() -> None:
    global _CURRENT
    while True:
        job_id = _PENDING.get()
        with _RUNNERS_LOCK:
            runner = _RUNNERS.pop(job_id, None)
        with _CURRENT_LOCK:
            _CURRENT = job_id
        job = store.load_job(job_id) or {}
        try:
            _update(job_id, status="running", stage="running")
            if runner is None:
                raise JobError("not_found", "任务执行体丢失")
            runner(job)
        except JobError as exc:
            _update(job_id, status="failed", stage="failed",
                    error_detail=exc.code, error=exc.detail or exc.code,
                    completed_at=store.now_iso())
        except subprocess.TimeoutExpired as exc:
            _update(job_id, status="failed", stage="timeout",
                    error_detail="job_timeout", error=f"超时：{exc}",
                    completed_at=store.now_iso())
        except Exception as exc:  # noqa: BLE001 - 任何异常都要落到作业记录
            _update(job_id, status="failed", stage="failed",
                    error_detail=f"{type(exc).__name__}",
                    error=f"{type(exc).__name__}: {exc}"[:300],
                    completed_at=store.now_iso())
        finally:
            with _CURRENT_LOCK:
                _CURRENT = None


def _current_job() -> str | None:
    with _CURRENT_LOCK:
        return _CURRENT


def _log_event(kind: str, *, request: dict | None = None, result: dict | None = None,
               status: str = "ready", actor: str = "local",
               config_change: dict | None = None, stage: str = "done") -> dict:
    """不占队列的“记录型”事件（如控制台设置变更），只为了让团队日志看得到。"""
    job = store.new_job(kind, request or {})
    job.update({"status": status, "stage": stage, "actor": actor,
                "result": result or {}, "completed_at": store.now_iso()})
    if config_change:
        job["config_change"] = config_change
    return store.save_job(job)


# --------------------------------------------------------------------------- #
# 子进程：所有需要后台页面的动作
# --------------------------------------------------------------------------- #
def _run_pipeline(argv: list[str], *, timeout: int = 1800) -> dict:
    out = EVIDENCE / f"job_out_{uuid.uuid4().hex[:8]}.json"
    cmd = [WRITE_PYTHON, "-u", "run_pipeline.py", *argv, f"--json={out}"]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env={**os.environ, 'MADDEN_PIPELINE_TIMEOUT': str(timeout)})
    except subprocess.TimeoutExpired as exc:
        raise JobError("job_timeout", f"子任务超过 {timeout} 秒未返回") from exc
    payload: dict = {}
    if out.exists():
        try:
            payload = json.loads(out.read_text(encoding="utf-8")) or {}
        except ValueError:
            payload = {}
        finally:
            try:
                out.unlink()
            except OSError:
                pass
    payload["returncode"] = None if proc is None else proc.returncode
    payload["stdout"] = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-200:]
    payload["stderr"] = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()][-80:]
    if payload.get("returncode") != 0 and not payload.get("error"):
        payload["error"] = next(iter(payload["stderr"]), "") or f"退出码 {payload['returncode']}"
    return payload


def _take_snapshot(job_id: str) -> dict:
    """取一次后台实时快照（独立子进程里开浏览器）。"""
    snap_out = EVIDENCE / f"snap_{job_id}.json"
    payload = _run_pipeline(["--snapshot-out", str(snap_out)], timeout=900)
    if payload.get("error") == "backend_login_expired":
        _meta_set(p2pah_session="expired")
        raise JobError("backend_login_expired", "服务器上的 P2PAH 后台登录已失效")
    if payload.get("returncode") != 0 or not snap_out.exists():
        _meta_set(p2pah_session="unknown")
        raise JobError("preview_unavailable",
                       payload.get("error") or "后台只读快照未取得")
    snap = json.loads(snap_out.read_text(encoding="utf-8"))
    try:
        snap_out.unlink()
    except OSError:
        pass
    if snap.get("login") or "/login" in (snap.get("url") or ""):
        _meta_set(p2pah_session="expired")
        raise JobError("backend_login_expired", "服务器上的 P2PAH 后台登录已失效")
    if not snap.get("rows"):
        raise JobError("backend_validation_failed", "后台行未就绪")
    _meta_set(p2pah_session="ok", last_snapshot_at=store.now_iso())
    return snap


def _write_targets(targets: dict, *, operation_id: str, actor: str,
                   extra: dict) -> dict:
    handle = EVIDENCE / f"targets_{operation_id}.json"
    handle.write_text(json.dumps({"targets": targets}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    try:
        payload = _run_pipeline(["--targets-json", str(handle), "--write",
                                 f"--operation-id={operation_id}",
                                 f"--actor={actor}",
                                 f"--extra-json={json.dumps(extra, ensure_ascii=False)}"],
                                timeout=1800)
    finally:
        try:
            handle.unlink()
        except OSError:
            pass
    audit = payload.get("audit") or {}
    if not payload.get("ok") or audit.get("status") != "CONFIRMED":
        raise JobError(audit.get("status") or payload.get("error") or "writer_not_confirmed",
                       "；".join(payload.get("stdout", [])[-3:]) or "写入未确认")
    return {"payload": payload, "audit": audit}


# --------------------------------------------------------------------------- #
# 各类任务
# --------------------------------------------------------------------------- #
def _quote_params() -> dict:
    return workbench.quote_params()


def _runner_collect(job: dict) -> None:
    job_id = job["job_id"]
    params = _quote_params()
    options = [f"--basis={params['basis']}", f"--margin={params['margin']}",
               f"--fx={params['fx']}", f"--profit={params['profit']}",
               f"--platforms={','.join(params['platforms'])}",
               f"--policy-revision={params['revision']}"]
    quote_out = EVIDENCE / f"quote_{job_id}.json"
    payload = _run_pipeline(["--quote-out", str(quote_out), *options], timeout=2400)
    if not payload.get("ok"):
        _meta_set(last_run=store.now_iso())
        raise JobError(payload.get("error") or "collection_incomplete",
                       "；".join(payload.get("stdout", [])[-4:]))
    run_id = payload.get("run_id")
    _meta_set(last_run=store.now_iso(), last_successful_run=store.now_iso(),
              p2pah_session="ok")
    drift = payload.get("cost_drift") or []
    _update(job_id, status="ready", stage="quote_ready", completed_at=store.now_iso(),
            log=payload.get("stdout", []),
            result={"run_id": run_id,
                    "quote_status": payload.get("quote_status"),
                    "cost_drift": drift,
                    "targets": payload.get("targets") or {}})


def _load_quote_for(run_id: str, *, check_policy: bool = True) -> dict:
    quote = store.load_quote(run_id)
    if not quote:
        raise JobError("not_found", "本轮报价不存在，请重新采集")
    latest = store.latest_quote()
    if latest and latest.get("run_id") != run_id and \
            (latest.get("created_at") or "") > (quote.get("created_at") or ""):
        raise JobError("newer_run_exists", "已有更新的采集轮次")
    if check_policy:
        params = _quote_params()
        if quote.get("policy_revision") != params["revision"]:
            raise JobError("automation_policy_changed_since_quote",
                           "报价使用的是旧控制台配置，请重新采集")
    return quote


def _runner_preview(job: dict) -> None:
    job_id = job["job_id"]
    run_id = str(job["request"].get("run_id") or "")
    quote = _load_quote_for(run_id)
    params = _quote_params()
    margin = Decimal(str(quote.get("minimum_gross_margin_pct") or params["margin"]))
    profit = Decimal(str(quote.get("admin_profit_rate") or params["profit"]))
    fx = Decimal(str(quote.get("fx") or params["fx"]))
    _update(job_id, stage="reading_backend")
    before = _take_snapshot(job_id)
    preview = workbench.build_preview(quote, before, run_id=run_id, margin=margin,
                                      profit=profit, fx=fx)
    preview["basis"] = quote.get("basis")
    preview["evidence_checked_at"] = (quote.get("evidence") or {}).get("checked_at")
    preview["policy_revision"] = quote.get("policy_revision")
    store.save_preview(preview)
    _update(job_id, status="ready", stage="preview_ready", completed_at=store.now_iso(),
            result={"preview_id": preview["preview_id"], "run_id": run_id,
                    "expires_at": preview["expires_at"]})


def _runner_recalculate(job: dict) -> None:
    job_id = job["job_id"]
    request = job["request"]
    run_id = str(request.get("run_id") or "")
    quote = _load_quote_for(run_id, check_policy=False)
    edits = request.get("edits") or {}
    overrides = edits.get("quotes") or {}
    params = _quote_params()
    if quote.get("policy_revision") != params["revision"]:
        raise JobError("automation_policy_changed_since_quote",
                       "报价使用的是旧控制台配置，请重新采集")
    margin = Decimal(str(edits.get("minimum_gross_margin_pct")
                         or quote.get("minimum_gross_margin_pct") or params["margin"]))
    if not (Decimal("0") <= margin < Decimal("100")):
        raise JobError("minimum_margin_invalid")
    profit = Decimal(str(quote.get("admin_profit_rate") or params["profit"]))
    fx = Decimal(str(quote.get("fx") or params["fx"]))
    # ---- 人工成本：改的是「本轮证据里的成本」，再由引擎整体重算建议价 ----
    # 只接受平台白名单内的值；精度对齐引擎 STEP（6 位），与后台 costPrice 一致。
    cost_edits = edits.get("costs") or {}
    clear_costs = edits.get("clear_costs")
    previous_costs = {k: str(v) for k, v in ((quote.get("edits") or {}).get("costs") or {}).items()}
    # clear_costs 的两种形态：
    #   true / 非空真值 → 全部取消人工成本；
    #   列表（如 ["PS"]）→ 只取消列出的平台 —— 前端把「把输入框填回采集值」识别成
    #   取消人工覆盖，需要一个平台粒度的入口，否则那一行会一直挂着"人工成本"标记。
    if isinstance(clear_costs, (list, tuple)):
        cleared = [str(p) for p in clear_costs]
        unknown = [p for p in cleared if p not in MANAGED]
        if unknown:
            raise JobError("automation_platform_disabled", f"未知平台 {'、'.join(unknown)}")
    else:
        cleared = list(previous_costs) if clear_costs else []
    manual_costs = {k: v for k, v in previous_costs.items() if k not in cleared}
    for platform, value in cost_edits.items():
        if platform not in MANAGED:
            raise JobError("automation_platform_disabled", f"未知平台 {platform}")
        try:
            cost_value = Decimal(str(value))
        except Exception as exc:  # noqa: BLE001
            raise JobError("cost_invalid", f"{platform} 成本不是数字") from exc
        if cost_value <= 0 or cost_value.quantize(workbench.STEP) != cost_value:
            raise JobError("cost_invalid", f"{platform} 成本最多 6 位小数且需大于 0")
        manual_costs[platform] = f"{cost_value:.6f}"
    costs_changed = manual_costs != previous_costs

    for platform, price in overrides.items():
        if platform not in MANAGED:
            raise JobError("automation_platform_disabled", f"未知平台 {platform}")
        try:
            value = Decimal(str(price))
        except Exception as exc:  # noqa: BLE001
            raise JobError("quote_not_ready", f"{platform} 目标价不是数字") from exc
        # 精度必须对齐引擎 STEP（6 位）：Madden 单价是 $0.03 量级，4 位会削掉引擎精度，
        # 更直接的问题是引擎自己产出的 6 位值（如 0.034086）会被这里拦下，
        # 导致「更新服务器预览」必定报格式无效。后台 costPrice 实测也是 6 位
        # （evidence/backend_baseline.json：0.173171），所以 6 位是双方的交集。
        if value <= 0 or value.quantize(workbench.STEP) != value:
            raise JobError("quote_not_ready", f"{platform} 目标价最多 6 位小数")
    margin_changed = margin != Decimal(str(quote.get("minimum_gross_margin_pct") or params["margin"]))
    if margin_changed or costs_changed:
        # 阈值或成本变了：同一轮证据重新过一遍引擎，否则底价行会与新阈值/新成本脱节。
        # 成本覆盖在 build_quote 内部于 apply_basis 之后生效，所以不传即回到采集口径。
        # 已有人手改过的目标价在这里先摘出来，重算后再由 apply_overrides 原样套回。
        existing_overrides = dict((quote.get("edits") or {}).get("quotes") or {})
        quote = workbench.build_quote(quote.get("evidence") or {}, basis=quote.get("basis") or params["basis"],
                                      margin=margin, fx=fx, profit=profit,
                                      policy_revision=quote.get("policy_revision"),
                                      cost_overrides=manual_costs)
        quote["run_id"] = run_id
        quote["edits"] = {"quotes": existing_overrides,
                          "minimum_gross_margin_pct": str(margin),
                          "reason": str(edits.get("reason") or "")[:200]}
        # ⚠️ 重建会把行数据打回引擎值，已有人手改过的目标价必须一起套回去，
        # 否则「改一次成本 / 改一次阈值」就把运营设的目标价静默冲掉
        # （2026-10-08 实测：PS 0.033900 / XBOX 0.020 就是这样没的）。
        # 本次提交的优先，所以 merged 里 update 放在后面。
        merged = dict(existing_overrides)
        merged.update({k: str(v) for k, v in overrides.items()})
        overrides = merged
    patched = workbench.apply_overrides(quote, overrides, margin=margin, profit=profit,
                                        fx=fx, reason=str(edits.get("reason") or "")[:200])
    patched["edits"]["costs"] = manual_costs
    store.save_quote(patched)
    if cost_edits or cleared:
        _log_event("cost_edit", actor="local",
                   request={"run_id": run_id, "costs": manual_costs,
                            "cleared": cleared, "previous": previous_costs},
                   result={"run_id": run_id, "quote_revision": patched.get("revision")})
    _log_event("recalculate", actor="local",
               request={"run_id": run_id, "edits": patched.get("edits")},
               result={"run_id": run_id, "quote_revision": patched.get("revision")})
    _update(job_id, status="ready", stage="quote_updated", completed_at=store.now_iso(),
            result={"run_id": run_id, "quote_status": patched.get("status"),
                    "quote_revision": patched.get("revision")})


def _runner_execute(job: dict) -> None:
    job_id = job["job_id"]
    request = job["request"]
    operation_id = str(request.get("client_event_id") or store.new_id())
    _update(job_id, stage="validating")
    preview = store.load_preview(str(request.get("preview_id") or ""))
    if not preview:
        raise JobError("preview_expired", "预览不存在")
    if _expired(preview.get("expires_at")):
        raise JobError("preview_expired")
    quote = _load_quote_for(str(preview.get("run_id") or ""))
    if quote.get("revision") != preview.get("quote_revision"):
        raise JobError("quote_changed_since_preview", "报价已修改，旧预览不能执行")
    params = _quote_params()
    if not params["system_enabled"]:
        raise JobError("automation_system_off", "系统总开关已关闭")
    pending = store.incomplete_audits()
    if pending:
        raise JobError("unresolved_execution_exists",
                       f"仍有 {len(pending)} 条未确认的改价操作")
    selected = [p for p in (request.get("selected_platforms") or []) if p in MANAGED]
    for platform in selected:
        if platform not in params["platforms"]:
            raise JobError("automation_platform_disabled", f"{platform} 未在控制台启用")
    confirmed = set(request.get("margin_confirmed_platforms") or [])
    reason = str(request.get("margin_exception_reason") or "")[:200]
    targets, low = {}, []
    for item in preview.get("targets") or []:
        platform = item["platform"]
        if platform not in selected:
            continue
        if item.get("marginBelowMinimum"):
            if platform not in confirmed:
                raise JobError("low_margin_confirmation_required",
                               f"{platform} 低于最低毛利率，需逐项确认")
            low.append(platform)
        targets[platform] = {"id": PRICE_ROW_IDS[platform],
                             "before_cost": item["backend_now_cost"],
                             "before_b2c": item["backend_now_b2c"],
                             "target_cost": item["targetCost"],
                             "expected_b2c": item["expected_b2c"],
                             "proposal": item["quote"],
                             "gross_margin_pct": item.get("actualGrossMargin")}
    if not targets:
        raise JobError("not_found", "所选平台没有可写入的目标值")
    if low and not reason:
        raise JobError("manual_margin_confirmation_required", "低毛利改价须填写原因")
    _update(job_id, stage="writing_backend")
    extra = {"operation_id": operation_id, "kind": "execute",
             "run_id": preview.get("run_id"), "preview_id": preview.get("preview_id"),
             "quote_edits": (quote.get("edits") or {}).get("quotes") or {},
             "low_margin_platforms": low,
             "operator_reason": reason or None}
    outcome = _write_targets(targets, operation_id=operation_id,
                            actor="workbench", extra=extra)
    _update(job_id, status="ready", stage="write_confirmed",
            completed_at=store.now_iso(),
            result={"status": "CONFIRMED", "operation_id": operation_id,
                    "selected": selected, "targets": targets,
                    "audit": outcome["audit"]})


def _runner_auto_cycle(job: dict) -> None:
    job_id = job["job_id"]
    params = _quote_params()
    operation_id = str(job["request"].get("client_event_id") or store.new_id())
    quote_out = EVIDENCE / f"quote_{job_id}.json"
    argv = ["--write", "--respect-margin-gate",
            f"--basis={params['basis']}", f"--margin={params['margin']}",
            f"--fx={params['fx']}", f"--profit={params['profit']}",
            f"--platforms={','.join(params['platforms'])}",
            f"--policy-revision={params['revision']}",
            f"--quote-out={quote_out}", "--actor=scheduler",
            f"--operation-id={operation_id}",
            f"--extra-json={json.dumps({'kind': 'auto_cycle', 'operation_id': operation_id}, ensure_ascii=False)}"]
    payload = _run_pipeline(argv, timeout=2700)
    if not payload.get("ok"):
        _meta_set(last_run=store.now_iso())
        raise JobError(payload.get("error") or "collection_incomplete",
                       "；".join(payload.get("stdout", [])[-4:]))
    _meta_set(last_run=store.now_iso(), last_successful_run=store.now_iso(),
              p2pah_session="ok")
    targets = payload.get("targets") or {}
    skipped = payload.get("skipped") or {}
    audit = payload.get("audit") or {}
    if audit.get("status") == "CONFIRMED":
        status = "confirmed"
    elif targets:
        status = "confirmed"
    elif skipped:
        status = "all_platforms_blocked"
    else:
        status = "no_price_change"
    _update(job_id, status="ready", stage="cycle_done", completed_at=store.now_iso(),
            log=payload.get("stdout", []),
            result={"status": status, "run_id": payload.get("run_id"),
                    "quote_status": payload.get("quote_status"),
                    "operation_id": operation_id if audit else None,
                    "audit": audit, "blocked_platforms": skipped,
                    "changes": [{"platform": p, **v} for p, v in targets.items()]})


def _runner_restore_preview(job: dict) -> None:
    job_id = job["job_id"]
    source = str(job["request"].get("source_execution_id") or "")
    audit = store.load_audit(source)
    if not audit:
        raise JobError("restore_preview_unavailable", "找不到该操作编号的审计")
    if audit.get("status") not in ("CONFIRMED", "RESTORED"):
        raise JobError("restore_source_not_confirmed", "原操作尚未完成确认")
    targets = audit.get("targets") or {}
    _update(job_id, stage="reading_backend")
    before = _take_snapshot(job_id)
    current = {row["id"]: row for row in (before.get("rows") or [])}
    rows, available = [], []
    for platform in MANAGED:
        target = targets.get(platform)
        if not target:
            continue
        row = current.get(PRICE_ROW_IDS[platform])
        if not row:
            continue
        matched = row.get("costPrice") == target.get("target_cost")
        if matched:
            available.append(platform)
        rows.append({"platform": platform,
                     "current_b2c": row.get("b2c"),
                     "current_cost": row.get("costPrice"),
                     "restore_b2c": target.get("before_b2c"),
                     "restore_cost": target.get("before_cost"),
                     "matches_completed": matched})
    if not rows:
        raise JobError("restore_preview_unavailable", "原操作没有可恢复的平台")
    if not available:
        raise JobError("restore_backend_changed_since_execution",
                       "后台现值与原操作完成时不一致")
    now = datetime.now(timezone.utc)
    preview = {"restore_preview_id": store.new_id(),
               "source_execution_id": source,
               "status": "restore_review_only",
               "created_at": now.isoformat(timespec="seconds"),
               "expires_at": (now + timedelta(minutes=workbench.PREVIEW_TTL_MINUTES)
                              ).isoformat(timespec="seconds"),
               "rows": rows, "available_platforms": available}
    store.save_restore_preview(preview)
    _update(job_id, status="ready", stage="restore_preview_ready",
            completed_at=store.now_iso(),
            result={"restore_preview_id": preview["restore_preview_id"],
                    "source_execution_id": source})


def _runner_restore(job: dict) -> None:
    job_id = job["job_id"]
    request = job["request"]
    source = str(request.get("source_execution_id") or "")
    operation_id = str(request.get("client_event_id") or store.new_id())
    preview = store.load_restore_preview(str(request.get("restore_preview_id") or ""))
    if not preview:
        raise JobError("restore_preview_expired", "恢复预览不存在")
    if preview.get("source_execution_id") != source:
        raise JobError("restore_source_mismatch", "恢复预览与原操作编号不一致")
    if _expired(preview.get("expires_at")):
        raise JobError("restore_preview_expired")
    available = set(preview.get("available_platforms") or [])
    selected = [p for p in (request.get("selected_platforms") or []) if p in available]
    if not selected:
        raise JobError("restore_preview_unavailable", "没有可恢复的平台")
    rows = {row["platform"]: row for row in preview.get("rows") or []}
    targets = {}
    for platform in selected:
        row = rows[platform]
        targets[platform] = {"id": PRICE_ROW_IDS[platform],
                             "before_cost": row["current_cost"],
                             "before_b2c": row["current_b2c"],
                             "target_cost": row["restore_cost"],
                             "expected_b2c": row["restore_b2c"],
                             "proposal": row["restore_b2c"],
                             "gross_margin_pct": None,
                             "restore": True}
    _update(job_id, stage="writing_backend")
    extra = {"operation_id": operation_id, "kind": "restore",
             "restore_source": source,
             "restore_preview_id": preview.get("restore_preview_id")}
    outcome = _write_targets(targets, operation_id=operation_id,
                            actor="workbench", extra=extra)
    # 把状态改写成 RESTORED（apply_prices 只知道“写成功”，分不清是改价还是恢复）。
    # 正常路径下该审计已由 apply_prices 按操作编号落盘；万一没找到，就用现有信息补一条，
    # 但**必须沿用同一个操作编号**，否则会在团队日志里留下一笔对不上号的孤儿记录。
    record = store.load_audit(operation_id) or {
        "id": operation_id, "actor": "workbench", "created_at": store.now_iso(),
        "targets": targets, "changed": sorted(targets)}
    record["id"] = operation_id
    record.update({"status": "RESTORED", "restore_source": source,
                   "restore_preview_id": preview.get("restore_preview_id")})
    store.save_audit(record)
    _update(job_id, status="ready", stage="restore_confirmed",
            completed_at=store.now_iso(),
            result={"status": "RESTORED", "operation_id": operation_id,
                    "source_execution_id": source, "selected": selected,
                    "audit": outcome["audit"]})


def _expired(iso: str | None) -> bool:
    if not iso:
        return True
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= when


# --------------------------------------------------------------------------- #
# 自动跟价调度器
# --------------------------------------------------------------------------- #
_SCHEDULER_STARTED = False
_BROWSER_IDLE_CHECKED = 0.0


def _release_idle_browser():
    global _BROWSER_IDLE_CHECKED
    if _current_job() or _submitted_ids() or time.monotonic() - _BROWSER_IDLE_CHECKED < 30:
        return
    _BROWSER_IDLE_CHECKED = time.monotonic()
    if pathlib.Path(WRITE_PYTHON).name == 'run_in_container.sh':
        from browser_runtime import release_idle
        release_idle()


def _schedule_state(cfg: dict) -> str:
    if not cfg.get("system_enabled"):
        return "system_off"
    if cfg.get("mode") != "auto":
        return "manual_mode"
    if not cfg.get("platforms"):
        return "platforms_off"
    return "auto"


def _next_after_settings(before, after, last, now):
    interval_changed = before.get('interval_minutes') != after.get('interval_minutes')
    stable = all(before.get(key) == after.get(key) for key in
                 ('system_enabled', 'mode', 'platforms', 'basis',
                  'minimum_gross_margin_pct', 'fx', 'profit'))
    if not interval_changed or not stable:
        return now
    try:
        anchor = datetime.fromisoformat(last['created_at'])
        if anchor.tzinfo is None:
            raise ValueError('aware_original_job_time_required')
    except (KeyError, TypeError, ValueError):
        anchor = now
    return max(now, anchor + timedelta(minutes=int(after['interval_minutes'])))


def _last_auto_job(schedule: dict) -> dict | None:
    job_id = schedule.get("last_job_id")
    return store.load_job(job_id) if job_id else None


def _scheduler_tick() -> None:
    cfg = store.load_config()
    state = _schedule_state(cfg)
    schedule = store.load_schedule()
    if state != "auto":
        if schedule.get("status") != state or schedule.get("next_at"):
            store.save_schedule({"status": state, "next_at": None, "last_error": None})
        return
    if _current_job() or _submitted_ids():
        store.save_schedule({"status": "in_progress"})
        return
    if (schedule.get("status") == "paused_after_failure"
            and schedule.get("failed_revision") == cfg.get("revision")):
        return                                   # 须重新保存设置才恢复
    interval = max(1, int(cfg.get("interval_minutes") or 60))
    now = datetime.now(timezone.utc)
    next_at = schedule.get("next_at")
    due = True
    if next_at:
        try:
            when = datetime.fromisoformat(next_at)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            due = now >= when
        except ValueError:
            due = True
    if due:
        job = _submit("auto_cycle",
                      {"policy_revision": cfg.get("revision"),
                       "platforms": cfg.get("platforms"),
                       "client_event_id": store.new_id()},
                      _runner_auto_cycle)
        store.save_schedule({"status": "due", "last_job_id": job["job_id"],
                             "last_result": None, "last_error": None,
                             "next_at": (now + timedelta(minutes=interval)
                                         ).isoformat(timespec="seconds")})
        return
    # 还没到点：若上一轮任务仍在排队或执行，状态必须保持“进行中”，
    # 否则前端的轮询会因为看到 waiting 而不再跟踪这一轮的结果。
    last = _last_auto_job(schedule)
    if last and last.get("status") in ("queued", "running"):
        store.save_schedule({"status": "in_progress"})
        return
    if schedule.get("status") != "due":
        store.save_schedule({"status": "waiting"})


def _watch_schedule_results() -> None:
    """把最近一次定时任务的结果同步到调度状态（失败即暂停）。"""
    schedule = store.load_schedule()
    job_id = schedule.get("last_job_id")
    if not job_id or schedule.get("last_result_checked") == job_id:
        return
    job = store.load_job(job_id)
    if not job or job.get("status") in ("queued", "running"):
        return
    cfg = store.load_config()
    if job.get("status") == "ready":
        store.save_schedule({"status": "waiting",
                             "last_result": (job.get("result") or {}).get("status"),
                             "last_error": None, "last_result_checked": job_id})
    else:
        store.save_schedule({"status": "paused_after_failure",
                             "last_result": "failed",
                             "last_error": job.get("error_detail") or job.get("error"),
                             "failed_revision": cfg.get("revision"),
                             "last_result_checked": job_id})


def _scheduler_loop() -> None:
    while True:
        time.sleep(5)
        try:
            try:
                _release_idle_browser()
                _meta_set(browser_cleanup_error=None)
            except Exception as exc:
                _meta_set(browser_cleanup_error=type(exc).__name__)
            _scheduler_tick()
            _watch_schedule_results()
        except Exception:  # noqa: BLE001 - 调度器绝不能死
            pass


# --------------------------------------------------------------------------- #
# 监控
# --------------------------------------------------------------------------- #
def _read_evidence() -> dict:
    try:
        return json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _browser_available() -> bool:
    """写价通道是否可用（决定 /health 的 browser / price_writer，进而决定前端执行按钮）。

    三层判定，按顺序：
      1. MADDEN_BROWSER_AVAILABLE=1/0 显式覆盖（想临时禁止写入时设 0）；
      2. 服务进程自己装了 playwright（本机形态，旧行为不变）；
      3. 写价子进程解释器存在 —— 云端形态：playwright 在浏览器容器里、
         服务进程故意不装（宿主 glibc 太老），此时采集/写价都走
         MADDEN_WRITE_PYTHON（= run_in_container.sh → docker exec）。
         ⚠️ 只用"解释器存在"判定，别去 import playwright 或探测 CDP：
         那会把云端永远判成 missing，前端「明确执行」按钮就永远点不了
         （2026-09-30 云端验收踩过：采集/预览全通、唯独按钮是灰的）。
    """
    import importlib.util
    override = os.environ.get("MADDEN_BROWSER_AVAILABLE")
    if override is not None and override.strip() != "":
        return override.strip().lower() not in ("0", "false", "no")
    if importlib.util.find_spec("playwright") is not None:
        return True
    return pathlib.Path(WRITE_PYTHON).exists()


def _relevant_jobs() -> list[dict]:
    return [j for j in store.list_jobs(limit=200)
            if j.get("kind") in ("collect", "auto_cycle")]


def build_health() -> dict:
    cfg = store.load_config()
    schedule = store.load_schedule()
    pending = _submitted_ids()
    current = _current_job()
    browser_ok = _browser_available()
    if current:
        writer = "busy"
    elif browser_ok:
        writer = "ready"
    else:
        writer = "missing"
    evidence = _read_evidence()
    offers = evidence.get("offers") or {}
    costs = evidence.get("costs") or {}
    sources = {}
    for label, site in (("lootbar", "LootBar"), ("iggm", "IGGM"), ("u4gm", "U4GM")):
        sources[label] = ("ok" if any(
            site in (offers.get(platform) or {}) for platform in MANAGED) else "missing")
    sources["p2pah_cost"] = "ok" if all(
        (costs.get(platform) or {}).get("cny_per_k") for platform in MANAGED) else "missing"
    if sources["p2pah_cost"] == "ok" and evidence.get("cost_drift"):
        sources["p2pah_cost"] = "drift"
    sources["storefront"] = "ok" if (evidence.get("storefront") or {}).get("rows") else "missing"
    sources["fx"] = "ok" if evidence.get("fx") else "missing"
    try:
        disk = shutil.disk_usage(str(ROOT))
        disk_gb = round(disk.free / (1024 ** 3), 1)
    except OSError:
        disk_gb = None
    return {
        "api": "ok",
        "worker": "ok" if _SCHEDULER_STARTED else "missing",
        "browser": "ok" if browser_ok else "missing",
        "browser_execution": "isolated_on_demand" if pathlib.Path(WRITE_PYTHON).name == 'run_in_container.sh' else "local",
        "browser_cleanup_error": _meta_get('browser_cleanup_error'),
        "p2pah_session": _meta_get("p2pah_session", "unknown"),
        "price_writer": writer,
        "automation_timer": "active" if _SCHEDULER_STARTED else "off",
        "storefront_collection": "linked",
        "https_required": False,
        "https_certificate": {"status": "not_applicable", "expires_at": None},
        "queue_depth": len(pending),
        "incomplete_executions": len(store.incomplete_audits()),
        "tab_count": 0 if not current else 1,
        "disk_free_gb": disk_gb,
        "sources": sources,
        "last_run": _meta_get("last_run") or schedule.get("updated_at"),
        "last_successful_run": _meta_get("last_successful_run"),
        "last_snapshot_at": _meta_get("last_snapshot_at"),
        "game_id": GAME_ID,
        "write_python": WRITE_PYTHON,
        "system_enabled": bool(cfg.get("system_enabled")),
        "mode": cfg.get("mode"),
    }


def _storefront_view(evidence: dict) -> dict:
    payload = (evidence.get("storefront") or {}) or load_storefront()
    rows = dict(payload.get("rows") or {})
    checked_at = payload.get("checked_at")
    return {"source": payload.get("source"),
            "checked_at": checked_at,
            "package_k": payload.get("package_k") or QUANTITY_K,
            "collection_run_id": evidence.get("run_id") if evidence.get("storefront") else None,
            "rows": rows, "errors": payload.get("errors") or {}}


def _publication(storefront_rows: dict, audit: dict | None) -> dict:
    if not audit:
        return {"status": "no_confirmed_write", "platforms": []}
    after = {row.get("platform"): row for row in (audit.get("backend_after") or [])}
    confirmed_at = audit.get("created_at")
    rows = []
    for platform in MANAGED:
        backend = after.get(platform) or {}
        page = storefront_rows.get(platform) or {}
        b2c = store.dec(backend.get("b2c"))
        bonus = store.dec(page.get("bonus_k") or 0) if page else None
        expect = (b2c * (QUANTITY_K + (bonus or Decimal("0")))) if b2c is not None else None
        page_usd = store.dec(page.get("package_usd")) if page else None
        if expect is None or page_usd is None:
            status = "unconfirmed"
        elif not _after(page.get("checked_at"), confirmed_at):
            status = "not_checked_after_write"
        else:
            gap = abs(page_usd - expect)
            status = "matched" if gap <= Decimal("0.011") else "mismatch"
        rows.append({"platform": platform, "status": status,
                     "backend_page_usd": f"{expect:.2f}" if expect is not None else None,
                     "public_page_usd": page.get("package_usd")})
    if all(r["status"] == "matched" for r in rows):
        overall = "matched"
    elif any(r["status"] == "mismatch" for r in rows):
        overall = "mismatch"
    elif any(r["status"] == "not_checked_after_write" for r in rows):
        overall = "not_checked_after_write"
    else:
        overall = "unconfirmed"
    return {"status": overall, "platforms": rows,
            "operation_id": audit.get("id"), "confirmed_at": confirmed_at}


def _after(later: str | None, earlier: str | None) -> bool:
    a, b = store._parse(later), store._parse(earlier)
    if a is None:
        return False
    if b is None:
        return True
    return a >= b


def build_monitor() -> dict:
    evidence = _read_evidence()
    health = build_health()
    schedule = store.load_schedule()
    storefront = _storefront_view(evidence)
    jobs = _relevant_jobs()
    latest = jobs[0] if jobs else None
    attempt = None
    if latest:
        attempt = {"run_id": (latest.get("result") or {}).get("run_id") or latest["job_id"],
                   "status": latest.get("status"),
                   "kind": latest.get("kind"),
                   "created_at": latest.get("created_at")}
    collection_run_id = storefront.get("collection_run_id")
    rows = storefront.get("rows") or {}
    # 给每行补上“本轮 / 上次”语义，前端据此上色
    if attempt and attempt.get("status") == "ready" and attempt.get("run_id") == collection_run_id:
        for row in rows.values():
            row["status"] = "last_collected"
    elif rows:
        for row in rows.values():
            row.setdefault("status", "stale")
            if row["status"] not in ("unavailable",):
                row["status"] = "stale"
    storefront["rows"] = rows

    quote = store.latest_quote() or {}
    proposals = {}
    if quote.get("run_id") == evidence.get("run_id"):
        proposals = {row["platform"]: row.get("proposal")
                     for row in quote.get("rows") or []}
    competitors = []
    for platform in MANAGED:
        for site, offer in (evidence.get("offers") or {}).get(platform, {}).items():
            competitors.append({"source": site, "platform": platform,
                                "gross_usd": offer.get("list_usd"),
                                "purchase_k": offer.get("base_k"),
                                "bonus_k": offer.get("bonus_k"),
                                "effective_usd_per_k": offer.get("usd_per_1k"),
                                "price_basis": offer.get("price_basis"),
                                "comparable": offer.get("comparable", True),
                                "captured_at": offer.get("checked_at")})
    publication = _publication(rows, store.last_confirmed_audit())
    return {
        "generated_at": store.now_iso(),
        "health": health,
        "storefront": storefront,
        "latest_attempt": attempt,
        "latest_collection": ({"run_id": evidence.get("run_id"),
                               "created_at": evidence.get("checked_at"),
                               "proposals": proposals,
                               "competitors": competitors,
                               "gaps": (evidence.get("provenance") or {}).get("competitors") or []}
                              if evidence.get("run_id") else None),
        "publication": publication,
        "cost_drift": evidence.get("cost_drift") or [],
        "automation": {"schedule": schedule},
        "variants": variants_from_provenance(evidence.get("provenance") or {}),
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "MaddenQuoteCloud/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # -- helpers ------------------------------------------------------------ #
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _fail(self, exc: Exception) -> None:
        code = getattr(exc, "code", None)
        if code:
            self._json({"error": code, "detail": getattr(exc, "detail", "")}, 409)
        else:
            self._json({"error": f"{type(exc).__name__}", "detail": str(exc)[:300]}, 500)

    def _guard(self) -> bool:
        """只接受本页发起的 JSON 请求：来源闸门 + 自定义头 + 同源。"""
        if _WRITE_LOOPBACK_ONLY and not _is_loopback(self.client_address[0]):
            self._json({"error": "authentication_required",
                        "detail": "写入接口仅接受本机或反向代理转发的请求"}, 403)
            return False
        if self.headers.get("X-Requested-With") != CSRF_HEADER:
            self._json({"error": "authentication_required",
                        "detail": "缺少工作台校验头，仅允许本页发起操作"}, 403)
            return False
        return True

    # -- routes ------------------------------------------------------------- #
    def do_OPTIONS(self):  # noqa: N802 - 不回 CORS 头，跨源预检必然失败
        self._json({"error": "authentication_required"}, 405)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            page = HERE / "index.html"
            if not page.exists():
                self._send(404, b"index.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            return

        if path == "/healthz":
            self._json({"ok": True, "write_python": WRITE_PYTHON,
                        "current_job": _current_job(),
                        "queue_depth": len(_submitted_ids())})
            return

        if not path.startswith(API):
            candidate = (HERE / path.lstrip("/")).resolve()
            if HERE in candidate.parents and candidate.is_file():
                ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
                self._send(200, candidate.read_bytes(), ctype)
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        route = path[len(API):] or "/"
        try:
            if route == "/health":
                self._json(build_health())
            elif route == "/monitor":
                self._json(build_monitor())
            elif route == "/automation":
                self._json(_automation_payload())
            elif route == "/activity":
                self._json(_activity_payload(query))
            elif route.startswith("/jobs/"):
                job = store.load_job(route[len("/jobs/"):])
                self._json(job or {"error": "not_found"}, 200 if job else 404)
            elif route.startswith("/quotes/"):
                quote = store.load_quote(route[len("/quotes/"):])
                self._json(quote or {"error": "not_found"}, 200 if quote else 404)
            elif route.startswith("/previews/"):
                preview = store.load_preview(route[len("/previews/"):])
                self._json(preview or {"error": "preview_expired"}, 200 if preview else 404)
            elif route.startswith("/restore-previews/"):
                preview = store.load_restore_preview(route[len("/restore-previews/"):])
                self._json(preview or {"error": "restore_preview_expired"},
                           200 if preview else 404)
            elif route.startswith("/audits/"):
                audit = store.load_audit(route[len("/audits/"):])
                if not audit:
                    self._json({"error": "not_found"}, 404)
                    return
                targets = audit.get("targets") or {}
                self._json({"id": audit.get("id"), "status": audit.get("status"),
                            "stage": audit.get("stage"), "actor": audit.get("actor"),
                            "created_at": audit.get("created_at"),
                            "selected": sorted(targets),
                            "changed": audit.get("changed") or [],
                            "sync": audit.get("sync"),
                            "mismatches": audit.get("mismatches"),
                            "error": audit.get("error"),
                            "operator_reason": audit.get("operator_reason"),
                            "low_margin_platforms": audit.get("low_margin_platforms") or [],
                            "restore_source": audit.get("restore_source"),
                            "targets": targets,
                            "backend_after": audit.get("backend_after") or []})
            else:
                self._json({"error": "not_found"}, 404)
        except Exception as exc:  # noqa: BLE001 - 前端要看到原因
            self._fail(exc)

    def do_POST(self):  # noqa: N802
        if not self._guard():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith(API):
            self._json({"error": "not_found"}, 404)
            return
        route = path[len(API):] or "/"
        payload = self._body()
        try:
            self._post(route, payload)
        except JobError as exc:
            self._json({"error": exc.code, "detail": exc.detail}, 409)
        except store.RevisionConflict as exc:
            self._json({"error": "automation_revision_changed", "detail": str(exc)}, 409)
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)

    def _post(self, route: str, payload: dict) -> None:
        if route == "/collect":
            job = _submit("collect", {"requested_at": store.now_iso()},
                          _runner_collect)
            self._json({"job_id": job["job_id"], "run_id": job["job_id"]}, 202)
            return

        if route == "/reprice/preview":
            run_id = str(payload.get("run_id") or "")
            if not run_id:
                raise JobError("not_found", "缺少 run_id")
            _load_quote_for(run_id)                 # 先校验，尽早给出错误码
            job = _submit("preview", {"run_id": run_id}, _runner_preview)
            self._json({"job_id": job["job_id"], "run_id": run_id}, 202)
            return

        if route == "/reprice/recalculate":
            run_id = str(payload.get("run_id") or "")
            if not run_id:
                raise JobError("not_found", "缺少 run_id")
            edits = payload.get("edits") or {}
            if not isinstance(edits, dict):
                raise JobError("quote_not_ready", "edits 格式无效")
            job = _submit("recalculate", {"run_id": run_id, "edits": edits},
                          _runner_recalculate)
            self._json({"job_id": job["job_id"], "run_id": run_id}, 202)
            return

        if route == "/reprice/execute":
            preview_id = str(payload.get("preview_id") or "")
            if not preview_id:
                raise JobError("preview_expired", "缺少 preview_id")
            if not store.load_preview(preview_id):
                raise JobError("preview_expired")
            job = _submit("execute", {
                "preview_id": preview_id,
                "selected_platforms": payload.get("selected_platforms") or [],
                "margin_confirmed_platforms": payload.get("margin_confirmed_platforms") or [],
                "margin_exception_reason": payload.get("margin_exception_reason") or "",
                "client_event_id": payload.get("client_event_id") or store.new_id(),
            }, _runner_execute)
            self._json({"job_id": job["job_id"],
                        "operation_id": job["request"]["client_event_id"]}, 202)
            return

        if route == "/automation":
            self._save_automation(payload)
            return

        if route == "/activity/retain":
            event_id = str(payload.get("id") or "")
            if not event_id:
                raise JobError("activity_mark_invalid", "缺少日志编号")
            store.set_mark(event_id, bool(payload.get("retained")))
            self._json({"ok": True, "id": event_id,
                        "retained": bool(payload.get("retained"))})
            return

        parts = [p for p in route.split("/") if p]
        # /reprice/<source>/restore/preview 与 /reprice/<source>/restore
        if len(parts) == 4 and parts[0] == "reprice" and parts[1] and parts[2] == "restore" \
                and parts[3] == "preview":
            source = parts[1]
            audit = store.load_audit(source)
            if not audit:
                raise JobError("restore_preview_unavailable", "找不到该操作编号的审计")
            if audit.get("status") not in ("CONFIRMED", "RESTORED"):
                raise JobError("restore_source_not_confirmed")
            job = _submit("restore_preview", {"source_execution_id": source},
                          _runner_restore_preview)
            self._json({"job_id": job["job_id"], "source_execution_id": source}, 202)
            return
        if len(parts) == 3 and parts[0] == "reprice" and parts[1] and parts[2] == "restore":
            source = parts[1]
            preview = store.load_restore_preview(str(payload.get("restore_preview_id") or ""))
            if not preview:
                raise JobError("restore_preview_expired")
            job = _submit("restore", {
                "source_execution_id": source,
                "restore_preview_id": payload.get("restore_preview_id"),
                "selected_platforms": payload.get("selected_platforms") or [],
                "client_event_id": payload.get("client_event_id") or store.new_id(),
            }, _runner_restore)
            self._json({"job_id": job["job_id"],
                        "operation_id": job["request"]["client_event_id"]}, 202)
            return

        self._json({"error": "not_found"}, 404)

    # -- 自动化控制台 -------------------------------------------------------- #
    def _save_automation(self, payload: dict) -> None:
        settings = payload.get("settings") or {}
        if not isinstance(settings, dict):
            raise JobError("automation_storage_unavailable", "settings 格式无效")
        margin = str(settings.get("minimum_gross_margin_pct") or "").strip()
        if not margin or not _decimal_ok(margin, 2, Decimal("0"), Decimal("100")):
            raise JobError("minimum_margin_invalid")
        try:
            interval = int(settings.get("interval_minutes"))
        except (TypeError, ValueError) as exc:
            raise JobError("automation_interval_invalid") from exc
        if not 1 <= interval <= 9999:
            raise JobError("automation_interval_invalid")
        platforms = [p for p in (settings.get("platforms") or []) if p in MANAGED]
        if not platforms:
            platforms = []
        before = store.load_config()
        after = store.save_config(
            {"system_enabled": bool(settings.get("system_enabled")),
             "mode": "auto" if settings.get("mode") == "auto" else "manual",
             "interval_minutes": interval,
             "platforms": platforms,
             "minimum_gross_margin_pct": margin},
            expected_revision=payload.get("expected_revision"),
            actor="local")
        _log_event("automation_config", actor="local",
                   request={"settings": {"system_enabled": after["system_enabled"],
                                         "mode": after["mode"],
                                         "interval_minutes": after["interval_minutes"],
                                         "platforms": after["platforms"],
                                         "minimum_gross_margin_pct": after["minimum_gross_margin_pct"]}},
                   result={"revision": after["revision"]},
                   config_change=store.config_change_event(before, after))
        if after.get("mode") == "auto" and after.get("system_enabled"):
            now = datetime.now(timezone.utc)
            next_at = _next_after_settings(before, after,
                                           _last_auto_job(store.load_schedule()) or {}, now)
            store.save_schedule({"status": "waiting" if next_at > now else "due",
                                 "next_at": next_at.isoformat(timespec="seconds"),
                                 "last_error": None})
        else:
            store.save_schedule({"status": _schedule_state(after),
                                 "next_at": None, "last_error": None})
        self._json(_automation_payload())


def _decimal_ok(text: str, places: int, low: Decimal, high: Decimal) -> bool:
    import re
    if not re.fullmatch(rf"\d+(?:\.\d{{1,{places}}})?", text):
        return False
    value = Decimal(text)
    return low <= value < high


def _automation_payload() -> dict:
    cfg = store.load_config()
    schedule = store.load_schedule()
    state = _schedule_state(cfg)
    if state != "auto":
        schedule = dict(schedule)
        schedule["status"] = state
        schedule["next_at"] = None
    payload = {"revision": cfg.get("revision"),
               "pricing_revision": cfg.get("pricing_revision") or cfg.get("revision"),
               "system_enabled": bool(cfg.get("system_enabled")),
               "mode": cfg.get("mode") or "manual",
               "interval_minutes": int(cfg.get("interval_minutes") or 60),
               "platforms": list(cfg.get("platforms") or []),
               "minimum_gross_margin_pct": str(cfg.get("minimum_gross_margin_pct")),
               "basis": cfg.get("basis"),
               "fx": str(cfg.get("fx")),
               "profit": str(cfg.get("profit")),
               "updated_by": cfg.get("updated_by"),
               "updated_at": cfg.get("updated_at"),
               "schedule": schedule}
    return payload


def _activity_payload(query: dict) -> dict:
    limit = 200
    try:
        limit = min(500, max(1, int((query.get("limit") or [200])[0])))
    except (TypeError, ValueError):
        pass
    day = (query.get("date") or [None])[0] or None
    if day:
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError as exc:
            raise JobError("activity_date_invalid") from exc
    return {"current_user": "local",
            "generated_at": store.now_iso(),
            "events": store.activity_events(limit=limit, day=day),
            "warnings": []}


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def _reap_interrupted_jobs() -> int:
    """服务重启后把「执行中」的孤儿任务收尾，否则自动跟价会永久卡住。

    根因：`_CURRENT` / `_PENDING` 只在内存里，服务一重启它们就没了，
    而作业文件还停在 `running`。`_scheduler_tick` 看到上一轮任务仍是
    queued/running 就一直写 `in_progress` 并 return，`_watch_schedule_results`
    也因为 job 还在 running 而直接跳过 —— 于是**永远不会再跑下一轮**，
    页面上也看不到任何报错（2026-10-08 部署重启时实测踩到）。

    处理：把孤儿任务标成失败（错误码 service_restarted，日志里显示「已中断」），
    并把调度状态复位成 waiting + 清空 next_at —— 下一个 tick 会立刻补跑一轮，
    不等满一个间隔。业务失败（采集失败等）的暂停语义不受影响。
    """
    reaped = 0
    stale_ids = []
    for job in store.list_jobs(limit=400):
        if job.get("status") in ("queued", "running"):
            stale_ids.append(job["job_id"])
            _update(job["job_id"], status="failed", stage="interrupted",
                    error_detail="service_restarted",
                    error="服务重启，本轮任务中断，未写入任何价格",
                    completed_at=store.now_iso())
            reaped += 1
    if not reaped:
        return 0
    schedule = store.load_schedule()
    patch = {"status": "waiting", "last_error": "服务重启，本轮已中断，已安排补跑",
             "last_result_checked": schedule.get("last_job_id"), "next_at": None}
    store.save_schedule(patch)
    _log_event("reap_interrupted", actor="system",
               request={"job_ids": stale_ids}, result={"reaped": reaped})
    return reaped


def start_background() -> None:
    global _SCHEDULER_STARTED
    try:
        reaped = _reap_interrupted_jobs()
        if reaped:
            print(f"！发现 {reaped} 个被服务重启中断的任务，已收尾并安排补跑")
    except Exception as exc:  # noqa: BLE001 - 自愈失败也不能阻止服务启动
        print(f"！中断任务清理失败（不影响服务）：{type(exc).__name__}: {exc}")
    threading.Thread(target=_worker_loop, daemon=True, name="madden-jobs").start()
    threading.Thread(target=_scheduler_loop, daemon=True, name="madden-scheduler").start()
    _SCHEDULER_STARTED = True


def main() -> None:
    print(f"{GAME_NAME} Coins 竞品报价工作台  ->  http://{HOST}:{PORT}/")
    print(f"证据目录  : {EVIDENCE}")
    print(f"写价解释器: {WRITE_PYTHON}")
    if not pathlib.Path(WRITE_PYTHON).exists():
        print("！该解释器不存在，采集与改价会失败；可用 MADDEN_WRITE_PYTHON 指定")
    print(f"后台 gid  : {GAME_ID}  价格行 {PRICE_ROW_IDS}")
    print("Ctrl+C 退出")
    start_background()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
