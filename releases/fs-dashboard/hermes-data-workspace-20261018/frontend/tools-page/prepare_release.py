"""Prepare the exact data-tools UI release from observed live bytes; no server writes."""
import argparse
import base64
import hashlib
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIVATE = ROOT / ".agent_runtime/hermes-data-workspace-20261018"
UI_BASELINE = PRIVATE / "ui-baseline-tools-page.json"
NAV_BASELINE = PRIVATE / "tools-page/navigation-live.json"
UI_PRIOR = PRIVATE / "ui-stage-20261018-integrated-v6"
CONVERSATION_PRIOR = ROOT / ".agent_runtime/hermes-conversation-20261018/release-v4/approved-manifest.json"
FORMAL = "/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf"
HOME = "/var/www/dashboard/fs-home/index.html"
NAV = "/var/www/dashboard/fs-home/navigation.json"
LEDGER = "/var/lib/fs-dashboard-release/current.json"
PREVIOUS = "workspace-native-20261006-e162b639a1d1"
PREFIX = "/var/lib/fs-navigation-formal-static/"
URL = "/dashboard/workspace-assets/"
EXPECTED = {
    FORMAL: "8acbae1d23fb9e70e6725b0e7f1d79263da6c25ef6616b07dfac9df3529e9f0b",
    HOME: "9c4a6c382644beb7396fd8700e5c461ede9333a8fc2003d68e594a118a37012f",
    NAV: "fba83394ea4906fe7bbac31a35c19dc9e055ba3c02a2daedde05ff198d2e3636",
    PREFIX + PREVIOUS + "/shell.js": "1d0d5f40e7941c8cb8d56788ffb2f2c44864a12771bb4bc60cbea6a6ccc6d3df",
    PREFIX + PREVIOUS + "/data-workspace.js": "69b51d47c3eb1cdbe6f7f05639b07de72e956fa416023b3c63748cae6ebbd7e6",
    PREFIX + PREVIOUS + "/index.html": "d0c5458644eb2af15245d4a25c5f6f1d07034939e6aca9dfc0684abfddd818f2",
}
BASE_PUBLISHER_SHA = "2f92f795ce2169a71c6ee1e2753868c34604d9b87357d3e064930a4da833c30e"
BASE_NAV_SHA = "5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357"
SOURCE_SHA = {
    "index.html": "b2cb4f32abc7940e32669f3caf851b362f3627c1b1595e42c567167646c42ff5",
    "page.css": "7740dbafdf516aa5b9158c85e4a3ed465d447dec1442c67ff3c9a0f90be4b8f0",
    "page.js": "d3087a70b7e2cb96ab32888057df69e71826757bd1fe794f9d22af4fce3944b3",
    "analytics-shell.js": "cf9119de22addd3f30a5243d5b5286f99956a9200145419533850b6555aefcc2",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace_one(raw, old, new, name):
    if raw.count(old) != 1:
        raise ValueError("exact_anchor_drift:" + name)
    return raw.replace(old, new, 1)


def observed():
    raw = UI_BASELINE.read_bytes()
    value = json.loads(raw)
    expected_paths = set(EXPECTED) - {NAV}
    if value.get("contract") != "fs-data-ui-baseline-v1" or value.get("production_writes") != 0:
        raise ValueError("read_only_ui_baseline_required")
    if {r["path"] for r in value["files"]} != expected_paths | {LEDGER}:
        raise ValueError("exact_ui_baseline_paths_required")
    out = {}
    for row in value["files"]:
        data = base64.b64decode(row["content"], validate=True)
        if sha(data) != row["sha256"] or (row["path"] in EXPECTED and row["sha256"] != EXPECTED[row["path"]]):
            raise ValueError("observed_ui_bytes_drift:" + row["path"])
        if (row["uid"], row["gid"], row["links"], row["mode"]) != (0, 0, 1, "0o600" if row["path"] == LEDGER else "0o644"):
            raise ValueError("observed_ui_metadata_drift:" + row["path"])
        out[row["path"]] = data
    nav = NAV_BASELINE.read_bytes()
    if sha(nav) != EXPECTED[NAV]:
        raise ValueError("observed_navigation_bytes_drift")
    out[NAV] = nav
    return value, raw, out


def navigation(raw):
    old = b'        "unified-business",\n        "weekly",'
    new = b'        "unified-business",\n        "data-analysis-tools",\n        "weekly",'
    raw = replace_one(raw, old, new, "analytics_ids")
    anchor = b'    {\n      "id": "unified-business",'
    item = ("    {\n"
            '      "id": "data-analysis-tools",\n'
            '      "label": "数据分析工具",\n'
            '      "path": "/dashboard/data-tools/",\n'
            '      "icon": "▤",\n'
            '      "short": "独立查询与归档数据",\n'
            '      "scope": "global-portal",\n'
            '      "section": "analytics",\n'
            '      "requiredGroup": "dashboard"\n'
            "    },\n").encode("utf-8")
    raw = replace_one(raw, anchor, item + anchor, "analytics_tool")
    result = json.loads(raw)
    section = next(x for x in result["sections"] if x["id"] == "analytics")
    tool = next(x for x in result["tools"] if x["id"] == "data-analysis-tools")
    if section["ids"].count(tool["id"]) != 1 or tool["path"] != "/dashboard/data-tools/":
        raise ValueError("navigation_addition_invalid")
    return raw


def location_blocks(formal):
    return re.findall(rb"location = [^\n]+\{.*?\n\}", formal, re.S)


def exact_block(blocks, route):
    prefix = ("location = " + route + " {").encode()
    matches = [b for b in blocks if b.startswith(prefix)]
    if len(matches) != 1 or b"auth_request /__nav_formal_native_session;" not in matches[0] or b"disable_symlinks on;" not in matches[0]:
        raise ValueError("protected_route_required:" + route)
    return matches[0]


def build_formal(current, release_id):
    blocks = location_blocks(current)
    old_url = URL + PREVIOUS + "/"
    new_url = URL + release_id + "/"
    old_root = PREFIX + PREVIOUS + "/"
    new_root = PREFIX + release_id + "/"
    entry = exact_block(blocks, "/dashboard/analytics/index.html")
    updated_entry = replace_one(entry, (old_root + "index.html").encode(), (new_root + "index.html").encode(), "analytics_alias")
    current = replace_one(current, entry, updated_entry, "analytics_entry")
    asset_templates = {
        "shell.js": exact_block(blocks, old_url + "shell.js"),
        "index.html": exact_block(blocks, old_url + "index.html"),
    }
    additions = []
    mime = {
        "shell.js": b"application/javascript",
        "index.html": b"text/html",
        "tools-index.html": b"text/html",
        "page.css": b"text/css",
        "page.js": b"application/javascript",
    }
    for name in ("shell.js", "index.html", "tools-index.html", "page.css", "page.js"):
        template = asset_templates["index.html" if name == "index.html" else "shell.js"]
        old_name = "index.html" if name == "index.html" else "shell.js"
        block = replace_one(template, (old_url + old_name).encode(), (new_url + name).encode(), "immutable_route_" + name)
        block = replace_one(block, (old_root + old_name).encode(), (new_root + name).encode(), "immutable_alias_" + name)
        additions.append(block.replace(b"    alias ", b"    types { }\n    default_type " + mime[name] + b";\n    alias ", 1))
    page_entry = entry.replace(b"/dashboard/analytics/index.html", b"/dashboard/data-tools/")
    page_entry = replace_one(page_entry, (old_root + "index.html").encode(), (new_root + "tools-index.html").encode(), "tools_entry_alias")
    additions.append(page_entry.replace(b"    alias ", b"    types { }\n    default_type text/html;\n    alias ", 1))
    for name in ("page.css", "page.js"):
        template = asset_templates["shell.js"]
        block = replace_one(template, (old_url + "shell.js").encode(), ("/dashboard/data-tools/" + name).encode(), "page_route_" + name)
        block = replace_one(block, (old_root + "shell.js").encode(), (new_root + name).encode(), "page_alias_" + name)
        additions.append(block.replace(b"    alias ", b"    types { }\n    default_type " + mime[name] + b";\n    alias ", 1))
    for block in additions:
        if b"auth_request /__nav_formal_native_session;" not in block or b"disable_symlinks on;" not in block:
            raise ValueError("new_route_missing_auth_or_symlink_guard")
    return current + b"\n\n" + b"\n\n".join(additions) + b"\n"


def protected_map(ui, obs):
    prior_ui = json.loads((UI_PRIOR / "release-manifest.json").read_bytes())
    prior_conversation = json.loads(CONVERSATION_PRIOR.read_bytes())
    protected = {r["path"]: r["sha256"] for r in prior_ui["unchangedRequired"]}
    protected.update({r["path"]: r["sha256"] for r in prior_conversation["unchangedRequired"]})
    protected.update({r["target"]: r["sha256"] for r in prior_conversation["files"]})
    protected["/var/www/dashboard/fs-home/brain/brain.js"] = "5dec4ec7be591e92d5aba1db67a3c5b141bb0b123fe2532be3e617dfd06bb6cb"
    for name in ("shell.js", "data-workspace.js", "index.html"):
        path = PREFIX + PREVIOUS + "/" + name
        protected[path] = EXPECTED[path]
    for path in (FORMAL, HOME, NAV):
        protected.pop(path, None)
    if len(protected) < 325 or protected.get("/var/www/dashboard/fs-home/brain/brain.js") is None:
        raise ValueError("protected_footprint_shrank")
    return [dict(path=path, sha256=digest) for path, digest in sorted(protected.items())]


def publisher(output, contract_sha):
    source = (UI_PRIOR / "release_workspace.py").read_bytes()
    if sha(source) != BASE_PUBLISHER_SHA or sha((UI_PRIOR / "release_navigation_base.py").read_bytes()) != BASE_NAV_SHA:
        raise ValueError("frozen_publisher_drift")
    text = source.decode("utf-8")
    text = text.replace("Only three immutable files, homepage HTML and the existing formal fragment are written.",
                        "Only five immutable files, formal route, homepage and navigation JSON are written.")
    text = replace_one(text, "MUTABLE = ('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/var/www/dashboard/fs-home/index.html')",
                       "MUTABLE = ('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf', '/var/www/dashboard/fs-home/index.html', '/var/www/dashboard/fs-home/navigation.json')", "publisher_mutable")
    text = replace_one(text, "NAMES = {'shell.js', 'data-workspace.js', 'index.html'}",
                       "NAMES = {'shell.js', 'index.html', 'tools-index.html', 'page.css', 'page.js'}", "publisher_assets")
    text = replace_one(text, "if len(m['targets'])!=2", "if len(m['targets'])!=3", "publisher_target_count")
    text = re.sub(r"CONTRACT_SHA = '[a-f0-9]{64}'", "CONTRACT_SHA = '" + contract_sha + "'", text, count=1)
    (output / "release_workspace.py").write_text(text, encoding="utf-8")
    for name in ("release_navigation.py", "release_navigation_base.py"):
        shutil.copyfile(UI_PRIOR / name, output / name)


def prepare(output):
    output = Path(output)
    if output.exists():
        raise ValueError("new_output_required")
    ui, ui_raw, obs = observed()
    source_files = {name: (HERE / name).read_bytes() for name in ("analytics-shell.js", "index.html", "page.css", "page.js")}
    if any(sha(data) != SOURCE_SHA[name] for name, data in source_files.items()):
        raise ValueError("frozen_frontend_source_drift")
    old_script = (URL + PREVIOUS + "/shell.js").encode()
    if obs[HOME].count(old_script) != 1 or obs[PREFIX + PREVIOUS + "/index.html"].count(old_script) != 1:
        raise ValueError("active_shell_reference_drift")
    nav = navigation(obs[NAV])
    source_sig = b"".join(source_files[name] for name in sorted(source_files))
    release_id = "workspace-native-20261006-" + sha(source_sig + obs[FORMAL] + obs[HOME] + nav)[:12]
    new_script = (URL + release_id + "/shell.js").encode()
    assets = {
        "shell.js": source_files["analytics-shell.js"],
        "index.html": replace_one(obs[PREFIX + PREVIOUS + "/index.html"], old_script, new_script, "analytics_index_shell"),
        "tools-index.html": source_files["index.html"],
        "page.css": source_files["page.css"],
        "page.js": source_files["page.js"],
    }
    home = replace_one(obs[HOME], old_script, new_script, "home_shell")
    formal = build_formal(obs[FORMAL], release_id)
    output.mkdir(parents=True)
    (output / "assets").mkdir()
    (output / "candidate").mkdir()
    for name, data in assets.items():
        (output / "assets" / name).write_bytes(data)
    for name, data in (("formal.conf", formal), ("home.html", home), ("navigation.json", nav)):
        (output / "candidate" / name).write_bytes(data)
    manifest = {
        "schemaVersion": 1,
        "scope": "hermes-data-tools-ui-20261018",
        "releaseReady": False,
        "releaseId": release_id,
        "immutableAssets": [dict(candidate="assets/" + name, target=PREFIX + release_id + "/" + name,
                                 url=URL + release_id + "/" + name, beforeSha256=None, sha256=sha(data))
                            for name, data in assets.items()],
        "targets": [dict(candidate="candidate/" + name, target=target, beforeSha256=sha(obs[target]), sha256=sha(data))
                    for name, target, data in (("formal.conf", FORMAL, formal), ("home.html", HOME, home), ("navigation.json", NAV, nav))],
        "unchangedRequired": protected_map(ui, obs),
        "requiredBusinessLedger": json.loads(obs[LEDGER]),
        "baselineObservedAt": ui["observed_at"],
        "uiBaselineSha256": sha(ui_raw),
        "navigationBaselineSha256": sha(obs[NAV]),
        "businessWrites": False,
        "timersChanged": False,
    }
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (output / "release-manifest.json").write_bytes(raw)
    (output / "release-contract.json").write_bytes(raw)
    publisher(output, sha(raw))
    result = {"releaseId": release_id, "manifestSha256": sha(raw), "assets": len(assets),
              "mutable": 3, "protected": len(manifest["unchangedRequired"]), "productionWrites": 0}
    (output / "preparation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), ensure_ascii=False, indent=2))
