#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""d4follow / AION2 模块的受控发布器 —— 唯一允许写生产 /opt/d4follow 的入口。

为什么需要它（2026-10-08 实测得到的教训）：
  /opt/d4follow 此前**没有任何受控发布入口**，部署靠手工 scp/rsync。后果是双向的：
    · 线上在用、仓库从来没有的文件 —— 钉钉推送活代码 dingtalk_push.py 曾在任何
      分支都找不到，线上是唯一副本；
    · 仓库旧版随时可能覆盖线上新版 —— main 的 opt/d4follow 自首次入库起一个字节
      未变，却比线上落后 9 个文件，谁按仓库同步一次就静默回退。
  所以「本机/运维机 → 生产」必须收敛到一个带守卫的入口。

本脚本做四件事：
  ① plan（只读）：远端 sha256 vs 仓库目标 sha256，逐文件给出处置判定；
  ② 旧版 / 未纳管守卫：远端内容若在仓库任何 ref 里都找不到对应版本 ⇒ 判定
     UNMANAGED 并拒发。这是防「覆盖掉服务器上直接改过的活代码」的唯一闸门；
  ③ apply（受控发布）：本地/远端发布锁 → 变更文件备份 → 逐文件上传与哈希条件替换
     → 逐文件 sha256 复核 → 复核失败自动从备份还原 → 写台账（本地 + 远端）；
  ④ rollback：校验当前 after 后按 releaseId 还原旧文件；新增文件保留，不删除。

明确不做：不整树 rsync、不删除远端文件、不改权限/认证、不碰 config.json、
不重启服务（config 变更后由人工按既定流程重启）。

用法（Windows OpenSSH；默认 dry-run，必须显式 --apply 才真正写生产）：
    python tools/release_d4follow.py plan     --host 47.85.224.112 --key D:/k/No1.pem
    python tools/release_d4follow.py apply    --host 47.85.224.112 --key D:/k/No1.pem \
        --release-id 20261008T1100Z --apply
    python tools/release_d4follow.py rollback --host 47.85.224.112 --key D:/k/No1.pem \
        --release-id 20261008T1100Z --apply
环境变量兜底：D4_RELEASE_HOST / _USER / _KEY / _DIR / _STATE / _SSH / _SCP / _KNOWN_HOSTS
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT_PREFIX = "opt/d4follow/"
DEFAULT_REMOTE_DIR = "/opt/d4follow"
ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")

# 发布单元内的例外：这些文件禁止从仓库发布。
#   set_dingtalk_secret.sh —— 线上是含真实钉钉 webhook token 的原件，仓库版是按
#   「凭据不入库」脱敏后的占位。从仓库发布会用空 token 覆盖线上 ⇒ 钉钉推送静默失效。
NEVER_PUBLISH = frozenset(["set_dingtalk_secret.sh"])


class Refused(RuntimeError):
    """守卫拒绝或发布失败；写入后的失败必须报告恢复结果。"""


# --------------------------------------------------------------------------
# 纯函数（离线可测，无 IO）
# --------------------------------------------------------------------------
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def check_release_id(value):
    if not ID_RE.match(value or ""):
        raise Refused("releaseId 必须匹配 %s，1-64 位（收到 %r）" % (ID_RE.pattern, value))
    return value


def safe_rel(value):
    """发布单元内相对路径守卫（相对 /opt/d4follow）。只允许平铺文件或 templates/ 一层。"""
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise Refused("非法发布路径：%r" % (value,))
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise Refused("发布路径不得含空段/./..：%r" % (value,))
    if len(parts) > 2 or (len(parts) == 2 and parts[0] != "templates"):
        raise Refused("发布单元只允许平铺文件或 templates/ 一层：%r" % (value,))
    return value


