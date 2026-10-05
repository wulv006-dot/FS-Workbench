"""Single server worker for FC27 collection, quote, write and restore jobs."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from snapshot_layer import ROOT, PLATFORMS, atomic_json
from server_quote_job import quote_for_run
from automation_policy import load_policy, check_write
from player_sync_policy import load_policy as load_player_sync_policy
from automation_tick import player_sync_gate
from fc27_cloud_api import writer_status


APP = Path("/opt/fc27-cloud-browser")
QUEUE = ROOT / "queue"
JOBS = ROOT / "jobs"


def save_job(job):
    path = JOBS / f"{job['job_id']}.json"
    atomic_json(path, job)
    os.chown(path.parent, -1, 11028)
    os.chmod(path.parent, 0o750)
    os.chown(path, -1, 11028)
    os.chmod(path, 0o640)


def run(command, timeout):
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                             cwd=str(APP))
    try:
        payload = json.loads(process.stdout.splitlines()[-1])
    except (IndexError, ValueError):
        payload = {"status": "failed", "reason": "process_output_invalid"}
    return process.returncode, payload


def run_writer_request(job, script, request, timeout):
    request_path = ROOT / "requests" / f"{job['job_id']}.json"
    descriptor = os.open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(request, stream, separators=(",", ":"))
    os.chown(request_path, 0, 11028)
    try:
        return run([str(APP / script), str(request_path)], timeout)
    finally:
        request_path.unlink(missing_ok=True)


def collect_quote(job):
    run_id = job["job_id"]
    code, snapshot = run(["python3", str(APP / "snapshot_layer.py"), run_id], 440)
    job["snapshot"] = snapshot
    save_job(job)
    if code or snapshot.get("status") != "ready_for_quote":
        job["error_detail"] = snapshot.get("reason") or snapshot.get("status") or "collector_failed"
        raise ValueError("collection_incomplete")
    job["storefront"] = refresh_storefront(job)
    save_job(job)
    if job["storefront"].get("status") != "ok":
        job["error_detail"] = "storefront_incomplete"
        raise ValueError("storefront_incomplete")
    state = json.loads((ROOT / "monitor/storefront.json").read_text(encoding="utf-8"))
    if (state.get("collection_run_id") != run_id or state.get("status") != "ok"
            or set(state.get("rows") or {}) != set(PLATFORMS)
            or any(state["rows"][p].get("status") != "ok" for p in PLATFORMS)):
        job["error_detail"] = "storefront_run_mismatch"
        raise ValueError("storefront_run_mismatch")
    run_path = ROOT / "runs" / f"{run_id}.json"
    run_snapshot = json.loads(run_path.read_text(encoding="utf-8"))
    if run_snapshot.get("run_id") != run_id or run_snapshot.get("status") != "ready_for_quote":
        raise ValueError("snapshot_changed_before_quote")
    run_snapshot["storefront"] = state
    atomic_json(run_path, run_snapshot)
    os.chown(run_path, -1, 11028)
    os.chmod(run_path, 0o640)
    code, quote = run(["python3", str(APP / "server_quote_job.py"), run_id], 15)
    job["quote"] = quote
    if code or quote.get("status") not in {"ready_for_preview", "margin_review_required"}:
        job["error_detail"] = quote.get("reason") or "quote_failed"
        raise ValueError("quote_not_ready")
    return {"run_id": run_id, "quote_status": quote["status"]}


def refresh_storefront(job):
    """Read the public selling price once after a competitor cycle, including failed cycles."""
    try:
        code, result = run(["/usr/sbin/runuser", "-u", "fc27api", "--", "/usr/bin/python3",
                            str(APP / "storefront_monitor.py"), job["job_id"]], 95)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "storefront_refresh_failed"}
    if code or result.get("status") not in {"ok", "partial", "unavailable"}:
        return {"status": "unavailable", "reason": result.get("reason") or "storefront_refresh_failed"}
    return result


def refresh_backend_cache(job):
    """Ask the authorized chenchao session to clear the admin cache after a confirmed write."""
    try:
        code, result = run([str(APP / "clear_cache_after_write.sh"), job["job_id"]], 175)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unconfirmed", "reason": "cache_clear_unavailable"}
    if code or result.get("status") != "cleared":
        return {"status": "unconfirmed", "reason": result.get("reason") or "cache_clear_failed"}
    return result


def verify_public_page(job):
    """Record whether the public 100K prices match the confirmed backend targets."""
    try:
        state = json.loads((ROOT / "monitor/storefront.json").read_text(encoding="utf-8"))
        quote = json.loads((ROOT / "quotes" / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        if state.get("collection_run_id") != job["job_id"] or state.get("status") != "ok":
            raise ValueError("public_page_unavailable")
        targets = {row["platform"]: row for row in quote["result"]["rows"]}
        selected = job["result"]["platforms"]
        if not selected or any(
                state["rows"][platform].get("status") != "ok"
                or Decimal(str(state["rows"][platform]["package_usd"])) !=
                Decimal(str(targets[platform]["target_page_usd"]))
                for platform in selected):
            raise ValueError("public_page_target_mismatch")
        return {"status": "verified", "platforms": selected,
                "checked_at": state["last_attempt_at"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unconfirmed", "reason": "public_page_readback_unconfirmed"}


def previous_public_write_gap(current_run_id):
    """Do not write again while the last confirmed write is absent from the public page."""
    previous = []
    for path in (ROOT / "jobs").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if (row.get("job_id") != current_run_id and row.get("kind") == "auto_cycle"
                and (row.get("result") or {}).get("status") == "confirmed"):
            previous.append(row)
    if not previous:
        return None
    last = max(previous, key=lambda row: row["created_at"])
    later_manual = []
    for path in (ROOT / "jobs").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if (row.get("kind") == "execute" and row.get("status") == "ready"
                and (row.get("result") or {}).get("status") == "CONFIRMED"
                and row.get("created_at", "") > last["created_at"]):
            later_manual.append(row)
    # A completed auto readback cannot prove publication of a later manual write.
    if ((last.get("public_page_readback") or {}).get("status") == "verified"
            and not later_manual):
        return None
    previous_quote = json.loads((ROOT / "quotes" / (last["job_id"] + ".json")).read_text(
        encoding="utf-8"))
    current_page = json.loads((ROOT / "monitor/storefront.json").read_text(encoding="utf-8"))
    if (current_page.get("collection_run_id") != current_run_id
            or current_page.get("status") != "ok"):
        raise ValueError("current_public_page_unavailable")
    targets = {row["platform"]: row for row in previous_quote["result"]["rows"]}
    selected = list(last["result"]["platforms"])
    if not selected:
        raise ValueError("previous_public_write_evidence_missing")
    expected_pages = {platform: Decimal(str(targets[platform]["target_page_usd"]))
                      for platform in selected}
    for row in sorted(later_manual, key=lambda item: item["created_at"]):
        audit = json.loads((ROOT / "executions" / (row["job_id"] + ".json")).read_text(
            encoding="utf-8"))
        if (audit.get("status") != "CONFIRMED" or audit.get("sync_confirmed") is not True
                or set(row["result"].get("platforms") or []) != set(audit.get("changed") or [])):
            raise ValueError("manual_price_write_evidence_missing")
        manual_targets = {target["platform"]: target for target in audit["targets"]}
        for platform in row["result"]["platforms"]:
            if platform not in PLATFORMS or platform not in manual_targets:
                raise ValueError("manual_price_write_evidence_missing")
            if platform not in selected:
                selected.append(platform)
            expected_pages[platform] = Decimal(str(manual_targets[platform]["quote"])) * 100
    missing = []
    for platform in selected:
        page = (current_page.get("rows") or {}).get(platform) or {}
        target = expected_pages[platform]
        if (page.get("status") != "ok" or Decimal(str(page["package_usd"])) !=
                Decimal(str(target))):
            missing.append(platform)
    return {"previous_execution_id": last["job_id"], "platforms": missing} if missing else None


def changed_auto_platforms(preview, eligible):
    """Only send platforms whose current backend B2C unit price differs."""
    try:
        before = {row["platform"]: row for row in preview["backend_before"]["rows"]}
        targets = {row["platform"]: row for row in preview["targets"]}
    except (KeyError, TypeError, AttributeError):
        raise ValueError("backend_preview_incomplete") from None
    if set(before) != set(PLATFORMS) or set(targets) != set(PLATFORMS):
        raise ValueError("backend_platforms_incomplete")
    changed, unchanged = [], []
    for platform in eligible:
        current = Decimal(str(before[platform]["b2c"]))
        target = Decimal(str(targets[platform]["quote"]))
        if current <= 0 or target <= 0:
            raise ValueError("backend_price_invalid:" + platform)
        (changed if current != target else unchanged).append(platform)
    return changed, unchanged


def load_backend_preview(summary, run_id):
    """The preview command prints an ID; the full checked snapshot is saved on disk."""
    try:
        preview_id = str(uuid.UUID(summary["preview_id"]))
        if preview_id != summary["preview_id"]:
            raise ValueError("backend_preview_id_invalid")
        preview = json.loads((ROOT / "previews" / (preview_id + ".json")).read_text(
            encoding="utf-8"))
        if (preview.get("preview_id") != preview_id or preview.get("run_id") != run_id
                or preview.get("status") != "review_only"):
            raise ValueError("backend_preview_mismatch")
        return preview
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError("backend_preview_unavailable") from None


def enqueue_player_sync(coin_job, config=None):
    """One durable follow-up job per confirmed automatic coin execution."""
    config = config or load_player_sync_policy()
    if not config["enabled"]:
        return {"status": "disabled"}
    coin_id = coin_job["job_id"]
    if coin_job.get("kind") != "auto_cycle" or (coin_job.get("result") or {}).get("status") != "confirmed":
        raise ValueError("player_sync_coin_not_confirmed")
    job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "fc27-player-sync:" + coin_id))
    path = QUEUE / (job_id + ".json")
    if path.exists() or (JOBS / (job_id + ".json")).exists():
        return {"status": "already_queued", "job_id": job_id}
    record = {"job_id": job_id, "kind": "player_sync", "actor": "system-automation",
              "created_at": datetime.now(timezone.utc).isoformat(), "status": "queued",
              "request": {"coin_execution_id": coin_id, "config_revision": config["revision"]}}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(path, 0, 11028)
    return {"status": "queued", "job_id": job_id}


def handle(job):
    kind = job["kind"]
    if kind == "collect":
        return collect_quote(job)
    if kind == "auto_cycle":
        policy = load_policy()
        revision = job["request"]["policy_revision"]
        if not policy["system_enabled"] or policy["revision"] != revision:
            raise ValueError("automation_policy_changed")
        collected = collect_quote(job)
        job["run_id"] = collected["run_id"]
        save_job(job)
        if policy["mode"] == "manual":
            return {**collected, "status": "collected_for_manual_review"}
        gate = player_sync_gate()
        if gate != "ready":
            return {**collected, "status": "deferred_player_sync", "reason": gate}
        previous_gap = previous_public_write_gap(job["job_id"])
        if previous_gap:
            return {**collected, "status": "previous_public_price_unconfirmed",
                    **previous_gap}
        quote = json.loads((ROOT / "quotes" / f"{job['job_id']}.json").read_text(encoding="utf-8"))
        selected, blocked = [], {}
        for platform in policy["platforms"]:
            try:
                check_write(policy, quote, [platform], automatic=True)
                selected.append(platform)
            except ValueError as exc:
                reason = str(exc)
                if reason.startswith(("automatic_margin_floor:", "automatic_tier_unavailable:",
                                      "automatic_tier_rule:")):
                    blocked[platform] = reason
                else:
                    raise
        job["blocked_platforms"] = blocked
        save_job(job)
        if not selected:
            return {**collected, "status": "all_platforms_blocked", "blocked_platforms": blocked}
        if writer_status() != "ready":
            raise ValueError("automation_writer_unavailable")
        current = load_policy()
        if not current["system_enabled"] or current["mode"] != "auto" or current["revision"] != revision:
            raise ValueError("automation_policy_changed")
        code, preview = run([str(APP / "preview_backend.sh"), job["job_id"]], 85)
        if code or preview.get("status") != "review_only":
            job["error_detail"] = preview.get("reason") or "preview_failed"
            raise ValueError("preview_unavailable")
        selected, unchanged = changed_auto_platforms(
            load_backend_preview(preview, job["job_id"]), selected)
        job["unchanged_platforms"] = unchanged
        save_job(job)
        if not selected:
            return {**collected, "status": "no_price_change", "platforms": [],
                    "unchanged_platforms": unchanged, "blocked_platforms": blocked}
        current = load_policy()
        if not current["system_enabled"] or current["mode"] != "auto" or current["revision"] != revision:
            raise ValueError("automation_policy_changed")
        request = {"preview_id": preview["preview_id"],
                   "execution_id": job["job_id"], "actor": "system-automation",
                   "platforms": selected, "margin_confirmed_platforms": [],
                   "margin_exception_reason": "", "policy_revision": revision,
                   "automatic": True}
        code, result = run_writer_request(job, "execute_price.sh", request, 130)
        if code or result.get("status") != "CONFIRMED":
            job["writer_result"] = result
            job["error_detail"] = result.get("reason") or result.get("status") or "writer_failed"
            raise ValueError("writer_not_confirmed")
        return {**collected, "status": "confirmed", "platforms": selected,
                "unchanged_platforms": unchanged, "blocked_platforms": blocked,
                "execution_id": job["job_id"]}
    if kind == "preview":
        run_id = job["request"]["run_id"]
        code, result = run([str(APP / "preview_backend.sh"), run_id], 85)
        if code or result.get("status") != "review_only":
            job["error_detail"] = result.get("reason") or result.get("status") or "preview_failed"
            raise ValueError("preview_unavailable")
        return result
    if kind == "recalculate":
        return quote_for_run(job["request"]["run_id"], job["request"]["edits"])
    if kind == "execute":
        policy = load_policy()
        if policy["revision"] != job["request"].get("policy_revision"):
            raise ValueError("automation_policy_changed")
        request = {"preview_id": job["request"]["preview_id"],
                   "execution_id": job["job_id"], "actor": job["actor"],
                   "platforms": job["request"]["platforms"],
                   "margin_confirmed_platforms": job["request"]["margin_confirmed_platforms"],
                   "margin_exception_reason": job["request"].get("margin_exception_reason", ""),
                   "policy_revision": policy["revision"], "automatic": False}
        code, result = run_writer_request(job, "execute_price.sh", request, 130)
        if code or result.get("status") != "CONFIRMED":
            job["writer_result"] = result
            job["error_detail"] = result.get("reason") or result.get("status") or "writer_failed"
            raise ValueError("writer_not_confirmed")
        return result
    if kind == "restore_preview":
        request = {"mode": "preview", "source_execution_id": job["request"]["source_execution_id"]}
        code, result = run_writer_request(job, "restore_price.sh", request, 130)
        if code or result.get("status") != "restore_review_only":
            job["error_detail"] = result.get("reason") or "restore_preview_failed"
            raise ValueError("restore_preview_unavailable")
        path = ROOT / "restore-previews" / f"{result['restore_preview_id']}.json"
        atomic_json(path, result)
        os.chown(path, 0, 11028)
        os.chmod(path, 0o640)
        return {"restore_preview_id": result["restore_preview_id"],
                "source_execution_id": request["source_execution_id"]}
    if kind == "restore":
        request = {"mode": "execute", "restore_preview_id": job["request"]["restore_preview_id"],
                   "source_execution_id": job["request"]["source_execution_id"],
                   "execution_id": job["job_id"], "actor": job["actor"],
                   "platforms": job["request"]["platforms"]}
        code, result = run_writer_request(job, "restore_price.sh", request, 130)
        if code or result.get("status") != "RESTORED":
            job["writer_result"] = result
            job["error_detail"] = result.get("reason") or "restore_failed"
            raise ValueError("restore_not_confirmed")
        return result
    if kind == "player_sync":
        config = load_player_sync_policy()
        if not config["enabled"]:
            return {"status": "skipped", "reason": "player_sync_disabled"}
        if config["revision"] != job["request"].get("config_revision"):
            return {"status": "skipped", "reason": "player_sync_config_changed"}
        coin_id = job["request"]["coin_execution_id"]
        if not isinstance(coin_id, str) or not (ROOT / "executions" / (coin_id + ".json")).exists():
            raise ValueError("player_sync_coin_execution_missing")
        request = {"job_id": job["job_id"], "coin_execution_id": coin_id,
                   "config_revision": config["revision"],
                   "resume": job["request"].get("resume") is True}
        code, result = run_writer_request(job, "sync_players.sh", request, 3700)
        if code or result.get("status") != "confirmed":
            job["sync_result"] = result
            job["error_detail"] = result.get("reason") or result.get("status") or "player_sync_failed"
            raise ValueError("player_sync_not_confirmed")
        return result
    raise ValueError("job_kind_unsupported")


def heartbeat():
    atomic_json(ROOT / "state/worker-heartbeat.json",
                {"at": datetime.now(timezone.utc).isoformat()})
    # Health is read by the unprivileged API.
    path = ROOT / "state/worker-heartbeat.json"
    os.chown(path.parent, -1, 11028)
    os.chmod(path.parent, 0o750)
    os.chown(path, -1, 11028)
    os.chmod(path, 0o640)


def main():
    for path in JOBS.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") == "running":
                job["status"] = "interrupted"
                job["error"] = "worker_restarted_during_job"
                job["completed_at"] = datetime.now(timezone.utc).isoformat()
                save_job(job)
        except (OSError, ValueError):
            pass
    for path in JOBS.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            intent = job.get("player_sync_intent") or {}
            if (job.get("kind") != "auto_cycle" or job.get("status") != "ready"
                    or (job.get("result") or {}).get("status") != "confirmed"
                    or not intent.get("enabled")
                    or (job.get("player_sync") or {}).get("status") in {"queued", "already_queued"}):
                continue
            config = load_player_sync_policy()
            if config["enabled"] and config["revision"] == intent.get("revision"):
                job["player_sync"] = enqueue_player_sync(job, config)
                save_job(job)
        except (OSError, ValueError, KeyError):
            pass
    def pulse():
        while True:
            heartbeat()
            time.sleep(5)
    threading.Thread(target=pulse, daemon=True).start()
    while True:
        queued = sorted(QUEUE.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not queued:
            time.sleep(2)
            continue
        path = queued[0]
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "queued" or job.get("job_id") != path.stem:
                path.rename(path.with_suffix(".invalid"))
                continue
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            save_job(job)
            path.unlink()
            try:
                job["result"] = handle(job)
                job["status"] = "ready"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                job["status"] = "failed"
                job["error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            wrote_price = (job["status"] == "ready" and
                           ((job["kind"] == "auto_cycle" and
                             (job.get("result") or {}).get("status") == "confirmed") or
                            (job["kind"] == "execute" and
                             (job.get("result") or {}).get("status") == "CONFIRMED")))
            if wrote_price:
                if job["kind"] == "auto_cycle":
                    try:
                        config = load_player_sync_policy()
                        job["player_sync_intent"] = {"enabled": config["enabled"],
                                                     "revision": config["revision"]}
                    except (OSError, ValueError) as exc:
                        job["player_sync_intent"] = {"enabled": False,
                                                     "error": type(exc).__name__}
                save_job(job)  # The confirmed backend write survives cache/readback failure.
                job["cache_refresh"] = refresh_backend_cache(job)
            if job["kind"] in {"collect", "auto_cycle"} and "storefront" not in job:
                job["storefront"] = refresh_storefront(job)
            if wrote_price:
                job["storefront_after"] = refresh_storefront(job)
            if (job["kind"] == "auto_cycle" and wrote_price):
                job["public_page_readback"] = verify_public_page(job)
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            save_job(job)
            if (job["kind"] == "auto_cycle" and job["status"] == "ready"
                    and (job.get("result") or {}).get("status") == "confirmed"):
                try:
                    intent = job.get("player_sync_intent") or {}
                    config = load_player_sync_policy()
                    job["player_sync"] = (enqueue_player_sync(job, config)
                                          if intent.get("enabled") and intent.get("revision") == config["revision"]
                                          else {"status": "disabled_or_changed"})
                except (OSError, ValueError) as exc:
                    job["player_sync"] = {"status": "enqueue_failed",
                                          "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
                save_job(job)
        except (OSError, ValueError):
            time.sleep(2)


if __name__ == "__main__":
    main()
