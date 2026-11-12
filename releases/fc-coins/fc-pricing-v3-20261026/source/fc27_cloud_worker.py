"""Single server worker for FC27 collection, quote, write and restore jobs."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import hashlib
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import uuid

from snapshot_layer import ROOT, PLATFORMS, SITES, atomic_json
from server_quote_job import quote_for_run, age_ok
from automation_policy import load_policy, check_write
from player_sync_policy import load_policy as load_player_sync_policy
from automation_tick import player_sync_gate, queue_mutation, QueueBusy, sync_directory, exclusive_json, superseded_basis, supersession_bytes, supersession_receipt, utc
from fc27_cloud_api import writer_status
import local_collection
from automation_tick import resolved_execution


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


from fc_pricing_v3.observations import collect_reference_market


def collect_quote(job):
    run_id = job["job_id"]
    cfg = local_collection.pin(job)
    save_job(job)
    if cfg['mode'] == 'local':
        job['storefront'] = {'status': 'unavailable', 'reason': 'local_collection_pending'}
        save_job(job)
        try:
            evidence = local_collection.collect(job, 'all')
        except (OSError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else 'local_storage_unavailable'
            failed = {'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                      'status': 'incomplete', 'reason': reason, 'quote_status': 'NO_QUOTE',
                      'competitors': [{'run_id': run_id, 'source': site, 'platform': p,
                                       'status': 'missing', 'reason': reason} for site in SITES for p in PLATFORMS],
                      'costs': [{'run_id': run_id, 'platform': p, 'status': 'missing', 'reason': reason} for p in PLATFORMS],
                      'fx': {'status': 'missing', 'reason': reason}, 'collection_mode': cfg}
            failed_path = ROOT / 'runs' / (run_id + '.json')
            atomic_json(failed_path, failed)
            os.chown(failed_path, -1, 11028)
            os.chmod(failed_path, 0o640)
            job['snapshot'] = {k: failed[k] for k in ('run_id', 'status', 'reason', 'quote_status')}
            job['error_detail'] = reason
            save_job(job)
            raise
        snapshot_path = ROOT / 'runs' / (run_id + '.json')
        atomic_json(snapshot_path, evidence['snapshot'])
        os.chown(snapshot_path, -1, 11028)
        os.chmod(snapshot_path, 0o640)
        store_local_public(evidence['storefront'])
        code, snapshot = 0, {'run_id': run_id, 'status': 'ready_for_quote', 'reason': None,
                              'valid_competitors': sum(r['status'] == 'valid' for r in evidence['snapshot']['competitors']),
                              'source_coverage': evidence['snapshot']['source_coverage'],
                              'source_warnings': evidence['snapshot']['source_warnings'], 'valid_costs': 3, 'fx_status': 'valid',
                              'quote_status': 'PENDING', 'collection_location': 'local'}
    else:
        code, snapshot = run(["python3", str(APP / "snapshot_layer.py"), run_id], 480)
    from fc_pricing_v3.runtime import collection_scope,ledger
    from fc_pricing_v3.selective_sources import source_plan
    selection=collection_scope(ledger(),run_id)
    planned=source_plan(selection['active_mode'],selection['scope'])
    if cfg['mode']=='server' and 'ItemD2R' in planned['required_markets']+planned.get('auxiliary_markets',[]):
        reference=collect_reference_market(run_id)
        job['reference_competitors']=reference
        run_path=ROOT/'runs'/(run_id+'.json')
        if run_path.is_file():
            run_snapshot=json.loads(run_path.read_text(encoding='utf-8'))
            if run_snapshot.get('run_id')!=run_id:raise ValueError('snapshot_changed_before_quote')
            run_snapshot['reference_competitors']=reference
            atomic_json(run_path,run_snapshot)
            os.chown(run_path,-1,11028);os.chmod(run_path,0o640)
    job["snapshot"] = snapshot
    save_job(job)
    if code or snapshot.get("status") != "ready_for_quote":
        job["error_detail"] = snapshot.get("reason") or snapshot.get("status") or "collector_failed"
        raise ValueError("collection_incomplete")
    job["storefront"] = (refresh_storefront(job) if cfg['mode'] == 'server' else
                         {'status': 'ok', 'collection_location': 'local', 'refreshed_platforms': list(PLATFORMS)})
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
    run_snapshot["collection_mode"] = cfg
    run_snapshot['source_plan']=planned
    # The existing shared source runtime owns HTTPS reads; worker Python has no ssl.
    atomic_json(run_path, run_snapshot)
    os.chown(run_path, -1, 11028)
    os.chmod(run_path, 0o640)
    code, quote = run(["python3", str(APP / "server_quote_job.py"), run_id], 300)
    job["quote"] = quote
    if code or quote.get("status") not in {"ready_for_preview", "margin_review_required"}:
        job["error_detail"] = quote.get("reason") or "quote_failed"
        raise ValueError(job["error_detail"])
    return {"run_id": run_id, "quote_status": quote["status"]}


def store_local_public(payload):
    path = ROOT / 'monitor/storefront.json'
    atomic_json(path, payload)
    os.chown(path, -1, 11028)
    os.chmod(path, 0o640)


def refresh_storefront(job):
    """Read the public selling price once after a competitor cycle, including failed cycles."""
    if local_collection.pin(job)['mode'] == 'local':
        try:
            result = local_collection.collect(job, 'storefront')['storefront']
            store_local_public(result)
            return {'status': 'ok', 'collection_location': 'local', 'refreshed_platforms': list(PLATFORMS)}
        except (OSError, ValueError) as exc:
            return {'status': 'unavailable', 'reason': str(exc) if isinstance(exc, ValueError) else 'local_storage_unavailable'}
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
        return {"status": "unconfirmed", "reason": result.get("reason") or "cache_clear_failed",
                "responses": result.get("responses", [])}
    return result


PUBLIC_READBACK_ATTEMPTS = 5
PUBLIC_READBACK_INTERVAL = 20


def _public_page_match(job):
    """Strict match of the stored public page against this cycle's confirmed targets.

    Returns (matched, platforms_or_reason). Every existing judgement is preserved:
    the state must belong to this run, be ok, each selected platform must be ok and
    its package_usd must equal target_page_usd exactly.
    """
    state = json.loads((ROOT / "monitor/storefront.json").read_text(encoding="utf-8"))
    quote = json.loads((ROOT / "quotes" / f"{job['job_id']}.json").read_text(encoding="utf-8"))
    if state.get("collection_run_id") != job["job_id"] or state.get("status") != "ok":
        return False, "public_page_unavailable"
    targets = {row["platform"]: row for row in quote["result"]["rows"]}
    selected = job["result"]["platforms"]
    if not selected:
        return False, "public_page_target_mismatch"
    if any(
            state["rows"][platform].get("status") != "ok"
            or Decimal(str(state["rows"][platform]["package_usd"])) !=
            Decimal(str(targets[platform]["target_page_usd"]))
            for platform in selected):
        return False, "public_page_target_mismatch"
    return True, selected


def verify_public_page(job):
    """Confirm the public 100K prices match the backend targets.

    The edge/cache in front of the public storefront does not necessarily reflect a
    confirmed backend write immediately. A single read taken seconds after the write
    can still see the previous package price, which must not be recorded as a real
    publication failure. Refresh and re-check within a bounded budget; only record
    verified when the strict comparison actually passes. Never relaxes any existing
    judgement and never fabricates a pass.
    """
    last = {"status": "unconfirmed", "reason": "public_page_readback_unconfirmed"}
    for attempt in range(PUBLIC_READBACK_ATTEMPTS):
        try:
            matched, detail = _public_page_match(job)
        except (OSError, ValueError, KeyError, TypeError):
            return {"status": "unconfirmed", "reason": "public_page_readback_unconfirmed"}
        if matched:
            state = json.loads((ROOT / "monitor/storefront.json").read_text(encoding="utf-8"))
            return {"status": "verified", "platforms": detail,
                    "checked_at": state["last_attempt_at"], "attempts": attempt + 1}
        if attempt + 1 < PUBLIC_READBACK_ATTEMPTS:
            job["storefront_after"] = refresh_storefront(job)
            save_job(job)
            time.sleep(PUBLIC_READBACK_INTERVAL)
    return last


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
    with queue_mutation():
        return _enqueue_player_sync_locked(coin_job, config)


def parent_fields_hash(parent):
    fields={k:parent.get(k) for k in ['job_id','kind','actor','status','request','run_id','result','completed_at','player_sync_basis','player_sync_intent']}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate_nochange_sources(jid,preview_id,raws,policy):
    snapshot=json.loads(raws['runs/'+jid+'.json']);quote=json.loads(raws['quotes/'+jid+'.json']);preview=json.loads(raws['previews/'+preview_id+'.json']);now=datetime.now(timezone.utc)
    if snapshot.get('run_id')!=jid or snapshot.get('status')!='ready_for_quote' or not age_ok(snapshot['created_at'],now) or quote.get('run_id')!=jid or quote.get('snapshot_sha256')!=hashlib.sha256(raws['runs/'+jid+'.json']).hexdigest() or not age_ok(quote['created_at'],now):raise ValueError('player_basis_collection_changed')
    costs=snapshot.get('costs',[]);offers=snapshot.get('competitors',[]);fx=snapshot.get('fx') or {};sf=snapshot.get('storefront') or {}
    if len(costs)!=3 or {r.get('platform') for r in costs}!=set(PLATFORMS) or any(r.get('status')!='valid' or r.get('run_id')!=jid or not age_ok(r['checked_at'],now) for r in costs):raise ValueError('player_basis_costs_incomplete')
    if len(offers)!=12 or {(r.get('platform'),r.get('source')) for r in offers}!={(p,s) for p in PLATFORMS for s in SITES} or any(r.get('status')!='valid' or r.get('run_id')!=jid or not age_ok(r['captured_at'],now) for r in offers):raise ValueError('player_basis_competitors_incomplete')
    if fx.get('status')!='valid' or not age_ok(fx['checked_at'],now) or sf.get('collection_run_id')!=jid or sf.get('status')!='ok' or set(sf.get('rows') or {})!=set(PLATFORMS) or any(r.get('status')!='ok' or not age_ok(r['checked_at'],now) for r in sf['rows'].values()):raise ValueError('player_basis_fx_or_public_source_incomplete')
    if preview.get('preview_id')!=preview_id or preview.get('run_id')!=jid or preview.get('status')!='review_only' or changed_auto_platforms(preview,list(PLATFORMS))[0]:raise ValueError('player_basis_preview_changed')
    check_write(policy,quote,list(PLATFORMS),automatic=True)


def prepare_nochange_basis(job,preview_id,unchanged,blocked):
    """Record a pending intent only after this natural cycle passes every existing rule."""
    if set(unchanged)!=set(PLATFORMS) or blocked:return None
    with queue_mutation():
        recovery=job.get('player_recovery') or {}
        pending=recovery.get('basis') if recovery.get('status')=='ready' else superseded_basis()
        if not pending:return None
        if pending.get('kind')=='prewrite_auth_recovery':
            if recovery_basis(job['job_id'],load_player_sync_policy())!=pending:raise ValueError('player_recovery_changed')
            if not 0<=(datetime.now(timezone.utc)-utc(recovery['checked_at'])).total_seconds()<=180:raise ValueError('player_recovery_expired')
        policy=load_policy();config=load_player_sync_policy()
        if not policy['system_enabled'] or policy['mode']!='auto' or policy['revision']!=job['request']['policy_revision'] or not config['enabled']:raise ValueError('player_basis_policy_changed')
        jid=job['job_id'];keys=['runs/'+jid+'.json','quotes/'+jid+'.json','previews/'+preview_id+'.json']
        raws={k:supersession_bytes(k) for k in keys};quote=json.loads(raws[keys[1]]);preview=json.loads(raws[keys[2]])
        validate_nochange_sources(jid,preview_id,raws,policy)
        cid=pending['coin_execution_id'];audit=json.loads(supersession_bytes('executions/'+cid+'.json'))
        rates={r['platform']:Decimal(str(r['b2c'])) for r in audit['after']['rows']}
        if len(rates)!=3 or set(rates)!=set(PLATFORMS):raise ValueError('player_basis_rates_incomplete')
        for section,key in [('backend_before','b2c'),('targets','quote')]:
            rows=preview[section]['rows'] if section=='backend_before' else preview[section]
            if len(rows)!=3 or {r['platform']:Decimal(str(r[key])) for r in rows}!=rates:raise ValueError('player_basis_preview_not_current')
        job['player_sync_basis']={**pending,'all_ledger_sha256':hashlib.sha256(supersession_bytes('all-coin-sync/'+cid+'.json')).hexdigest(),'source_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in raws.items()},'preview_id':preview_id,'coin_revision':policy['revision'],'player_revision':config['revision']}
        job['player_sync_intent']={'enabled':True,'revision':config['revision']}
        save_job(job)
        return job['player_sync_basis']


def validate_nochange_parent(parent,config,active_job_id=None):
    basis=parent.get('player_sync_basis') or {};policy=load_policy()
    if parent.get('kind')!='auto_cycle' or parent.get('actor')!='system-automation' or parent.get('status')!='ready' or (parent.get('result') or {}).get('status')!='no_price_change' or parent.get('player_sync_intent')!={'enabled':True,'revision':config['revision']}:raise ValueError('player_basis_parent_invalid')
    if not 0<=(datetime.now(timezone.utc)-utc(parent['completed_at'])).total_seconds()<=300:raise ValueError('player_basis_parent_expired')
    if not policy['system_enabled'] or policy['mode']!='auto' or policy['revision']!=basis.get('coin_revision') or not config['enabled'] or config['revision']!=basis.get('player_revision'):raise ValueError('player_basis_policy_changed')
    old=json.loads(supersession_bytes('jobs/'+basis['old_player_job_id']+'.json'))
    current=recovery_basis(parent['job_id'],config,active_job_id) if basis.get('kind')=='prewrite_auth_recovery' else superseded_basis(old)
    if not current or any(current[k]!=basis[k] for k in current):raise ValueError('player_basis_supersession_changed')
    cid=basis['coin_execution_id']
    if hashlib.sha256(supersession_bytes('all-coin-sync/'+cid+'.json')).hexdigest()!=basis['all_ledger_sha256']:raise ValueError('player_basis_all_changed')
    jid=parent['job_id'];expected={'runs/'+jid+'.json','quotes/'+jid+'.json','previews/'+basis['preview_id']+'.json'}
    if set(basis['source_sha256'])!=expected:raise ValueError('player_basis_source_scope_changed')
    raws={k:supersession_bytes(k) for k in expected}
    if any(hashlib.sha256(raw).hexdigest()!=basis['source_sha256'][k] for k,raw in raws.items()):raise ValueError('player_basis_source_changed')
    validate_nochange_sources(jid,basis['preview_id'],raws,policy)
    return {'parent_id':jid,'parent_fields_sha256':parent_fields_hash(parent),'basis':basis}


def _enqueue_player_sync_locked(coin_job, config=None):
    """One durable follow-up job per confirmed automatic coin execution."""
    config = config or load_player_sync_policy()
    if not config["enabled"]:
        return {"status": "disabled"}
    nochange=(coin_job.get('result') or {}).get('status')=='no_price_change' and bool(coin_job.get('player_sync_basis'))
    coin_id=coin_job['player_sync_basis']['coin_execution_id'] if nochange else (coin_job.get('v3_outcome') or {}).get('operation_id',coin_job['job_id'])
    if coin_job.get('kind') not in ('auto_cycle','v3_cycle') or (not nochange and (coin_job.get('result') or {}).get('status')!='confirmed'):raise ValueError('player_sync_coin_not_confirmed')
    if coin_job.get('kind')=='v3_cycle':
        if (coin_job.get('request') or {}).get('v3_operation_id')!=coin_id:raise ValueError('player_sync_parent_mismatch')
        v3_player_completion(coin_id,coin_job['job_id'])
    job_id = recovery_job_id(coin_job['job_id']) if nochange and coin_job['player_sync_basis'].get('kind')=='prewrite_auth_recovery' else str(uuid.uuid5(uuid.NAMESPACE_URL, "fc27-player-sync:" + coin_id))
    path = QUEUE / (job_id + ".json")
    if path.exists() or (JOBS / (job_id + ".json")).exists():
        return {"status": "already_queued", "job_id": job_id}
    automatic_basis=validate_nochange_parent(coin_job,config) if nochange else None
    record = {"job_id": job_id, "kind": "player_sync", "actor": "system-automation",
              "created_at": datetime.now(timezone.utc).isoformat(), "status": "queued",
              "request": {"coin_execution_id": coin_id, "config_revision": config["revision"]}}
    if automatic_basis:record["request"]["automatic_basis"]=automatic_basis
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(path, 0, 11028)
    sync_directory(QUEUE)
    return {"status": "queued", "job_id": job_id}


def v3_player_completion(coin_id,parent_id=None):
    """Read terminal proof from the original ledger, never from a submitted request."""
    from fc_pricing_v3.runtime import ledger
    operation=ledger().get('operations',coin_id)
    if not operation or operation.get('operation_id')!=coin_id or operation.get('status')!='COMPLETED':raise ValueError('player_sync_coin_not_confirmed')
    if operation.get('target_not_completed') and not any(s.get('kind')=='base' and s.get('state')=='CONFIRMED' for s in operation.get('steps',[])):raise ValueError('player_sync_base_not_confirmed')
    bundle=operation['bundle']
    if parent_id is not None and bundle.get('snapshot_id')!=parent_id:raise ValueError('player_sync_parent_mismatch')
    receipt=operation.get('readback') or {}
    return dict(operation_id=coin_id,status=operation['status'],snapshot_id=bundle.get('snapshot_id'),bundle_sha256=bundle.get('sha256'),
                base_prices=(operation.get('actual_action') or bundle['action'])['base_prices'],
                confirmed_at=operation.get('actual_state_confirmed_at') or operation.get('completed_at'),
                readback={k:receipt.get(k) for k in ('status','operation_id','confirmation_scope','order_feedback','admin_unit_prices','targets')})


def recovery_job_id(parent_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'fc27-player-recovery:' + parent_id))


def recovery_candidate(root, config, cycle_id, read_bytes, resolved_execution, at=None, active_job_id=None):
    at = at or datetime.now(timezone.utc)
    def read(key):
        return json.loads(read_bytes(key))
    if not config.get('enabled'):
        raise ValueError('recovery_player_disabled')
    for folder in ('queue', 'jobs', 'executions', 'all-coin-sync', 'player-sync'):
        path = root / folder
        if not path.is_dir() or path.is_symlink():
            raise ValueError('recovery_ledger_unavailable')
    if any((root / 'queue').glob('*.json')):
        raise ValueError('recovery_queue_busy')
    jobs = [read('jobs/' + p.name) for p in (root / 'jobs').glob('*.json')]
    if active_job_id is not None:
        active = [j for j in jobs if j.get('job_id') == active_job_id]
        if (active_job_id != recovery_job_id(cycle_id) or len(active) != 1
                or active[0].get('kind') != 'player_sync' or active[0].get('status') != 'running'
                or ((active[0].get('request') or {}).get('automatic_basis') or {}).get('parent_id') != cycle_id):
            raise ValueError('recovery_active_job_invalid')
        jobs = [j for j in jobs if j.get('job_id') != active_job_id]
    if any(j.get('status') == 'running' and j.get('job_id') != cycle_id for j in jobs):
        raise ValueError('recovery_job_running')
    players = [j for j in jobs if j.get('kind') == 'player_sync'
               and (j.get('request') or {}).get('config_revision') == config['revision']]
    if not players:
        raise ValueError('recovery_failure_missing')
    last = max(players, key=lambda j: j['created_at'])
    jid = last['job_id']
    if str(uuid.UUID(jid)) != jid:
        raise ValueError('recovery_job_id_invalid')
    result = last.get('sync_result') or {}
    if (last.get('status') != 'failed' or last.get('actor') != 'system-automation'
            or last.get('error') != 'player_sync_not_confirmed'
            or result.get('status') != 'blocked_before_write'
            or result.get('reason') != 'chenchao_auth_unavailable'
            or last.get('error_detail') != 'chenchao_auth_unavailable'
            or last.get('result')):
        raise ValueError('recovery_requires_reconciliation')
    completed = datetime.fromisoformat(last['completed_at'].replace('Z', '+00:00'))
    if completed.tzinfo is None or completed > at:
        raise ValueError('recovery_failure_timestamp_invalid')
    # Absence alone is not proof: it supplements the narrow typed prewrite error.
    ledger = root / 'player-sync' / (jid + '.json')
    if ledger.exists() or ledger.is_symlink():
        raise ValueError('recovery_player_write_may_have_started')
    audits = [read('executions/' + p.name) for p in (root / 'executions').glob('*.json')]
    if not audits or any(not resolved_execution(a) for a in audits):
        raise ValueError('recovery_coin_write_unconfirmed')
    all_rows = [read('all-coin-sync/' + p.name) for p in (root / 'all-coin-sync').glob('*.json')]
    if not all_rows or any(a.get('status') != 'confirmed' for a in all_rows):
        raise ValueError('recovery_all_write_unconfirmed')
    confirmed = [a for a in audits if a.get('status') == 'CONFIRMED' and a.get('sync_confirmed') is True]
    current = max(confirmed, key=lambda a: a['created_at']) if confirmed else None
    cid = (last.get('request') or {}).get('coin_execution_id')
    if (not current or current.get('execution_id') != cid or str(uuid.UUID(cid)) != cid
            or current.get('automatic') is not True
            or current.get('all_baseline', {}).get('status') != 'confirmed'):
        raise ValueError('recovery_coin_basis_changed')
    return {'kind': 'prewrite_auth_recovery', 'old_player_job_id': jid,
            'failed_job_sha256': hashlib.sha256(read_bytes('jobs/' + jid + '.json')).hexdigest(),
            'coin_execution_id': cid,
            'coin_execution_sha256': hashlib.sha256(read_bytes('executions/' + cid + '.json')).hexdigest(),
            'all_ledger_sha256': hashlib.sha256(read_bytes('all-coin-sync/' + cid + '.json')).hexdigest()}


def recovery_basis(cycle_id, config, active_job_id=None):
    return recovery_candidate(ROOT, config, cycle_id, supersession_bytes, resolved_execution, active_job_id=active_job_id)


def verify_recovery_public_prices(basis):
    """Reuse the host's existing public outbound adapter; never mount its keys into the session container."""
    import storefront_monitor as sf
    import tempfile
    cid = basis['coin_execution_id']
    ledger = json.loads(supersession_bytes('all-coin-sync/' + cid + '.json'))
    if ledger.get('status') != 'confirmed' or len(ledger.get('steps', [])) != 3:
        raise ValueError('recovery_public_ledger_incomplete')
    rows = {step['platform']: step['source'] for step in ledger['steps']}
    if set(rows) != set(PLATFORMS):raise ValueError('recovery_public_platforms_incomplete')
    with tempfile.TemporaryDirectory(prefix='fc-recovery-public-') as folder:
        jar=Path(folder)/'public-cookie.txt'
        mapping=sf.page_mapping(sf.fetch(sf.PAGE_URL,cookie_jar=jar))
        for key,platform in sf.PLATFORMS.items():
            payload=json.loads(sf.fetch(sf.GOODS_URL,{'Game_id':'1327','top_cid':'1','aid':mapping['servers'][key],'cid':mapping['cid'],'site_id':mapping['site_id']},100000,jar))
            offers=payload['goods']['index']['list'];row=rows[platform]
            if len(offers)!=1 or offers[0]['unit']!='K' or int(offers[0]['id'])!=int(row['id']) or len(offers[0]['goods_list'])!=15:
                raise ValueError('recovery_public_scope_changed')
            for i,tier in enumerate(offers[0]['goods_list'].values()):
                for public_key,backend_key in [('num','gold'),('give','give'),('discount','discount'),('price','price'),('price_discount','price')]:
                    if Decimal(str(tier[public_key]))!=Decimal(str(row['more'][backend_key][i])):
                        raise ValueError('recovery_public_tier_changed')


