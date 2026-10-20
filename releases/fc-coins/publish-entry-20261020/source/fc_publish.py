"""FC27 发布的调用端（无特权，只做离线预检并打印宿主命令）。

它**不能**发布：没有 root，不碰 /opt、/var/lib/fc27-cloud，也不改任何文件。
真正校验与写入在宿主固定入口 /usr/local/sbin/fc27-publish，那边会从头重算，
不采信本脚本的任何结论。

用法：
    python3 fc_publish.py fc-coins <release> <pr> [--checkout PATH] [--entry PATH]

输出：一段 JSON（本地预检结论）+ 一行可直接交给值班人执行的宿主命令。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fc27_publish_entry import (  # noqa: E402
    COMMIT_RE,
    MODULE_RE,
    TARGET_RE,
    PR_RE,
    RELEASE_RE,
    SHA_RE,
    GitArtifacts,
    PublishError,
    sha256_bytes,
)

DEFAULT_ENTRY = "/usr/local/sbin/fc27-publish"
DEFAULT_RELEASE_PREFIX = "releases/fc-coins/"


def preflight(checkout, module, release, pr, entry=DEFAULT_ENTRY):
    if not MODULE_RE.match(module):
        raise PublishError("module_invalid")
    if not RELEASE_RE.match(release):
        raise PublishError("release_invalid")
    if not PR_RE.match(pr):
        raise PublishError("pr_invalid")

    artifacts = GitArtifacts(checkout)
    ref = artifacts.main_ref
    base = f"{DEFAULT_RELEASE_PREFIX}{release}"
    if not artifacts.exists(ref, f"{base}/approval.json"):
        raise PublishError("release_not_on_main", base)

    approval = json.loads(artifacts.blob(ref, f"{base}/approval.json"))
    commit = str(approval.get("merge_commit", ""))
    if not COMMIT_RE.match(commit):
        raise PublishError("approval_merge_commit_invalid")
    if str(approval.get("pr")) != pr:
        raise PublishError("approval_pr_mismatch")
    if not artifacts.is_ancestor(commit, ref):
        raise PublishError("merge_commit_not_on_main", commit[:12])
    subject = artifacts.subject(commit)
    if f"(#{pr})" not in subject:
        raise PublishError("merge_commit_pr_binding", subject[:80])

    manifest = json.loads(artifacts.blob(commit, f"{base}/targets.json"))
    targets = manifest.get("targets") or {}
    if not targets:
        raise PublishError("manifest_targets_empty")
    scope = approval.get("scope")
    if not isinstance(scope, list) or sorted(scope) != sorted(targets):
        raise PublishError("approval_scope_mismatch")

    rows = {}
    for name, row in targets.items():
        if not TARGET_RE.match(name) or ".." in name:
            raise PublishError("target_name_invalid", name)
        after = str(row.get("after", ""))
        before = str(row.get("before", ""))
        if not SHA_RE.match(after) or not SHA_RE.match(before):
            raise PublishError("manifest_hash_invalid", name)
        blob = artifacts.blob(commit, f"{base}/source/{name}")
        if sha256_bytes(blob) != after:
            raise PublishError("candidate_hash_mismatch", name)
        rows[name] = {"target": row.get("target"), "before": before, "after": after}

    return {
        "mode": "preflight",
        "module": module,
        "release": release,
        "pr": pr,
        "merge_commit": commit,
        "merge_subject": subject,
        "candidates_verified": sorted(rows),
        "live_baseline": "not_checked_here: 只有宿主入口能读 /opt 现场哈希",
        "policy_and_scope": "not_checked_here: 策略文件在宿主 /etc，本端不读",
        "host_command": f"sudo {entry} {module} {release} {pr}",
        "host_command_apply": f"sudo {entry} {module} {release} {pr} --apply",
        "note": "宿主入口会重新校验策略、目标白名单、现场基线与队列/锁，本端结论不构成授权",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=True, description="FC27 发布调用端（无特权预检）")
    parser.add_argument("module")
    parser.add_argument("release")
    parser.add_argument("pr")
    parser.add_argument("--checkout", default=None)
    parser.add_argument("--entry", default=DEFAULT_ENTRY)
    args = parser.parse_args(argv)

    checkout = Path(args.checkout).resolve() if args.checkout else Path(__file__).resolve().parents[4]
    try:
        print(json.dumps(preflight(checkout, args.module, args.release, args.pr, args.entry),
                         ensure_ascii=False, indent=1))
        return 0
    except PublishError as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
