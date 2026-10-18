"""Prepare a fresh CAS stage for the three-target product source patch."""

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

from scope import (BACKEND, CURRENT_IMAGE, PRIOR_UI_MANIFEST_SHA256, SCOPE,
                   SOURCE, SOURCE_BEFORE_SHA256, SOURCE_SHA256, UNIT_BEFORE_SHA256)
from prepare_image import prepare as prepare_image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / ".agent_runtime/hermes-generic-data-20261018/ui-stage-final-v3/approved-manifest.json"
PLAN = HERE / "baseline-paths.json"
BASE_PUBLISHER = ROOT / "fs_hermes_conversation_20261018/deploy/release_navigation_base.py"
BASE_SHA = "1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de"
UNITS = {unit: {"ActiveState": "active"} for unit in
         ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service")}
PARALLEL_ACK = {
    "/var/lib/fs-hermes-fc/profile/memories/MEMORY.md": (
        "a2377f14bd592ef850f5b72a75cfc79b3eb6ef3323eed25ad90402c1ba5b739d",
        "88ce337ff5e3e6a00bd524a58b8ec1dc7a2669036a10db3f009c3dfb3320e4e7"),
    "/var/lib/fs-hermes-fc/profile/skills/report-html-authoring/APPLICATIONS.md": (
        "1086c1ba5c75e55b0daf466aeb49131271791d27e06e11a35f417c6219c049c6",
        "a4fa023d5633abebb24dcc89fa390a0abbbc0abb50c1fb75d7c758e11b3e9ef4"),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(baseline_path, output, ack_parallel_drift=False):
    output, baseline_path = Path(output), Path(baseline_path)
    if output.exists() or not SOURCE_SHA256:
        raise ValueError("new_output_and_frozen_source_required")
    prior_raw, plan_raw, baseline_raw = PRIOR.read_bytes(), PLAN.read_bytes(), baseline_path.read_bytes()
    if sha(prior_raw) != PRIOR_UI_MANIFEST_SHA256:
        raise ValueError("successful_ui_manifest_drift")
    prior, plan, baseline = map(json.loads, (prior_raw, plan_raw, baseline_raw))
    if baseline.get("contract") != "fs-hermes-product-patch-live-baseline-v1" or baseline.get("production_writes") != 0:
        raise ValueError("exact_read_only_inventory_required")
    when = dt.datetime.fromisoformat(baseline["observed_at"])
    # Server and workstation clocks can differ by a few seconds; still reject stale reads.
    if when.tzinfo is None or not -30 <= (dt.datetime.now(dt.timezone.utc) - when).total_seconds() <= 3600:
        raise ValueError("baseline_older_than_one_hour")
    if baseline.get("inventoryPlanSha256") != sha(plan_raw) or baseline.get("units") != UNITS:
        raise ValueError("inventory_or_service_drift")
    before = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
    before.update({r["target"]: r["sha256"] for r in prior["immutableAssets"] + prior["targets"]})
    targets = {target for _, target in BACKEND}
    if len(before) != 349 or len(targets) != 3 or set(plan["paths"]) != set(before) or plan["newAllowed"]:
        raise ValueError("prior_full_protected_scope_drift")
    if before["/opt/fs-hermes-fc/admin_product_orders.py"] != SOURCE_BEFORE_SHA256 or \
       before["/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py"] != SOURCE_BEFORE_SHA256 or \
       before["/etc/systemd/system/fc27-p2pah-session.service"] != UNIT_BEFORE_SHA256:
        raise ValueError("three_target_old_sha_drift")
    rows = baseline["files"]
    if len(rows) != 349 or {r["path"] for r in rows} != set(before):
        raise ValueError("all_349_live_paths_required")
    by_path = {r["path"]: r for r in rows}
    acknowledged = []
    for path, expected in before.items():
        row = by_path[path]
        if not row["exists"]:
            raise ValueError("protected_or_target_baseline_drift:" + path)
        if row["sha256"] != expected:
            if not ack_parallel_drift or PARALLEL_ACK.get(path) != (expected, row["sha256"]):
                raise ValueError("protected_or_target_baseline_drift:" + path)
            acknowledged.append({"path": path, "previousApprovedSha256": expected,
                                 "acknowledgedLiveSha256": row["sha256"]})
            before[path] = row["sha256"]
    if ack_parallel_drift and {r["path"] for r in acknowledged} != set(PARALLEL_ACK):
        raise ValueError("exact_two_parallel_drifts_required")
    product = ROOT / SOURCE
    if product.is_symlink() or sha(product.read_bytes()) != SOURCE_SHA256:
        raise ValueError("candidate_product_sha_drift")
    image = prepare_image(output / "image-inputs")
    unit = (output / "image-inputs/fc27-p2pah-session.service").read_bytes()
    candidates = (product.read_bytes(), product.read_bytes(), unit)
    files = []
    for (candidate, target), data in zip(BACKEND, candidates):
        info = by_path[target]
        if (info["uid"], info["gid"], info["mode"], info["links"]) != (0, 0, "0o644", 1):
            raise ValueError("target_owner_mode_drift:" + target)
        staged = output / "candidate" / candidate
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        files.append({"candidate": candidate, "target": target, "beforeSha256": info["sha256"],
                      "sha256": sha(data), "owner": "0:0", "mode": "0o644"})
    protected = [{"path": path, "sha256": before[path]} for path in sorted(set(before) - targets)]
    bridge = HERE / "release_bridge.py"
    lifecycle = HERE / "session_image_lifecycle.py"
    scope = HERE / "scope.py"
    if sha(BASE_PUBLISHER.read_bytes()) != BASE_SHA or any(p.is_symlink() for p in (bridge, lifecycle, scope)):
        raise ValueError("reviewed_publisher_source_drift")
    output.mkdir(exist_ok=True)
    for path, name in ((BASE_PUBLISHER, "release_navigation_base.py"), (bridge, "release_bridge.py"),
                       (lifecycle, "session_image_lifecycle.py"), (scope, "scope.py")):
        shutil.copyfile(path, output / name)
    manifest = {"schemaVersion": 1, "scope": SCOPE, "releaseReady": False,
                "imageId": "sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544",
                "sessionCurrentImage": CURRENT_IMAGE, "sessionImage": image,
                "basePublisherSha256": BASE_SHA, "publisherBridgeSha256": sha(bridge.read_bytes()),
                "imageLifecycleSha256": sha(lifecycle.read_bytes()), "releaseScopeSha256": sha(scope.read_bytes()),
                "files": files, "unchangedRequired": protected, "runtimeRequired": UNITS,
                "businessWrites": False, "timersChanged": False,
                "baselineObservedAt": baseline["observed_at"], "baselineSha256": sha(baseline_raw),
                "inventoryPlanSha256": sha(plan_raw), "priorApprovedManifestSha256": PRIOR_UI_MANIFEST_SHA256,
                "acknowledgedParallelChanges": acknowledged}
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    (output / "approved-manifest.json").write_bytes(manifest_raw)
    (output / "baseline.json").write_bytes(baseline_raw)
    return {"stage": str(output), "manifestSha256": sha(manifest_raw), "files": 3,
            "protected": 346, "releaseReady": False, "productionWrites": 0}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--ack-exact-parallel-drift", action="store_true")
    a = p.parse_args()
    print(json.dumps(prepare(a.baseline, a.stage, a.ack_exact_parallel_drift), ensure_ascii=False, indent=2))
