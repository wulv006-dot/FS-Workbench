"""Pin the successful backend+UI release footprint without copying live bytes."""

import hashlib
import json
from pathlib import Path

from scope import BACKEND, PRIOR_UI_MANIFEST_SHA256

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIOR = ROOT / ".agent_runtime/hermes-generic-data-20261018/ui-stage-final-v3/approved-manifest.json"


def build():
    raw = PRIOR.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRIOR_UI_MANIFEST_SHA256:
        raise ValueError("latest_successful_ui_manifest_drift")
    manifest = json.loads(raw)
    observed = {r["path"] for r in manifest["unchangedRequired"]}
    observed.update(r["target"] for r in manifest["immutableAssets"] + manifest["targets"])
    targets = {target for _, target in BACKEND}
    if len(observed) != 349 or len(targets) != 3 or not targets <= observed:
        raise ValueError("successful_release_footprint_drift")
    return {"contract": "fs-hermes-product-patch-baseline-paths-v1",
            "priorApprovedManifestSha256": PRIOR_UI_MANIFEST_SHA256,
            "paths": sorted(observed), "newAllowed": [], "productionWrites": 0}


if __name__ == "__main__":
    value = build()
    (HERE / "baseline-paths.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"inventoryPaths": len(value["paths"]), "targets": len(BACKEND), "productionWrites": 0}))