def probe_player_recovery(job):
    """One bounded read-only probe; eligibility is never persisted as a global gate."""
    if job.get('player_recovery'):
        return False  # An interrupted stage is not replayed in this cycle.
    try:
        config = load_player_sync_policy()
        with queue_mutation():
            basis = recovery_basis(job['job_id'], config)
            job['player_recovery'] = {'status': 'probing', 'basis': basis,
                                      'player_revision': config['revision']}
            save_job(job)
        request = {'job_id': job['job_id'], 'coin_execution_id': basis['coin_execution_id'],
                   'config_revision': config['revision'], 'dry_run': True,
                   'recovery_preflight': True}
        code, result = run_writer_request(job, 'sync_players.sh', request, 180)
        job['player_recovery']['probe_result'] = {
            'exit_code': code, 'status': str(result.get('status') or 'missing')[:64],
            'reason': str(result.get('reason') or '')[:100]}
        if code or result.get('status') != 'preflight_ready':
            raise ValueError('recovery_probe_failed')
        verify_recovery_public_prices(basis)
        with queue_mutation():
            if load_player_sync_policy() != config or recovery_basis(job['job_id'], config) != basis:
                raise ValueError('recovery_basis_changed')
            policy = load_policy()
            if not policy['system_enabled'] or policy['mode'] != 'auto' or policy['revision'] != job['request']['policy_revision']:
                raise ValueError('recovery_policy_changed')
            job['player_recovery'].update(status='ready', checked_at=datetime.now(timezone.utc).isoformat())
            save_job(job)
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        job.setdefault('player_recovery', {}).update(status='blocked', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        save_job(job)
        return False


def handle(job):
    kind=job['kind']
    if kind=='collect':return collect_quote(job)
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
        execution=json.loads((ROOT/'executions'/(coin_id+'.json')).read_text(encoding='utf-8'))
        if execution.get('status') in ('ORDER_ADMIN_CONFIRMED','PUBLIC_CONFIRMED'):
            if not job['request'].get('automatic_basis') and job['job_id']!=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+coin_id)):raise ValueError('player_sync_original_job_mismatch')
            request['v3_completion']=v3_player_completion(coin_id)
        if job['request'].get('automatic_basis'):
            with queue_mutation():
                parent_id=job['request']['automatic_basis']['parent_id']
                parent=json.loads(supersession_bytes('jobs/'+parent_id+'.json'))
                current=validate_nochange_parent(parent,load_player_sync_policy(),job['job_id'] if (parent.get('player_sync_basis') or {}).get('kind')=='prewrite_auth_recovery' else None)
                if current!=job['request']['automatic_basis'] or current['basis']['coin_execution_id']!=coin_id or (recovery_job_id(parent_id) if current['basis'].get('kind')=='prewrite_auth_recovery' else str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+coin_id)))!=job['job_id']:raise ValueError('player_basis_request_changed')
                request['automatic_basis']=current
        code, result = run_writer_request(job, "sync_players.sh", request, 3700)
        if code or result.get("status") != "confirmed":
            job["sync_exit_code"] = code
            job["sync_result"] = result
            job["error_detail"] = result.get("reason") or result.get("status") or "player_sync_failed"
            raise ValueError("player_sync_not_confirmed")
        return result
    raise ValueError("job_kind_unsupported")


def heartbeat():
    payload={"at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
             "queue_protocol": "existing-tick-inode-v4"}
    try:
        basis=superseded_basis()
        if basis:
            receipt=supersession_receipt(basis['old_player_job_id'])
            payload['supersession_gate']={'player_job_id':basis['old_player_job_id'],
                'coin_execution_id':basis['coin_execution_id'],'after_sha256':receipt['after_sha256']}
    except (OSError,ValueError,KeyError,TypeError):pass
    atomic_json(ROOT / "state/worker-heartbeat.json",payload)
    # Health is read by the unprivileged API.
    path = ROOT / "state/worker-heartbeat.json"
    os.chown(path.parent, -1, 11028)
    os.chmod(path.parent, 0o750)
    os.chown(path, -1, 11028)
    os.chmod(path, 0o640)


def recover_running_jobs():
    with queue_mutation():
        _recover_running_jobs_locked()


def _recover_running_jobs_locked():
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
def retry_player_followups():
    with queue_mutation():
        _retry_player_followups_locked()


def _player_writer_available():
    import fcntl,stat
    path=ROOT/'state/price-writer.lock'
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(descriptor);current=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):
            raise ValueError('player_writer_lock_changed')
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        return True
    finally:os.close(descriptor)


def _player_queue_expired(job):
    # Bound queue wait by the existing writer allowance, without extending it on retry.
    return (datetime.now(timezone.utc)-utc(job['created_at'])).total_seconds()>=3700


