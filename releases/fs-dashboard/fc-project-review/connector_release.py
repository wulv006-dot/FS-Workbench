"""Package a one-operation FS connector image using its existing 187 updater."""
import argparse
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2] if len(HERE.parents) > 2 else HERE
BASE = "sha256:18a4c07741382bef8a99e0c3967d7b31a0c9a4d21e0a6d080018f706dd379088"
BASE_TAG = "fs-data-connector:stage5-methods-27fe096"
ACTIVE_CATALOG_SHA = "07c81c4615d5c30aeee969f145a3c4c09971030f445682eb3330f2a70394a598"
UNIT_SHA = "e353ddb0c4ac846086675f331fc3e8331260ff7ff965ff2156e4598c5f7f9ffb"
FC_REVIEW = "business.fc_project_review"
OPERATION = FC_REVIEW
REVISION_UPDATE = "fc-project-review-revision"
COVERAGE_MODULE = "unified-business"
GUIDE = None
BACKUP_PREFIX = "fc-review-"
STAGE_BASE_TAG = False
VIP = "customer_tracking.vip_period"
RELEASES = {
    OPERATION: (BASE, BASE_TAG, ACTIVE_CATALOG_SHA, UNIT_SHA, COVERAGE_MODULE, GUIDE, BACKUP_PREFIX, STAGE_BASE_TAG),
    VIP: ("sha256:df7460f18eb00e12e7b9bec49d3532ea84a5d1fa5a218a3857350bbfc1c0f964",
          "fs-data-connector:vip-base-df7460f18eb0",
          "0d89dbf057d9445ad16d4305acc9b73fd51a6793cd0c19ebf6470bdafcb826cd",
          "839f863a54ec3150d8b1c0850b6f6ccf6ca17c004fa2fbe785e5cb4ee560ecd5",
          "customer-tracking", "customer_business_details", "customer-vip-preferred-", True),
}
PUBLISHER = REPO / "docs/planning/fs-data-connector-20261109/deploy/connector"
PUBLISHER_FILES = ("update_connector_image_187.py", "install_connector_187.py",
                   "fs-data-connector.service.in", "client_public_probe.py", "connector_smoke.py")


def select_release(operation, *, base_image=None, active_catalog_sha=None, unit_sha=None):
    global OPERATION, BASE, BASE_TAG, ACTIVE_CATALOG_SHA, UNIT_SHA, COVERAGE_MODULE, GUIDE, BACKUP_PREFIX, STAGE_BASE_TAG
    if operation == REVISION_UPDATE:
        if not base_image or not re.fullmatch(r"sha256:[0-9a-f]{64}", base_image):
            raise ValueError("fixed_live_base_image_required")
        for digest in (active_catalog_sha, unit_sha):
            if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("fixed_live_base_digest_required")
        tag = "fs-data-connector:fc-review-revision-base-" + base_image[7:19]
        config = (base_image, tag, active_catalog_sha, unit_sha, "unified-business", None,
                  "fc-review-revision-", True)
    else:
        if operation not in RELEASES:
            raise ValueError("unknown_connector_release_operation")
        config = RELEASES[operation]
    OPERATION = operation
    BASE, BASE_TAG, ACTIVE_CATALOG_SHA, UNIT_SHA, COVERAGE_MODULE, GUIDE, BACKUP_PREFIX, STAGE_BASE_TAG = config


def verify_catalog(active, proposed):
    expected = deepcopy(proposed)
    additions = [operation for operation in expected["operations"] if operation["name"] == OPERATION]
    if len(additions) != 1 or additions[0]["module"] != COVERAGE_MODULE:
        raise ValueError("one_new_operation_required")
    if OPERATION == VIP:
        prior = [operation for operation in active["operations"] if operation["name"] == OPERATION]
        properties = additions[0]["input_schema"]["properties"]
        if len(prior) != 1 or properties.pop("scope", None) != {"type": "string", "enum": ["uk_us", "global_preferred"]}:
            raise ValueError("one_optional_vip_scope_required")
        additions[0]["description"] = prior[0]["description"]
        if expected != active:
            raise ValueError("unrelated_catalog_change")
        return
    expected["operations"].remove(additions[0])
    modules = [module for module in expected["coverage"] if module["module"] == COVERAGE_MODULE]
    if len(modules) != 1:
        raise ValueError("one_operation_coverage_module_required")
    modules[0]["operations"] -= 1
    if GUIDE is not None:
        guides = [guide for guide in expected["data_methods"]["guides"] if guide["id"] == GUIDE]
        if len(guides) != 1 or guides[0]["operations"].count(OPERATION) != 1:
            raise ValueError("one_operation_guide_reference_required")
        guides[0]["operations"].remove(OPERATION)
    if expected != active:
        raise ValueError("unrelated_catalog_change")


