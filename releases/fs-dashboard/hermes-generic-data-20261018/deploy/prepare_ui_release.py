"""Prepare a two-asset, two-mutable UI follow-up from the deployed tools release."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from release_scope import BACKEND, SOURCE_SHA256
from prepare_session_image import BASELINE as SESSION_UNIT_BASELINE, BEFORE_UNIT_SHA, OLD_TAG, NEW_TAG

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / ".agent_runtime/hermes-data-workspace-20261018/tools-page/stage-final-v1"
PRIOR_MANIFEST_SHA = "431bd905d1a48d1d1c3756cebb5c6ca42b79f2f244511c82a17f1cf17532cc54"
FORMAL = "/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf"
BRAIN = "/var/www/dashboard/fs-home/brain/brain.js"
PREFIX = "/var/lib/fs-navigation-formal-static/"
URL_PREFIX = "/dashboard/workspace-assets/"
MODULE = ROOT / "fs_hermes_data_workspace_20261018/frontend/data-workspace.js"
MODULE_SHA = "52d57e8b9ebeffe55dc141fa4f5063600bbc18503f719894d41f91956dfec0c2"
BRAIN_SOURCE = ROOT / "fs_hermes_conversation_20261018/frontend/entry/brain.js"
BRAIN_SHA = "f5e24d65ceb0f32ae40032cd54805ebd2e9398b2175c9fbd57ff786ec521fca4"
OLD_MODULE = "/dashboard/workspace-assets/workspace-native-20261006-e162b639a1d1/data-workspace.js"
OLD_BRAIN_SHA = "5dec4ec7be591e92d5aba1db67a3c5b141bb0b123fe2532be3e617dfd06bb6cb"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def one(raw, old, new, label):
    if raw.count(old) != 1:
        raise ValueError("exact_anchor_drift:" + label)
    return raw.replace(old, new, 1)


def block(formal, route):
    pattern = rb"location = " + re.escape(route.encode()) + rb" \{.*?\n\}"
    matches = re.findall(pattern, formal, re.S)
    if len(matches) != 1 or b"auth_request /__nav_formal_native_session;" not in matches[0] or b"disable_symlinks on;" not in matches[0]:
        raise ValueError("authenticated_exact_route_required:" + route)
    return matches[0]


def prepare(output):
    output = Path(output)
    if output.exists():
        raise ValueError("new_output_required")
    if sha((PRIOR / "approved-manifest.json").read_bytes()) != PRIOR_MANIFEST_SHA:
        raise ValueError("prior_deployed_manifest_drift")
    prior = json.loads((PRIOR / "approved-manifest.json").read_text("utf-8"))
    previous = prior["releaseId"]
    if previous != "workspace-native-20261006-37fe775358df":
        raise ValueError("prior_release_identity_drift")
    module, brain = MODULE.read_bytes(), BRAIN_SOURCE.read_bytes()
    if sha(module) != MODULE_SHA or sha(brain) != BRAIN_SHA:
        raise ValueError("frozen_ui_source_drift")
    release = "workspace-native-20261006-" + MODULE_SHA[:12]
    url = URL_PREFIX + release + "/data-workspace.js"
    tools = (PRIOR / "assets/tools-index.html").read_bytes()
    old = json.loads((PRIOR / "approved-manifest.json").read_bytes())["immutableAssets"]
    if sha(tools) != next(r["sha256"] for r in old if r["candidate"] == "assets/tools-index.html"):
        raise ValueError("prior_tools_index_drift")
    tools = one(tools, OLD_MODULE.encode(), url.encode(), "tools_module_url")
    formal = (PRIOR / "candidate/formal.conf").read_bytes()
    old_formal_sha = next(r["sha256"] for r in prior["targets"] if r["target"] == FORMAL)
    if sha(formal) != old_formal_sha:
        raise ValueError("prior_formal_candidate_drift")
    old_entry = block(formal, "/dashboard/data-tools/index.html")
    new_entry = one(old_entry, (PREFIX + previous + "/tools-index.html").encode(),
                    (PREFIX + release + "/tools-index.html").encode(), "tools_index_alias")
    formal = one(formal, old_entry, new_entry, "tools_index_route")
    template = block(formal, URL_PREFIX + previous + "/page.js")
    new_asset = one(template, (URL_PREFIX + previous + "/page.js").encode(), url.encode(), "new_module_route")
    new_asset = one(new_asset, (PREFIX + previous + "/page.js").encode(),
                    (PREFIX + release + "/data-workspace.js").encode(), "new_module_alias")
    if b"default_type application/javascript;" not in new_asset or b"alias " not in new_asset:
        raise ValueError("strict_module_mime_or_alias_missing")
    formal += b"\n\n" + new_asset + b"\n"
    block(formal, url)
    output.mkdir(parents=True)
    (output / "assets").mkdir()
    (output / "candidate").mkdir()
    (output / "assets/data-workspace.js").write_bytes(module)
    (output / "assets/tools-index.html").write_bytes(tools)
    (output / "candidate/formal.conf").write_bytes(formal)
    (output / "candidate/brain.js").write_bytes(brain)
    protected = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
    protected.update({r["target"]: r["sha256"] for r in prior["immutableAssets"] + prior["targets"]})
    unit_before = SESSION_UNIT_BASELINE.read_bytes()
    if sha(unit_before) != BEFORE_UNIT_SHA or unit_before.count(OLD_TAG.encode()) != 1:
        raise ValueError("session_unit_source_baseline_drift")
    unit_after = sha(unit_before.replace(OLD_TAG.encode(), NEW_TAG.encode(), 1))
    for local, _, target in BACKEND:
        expected = unit_after if local == "@generated-session-unit" else SOURCE_SHA256[local]
        if local != "@generated-session-unit" and sha((ROOT / local).read_bytes()) != expected:
            raise ValueError("backend_after_source_drift:" + local)
        if target not in protected and target not in ("/opt/fs-hermes-fc/cohort_paid_source.py",
                                                  "/opt/fc27-cloud/marketing-session-20261009/cohort_paid_source.py"):
            raise ValueError("backend_target_not_in_prior_protection:" + target)
        protected[target] = expected
    if protected.pop(BRAIN, None) != OLD_BRAIN_SHA or protected.pop(FORMAL) != old_formal_sha:
        raise ValueError("prior_brain_or_formal_baseline_drift")
    if len(protected) != 345:
        raise ValueError("protected_footprint_shrank")
    manifest = {"schemaVersion": 1, "scope": "hermes-generic-data-ui-20261018",
                "releaseReady": False, "releaseId": release,
                "immutableAssets": [
                    {"candidate": "assets/" + name, "target": PREFIX + release + "/" + name,
                     "url": URL_PREFIX + release + "/" + name, "beforeSha256": None, "sha256": sha(data)}
                    for name, data in (("data-workspace.js", module), ("tools-index.html", tools))],
                "targets": [
                    {"candidate": "candidate/formal.conf", "target": FORMAL,
                     "beforeSha256": old_formal_sha, "sha256": sha(formal)},
                    {"candidate": "candidate/brain.js", "target": BRAIN,
                     "beforeSha256": OLD_BRAIN_SHA, "sha256": BRAIN_SHA}],
                "unchangedRequired": [{"path": path, "sha256": digest} for path, digest in sorted(protected.items())],
                "requiredBusinessLedger": prior["requiredBusinessLedger"],
                "businessWrites": False, "timersChanged": False,
                "priorApprovedManifestSha256": PRIOR_MANIFEST_SHA}
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (output / "release-contract.json").write_bytes(raw)
    (output / "release-manifest.json").write_bytes(raw)
    template = (PRIOR / "release_workspace.py").read_text("utf-8")
    template = one(template, "HOME = '/var/www/dashboard/fs-home/index.html'",
                   "HOME = '/var/www/dashboard/fs-home/brain/brain.js'", "publisher_brain_last")
    template = one(template,
                   "MUTABLE = ('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/var/www/dashboard/fs-home/index.html', '/var/www/dashboard/fs-home/navigation.json')",
                   "MUTABLE = ('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/var/www/dashboard/fs-home/brain/brain.js')",
                   "publisher_mutable")
    template = one(template, "NAMES = {'shell.js', 'index.html', 'tools-index.html', 'page.css', 'page.js'}",
                   "NAMES = {'data-workspace.js', 'tools-index.html'}", "publisher_assets")
    template = one(template, "if len(m['targets'])!=3", "if len(m['targets'])!=2", "publisher_targets")
    template, count = re.subn(r"CONTRACT_SHA = '[a-f0-9]{64}'", "CONTRACT_SHA = '" + sha(raw) + "'", template)
    if count != 1:
        raise ValueError("publisher_contract_anchor")
    (output / "release_workspace.py").write_text(template, encoding="utf-8")
    for name in ("release_navigation.py", "release_navigation_base.py"):
        shutil.copyfile(PRIOR / name, output / name)
    return {"releaseId": release, "manifestSha256": sha(raw), "immutableAssets": 2,
            "mutableTargets": 2, "protectedPaths": len(protected), "productionWrites": 0}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.output), ensure_ascii=False, indent=2))
