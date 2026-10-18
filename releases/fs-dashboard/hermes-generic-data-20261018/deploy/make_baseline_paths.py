"""Freeze the protected prior UI footprint plus this release's exact targets."""

import hashlib
import json
from pathlib import Path

from release_scope import BACKEND, NEW_ALLOWED


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / ".agent_runtime/hermes-data-workspace-20261018/tools-page/stage-final-v1/approved-manifest.json"
PRIOR_SHA = "431bd905d1a48d1d1c3756cebb5c6ca42b79f2f244511c82a17f1cf17532cc54"


def build():
    raw = PRIOR.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRIOR_SHA:
        raise ValueError("prior_approved_ui_manifest_drift")
    prior = json.loads(raw)
    observed = {row["path"] for row in prior["unchangedRequired"]}
    observed.update(row["target"] for row in prior["targets"] + prior["immutableAssets"])
    if len(observed) != 345:
        raise ValueError("prior_protected_footprint_drift")
    targets = {target for _, _, target in BACKEND}
    if len(targets) != len(BACKEND) or not NEW_ALLOWED <= targets:
        raise ValueError("exact_backend_target_map_required")
    return {"contract": "fs-hermes-generic-data-baseline-paths-v1",
            "priorApprovedManifestSha256": PRIOR_SHA,
            "paths": sorted(observed | targets), "newAllowed": sorted(NEW_ALLOWED),
            "productionWrites": 0}


if __name__ == "__main__":
    value = build()
    path = HERE / "baseline-paths.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "protectedPrior": 345,
                      "inventoryPaths": len(value["paths"]), "productionWrites": 0}))