def revision_catalog(active, reviewed):
    candidate = deepcopy(active)
    current = [item for item in candidate["operations"] if item["name"] == FC_REVIEW]
    reference = [item for item in reviewed["operations"] if item["name"] == FC_REVIEW]
    if len(current) != 1 or len(reference) != 1:
        raise ValueError("existing_fc_operation_required")
    before = deepcopy(reference[0])
    schema = before["input_schema"]["properties"].pop("revision", None)
    if schema != {"type": "string", "maxLength": 64, "pattern": "[0-9a-f]{64}"}:
        raise ValueError("optional_fc_revision_schema_required")
    before["description"] = current[0]["description"]
    if "revision" in before["input_schema"].get("required", []) or before != current[0]:
        raise ValueError("live_fc_operation_changed_reconcile_first")
    current[0]["description"] = reference[0]["description"]
    current[0]["input_schema"]["properties"]["revision"] = schema
    return json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def revision_response_view(active, reviewed):
    active = active.replace(b"\r\n", b"\n")
    anchor = b"        for key in CONTEXT_FIELDS:\n"
    revision_context = (
        b"        fields = CONTEXT_FIELDS\n"
        b"        if (not ancestor_path and result.get('operation') == 'business.fc_project_review'\n"
        b"                and 'archivedAt' in ancestor and 'packets' in ancestor):\n"
        b"            fields = ('revision', 'archivedAt') + fields\n"
        b"        for key in fields:\n"
    )
    if active.count(anchor) != 1 or active.replace(anchor, revision_context) != reviewed:
        raise ValueError("live_response_view_changed_reconcile_first")
    return reviewed


