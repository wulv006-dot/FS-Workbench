"""Exact three-target product-source patch over the reviewed FS publisher."""

import argparse
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import types
from pathlib import Path

SCOPE_SHA = "b8d95b183d3dc923cccce72761a11957356f6959c35e8ecff86fb492fff89e05"
if SCOPE_SHA is None or hashlib.sha256(Path(__file__).with_name("scope.py").read_bytes()).hexdigest() != SCOPE_SHA:
    raise ValueError("frozen_release_scope_changed")
from scope import BACKEND, CURRENT_IMAGE, SCOPE
NEW_ALLOWED = set()

HERE = Path(__file__).resolve().parent
BASE_SHA = "1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de"
TARGETS = dict(BACKEND)
MARKETING_LOCK = "/opt/mmoexp-marketing/data/verified-readonly/collector.lock"
SESSION_UNIT = "/etc/systemd/system/fc27-p2pah-session.service"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_directory(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("private_runtime_directory_link")
    if not path.is_dir():
        raise ValueError("private_runtime_directory_missing_or_wrong_type")
    info = path.stat()
    if os.name == "posix" and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 0, 0o700):
        raise ValueError("private_runtime_directory_owner_or_mode_drift")


def load_base():
    raw = (HERE / "release_navigation_base.py").read_bytes()
    if _sha(raw) != BASE_SHA:
        raise ValueError("frozen_base_publisher_changed")
    source = raw.decode("utf-8")
    replacements = (
        ("HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'", f"HERMES_HISTORY_SCOPE='{SCOPE}'"),
        ("if any(r.get('beforeSha256') is None for r in files if not ((", "if any(r.get('beforeSha256') is None for r in files if r['target'] not in GENERIC_NEW and not (("),
        ("   if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_apply(manifest,backup,journal,root)",
         "   generic_session_apply(manifest,stage,backup,journal,root)\n   if manifest.get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_apply(manifest,backup,journal,root)"),
        (" if journal['manifest'].get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_restore(backup,journal)",
         " generic_session_restore(backup,journal)\n if journal['manifest'].get('scope')==HERMES_CAPABILITY_SCOPE:capability_session_restore(backup,journal)"),
    )
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError("frozen_publisher_seam_changed")
        source = source.replace(before, after)
    base = types.ModuleType("_reviewed_generic_data_publisher")
    base.__file__ = str(HERE / "release_navigation_base.py")
    base.GENERIC_NEW = NEW_ALLOWED
    exec(compile(source, base.__file__, "exec"), base.__dict__)
    base.HERMES_HISTORY_TARGETS = TARGETS
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get("scope") == SCOPE else (_ for _ in ()).throw(ValueError("generic_scope_only"))
    base.target_for = lambda candidate: TARGETS[candidate]

    def lifecycle(manifest):
        path = HERE / "session_image_lifecycle.py"
        data = path.read_bytes()
        if path.is_symlink() or _sha(data) != manifest.get("imageLifecycleSha256"):
            raise ValueError("frozen_image_lifecycle_changed")
        module = types.ModuleType("_reviewed_generic_session_image")
        exec(compile(data, str(path), "exec"), module.__dict__)
        return module

    original_validate = base.validate

    def validate(manifest, stage):
        if manifest.get("scope") != SCOPE or manifest.get("basePublisherSha256") != BASE_SHA:
            raise ValueError("exact_generic_publisher_scope_required")
        if manifest.get("publisherBridgeSha256") != _sha(Path(__file__).read_bytes()):
            raise ValueError("frozen_bridge_changed")
        if manifest.get("businessWrites") is not False or manifest.get("timersChanged") is not False:
            raise ValueError("business_or_timer_boundary_changed")
        if manifest.get("runtimeRequired") != {name: {"ActiveState": "active"} for name in
               ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service")}:
            raise ValueError("three_active_services_required")
        if manifest.get("imageId") != "sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544":
            raise ValueError("hermes_image_drift")
        if manifest.get("sessionCurrentImage") != CURRENT_IMAGE or manifest.get("releaseScopeSha256") != SCOPE_SHA:
            raise ValueError("current_session_image_or_scope_drift")
        rows = original_validate(manifest, stage)
        if {r["candidate"]: r["target"] for r in rows} != TARGETS:
            raise ValueError("target_allowlist_drift")
        if any(r.get("beforeSha256") is None for r in rows):
            raise ValueError("existing_three_targets_required")
        unit_row = next(r for r in rows if r["target"] == SESSION_UNIT)
        image = lifecycle(manifest)
        unit = (stage / "candidate" / unit_row["candidate"]).read_bytes()
        if unit.count(image.NEW.encode()) != 1 or _sha(unit.replace(image.NEW.encode(), image.OLD.encode())) != unit_row["beforeSha256"]:
            raise ValueError("session_unit_unrelated_change")
        staged = stage / "image-inputs/session-build"
        image_contract = json.loads((stage / "image-inputs/session-image-contract.json").read_text("utf-8"))
        if image_contract != manifest["sessionImage"]:
            raise ValueError("session_build_contract_drift")
        desired = {r["target"]: r["sha256"] for r in rows}
        for name in image.NAMES:
            target = image.HOST + name
            if _sha((staged / name).read_bytes()) != desired[target]:
                raise ValueError("image_input_not_same_as_host_candidate")
        if _sha((staged / "Dockerfile").read_bytes()) != image_contract["dockerfileSha256"]:
            raise ValueError("image_dockerfile_drift")
        return rows

    base.validate = validate
    original_inspect = base.inspect

    def inspect(manifest, stage, root=Path("/")):
        result = original_inspect(manifest, stage, root)
        if root == Path("/") and os.name == "posix":
            candidate = (stage / "candidate/source/hermes").resolve(strict=True)
            live = Path("/opt/fs-hermes-fc")
            program = (
                "import sys;from pathlib import Path;"
                "candidate=Path(sys.argv[1]);live=Path(sys.argv[2]);"
                "sys.path[:0]=[str(candidate),str(live)];"
                "import admin_product_orders,controller;"
                "assert Path(admin_product_orders.__file__).resolve()==candidate/'admin_product_orders.py';"
                "assert Path(controller.__file__).resolve()==live/'controller.py'"
            )
            try:
                composed = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(candidate), str(live)],
                                          cwd="/", capture_output=True, timeout=25, check=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("generic_composed_import_unavailable") from error
            if composed.returncode:
                raise ValueError("generic_composed_import_failed")
            lifecycle(manifest).baseline(manifest)
        return result

    base.inspect = inspect
    original_quiescent = base.hermes_quiescent

    def quiescent(root):
        original_quiescent(root)
        path = base.rooted(root, "/var/lib/fs-hermes-fc/fs/conversations/conversations.db")
        base.no_target_link(path)
        if path.exists():
            with contextlib.closing(sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)) as db:
                count = db.execute("SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')").fetchone()[0]
                if count:
                    raise ValueError("active_or_unknown_conversation_run")
        monitor_root = base.rooted(root, "/var/lib/fs-business-ranges/fc-detail/cohort-observations")
        private_directory(monitor_root)
        for monitor in monitor_root.glob("*.monitor.json"):
            base.no_target_link(monitor)
            if json.loads(monitor.read_text("utf-8")).get("last_status") == "pending":
                raise ValueError("pending_cohort_monitor_requires_reconciliation")

    base.hermes_quiescent = quiescent
    original_guards = base.guards
    current = {"journal": None}
    original_write = base.journal_write

    def write_journal(backup, journal):
        current["journal"] = journal
        return original_write(backup, journal)

    base.journal_write = write_journal

    def guards(manifest, root, reader_stopped=False):
        original_guards(manifest, root, reader_stopped)
        attempts = base.rooted(root, "/var/lib/fs-hermes-fc/fs/es-structures")
        private_directory(attempts)
        if any(attempts.glob("*.attempt")):
            raise ValueError("es_attempt_requires_reconciliation")
        for row in manifest["files"]:
            path = base.rooted(root, row["target"])
            base.no_target_link(path)
            if path.exists():
                info = path.stat()
                if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o644, 1):
                    raise ValueError("target_owner_mode_drift")
                if row["beforeSha256"] is None:
                    own = next((r for r in (current["journal"] or {}).get("files", []) if r["target"] == row["target"]), {})
                    if not (own.get("intent") and own.get("written") and base.digest(path) == row["sha256"]):
                        raise ValueError("new_target_conflict")

    base.guards = guards
    base.session_lifecycle = lifecycle
    def generic_session_apply(manifest, stage, backup, journal, root):
        if manifest.get("scope") == SCOPE:
            return base.session_lifecycle(manifest).apply(manifest, stage, backup, journal, root,
                                                          base.atomic, base.journal_write, base.digest, base.no_target_link)
    def generic_session_restore(backup, journal):
        if journal["manifest"].get("scope") == SCOPE:
            return base.session_lifecycle(journal["manifest"]).restore(backup, journal, base.journal_write)
    base.generic_session_apply = generic_session_apply
    base.generic_session_restore = generic_session_restore
    original_restart = base.restart_for

    def restart(manifest, fence=None):
        if manifest.get("scope") != SCOPE:
            return original_restart(manifest, fence)
        if fence is None:
            raise ValueError("hermes_admission_fence_required")
        fence.stop_then_unlock_database()
        original_restart(dict(manifest, scope=base.HERMES_WORKER_SCOPE), fence)
        original_restart(dict(manifest, scope=base.DEEP_SCOPE), fence)

    base.restart_for = restart
    original_locks = base.locks

    @contextlib.contextmanager
    def locks(root):
        import fcntl
        with original_locks(root):
            path = base.rooted(root, MARKETING_LOCK)
            base.no_target_link(path)
            fd = os.open(str(path), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o600, 1):
                    raise ValueError("marketing_collector_lock_boundary")
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                os.close(fd)

    base.locks = locks
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "apply", "rollback"), nargs="?", default="inspect")
    parser.add_argument("--manifest", type=Path, default=HERE / "approved-manifest.json")
    parser.add_argument("--approved-manifest-sha")
    parser.add_argument("--release-id")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.action != "inspect" and os.name != "posix":
        raise ValueError("release_mutations_require_reviewed_linux_host")
    base = load_base()
    if args.action == "rollback":
        if not args.backup or args.backup.parent != Path("/var/backups/fs-navigation-20261006"):
            raise ValueError("exact_backup_parent_required")
        result = base.rollback(args.backup, args.approved_manifest_sha)
    else:
        raw = args.manifest.read_bytes()
        manifest = json.loads(raw)
        result = base.inspect(manifest, args.manifest.parent) if args.action == "inspect" else base.apply(
            manifest, args.manifest.parent, args.approved_manifest_sha, raw, args.release_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
