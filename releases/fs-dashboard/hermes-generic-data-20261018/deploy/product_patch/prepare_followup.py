"""Prepare the next exact product patch from the successful 349-file release.

This creates a new stage; it never edits the frozen first patch or production.
"""

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE / "baseline-paths.json"
BASE = ROOT / "fs_hermes_conversation_20261018/deploy/release_navigation_base.py"
SOURCE = ROOT / "admin_data_tools_20261018/source/admin_product_orders.py"
PREVIOUS_SHA = "89099e921d978730de690d4d1c5d0148cff60ae05faf729c2d7a91098336e4f6"
SOURCE_SHA = "5084bfcfba86e422925911d87983e6642f630abcd5da3cb0c5b50788fafb296a"
CURRENT_IMAGE = "sha256:b9b65002d1d0d6bc08f412cbd3efcb097ad75e9d5d350fda1af765c1319efeab"
CURRENT_TAG = "fc27-cloud-session:hermes-product-match-20261018-v1"
NEW_TAG = "fc27-cloud-session:hermes-product-match-20261018-v2"
NEW_SCOPE = "fs-hermes-product-orders-20261018-v2"
V3_PREVIOUS_SHA = "6cd64c41c4031894cec2c3e700f003551862d224b51e21a4777377127fe69642"
V3_SOURCE_SHA = "0a8a09b113b2ee4f9577ddcb1ac8e9eb992d92bca3b3543e9b9fa76472e52243"
V3_CURRENT_IMAGE = "sha256:1544c4b6c78ba985ae1b922e746764f4923ddbec3227623321b2c6783ebdef43"
V3_CURRENT_TAG = NEW_TAG
V3_NEW_TAG = "fc27-cloud-session:hermes-product-match-20261018-v3"
V3_SCOPE = "fs-hermes-product-orders-20261018-v3"
BASE_SHA = "1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de"
TEMPLATE_SHA = {
    "scope.py": "b8d95b183d3dc923cccce72761a11957356f6959c35e8ecff86fb492fff89e05",
    "release_bridge.py": "893f8528cfe283afec1e53fbd3540b324362797dc93fb7386c9b5c07c2a6152b",
    "session_image_lifecycle.py": "f10546b83d0c8d11b5b2f9155aa94eb54a0bc44c52ef6123c8fe95fbad911f97",
}
TARGETS = (
    ("source/hermes/admin_product_orders.py", "/opt/fs-hermes-fc/admin_product_orders.py"),
    ("source/session/admin_product_orders.py", "/opt/fc27-cloud/marketing-session-20261009/admin_product_orders.py"),
    ("source/session/fc27-p2pah-session.service", "/etc/systemd/system/fc27-p2pah-session.service"),
)
UNITS = {unit: {"ActiveState": "active"} for unit in
         ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def exact_replace(raw, old, new):
    if raw.count(old) != 1:
        raise ValueError("frozen_template_seam_changed:" + old[:60])
    return raw.replace(old, new)


def template(name):
    path = HERE / name
    if path.is_symlink() or sha(path.read_bytes()) != TEMPLATE_SHA[name]:
        raise ValueError("frozen_publisher_template_changed:" + name)
    return path.read_text("utf-8")


def scope_code(previous_source, previous_unit, config):
    raw = template("scope.py")
    updates = {
        "SCOPE": config["scope"],
        "SOURCE_SHA256": config["sourceSha"],
        "CURRENT_IMAGE": config["image"],
        "CURRENT_TAG": config["currentTag"],
        "NEW_TAG": config["newTag"],
        "UNIT_BEFORE_SHA256": previous_unit,
        "SOURCE_BEFORE_SHA256": previous_source,
        "PRIOR_UI_MANIFEST_SHA256": config["previousSha"],
    }
    for name, value in updates.items():
        old = next((line for line in raw.splitlines() if line.startswith(name + " = ")), None)
        if old is None:
            raise ValueError("frozen_scope_field_missing:" + name)
        raw = exact_replace(raw, old + "\n", name + " = " + json.dumps(value) + "\n")
    return raw.encode()


def lifecycle_code(config):
    raw = template("session_image_lifecycle.py")
    for name, value in (("BASE", config["image"]), ("OLD", config["currentTag"]),
                        ("NEW", config["newTag"])):
        old = next((line for line in raw.splitlines() if line.startswith(name + " = ")), None)
        if old is None:
            raise ValueError("frozen_image_field_missing:" + name)
        raw = exact_replace(raw, old + "\n", name + " = " + json.dumps(value) + "\n")
    return raw.encode()


def bridge_code(scope_sha):
    raw = template("release_bridge.py")
    old = next((line for line in raw.splitlines() if line.startswith("SCOPE_SHA = ")), None)
    if old is None:
        raise ValueError("frozen_bridge_scope_pin_missing")
    raw = exact_replace(raw, old + "\n", "SCOPE_SHA = " + json.dumps(scope_sha) + "\n")
    return raw.encode()


def prepare(previous_path, baseline_path, output, source_path, source_sha,
            current_image_id, current_tag, new_tag, profile="v2"):
    configs = {
        "v2": {"previousSha": PREVIOUS_SHA, "sourceSha": SOURCE_SHA,
               "image": CURRENT_IMAGE, "currentTag": CURRENT_TAG,
               "newTag": NEW_TAG, "scope": NEW_SCOPE, "previousScope": "fs-hermes-product-orders-20261018-v1"},
        "v3": {"previousSha": V3_PREVIOUS_SHA, "sourceSha": V3_SOURCE_SHA,
               "image": V3_CURRENT_IMAGE, "currentTag": V3_CURRENT_TAG,
               "newTag": V3_NEW_TAG, "scope": V3_SCOPE, "previousScope": NEW_SCOPE},
    }
    if profile not in configs or not configs[profile]["sourceSha"]:
        raise ValueError("reviewed_followup_profile_and_source_required")
    config = configs[profile]
    previous_path, baseline_path, output, source_path = map(Path,
        (previous_path, baseline_path, output, source_path))
    if output.exists() or source_path.resolve() != SOURCE.resolve() or source_path.is_symlink():
        raise ValueError("new_output_and_exact_source_required")
    if (source_sha, current_image_id, current_tag, new_tag) != (
            config["sourceSha"], config["image"], config["currentTag"], config["newTag"]):
        raise ValueError("frozen_source_or_image_identity_drift")
    previous_raw, baseline_raw, plan_raw = (path.read_bytes() for path in
                                            (previous_path, baseline_path, PLAN))
    if sha(previous_raw) != config["previousSha"] or sha(BASE.read_bytes()) != BASE_SHA or BASE.is_symlink():
        raise ValueError("successful_previous_release_or_base_publisher_drift")
    previous, baseline, plan = map(json.loads, (previous_raw, baseline_raw, plan_raw))
    if previous.get("scope") != config["previousScope"] or len(previous.get("files", [])) != 3:
        raise ValueError("successful_previous_scope_required")
    before = {row["path"]: row["sha256"] for row in previous["unchangedRequired"]}
    before.update({row["target"]: row["sha256"] for row in previous["files"]})
    if len(before) != 349 or len(previous["unchangedRequired"]) != 346 or \
       {row["target"] for row in previous["files"]} != {target for _, target in TARGETS}:
        raise ValueError("previous_complete_349_scope_required")
    if plan.get("newAllowed") or set(plan["paths"]) != set(before):
        raise ValueError("fixed_inventory_plan_drift")
    if baseline.get("contract") != "fs-hermes-product-patch-live-baseline-v1" or \
       baseline.get("production_writes") != 0 or baseline.get("inventoryPlanSha256") != sha(plan_raw) or \
       baseline.get("units") != UNITS:
        raise ValueError("fresh_read_only_inventory_required")
    when = dt.datetime.fromisoformat(baseline["observed_at"])
    if when.tzinfo is None or not -30 <= (dt.datetime.now(dt.timezone.utc) - when).total_seconds() <= 3600:
        raise ValueError("baseline_older_than_one_hour")
    rows = baseline["files"]
    if len(rows) != 349 or {r["path"] for r in rows} != set(before):
        raise ValueError("all_349_live_paths_required")
    by_path = {r["path"]: r for r in rows}
    for path, expected in before.items():
        if not by_path[path]["exists"] or by_path[path]["sha256"] != expected:
            raise ValueError("protected_or_target_baseline_drift:" + path)
    source = source_path.read_bytes()
    if sha(source) != config["sourceSha"]:
        raise ValueError("candidate_source_sha_drift")
    product_targets = (TARGETS[0][1], TARGETS[1][1])
    if before[product_targets[0]] != before[product_targets[1]]:
        raise ValueError("two_host_product_baseline_mismatch")
    unit_target = TARGETS[2][1]
    previous_unit_path = previous_path.parent / "candidate" / TARGETS[2][0]
    if previous_unit_path.is_symlink():
        raise ValueError("previous_staged_unit_link")
    unit = previous_unit_path.read_bytes()
    if sha(unit) != before[unit_target] or unit.count(config["currentTag"].encode()) != 1 or \
       config["newTag"].encode() in unit:
        raise ValueError("previous_staged_unit_or_tag_drift")
    if previous["sessionImage"]["newTag"] != config["currentTag"] or \
       previous["sessionImage"]["sourceSha256"] != before[product_targets[0]]:
        raise ValueError("previous_session_image_contract_drift")
    new_unit = unit.replace(config["currentTag"].encode(), config["newTag"].encode(), 1)
    scope = scope_code(before[product_targets[0]], before[unit_target], config)
    lifecycle = lifecycle_code(config)
    bridge = bridge_code(sha(scope))
    dockerfile = ("FROM " + config["image"] + "\n"
                  "COPY admin_product_orders.py /usr/local/bin/admin_product_orders.py\n"
                  "RUN python3 -B -c 'import ast,pathlib; ast.parse(pathlib.Path(\"/usr/local/bin/admin_product_orders.py\").read_text())'\n").encode()
    contract = {"baseImage": config["image"], "oldTag": config["currentTag"], "newTag": config["newTag"],
                "unit": {"beforeSha256": before[unit_target], "sha256": sha(new_unit)},
                "sourceSha256": config["sourceSha"], "dockerfileSha256": sha(dockerfile), "productionWrites": 0}
    files = []
    for (candidate, target), data in zip(TARGETS, (source, source, new_unit)):
        info = by_path[target]
        if (info["uid"], info["gid"], info["mode"], info["links"]) != (0, 0, "0o644", 1):
            raise ValueError("target_owner_mode_drift:" + target)
        files.append({"candidate": candidate, "target": target, "beforeSha256": before[target],
                      "sha256": sha(data), "owner": "0:0", "mode": "0o644"})
    output.mkdir(parents=True)
    for candidate, data in zip((row["candidate"] for row in files), (source, source, new_unit)):
        path = output / "candidate" / candidate
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    build = output / "image-inputs/session-build"
    build.mkdir(parents=True)
    (build / "admin_product_orders.py").write_bytes(source)
    (build / "Dockerfile").write_bytes(dockerfile)
    (output / "image-inputs/fc27-p2pah-session.service").write_bytes(new_unit)
    (output / "image-inputs/session-image-contract.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    for name, data in (("release_navigation_base.py", BASE.read_bytes()),
                       ("scope.py", scope), ("release_bridge.py", bridge),
                       ("session_image_lifecycle.py", lifecycle)):
        (output / name).write_bytes(data)
    manifest = {"schemaVersion": 1, "scope": config["scope"], "releaseReady": False,
                "imageId": previous["imageId"], "sessionCurrentImage": config["image"],
                "sessionImage": contract, "basePublisherSha256": BASE_SHA,
                "publisherBridgeSha256": sha(bridge), "imageLifecycleSha256": sha(lifecycle),
                "releaseScopeSha256": sha(scope), "files": files,
                "unchangedRequired": [{"path": path, "sha256": before[path]}
                                      for path in sorted(set(before) - {t for _, t in TARGETS})],
                "runtimeRequired": UNITS, "businessWrites": False, "timersChanged": False,
                "baselineObservedAt": baseline["observed_at"], "baselineSha256": sha(baseline_raw),
                "inventoryPlanSha256": sha(plan_raw), "priorApprovedManifestSha256": config["previousSha"],
                "acknowledgedParallelChanges": []}
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    (output / "approved-manifest.json").write_bytes(raw)
    (output / "baseline.json").write_bytes(baseline_raw)
    return {"stage": str(output), "manifestSha256": sha(raw), "files": 3,
            "protected": 346, "releaseReady": False, "productionWrites": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--current-image-id", required=True)
    parser.add_argument("--current-tag", required=True)
    parser.add_argument("--new-tag", required=True)
    parser.add_argument("--profile", choices=("v2", "v3"), default="v2")
    args = parser.parse_args()
    print(json.dumps(prepare(args.previous_manifest, args.baseline, args.stage, args.source,
                             args.source_sha, args.current_image_id, args.current_tag, args.new_tag,
                             args.profile),
                     ensure_ascii=False, indent=2))