def _player_not_sent_busy(job):
    try:
        if str(uuid.UUID(job.get('job_id','')))!=job.get('job_id'):return False
    except (ValueError,TypeError,AttributeError):return False
    if (job.get('kind')!='player_sync' or job.get('actor')!='system-automation' or job.get('status')!='failed'
            or job.get('error')!='player_sync_not_confirmed' or job.get('error_detail')!='busy'
            or type(job.get('sync_exit_code')) is not int or job['sync_exit_code']!=75
            or job.get('sync_result')!={'status':'busy'} or job.get('result') or 'post_response' in job):return False
    for folder in ('player-sync','requests'):
        path=ROOT/folder/(job['job_id']+'.json')
        if path.exists() or path.is_symlink():return False
    return True


def _player_busy_retry_matches(job,raw):
    old=json.loads(raw);retry=job.get('writer_lock_retry') or {}
    return (job.get('status')=='queued' and type(retry.get('attempt')) is int
            and retry==dict(attempt=1,failed_job_sha256=hashlib.sha256(raw).hexdigest())
            and _player_not_sent_busy(old) and not old.get('writer_lock_retry')
            and all(job.get(key)==old.get(key) for key in ('job_id','kind','actor','request','created_at')))


def _retry_player_lock_busy_locked(job,path):
    if not _player_not_sent_busy(job):return
    if path.name!=job['job_id']+'.json':raise ValueError('player_busy_job_identity_changed')
    queued=QUEUE/(job['job_id']+'.json');raw=path.read_bytes()
    if json.loads(raw)!=job:raise ValueError('player_busy_job_changed')
    if queued.exists():
        if not _player_busy_retry_matches(json.loads(queued.read_text()),raw):raise ValueError('queue_claim_needs_reconcile')
        return
    if job.get('writer_lock_retry') or _player_queue_expired(job):
        job['error_detail']='player_writer_lock_retry_exhausted' if job.get('writer_lock_retry') else 'player_writer_queue_timeout'
        save_job(job);return
    record=dict(job,status='queued',writer_lock_retry=dict(attempt=1,failed_job_sha256=hashlib.sha256(raw).hexdigest()))
    record['writer_lock_failures']=list(job.get('writer_lock_failures') or [])+[dict(previous_job=json.loads(raw),failed_job_sha256=hashlib.sha256(raw).hexdigest(),classification='NOT_SENT_writer_lock_busy')]
    exclusive_json(queued,record);os.chown(queued,0,11028)


