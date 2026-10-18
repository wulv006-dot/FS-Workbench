"""Build-only inputs for the fixed shared-session image; never touches Docker or production."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE = ROOT / ".agent_runtime/hermes-generic-data-20261018/baseline/fc27-p2pah-session.service"
BEFORE_UNIT_SHA = "425ce7db212dcbd353e66deeff5cbc19df804e5bed1dc90e5e84bf002bb82234"
BASE_IMAGE = "sha256:08c381f103f932ca219a72aab5cf360e6584ae321012bf9fee066ffc1d3bc352"
OLD_TAG = "fc27-cloud-session:players-shared-20261018-v1"
NEW_TAG = "fc27-cloud-session:hermes-generic-data-20261018-v1"
UNIT_TARGET = "/etc/systemd/system/fc27-p2pah-session.service"
SESSION_SOURCE = "/opt/fc27-cloud/marketing-session-20261009"
FILES = {
    "p2pah_session_service.py": ROOT / "fs_hermes_generic_data_20261018/source/p2pah_session_service.py",
    "admin_product_orders.py": ROOT / "admin_data_tools_20261018/source/admin_product_orders.py",
    "cohort_paid_source.py": ROOT / "fs_phase2_data_20261018/source/cohort_paid_source.py",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(output):
    output = Path(output)
    if output.exists():
        raise ValueError("new_output_required")
    unit = BASELINE.read_bytes()
    if sha(unit) != BEFORE_UNIT_SHA or unit.count(OLD_TAG.encode()) != 1 or NEW_TAG.encode() in unit:
        raise ValueError("active_session_unit_baseline_drift")
    sources = {}
    for name, path in FILES.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError("candidate_missing_or_linked:" + name)
        sources[name] = path.read_bytes()
    dockerfile = ("FROM " + BASE_IMAGE + "\n"
                  "COPY p2pah_session_service.py admin_product_orders.py cohort_paid_source.py /usr/local/bin/\n"
                  "RUN python3 -B -c 'import ast,pathlib; "
                  "[ast.parse(pathlib.Path(\"/usr/local/bin/\"+n).read_text()) for n in "
                  "(\"p2pah_session_service.py\",\"admin_product_orders.py\",\"cohort_paid_source.py\")]'\n").encode()
    new_unit = unit.replace(OLD_TAG.encode(), NEW_TAG.encode(), 1)
    output.mkdir(parents=True)
    build = output / "session-build"
    build.mkdir()
    for name, raw in sources.items():
        (build / name).write_bytes(raw)
    (build / "Dockerfile").write_bytes(dockerfile)
    (output / "fc27-p2pah-session.service").write_bytes(new_unit)
    contract = {
        "scope": "hermes-generic-data-session-image-20261018",
        "productionWrites": 0,
        "baseImage": BASE_IMAGE,
        "oldTag": OLD_TAG,
        "newTag": NEW_TAG,
        "unit": {"target": UNIT_TARGET, "beforeSha256": BEFORE_UNIT_SHA, "sha256": sha(new_unit)},
        "sources": [{"name": name, "hostTarget": SESSION_SOURCE + "/" + name,
                     "containerTarget": "/usr/local/bin/" + name, "sha256": sha(raw)}
                    for name, raw in sources.items()],
        "dockerfileSha256": sha(dockerfile),
    }
    (output / "session-image-contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return {"newTag": NEW_TAG, "baseImage": BASE_IMAGE, "unitBeforeSha256": BEFORE_UNIT_SHA,
            "unitSha256": sha(new_unit), "sources": len(sources), "productionWrites": 0}
