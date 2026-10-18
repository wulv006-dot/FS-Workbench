"""Build inputs only: layer one reviewed product module over the running image."""

import hashlib
import json
from pathlib import Path

from scope import CURRENT_IMAGE, CURRENT_TAG, NEW_TAG, SOURCE_SHA256, UNIT_BEFORE_SHA256

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UNIT = ROOT / ".agent_runtime/hermes-generic-data-20261018/backend-stage-v3/image-inputs/fc27-p2pah-session.service"
PRODUCT = ROOT / "admin_data_tools_20261018/source/admin_product_orders.py"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(output):
    output = Path(output)
    if output.exists() or not SOURCE_SHA256:
        raise ValueError("new_output_and_frozen_product_source_required")
    unit, product = UNIT.read_bytes(), PRODUCT.read_bytes()
    if sha(unit) != UNIT_BEFORE_SHA256 or unit.count(CURRENT_TAG.encode()) != 1:
        raise ValueError("running_session_unit_baseline_drift")
    if sha(product) != SOURCE_SHA256:
        raise ValueError("frozen_product_source_drift")
    dockerfile = ("FROM " + CURRENT_IMAGE + "\n"
                  "COPY admin_product_orders.py /usr/local/bin/admin_product_orders.py\n"
                  "RUN python3 -B -c 'import ast,pathlib; ast.parse(pathlib.Path(\"/usr/local/bin/admin_product_orders.py\").read_text())'\n").encode()
    new_unit = unit.replace(CURRENT_TAG.encode(), NEW_TAG.encode(), 1)
    build = output / "session-build"
    build.mkdir(parents=True)
    (build / "admin_product_orders.py").write_bytes(product)
    (build / "Dockerfile").write_bytes(dockerfile)
    (output / "fc27-p2pah-session.service").write_bytes(new_unit)
    contract = {"baseImage": CURRENT_IMAGE, "oldTag": CURRENT_TAG, "newTag": NEW_TAG,
                "unit": {"beforeSha256": UNIT_BEFORE_SHA256, "sha256": sha(new_unit)},
                "sourceSha256": SOURCE_SHA256, "dockerfileSha256": sha(dockerfile),
                "productionWrites": 0}
    (output / "session-image-contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract
