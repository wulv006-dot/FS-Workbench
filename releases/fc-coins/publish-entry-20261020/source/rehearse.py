"""只检查、不发布：在沙盒里跑真实的校验入口（真实 git + 真实哈希 + 真实锁/空闲语义）。

与 tests/ 的区别：单元测试注入假 git；本脚本用**真的 git 仓库**跑
`GitArtifacts`（`git cat-file` / `merge-base --is-ancestor` / `log -1`），
因此覆盖真实对象解析这条平时不在 CI 里的路径。

沙盒内做的映射（每条都会写进报告 scope，不冒充生产状态）：
  1. 策略里的 `/opt/...` 绝对路径 → 沙盒同名路径（真实策略文件不改）；
  2. 生成 `approval.json`（含 `"rehearsal": true`），真实发布时由发布人写；
  3. 没有 `--live-dir` 时用候选字节当现场基线（before 取现场哈希）。

它**不**写 `/opt`、`/var/lib/fc27-cloud`、`/etc`，不调 systemctl，不联网。

用法：
    python3 rehearse.py --release-dir ../../../releases/fc-coins/<release> --pr 231
    python3 rehearse.py ... --scenario all
    python3 rehearse.py ... --live-dir /path/to/before-bytes      # 用真实现场副本

退出码：0 全部符合预期；1 有场景与预期不符；2 用法/输入错误。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fc27_publish_entry as entry  # noqa: E402

SCENARIOS = ("base", "candidate", "baseline", "scope", "pr")
EXPECT = {"base": None, "candidate": "candidate_hash_mismatch", "baseline": "baseline_drift",
          "scope": "approval_scope_mismatch", "pr": "approval_pr_mismatch"}


def sha(path):
    return entry.sha256_file(path)


def git(repo, *args, check=True):
    return subprocess.run(["git", "-c", f"safe.directory={repo}", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, check=check)


class Sandbox:
    """三提交结构：A=基线，B=带 (#pr) 的 squash 形态提交（=merge_commit），C=main 顶端（放最终 approval）。"""

    def __init__(self, root, release_dir, policy_path, module, release, pr, live_dir=None):
        self.root = Path(root)
        self.release_dir = Path(release_dir)
        self.policy_path = Path(policy_path)
        self.module = module
        self.release = release
        self.pr = pr
        self.live_dir = Path(live_dir) if live_dir else None
        self.checkout = self.root / "checkout"
        self.live_root = self.root / "live"
        self.state_root = self.root / "state"
        self.base = f"releases/fc-coins/{release}"

    def prepare(self, scenario):
        for path in (self.checkout, self.live_root, self.state_root):
            path.mkdir(parents=True)
        for name in ("queue", "jobs", "executions", "state", "rollback", "releases"):
            (self.state_root / name).mkdir()
        (self.state_root / "state" / "price-writer.lock").write_text("")

        manifest = json.loads((self.release_dir / "targets.json").read_text(encoding="utf-8"))
        targets = manifest["targets"]

        # 现场树 + 基线哈希（在篡改之前取）
        before = {}
        for name in targets:
            source = self.release_dir / "source" / name
            if not source.is_file():
                raise SystemExit(f"release_missing_source: {name}")
            live = self.live_root / name
            if self.live_dir:
                copy = self.live_dir / name
                if not copy.is_file():
                    raise SystemExit(f"live_missing: {copy}")
                shutil.copy2(copy, live)
            else:
                shutil.copy2(source, live)
            before[name] = sha(live)

        # 策略映射进沙盒
        policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        module_policy = policy["modules"][self.module]
        module_policy["allowed_roots"] = [str(self.live_root)]
        module_policy["targets"] = {name: str(self.live_root / name) for name in targets}
        module_policy["target_units"] = {name: module_policy.get("target_units", {}).get(name, [])
                                         for name in targets}
        self.policy_sandbox = self.root / "release-policy.json"
        self.policy_sandbox.write_text(json.dumps(policy, ensure_ascii=False, indent=1), encoding="utf-8")

        # 发布目录（候选字节原样）
        release_out = self.checkout / self.base
        shutil.copytree(self.release_dir / "source", release_out / "source")
        out = {"targets": {name: {"target": str(self.live_root / name), "before": before[name],
                                  "after": sha(release_out / "source" / name)} for name in targets}}
        (release_out / "targets.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

        # 授权记录（场景可篡改）
        approval = {"pr": int(self.pr), "merge_commit": "0" * 40, "authorized_by": "rehearsal",
                    "authorized_at": "2026-10-20T00:00:00+08:00",
                    "scope": sorted(targets), "rehearsal": True}
        if scenario == "scope":
            approval["scope"] = sorted(targets)[:-1]
        if scenario == "pr":
            approval["pr"] = int(self.pr) + 1
        approval_path = release_out / "approval.json"
        approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=1), encoding="utf-8")

        # 场景篡改：候选字节（提交前改，才能体现在 merge_commit 的对象里）
        if scenario == "candidate":
            victim = release_out / "source" / sorted(targets)[0]
            victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        # 场景篡改：现场漂移（基线已在篡改前取，故会失配）
        if scenario == "baseline":
            live = self.live_root / sorted(targets)[0]
            live.write_bytes(live.read_bytes() + b"\n# moved on\n")

        git(self.checkout, "init", "-q", "-b", "main")
        git(self.checkout, "config", "user.email", "rehearsal@local")
        git(self.checkout, "config", "user.name", "rehearsal")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", "rehearsal base")          # A
        git(self.checkout, "commit", "-q", "--allow-empty", "-m", f"fix(fc-coins): rehearsal (#{self.pr})")  # B
        merge_commit = git(self.checkout, "rev-parse", "HEAD").stdout.strip()

        approval["merge_commit"] = merge_commit
        approval_path.write_text(json.dumps(approval, ensure_ascii=False, indent=1), encoding="utf-8")
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-q", "-m", "rehearsal approval")      # C
        git(self.checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.merge_commit = merge_commit
        self.manifest = out
        return self

    def publisher(self):
        return entry.Publisher(
            paths=entry.Paths(policy=self.policy_sandbox, checkout=self.checkout, state_root=self.state_root),
            artifacts=entry.GitArtifacts(self.checkout),
            systemd=lambda unit, action: (True, "active" if action == "is-active" else "ok"),
            monitor=lambda: {"health": {"worker": "ok"}},
            sleep=lambda _s: None,
        )


def run_scenario(work, args, scenario):
    sandbox = Sandbox(work, args.release_dir, args.policy, args.module, args.release, args.pr,
                      args.live_dir).prepare(scenario)
    result = {"scenario": scenario, "expected": EXPECT[scenario],
              "scope": {"git": "real", "hashing": "real",
                        "policy_paths": "mapped into sandbox",
                        "approval": "generated (rehearsal: true)",
                        "live_baseline": "from --live-dir" if args.live_dir else "source bytes (sandbox baseline)",
                        "systemctl": "stubbed (no units touched)"}}
    publisher = sandbox.publisher()
    try:
        publisher.load_policy()
        module_entry = publisher.module_policy(args.module)
        plan = publisher.plan(args.module, args.release, args.pr)
        publisher.check_idle()
        publisher.check_units(plan, module_entry)
        result["actual"] = None
        result["plan"] = {"merge_commit": plan["merge_commit"][:12],
                          "targets": sorted(plan["targets"]),
                          "units": plan["units"]}
    except entry.PublishError as exc:
        result["actual"] = exc.code
        result["detail"] = exc.detail[:160]
    result["ok"] = result["actual"] == EXPECT[scenario]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="只检查不发布：沙盒校验演练")
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--release", default=None, help="默认取 release-dir 目录名")
    parser.add_argument("--policy", default=str(Path(__file__).resolve().parent / "release-policy.example.json"))
    parser.add_argument("--module", default="fc-coins")
    parser.add_argument("--pr", required=True)
    parser.add_argument("--live-dir", default=None)
    parser.add_argument("--scenario", default="all", choices=("all",) + SCENARIOS)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    args.release_dir = Path(args.release_dir).resolve()
    args.release = args.release or args.release_dir.name
    if not (args.release_dir / "targets.json").is_file():
        raise SystemExit("missing targets.json in --release-dir")

    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    root = Path(tempfile.mkdtemp(prefix="fc27-rehearsal-"))
    results = []
    try:
        for name in scenarios:
            work = root / name
            work.mkdir()
            results.append(run_scenario(work, args, name))
    finally:
        if args.keep:
            print(f"sandbox: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)

    print(json.dumps({"release": args.release, "pr": args.pr, "results": results}, ensure_ascii=False, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
