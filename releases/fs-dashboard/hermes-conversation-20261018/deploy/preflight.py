"""Freeze exact source bytes against a fresh complete read-only server baseline."""

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path

from release_scope import NEW_ALLOWED, SCOPE, TARGETS


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = HERE / "release_navigation_base.py"
BASE_SHA = "1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de"
IMAGE = "sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544"


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(baseline, source_commit, stage, release_ready=False):
    if stage.exists(): raise ValueError("new_stage_required")
    if not re.fullmatch(r"[a-f0-9]{40}", source_commit): raise ValueError("exact_source_commit_required")
    observed = json.loads(baseline.read_text("utf-8"))
    if observed.get("contract") != "fs-hermes-conversation-baseline-v1" or observed.get("production_writes") != 0:
        raise ValueError("fresh_read_only_baseline_required")
    when = dt.datetime.fromisoformat(observed["observed_at"])
    if when.tzinfo is None or not 0 <= (dt.datetime.now(dt.timezone.utc) - when).total_seconds() <= 3600:
        raise ValueError("baseline_must_be_new_within_one_hour")
    paths = set(json.loads((HERE / "baseline-paths.json").read_text())["paths"])
    rows = observed["files"]
    if len(rows) != len(paths) or {r["path"] for r in rows} != paths:
        raise ValueError("complete_exact_baseline_required")
    if observed.get("units") != {"fs-business-range.service": {"ActiveState": "active"},
                                  "fs-hermes-fc.service": {"ActiveState": "active"}}:
        raise ValueError("active_services_required")
    by_path = {r["path"]: r for r in rows}
    files = []
    for relative, target in TARGETS.items():
        source = ROOT / relative
        if not source.is_file() or source.is_symlink(): raise ValueError("candidate_missing_or_linked: " + relative)
        row = by_path[target]
        if row["exists"]:
            if (row["uid"], row["gid"], row["links"], row["mode"]) != (0, 0, 1, "0o644"):
                raise ValueError("target_owner_mode_drift: " + target)
            if not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]): raise ValueError("target_sha_missing: " + target)
        elif target not in NEW_ALLOWED or row.get("sha256") is not None:
            raise ValueError("new_target_baseline_drift: " + target)
        files.append({"candidate": relative, "target": target, "beforeSha256": row["sha256"],
                      "sha256": digest(source), "mode": "0o644", "owner": "0:0"})
    protected = [{"path": path, "sha256": row["sha256"]} for path, row in sorted(by_path.items())
                 if path not in TARGETS.values() and row["exists"]]
    manifest = {"schemaVersion": 1, "scope": SCOPE, "releaseReady": release_ready,
                "sourceCommit": source_commit, "imageId": IMAGE, "files": files,
                "unchangedRequired": protected,
                "runtimeRequired": observed["units"], "businessWrites": False, "timersChanged": False,
                "baselineObservedAt": observed["observed_at"], "baselineSha256": digest(baseline)}
    if digest(BASE) != BASE_SHA: raise ValueError("frozen_publisher_drift")
    stage.mkdir(parents=True)
    for row in files:
        target = stage / "candidate" / row["candidate"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / row["candidate"], target)
    (stage / "approved-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (stage / "baseline.json").write_bytes(baseline.read_bytes())
    for name, source in (("release_navigation_base.py", BASE), ("release_bridge.py", HERE / "release_bridge.py"),
                         ("release_scope.py", HERE / "release_scope.py")):
        shutil.copyfile(source, stage / name)
    return {"stage": str(stage), "manifestSha256": digest(stage / "approved-manifest.json"),
            "files": len(files), "protected": len(protected), "releaseReady": release_ready, "productionWrites": 0}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--release-ready", action="store_true")
    a = p.parse_args()
    print(json.dumps(prepare(a.baseline, a.source_commit, a.stage, a.release_ready), indent=2))