def classify(remote_sha, target_sha, known_repo_shas):
    """远端单文件的处置判定（纯函数）。

    NEW       远端不存在          → 纯新增，安全
    SAME      远端 == 目标         → 已一致，跳过
    OLD       远端内容可被仓库解释 → 升级覆盖，安全
    UNMANAGED 远端内容是仓库里没有的 → 拒发（服务器上可能有人直接改过）
    """
    if not remote_sha:
        return "NEW"
    if remote_sha == target_sha:
        return "SAME"
    if remote_sha in known_repo_shas:
        return "OLD"
    return "UNMANAGED"


def plan_actions(remote_map, target_map, known_by_rel, allow_unmanaged=False):
    """返回 (actions, refusals)。actions: [(rel, kind, remote_sha, target_sha)]。

    known_by_rel: {rel: {该文件在仓库出现过的内容 sha256}}，守卫按文件判定。
    """
    actions, refusals = [], []
    for rel in sorted(target_map):
        target_sha = target_map[rel]
        remote_sha = remote_map.get(rel)
        known = known_by_rel.get(rel, set()) if isinstance(known_by_rel, dict) else set(known_by_rel)
        kind = classify(remote_sha, target_sha, known)
        if kind == "UNMANAGED" and not allow_unmanaged:
            refusals.append((rel, remote_sha, target_sha))
        else:
            actions.append((rel, "OVERRIDE" if kind == "UNMANAGED" else kind, remote_sha, target_sha))
    return actions, refusals


# --------------------------------------------------------------------------
# 本地 git 读取
# --------------------------------------------------------------------------
def git(*args, stdin=None):
    return subprocess.run(["git", "-c", "safe.directory=%s" % ROOT, "-C", str(ROOT)] + list(args),
                          input=stdin, capture_output=True)


def git_show(ref, path):
    p = git("show", "%s:%s" % (ref, path))
    return p.stdout if p.returncode == 0 else None


def unit_files(ref):
    p = git("ls-tree", "-r", "--name-only", ref, UNIT_PREFIX)
    if p.returncode != 0:
        raise Refused("git ls-tree 失败：%s" % p.stderr.decode("utf-8", "replace").strip())
    return [x for x in p.stdout.decode("utf-8", "replace").split("\n") if x.strip()]


def target_map(ref, only=None):
    out = {}
    for full in unit_files(ref):
        rel = full[len(UNIT_PREFIX):]
        if rel in NEVER_PUBLISH:
            continue
        if only and rel not in only:
            continue
        safe_rel(rel)
        data = git_show(ref, full)
        if data is None:
            raise Refused("无法读取 %s:%s" % (ref, full))
        out[rel] = sha256_bytes(data)
    if not out:
        raise Refused("发布单元为空（ref=%s, only=%s）" % (ref, only))
    return out


def repo_known_shas(rels):
    """{rel: {该文件在仓库所有 ref 上出现过的内容 sha256}} —— 守卫的「可解释」集合。

    实现：一次 `git rev-list --all --objects` 拿到发布单元下所有历史 blob，再两次
    `git cat-file --batch-check/--batch` 批量取内容算 sha256。不走「ref×文件逐个 git show」，
    那在 Windows 上要上千次子进程，实测会超时。
    """
    wanted = set(rels)
    p = git("rev-list", "--all", "--objects", "--", UNIT_PREFIX)
    if p.returncode != 0:
        raise Refused("git rev-list 失败：%s" % p.stderr.decode("utf-8", "replace").strip())
    rel_oids, all_oids = {}, set()
    for line in p.stdout.decode("utf-8", "replace").split("\n"):
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        oid, path = parts
        if not path.startswith(UNIT_PREFIX):
            continue
        rel = path[len(UNIT_PREFIX):]
        if rel not in wanted:
            continue
        rel_oids.setdefault(rel, set()).add(oid)
        all_oids.add(oid)
    if not all_oids:
        return {}
    chk = git("cat-file", "--batch-check", stdin=("\n".join(sorted(all_oids)) + "\n").encode())
    blobs = [x.split()[0] for x in chk.stdout.decode("utf-8", "replace").split("\n")
             if len(x.split()) == 3 and x.split()[1] == "blob"]
    if not blobs:
        return {}
    raw = git("cat-file", "--batch", stdin=("\n".join(blobs) + "\n").encode()).stdout
    sha_by_oid, i = {}, 0
    while i < len(raw):
        nl = raw.index(b"\n", i)
        parts = raw[i:nl].decode("utf-8", "replace").split()
        if len(parts) != 3:
            break
        size = int(parts[2])
        start = nl + 1
        sha_by_oid[parts[0]] = sha256_bytes(raw[start:start + size])
        i = start + size + 1
    return {rel: {sha_by_oid[o] for o in oids if o in sha_by_oid} for rel, oids in rel_oids.items()}


