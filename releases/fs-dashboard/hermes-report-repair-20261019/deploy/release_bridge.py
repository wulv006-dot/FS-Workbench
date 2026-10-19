"""Pin the reviewed publisher, changing only this release's exact scope."""

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import types
from contextlib import closing
from pathlib import Path

from release_scope import NEW_ALLOWED, SCOPE, TARGETS


HERE = Path(__file__).resolve().parent
BASE_SHA = "1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de"


TRACKING_DB='/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db'

def tracking_jobs_idle(root):
    path = root / TRACKING_DB.lstrip("/")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("tracking_ledger_path_link")
    if not path.exists():
        return
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("tracking_ledger_wrong_type")
    if os.name == "posix" and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o600):
        raise ValueError("tracking_ledger_permissions")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            pending = db.execute("SELECT count(*) FROM scan_jobs WHERE state='pending'").fetchone()[0]
            running = db.execute("SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')").fetchone()[0]
    except sqlite3.Error as error:
        raise ValueError("tracking_ledger_schema_or_read_failure") from error
    if pending or running:
        raise ValueError("tracking_job_in_flight")


def load_base():
    raw = (HERE / "release_navigation_base.py").read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError("frozen_publisher_drift")
    approved_raw = (HERE / "approved-manifest.json").read_bytes()
    approved = json.loads(approved_raw)
    mapping = {r["candidate"]: r["target"] for r in approved["files"]}
    if approved.get("scope") != SCOPE or mapping != TARGETS or len(approved["files"]) != len(TARGETS):
        raise ValueError("exact_conversation_targets_required")
    if any((r.get("beforeSha256") is None and r["target"] not in NEW_ALLOWED) or
           r.get("mode") != "0o644" or r.get("owner") != "0:0" for r in approved["files"]):
        raise ValueError("exact_new_and_existing_targets_required")
    if approved.get("businessWrites") is not False or approved.get("timersChanged") is not False:
        raise ValueError("read_only_business_boundary")
    if approved.get("runtimeRequired") != {"fs-business-range.service": {"ActiveState": "active"},
                                            "fs-hermes-fc.service": {"ActiveState": "active"}}:
        raise ValueError("active_services_required")
    source = raw.decode("utf-8")
    old_scope = "HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'"
    if source.count(old_scope) != 1: raise ValueError("frozen_scope_anchor_drift")
    source = source.replace(old_scope, f"HERMES_HISTORY_SCOPE='{SCOPE}'")
    needle = "if any(r.get('beforeSha256') is None for r in files if not (("
    if source.count(needle) != 1: raise ValueError("frozen_new_target_anchor_drift")
    source = source.replace(needle, "if any(r.get('beforeSha256') is None for r in files if r['target'] not in CONVERSATION_NEW and not ((")
    base = types.ModuleType("conversation_frozen_publisher")
    base.__file__ = str(HERE / "release_navigation_base.py")
    base.CONVERSATION_NEW = NEW_ALLOWED
    exec(compile(source, base.__file__, "exec"), base.__dict__)
    base.HERMES_HISTORY_TARGETS = TARGETS
    old_target = base.target_for
    base.target_for = lambda relative: TARGETS[relative] if relative in TARGETS else old_target(relative)
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get("scope") == SCOPE else (_ for _ in ()).throw(ValueError("conversation_scope_only"))
    original_validate = base.validate
    def validate(manifest, stage):
        if manifest != approved: raise ValueError("exact_frozen_manifest_required")
        result = original_validate(manifest, stage)
        return result
    base.validate = validate
    original_inspect = base.inspect

    def composed_import(stage, root):
        if root != Path("/") or os.name != "posix":
            return  # Local synthetic tests do not have the active service tree.
        candidate = (stage / "candidate/source").resolve(strict=True)
        live = Path("/opt/fs-hermes-fc")
        if not (live / "controller.py").is_file():
            raise ValueError("active_hermes_controller_missing")
        program = (
            "import sys; from pathlib import Path; "
            "candidate=Path(sys.argv[1]); live=Path(sys.argv[2]); "
            "sys.path[:0]=[str(candidate),str(live),'/opt/fs-exact-range-20261001']; "
            "import controller,research,management_context,evidence_access,html_check; "
            "assert Path(controller.__file__).resolve()==candidate/'controller.py'; "
            "assert Path(research.__file__).resolve()==candidate/'research.py'; "
            "names={v['function']['name'] for v in research.tool_schemas()}; "
            "assert 'mcp__fcro__fc_read_evidence' in names; "
            "assert 'mcp__fcro__fc_check_report_html' in names"
        )
        try:
            result = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(candidate), str(live)],
                                    cwd="/", capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("conversation_composed_import_unavailable") from exc
        if result.returncode:
            raise ValueError("conversation_composed_import_failed")

    def inspect(manifest, stage, root=Path("/")):
        # This is also called by apply under the original publisher's release locks.
        result = original_inspect(manifest, stage, root)
        composed_import(stage, root)
        return result
    base.inspect = inspect
    original_quiescent = base.hermes_quiescent
    def quiescent(root):
        original_quiescent(root)
        # The pinned old image predates private customer jobs but has model jobs.
        if root == Path("/") and os.name == "posix":
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=3) as response:
                health = json.load(response)
            if response.status != 200 or not (health.get("ready") is True or health.get("status") == "ready"):
                raise ValueError("session_health_not_ready_for_release")
            count = health.get("active_model_reads")
            if type(count) is not int or count != 0:
                raise ValueError("active_model_reads_block_release")
            image = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.Image}}", "fc27-p2pah-session"],
                text=True, timeout=10).strip()
            customer = health.get("active_customer_reads")
            if image == 'sha256:18d9f4c3531782953636aa3b47afd9e3a7eb802bc06782d8106260bed4f184eb':
                if customer is not None and (type(customer) is not int or customer != 0):
                    raise ValueError("active_customer_reads_block_release")
            elif type(customer) is not int or customer != 0:
                raise ValueError("active_customer_reads_counter_missing_or_busy")
        tracking_jobs_idle(root)
        if root == Path("/") and os.name == "posix":
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8931/health", timeout=3) as response:
                range_health = json.load(response)
            if response.status != 200 or range_health.get("ok") is not True:
                raise ValueError("range_health_not_ready_for_release")
            reports = range_health.get("active_customer_reports")
            if reports is not None and (type(reports) is not int or reports != 0):
                raise ValueError("active_customer_reports_block_release")
        path = base.rooted(root, "/var/lib/fs-hermes-fc/fs/conversations/conversations.db")
        base.no_target_link(path)
        if path.exists():
            with closing(sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)) as db:
                active = db.execute("SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')").fetchone()[0]
                if active: raise ValueError("active_or_unknown_conversation_run")
    base.hermes_quiescent = quiescent
    original_guards = base.guards
    state = {"applying": False, "journal": None}
    original_journal = base.journal_write
    def durable_journal(backup, journal):
        original_journal(backup, journal)
        if state["applying"] and journal.get("manifest") == approved:
            state["journal"] = json.loads(json.dumps(journal))
    base.journal_write = durable_journal
    def guards(manifest, root, **kwargs):
        original_guards(manifest, root, **kwargs)
        for row in manifest["files"]:
            path = base.rooted(root, row["target"])
            base.no_target_link(path)
            if path.exists():
                info = path.stat()
                if row["beforeSha256"] is None:
                    own = next((r for r in (state["journal"] or {}).get("files", []) if r["target"] == row["target"]), {})
                    if not (state["applying"] and own.get("intent") and own.get("written") and
                            base.digest(path) == row["sha256"]):
                        raise ValueError("new_conversation_target_conflict")
                if (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, 0, 0o644):
                    raise ValueError("conversation_target_owner_mode_drift")
    base.guards = guards
    original_apply = base.apply
    def apply(*args, **kwargs):
        if state["applying"]: raise ValueError("conversation_apply_already_active")
        state.update(applying=True, journal=None)
        try: return original_apply(*args, **kwargs)
        finally: state.update(applying=False, journal=None)
    base.apply = apply
    return base


if __name__ == "__main__": load_base().main()
