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
OPERATION = "business.fc_project_review"
PUBLISHER = REPO / "docs/planning/fs-data-connector-20261109/deploy/connector"
PUBLISHER_FILES = ("update_connector_image_187.py", "install_connector_187.py",
                   "fs-data-connector.service.in", "client_public_probe.py", "connector_smoke.py")


def verify_catalog(active, proposed):
    expected = deepcopy(proposed)
    additions = [operation for operation in expected["operations"] if operation["name"] == OPERATION]
    if len(additions) != 1:
        raise ValueError("one_new_operation_required")
    expected["operations"].remove(additions[0])
    for module in expected["coverage"]:
        if module["module"] == "unified-business":
            module["operations"] -= 1
    if expected != active:
        raise ValueError("non_review_catalog_change")


def commit_id(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{40}",value):
        raise ValueError("full_git_commit_required")
    return value


def prepare(directory, active, source_commit, merged_commit):
    source_commit, merged_commit = commit_id(source_commit), commit_id(merged_commit)
    raw = active.read_bytes()
    if sha256(raw).hexdigest() != ACTIVE_CATALOG_SHA:
        raise ValueError("active_catalog_changed_reconcile_first")
    proposed = (REPO / "fs_mcp_connector/catalog.json").read_bytes().replace(b"\r\n", b"\n")
    verify_catalog(json.loads(raw), json.loads(proposed))
    directory.mkdir(parents=True, exist_ok=False)
    image = directory / "image"
    image.mkdir()
    (image / "catalog.json").write_bytes(proposed)
    (image / "Dockerfile").write_bytes((
        f"FROM {BASE_TAG}\n"
        "COPY catalog.json /app/fs_mcp_connector/catalog.json\n"
        f'LABEL org.opencontainers.image.revision="{source_commit}" fs.previous-image="{BASE}"\n').encode("utf-8"))
    publisher = directory / "publisher"
    publisher.mkdir()
    for name in PUBLISHER_FILES:
        (publisher / name).write_bytes((PUBLISHER / name).read_bytes().replace(b"\r\n", b"\n"))
    shutil.copyfile(__file__,directory / "connector_release.py")
    (directory / "release.json").write_text(json.dumps(dict(source_commit=source_commit,
        merged_commit=merged_commit, base_image=BASE, base_catalog_sha256=ACTIVE_CATALOG_SHA,
        catalog_sha256=sha256(proposed).hexdigest(), unit_before_sha256=UNIT_SHA)),encoding="utf-8")
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
        raise ValueError("derived_image_changed_beyond_catalog")


def load_release(directory):
    metadata = json.loads((directory / "release.json").read_bytes())
    if metadata["base_image"] != BASE or metadata["base_catalog_sha256"] != ACTIVE_CATALOG_SHA or metadata["unit_before_sha256"] != UNIT_SHA:
        raise ValueError("release_base_changed")
    for name in ("source_commit","merged_commit"):
        commit_id(metadata[name])
    if sha256((directory/"image/catalog.json").read_bytes()).hexdigest() != metadata["catalog_sha256"]:
        raise ValueError("release_catalog_changed")
    return metadata


def build(directory, source_commit):
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
    module.BACKUP = Path("/var/backups/fs-data-connector") / ("fc-review-" + module.REVISION[:12])
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
    actions.add_parser("build")
    for action in ("check","apply"):
        actions.add_parser(action).add_argument("image_id")
    actions.add_parser("rollback")
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(args.directory,args.active_catalog,args.source_commit,args.merged_commit))
        return
    metadata = load_release(HERE)
    if args.action == "build":
        print(build(HERE,metadata["source_commit"]))
        return
    publisher = updater(HERE,metadata)
    if args.action == "rollback":
        publisher.rollback()
        return
    verify_image(args.image_id,metadata["source_commit"])
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