def fixed_commit(value, full=False):
    """显式基线模式只接受提交 ID；先解析一次，后续读取固定完整 ID。"""
    pattern = r"[0-9a-fA-F]{40}" if full else r"[0-9a-fA-F]{7,40}"
    if not re.fullmatch(pattern, value or ""):
        raise Refused("显式基线模式要求 %s提交 SHA：%r" % ("完整 " if full else "固定 ", value))
    p = git("rev-parse", "--verify", "%s^{commit}" % value)
    resolved = p.stdout.decode("ascii", "replace").strip()
    if p.returncode != 0 or not re.fullmatch(r"[0-9a-fA-F]{40}", resolved):
        raise Refused("无法解析固定提交：%s" % value)
    return resolved.lower()


def baseline_known_shas(commit, rels):
    """只以指定提交的同路径内容作证明，不扫描其它 ref 或历史 blob。"""
    known = {}
    for rel in rels:
        safe_rel(rel)
        data = git_show(commit, UNIT_PREFIX + rel)
        known[rel] = {sha256_bytes(data)} if data is not None else set()
    return known


# --------------------------------------------------------------------------
# 远端 IO（ssh / scp）
# --------------------------------------------------------------------------
REMOTE_HASH_SCRIPT = """
import hashlib, json, os, sys
root = sys.argv[1]
out = {}
for rel in json.loads(sys.argv[2]):
    p = os.path.join(root, rel)
    if os.path.isfile(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
sys.stdout.write(json.dumps(out))
"""

# 在同一远端进程内检查来源和目标，再替换。调用者持有远端发布锁。
REMOTE_REPLACE_SCRIPT = """
import hashlib, json, os, shutil, sys, uuid
src, dst, expected_before, expected_after, restore = json.loads(sys.argv[1])
def digest(path):
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError('refuse non-regular path: ' + path)
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()
if digest(src) != expected_after:
    raise RuntimeError('source hash changed: ' + src)
if digest(dst) != expected_before:
    raise RuntimeError('destination CAS mismatch: ' + dst)
if restore:
    staged = src + '.restore.' + uuid.uuid4().hex
    shutil.copy2(src, staged)
    if digest(staged) != expected_after or digest(dst) != expected_before:
        raise RuntimeError('restore CAS mismatch: ' + dst)
    src = staged
os.replace(src, dst)
"""