def commit_id(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{40}",value):
        raise ValueError("full_git_commit_required")
    return value


def prepare(directory, active, source_commit, merged_commit, *, active_response_view=None):
    source_commit, merged_commit = commit_id(source_commit), commit_id(merged_commit)
    raw = active.read_bytes()
    if sha256(raw).hexdigest() != ACTIVE_CATALOG_SHA:
        raise ValueError("active_catalog_changed_reconcile_first")
    proposed = (REPO / "fs_mcp_connector/catalog.json").read_bytes().replace(b"\r\n", b"\n")
    response_hashes = {}
    copy_line = "COPY catalog.json /app/fs_mcp_connector/catalog.json\n"
    if OPERATION == REVISION_UPDATE:
        proposed = revision_catalog(json.loads(raw), json.loads(proposed))
        active_view = active_response_view.read_bytes()
        reviewed_view = (REPO / "fs_mcp_connector/response_view.py").read_bytes().replace(b"\r\n", b"\n")
        view = revision_response_view(active_view, reviewed_view)
        response_hashes = {"base_response_view_sha256": sha256(active_view).hexdigest(),
                           "response_view_sha256": sha256(view).hexdigest()}
        copy_line = "COPY catalog.json response_view.py /app/fs_mcp_connector/\n"
    else:
        verify_catalog(json.loads(raw), json.loads(proposed))
    directory.mkdir(parents=True, exist_ok=False)
    image = directory / "image"
    image.mkdir()
    (image / "catalog.json").write_bytes(proposed)
    if response_hashes:
        (image / "response_view.py").write_bytes(view)
    (image / "Dockerfile").write_bytes((
        f"FROM {BASE_TAG}\n{copy_line}"
        f'LABEL org.opencontainers.image.revision="{source_commit}" fs.previous-image="{BASE}"\n').encode("utf-8"))
    publisher = directory / "publisher"
    publisher.mkdir()
    for name in PUBLISHER_FILES:
        (publisher / name).write_bytes((PUBLISHER / name).read_bytes().replace(b"\r\n", b"\n"))
    shutil.copyfile(__file__,directory / "connector_release.py")
    (directory / "release.json").write_text(json.dumps(dict(source_commit=source_commit,
        merged_commit=merged_commit, base_image=BASE, base_catalog_sha256=ACTIVE_CATALOG_SHA,
        catalog_sha256=sha256(proposed).hexdigest(), unit_before_sha256=UNIT_SHA, operation=OPERATION,
        **response_hashes)),encoding="utf-8")
    return directory


def image_inspect(reference):
    raw = subprocess.check_output(["docker","image","inspect",reference])
    return json.loads(raw)[0]


def verify_image(image_id, source_commit):
    base, candidate = image_inspect(BASE), image_inspect(image_id)
    old_layers, new_layers = base["RootFS"]["Layers"], candidate["RootFS"]["Layers"]
    before, after = dict(base["Config"]), dict(candidate["Config"])
    labels = after.pop("Labels")
    expected_labels = {**(before.pop("Labels") or {}), "org.opencontainers.image.revision":source_commit,
                       "fs.previous-image":BASE}
    if candidate["Id"] != image_id or new_layers[:-1] != old_layers or after != before or labels != expected_labels:
        raise ValueError("derived_image_changed_beyond_connector_payload")


def verify_payload_image(image_id, metadata, *, base=False):
    prefix = "base_" if base else ""
    payloads = {"catalog.json": metadata[prefix + "catalog_sha256"]}
    if metadata["operation"] == REVISION_UPDATE:
        payloads["response_view.py"] = metadata[prefix + "response_view_sha256"]
    expected = {"/app/fs_mcp_connector/" + name: digest for name, digest in payloads.items()}
    value = subprocess.check_output([
        "docker", "run", "--rm", "--network=none", "--read-only", "--entrypoint", "sha256sum",
        image_id, *expected,
    ], text=True)
    checked = {path: digest for digest, path in (line.split(maxsplit=1) for line in value.splitlines())}
    if checked != expected:
        raise ValueError("connector_payload_readback_failed")


def load_release(directory):
    metadata = json.loads((directory / "release.json").read_bytes())
    operation = metadata.setdefault("operation", FC_REVIEW)
    select_release(operation, base_image=metadata["base_image"],
                   active_catalog_sha=metadata["base_catalog_sha256"], unit_sha=metadata["unit_before_sha256"])
    if metadata["base_image"] != BASE or metadata["base_catalog_sha256"] != ACTIVE_CATALOG_SHA or metadata["unit_before_sha256"] != UNIT_SHA:
        raise ValueError("release_base_changed")
    for name in ("source_commit","merged_commit"):
        commit_id(metadata[name])
    if sha256((directory/"image/catalog.json").read_bytes()).hexdigest() != metadata["catalog_sha256"]:
        raise ValueError("release_catalog_changed")
    if operation == REVISION_UPDATE:
        if not re.fullmatch(r"[0-9a-f]{64}", metadata["base_response_view_sha256"]):
            raise ValueError("release_base_response_view_changed")
        if sha256((directory / "image/response_view.py").read_bytes()).hexdigest() != metadata["response_view_sha256"]:
            raise ValueError("release_response_view_changed")
    return metadata


def build(directory, source_commit):
    if STAGE_BASE_TAG:
        try:
            image_inspect(BASE_TAG)
        except subprocess.CalledProcessError:
            if image_inspect(BASE)["Id"] != BASE:
                raise ValueError("fixed_base_image_unavailable")
            subprocess.run(["docker","image","tag",BASE,BASE_TAG],check=True)
    if image_inspect(BASE_TAG)["Id"] != BASE:
        raise ValueError("base_image_tag_changed")
    image_id = subprocess.check_output(["docker","build","--network=none","--pull=false","--quiet",str(directory/"image")],text=True).strip()
    verify_image(image_id, source_commit)
    return image_id


def updater(directory, metadata):
    spec = importlib.util.spec_from_file_location("fc_review_connector_updater",directory/"publisher"/"update_connector_image_187.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OLD_IMAGE = BASE
    module.REVISION = metadata["source_commit"]
    module.MERGED_COMMIT = metadata["merged_commit"]
    module.BACKUP = Path("/var/backups/fs-data-connector") / (BACKUP_PREFIX + module.REVISION[:12])
    module.base.BACKUP = module.BACKUP
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action",required=True)
    plan = actions.add_parser("prepare")
    plan.add_argument("directory",type=Path)
    plan.add_argument("--active-catalog",type=Path,required=True)
    plan.add_argument("--source-commit",required=True)
    plan.add_argument("--merged-commit",required=True)
    plan.add_argument("--operation", choices=(*RELEASES, REVISION_UPDATE), default=FC_REVIEW)
    plan.add_argument("--active-response-view", type=Path)
    plan.add_argument("--base-image")
    plan.add_argument("--unit-sha")
    actions.add_parser("build")
    for action in ("check","apply"):
        actions.add_parser(action).add_argument("image_id")
    actions.add_parser("rollback")
    args = parser.parse_args()
    if args.action == "prepare":
        baseline = (args.active_response_view, args.base_image, args.unit_sha)
        if args.operation == REVISION_UPDATE:
            if not all(baseline):
                plan.error("revision update requires --active-response-view, --base-image and --unit-sha")
            select_release(args.operation, base_image=args.base_image,
                           active_catalog_sha=sha256(args.active_catalog.read_bytes()).hexdigest(),
                           unit_sha=args.unit_sha)
        else:
            if any(baseline):
                plan.error("live baseline arguments are only supported by the revision update")
            select_release(args.operation)
        print(prepare(args.directory, args.active_catalog, args.source_commit, args.merged_commit,
                      active_response_view=args.active_response_view))
        return
    metadata = load_release(HERE)
    if args.action == "build":
        if OPERATION == REVISION_UPDATE:
            verify_payload_image(BASE, metadata, base=True)
        image_id = build(HERE,metadata["source_commit"])
        verify_payload_image(image_id, metadata)
        print(image_id)
        return
    publisher = updater(HERE,metadata)
    if args.action == "rollback":
        publisher.rollback()
        return
    verify_image(args.image_id,metadata["source_commit"])
    if OPERATION == REVISION_UPDATE:
        verify_payload_image(BASE, metadata, base=True)
    verify_payload_image(args.image_id, metadata)
    if publisher.base.sha(publisher.base.UNIT.read_bytes()) != UNIT_SHA:
        raise ValueError("active_unit_changed_reconcile_first")
    if args.action == "check":
        before,after=publisher.check(args.image_id)
        print(json.dumps(dict(image_after=args.image_id,unit_before=publisher.base.sha(before),
                              unit_after=publisher.base.sha(after),production_writes=0)))
    else:
        publisher.apply(args.image_id)


if __name__ == "__main__":
    main()
