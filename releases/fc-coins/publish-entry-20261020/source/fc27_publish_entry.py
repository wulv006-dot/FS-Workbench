"""FC27 受控发布入口（宿主可信端，唯一持有 root 权限的一段）。

调用端不可信：只接受三个 ID（模块、发布名、PR 号），其余从宿主本地重推：
  * 策略      /etc/fc27-cloud/release-policy.json（root 所有，只读）
  * 仓库检出  /opt/fc27-workbench（root 所有；刷新由 root 单独执行，本件不联网）
  * 产物字节  只用 `git cat-file blob <merge_commit>:<path>`，不读工作区
  * 线上基线  现场 sha256，不采信清单里的 before
  * 授权      /etc/fc27-cloud/authorizations/<module>/<release>.json（同一 fd 校验）
  * 锁        模块自带 queue_mutation 协议 + 既有 price-writer.lock，按原顺序两把都取

安装（一次性，人工，root）：
    install -o root -g root -m 0755 fc27_publish_entry.py /usr/local/sbin/fc27-publish

调用（唯一形态）：
    sudo /usr/local/sbin/fc27-publish <module> <release> <pr-number> [--apply]

退出码：0 成功；2 用法；3 校验失败；4 基线漂移；5 忙/锁缺失或不可信；6 失败已回退；7 写入状态未知。
"""
from __future__ import annotations

import ast
import fcntl
import hashlib
import importlib
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ENTRY_VERSION = "1.1.0"

DEFAULT_POLICY = Path("/etc/fc27-cloud/release-policy.json")
DEFAULT_CHECKOUT = Path("/opt/fc27-workbench")
DEFAULT_STATE_ROOT = Path("/var/lib/fc27-cloud")
DEFAULT_AUTHORIZATION_ROOT = Path("/etc/fc27-cloud/authorizations")
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
# 可信读取：逐级 O_NOFOLLOW 打开；同一 fd 校验属主/权限/内容，读完确认 inode 未变
# --------------------------------------------------------------------------- #
def validate_index(root):
    """返回：从该目录开始校验属主与权限（其上层只靠 O_NOFOLLOW 拒绝符号链接）。"""
    return max(len(Path(root).parts) - 2, 0)


