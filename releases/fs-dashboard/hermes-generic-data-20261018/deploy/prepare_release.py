"""Freeze a reviewed backend stage from a fresh, exact read-only production inventory."""

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from release_scope import BACKEND, FROZEN, NEW_ALLOWED, SCOPE, SOURCE_SHA256
from prepare_session_image import BASE_IMAGE, FILES as SESSION_FILES, prepare as prepare_image
from release_bridge import BASE_SHA, SCOPE_SHA


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAN = HERE / "baseline-paths.json"
PRIOR = ROOT / ".agent_runtime/hermes-data-workspace-20261018/tools-page/stage-final-v1/approved-manifest.json"
PRIOR_SHA = "431bd905d1a48d1d1c3756cebb5c6ca42b79f2f244511c82a17f1cf17532cc54"
REQUIRED_UNITS = {name: {"ActiveState": "active"} for name in
                  ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(baseline_path, output):
    baseline_path, output = Path(baseline_path), Path(output)
    if not FROZEN:
        raise ValueError("exact_scope_not_frozen")
    if output.exists():
        raise ValueError("new_output_required")
    plan_raw, prior_raw, baseline_raw = PLAN.read_bytes(), PRIOR.read_bytes(), baseline_path.read_bytes()
    if sha(prior_raw) != PRIOR_SHA:
        raise ValueError("prior_approved_manifest_drift")
    plan, prior, baseline = map(json.loads, (plan_raw, prior_raw, baseline_raw))
    if baseline.get("contract") != "fs-hermes-generic-data-live-baseline-v1" or baseline.get("production_writes") != 0:
        raise ValueError("fresh_read_only_baseline_required")
    when = dt.datetime.fromisoformat(baseline["observed_at"])
    if when.tzinfo is None or not 0 <= (dt.datetime.now(dt.timezone.utc) - when).total_seconds() <= 3600:
        raise ValueError("baseline_must_be_new_within_one_hour")
    if baseline.get("inventoryPlanSha256") != sha(plan_raw) or baseline.get("units") != REQUIRED_UNITS:
        raise ValueError("inventory_or_runtime_drift")
    paths = set(plan["paths"])
    rows = baseline["files"]
    if len(rows) != len(paths) or {r["path"] for r in rows} != paths:
        raise ValueError("complete_exact_inventory_required")
    by_path = {r["path"]: r for r in rows}
    before = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
    before.update({r["target"]: r["sha256"] for r in prior["targets"] + prior["immutableAssets"]})
    targets = {target for _, _, target in BACKEND}
    if len(targets) != len(BACKEND) or not NEW_ALLOWED <= targets or paths != set(before) | targets:
        raise ValueError("fixed_target_map_drift")
    for path, expected in before.items():
        row = by_path[path]
        if not row["exists"] or row["sha256"] != expected:
            raise ValueError("protected_or_before_sha_drift:" + path)
    image_stage = output / "image-inputs"
    prepare_image(image_stage)
    image_contract = json.loads((image_stage / "session-image-contract.json").read_text("utf-8"))
    if image_contract["baseImage"] != BASE_IMAGE or {r["name"] for r in image_contract["sources"]} != set(SESSION_FILES):
        raise ValueError("session_image_contract_drift")
    files = []
    for local, candidate, target in BACKEND:
        source = image_stage / "fc27-p2pah-session.service" if local == "@generated-session-unit" else ROOT / local
        if not source.is_file() or source.is_symlink():
            raise ValueError("candidate_missing_or_linked:" + candidate)
        old = by_path[target]
        if old["exists"]:
            if (old["uid"], old["gid"], old["links"], old["mode"]) != (0, 0, 1, "0o644"):
                raise ValueError("target_owner_mode_drift:" + target)
        elif target not in NEW_ALLOWED or old.get("sha256") is not None:
            raise ValueError("new_target_outside_allowlist:" + target)
        raw = source.read_bytes()
        if local != "@generated-session-unit" and sha(raw) != SOURCE_SHA256.get(local):
            raise ValueError("reviewed_source_sha_drift:" + local)
        row = {"candidate": candidate, "target": target, "beforeSha256": old["sha256"],
               "sha256": sha(raw), "mode": "0o644", "owner": "0:0"}
        files.append(row)
        staged = output / "candidate" / candidate
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(raw)
    paired = {r["target"]: r["sha256"] for r in files}
    for name in ("admin_product_orders.py", "cohort_paid_source.py"):
        if paired["/opt/fs-hermes-fc/" + name] != paired["/opt/fc27-cloud/marketing-session-20261009/" + name]:
            raise ValueError("hermes_and_session_source_diverged:" + name)
    protected = [{"path": path, "sha256": before[path]} for path in sorted(set(before) - targets)]
    publisher = ROOT / "fs_hermes_conversation_20261018/deploy/release_navigation_base.py"
    bridge = HERE / "release_bridge.py"
    lifecycle = HERE / "session_image_lifecycle.py"
    if (sha(publisher.read_bytes()) != BASE_SHA or sha((HERE / "release_scope.py").read_bytes()) != SCOPE_SHA
            or bridge.is_symlink() or lifecycle.is_symlink()):
        raise ValueError("reviewed_publisher_source_drift")
    for source, name in ((publisher, "release_navigation_base.py"), (HERE / "release_scope.py", "release_scope.py"),
                         (bridge, "release_bridge.py"),
                         (lifecycle, "session_image_lifecycle.py")):
        shutil.copyfile(source, output / name)
    tree_sha = sha(b"".join((r["candidate"] + "\0" + r["sha256"] + "\n").encode("utf-8") for r in sorted(files, key=lambda row: row["candidate"])))
    manifest = {"schemaVersion": 1, "scope": SCOPE, "releaseReady": False,
                "candidateTreeSha256": tree_sha,
                "imageId": "sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544",
                "basePublisherSha256": BASE_SHA,
                "releaseScopeSha256": SCOPE_SHA,
                "publisherBridgeSha256": sha(bridge.read_bytes()),
                "imageLifecycleSha256": sha(lifecycle.read_bytes()),
                "sessionImage": image_contract, "files": files, "unchangedRequired": protected,
                "runtimeRequired": REQUIRED_UNITS, "businessWrites": False, "timersChanged": False,
                "baselineObservedAt": baseline["observed_at"], "baselineSha256": sha(baseline_raw),
                "inventoryPlanSha256": sha(plan_raw), "priorApprovedManifestSha256": PRIOR_SHA}
    (output / "approved-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "baseline.json").write_bytes(baseline_raw)
    return {"stage": str(output), "manifestSha256": sha((output / "approved-manifest.json").read_bytes()),
            "files": len(files), "protected": len(protected), "releaseReady": False, "productionWrites": 0}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.baseline, a.stage), ensure_ascii=False, indent=2))