def _retry_player_followups_locked():
    for path in JOBS.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get('kind')=='player_sync':
                _retry_player_lock_busy_locked(job,path)
                continue
            intent = job.get("player_sync_intent") or {}
            if (job.get("kind") not in ("auto_cycle","v3_cycle") or job.get("status") != "ready"
                    or not ((job.get("result") or {}).get("status")=="confirmed" or ((job.get("result") or {}).get("status")=="no_price_change" and job.get("player_sync_basis")))
                    or not intent.get("enabled")
                    or (job.get("player_sync") or {}).get("status") in {"queued", "already_queued"}):
                continue
            config = load_player_sync_policy()
            if config["enabled"] and config["revision"] == intent.get("revision"):
                job["player_sync"] = _enqueue_player_sync_locked(job, config)
                save_job(job)
        except (OSError, ValueError, KeyError):
            pass
def claim_next_job():
    with queue_mutation():
        queued = sorted(QUEUE.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for path in queued:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "queued" or job.get("job_id") != path.stem:
                path.rename(path.with_suffix(".invalid"))
                return None
            prior=JOBS/(path.stem+'.json')
            if prior.is_symlink() or (prior.exists() and not (job.get('kind')=='player_sync' and _player_busy_retry_matches(job,prior.read_bytes()))):
                # Only an exact unsent lock-busy receipt admits this same-ID retry.
                raise ValueError('queue_claim_needs_reconcile')
            if job.get('kind')=='player_sync':
                if _player_queue_expired(job):
                    job.update(status='failed',error='player_sync_not_confirmed',error_detail='player_writer_queue_timeout',completed_at=datetime.now(timezone.utc).isoformat())
                    save_job(job);sync_directory(JOBS);path.unlink();sync_directory(QUEUE)
                    continue
                if not _player_writer_available():continue
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            save_job(job)
            sync_directory(JOBS)
            path.unlink()
            sync_directory(QUEUE)
            return job
        return None


def main():
    def pulse():
        while True:
            heartbeat()
            time.sleep(5)
    threading.Thread(target=pulse, daemon=True).start()
    startup_recovered = False
    while True:
        try:
            if not startup_recovered:
                recover_running_jobs()
                startup_recovered = True
            retry_player_followups()
            job = claim_next_job()
            if job is None:
                time.sleep(2)
                continue
            try:
                job["result"] = handle(job)
                job["status"] = "ready"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                if job['kind']=='collect' and isinstance(exc,ValueError) and reason.lower().startswith(('pricing_v3_infeasible:','pricing_v3_capacity_unresolved:')):
                    job.update(status='ready',result=dict(status='INFEASIBLE',reason=reason,run_id=job['job_id']))
                else:
                    job.update(status='failed',error=reason)
            if job['kind']=='collect' and 'storefront' not in job:
                job['storefront']=refresh_storefront(job)
            job['completed_at']=datetime.now(timezone.utc).isoformat()
            save_job(job)
        except (OSError, ValueError):
            time.sleep(2)


if __name__ == "__main__":
    main()
