"""现场哈希校准：把宿主回读的 sha256 与策略里的目标清单对照。

为什么需要它：策略里的 37 个目标是**路径白名单**，不是"当前线上就是这个哈希"。
发布前必须先确认每个目标在宿主上确实存在、且与 `targets.json` 的 `before` 一致，
否则发布器会在 `baseline_drift` 处拒绝（这是正确行为，但要让值班人提前看到差异）。

用法（宿主上，只读）：
    # 1) 生成回读命令，交给有权限的人执行
    python3 calibrate.py --policy /etc/fc27-cloud/release-policy.json --module fc-coins --emit-commands

    # 2) 把回读结果贴回（stdin 或文件），得到差异表
    sha256sum /opt/fc27-cloud-browser/*.py | python3 calibrate.py --policy ... --module fc-coins --readback -

    # 3) 若要和某次发布清单对照
    python3 calibrate.py --policy ... --module fc-coins --targets targets.json --readback readback.txt

退出码：0 全部一致；4 有漂移或缺失；2 用法/输入错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LINE_RE = re.compile(r"^([0-9a-f]{64})\s+\*?(.+?)\s*$")
COMMAND_RE = re.compile(r"^sha256sum\s+(.+)$")


def load_targets(policy_path, module):
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    modules = policy.get("modules", {})
    if module not in modules:
        raise SystemExit(f"module_not_in_policy: {module}")
    entry = modules[module]
    targets = entry.get("targets", {})
    if not targets:
        raise SystemExit("policy_targets_empty")
    return entry, targets


def emit_commands(entry, targets):
    lines = ["# 逐文件回读（只读）："]
    for name in sorted(targets):
        lines.append(f"sha256sum {targets[name]}")
    lines.append("# 单元状态（只读）：")
    for unit in sorted(entry.get("units", {})):
        lines.append(f"systemctl is-active {unit}")
    return "\n".join(lines)


def parse_readback(text):
    """返回 ({绝对路径: sha256}, [忽略的行])。"""
    hashes, ignored = {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            ignored.append(raw)
            continue
        digest, path = match.group(1), match.group(2)
        if not path.startswith("/"):
            ignored.append(raw)
            continue
        hashes[path] = digest
    return hashes, ignored


def compare(targets, hashes, expected=None):
    report = {"targets": len(targets), "matched": [], "drift": [], "missing": [],
              "unexpected": [], "not_in_policy": []}
    for name in sorted(targets):
        path = targets[name]
        if path not in hashes:
            report["missing"].append({"name": name, "path": path})
            continue
        actual = hashes[path]
        want = None
        if expected:
            want = expected.get(path) or expected.get(name)
        if want is not None and actual != want:
            report["drift"].append({"name": name, "path": path, "expected": want, "actual": actual})
        else:
            report["matched"].append(name)
    known = set(targets.values())
    for path in sorted(hashes):
        if path not in known:
            report["not_in_policy"].append(path)
    if expected:
        for key in sorted(expected):
            if key.startswith("/") and key not in known:
                report["unexpected"].append(key)
    report["ok"] = not report["drift"] and not report["missing"]
    return report


def load_expected(path):
    """targets.json（发布清单）→ {target 路径: before/after 期望值}。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("targets", data)
    expected = {}
    for name, row in rows.items():
        if isinstance(row, dict):
            if row.get("target"):
                expected[row["target"]] = row.get("before") or row.get("after")
            if row.get("before"):
                expected[name] = row["before"]
    return {k: v for k, v in expected.items() if v}


def main(argv=None):
    parser = argparse.ArgumentParser(description="FC27 现场哈希校准（只读）")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--readback", default=None, help="回读文件路径，- 表示 stdin")
    parser.add_argument("--targets", default=None, help="可选：某次发布 targets.json，用于比 before")
    parser.add_argument("--emit-commands", action="store_true")
    args = parser.parse_args(argv)

    entry, targets = load_targets(args.policy, args.module)
    if args.emit_commands:
        print(emit_commands(entry, targets))
        return 0
    if not args.readback:
        parser.error("需要 --readback 或 --emit-commands")

    if args.readback == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.readback).read_text(encoding="utf-8")
    hashes, ignored = parse_readback(text)
    expected = load_expected(args.targets) if args.targets else None
    report = compare(targets, hashes, expected)
    report["ignored_lines"] = len(ignored)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["ok"] else 4


if __name__ == "__main__":
    sys.exit(main())