def open_beneath(path, owner_uid=0, validate_from=0):
    """打开绝对路径：先用 lstat 逐级拒绝符号链接，再以 O_NOFOLLOW 打开并核对 inode。

    不依赖 errno 区分 ELOOP / ENOTDIR：Linux 上 O_DIRECTORY|O_NOFOLLOW 命中符号链接目录时
    返回的是 ENOTDIR，各版本行为不一致，所以显式 lstat。
    """
    text = str(path)
    if not text.startswith("/"):
        raise PublishError("path_not_absolute", text)
    segments = Path(text).parts[1:]
    if not segments:
        raise PublishError("path_not_absolute", text)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        dir_fd = os.open("/", flags)
    except OSError as exc:
        raise PublishError("path_open_failed", f"/:{exc.strerror}")
    handed_over = False
    try:
        for index, segment in enumerate(segments[:-1]):
            try:
                info = os.stat(segment, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise PublishError("path_missing", f"{text}:{segment}")
            except OSError as exc:
                raise PublishError("path_open_failed", f"{text}:{segment}:{exc.strerror}")
            if stat.S_ISLNK(info.st_mode):
                raise PublishError("path_is_symlink", f"{text}:{segment}")
            if not stat.S_ISDIR(info.st_mode):
                raise PublishError("path_not_directory", f"{text}:{segment}")
            try:
                nxt = os.open(segment, flags, dir_fd=dir_fd)
            except OSError as exc:
                raise PublishError("path_open_failed", f"{text}:{segment}:{exc.strerror}")
            os.close(dir_fd)
            dir_fd = nxt
            opened = os.fstat(dir_fd)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise PublishError("path_inode_changed", f"{text}:{segment}")
            if index >= validate_from and (opened.st_uid != owner_uid
                                           or stat.S_IMODE(opened.st_mode) & 0o022):
                raise PublishError("path_parent_untrusted", f"{text}:{segment}")
        name = segments[-1]
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise PublishError("path_missing", text)
        except OSError as exc:
            raise PublishError("path_open_failed", f"{text}:{exc.strerror}")
        if stat.S_ISLNK(info.st_mode):
            raise PublishError("path_is_symlink", text)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as exc:
            raise PublishError("path_open_failed", f"{text}:{exc.strerror}")
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(fd)
            raise PublishError("path_inode_changed", text)
        handed_over = True
        return fd, dir_fd, name, opened
    finally:
        if not handed_over:
            try:
                os.close(dir_fd)
            except OSError:
                pass


def read_trusted(path, owner_uid=0, validate_from=0, max_bytes=65536):
    fd, dir_fd, name, before = open_beneath(path, owner_uid, validate_from)
    try:
        mode = stat.S_IMODE(before.st_mode)
        if not stat.S_ISREG(before.st_mode):
            raise PublishError("path_not_regular", str(path))
        if before.st_nlink != 1:
            raise PublishError("path_hardlinked", f"{path}:nlink={before.st_nlink}")
        if before.st_uid != owner_uid:
            raise PublishError("path_owner_mismatch", f"{path}:uid={before.st_uid}")
        if mode & 0o022:
            raise PublishError("path_writable", f"{path}:{oct(mode)}")
        if before.st_size > max_bytes:
            raise PublishError("path_too_large", f"{path}:{before.st_size}")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise PublishError("path_too_large", str(path))
            chunks.append(chunk)
        after = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise PublishError("path_inode_changed", str(path))
        return b"".join(chunks)
    finally:
        os.close(fd)
        os.close(dir_fd)


# --------------------------------------------------------------------------- #
# 宿主侧依赖（可注入，便于离线测试）
# --------------------------------------------------------------------------- #
class GitArtifacts:
    def __init__(self, checkout, main_ref="refs/remotes/origin/main", runner=None):
        self.checkout = Path(checkout)
        self.main_ref = main_ref
        self._runner = runner or self._default

    def _default(self, args):
        import subprocess

        result = subprocess.run(
            ["git", "-c", f"safe.directory={self.checkout}", "-C", str(self.checkout)] + args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise PublishError("git_failed",
                               " ".join(args[:2]) + ":" + result.stderr.decode("utf-8", "replace")[:200])
        return result.stdout

    def blob(self, commit, path):
        return self._runner(["cat-file", "blob", f"{commit}:{path}"])

    def exists(self, ref, path):
        try:
            self._runner(["cat-file", "-e", f"{ref}:{path}"])
        except PublishError:
            return False
        return True

    def is_ancestor(self, commit, ref):
        try:
            self._runner(["merge-base", "--is-ancestor", commit, ref])
        except PublishError:
            return False
        return True

    def subject(self, commit):
        return self._runner(["log", "-1", "--format=%s", commit]).decode("utf-8", "replace").strip()

    def author(self, commit):
        return self._runner(["log", "-1", "--format=%ae", commit]).decode("utf-8", "replace").strip()

    def list_files(self, commit, directory):
        out = self._runner(["ls-tree", "-r", "--name-only", commit, "--", directory])
        prefix = directory.rstrip("/") + "/"
        return [line[len(prefix):] for line in out.decode("utf-8", "replace").splitlines()
                if line.startswith(prefix) and line.endswith(".py")]


class SystemdRunner:
    ALLOWED_ACTIONS = frozenset({"is-active", "stop", "restart"})

    def __call__(self, unit, action):
        if action not in self.ALLOWED_ACTIONS:
            raise PublishError("unit_action_rejected", action)
        import subprocess

        result = subprocess.run(["systemctl", action, unit],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        return result.returncode == 0, result.stdout.decode("utf-8", "replace").strip()


def monitor_reader(timeout=5):
    user = MONITOR_USER_FILE.read_text(encoding="utf-8").strip()
    request = Request(MONITOR_URL, headers={"X-Authenticated-User": user})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def default_queue_lock(policy):
    """沿用模块自带的 queue_mutation：不创建文件、拒绝符号链接、校验元数据、NB flock。"""
    spec = (policy or {}).get("queue_lock") or {}
    module_dir = spec.get("module_dir")
    factory = spec.get("factory") or "automation_tick:queue_mutation"
    if not module_dir:
        raise PublishError("queue_lock_not_configured")
    module_name, _, attribute = factory.partition(":")
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attribute)()
    except BlockingIOError:
        raise PublishError("queue_lock_busy")
    except ImportError as exc:
        raise PublishError("queue_lock_unavailable", str(exc)[:160])
    except OSError as exc:
        raise PublishError("queue_lock_untrusted", str(exc)[:160])


@dataclass
class Paths:
    policy: Path = DEFAULT_POLICY
    checkout: Path = DEFAULT_CHECKOUT
    state_root: Path = DEFAULT_STATE_ROOT
    authorization_root: Path = DEFAULT_AUTHORIZATION_ROOT

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
# 两把锁：先 queue_mutation（既有协议），再 price-writer.lock；顺序不可换
# --------------------------------------------------------------------------- #
class ModuleLocks:
    def __init__(self, paths, policy, queue_factory=None, owner_uid=0, sleep=time.sleep):
        self.paths = paths
        self.policy = policy
        self._factory = queue_factory or (lambda: default_queue_lock(policy))
        self.owner_uid = owner_uid
        self._sleep = sleep
        self._queue_cm = None
        self._price_fd = None
        self._price_parent = None
        self._price_name = None

    def __enter__(self):
        try:
            self._queue_cm = self._factory()
            self._queue_cm.__enter__()
        except PublishError:
            raise
        except BlockingIOError:
            raise PublishError("queue_lock_busy")
        except OSError as exc:
            raise PublishError("queue_lock_untrusted", str(exc)[:160])
        try:
            self._acquire_price_lock()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _acquire_price_lock(self):
        path = self.paths.price_writer_lock
        fd, parent, name, info = open_beneath(path, self.owner_uid,
                                              validate_index(self.paths.state_root))
        try:
            mode = stat.S_IMODE(info.st_mode)
            if not stat.S_ISREG(info.st_mode):
                raise PublishError("price_lock_not_regular", str(path))
            if info.st_nlink != 1:
                raise PublishError("price_lock_hardlinked", f"nlink={info.st_nlink}")
            if info.st_uid != self.owner_uid:
                raise PublishError("price_lock_owner_mismatch", f"uid={info.st_uid}")
            if mode & 0o022:
                raise PublishError("price_lock_writable", oct(mode))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PublishError("price_lock_busy", str(path))
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise PublishError("price_lock_inode_changed", str(path))
        except BaseException:
            os.close(fd)
            os.close(parent)
            raise
        self._price_fd, self._price_parent, self._price_name = fd, parent, name

    def __exit__(self, *_exc):
        if self._price_fd is not None:
            try:
                fcntl.flock(self._price_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._price_fd)
                os.close(self._price_parent)
                self._price_fd = self._price_parent = None
        if self._queue_cm is not None:
            try:
                self._queue_cm.__exit__(None, None, None)
            finally:
                self._queue_cm = None
        return False


# --------------------------------------------------------------------------- #
# 发布器
# --------------------------------------------------------------------------- #
class Publisher:
    def __init__(self, paths=None, artifacts=None, systemd=None, monitor=None, sleep=time.sleep,
                 now=None, queue_factory=None, reader=None, policy_owner_uid=0):
        self.paths = paths or Paths()
        self._artifacts = artifacts
        self._systemd = systemd or SystemdRunner()
        self._monitor = monitor or monitor_reader
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._queue_factory = queue_factory
        self._reader = reader or read_trusted
        self.policy_owner_uid = policy_owner_uid
        self.policy = None
        self._entry = None

    @property
    def artifacts(self):
        if self._artifacts is None:
            self._artifacts = GitArtifacts(self.paths.checkout)
        return self._artifacts

    # -- 策略 -------------------------------------------------------------- #
    def load_policy(self):
        raw = json.loads(self._reader(self.paths.policy, self.policy_owner_uid,
                                      validate_index(self.paths.policy.parent)).decode("utf-8"))
        if raw.get("version") != 1 or not isinstance(raw.get("modules"), dict):
            raise PublishError("policy_schema")
        for module, entry in raw["modules"].items():
            if not MODULE_RE.match(module):
                raise PublishError("policy_module_name", module)
            for name, target in entry.get("targets", {}).items():
                if not TARGET_RE.match(name) or ".." in name:
                    raise PublishError("policy_target_name", name)
                if not any(target.startswith(root.rstrip("/") + "/") for root in entry.get("allowed_roots", [])):
                    raise PublishError("policy_target_outside_root", target)
            for unit, actions in entry.get("units", {}).items():
                if not set(actions) <= SystemdRunner.ALLOWED_ACTIONS:
                    raise PublishError("policy_unit_action", unit)
            for unit, files in entry.get("unit_entrypoints", {}).items():
                if unit not in entry.get("units", {}):
                    raise PublishError("policy_unit_entrypoint_unknown", unit)
                if not files:
                    raise PublishError("policy_unit_entrypoint_empty", unit)
            if not entry.get("module_source_dir"):
                raise PublishError("policy_module_source_missing", module)
        self.policy = raw
        return raw

    def module_policy(self, module):
        entry = (self.policy or {}).get("modules", {}).get(module)
        if entry is None:
            raise PublishError("module_not_in_policy", module)
        return entry

    # -- 授权（同一 fd） ---------------------------------------------------- #
    def _authorization(self, module, release, commit, scope):
        authz = self.policy.get("authorization", {}) or {}
        directory = Path(authz.get("dir") or self.paths.authorization_root)
        owner_uid = int(authz.get("owner_uid", 0))
        path = directory / module / f"{release}.json"
        raw = self._reader(path, owner_uid, validate_index(directory))
        try:
            record = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise PublishError("authorization_unreadable", str(exc)[:120])
        if str(record.get("merge_commit", "")) != commit:
            raise PublishError("authorization_commit_mismatch", str(record.get("merge_commit"))[:12])
        if sorted(record.get("scope") or []) != sorted(scope):
            raise PublishError("authorization_scope_mismatch")
        if not str(record.get("authorized_by", "")).strip():
            raise PublishError("authorization_authorizer_missing")
        expires = str(record.get("expires_at", ""))
        try:
            deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except ValueError:
            raise PublishError("authorization_expiry_invalid", expires)
        if deadline.tzinfo is None:
            raise PublishError("authorization_expiry_naive", expires)
        if deadline <= self._now():
            raise PublishError("authorization_expired", expires)
        authors = [a.strip().lower() for a in (authz.get("commit_authors") or [])]
        author = self.artifacts.author(commit).strip().lower()
        if not authors or author not in authors:
            raise PublishError("authorization_author_not_allowed", author)
        return record

    # -- 依赖决定单元 ------------------------------------------------------- #
    @staticmethod
    def _imports(blob):
        try:
            tree = ast.parse(blob.decode("utf-8", "replace"))
        except SyntaxError:
            return set()
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names.add(node.module.split(".")[0])
        return names

    def dependency_units(self, entry, commit, base, target_names):
        """按真实 import 关系推导：哪些单元会加载被替换的文件。"""
        source_dir = entry["module_source_dir"].rstrip("/")
        modules = {}
        for relative in self.artifacts.list_files(commit, source_dir):
            modules[Path(relative).stem] = self.artifacts.blob(commit, f"{source_dir}/{relative}")
        for name in target_names:
            modules[Path(name).stem] = self.artifacts.blob(commit, f"{base}/source/{name}")
        graph = {stem: {n for n in self._imports(blob) if n in modules} for stem, blob in modules.items()}

        def closure(stem):
            seen, stack = set(), [stem]
            while stack:
                current = stack.pop()
                if current in graph and current not in seen:
                    seen.add(current)
                    stack.extend(graph[current])
            return seen

        units = {}
        for unit, files in (entry.get("unit_entrypoints") or {}).items():
            loaded = set()
            for relative in files:
                loaded |= closure(Path(relative).stem)
            hits = [name for name in target_names if Path(name).stem in loaded]
            if hits:
                units[unit] = sorted(hits)
        return units

    # -- 校验 -------------------------------------------------------------- #
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

        manifest = json.loads(self.artifacts.blob(commit, f"{base}/targets.json"))
        targets = manifest.get("targets")
        if not isinstance(targets, dict) or not targets:
            raise PublishError("manifest_targets_empty")
        scope = approval.get("scope")
        if not isinstance(scope, list) or sorted(scope) != sorted(targets):
            raise PublishError("approval_scope_mismatch")

        authorization = self._authorization(module, release, commit, sorted(targets))

        plan = {"module": module, "release": release, "pr": pr, "merge_commit": commit,
                "base": base, "targets": {}, "units": {}}
        for name, row in targets.items():
            if name not in entry["targets"]:
                raise PublishError("target_not_in_policy", name)
            expected = entry["targets"][name]
            if row.get("target") != expected:
                raise PublishError("target_path_mismatch", name)
            after, before = str(row.get("after", "")), str(row.get("before", ""))
            if not SHA_RE.match(after) or not SHA_RE.match(before):
                raise PublishError("manifest_hash_invalid", name)
            if sha256_bytes(self.artifacts.blob(commit, f"{base}/source/{name}")) != after:
                raise PublishError("candidate_hash_mismatch", name)
            plan["targets"][name] = {"path": expected, "before": before, "after": after}

        plan["units"] = self.dependency_units(entry, commit, base, sorted(targets))
        for unit, names in plan["units"].items():
            granted = entry.get("units", {}).get(unit)
            if not granted:
                raise PublishError("unit_dependency_not_granted", unit)
            if "restart" not in granted:
                raise PublishError("unit_action_not_granted", unit)
        plan["units"] = {u: sorted(names) for u, names in sorted(plan["units"].items())}

        for name, row in plan["targets"].items():
            path = Path(row["path"])
            if path.is_symlink():
                raise PublishError("target_is_symlink", name)
            linked = symlinked_ancestors(row["path"])
            if linked:
                raise PublishError("target_parent_symlink", ";".join(linked[:3]))
            if not path.is_file():
                raise PublishError("target_missing", name)
            live = sha256_file(path)
            row["live"] = live
            if live != row["before"]:
                raise PublishError("baseline_drift", f"{name}:{live[:12]}!={row['before'][:12]}")
        plan["authorization"] = {"authorized_by": authorization.get("authorized_by"),
                                 "expires_at": authorization.get("expires_at"),
                                 "commit_author": self.artifacts.author(commit)}
        return plan

    def reverify(self, plan, stage):
        """取锁后、停服务后再核一次：授权有效期、候选字节、现场 before。"""
        self._authorization(plan["module"], plan["release"], plan["merge_commit"], sorted(plan["targets"]))
        for name, row in plan["targets"].items():
            blob = self.artifacts.blob(plan["merge_commit"], f"{plan['base']}/source/{name}")
            if sha256_bytes(blob) != row["after"]:
                raise PublishError("candidate_hash_mismatch", f"{stage}:{name}")
            live = sha256_file(Path(row["path"]))
            if live != row["before"]:
                raise PublishError("baseline_drift", f"{stage}:{name}:{live[:12]}!={row['before'][:12]}")
        return True

    # -- 运行态（只读） ---------------------------------------------------- #
    def check_idle(self):
        if list(self.paths.queue.glob("*.json")):
            raise PublishError("queue_not_idle")
        for path in self.paths.jobs.glob("*.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") in IDLE_JOB_RUNNING:
                raise PublishError("job_not_idle", path.name)
            if (job.get("kind") == "auto_cycle" and job.get("result", {}).get("status") == "confirmed"
                    and not job.get("completed_at")):
                raise PublishError("job_not_idle", path.name)
        for path in self.paths.executions.glob("*.json"):
            if json.loads(path.read_text(encoding="utf-8")).get("status") in UNRESOLVED_EXECUTION:
                raise PublishError("coin_execution_unresolved", path.name)

    def locks(self):
        owner_uid = int(((self.policy or {}).get("authorization") or {}).get("owner_uid", 0))
        return ModuleLocks(self.paths, self.policy or {}, self._queue_factory, owner_uid, self._sleep)

    def check_units(self, plan, entry=None):
        entry = entry or self._entry or self.module_policy(plan["module"])
        for unit in plan["units"]:
            granted = entry.get("units", {}).get(unit, [])
            if "is-active" not in granted:
                raise PublishError("unit_readback_not_granted", unit)
            ok, state = self._systemd(unit, "is-active")
            if not ok or state != "active":
                raise PublishError("unit_not_active", f"{unit}:{state}")

    # -- 写入 -------------------------------------------------------------- #
    def _protected_snapshot(self, entry, targets):
        skip = {row["path"] for row in targets.values()}
        snapshot = {}
        for root in [Path(r) for r in entry.get("allowed_roots", [])]:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink() or str(path) in skip:
                    continue
                if path.suffix in (".py", ".sh", ".js", ".json", ".html", ".css"):
                    snapshot[str(path)] = sha256_file(path)
        return snapshot

    def _backup(self, plan, directory):
        directory.mkdir(parents=True, exist_ok=False)
        meta = {"module": plan["module"], "release": plan["release"], "pr": plan["pr"],
                "merge_commit": plan["merge_commit"],
                "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
        for name, row in plan["targets"].items():
            source = Path(row["path"])
            info = source.stat()
            copy = directory / name
            copy.write_bytes(source.read_bytes())
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
            except Exception:  # noqa: BLE001 - 读回失败按"还没好"处理
                pass
            self._sleep(0.5)
        raise PublishError("runtime_not_ready", json.dumps(last, ensure_ascii=False)[:160] if last else "")

    def _receipt(self, payload):
        self.paths.receipt_root.mkdir(parents=True, exist_ok=True)
        path = self.paths.receipt_root / f"{payload['stamp']}-{payload['module']}.json"
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
                   "units": {}, "status": "started", "stages": []}
        backup_dir = self.paths.rollback_root / f"{stamp}-{plan['module']}"
        stopped, swapped = [], False
        try:
            payload["protected_before"] = self._protected_snapshot(entry, plan["targets"])
            self._backup(plan, backup_dir)
            payload["rollback_dir"] = str(backup_dir)

            for unit in plan["units"]:
                ok, detail = self._systemd(unit, "stop")
                payload["units"][unit] = {"stop": ok, "stop_detail": detail}
                if not ok:
                    raise PublishError("unit_stop_failed", f"{unit}:{detail}")
                stopped.append(unit)
            payload["stages"].append("stopped")

            self.reverify(plan, "post-stop")
            payload["stages"].append("post-stop-reverified")

            for name, row in plan["targets"].items():
                swapped = True
                self._atomic_swap(self.artifacts.blob(plan["merge_commit"], f"{plan['base']}/source/{name}"),
                                  row["path"])
                payload["targets"][name] = {"path": row["path"], "before": row["before"],
                                            "after": row["after"]}
            for unit in plan["units"]:
                ok, detail = self._systemd(unit, "restart")
                payload["units"].setdefault(unit, {})["restart"] = ok
                payload["units"][unit]["restart_detail"] = detail
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
                raise PublishError("protected_drift")
            payload["status"] = "published"
            payload["finished_at"] = datetime.now(timezone.utc).isoformat()
            payload["receipt"] = self._receipt(payload)
            return payload
        except Exception as exc:  # noqa: BLE001 - 任何失败都必须走回退
            payload["error"] = f"{getattr(exc, 'code', type(exc).__name__)}:{getattr(exc, 'detail', str(exc))}"[:300]
            payload["finished_at"] = datetime.now(timezone.utc).isoformat()
            rolled = self._rollback(payload, plan, backup_dir, stopped, swapped)
            payload["rollback"] = rolled
            if not rolled.get("ok"):
                payload["status"] = "unknown_write_state"
            elif rolled.get("unit_errors"):
                payload["status"] = "rolled_back_unit_errors"
            else:
                payload["status"] = "rolled_back"
            payload["receipt"] = self._receipt(payload)
            raise PublishError(payload["status"], payload["error"])

    def _rollback(self, payload, plan, backup_dir, stopped, swapped):
        """ok 只表示文件字节已恢复到 before；单元状态问题单独记，但同样不忽略。"""
        result = {"ok": False, "restored": {}, "errors": [], "unit_errors": []}
        if not swapped and not stopped:
            result["ok"] = True
            result["note"] = "nothing_written"
            return result
        if not backup_dir.exists():
            result["errors"].append("backup_missing")
            return result
        for unit in stopped:
            ok, detail = self._systemd(unit, "stop")
            if not ok:
                result["unit_errors"].append(f"stop:{unit}:{detail}")
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
            ok, detail = self._systemd(unit, "restart")
            if not ok:
                result["unit_errors"].append(f"restart:{unit}:{detail}")
        result["ok"] = not result["errors"]
        return result


def symlinked_ancestors(path):
    found = []
    parent = Path(path).parent
    while True:
        try:
            if parent.is_symlink():
                found.append(str(parent))
        except OSError:
            pass
        if str(parent) in ("/", ""):
            return found
        parent = parent.parent


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
        publisher.load_policy()
        entry = publisher.module_policy(module)
        plan = publisher.plan(module, release, pr)
        if not apply_mode:
            with publisher.locks():
                publisher.reverify(plan, "post-lock")
                publisher.check_idle()
                publisher.check_units(plan, entry)
            print(json.dumps({"mode": "check", "plan": plan}, ensure_ascii=False, indent=1))
            return 0
        if os.geteuid() != 0:
            raise PublishError("root_required")
        with publisher.locks():
            publisher.reverify(plan, "post-lock")
            publisher.check_idle()
            publisher.check_units(plan, entry)
            result = publisher.apply(plan, entry)
        print(json.dumps({"mode": "apply", "result": result}, ensure_ascii=False, indent=1))
        return 0
    except PublishError as exc:
        code = {"baseline_drift": 4, "price_lock_busy": 5, "price_lock_missing": 5,
                "queue_lock_busy": 5, "queue_lock_not_configured": 5, "queue_not_idle": 5,
                "job_not_idle": 5, "coin_execution_unresolved": 5,
                "rolled_back": 6, "rolled_back_unit_errors": 6,
                "unknown_write_state": 7}.get(exc.code, 3)
        print(json.dumps({"error": exc.code, "detail": exc.detail}, ensure_ascii=False), file=sys.stderr)
        return code


if __name__ == "__main__":
    sys.exit(main())
