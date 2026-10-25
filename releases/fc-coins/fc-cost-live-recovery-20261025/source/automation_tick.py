"""Enqueue due FC cycles and maintain their idle browser; never writes prices."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import uuid
import stat
import sys
from contextlib import contextmanager

from automation_policy import ROOT, POLICY_FILE, load_policy
from player_sync_policy import load_policy as load_player_sync_policy


class QueueBusy(BlockingIOError):
    """No queue mutation was accepted; the caller may retry."""


@contextmanager
def queue_mutation():
    """Use the existing tick inode for all queue mutations, without creating it.

    The common inode is acquired first; nested config/business locks are NB.
    Worker releases queue
    before business execution. Reads and OFF saves do not acquire this mutex.
    Reconcile retains it until the final metadata publication.
    """
    import fcntl
    descriptors = []
    lock = None
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(parent)
        for segment in (ROOT / 'state').parts[1:]:
            parent = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=parent)
            descriptors.append(parent)
            current = os.fstat(parent)
            if current.st_uid != 0 or stat.S_IMODE(current.st_mode) & 0o022:
                raise OSError('queue_lock_parent_untrusted')
        lock = os.open('automation-tick.lock', os.O_RDONLY | os.O_NOFOLLOW,
                       dir_fd=parent)
        before = os.fstat(lock)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) != 0o644):
            raise OSError('queue_lock_metadata_untrusted')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise QueueBusy('queue_mutation_busy') from None
        current = os.stat('automation-tick.lock', dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise OSError('queue_lock_inode_changed')
        yield
        current = os.stat('automation-tick.lock', dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise OSError('queue_lock_inode_changed')
    finally:
        if lock is not None:
            os.close(lock)
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def supersession_bytes(key):
    """Bound existing records through stable descriptors; never follow links."""
    import stat
    import re
    if key!='state/worker-heartbeat.json' and not re.fullmatch(r'(jobs|player-sync|executions|all-coin-sync|runs|quotes|previews)/[0-9a-f-]{36}\.json',key):raise ValueError('supersession_record_path_invalid')
    path=ROOT/key;fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for index,part in enumerate(path.parent.parts[1:],1):
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            st=os.fstat(child);current=os.stat(part,dir_fd=fd,follow_symlinks=False)
            group_dir=st.st_gid==11028 and stat.S_IMODE(st.st_mode)==0o2770 and Path('/').joinpath(*path.parent.parts[1:index+1]) in {ROOT/'executions',ROOT/'all-coin-sync',ROOT/'player-sync',ROOT/'runs',ROOT/'quotes',ROOT/'previews'}
            if st.st_uid!=0 or (stat.S_IMODE(st.st_mode)&0o022 and not group_dir) or (st.st_dev,st.st_ino)!=(current.st_dev,current.st_ino):
                os.close(child);raise ValueError('supersession_record_parent_untrusted')
            os.close(fd);fd=child
        record=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            st=os.fstat(record)
            if not stat.S_ISREG(st.st_mode) or st.st_uid not in {0,994,11027} or st.st_gid not in {0,11028} or stat.S_IMODE(st.st_mode)&0o022 or st.st_nlink!=1:raise ValueError('supersession_record_untrusted')
            if key=='state/worker-heartbeat.json' and (st.st_uid!=0 or st.st_gid!=11028 or stat.S_IMODE(st.st_mode)!=0o640):raise ValueError('supersession_heartbeat_untrusted')
            with os.fdopen(record,'rb',closefd=False) as stream:raw=stream.read(32000001)
            after=os.fstat(record);current=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
            if len(raw)>32000000 or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or (current.st_dev,current.st_ino)!=(st.st_dev,st.st_ino):raise ValueError('supersession_record_changed')
            return raw
        finally:os.close(record)
    finally:os.close(fd)


def latest_confirmed_coin():
    rows=[json.loads(supersession_bytes('executions/'+p.name)) for p in (ROOT/'executions').glob('*.json')]
    rows=[r for r in rows if r.get('status')=='CONFIRMED' and r.get('sync_confirmed') is True]
    return max(rows,key=lambda r:utc(r['created_at'])) if rows else None


def supersession_receipt(job_id):
    """Only a root-private controlled transaction can authorize supersession."""
    import stat
    if str(uuid.UUID(job_id))!=job_id:raise ValueError('supersession_job_identity_invalid')
    path=ROOT/'rollback'/('player-reconcile-v2-'+job_id+'-supersession')/'supersession-receipt.json'
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in path.parent.parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            st=os.fstat(child);current=os.stat(part,dir_fd=fd,follow_symlinks=False)
            if st.st_uid!=0 or stat.S_IMODE(st.st_mode)&0o022 or (st.st_dev,st.st_ino)!=(current.st_dev,current.st_ino):
                os.close(child);raise ValueError('supersession_parent_untrusted')
            os.close(fd);fd=child
        record=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            st=os.fstat(record)
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_gid!=0 or stat.S_IMODE(st.st_mode)!=0o600 or st.st_nlink!=1:raise ValueError('supersession_receipt_untrusted')
            with os.fdopen(record,'rb',closefd=False) as stream:raw=stream.read(32000001)
            after=os.fstat(record);current=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
            if len(raw)>32000000 or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or (current.st_dev,current.st_ino)!=(st.st_dev,st.st_ino):raise ValueError('supersession_receipt_changed')
        finally:os.close(record)
        return json.loads(raw)
    finally:os.close(fd)


def superseded_basis(record=None):
    """A historical failure is superseded, never confirmed for a new price."""
    import hashlib
    if record is None:
        rows=[json.loads(supersession_bytes('jobs/'+p.name)) for p in (ROOT/'jobs').glob('*.json')]
        rows=[r for r in rows if r.get('kind')=='player_sync']
        record=max(rows,key=lambda r:utc(r['created_at'])) if rows else None
    if not record or record.get('status')!='superseded':return None
    pid=record['job_id'];receipt=supersession_receipt(pid)
    if receipt.get('status')!='superseded' or receipt.get('player_job_id')!=pid:raise ValueError('supersession_receipt_incomplete')
    for key in ['jobs/'+pid+'.json','player-sync/'+pid+'.json']:
        raw=supersession_bytes(key);value=json.loads(raw)
        if hashlib.sha256(raw).hexdigest()!=receipt['after_sha256'][key] or value.get('status')!='superseded' or value.get('supersession')!=receipt['marker']:raise ValueError('supersession_partial_or_changed')
    marker=receipt['marker'];cid=marker['superseding_coin_execution_id'];current=latest_confirmed_coin()
    if not current or current.get('execution_id')!=cid:raise ValueError('supersession_current_coin_changed')
    for key,wanted in receipt['basis_sha256'].items():
        if hashlib.sha256(supersession_bytes(key)).hexdigest()!=wanted:raise ValueError('supersession_coin_basis_changed')
    config=load_player_sync_policy()
    if not config['enabled'] or config['revision']!=marker['player_revision']:raise ValueError('supersession_policy_changed')
    return {'old_player_job_id':pid,'coin_execution_id':cid,'coin_execution_sha256':receipt['basis_sha256']['executions/'+cid+'.json'],
            'supersession_proof_sha256':marker['readback_proof_sha256']}


def player_price_readback_waived(record):
    """Only a completed category response followed by the retired price check."""
    request = record.get("request") or {}
    if (record.get("kind") != "player_sync" or record.get("status") != "failed"
            or record.get("error") != "player_sync_not_confirmed"
            or record.get("error_detail") != "player_sample_readback_timeout"
            or not valid_job_id(record.get("job_id"))
            or not valid_job_id(request.get("coin_execution_id"))):
        return False
    try:
        ledger = json.loads((ROOT / "player-sync" / (record["job_id"] + ".json")).read_text(encoding="utf-8"))
        return (isinstance(ledger, dict) and ledger.get("job_id") == record["job_id"]
                and ledger.get("coin_execution_id") == request["coin_execution_id"]
                and ledger.get("mode") == "category_all"
                and ledger.get("status") == "needs_reconcile"
                and ledger.get("stage") == "stopped"
                and ledger.get("error") == "player_sample_readback_timeout"
                and bool(ledger.get("completed_at")))
    except (OSError, ValueError, TypeError):
        return False


def player_sync_gate():
    """Block unresolved requests, excluding the retired player price verification."""
    config = load_player_sync_policy()
    if not config["enabled"]:
        return "ready"
    for path in (ROOT / "jobs").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        intent = record.get("player_sync_intent") or {}
        if (record.get("kind") == "auto_cycle" and record.get("status") == "ready"
                and ((record.get("result") or {}).get("status") == "confirmed"
                     or ((record.get("result") or {}).get("status") == "no_price_change" and record.get('player_sync_basis')))
                and intent.get("enabled") and intent.get("revision") == config["revision"]
                and (record.get("player_sync") or {}).get("status") not in {"queued", "already_queued"}):
            return "needs_reconcile"
    records = []
    for folder in ("queue", "jobs"):
        for path in (ROOT / folder).glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if (record.get("kind") == "player_sync"
                    and (record.get("request") or {}).get("config_revision") == config["revision"]):
                records.append(record)
    if not records:
        return "ready"
    last = max(records, key=lambda row: utc(row["created_at"]))
    if last.get("status") in {"queued", "running"}:
        return "in_progress"
    if player_price_readback_waived(last):
        return "ready"
    if last.get('status')=='superseded':
        try:
            if os.geteuid()==0:return 'ready' if superseded_basis(last) else 'needs_reconcile'
            # API is unprivileged. A fresh root-owned heartbeat reports the
            # worker's private validation; only root producers can act on it.
            import hashlib
            pulse=json.loads(supersession_bytes('state/worker-heartbeat.json'));approval=pulse.get('supersession_gate') or {}
            if not 0<=(datetime.now(timezone.utc)-utc(pulse['at'])).total_seconds()<=15 or approval.get('player_job_id')!=last['job_id']:return 'needs_reconcile'
            current=latest_confirmed_coin()
            if not current or current['execution_id']!=approval.get('coin_execution_id'):return 'needs_reconcile'
            for key,wanted in approval['after_sha256'].items():
                if key not in ['jobs/'+last['job_id']+'.json','player-sync/'+last['job_id']+'.json'] or hashlib.sha256(supersession_bytes(key)).hexdigest()!=wanted:return 'needs_reconcile'
            if len(approval['after_sha256'])!=2:return 'needs_reconcile'
            return 'ready'
        except (OSError,ValueError,KeyError,TypeError):return 'needs_reconcile'
    if last.get("status") != "ready" or (last.get("result") or {}).get("status") != "confirmed":
        return "needs_reconcile"
    return "ready"

def exclusive_json(path, payload):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def utc(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("automation_timestamp_invalid")
    return date.astimezone(timezone.utc)


def latest_cycle():
    records = []
    for folder in ("queue", "jobs"):
        for path in (ROOT / folder).glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job.get("kind") == "auto_cycle":
                    records.append(job)
            except (OSError, ValueError):
                raise ValueError("automation_job_unreadable") from None
    return max(records, key=lambda job: utc(job["created_at"])) if records else None


# Three fast retries, then one recovery check per hour while enabled.
# Every check is a new complete cycle; business writes are never replayed.
RETRY_MINUTES = (5, 15, 30, 60)
TRANSIENT_TIMEOUTS = {"browser_connection_timeout", "page_create_timeout",
                      "page_navigation_timeout", "page_read_timeout",
                      "platform_click_timeout", "platform_timeout", "collection_timeout", "TimeoutError"}
RETRY_LOCKS = ("snapshot.lock", "price-writer.lock", "p2pah-cost.lock", "lootbar.lock",
               "IGGM.lock", "U4GM.lock", "U7Buy.lock", "fx.lock")


def read_record(path):
    return json.loads(path.read_text(encoding="utf-8"))


def valid_job_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def proven_prewrite_timeout(job, revision):
    """Only proven read-only transient failures permit a new collection cycle."""
    if (job.get("kind") != "auto_cycle" or job.get("status") != "failed"
            or job.get("error") != "collection_incomplete"
            or (job.get("request") or {}).get("policy_revision") != revision
            or not valid_job_id(job.get("job_id")) or not job.get("completed_at")):
        return False
    if any(key in job for key in ("quote", "result", "writer_result", "run_id", "cache_refresh",
                                  "public_page_readback", "player_sync", "player_sync_intent")):
        return False
    jid = job["job_id"]
    if any((ROOT / folder / (jid + ".json")).exists() for folder in
           ("quotes", "previews", "requests", "executions", "all-coin-sync", "player-sync")):
        return False
    # preview_backend.sh keeps NO_PREVIEW diagnostics in root-only failed temp
    # files; they are never accepted preview IDs or price-write artifacts.
    previews = (p for p in (ROOT / "previews").glob("*.json")
                if not (p.name.startswith(".preview-") and p.name.endswith(".failed.json")
                        and len(p.name[len(".preview-"):-len(".failed.json")]) == 8
                        and p.name[len(".preview-"):-len(".failed.json")].isascii()
                        and p.name[len(".preview-"):-len(".failed.json")].isalnum()))
    if any(read_record(p).get("run_id") == jid for p in previews):
        return False
    snapshot = job.get("snapshot") or {}
    run = read_record(ROOT / "runs" / (jid + ".json"))
    if any(row.get("run_id") != jid or row.get("status") != "incomplete"
           or row.get("quote_status") != "NO_QUOTE" for row in (snapshot, run)):
        return False
    reason = job.get("error_detail")
    if not isinstance(reason, str) or reason != snapshot.get("reason") or reason != run.get("reason"):
        return False
    parts = reason.split(";")
    for part in parts:
        fields = part.split(":")
        if fields == ["P2PAH", "global_order_transport_unavailable"]:
            continue
        # Noncore HTTP challenges are retried by fresh collection, never solved or replayed.
        if (len(fields) in (2, 3) and fields[0] in {"IGGM", "U4GM", "U7Buy"}
                and fields[1] == "http_blocked"
                and (len(fields) == 2 or fields[2] in {"PS", "XBOX", "PC"})):
            continue
        # The cost collector visits pages 1..15 and emits typed page timeouts.
        # Only these read-only P2PAH failures qualify; HTTP/auth/validation do not.
        if (len(fields) == 3 and fields[0] == "P2PAH"
                and fields[1] in {"order_page_navigation_timeout", "order_page_read_timeout"}
                and fields[2] in {str(page) for page in range(1, 16)}):
            continue
        if (len(fields) not in (2, 3) or fields[0] not in {"Lootbar", "IGGM", "U4GM", "U7Buy", "P2PAH", "BOC"}
                or fields[1] not in TRANSIENT_TIMEOUTS
                or (len(fields) == 3 and fields[2] not in {"PS", "XBOX", "PC"})):
            return False
    return bool(parts)


def resolved_execution(record):
    if record.get("status") in {"CONFIRMED", "RESTORED", "CHECK_ONLY"}:
        return True
    if record.get("status") == "FAILED_BEFORE_WRITE":
        return not record.get("changed")
    # These are audited maintenance contracts, not generic status exemptions.
    if (record.get("kind") == "all_baseline_repair" and record.get("status") == "ALL_ALIGNED"
            and record.get("stage") == "all_alignment_complete" and record.get("sync_confirmed") is True
            and record.get("mmoexp_write_performed") is False):
        baseline = record.get("all_baseline") or {}
        return baseline.get("status") == "confirmed" and set(baseline.get("platforms") or []) == {"PS", "XBOX", "PC"}
    if (record.get("kind") == "player_validation_once" and record.get("status") == "VALIDATED"
            and record.get("stage") == "complete_independent_readback" and record.get("completed_at")):
        proof = record.get("independent_readback") or {}
        digest = proof.get("sha256")
        count = record.get("sample_verified_count")
        return (isinstance(digest, str) and len(digest) == 64 and all(x in "0123456789abcdef" for x in digest)
                and bool(proof.get("checked_at")) and utc(proof["checked_at"]) <= utc(record["completed_at"])
                and type(count) is int and count > 0 and count == len(record.get("samples") or []))
    return False


def proven_prewrite_rejection(job, revision):
    """Only the initial hook rejection occurs before the writer creates its ledger."""
    try:
        jid = job.get('job_id')
        if (job.get('kind') != 'auto_cycle' or job.get('status') != 'failed'
                or job.get('error') != 'writer_not_confirmed' or job.get('error_detail') != 'hook_scope_paused'
                or job.get('writer_result') not in ({'status':'FAILED','reason':'hook_scope_paused'},
                    {'status':'FAILED','reason':'hook_scope_paused','missing_module':None})
                or (job.get('request') or {}).get('policy_revision') != revision
                or not valid_job_id(jid) or job.get('run_id', jid) != jid
                or not utc(job['created_at']) <= utc(job['completed_at']) <= datetime.now(timezone.utc)):
            return False
        if any(key in job for key in ('result','changed','send_attempted','sent','write_started',
                                      'dispatch_started','cache_refresh','public_page_readback','player_sync','player_sync_intent')):
            return False
        required = ('queue','jobs','runs','quotes','previews','requests','executions','all-coin-sync','player-sync')
        if any(not (ROOT/folder).is_dir() or (ROOT/folder).is_symlink() for folder in required):
            return False
        if any((ROOT/folder/(jid+'.json')).exists() or (ROOT/folder/(jid+'.json')).is_symlink()
               for folder in ('requests','executions','all-coin-sync','player-sync')):
            return False
        if (ROOT/'executions'/('run-'+jid+'.used')).exists():
            return False
        for path in (ROOT/'executions').glob('*.json'):
            row = read_record(path)
            if row.get('run_id') == jid or not resolved_execution(row):
                return False
        if any(read_record(path).get('status') != 'confirmed' for path in (ROOT/'all-coin-sync').glob('*.json')):
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def proven_prewrite_retry(job, revision):
    return proven_prewrite_timeout(job, revision) or proven_prewrite_rejection(job, revision)


def retry_guard():
    if any(not (ROOT / folder).is_dir() for folder in ("queue", "jobs", "executions", "all-coin-sync")):
        return "ledger_unavailable"
    if any((ROOT / "queue").glob("*.json")):
        return "queue_busy"
    if any(read_record(p).get("status") == "running" for p in (ROOT / "jobs").glob("*.json")):
        return "job_running"
    # Keep the writer's uncertainty gate, including unknown/corrupt ledgers.
    if any(not resolved_execution(read_record(p)) for p in (ROOT / "executions").glob("*.json")):
        return "write_unconfirmed"
    if any(read_record(p).get("status") != "confirmed" for p in (ROOT / "all-coin-sync").glob("*.json")):
        return "all_sync_unconfirmed"
    if player_sync_gate() != "ready":
        return "player_sync_unconfirmed"
    return "ready"


def retry_plan(policy, last, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        if (not policy["system_enabled"] or policy["mode"] != "auto" or not policy["platforms"]
                or not last or not proven_prewrite_retry(last, policy["revision"])):
            return None
        request = last.get("request") or {}
        attempt = request.get("collection_retry_attempt", 0)
        if type(attempt) is not int or not 0 <= attempt <= 1000000:
            return None
        root_id = request.get("collection_retry_root", last["job_id"])
        if attempt:
            parent_id = request.get("collection_retry_of")
            if not valid_job_id(parent_id) or not valid_job_id(root_id):
                return None
            parent = read_record(ROOT / "jobs" / (parent_id + ".json"))
            root = read_record(ROOT / "jobs" / (root_id + ".json"))
            if (not proven_prewrite_retry(parent, policy["revision"])
                    or not proven_prewrite_retry(root, policy["revision"])
                    or (parent.get("request") or {}).get("collection_retry_attempt", 0) != attempt - 1
                    or (parent.get("request") or {}).get("collection_retry_root", parent_id) != root_id
                    or utc(parent["created_at"]) >= utc(last["created_at"])):
                return None
        elif any(k in request for k in ("collection_retry_of", "collection_retry_root")):
            return None
        completed = utc(last["completed_at"])
        if completed > now:
            return None
        delay = RETRY_MINUTES[min(attempt, len(RETRY_MINUTES) - 1)]
        next_at = completed + timedelta(minutes=delay)
        guard = retry_guard()
        if guard == 'ready' and proven_prewrite_rejection(last, policy['revision']):
            from automation_policy import hooks_before_write
            try:
                hooks_before_write(policy, policy['platforms'], automatic=True)
            except (OSError, ValueError) as exc:
                guard = str(exc) if str(exc).startswith('hook_') else 'hook_control_unavailable'
        return {"attempt": attempt, "next_attempt": attempt + 1, "root_job_id": root_id,
                "retry_of": last["job_id"], "delay_minutes": delay, "next_at": next_at.isoformat(),
                "fast_retries_exhausted": attempt >= 3, "blocked_reason": None if guard == "ready" else guard,
                "status": "retry_blocked" if guard != "ready" else "retry_due" if now >= next_at else
                          "retry_cooldown" if attempt >= 3 else "retry_waiting"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


# Audited historical exception: the 12:05:15 worker traceback proves check_write
# raised KeyError("IGGM") before preview/request creation. The original job remains
# unchanged; its exact byte digest and all no-write guards below must still match.
AUDITED_PREWRITE_INTERRUPTS = {
    "b5ef086d-ec83-40d6-b7a5-9203b99679bd":
        "0008ed4ce6b9a9a5070b0996e2b045ee4f94b477f22d52904a8633d62e043627",
}


def proven_readonly_cycle_failure(job, revision):
    """New full collection on its natural interval; never replay an old writer."""
    try:
        import hashlib
        jid = job.get('job_id')
        typed = (job.get('status') == 'failed' and
                 (job.get('error') in {'collection_incomplete', 'storefront_incomplete',
                    'storefront_run_mismatch', 'quote_not_ready', 'preview_unavailable'}
                  or str(job.get('error', '')).startswith('automation_source_incomplete:')))
        audited = False
        if (jid in AUDITED_PREWRITE_INTERRUPTS and job.get('status') == 'interrupted'
                and job.get('error') == 'worker_restarted_during_job'
                and job.get('actor') == 'system-automation'):
            path = ROOT / 'jobs' / (jid + '.json')
            audited = (not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest()
                       == AUDITED_PREWRITE_INTERRUPTS[jid])
        if (job.get('kind') != 'auto_cycle' or not (typed or audited)
                or (job.get('request') or {}).get('policy_revision') != revision
                or not valid_job_id(jid) or not job.get('completed_at')):
            return False
        if any(key in job for key in ('result', 'writer_result', 'changed', 'send_attempted',
                'write_started', 'player_sync', 'player_sync_intent', 'cache_refresh')):
            return False
        for folder in ('requests', 'executions', 'all-coin-sync', 'player-sync'):
            directory = ROOT / folder
            if not directory.is_dir() or directory.is_symlink():return False
            path = directory / (jid + '.json')
            if path.exists() or path.is_symlink():return False
        if (ROOT / 'executions' / ('run-' + jid + '.used')).exists():return False
        if any(read_record(p).get('run_id') == jid or not resolved_execution(read_record(p))
               for p in (ROOT / 'executions').glob('*.json')):return False
        return all(read_record(p).get('status') == 'confirmed'
                   for p in (ROOT / 'all-coin-sync').glob('*.json'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def due(policy, last, now=None):
    now = now or datetime.now(timezone.utc)
    if not policy["system_enabled"]:
        return "system_off"
    if policy["mode"] != "auto":
        return "manual_mode"
    if not policy["platforms"]:
        return "platforms_off"
    if last is None:
        return "due"
    last_revision = last.get("request", {}).get("policy_revision")
    # Range-only revisions preserve the original completion-based interval.
    # General settings changes retain the existing immediate due/resume behavior.
    if (type(last_revision) is not int
            or not policy.get("schedule_revision", policy["revision"]) <= last_revision <= policy["revision"]):
        return "due"
    if last["status"] in {"queued", "running"}:
        return "in_progress"
    if last["status"] in {"failed", "interrupted"}:
        retry = retry_plan(policy, last, now)
        if retry:
            return retry["status"]
        if proven_readonly_cycle_failure(last, policy['revision']):
            completed = utc(last['completed_at'])
            return 'due' if now - completed >= timedelta(minutes=policy['interval_minutes']) else 'waiting'
        return "paused_after_failure"
    # A recovered dependency resumes on the next natural collection deadline.
    # Do not launch an immediate extra cycle merely because the gate changed.
    completed = utc(last.get("completed_at") or last["created_at"])
    return "due" if now - completed >= timedelta(minutes=policy["interval_minutes"]) else "waiting"


def _tick_locked():
    import fcntl  # Linux timer; due() can also be verified on Windows.
    with queue_mutation():
        # Serialize timer queue publication with range-only configuration saves.
        POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with POLICY_FILE.with_suffix(".lock").open("a+b") as config_lock:
            fcntl.flock(config_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            policy = load_policy()
            last = latest_cycle()
            status = due(policy, last)
            if status not in {"due", "retry_due"}:
                return {"status": status, "collection_retry": retry_plan(policy, last)}
            request = {"policy_revision": policy["revision"]}
            from contextlib import ExitStack
            with ExitStack() as held:
                if status == "retry_due":
                    try:
                        for name in RETRY_LOCKS:
                            lock = held.enter_context((ROOT / "state" / name).open("rb"))
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return {"status": "retry_blocked", "reason": "active_lock"}
                    except OSError:
                        return {"status": "retry_blocked", "reason": "lock_unavailable"}
                    current = load_policy()
                    current_last = latest_cycle()
                    if current != policy or not current_last or current_last["job_id"] != last["job_id"]:
                        return {"status": "retry_cancelled", "reason": "policy_or_latest_cycle_changed"}
                    retry = retry_plan(current, current_last)
                    if not retry or retry["status"] != "retry_due":
                        return {"status": "retry_blocked", "collection_retry": retry}
                    request.update(collection_retry_attempt=retry["next_attempt"],
                                   collection_retry_of=retry["retry_of"], collection_retry_root=retry["root_job_id"])
                job_id = str(uuid.uuid4())
                exclusive_json(ROOT / "queue" / f"{job_id}.json",
                               {"job_id": job_id, "kind": "auto_cycle", "actor": "system-automation",
                                "created_at": datetime.now(timezone.utc).isoformat(), "status": "queued",
                                "request": request})
                return {"status": "queued", "job_id": job_id, "collection_retry": request.get("collection_retry_attempt")}


def tick():
    try:
        try:
            from browser_lifecycle import maintain
            maintenance = maintain()
        except Exception as error:
            maintenance = {'status': 'failed', 'error': type(error).__name__}
        result = _tick_locked()
        result['browser_lifecycle'] = maintenance
        result['queue_protocol'] = 'existing-tick-inode-v4'
        return result
    except BlockingIOError:
        return {"status": "retry_blocked", "reason": "queue_or_policy_busy", "retryable": True,
                "queue_protocol": "existing-tick-inode-v4"}


if __name__ == "__main__":
    if sys.argv[1:] == ['--queue-protocol']:
        try:
            with queue_mutation():
                result={'status':'ready','read_only':True,'queue_protocol':'existing-tick-inode-v4'}
        except QueueBusy:
            result={'status':'busy','read_only':True,'queue_protocol':'existing-tick-inode-v4'}
        print(json.dumps(result))
    else:
        print(json.dumps(tick()))