class Remote(object):
    def __init__(self, host, user, key):
        self.host, self.user, self.key = host, user, key
        self.ssh = os.environ.get("D4_RELEASE_SSH", r"C:\Windows\System32\OpenSSH\ssh.exe")
        self.scp = os.environ.get("D4_RELEASE_SCP", r"C:\Windows\System32\OpenSSH\scp.exe")
        if not os.path.exists(self.key):
            raise Refused("找不到密钥文件：%s" % self.key)
        for exe in (self.ssh, self.scp):
            if not os.path.exists(exe):
                raise Refused("找不到 OpenSSH 可执行文件：%s" % exe)

    def opts(self):
        opts = ["-i", self.key,
                "-o", "StrictHostKeyChecking=yes",
                "-o", "BatchMode=yes",
                "-o", "KexAlgorithms=curve25519-sha256,curve25519-sha256@libssh.org",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=15",
                "-o", "ServerAliveInterval=20"]
        known_hosts = os.environ.get("D4_RELEASE_KNOWN_HOSTS")
        if known_hosts:
            if not Path(known_hosts).is_file():
                raise Refused("找不到已核验的 known_hosts 文件：%s" % known_hosts)
            opts += ["-o", 'UserKnownHostsFile="%s"' % known_hosts.replace("\\", "/")]
        return opts

    def target(self):
        return "%s@%s" % (self.user, self.host)

    def run(self, cmd, timeout=180):
        p = subprocess.run([self.ssh] + self.opts() + [self.target(), cmd],
                           capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

    def must(self, cmd, timeout=180, what="远端命令"):
        rc, out, err = self.run(cmd, timeout=timeout)
        if rc != 0:
            raise Refused("%s 失败（rc=%d）：%s" % (what, rc, (err or out).strip()[:400]))
        return out

    def hashes(self, remote_dir, rels):
        if not rels:
            return {}
        payload = base64.b64encode(REMOTE_HASH_SCRIPT.encode("utf-8")).decode("ascii")
        args = json.dumps(list(rels))
        cmd = "python3 -c %s %s %s" % (
            _shq("import base64,sys;exec(base64.b64decode('%s'))" % payload),
            _shq(remote_dir), _shq(args))
        out = self.must(cmd, what="远端 sha256 采集").strip()
        return json.loads(out) if out else {}

    def mkdir(self, path):
        self.must("mkdir -p %s" % _shq(path), what="远端 mkdir")

    def mkdir_exclusive(self, path):
        self.must("mkdir %s" % _shq(path), what="远端独占目录（已存在则拒绝）")

    def upload_tree(self, local_dir, remote_tmp):
        parts = sorted(Path(local_dir).iterdir())
        if not parts:
            raise Refused("staging 目录为空")
        self.mkdir_exclusive(remote_tmp)
        dst = "%s:%s/" % (self.target(), remote_tmp)
        cmd = [self.scp, "-O", "-r", "-q"] + self.opts() + [str(x) for x in parts] + [dst]
        p = subprocess.run(cmd, capture_output=True, timeout=900)
        if p.returncode != 0:
            raise Refused("scp 上传失败：%s" % p.stderr.decode("utf-8", "replace").strip()[:400])

    def copy(self, src, dst):
        self.must("cp -p %s %s" % (_shq(src), _shq(dst)), what="远端备份 cp")

    def mv(self, src, dst):
        self.must("mv -f %s %s" % (_shq(src), _shq(dst)), what="远端原子 mv")

    def replace_checked(self, src, dst, expected_before, expected_after, restore=False):
        payload = base64.b64encode(REMOTE_REPLACE_SCRIPT.encode("utf-8")).decode("ascii")
        values = json.dumps([src, dst, expected_before, expected_after, restore])
        self.must("python3 -c %s %s" % (
            _shq("import base64,sys;exec(base64.b64decode('%s'))" % payload), _shq(values)),
            what="远端哈希条件替换")

    def write_text(self, path, text):
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.must("python3 -c %s %s %s" % (
            _shq("import base64,os,sys,uuid;"
                 "p=sys.argv[1];os.makedirs(os.path.dirname(p),exist_ok=True);"
                 "t=p+'.writing.'+uuid.uuid4().hex;"
                 "f=open(t,'xb');f.write(base64.b64decode(sys.argv[2]));"
                 "f.flush();os.fsync(f.fileno());f.close();os.replace(t,p)"),
            _shq(path), _shq(payload)), what="远端写台账")


class RemoteLock(object):
    """跨机器发布互斥；不抢占旧锁，只释放含本次 token 的空目录。"""

    def __init__(self, remote, remote_dir):
        self.remote = remote
        self.path = remote_dir.rstrip("/") + "/.release.lock"
        self.owner = self.path + "/" + uuid.uuid4().hex

    def __enter__(self):
        self.remote.mkdir_exclusive(self.path)
        # 若连接中断，保留锁供人工核查，绝不强制抢锁。
        self.remote.mkdir_exclusive(self.owner)
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.remote.must("rmdir %s && rmdir %s" % (_shq(self.owner), _shq(self.path)),
                             what="释放本次远端空锁")
        except Exception as error:
            if kind is None:
                raise
            print("远端锁未释放，须核查 %s：%s" % (self.path, error))


def _shq(value):
    """POSIX 单引号引用（远端都是 Linux）。"""
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


# --------------------------------------------------------------------------
# 本地状态
# --------------------------------------------------------------------------
def state_path(state_dir, release_id):
    d = Path(state_dir) / "releases"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%s.json" % release_id)


def write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Lock(object):
    """本地发布锁：同一台运维机不允许两个发布同时跑。"""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(str(self.path), "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                self.f.write(b"0")
                self.f.flush()
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise Refused("另一个发布正在进行（锁 %s 被占用）" % self.path)
        return self

    def __exit__(self, *exc):
        self.f.close()


# --------------------------------------------------------------------------
# 命令实现
# --------------------------------------------------------------------------
def _resolve_only(args, ref):
    only = set()
    if args.files:
        for item in args.files.split(","):
            item = item.strip()
            if not item:
                continue
            safe_rel(item)
            if item in NEVER_PUBLISH:
                raise Refused("%s 在 NEVER_PUBLISH 名单里，禁止从仓库发布" % item)
            only.add(item)
        # 只发布仓库里确实存在的路径
        existing = set(x[len(UNIT_PREFIX):] for x in unit_files(ref))
        missing = only - existing
        if missing:
            raise Refused("指定文件不在 %s 的发布单元里：%s" % (ref, ", ".join(sorted(missing))))
        return only
    return None


def gather(args):
    rid = getattr(args, "release_id", None)
    if rid:
        check_release_id(rid)
    ref = args.ref
    baseline = getattr(args, "baseline_ref", None)
    if baseline:
        if getattr(args, "allow_unmanaged", False):
            raise Refused("显式基线模式禁止 --allow-unmanaged")
        ref = fixed_commit(ref, full=True)
        baseline = fixed_commit(baseline)
        args._baseline_commit = baseline
        print("固定基线证明：%s（只读取本次待变更路径，不扫描历史）" % baseline, flush=True)
    remote = Remote(args.host, args.user, args.key)
    only = _resolve_only(args, ref)
    targets = target_map(ref, only)
    remote_map = remote.hashes(args.remote_dir, list(targets))
    if baseline:
        changed_existing = [r for r in targets if remote_map.get(r) and remote_map[r] != targets[r]]
        known = baseline_known_shas(baseline, changed_existing)
    else:
        known = repo_known_shas(list(targets))
    actions, refusals = plan_actions(remote_map, targets, known,
                                     allow_unmanaged=getattr(args, "allow_unmanaged", False))
    return remote, ref, targets, remote_map, known, actions, refusals


def print_plan(ref, actions, refusals):
    print("发布源 ref : %s (%s)" % (ref, git("rev-parse", ref).stdout.decode().strip()))
    print("%-34s %-10s %s" % ("文件", "处置", "说明"))
    print("-" * 88)
    for rel, kind, rem, tgt in actions:
        note = {"NEW": "远端不存在，纯新增",
                "SAME": "已一致，跳过",
                "OLD": "远端=仓库历史版本，升级覆盖",
                "OVERRIDE": "⚠ 覆盖远端未纳管内容（人工已确认）"}[kind]
        print("%-34s %-10s %s" % (rel, kind, note))
    for rel, rem, tgt in refusals:
        print("%-34s %-10s %s" % (rel, "UNMANAGED", "❌ 远端内容不在本次 Git 证明集合中：%s" % rem[:16]))
    print("-" * 88)
    change = [a for a in actions if a[1] != "SAME"]
    print("总计 %d 个文件；需变更 %d；拒发 %d" % (
        len(actions) + len(refusals), len(change), len(refusals)))


def cmd_plan(args):
    _, ref, _, _, _, actions, refusals = gather(args)
    print_plan(ref, actions, refusals)
    if refusals:
        print("\n结论：会拒发（存在未纳管文件）。先核对并纳管当前现役版本。")
        return 1
    print("\n结论：可安全发布（无未纳管文件）。")
    return 0


def check_hashes(remote, directory, expected, label):
    actual = remote.hashes(directory, list(expected))
    bad = [r for r, value in expected.items() if actual.get(r) != value]
    if bad:
        raise Refused("%s哈希不一致：%s" % (label, ", ".join(bad)))


def backup_name(rel):
    return rel.replace("/", "__") + ".before"


def save_record(args, remote, record):
    write_json_atomic(state_path(args.state_dir, args.release_id), record)
    remote.write_text("%s/_release_ledger/%s.json" % (args.remote_dir.rstrip("/"), args.release_id),
                      json.dumps(record, ensure_ascii=False, indent=2))


def recover_replaced(remote, remote_dir, backup_dir, attempted):
    """连回执不明的替换也核对；只还原本次 after，绝不覆盖第三方后续变更。"""
    restored, retained, unrestored = [], [], []
    for item in reversed(attempted):
        rel, before, after = item["rel"], item["before"], item["after"]
        try:
            current = remote.hashes(remote_dir, [rel]).get(rel)
            if current == before:
                restored.append(rel)
            elif current != after:
                unrestored.append(rel + "（现态已变化，未覆盖）")
            elif before is None:
                retained.append(rel)
            else:
                remote.replace_checked(backup_dir + "/" + backup_name(rel),
                                       remote_dir.rstrip("/") + "/" + rel, after, before, restore=True)
                check_hashes(remote, remote_dir, {rel: before}, "恢复后")
                restored.append(rel)
        except Exception as error:
            unrestored.append("%s（%s）" % (rel, error))
    return {"restored": restored, "retainedNew": retained, "unrestored": unrestored}


def cmd_apply(args):
    if not args.apply:
        print("[dry-run] 未加 --apply，只做判定，不写远端。\n")
        return cmd_plan(args)
    check_release_id(args.release_id)
    lock_path = Path(args.state_dir) / "release.lock"
    with Lock(lock_path):
        remote, ref, targets, remote_map, known, actions, refusals = gather(args)
        if refusals:
            print_plan(ref, actions, refusals)
            raise Refused("存在 %d 个未纳管文件；先核对并纳管当前现役版本" % len(refusals))
        change = [a for a in actions if a[1] != "SAME"]
        print_plan(ref, actions, refusals)
        if not change:
            print("\n远端已与发布源一致，无需发布。")
            return 0

        if state_path(args.state_dir, args.release_id).exists():
            raise Refused("releaseId 已有本地台账，必须使用新的 releaseId")
        backup_dir = "%s/_bak_release_%s" % (args.remote_dir.rstrip("/"), args.release_id)
        staging_parent = tempfile.mkdtemp(prefix="d4follow-release-")
        staging = Path(staging_parent) / args.release_id
        staging.mkdir(parents=True)
        for rel, kind, rem, tgt in change:
            data = git_show(ref, UNIT_PREFIX + rel)
            if data is None:
                raise Refused("无法从 %s 读取 %s" % (ref, rel))
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)

        remote_tmp = "%s/.release_%s.tmp" % (args.remote_dir.rstrip("/"), args.release_id)
        record = {
            "releaseId": args.release_id,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "host": args.host,
            "remoteDir": args.remote_dir,
            "sourceRef": ref,
            "baselineCommit": getattr(args, "_baseline_commit", None),
            "sourceTree": git("rev-parse", "%s^{tree}" % ref).stdout.decode().strip(),
            "backupDir": backup_dir,
            "stagingDir": remote_tmp,
            "status": "prepared",
            "files": [{"rel": rel, "before": rem, "after": tgt} for rel, kind, rem, tgt in change],
        }
        with RemoteLock(remote, args.remote_dir):
            baseline = {r: remote_map.get(r) for r in targets}
            check_hashes(remote, args.remote_dir, baseline, "加锁后现态")
            remote.mkdir_exclusive(backup_dir)
            print("\n[1/5] 远端备份 → %s" % backup_dir)
            for item in record["files"]:
                if item["before"]:
                    remote.copy(args.remote_dir.rstrip("/") + "/" + item["rel"],
                                backup_dir + "/" + backup_name(item["rel"]))
            check_hashes(remote, backup_dir,
                         {backup_name(i["rel"]): i["before"] for i in record["files"] if i["before"]},
                         "备份")

            print("[2/5] 上传 staging → %s" % remote_tmp)
            remote.upload_tree(str(staging), remote_tmp)
            check_hashes(remote, remote_tmp, {i["rel"]: i["after"] for i in record["files"]}, "上传后")
            check_hashes(remote, args.remote_dir, baseline, "替换前最终现态")
            # 先留可恢复台账，再做首个替换；断线时仍能查到准确 before/after。
            save_record(args, remote, record)
            attempted = []
            try:
                print("[3/5] 逐文件哈希条件替换")
                for item in record["files"]:
                    attempted.append(item)  # SSH 回执不明也必须检查是否已替换。
                    remote.replace_checked(remote_tmp + "/" + item["rel"],
                                           args.remote_dir.rstrip("/") + "/" + item["rel"],
                                           item["before"], item["after"])
                print("[4/5] 复核线上")
                check_hashes(remote, args.remote_dir, targets, "发布后")
                print("[5/5] 写台账")
                record["status"] = "applied"
                save_record(args, remote, record)
            except BaseException as error:
                recovery = recover_replaced(remote, args.remote_dir, backup_dir, attempted)
                record.update(status="apply-failed", failure=str(error), recovery=recovery)
                try:
                    save_record(args, remote, record)
                except Exception as ledger_error:
                    print("失败台账未完整写入：%s" % ledger_error)
                raise Refused("发布失败：%s；已恢复=%s；保留新增=%s；未恢复=%s" % (
                    error, recovery["restored"], recovery["retainedNew"], recovery["unrestored"])) from error
        print("\n发布完成：%s（%d 个文件）" % (args.release_id, len(change)))
        print("备份和暂存目录均保留；本工具不重启服务。")
        print("回滚命令：python tools/release_d4follow.py rollback --host %s --key <KEY> --release-id %s --apply"
              % (args.host, args.release_id))
        return 0


def cmd_rollback(args):
    if not args.apply:
        print("[dry-run] 未加 --apply，只做检查，不写远端。")
    check_release_id(args.release_id)
    record = state_path(args.state_dir, args.release_id)
    if not record.exists():
        raise Refused("本地台账里没有 releaseId=%s" % args.release_id)
    rec = json.loads(record.read_text(encoding="utf-8"))
    if rec.get("host") != args.host or rec.get("remoteDir", "").rstrip("/") != args.remote_dir.rstrip("/"):
        raise Refused("回滚主机/目录与发布台账不一致")
    expected_backup = "%s/_bak_release_%s" % (args.remote_dir.rstrip("/"), args.release_id)
    if rec.get("backupDir") != expected_backup or rec.get("releaseId") != args.release_id:
        raise Refused("回滚备份位置与 releaseId 不一致")
    if rec.get("status") != "applied":
        raise Refused("台账状态不是已发布；请先核查记录，不得盲目重放：%s" % rec.get("status"))
    print("将回滚 %s（发布于 %s，%d 个文件）" % (rec["releaseId"], rec["at"], len(rec["files"])))
    for item in rec["files"]:
        safe_rel(item["rel"])
        print("   %-34s %s -> %s" % (item["rel"], (item["after"] or "-")[:12], (item["before"] or "新增文件保留、不删除")[:20]))
    if not args.apply:
        return 0
    lock_path = Path(args.state_dir) / "release.lock"
    with Lock(lock_path):
        remote = Remote(args.host, args.user, args.key)
        with RemoteLock(remote, args.remote_dir):
            check_hashes(remote, args.remote_dir, {i["rel"]: i["after"] for i in rec["files"]}, "回滚前现态")
            existing = [i for i in rec["files"] if i["before"] is not None]
            check_hashes(remote, rec["backupDir"],
                         {backup_name(i["rel"]): i["before"] for i in existing}, "回滚备份")
            recovery = recover_replaced(remote, args.remote_dir, rec["backupDir"], rec["files"])
            rec["recovery"] = recovery
            rec["status"] = "rollback-failed" if recovery["unrestored"] else "rolled-back"
            rec["rolledBackAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                save_record(args, remote, rec)
            except Exception as error:
                raise Refused("回滚文件核对结果=%s；台账写入失败=%s" % (recovery, error)) from error
            if recovery["unrestored"]:
                raise Refused("回滚部分失败；已恢复=%s；未恢复=%s；保留新增=%s" % (
                    recovery["restored"], recovery["unrestored"], recovery["retainedNew"]))
        print("回滚完成：%s" % args.release_id)
        print("新增文件保留（旧代码恢复后不再引用）：%s" % recovery["retainedNew"])
    return 0


def main():
    ap = argparse.ArgumentParser(description="d4follow 受控发布器（唯一允许写生产 /opt/d4follow 的入口）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--host", default=os.environ.get("D4_RELEASE_HOST"))
        p.add_argument("--user", default=os.environ.get("D4_RELEASE_USER", "root"))
        p.add_argument("--key", default=os.environ.get("D4_RELEASE_KEY"))
        p.add_argument("--remote-dir", default=os.environ.get("D4_RELEASE_DIR", DEFAULT_REMOTE_DIR))
        p.add_argument("--ref", default="HEAD")
        p.add_argument("--baseline-ref", help="仅用指定固定基线提交证明现役版本，避免扫描全部历史；--ref 须完整提交 SHA")
        p.add_argument("--files", default="", help="逗号分隔的相对路径；留空=整个发布单元")
        p.add_argument("--state-dir", default=os.environ.get("D4_RELEASE_STATE", str(Path.home() / ".d4follow-release")))
        p.add_argument("--apply", action="store_true", help="不加则 dry-run")

    for name, helptext in (("plan", "只读：远端 vs 仓库逐文件判定"),
                           ("apply", "受控发布"),
                           ("rollback", "按 releaseId 还原")):
        parser = sub.add_parser(name, help=helptext)
        common(parser)
        if name in ("apply", "rollback"):
            parser.add_argument("--release-id", required=True)
        if name == "apply":
            parser.add_argument("--allow-unmanaged", action="store_true",
                                help="允许覆盖远端未纳管内容（需人工确认后再加）")

    args = ap.parse_args()
    if not args.host or not args.key:
        ap.error("必须提供 --host 与 --key（或用环境变量 D4_RELEASE_HOST / D4_RELEASE_KEY）")
    try:
        handler = {"plan": cmd_plan, "apply": cmd_apply, "rollback": cmd_rollback}[args.cmd]
        raise SystemExit(handler(args))
    except Refused as error:
        print(json.dumps({"status": "refused", "reason": str(error)}, ensure_ascii=False))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
