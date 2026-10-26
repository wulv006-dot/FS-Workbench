"""Authenticated local API for FC27 server jobs and review artifacts."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit
import uuid

from automation_policy import load_policy, save_policy, save_discount_rules
from server_quote_job import preview_discount_rules
from fc27_quote_engine import source_coverage
from automation_tick import latest_cycle, due, player_sync_gate, retry_plan, queue_mutation, QueueBusy, sync_directory, player_price_readback_waived
from player_sync_policy import load_policy as load_player_sync_policy, save_policy as save_player_sync_policy
import activity_log_store
import local_collection


ROOT = Path("/var/lib/fc27-cloud")
APP = Path("/opt/fc27-cloud-browser")
WRITE_ENABLE_FILE = Path("/etc/fc27-cloud/write-enabled")
WRITERS = {name.strip() for name in os.environ.get("FC27_CLOUD_WRITERS", "wulv,chenchao,DY").split(",") if name.strip()}
ID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _without_replay_paths(value):
    if isinstance(value, dict):
        return {key: _without_replay_paths(item) for key, item in value.items() if key not in {"paths", "replay_paths"}}
    if isinstance(value, list):
        return [_without_replay_paths(item) for item in value]
    return value


def public_artifact(payload, include_quote_sha=False):
    evidence = payload.get("evidence") if isinstance(payload, dict) else None
    if isinstance(evidence, dict):
        safe = {key: value for key, value in evidence.items() if key != "historical_orders"}
        if isinstance(safe.get("history_replay"), dict):
            safe["history_replay"] = _without_replay_paths(safe["history_replay"])
        for collection in ("region_rules", "regional_controls"):
            if isinstance(safe.get(collection), list):
                safe[collection] = [dict(row, history={key: value for key, value in row["history"].items() if key != "replay_paths"})
                    if isinstance(row, dict) and isinstance(row.get("history"), dict) else row
                    for row in safe[collection]]
        result = dict(payload, evidence=safe)
        if include_quote_sha:
            result["original_quote_sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return result
    return payload


def valid_id(value):
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def read_json(path):
    # Writers publish atomically, then restore the existing read group/mode.
    # Briefly retry that read window; persistent denial remains a real error.
    delays = (0.02, 0.05, 0.10)
    for attempt in range(len(delays) + 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def exclusive_json(path, payload):
    path.parent.mkdir(mode=0o2770, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())


def certificate_health():
    path = ROOT / "state/https-certificate.json"
    result = {"status": "missing", "expires_at": None}
    if not path.exists():
        return result
    try:
        payload = read_json(path)
        checked = datetime.fromisoformat(payload["checked_at"])
        expires = datetime.fromisoformat(payload["expires_at"])
        result["expires_at"] = expires.isoformat()
        if payload.get("status") != "ok":
            result["status"] = "renewal_failed"
        elif datetime.now(timezone.utc) - checked > timedelta(hours=26):
            result["status"] = "check_stale"
        elif expires <= datetime.now(timezone.utc) + timedelta(days=2):
            result["status"] = "expiring"
        else:
            result["status"] = "ok"
    except (OSError, ValueError, KeyError, TypeError):
        result["status"] = "invalid"
    return result


def writer_status():
    if not (APP / "execute_price.sh").exists():
        return "missing"
    if not WRITE_ENABLE_FILE.exists():
        return "https_required"
    return "ready" if certificate_health()["status"] == "ok" else "certificate_unhealthy"


def health():
    result = {"api": "ok", "worker": "missing", "browser": "missing",
              "p2pah_session": "missing", "last_run": None,
              "price_writer": writer_status(),
              "https_certificate": certificate_health(),
              "queue_depth": 0, "tab_count": None, "disk_free_gb": None,
              "sources": {name: "missing" for name in ("lootbar", "iggm", "u4gm", "u7buy", "p2pah_cost", "fx")},
              "last_successful_run": None, "incomplete_executions": 0}
    result['queue_protocol'] = 'existing-tick-inode-v4'
    result['api_pid'] = os.getpid()
    heartbeat = ROOT / "state/worker-heartbeat.json"
    if heartbeat.exists():
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(read_json(heartbeat)["at"])
            result["worker"] = "ok" if age.total_seconds() <= 15 else "stale"
        except (OSError, ValueError, KeyError):
            pass
    for key, url in (("browser", "http://127.0.0.1:9225/json/version"),
                     ("p2pah_session", "http://127.0.0.1:8767/health")):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.load(response)
                if key == "p2pah_session":
                    result[key] = "ok" if payload.get("ready") else "missing"
                else:
                    result[key] = "ok" if payload.get("Browser") else "missing"
        except (OSError, ValueError):
            pass
    result['order_session'] = 'missing'
    try:
        with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=8) as response:
            if json.load(response).get('ready'):
                result['order_session'] = 'ok'
    except (OSError, ValueError):
        pass
    if result['order_session'] != 'ok':
        result['p2pah_session'] = 'missing'
    runs = [path for path in (ROOT / "runs").glob("*.json") if valid_id(path.stem)]
    if runs:
        last = max(runs, key=lambda p: p.stat().st_mtime)
        payload = read_json(last)
        result["last_run"] = {"run_id": payload.get("run_id"),
                              "status": payload.get("status"),
                              "created_at": payload.get("created_at")}
        if payload.get("status") == "ready_for_quote":
            source_names = {"Lootbar": "lootbar", "IGGM": "iggm", "U4GM": "u4gm", "U7Buy": "u7buy"}
            for source, key in source_names.items():
                matches = [row for row in payload.get("competitors", []) if row.get("source") == source]
                result["sources"][key] = "ok" if len(matches) == 3 and all(row.get("status") == "valid" for row in matches) else "missing"
            costs = payload.get("costs", [])
            result["sources"]["p2pah_cost"] = "ok" if len(costs) == 3 and all(row.get("status") == "valid" for row in costs) else "missing"
            result["sources"]["fx"] = "ok" if payload.get("fx", {}).get("status") == "valid" else "missing"
        successful = [path for path in runs if read_json(path).get("status") == "ready_for_quote"]
        if successful:
            result["last_successful_run"] = read_json(max(successful, key=lambda p: p.stat().st_mtime)).get("created_at")
    result["queue_depth"] = len(list((ROOT / "queue").glob("*.json")))
    try:
        with urllib.request.urlopen("http://127.0.0.1:9225/json", timeout=2) as response:
            result["tab_count"] = len([tab for tab in json.load(response) if tab.get("type") == "page"])
    except (OSError, ValueError):
        pass
    result["disk_free_gb"] = round(shutil.disk_usage(ROOT).free / (1024 ** 3), 2)
    for path in (ROOT / "executions").glob("*.json"):
        try:
            if read_json(path).get("status") in {"RUNNING", "UNCERTAIN", "PARTIAL"}:
                result["incomplete_executions"] += 1
        except (OSError, ValueError):
            result["incomplete_executions"] += 1
    return result


def automation_view(policy, actor=None):
    policy={**policy,'can_edit_discount_rules':False,'can_manage_v3':actor in WRITERS}
    from fc_pricing_v3.monitoring import projection
    v3=projection(ROOT)
    if v3['enabled']:return dict(policy,schedule=v3['schedule'],v3=v3)
    try:
        last = latest_cycle()
        collection_status = due(policy, last)
        retry = retry_plan(policy, last)
        status = collection_status
        if policy["system_enabled"] and policy["mode"] == "auto":
            gate = player_sync_gate()
            if gate != "ready":
                status = "player_sync_" + gate
    except (OSError, ValueError, KeyError, TypeError):
        return {**policy, "schedule": {"status": "unavailable", "last_job_id": None,
                                        "last_status": None, "last_result": None,
                                        "last_error": None, "next_at": None}}
    next_at = None
    if retry:
        next_at = retry["next_at"]
    if last and collection_status == "waiting":
        finished = datetime.fromisoformat(last.get("completed_at") or last["created_at"])
        next_at = (finished + timedelta(minutes=policy["interval_minutes"])).isoformat()
    return {**policy, "schedule": {"status": status, "collection_status": collection_status,
                                    "last_job_id": last.get("job_id") if last else None,
                                    "last_status": last.get("status") if last else None,
                                    "last_result": (last.get("result") or {}).get("status") if last else None,
                                    "last_error": (last.get("error_detail") or last.get("error")) if last else None,
                                    "next_at": next_at, "collection_retry": retry}}


def player_sync_view(policy):
    paths = list((ROOT / "jobs").glob("*.json")) + list((ROOT / "queue").glob("*.json"))
    jobs = []
    for path in paths:
        try:
            row = read_json(path)
            if row.get("kind") == "player_sync":
                jobs.append(row)
        except (OSError, ValueError):
            continue
    latest = max(jobs, key=lambda row: row.get("created_at") or "") if jobs else None
    progress = None
    if latest:
        progress_path = ROOT / "player-sync" / (latest["job_id"] + ".json")
        if progress_path.exists():
            try:
                progress = read_json(progress_path)
            except (OSError, ValueError):
                progress = {"status": "unavailable"}
    return {**policy, "price_verification": "disabled",
            "price_verification_waived": bool(latest and player_price_readback_waived(latest)),
            "last_job": ({"job_id": latest.get("job_id"),
                                     "status": latest.get("status"),
                                     "config_revision": (latest.get("request") or {}).get("config_revision"),
                                     "result": (latest.get("result") or latest.get("sync_result") or {}).get("status"),
                                     "error": latest.get("error") or latest.get("error_detail"),
                                     "completed_at": latest.get("completed_at"),
                                     "progress": ({key: progress.get(key) for key in (
                                         "status", "mode", "model_count", "verified_count",
                                         "sample_count", "sample_verified_count", "active_model_id",
                                         "last_verified_model_id", "updated_at", "completed_at")}
                                          if progress else None)}
                                    if latest else None)}


def latest_complete_collection():
    paths = sorted((path for path in (ROOT / "runs").glob("*.json") if valid_id(path.stem)),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    last_attempt = None
    for path in paths:
        try:
            run = read_json(path)
            if last_attempt is None:
                last_attempt = {"run_id": run.get("run_id"), "status": run.get("status"),
                                "created_at": run.get("created_at"), "reason": run.get("reason")}
            competitors = run.get("competitors") or []
            costs = run.get("costs") or []
            coverage = source_coverage(competitors)
            if (run.get("status") != "ready_for_quote" or not coverage["ready"]
                    or len(costs) != 3 or any(row.get("status") != "valid" for row in costs)):
                continue
            run_id = run.get("run_id")
            quote_path = ROOT / "quotes" / f"{run_id}.json"
            quote = read_json(quote_path) if valid_id(run_id) and quote_path.exists() else {}
            proposals = {}
            if quote.get("run_id") == run_id and quote.get("status") in {"ready_for_preview", "margin_review_required"}:
                proposals = {row["platform"]: row.get("proposal") for row in quote.get("result", {}).get("rows", [])
                             if row.get("platform") in {"PS", "XBOX", "PC"}}
            return last_attempt, {"run_id": run_id, "created_at": run.get("created_at"),
                                  "unavailable_sources": coverage["unavailable_sources"],
                                  "reference_sources": coverage["reference_sources"],
                                  "source_warnings": run.get("source_warnings", []),
                                  "competitors": [{key: row.get(key) for key in
                                                   ("platform", "source", "gross_usd", "purchase_k", "bonus_k",
                                                    "effective_usd_per_k", "captured_at", "comparable", "conditional", "url", "status")}
                                                  for row in competitors if row.get("status") == "valid"],
                                  "costs": [{key: row.get(key) for key in
                                             ("platform", "cny_per_1k", "checked_at", "trade_at")}
                                            for row in costs],
                                  "proposals": proposals,
                                  "quote_created_at": quote.get("created_at") if proposals else None}
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return last_attempt, None


def publication_view(storefront):
    """Compare the latest observed backend prices at public-page cent precision."""
    audits = []
    for path in (ROOT / "executions").glob("*.json"):
        if not valid_id(path.stem):
            continue
        try:
            audit = read_json(path)
            checked = datetime.fromisoformat(str(audit.get('created_at', '')).replace('Z', '+00:00'))
            if (audit.get("status") == "CONFIRMED" and audit.get("sync_confirmed") is True
                    and valid_id(audit.get("execution_id")) and checked.tzinfo is not None):
                audits.append(audit)
        except (OSError, ValueError, TypeError):
            continue
    written_at = max((row['created_at'] for row in audits), default=None)
    # Read-only previews validate the live game/platform/site filters before persisting.
    for path in (ROOT / 'previews').glob('*.json'):
        if not valid_id(path.stem):
            continue
        try:
            preview = read_json(path)
            backend = preview.get('backend_before') or {}
            checked = datetime.fromisoformat(preview['created_at'].replace('Z', '+00:00'))
            if (preview.get('preview_id') != path.stem or not valid_id(preview.get('run_id'))
                    or preview.get('status') != 'review_only' or checked.tzinfo is None
                    or (datetime.now(timezone.utc) - checked).total_seconds() < 0
                    or backend.get('gameId') != '1322' or backend.get('isRoute') is not True
                    or backend.get('login') is not False or backend.get('allServerChecked') is not False
                    or backend.get('selectedWebsites') != 0 or backend.get('b2cSelected') is not True
                    or backend.get('origin') != 'https://order.p2pah.cn'):
                continue
            audits.append({'execution_id': None, 'preview_id': path.stem,
                           'created_at': preview['created_at'], 'after': backend,
                           'basis': 'backend_preview'})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if not audits:
        return {"status": "no_confirmed_write", "platforms": []}
    latest = max(audits, key=lambda row: datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')))
    if latest.get('basis')=='backend_preview':
        # A later unchanged observation does not erase the confirmed write identity.
        observed=latest
        def same_prices(a,b):
            try:
                left={r['platform']:(str(r['id']),Decimal(r['costPrice']),Decimal(r['lirunlv']),Decimal(r['b2c'])) for r in a['after']['rows']}
                right={r['platform']:(str(r['id']),Decimal(r['costPrice']),Decimal(r['lirunlv']),Decimal(r['b2c'])) for r in b['after']['rows']}
                return len(a['after']['rows'])==len(b['after']['rows'])==3 and set(left)=={'PS','XBOX','PC'} and left==right and a['after']['exchangeRate']==b['after']['exchangeRate']
            except (KeyError,TypeError,InvalidOperation):return False
        matches=[a for a in audits if a.get('status')=='CONFIRMED' and a['created_at']<=observed['created_at'] and same_prices(a,observed)]
        if matches:
            latest=dict(max(matches,key=lambda a:a['created_at']),basis='confirmed_write_and_matching_backend_preview',
                        observed_at=observed['created_at'],observation_preview_id=observed['preview_id'])
    execution_id = latest["execution_id"]
    try:
        after = {row["platform"]: row for row in latest["after"]["rows"]}
        if set(after) != {"PS", "XBOX", "PC"} or len(latest['after']['rows']) != 3:
            raise ValueError("backend_rows_incomplete")
        details = []
        for platform in ("PS", "XBOX", "PC"):
            row = (storefront.get("rows") or {}).get(platform) or {}
            backend = (Decimal(str(after[platform]["b2c"])) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if not backend.is_finite() or backend <= 0:
                raise ValueError("backend_price_invalid")
            checked = row.get("checked_at")
            public = Decimal(str(row["package_usd"])) if row.get("status") == "ok" else None
            state = ("unavailable" if not checked or public is None or not public.is_finite()
                     else "not_checked_after_write" if written_at and datetime.fromisoformat(checked.replace('Z', '+00:00')) < datetime.fromisoformat(written_at.replace('Z', '+00:00'))
                     else "matched" if public == backend else "mismatch")
            details.append({"platform": platform, "status": state,
                            "backend_page_usd": str(backend.quantize(Decimal("0.01"))),
                            "public_page_usd": str(public) if public is not None else None,
                            "public_checked_at": checked})
        status = ("mismatch" if any(row["status"] == "mismatch" for row in details)
                  else "unavailable" if any(row["status"] == "unavailable" for row in details)
                  else "not_checked_after_write" if any(row["status"] == "not_checked_after_write" for row in details)
                  else "matched")
        return {"status": status, "execution_id": execution_id,
                "basis": latest.get('basis', 'confirmed_write'), "preview_id": latest.get('preview_id'),
                "backend_checked_at": latest.get('observed_at',latest['created_at']),
                "observation_preview_id": latest.get('observation_preview_id'),
                "write_mode": ("manual" if latest.get("automatic") is False else
                               "automatic" if latest.get("automatic") is True else "unknown"),
                "backend_written_at": None if latest.get('basis') == 'backend_preview' else latest["created_at"], "platforms": details}
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return {"status": "evidence_incomplete", "execution_id": execution_id, "platforms": []}


def monitor_view():
    current_time = datetime.now(timezone.utc)
    try:
        storefront = read_json(ROOT / "monitor/storefront.json")
    except (OSError, ValueError, TypeError):
        storefront = {"status": "unavailable", "last_attempt_at": None, "rows": {}}
    rows = {}
    for platform in ("PS", "XBOX", "PC"):
        row = (storefront.get("rows") or {}).get(platform) or {}
        status = ("last_collected" if row.get("status") == "ok" and row.get("package_usd") is not None
                  and row.get("checked_at") else "unavailable" if row.get("package_usd") is not None
                  else "missing")
        rows[platform] = {key: row.get(key) for key in
                          ("package_usd", "base_k", "bonus_k", "usd_per_k", "checked_at", "sku_id")}
        rows[platform]["status"] = status
    try:
        timer = subprocess.run(["systemctl", "is-active", "fc-pricing-v3.service"],
                               capture_output=True, text=True, timeout=2)
        timer_status = timer.stdout.strip() if timer.stdout.strip() in {"active", "inactive", "failed"} else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        timer_status = "unknown"
    last_attempt, collection = latest_complete_collection()
    cycle = latest_cycle()
    page_readback = (cycle or {}).get("public_page_readback") or {}
    cache_jobs = []
    for path in (ROOT / "jobs").glob("*.json"):
        try:
            job = read_json(path)
            if job.get("kind") in {"auto_cycle", "execute"} and job.get("cache_refresh"):
                cache_jobs.append(job)
        except (OSError, ValueError, TypeError):
            continue
    cache_job = max(cache_jobs, key=lambda row: row.get("created_at", "")) if cache_jobs else {}
    try:
        player_sync = player_sync_view(load_player_sync_policy())
    except (OSError, ValueError, TypeError):
        player_sync = {"enabled": None, "revision": None, "last_job": None}
    return {"generated_at": current_time.isoformat(),
            "storefront": {"status": storefront.get("status", "unavailable"),
                           "last_attempt_at": storefront.get("last_attempt_at"), "rows": rows,
                           "collection_run_id": storefront.get("collection_run_id"),
                           "source": "https://www.mmoexp.com/Fc-27/Coins.html",
                           "locale": "US/USD public page", "package_k": 100},
            "latest_attempt": last_attempt, "latest_collection": collection,
            "page_readback": {"status": page_readback.get("status"),
                              "checked_at": page_readback.get("checked_at"),
                              "run_id": (cycle or {}).get("job_id")},
            "cache_refresh": {"status": (cache_job.get("cache_refresh") or {}).get("status"),
                              "checked_at": (cache_job.get("cache_refresh") or {}).get("checked_at"),
                              "reason": (cache_job.get("cache_refresh") or {}).get("reason")},
            "publication": publication_view(storefront),
            "automation": automation_view(load_policy()),
            "player_sync": player_sync,
            "health": {**health(), "automation_timer": timer_status,
                       "storefront_collection": "linked"}}


def activity_changes(job, audit):
    kind = job.get("kind")
    selected = (audit or {}).get("selected") or job.get("request", {}).get("platforms") or []
    if kind not in {"execute", "auto_cycle", "restore"} or not isinstance(selected, list):
        return []
    before_rows = {row.get("platform"): row for row in (audit or {}).get("before", {}).get("rows", [])
                   if isinstance(row, dict)}
    after_rows = {row.get("platform"): row for row in (audit or {}).get("after", {}).get("rows", [])
                  if isinstance(row, dict)}
    targets = {row.get("platform"): row for row in (audit or {}).get("targets", [])
               if isinstance(row, dict)}
    changes = []
    for platform in selected:
        if platform not in {"PS", "XBOX", "PC"}:
            continue
        before, after, target = before_rows.get(platform, {}), after_rows.get(platform, {}), targets.get(platform, {})
        changes.append({"platform": platform,
                        "before_cost": before.get("costPrice"), "before_b2c": before.get("b2c"),
                        "target_cost": target.get("targetCost") if kind in {"execute", "auto_cycle"} else target.get("restore_cost"),
                        "target_b2c": target.get("quote") if kind in {"execute", "auto_cycle"} else target.get("restore_b2c"),
                        "after_cost": after.get("costPrice"), "after_b2c": after.get("b2c")})
    return changes


def cloud_activity(limit):
    paths = list((ROOT / "jobs").glob("*.json")) + list((ROOT / "queue").glob("*.json"))
    def modified(path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0
    paths.sort(key=modified, reverse=True)
    events, skipped = [], 0
    for path in paths[:max(limit * 2, 200)]:
        try:
            job = read_json(path)
            if not valid_id(job.get("job_id")) or job["job_id"] != path.stem:
                raise ValueError("job_id_invalid")
            kind = job.get("kind")
            if kind not in {"collect", "auto_cycle", "preview", "recalculate", "execute", "restore_preview", "restore", "player_sync"}:
                continue
            audit_path = ROOT / "executions" / f"{job['job_id']}.json"
            audit = read_json(audit_path) if kind in {"execute", "auto_cycle", "restore"} and audit_path.exists() else None
            request = job.get("request") or {}
            edits = (request.get("edits") or {}) if kind == "recalculate" else {}
            changed_quotes = edits.get("quotes") or {} if isinstance(edits, dict) else {}
            events.append({"id": job["job_id"], "source": "cloud",
                           "at": job.get("completed_at") or job.get("started_at") or job.get("created_at"),
                           "user": job.get("actor"), "kind": kind,
                           "status": (audit or {}).get("status") or job.get("status"),
                           "job_status": job.get("status"),
                           "stage": (audit or {}).get("stage"),
                           "run_id": (audit or {}).get("run_id") or request.get("run_id") or
                                     (job.get("result") or {}).get("run_id") or
                                     (job["job_id"] if kind == "collect" else None),
                           "source_execution_id": (audit or {}).get("source_execution_id") or request.get("source_execution_id"),
                           "platforms": (audit or {}).get("selected") or request.get("platforms") or [],
                           "quote_edits": {key: changed_quotes[key] for key in ("PS", "XBOX", "PC")
                                           if isinstance(changed_quotes, dict) and key in changed_quotes},
                           "cycle_status": (job.get("result") or {}).get("status") if kind == "auto_cycle" else None,
                           "blocked_platforms": (job.get("result") or {}).get("blocked_platforms") or job.get("blocked_platforms") or {},
                           "operator_reason": (audit or {}).get("operator_reason"),
                           "low_margin_platforms": (audit or {}).get("low_margin_platforms") or [],
                           "changes": activity_changes(job, audit),
                           "error": (audit or {}).get("error") or job.get("error_detail") or job.get("error")})
        except (OSError, ValueError, TypeError, KeyError):
            skipped += 1
    return events[:limit], skipped


def legacy_activity(actor, limit):
    request = urllib.request.Request(f"http://127.0.0.1:8878/events?limit={limit}",
                                     headers={"X-Authenticated-User": actor})
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.load(response)
    events = []
    for raw in payload.get("events", []):
        changes = raw.get("changes") or []
        events.append({"id": str(raw.get("id")), "source": "legacy", "at": raw.get("at"),
                       "user": raw.get("user"), "kind": raw.get("event_type"),
                       "status": raw.get("status"), "stage": None,
                       "run_id": raw.get("run_id"), "attempt_id": raw.get("attempt_id"),
                       "source_execution_id": None,
                       "platforms": raw.get("platforms") or [], "quote_edits": {},
                       "changes": [{key: item.get(key) for key in (
                           "platform", "before_cost", "before_b2c", "target_cost", "target_b2c",
                           "after_cost", "after_b2c")} for item in changes if isinstance(item, dict)],
                       "error": None})
    return events


def automation_config_activity(limit):
    path = ROOT / "config/automation-events.jsonl"
    if not path.exists():
        return []
    rows = path.read_text(encoding="utf-8").splitlines()[-limit:]
    events = []
    for line in rows:
        raw = json.loads(line)
        before, after = raw["before"], raw["after"]
        events.append({"id": "config-" + str(raw["revision"]), "source": "cloud",
                       "at": raw["at"], "user": raw["actor"], "kind": "automation_config",
                       "status": "ready", "stage": None, "run_id": None,
                       "platforms": after["platforms"], "quote_edits": {}, "changes": [],
                       "config_change": {"before_enabled": before["system_enabled"],
                                         "after_enabled": after["system_enabled"],
                                         "before_mode": before["mode"], "after_mode": after["mode"],
                                         "revision": raw["revision"],
                                          "before_pricing_rules": before.get("pricing_rules"),
                                          "after_pricing_rules": after.get("pricing_rules")}, "error": None})
    return events


def activity_feed(actor, limit=100, day=None, now=None, deep=False):
    source_limit = 10000 if deep else 500
    cloud, skipped = cloud_activity(source_limit)
    warnings = []
    if skipped:
        warnings.append(f"cloud_records_unreadable:{skipped}")
    try:
        cloud += automation_config_activity(source_limit)
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append("automation_config_history_unavailable")
    try:
        legacy = legacy_activity(actor, 200)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        legacy = []
        warnings.append("legacy_journal_unavailable")
    captured = activity_log_store.capture(cloud + legacy, now=now)
    if captured["skipped"]:
        warnings.append(f"activity_copy_skipped:{captured['skipped']}")
    selected = activity_log_store.query(limit, day=day, now=now)
    return {"current_user": actor, **selected, "warnings": warnings,
            "retention_days": activity_log_store.KEEP_DAYS}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def actor(self):
        name = self.headers.get("X-Authenticated-User", "").strip()
        return name if re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", name) else None

    def body(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("content_type_invalid")
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and origin not in {"http://" + host, "https://" + host}:
            raise ValueError("origin_invalid")
        length = int(self.headers.get("Content-Length", "0"))
        limit = 65536 if urlsplit(self.path).path == "/local-collection/submit" else 4096
        if not 0 < length <= limit:
            raise ValueError("request_size_invalid")
        return json.loads(self.rfile.read(length))

    def enqueue(self, kind, actor, payload, job_id=None, *, idempotent=False):
        job_id = job_id or str(uuid.uuid4())
        record = {"job_id": job_id, "kind": kind, "actor": actor,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "status": "queued", "request": payload}
        with queue_mutation():
            # Check jobs under the same mutex as worker claim/unlink.
            if ((ROOT / "jobs" / f"{job_id}.json").exists()
                    or (ROOT / "queue" / f"{job_id}.json").exists()):
                if idempotent:
                    original=next(p for p in (ROOT/'jobs'/f'{job_id}.json',ROOT/'queue'/f'{job_id}.json') if p.exists())
                    saved=read_json(original)
                    if saved.get('actor')!=actor or saved.get('kind')!=kind or saved.get('request')!=payload:
                        raise ValueError('idempotency_payload_conflict')
                    return job_id, False
                raise FileExistsError('duplicate_job')
            exclusive_json(ROOT / "queue" / f"{job_id}.json", record)
            sync_directory(ROOT / "queue")
        return (job_id, True) if idempotent else job_id

    def do_GET(self):
        actor = self.actor()
        if not actor:
            self.respond(401, {"error": "authentication_required"})
            return
        parsed = urlsplit(self.path)
        parts = [x for x in parsed.path.strip("/").split("/") if x]
        if actor == "dot_fc_observer":
            from fc_observer import read_observation
            code, payload = read_observation(sys.modules[__name__], parsed)
            self.respond(code, payload)
            return
        try:
            if parts[:2]==['pricing','v3']:
                from fc_pricing_v3.api import read
                self.respond(200,read('/'.join(parts[2:])))
                return
            if parts == ["reference-observer"]:
                from reference_observer_view import read_view
                self.respond(200, read_view())
                return
            if parts == ["collection-mode"]:
                self.respond(200, local_collection.view())
                return
            if parts == ['pricing','state']:
                from pricing_state import state
                view=state(owner=actor)
                if isinstance(view.get('quote'),dict):
                    view['quote']=public_artifact(view['quote'],include_quote_sha=True)
                self.respond(200,view)
                return
            if parts == ["health"]:
                self.respond(200, health())
                return
            if parts == ["monitor"]:
                self.respond(200, monitor_view())
                return
            if parts == ["activity"]:
                try:
                    limit = int(parse_qs(parsed.query).get("limit", ["100"])[0])
                except ValueError:
                    limit = 100
                day = parse_qs(parsed.query).get("date", [None])[0]
                if day is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                    self.respond(400, {"error": "activity_date_invalid"})
                    return
                try:
                    result = activity_feed(actor, max(1, min(limit, 200)), day=day)
                except ValueError:
                    self.respond(400, {"error": "activity_date_invalid"})
                    return
                self.respond(200, result)
                return
            if parts == ["automation"]:
                self.respond(200, automation_view(load_policy(), actor))
                return
            if parts == ["player-sync"]:
                self.respond(200, player_sync_view(load_player_sync_policy()))
                return
            if len(parts) == 2 and parts[0] in {"jobs", "snapshots", "quotes", "previews", "audits", "restore-previews"} and valid_id(parts[1]):
                folder = "runs" if parts[0] == "snapshots" else "executions" if parts[0] == "audits" else parts[0]
                path = ROOT / folder / f"{parts[1]}.json"
                if parts[0] == "jobs" and not path.exists():
                    path = ROOT / "queue" / f"{parts[1]}.json"
                if not path.exists():
                    self.respond(404, {"error": "not_found"})
                    return
                payload = read_json(path)
                if parts[0] in {"quotes", "snapshots"}:
                    payload = public_artifact(payload, include_quote_sha=parts[0] == "quotes")
                self.respond(200, payload)
                return
            self.respond(404, {"error": "not_found"})
        except (OSError, ValueError, sqlite3.Error) as exc:
            failure = ("permission_denied" if isinstance(exc, PermissionError)
                       else "invalid_json" if isinstance(exc, json.JSONDecodeError)
                       else "missing_state" if isinstance(exc, FileNotFoundError)
                       else "storage_unavailable")
            self.respond(503, {"error": "state_unavailable", "read_failure": failure,
                               "retryable_read": isinstance(exc, PermissionError)})

    def do_POST(self):
        actor = self.actor()
        if actor == "dot_fc_observer":
            self.respond(403, {"error": "observer_read_only"})
            return
        if not actor:
            self.respond(401, {"error": "authentication_required"})
            return
        parts = [x for x in self.path.split("?", 1)[0].strip("/").split("/") if x]
        try:
            data = self.body()
            if parts == ["activity", "retain"]:
                if self.headers.get("X-Forwarded-Proto") != "https":
                    self.respond(503, {"error": "https_required_for_activity_mark"})
                    return
                if set(data) != {"source", "id", "retained"}:
                    raise ValueError("activity_mark_invalid")
                try:
                    result = activity_log_store.set_retained(
                        data["source"], data["id"], data["retained"], actor)
                except (OSError, sqlite3.Error):
                    self.respond(503, {"error": "activity_storage_unavailable"})
                    return
                self.respond(200, result)
                return
            if parts == ["player-sync"]:
                if self.headers.get("X-Forwarded-Proto") != "https":
                    self.respond(503, {"error": "https_required_for_player_sync"})
                    return
                if set(data) != {"enabled", "expected_revision"}:
                    raise ValueError("player_sync_request_invalid")
                updated = save_player_sync_policy(data["enabled"], actor, data["expected_revision"])
                self.respond(200, player_sync_view(updated))
                return
            if actor not in WRITERS:
                self.respond(403, {"error": "write_role_required"})
                return
            if parts[:2]==['pricing','v3']:
                if self.headers.get('X-Forwarded-Proto')!='https' or self.headers.get('Origin')!='https://'+self.headers.get('Host',''):
                    self.respond(403,{'error':'pricing_https_origin_required'})
                    return
                from fc_pricing_v3.api import post
                self.respond(202,post('/'.join(parts[2:]),data,actor))
                return
            if parts and (parts[0]=='reprice' or parts[0]=='pricing' and parts[1:]!=['collect']):
                self.respond(409,{'error':'pricing_legacy_dispatch_retired_use_v3'})
                return
            if len(parts)==2 and parts[0]=='pricing'  and parts[1] in {'collect','preview','recalculate','restore-preview','hermes-review','evaluate'}:
                if self.headers.get('X-Forwarded-Proto')!='https' or self.headers.get('Origin')!='https://'+self.headers.get('Host',''):
                    self.respond(403,{'error':'pricing_https_origin_required'})
                    return
                action=parts[1]
                if action=='evaluate':
                    from pricing_state import evaluate
                    self.respond(200,evaluate(data,load_policy()))
                    return
                expected={'collect':{'client_event_id'},'preview':{'client_event_id','run_id'},
                          'recalculate':{'client_event_id','run_id','edits'},
                          'restore-preview':{'client_event_id','source_execution_id'},
                          'hermes-review':{'client_event_id','run_id'}}[action]
                if action=='hermes-review' and 'restore_source_execution_id' in data:
                    expected=expected|{'restore_source_execution_id'}
                if set(data)!=expected or not valid_id(data.get('client_event_id')):
                    raise ValueError('pricing_operation_fields')
                payload={k:v for k,v in data.items() if k!='client_event_id'}
                if 'run_id' in payload and not valid_id(payload['run_id']):raise ValueError('pricing_run_invalid')
                if 'source_execution_id' in payload and not valid_id(payload['source_execution_id']):raise ValueError('pricing_source_invalid')
                if 'restore_source_execution_id' in payload and not valid_id(payload['restore_source_execution_id']):raise ValueError('pricing_source_invalid')
                kind={'collect':'collect','preview':'preview','recalculate':'recalculate',
                      'restore-preview':'restore_preview','hermes-review':'hermes_review'}[action]
                job_id,accepted=self.enqueue(kind,actor,payload,data['client_event_id'],idempotent=True)
                self.respond(202 if accepted else 200,{'job_id':job_id,'status':'queued' if accepted else 'already_submitted'})
                return
            if parts in (["collection-mode"], ["local-collection", "poll"], ["local-collection", "submit"]):
                if self.headers.get("X-Forwarded-Proto") != "https" or self.headers.get("Origin") != "https://" + self.headers.get("Host", ""):
                    self.respond(403, {"error": "local_https_origin_required"})
                    return
                if parts == ["collection-mode"]:
                    with queue_mutation():
                        result = local_collection.save(data, actor)
                elif parts[-1] == "poll":
                    result = local_collection.poll(data, actor)
                else:
                    result = local_collection.submit(data, actor)
                self.respond(200, result)
                return
            if parts in (["automation", "discount-rules"], ["automation", "discount-preview"]):
                self.respond(409,{'error':'pricing_legacy_bands_retired','strategy':'fc-pricing-v3-20261026'})
                return
            if parts == ["automation"]:
                if self.headers.get("X-Forwarded-Proto") != "https":
                    self.respond(503, {"error": "https_required_for_automation_config"})
                    return
                if set(data) != {"settings", "expected_revision"}:
                    raise ValueError("automation_request_invalid")
                if (not isinstance(data["settings"], dict) or set(data["settings"]) != {
                        "system_enabled", "mode", "interval_minutes", "platforms", "minimum_gross_margin_pct"}):
                    raise ValueError("automation_request_invalid")
                if (isinstance(data["settings"], dict)
                        and data["settings"].get("system_enabled") is True
                        and data["settings"].get("mode") == "auto"
                        and writer_status() != "ready"):
                    self.respond(503, {"error": "automation_writer_unavailable"})
                    return
                try:
                    updated = save_policy(data["settings"], actor, data["expected_revision"])
                except OSError:
                    self.respond(503, {"error": "automation_storage_unavailable"})
                    return
                self.respond(200, automation_view(updated, actor))
                return
            if parts == ["collect"]:
                job_id = self.enqueue("collect", actor, {}, str(uuid.uuid4()))
                self.respond(202, {"run_id": job_id, "status": "queued"})
                return
            if parts == ["reprice", "preview"]:
                run_id = data.get("run_id")
                if not valid_id(run_id):
                    raise ValueError("run_id_invalid")
                job_id = self.enqueue("preview", actor, {"run_id": run_id})
                self.respond(202, {"job_id": job_id, "status": "queued"})
                return
            if parts == ["reprice", "recalculate"]:
                run_id = data.get("run_id")
                edits = data.get("edits", {})
                if not valid_id(run_id) or not isinstance(edits, dict):
                    raise ValueError("edits_invalid")
                job_id = self.enqueue("recalculate", actor, {"run_id": run_id, "edits": edits})
                self.respond(202, {"job_id": job_id, "status": "queued"})
                return
            if parts == ["reprice", "execute"]:
                if writer_status() != "ready":
                    self.respond(503, {"error": "certificate_unhealthy" if WRITE_ENABLE_FILE.exists()
                                       else "https_required_for_price_write"})
                    return
                if self.headers.get("X-Forwarded-Proto") != "https":
                    self.respond(503, {"error": "https_required_for_price_write"})
                    return
                preview_id = data.get("preview_id")
                selected = data.get("selected_platforms")
                confirmed = data.get("margin_confirmed_platforms", [])
                margin_reason = data.get("margin_exception_reason", "")
                event_id = data.get("client_event_id")
                if (not valid_id(preview_id) or not valid_id(event_id)
                        or not isinstance(selected, list) or not selected
                        or len(selected) != len(set(selected)) or any(x not in {"PS", "XBOX", "PC"} for x in selected)
                         or not isinstance(confirmed, list) or any(x not in selected for x in confirmed)
                         or not isinstance(margin_reason, str) or len(margin_reason.strip()) > 200):
                    raise ValueError("execute_invalid")
                job_id, accepted = self.enqueue("execute", actor, {"preview_id": preview_id,
                              "platforms": selected, "margin_confirmed_platforms": confirmed,
                              "margin_exception_reason": margin_reason.strip(),
                              "policy_revision": load_policy()["revision"]}, event_id, idempotent=True)
                self.respond(202 if accepted else 200,
                             {"job_id": job_id, "status": "queued" if accepted else "already_submitted"})
                return
            if len(parts) == 4 and parts[0] == "reprice" and valid_id(parts[1]) and parts[2:] == ["restore", "preview"]:
                if data:
                    raise ValueError("restore_preview_body_invalid")
                job_id = self.enqueue("restore_preview", actor, {"source_execution_id": parts[1]})
                self.respond(202, {"job_id": job_id, "status": "queued"})
                return
            if len(parts) == 3 and parts[0] == "reprice" and valid_id(parts[1]) and parts[2] == "restore":
                if writer_status() != "ready":
                    self.respond(503, {"error": "certificate_unhealthy" if WRITE_ENABLE_FILE.exists()
                                       else "https_required_for_price_write"})
                    return
                if self.headers.get("X-Forwarded-Proto") != "https":
                    self.respond(503, {"error": "https_required_for_price_write"})
                    return
                restore_preview_id = data.get("restore_preview_id")
                selected = data.get("selected_platforms")
                event_id = data.get("client_event_id")
                if (not valid_id(restore_preview_id) or not valid_id(event_id)
                        or not isinstance(selected, list) or not selected
                        or len(selected) != len(set(selected))
                        or any(x not in {"PS", "XBOX", "PC"} for x in selected)):
                    raise ValueError("restore_invalid")
                job_id, accepted = self.enqueue("restore", actor, {"source_execution_id": parts[1],
                             "restore_preview_id": restore_preview_id,
                              "platforms": selected}, event_id, idempotent=True)
                self.respond(202 if accepted else 200,
                             {"job_id": job_id, "status": "queued" if accepted else "already_submitted"})
                return
            self.respond(404, {"error": "not_found"})
        except QueueBusy:
            self.respond(503, {"error": "queue_mutation_busy", "retryable": True,
                               "accepted": False})
        except FileExistsError:
            self.respond(409, {"error": "duplicate_job"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            code = str(exc) if isinstance(exc, ValueError) else "invalid_request"
            self.respond(409 if code in {"automation_revision_changed", "player_sync_revision_changed", "local_revision_changed", "local_job_in_progress"} else 400,
                         {"error": code if code.startswith(("pricing_", "automation_", "minimum_sale_", "minimum_margin_", "player_sync_", "activity_", "local_")) else "invalid_request"})
        except (OSError, sqlite3.Error):
            self.respond(503, {"error": "queue_unavailable"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--activity-maintenance":
        result = activity_feed("system-archive", 1, deep=True)
        print(json.dumps({"status": "ok", "warnings": result["warnings"]}))
    else:
        ThreadingHTTPServer(("127.0.0.1", 8879), Handler).serve_forever()
