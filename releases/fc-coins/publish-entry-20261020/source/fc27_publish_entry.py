"""FC27 受控发布入口（宿主可信端，唯一持有 root 权限的一段）。

设计前提：**调用端不可信**。仓库里的 tools/releases 脚本可以被任何人改，
所以本文件不接受调用端传来的路径、命令、单元名、哈希或"已批准"声明，
只接受三个 ID（模块、发布名、PR 号），其余全部从宿主本地重新推导：

  * 策略文件  /etc/fc27-cloud/release-policy.json（root 所有，只读）
  * 仓库检出  /opt/fc27-workbench（root 所有，只有 root 能 fetch）
  * 产物字节  只用 `git cat-file blob <merge_commit>:<path>`，不用工作区
  * 线上基线  现场 sha256，不采信任何清单里的 before

安装方式（一次性，人工执行，之后不再由仓库自动更新）：
    install -o root -g root -m 0755 fc27_publish_entry.py /usr/local/sbin/fc27-publish

调用形式（只有这一种，其它参数一律拒绝）：
    sudo /usr/local/sbin/fc27-publish <module> <release> <pr-number> [--apply]

退出码：0 成功；2 用法；3 校验失败；4 基线漂移；5 忙/锁占用；6 失败已回退；
        7 写入状态未知（回退也失败，禁止自动重试）。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ENTRY_VERSION = "1.0.0"

DEFAULT_POLICY = Path("/etc/fc27-cloud/release-policy.json")
DEFAULT_CHECKOUT = Path("/opt/fc27-workbench")
DEFAULT_STATE_ROOT = Path("/var/lib/fc27-cloud")
MONITOR_URL = "http://127.0.0.1:8879/monitor"
MONITOR_USER_FILE = Path("/etc/fc27-cloud/monitor-user")

MODULE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
RELEASE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PR_RE = re.compile(r"^[1-9][0-9]{0,6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

IDLE_JOB_RUNNING = {"queued", "running"}
UNRESOLVED_EXECUTION = {"RUNNING", "UNCERTAIN", "PARTIAL"}


class PublishError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------- #
# 宿主侧依赖（可注入，便于离线测试；生产默认实现只读本地和 loopback）
# --------------------------------------------------------------------------- #
class GitArtifacts:
    """只用核对过的 git 对象；不读工作区、不联网。"""

    def __init__(self, checkout, main_ref="refs/remotes/origin/main", runner=None):
        self.checkout = Path(checkout)
        self.main_ref = main_ref
        self._runner = runner or self._default

    def _default(self, args):
        import subprocess

        result = subprocess.run(
            ["git", "-c", f"safe.directory={self.checkout}", "-C", str(self.checkout)] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise PublishError("git_failed", " ".join(args[:2]) + ":" + result.stderr.decode("utf-8", "replace")[:200])
        return result.stdout

    def blob(self, commit, path):
        return self._runner(["cat-file", "blob", f"{commit}:{path}"])

    def is_ancestor(self, commit, ref):
        try:
            self._runner(["merge-base", "--is-ancestor", commit, ref])
        except PublishError:
            return False
        return True

    def subject(self, commit):
        return self._runner(["log", "-1", "--format=%s", commit]).decode("utf-8", "replace").strip()

    def exists(self, ref, path):
        try:
            self._runner(["cat-file", "-e", f"{ref}:{path}"])
        except PublishError:
            return False
        return True


class SystemdRunner:
    """只允许 policy 列出的单元与动词；动词并集固定为这三个。"""

    ALLOWED_ACTIONS = frozenset({"is-active", "stop", "restart"})

    def __call__(self, unit, action):
        if action not in self.ALLOWED_ACTIONS:
            raise PublishError("unit_action_rejected", action)
        import subprocess

        result = subprocess.run(
            ["systemctl", action, unit],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return result.returncode == 0, result.stdout.decode("utf-8", "replace").strip()


def monitor_reader(timeout=5):
    user = MONITOR_USER_FILE.read_text(encoding="utf-8").strip()
    request = Request(MONITOR_URL, headers={"X-Authenticated-User": user})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


@dataclass
class Paths:
    policy: Path = DEFAULT_POLICY
    checkout: Path = DEFAULT_CHECKOUT
    state_root: Path = DEFAULT_STATE_ROOT

    @property
    def rollback_root(self):
        return self.state_root / "rollback"

    @property
    def receipt_root(self):
        return self.state_root / "releases"

    @property
    def price_writer_lock(self):
        return self.state_root / "state" / "price-writer.lock"

    @property
    def queue(self):
        return self.state_root / "queue"

    @property
    def jobs(self):
        return self.state_root / "jobs"

    @property
    def executions(self):
        return self.state_root / "executions"


# --------------------------------------------------------------------------- #
# 发布器
# --------------------------------------------------------------------------- #
class Publisher:
    def __init__(self, paths=None, artifacts=None, systemd=None, monitor=None, sleep=time.sleep):
        self.paths = paths or Paths()
        self._artifacts = artifacts
        self._systemd = systemd or SystemdRunner()
        self._monitor = monitor or monitor_reader
        self._sleep = sleep
        self.policy = None
        self.lock_fd = None

    # -- 基础设施 ---------------------------------------------------------- #
    @property
    def artifacts(self):
        if self._artifacts is None:
            self._artifacts = GitArtifacts(self.paths.checkout)
        return self._artifacts

    def load_policy(self):
        try:
            raw = json.loads(self.paths.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PublishError("policy_unreadable", str(exc)[:120])
        if raw.get("version") != 1 or not isinstance(raw.get("modules"), dict):
            raise PublishError("policy_schema")
        for module, entry in raw["modules"].items():
            if not MODULE_RE.match(module):
                raise PublishError("policy_module_name", module)
            for name, target in entry.get("targets", {}).items():
                if not TARGET_RE.match(name) or ".." in name:
                    raise PublishError("policy_target_name", name)
                roots = entry.get("allowed_roots", [])
                if not any(target.startswith(root.rstrip("/") + "/") for root in roots):
                    raise PublishError("policy_target_outside_root", target)
            for unit, actions in entry.get("units", {}).items():
                if not set(actions) <= SystemdRunner.ALLOWED_ACTIONS:
                    raise PublishError("policy_unit_action", unit)
            for name, units in entry.get("target_units", {}).items():
                if name not in entry.get("targets", {}):
                    raise PublishError("policy_unit_target_unknown", name)
                for unit in units:
                    if unit not in entry.get("units", {}):
                        raise PublishError("policy_unit_reference_unknown", unit)
        self.policy = raw
        return raw

    @property
    def current_entry(self):
        return getattr(self, "_entry", None)

    def module_policy(self, module):
        entry = self.policy["modules"].get(module)
        if entry is None:
            raise PublishError("module_not_in_policy", module)
        return entry

    # -- 只读校验 ---------------------------------------------------------- #
    def plan(self, module, release, pr):
        if not MODULE_RE.match(module or ""):
            raise PublishError("module_invalid")
        if not RELEASE_RE.match(release or ""):
            raise PublishError("release_invalid")
        if not PR_RE.match(pr or ""):
            raise PublishError("pr_invalid")
        self.load_policy()
        entry = self.module_policy(module)
        self._entry = entry
        base = f"{entry['release_prefix']}{release}"
        if not self.artifacts.exists(self.artifacts.main_ref, f"{base}/approval.json"):
            raise PublishError("release_not_on_main", base)

        approval = json.loads(self.artifacts.blob(self.artifacts.main_ref, f"{base}/approval.json"))
        commit = str(approval.get("merge_commit", ""))
        if not COMMIT_RE.match(commit):
            raise PublishError("approval_merge_commit_invalid")
        if str(approval.get("pr")) != pr:
            raise PublishError("approval_pr_mismatch", f"{approval.get('pr')}!={pr}")
        if not self.artifacts.is_ancestor(commit, self.artifacts.main_ref):
            raise PublishError("merge_commit_not_on_main", commit[:12])
        subject = self.artifacts.subject(commit)
        if f"(#{pr})" not in subject:
            raise PublishError("merge_commit_pr_binding", subject[:80])
        if not str(approval.get("authorized_by", "")).strip() or not str(approval.get("authorized_at", "")).strip():
            raise PublishError("approval_authorization_missing")

        manifest = json.loads(self.artifacts.blob(commit, f"{base}/targets.json"))
        targets = manifest.get("targets")
        if not isinstance(targets, dict) or not targets:
            raise PublishError("manifest_targets_empty")

        scope = approval.get("scope")
        if not isinstance(scope, list) or sorted(scope) != sorted(targets):
            raise PublishError("approval_scope_mismatch")

        plan = {"module": module, "release": release, "pr": pr, "merge_commit": commit,
                "base": base, "targets": {}, "units": {}, "restart": []}
        for name, row in targets.items():
            if name not in entry["targets"]:
                raise PublishError("target_not_in_policy", name)
            expected = entry["targets"][name]
            if row.get("target") != expected:
                raise PublishError("target_path_mismatch", name)
            after = str(row.get("after", ""))
            before = str(row.get("before", ""))
            if not SHA_RE.match(after) or not SHA_RE.match(before):
                raise PublishError("manifest_hash_invalid", name)
            blob = self.artifacts.blob(commit, f"{base}/source/{name}")
            if sha256_bytes(blob) != after:
                raise PublishError("candidate_hash_mismatch", name)
            plan["targets"][name] = {"path": expected, "before": before, "after": after}
            for unit in entry.get("target_units", {}).get(name, []):
                plan["units"].setdefault(unit, set()).add("restart")
        for unit in plan["units"]:
            allowed = entry.get("units", {}).get(unit)
            if not allowed:
                raise PublishError("unit_not_in_policy", unit)
            if "restart" not in allowed:
                raise PublishError("unit_action_not_granted", unit)
        plan["units"] = {u: sorted(a) for u, a in sorted(plan["units"].items())}

        for name, row in plan["targets"].items():
            path = Path(row["path"])
            if path.is_symlink():
                raise PublishError("target_is_symlink", name)
            if not path.is_file():
                raise PublishError("target_missing", name)
            if os.path.realpath(path) != os.path.realpath(row["path"]):
                raise PublishError("target_realpath_mismatch", name)
            live = sha256_file(path)
            row["live"] = live
            if live != row["before"]:
                raise PublishError("baseline_drift", f"{name}:{live[:12]}!={row['before'][:12]}")
        return plan

    # -- 运行态（只读） ---------------------------------------------------- #
    def check_idle(self):
        if list(self.paths.queue.glob("*.json")):
            raise PublishError("queue_not_idle")
        for path in self.paths.jobs.glob("*.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") in IDLE_JOB_RUNNING:
                raise PublishError("job_not_idle", path.name)
            if (job.get("kind") == "auto_cycle"
                    and job.get("result", {}).get("status") == "confirmed"
                    and not job.get("completed_at")):
                raise PublishError("job_not_idle", path.name)
        for path in self.paths.executions.glob("*.json"):
            if json.loads(path.read_text(encoding="utf-8")).get("status") in UNRESOLVED_EXECUTION:
                raise PublishError("coin_execution_unresolved", path.name)

    def acquire_lock(self):
        lock = self.paths.price_writer_lock
        if not lock.exists():
            raise PublishError("price_writer_lock_missing", str(lock))
        fd = os.open(lock, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise PublishError("price_writer_lock_busy")
        self.lock_fd = fd

    def release_lock(self):
        if self.lock_fd is not None:
            fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            os.close(self.lock_fd)
            self.lock_fd = None

    def check_units(self, plan, entry=None):
        entry = entry or self.current_entry
        if entry is None:
            raise PublishError("policy_not_loaded")
        for unit in plan["units"]:
            granted = entry.get("units", {}).get(unit, [])
            if "is-active" not in granted:
                raise PublishError("unit_readback_not_granted", unit)
            ok, state = self._systemd(unit, "is-active")
            if not ok or state != "active":
                raise PublishError("unit_not_active", f"{unit}:{state}")

    # -- 写入 -------------------------------------------------------------- #
    def _protected_snapshot(self, entry, targets):
        roots = [Path(r) for r in entry.get("allowed_roots", [])]
        skip = {row["path"] for row in targets.values()}
        snapshot = {}
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                if str(path) in skip:
                    continue
                if path.suffix not in (".py", ".sh", ".js", ".json", ".html", ".css"):
                    continue
                snapshot[str(path)] = sha256_file(path)
        return snapshot

    def _backup(self, plan, entry, directory):
        directory.mkdir(parents=True, exist_ok=False)
        meta = {"module": plan["module"], "release": plan["release"], "pr": plan["pr"],
                "merge_commit": plan["merge_commit"], "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {}}
        for name, row in plan["targets"].items():
            source = Path(row["path"])
            info = source.stat()
            copy = directory / name
            shutil.copy2(source, copy)
            os.chmod(copy, stat.S_IMODE(info.st_mode))
            meta["files"][name] = {"path": row["path"], "sha256": row["live"],
                                   "mode": stat.S_IMODE(info.st_mode),
                                   "uid": info.st_uid, "gid": info.st_gid}
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return meta

    @staticmethod
    def _atomic_swap(data, target):
        target = Path(target)
        info = target.stat()
        temp = target.with_name("." + target.name + ".publish-tmp")
        try:
            with open(temp, "xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, stat.S_IMODE(info.st_mode))
            os.chown(temp, info.st_uid, info.st_gid)
            os.replace(temp, target)
            fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if temp.exists():
                temp.unlink()

    def _wait_health(self, deadline=10.0):
        end = time.monotonic() + deadline
        last = None
        while time.monotonic() < end:
            try:
                monitor = self._monitor()
                last = monitor
                if monitor.get("health", {}).get("worker") == "ok":
                    return monitor
            except Exception:  # 读回失败按"还没好"处理，不伪造成功
                pass
            self._sleep(0.5)
        raise PublishError("runtime_not_ready", json.dumps(last, ensure_ascii=False)[:160] if last else "")

    def _receipt(self, payload):
        self.paths.receipt_root.mkdir(parents=True, exist_ok=True)
        name = f"{payload['stamp']}-{payload['module']}.json"
        path = self.paths.receipt_root / name
        with open(path, "x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=1))
            stream.flush()
            os.fsync(stream.fileno())
        return str(path)

    # -- 主流程 ------------------------------------------------------------ #
    def apply(self, plan, entry):
        stamp = utc_stamp()
        payload = {"stamp": stamp, "entry_version": ENTRY_VERSION, "module": plan["module"],
                   "release": plan["release"], "pr": int(plan["pr"]), "merge_commit": plan["merge_commit"],
                   "started_at": datetime.now(timezone.utc).isoformat(), "targets": {},
                   "units": {}, "status": "started"}
        backup_dir = self.paths.rollback_root / f"{stamp}-{plan['module']}"
        stopped = []
        swapped = False
        try:
            payload["protected_before"] = self._protected_snapshot(entry, plan["targets"])
            self._backup(plan, entry, backup_dir)
            payload["rollback_dir"] = str(backup_dir)
            for unit in plan["units"]:
                self._systemd(unit, "stop")
                stopped.append(unit)
            for name, row in plan["targets"].items():
                swapped = True
                self._atomic_swap(self.artifacts.blob(plan["merge_commit"], f"{plan['base']}/source/{name}"), row["path"])
                payload["targets"][name] = {"path": row["path"], "before": row["before"], "after": row["after"]}
            for unit in plan["units"]:
                ok, detail = self._systemd(unit, "restart")
                payload["units"][unit] = {"restart": ok, "detail": detail}
                if not ok:
                    raise PublishError("unit_restart_failed", unit)
            monitor = self._wait_health()
            payload["monitor"] = monitor.get("health")
            for name, row in plan["targets"].items():
                installed = sha256_file(Path(row["path"]))
                payload["targets"][name]["installed"] = installed
                if installed != row["after"]:
                    raise PublishError("readback_mismatch", name)
            protected_after = self._protected_snapshot(entry, plan["targets"])
            if protected_after != payload["protected_before"]:
                changed = sorted(set(protected_after.items()) ^ set(payload["protected_before"].items()))
                raise PublishError("protected_drift", json.dumps(changed[:3], ensure_ascii=False)[:200])
            payload["status"] = "published"
            payload["finished_at"] = datetime.now(timezone.utc).isoformat()
            payload["receipt"] = self._receipt(payload)
            return payload
        except Exception as exc:  # noqa: BLE001 - 任何失败都必须走回退
            payload["error"] = f"{getattr(exc, 'code', type(exc).__name__)}:{getattr(exc, 'detail', str(exc))}"[:300]
            payload["finished_at"] = datetime.now(timezone.utc).isoformat()
            rolled = self._rollback(payload, plan, backup_dir, stopped, swapped)
            payload["rollback"] = rolled
            payload["status"] = "rolled_back" if rolled.get("ok") else "unknown_write_state"
            payload["receipt"] = self._receipt(payload)
            raise PublishError(payload["status"], payload["error"])

    def _rollback(self, payload, plan, backup_dir, stopped, swapped):
        """ok 只表示“文件字节已恢复到 before”；单元没起来是另一件事，单独记。"""
        result = {"ok": False, "restored": {}, "errors": [], "unit_errors": []}
        if not swapped and not stopped:
            result["ok"] = True
            result["note"] = "nothing_written"
            return result
        if not backup_dir.exists():
            result["errors"].append("backup_missing")
            return result
        for unit in stopped:
            try:
                self._systemd(unit, "stop")
            except Exception as exc:  # noqa: BLE001
                result["unit_errors"].append(f"stop:{unit}:{exc}")
        for name, row in plan["targets"].items():
            copy = backup_dir / name
            try:
                if not copy.is_file():
                    raise FileNotFoundError(name)
                self._atomic_swap(copy.read_bytes(), row["path"])
                restored = sha256_file(Path(row["path"]))
                result["restored"][name] = restored
                if restored != row["before"]:
                    result["errors"].append(f"restore_mismatch:{name}")
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"restore:{name}:{exc}")
        for unit in stopped:
            try:
                ok, detail = self._systemd(unit, "restart")
                if not ok:
                    result["unit_errors"].append(f"restart:{unit}:{detail}")
            except Exception as exc:  # noqa: BLE001
                result["unit_errors"].append(f"restart:{unit}:{exc}")
        result["ok"] = not result["errors"]
        return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    apply_mode = "--apply" in argv
    args = [a for a in argv if a != "--apply"]
    if len(args) != 3 or (apply_mode and len(argv) != 4):
        print("usage: fc27-publish <module> <release> <pr-number> [--apply]", file=sys.stderr)
        return 2
    module, release, pr = args
    publisher = Publisher()
    try:
        entry = None
        publisher.load_policy()
        entry = publisher.module_policy(module)
        plan = publisher.plan(module, release, pr)
        if not apply_mode:
            publisher.check_idle()
            publisher.check_units(plan, entry)
            print(json.dumps({"mode": "check", "plan": plan}, ensure_ascii=False, indent=1))
            return 0
        if os.geteuid() != 0:
            raise PublishError("root_required")
        publisher.acquire_lock()
        try:
            publisher.check_idle()
            publisher.check_units(plan, entry)
            result = publisher.apply(plan, entry)
        finally:
            publisher.release_lock()
        print(json.dumps({"mode": "apply", "result": result}, ensure_ascii=False, indent=1))
        return 0
    except PublishError as exc:
        code = {"baseline_drift": 4, "price_writer_lock_busy": 5, "queue_not_idle": 5,
                "job_not_idle": 5, "coin_execution_unresolved": 5, "rolled_back": 6,
                "unknown_write_state": 7}.get(exc.code, 3)
        print(json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False), file=sys.stderr)
        return code


if __name__ == "__main__":
    sys.exit(main())
