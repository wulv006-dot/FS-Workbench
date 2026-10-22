#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FS 访问控制引擎 (fs-iam) · 策略求值内核
==========================================

设计参照 **阿里云 RAM / AWS IAM** 的授权模型，替换过去那套「路径里有没有
admin/deploy 关键词」的启发式判断：

    成员 (subject)  --绑定-->  角色 (role)  --包含-->  策略规则 (rule)
    规则 = 允许访问的「资源集合」×「动作集合」

四条硬规则（与大厂一致）
------------------------
1. **默认拒绝（deny by default）**：没被任何规则命中 → 403。
2. **显式拒绝优先**：命中了 deny 规则，即使同时命中 allow 也一律拒绝。
3. **最小权限**：角色只拿到显式列出的 资源×动作，没有隐式继承。
4. **决策可解释**：每次判断都能回答「谁 / 要什么动作 / 落在哪个资源 /
   命中了哪条规则 / 为什么被拒」。

资源与动作
----------
动作只有 5 个，覆盖全站所有写操作：

    view     浏览、读取
    edit     改数据（改价、写配置、提交表单）
    execute  触发类（采集、刷新、执行、跑任务）
    deploy   部署通道（/deploy/ 与 nginx 的 group=deploy）
    manage   成员与授权（IAM 控制台、/admin）

资源 = 业务模块（d4 / nba / mlb / sales / tasks …）+ 平台类
（home / identity / deploy / admin / unmapped）。

URI → 资源 的映射是**显式前缀表**，最长前缀优先，不再猜关键词。
改路由只要改 RESOURCES 一处。

本模块只做纯计算：不读 htpasswd、不碰 cookie、不联网，方便单测。
"""
import json
import os
import posixpath
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit

SCHEMA_VERSION = 1

# ---------------------------------------------------------------- 常量

VIEW, EDIT, EXECUTE, DEPLOY, MANAGE = "view", "edit", "execute", "deploy", "manage"
ACTIONS = (VIEW, EDIT, EXECUTE, DEPLOY, MANAGE)

ACTION_LABELS = (
    (VIEW, "查看"),
    (EDIT, "改数据"),
    (EXECUTE, "执行"),
    (DEPLOY, "部署"),
    (MANAGE, "授权"),
)

# 超级角色名：持有它的成员 = 全权管理员（历史 ADMINS 名单的来源）
ADMIN_ROLE = "PlatformAdmin"

HERE = os.path.dirname(os.path.abspath(__file__))

# 活策略（含成员绑定）是可写状态，放 data 目录；代码目录只读。
LIVE_POLICY = os.environ.get("FS_IAM_POLICY") or "/opt/auth-portal/data/fs-iam/policy.json"
AUDIT_LOG = os.environ.get("FS_IAM_AUDIT") or "/opt/auth-portal/data/fs-iam/audit.jsonl"
SEED_POLICY = os.environ.get("FS_IAM_SEED") or os.path.join(HERE, "policy.seed.json")

# 与旧 access_policy.CONTROL 完全一致的动词表：命中即视为「执行」而不是「查看」。
CONTROL = frozenset((
    "apply", "execute", "run", "start", "stop", "pause", "resume", "reset",
    "delete", "save", "update", "set", "clear", "unlock", "clear-lock",
    "clear_lock", "reset-lock", "reset_lock", "ban", "unban", "deploy",
    "publish", "restart", "backfill", "collect", "refresh-now", "refresh_now",
))

# 这些路径段出现在 URI 里就升级动作：admin → manage，deploy → deploy。
_SEGMENT_ACTION = {"admin": MANAGE, "deploy": DEPLOY}
# 与旧策略保持一致：非管理员命中这些路径段一律拒绝（任何方法）。
_SEGMENT_GUARDED = frozenset(("admin", "deploy"))

# ---------------------------------------------------------------- 资源目录
# (资源 id, 中文名, 所属工作区, (路径前缀...))
# ★ 这里是 URI → 资源的**唯一真源**。id 与旧 module_permissions.MODULES 对齐，
#   以便注册账号的既有授权可以原样平移过来。
SECTIONS = (
    ("analytics", "数据分析"),
    ("brain", "Hermes 智体"),
    ("sports", "球类工作区"),
    ("arpg", "RPG 工作区"),
    ("bots", "机器人管理"),
    ("collaboration", "协作工具"),
    ("platform", "平台与账号"),
)

RESOURCES = (
    # ---- 平台与账号 ----
    ("identity", "身份与门户", "platform", ("/__auth", "/verify")),
    ("admin", "成员与授权", "platform", ("/admin", "/__auth/iam")),
    ("deploy", "部署工作台", "platform", ("/deploy",)),
    # ---- 数据分析 ----
    ("unified-business", "数据看板", "analytics", ("/dashboard/analytics", "/dashboard/users")),
    ("data-analysis-tools", "数据分析工具", "analytics", ("/dashboard/data-tools",)),
    ("management", "经营管理台", "analytics", ("/dashboard/management",)),
    ("game-monitor", "游戏监控台", "analytics", ("/dashboard/game-monitor",)),
    # ---- Hermes 智体 ----
    ("brain", "Hermes 智体", "brain", ("/dashboard/fs-home/brain",)),
    # ---- 球类工作区 ----
    ("coins", "FC27 金币控制台", "sports", ("/dashboard/fc27-coins.html", "/dashboard/fc27-coins.")),
    ("fc27-bundles", "FC27 捆绑包改价", "sports", ("/dashboard/modules/sports/bundles",)),
    ("fc27-sbc", "FC27 SBC 上架工具", "sports", ("/dashboard/fc27-sbc",)),
    ("ops", "FC27 运营看板", "sports", ("/s/wulv/fc27-ops",)),
    ("players", "FC27 球员维护", "sports", ("/tools/fc27-players",)),
    ("gallery", "FC27 收藏馆调价", "sports", ("/tools/fc27-gallery",)),
    ("odds", "FC26 库存与交付", "sports", ("/s/wulv/fc-odds",)),
    ("mlb", "MLB 新卡工作台", "sports", ("/mlb",)),
    ("nba", "NBA2K 自动改价台", "sports", ("/nba2k27",)),
    ("madden", "Madden 金币看板", "sports", ("/dashboard/madden27-coins.html", "/dashboard/madden27-coins.")),
    # ---- RPG 工作区 ----
    ("d4", "RPG 游戏改价系统", "arpg", ("/d4",)),
    ("g2g", "G2G 自动改价", "arpg", ("/g2g",)),
    ("sales", "销售部系统", "arpg", ("/sales",)),
    # ---- 机器人管理 ----
    ("bot-console", "Discord 机器人控制台", "bots", ("/bots",)),
    # ---- 协作工具 ----
    ("tasks", "项目工作任务台", "collaboration", ("/dashboard/tasks",)),
    ("green_plan", "绿茵计划", "collaboration", ("/dashboard/tasks/green-plan", "/dashboard/tasks/api/green-plan")),
    ("docs", "部门手册", "collaboration", ("/docs",)),
    ("sites", "团队工具目录", "collaboration", ("/s",)),
    # ---- 兜底 ----
    ("home", "平台首页", "platform", ("/dashboard",)),
    ("sensitive", "敏感 API", "platform", ()),
)

RESOURCE_IDS = tuple(rid for rid, _l, _s, _p in RESOURCES)
RESOURCE_LABEL = {rid: label for rid, label, _s, _p in RESOURCES}
RESOURCE_SECTION = {rid: sec for rid, _l, sec, _p in RESOURCES}

# 最长前缀优先：/dashboard/tasks/api/green-plan 先命中 green_plan 而不是 tasks
_PREFIX_TABLE = sorted(
    ((prefix, rid) for rid, _l, _s, prefixes in RESOURCES for prefix in prefixes),
    key=lambda item: -len(item[0]),
)

# 历史兼容例外：改造前 access_policy.py 第 24 行有一条「任务台自己管权限，
# 所以放行这个 PATCH」的特例。任务台内部仍会校验成员身份 / 指派人 / 字段权限，
# 因此这里按原样保留，但**写进策略文件**（compat_exceptions），可见、可审计、
# 也可以随时删掉 —— 不再藏在代码里。
COMPAT_EXCEPTION_DEFAULT = {
    "id": "green-plan-task-patch",
    "desc": "任务台内部自带成员/指派人/字段校验，仅放行该精确路由的 PATCH",
    "methods": ["PATCH"],
    "uri": r"/dashboard/tasks/api/green-plan/tasks/G[0-9]+",
    "excludeSubjectPrefix": "reg:",
}

# 旧策略里「注册账号不可直达」的路径：保留资源名便于解释，语义同 unmapped。
BLOCKED_PREFIXES = (
    "/dashboard/api/",
    "/dashboard/fc27-quote-api/",
    "/dashboard/fc27-activity-api/",
    "/api/fc27/cloud/",
    "/dashboard/tasks/api/members",
    "/s/wulv/fc27-ops/api/collect",
)

UNMAPPED = "unmapped"


# ---------------------------------------------------------------- 路径 → 资源

def normalize_path(uri):
    """解码 + 归一化。多次解码防 %252e 之类的二次编码绕过。"""
    raw = urlsplit(uri or "/").path or "/"
    for _ in range(4):
        try:
            decoded = unquote(raw, errors="strict")
        except Exception:
            break
        if decoded == raw:
            break
        raw = decoded
    path = posixpath.normpath("/" + raw.replace("\\", "/").lstrip("/"))
    if raw.endswith("/") and not path.endswith("/"):
        path += "/"
    return path


def segments(path):
    return [s for s in re.split(r"[/\\]+", path.lower()) if s]


def resolve_resource(uri):
    """URI → 资源 id。显式前缀表，最长前缀优先，不做关键词猜测。"""
    path = normalize_path(uri)
    if path == "/":
        return "identity"
    for prefix in BLOCKED_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return UNMAPPED
    for prefix, rid in _PREFIX_TABLE:
        if path == prefix or path.startswith(prefix if prefix.endswith("/") else prefix + "/"):
            return rid
    return UNMAPPED


def _query_has_control(uri):
    try:
        pairs = parse_qs(urlsplit(uri or "/").query)
    except Exception:
        return False
    for key, values in pairs.items():
        if key.lower() in ("action", "op", "command", "cmd"):
            if any(str(v).lower() in CONTROL for v in values):
                return True
    return False


def requirement(method, uri, group=""):
    """判定这次请求需要哪个动作。返回 (resource_id, action)。

    与旧策略逐条等价：
      * group=deploy 或资源本身是 deploy → 需要 deploy
      * 路径含 admin / deploy 段 → 分别需要 manage / deploy（任何方法）
      * admin 资源 → 需要 manage
      * GET/HEAD → view；查询串带控制动词 → execute
      * 其余方法 → execute（路径段是控制动词）否则 edit
      * identity 资源 → 永远只要求 view（登录自举，防止把自己锁在外面）
    """
    path = normalize_path(uri)
    resource = resolve_resource(path)
    method = (method or "GET").upper()

    if resource == "identity" and method in ("GET", "HEAD", "OPTIONS"):
        # 门户自身只读：登录、登出、/verify 都靠它，任何人不能被锁在外面。
        # 写请求不享受这个旁路，继续按通用规则判定（与旧策略「非 GET 一律拒」一致）。
        return resource, VIEW
    if resource == "admin":
        return resource, MANAGE

    segs = set(segments(path))
    for seg, action in _SEGMENT_ACTION.items():
        if seg in segs and seg in _SEGMENT_GUARDED:
            return resource, action

    if group == "deploy" or resource == "deploy":
        return resource, DEPLOY

    if method in ("GET", "HEAD", "OPTIONS"):
        # 旧策略对「GET 但路径里带控制动词」也是拒绝的（/d4/api/collect 之类），
        # 这里把动作升级成 execute 而不是 view，语义保持一致。
        if segs & CONTROL or _query_has_control(uri):
            return resource, EXECUTE
        return resource, VIEW

    if segs & CONTROL or _query_has_control(uri):
        return resource, EXECUTE
    return resource, EDIT


# ---------------------------------------------------------------- 策略读写

class PolicyError(Exception):
    pass


def _as_rule_list(value, where):
    if value is None:
        return []
    if not isinstance(value, list):
        raise PolicyError("%s 必须是数组" % where)
    out = []
    for i, rule in enumerate(value):
        if not isinstance(rule, dict):
            raise PolicyError("%s[%d] 必须是对象" % (where, i))
        resources = rule.get("resources", rule.get("resource"))
        actions = rule.get("actions", rule.get("action"))
        resources = [resources] if isinstance(resources, str) else list(resources or [])
        actions = [actions] if isinstance(actions, str) else list(actions or [])
        if not resources or not actions:
            raise PolicyError("%s[%d] 缺 resources/actions" % (where, i))
        for a in actions:
            if a != "*" and a not in ACTIONS:
                raise PolicyError("%s[%d] 未知动作 %r" % (where, i, a))
        out.append({"resources": [str(r) for r in resources], "actions": [str(a) for a in actions]})
    return out


def validate(policy):
    """严格校验。宁可拒绝启动，也不要用一份半错的策略放行。"""
    if not isinstance(policy, dict):
        raise PolicyError("策略必须是对象")
    if policy.get("schema") != SCHEMA_VERSION:
        raise PolicyError("schema 必须是 %d" % SCHEMA_VERSION)
    roles = policy.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise PolicyError("roles 缺失")
    if ADMIN_ROLE not in roles:
        raise PolicyError("缺少超级角色 %s" % ADMIN_ROLE)
    for name, role in roles.items():
        if not isinstance(role, dict):
            raise PolicyError("角色 %s 必须是对象" % name)
        _as_rule_list(role.get("rules"), "roles.%s.rules" % name)
        if not role.get("super") and not role.get("rules"):
            raise PolicyError("角色 %s 既非 super 又没有任何规则" % name)
    bindings = policy.get("bindings") or {}
    if not isinstance(bindings, dict):
        raise PolicyError("bindings 必须是对象")
    unbound = policy.get("unbound_role") or ""
    if unbound:
        if unbound not in roles:
            raise PolicyError("unbound_role 指向不存在的角色 %r" % unbound)
        if roles[unbound].get("super"):
            raise PolicyError("unbound_role 不能是超级角色（否则等于全站默认管理员）")
    for subject, binding in bindings.items():
        if isinstance(binding, list):
            binding = {"roles": binding}
        if not isinstance(binding, dict):
            raise PolicyError("bindings.%s 必须是对象或数组" % subject)
        for role in binding.get("roles") or []:
            if role not in roles:
                raise PolicyError("bindings.%s 引用了不存在的角色 %r" % (subject, role))
        _as_rule_list(binding.get("grants"), "bindings.%s.grants" % subject)
        _as_rule_list(binding.get("deny"), "bindings.%s.deny" % subject)
    supers = [n for n, r in roles.items() if r.get("super")]
    admins = [s for s, b in bindings.items()
              if isinstance(b, dict) and any(r in supers for r in (b.get("roles") or []))]
    if not admins and not [s for s, b in bindings.items() if isinstance(b, list)
                           and any(r in supers for r in b)]:
        raise PolicyError("至少要保留一名超级管理员")
    return policy


def default_policy():
    """首次运行时的种子策略：完全复刻改造前的既有权限，零行为变化。"""
    return {
        "schema": SCHEMA_VERSION,
        "generation": 1,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated_by": "system:seed",
        "roles": {
            ADMIN_ROLE: {
                "label": "平台管理员",
                "desc": "全部模块全部动作，含部署与成员授权",
                "super": True,
                "rules": [],
            },
            "Viewer": {
                "label": "只读访客",
                "desc": "只能浏览，不能改动任何数据（改造前非管理员账号的等价权限）",
                "rules": [{"resources": ["*"], "actions": [VIEW]}],
            },
            "PricingOps": {
                "label": "定价运营",
                "desc": "RPG / 球类改价：可改价、可触发采集，不可部署、不可授权",
                "rules": [{"resources": ["d4", "g2g", "nba", "fc27-bundles", "fc27-sbc",
                                         "coins", "madden", "players", "gallery", "game-monitor"],
                           "actions": [VIEW, EDIT, EXECUTE]}],
            },
            "SportsOps": {
                "label": "球类运营",
                "desc": "FC27 / FC26 / NBA2K / MLB 全部可改可跑",
                "rules": [{"resources": ["coins", "fc27-bundles", "fc27-sbc", "ops", "players",
                                         "gallery", "odds", "mlb", "nba", "madden"],
                           "actions": [VIEW, EDIT, EXECUTE]}],
            },
            "ArpgOps": {
                "label": "RPG 运营",
                "desc": "D4 / G2G / 销售部系统可改可跑",
                "rules": [{"resources": ["d4", "g2g", "sales"],
                           "actions": [VIEW, EDIT, EXECUTE]}],
            },
            "CollabEditor": {
                "label": "协作编辑",
                "desc": "任务台 / 绿茵计划 / 部门手册可读写，其余只读",
                "rules": [{"resources": ["tasks", "green_plan", "docs"],
                           "actions": [VIEW, EDIT, EXECUTE]},
                          {"resources": ["*"], "actions": [VIEW]}],
            },
            "Deployer": {
                "label": "部署负责人",
                "desc": "可使用部署工作台，其余按只读",
                "rules": [{"resources": ["deploy"], "actions": [VIEW, DEPLOY]},
                          {"resources": ["*"], "actions": [VIEW]}],
            },
            "Auditor": {
                "label": "审计员",
                "desc": "全站只读 + 可查授权变更与决策日志",
                "rules": [{"resources": ["*"], "actions": [VIEW]}],
            },
            "Analyst": {
                "label": "数据分析",
                "desc": "只看数据看板 / 监控台 / Hermes 智体",
                "rules": [{"resources": ["unified-business", "data-analysis-tools", "management",
                                         "game-monitor", "brain", "home"],
                           "actions": [VIEW]}],
            },
        },
        "bindings": {
            "wulv": {"roles": [ADMIN_ROLE]},
            "chenchao": {"roles": [ADMIN_ROLE]},
            "DY": {"roles": [ADMIN_ROLE]},
            "fstech": {"roles": [ADMIN_ROLE]},
            "mmoexp": {"roles": ["Viewer"]},
        },
        "compat_exceptions": [dict(COMPAT_EXCEPTION_DEFAULT)],
        "unbound_role": "Viewer",
    }


def _atomic_write(path, text):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".policy.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_policy(path=None):
    path = path or LIVE_POLICY
    if not os.path.exists(path):
        seed = SEED_POLICY if os.path.exists(SEED_POLICY) else None
        if seed:
            with open(seed, "r", encoding="utf-8") as fh:
                policy = json.load(fh)
        else:
            policy = default_policy()
        validate(policy)
        if path.startswith("/opt/"):
            _atomic_write(path, json.dumps(policy, ensure_ascii=False, indent=2) + "\n")
        return policy
    with open(path, "r", encoding="utf-8") as fh:
        policy = json.load(fh)
    return validate(policy)


def save_policy(policy, actor, path=None, audit_path=None, note=""):
    """原子落盘 + 追加审计。返回新 revision。"""
    path = path or LIVE_POLICY
    validate(policy)
    old = None
    try:
        old = load_policy(path)
    except Exception:
        old = None
    changes = diff(old, policy) if old else []
    if os.path.exists(path):
        try:
            shutil.copy2(path, path + ".bak")
            shutil.copy2(path, "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S")))
            _prune_backups(path, keep=20)
        except OSError:
            pass
    policy["generation"] = int(policy.get("generation") or 0) + 1
    policy["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    policy["updated_by"] = actor
    body = json.dumps(policy, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    _atomic_write(path, body)
    append_audit({
        "at": int(time.time()),
        "actor": actor,
        "kind": "policy.save",
        "note": note,
        "generation": policy["generation"],
        "revision": revision_of(policy),
        "changes": changes,
    }, audit_path)
    return revision_of(policy)


def _prune_backups(path, keep=20):
    """按时间戳滚动保留，避免 .bak-* 无限堆积。"""
    directory = os.path.dirname(path)
    base = os.path.basename(path)
    try:
        names = sorted(n for n in os.listdir(directory) if n.startswith(base + ".bak-"))
    except OSError:
        return
    for name in names[:-keep] if len(names) > keep else []:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


def append_audit(entry, audit_path=None):
    path = audit_path or AUDIT_LOG
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError:
        pass


def read_audit(limit=200, audit_path=None):
    path = audit_path or AUDIT_LOG
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:][::-1]


def revision_of(policy):
    import hashlib
    body = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def diff(old, new):
    """粗粒度变更清单：角色增删改 + 绑定增删改。给审计看，不求精确到字段。"""
    changes = []
    if not old:
        return changes
    old_roles, new_roles = old.get("roles") or {}, new.get("roles") or {}
    for name in set(old_roles) | set(new_roles):
        if name not in old_roles:
            changes.append({"op": "role.add", "role": name})
        elif name not in new_roles:
            changes.append({"op": "role.remove", "role": name})
        elif _rule_signature(old_roles[name]) != _rule_signature(new_roles[name]):
            changes.append({"op": "role.update", "role": name})
    old_bind, new_bind = _norm_bindings(old), _norm_bindings(new)
    for subject in set(old_bind) | set(new_bind):
        if subject not in old_bind:
            changes.append({"op": "member.add", "subject": subject, "roles": new_bind[subject]})
        elif subject not in new_bind:
            changes.append({"op": "member.remove", "subject": subject, "roles": old_bind[subject]})
        elif old_bind[subject] != new_bind[subject]:
            changes.append({"op": "member.roles", "subject": subject,
                            "from": old_bind[subject], "to": new_bind[subject]})
    return changes


def _rule_signature(role):
    if role.get("super"):
        return ("super",)
    sig = []
    for rule in role.get("rules") or []:
        sig.append((tuple(sorted(rule.get("resources") or [])),
                    tuple(sorted(rule.get("actions") or []))))
    return tuple(sorted(sig))


def _norm_bindings(policy):
    out = {}
    for subject, binding in (policy.get("bindings") or {}).items():
        if isinstance(binding, list):
            binding = {"roles": binding}
        out[subject] = sorted(binding.get("roles") or [])
    return out


# ---------------------------------------------------------------- 求值

class Decision(object):
    __slots__ = ("allow", "code", "subject", "resource", "action", "roles",
                 "reason", "matched")

    def __init__(self, allow, code, subject, resource, action, roles=(), reason="", matched=()):
        self.allow = allow
        self.code = code
        self.subject = subject
        self.resource = resource
        self.action = action
        self.roles = list(roles)
        self.reason = reason
        self.matched = list(matched)

    def as_dict(self):
        return {
            "allow": self.allow,
            "code": self.code,
            "subject": self.subject,
            "resource": self.resource,
            "resourceLabel": RESOURCE_LABEL.get(self.resource, self.resource),
            "action": self.action,
            "actionLabel": dict(ACTION_LABELS).get(self.action, self.action),
            "roles": self.roles,
            "reason": self.reason,
            "matched": self.matched,
        }

    def __repr__(self):
        return "<Decision %s %s:%s %s %s>" % (
            self.subject, self.resource, self.action,
            "ALLOW" if self.allow else "DENY", self.reason)


def binding_of(policy, subject):
    binding = (policy.get("bindings") or {}).get(subject)
    if binding is None:
        return None
    if isinstance(binding, list):
        return {"roles": list(binding)}
    return binding


def is_admin(policy, subject):
    """是否全权管理员（= 旧 ADMINS 名单的语义）。"""
    binding = binding_of(policy, subject)
    if not binding:
        return False
    roles = policy.get("roles") or {}
    return any((roles.get(r) or {}).get("super") for r in binding.get("roles") or [])


def admins(policy):
    return frozenset(s for s in (policy.get("bindings") or {}) if is_admin(policy, s))


def _rule_hit(rule, resource, action):
    resources = rule.get("resources") or []
    actions = rule.get("actions") or []
    res_ok = "*" in resources or resource in resources
    act_ok = "*" in actions or action in actions
    return res_ok and act_ok


def grant_matrix(policy, subject):
    """聚合成员的生效权限：{resource: set(actions)}，供控制台展示。"""
    binding = effective_binding(policy, subject)[0] or {}
    roles = policy.get("roles") or {}
    matrix = {}
    for role_name in binding.get("roles") or []:
        role = roles.get(role_name) or {}
        if role.get("super"):
            for rid in RESOURCE_IDS:
                matrix.setdefault(rid, set()).update(ACTIONS)
            matrix.setdefault(UNMAPPED, set()).update((VIEW,))
            continue
        for rule in role.get("rules") or []:
            targets = RESOURCE_IDS if "*" in (rule.get("resources") or []) else rule["resources"]
            for rid in targets:
                matrix.setdefault(rid, set()).update(
                    ACTIONS if "*" in (rule.get("actions") or []) else rule["actions"])
    for rule in binding.get("grants") or []:
        targets = RESOURCE_IDS if "*" in (rule.get("resources") or []) else rule["resources"]
        for rid in targets:
            matrix.setdefault(rid, set()).update(
                ACTIONS if "*" in (rule.get("actions") or []) else rule["actions"])
    for rule in binding.get("deny") or []:
        targets = RESOURCE_IDS if "*" in (rule.get("resources") or []) else rule["resources"]
        for rid in targets:
            if rid not in matrix:
                continue
            if "*" in (rule.get("actions") or []):
                matrix.pop(rid, None)
            else:
                matrix[rid] -= set(rule["actions"])
                if not matrix[rid]:
                    matrix.pop(rid, None)
    return {rid: sorted(acts) for rid, acts in matrix.items() if acts}


def _compat_exception(policy, subject, method, uri):
    """命中历史兼容例外则返回该例外（None 表示没有）。"""
    for exc in policy.get("compat_exceptions") or []:
        prefix = exc.get("excludeSubjectPrefix")
        if prefix and str(subject).startswith(prefix):
            continue
        methods = [str(m).upper() for m in (exc.get("methods") or [])]
        if (method or "GET").upper() not in methods:
            continue
        try:
            if re.fullmatch(exc.get("uri") or r"(?!)", uri or ""):
                return exc
        except re.error:
            continue
    return None


def effective_binding(policy, subject):
    """成员的生效绑定。

    没有绑定的人**不会**因此变成管理员，也不会被无声放行：
    如果策略里配了 unbound_role（默认 Viewer），就按那个角色走，并在决策理由里
    标明「默认角色」——这正是改造前「非管理员只能读」的等价行为；
    把 unbound_role 置空即变成严格的 deny-by-default。
    """
    binding = binding_of(policy, subject)
    if binding:
        return binding, False
    fallback = policy.get("unbound_role") or ""
    if fallback and fallback in (policy.get("roles") or {}):
        return {"roles": [fallback], "grants": [], "deny": []}, True
    return None, False


def evaluate(policy, subject, method, uri, group=""):
    """核心求值。返回 Decision。"""
    resource, action = requirement(method, uri, group)

    if not subject:
        return Decision(False, 401, "", resource, action, reason="未登录")

    # A missing binding must revoke this dedicated identity, never fall back to Viewer.
    if subject == "dot_fc_observer":
        bound = binding_of(policy, subject) or {}
        parsed = urlsplit(uri or "/")
        allowed = parsed.path in (
            "/api/fc27/cloud/automation", "/api/fc27/cloud/monitor",
            "/api/fc27/cloud/pricing/state")
        allowed = allowed or bool(re.fullmatch(
            r"/api/fc27/cloud/jobs/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
            parsed.path))
        if ((method or "GET").upper() != "GET" or group == "deploy"
                or parsed.query or parsed.fragment or not allowed
                or "FCObserver" not in (bound.get("roles") or [])):
            return Decision(False, 403, subject, resource, action,
                            reason="FC observer exact read scope required")
        resource, action = "coins", VIEW

    # 身份自举：已登录成员永远能访问门户自身，避免改错策略把所有人锁在门外。
    if resource == "identity" and (method or "GET").upper() in ("GET", "HEAD", "OPTIONS"):
        return Decision(True, 200, subject, resource, action,
                        reason="identity-bootstrap")

    binding, implicit = effective_binding(policy, subject)
    roles = policy.get("roles") or {}
    if not binding:
        return Decision(False, 403, subject, resource, action, reason="未分配角色（默认拒绝）")

    role_names = list(binding.get("roles") or [])
    tag = "（默认角色）" if implicit else ""

    for rule in binding.get("deny") or []:
        if _rule_hit(rule, resource, action):
            return Decision(False, 403, subject, resource, action, role_names,
                            reason="显式拒绝优先",
                            matched=["deny:%s/%s" % (resource, action)])

    exc = _compat_exception(policy, subject, method, uri)
    if exc:
        return Decision(True, 200, subject, resource, action, role_names,
                        reason="兼容例外 %s" % exc.get("id"), matched=["compat:%s" % exc.get("id")])

    for name in role_names:
        role = roles.get(name) or {}
        if role.get("super"):
            return Decision(True, 200, subject, resource, action, role_names,
                            reason="超级角色 %s%s" % (name, tag), matched=["role:%s(super)" % name])

    matched = []
    for name in role_names:
        role = roles.get(name) or {}
        for index, rule in enumerate(role.get("rules") or []):
            if _rule_hit(rule, resource, action):
                matched.append("role:%s#%d" % (name, index))
    for index, rule in enumerate(binding.get("grants") or []):
        if _rule_hit(rule, resource, action):
            matched.append("grant#%d" % index)

    if matched:
        return Decision(True, 200, subject, resource, action, role_names,
                        reason="命中 %s%s" % (matched[0], tag), matched=matched)
    return Decision(False, 403, subject, resource, action, role_names,
                    reason="没有任何规则授予 %s:%s（默认拒绝）" % (resource, action))


def authorize(policy, subject, method, uri, group=""):
    """便捷入口：只要状态码。"""
    return evaluate(policy, subject, method, uri, group).code


# ---------------------------------------------------------------- 目录（给 UI）

def catalog():
    """资源目录：按工作区分组，附带每个资源的可授权动作。"""
    out = []
    for section_id, section_label in SECTIONS:
        items = [{"id": rid, "label": RESOURCE_LABEL[rid],
                  "actions": list(ACTIONS) if rid != "identity" else [VIEW]}
                 for rid, _l, sec, _p in RESOURCES if sec == section_id]
        if items:
            out.append({"id": section_id, "label": section_label, "resources": items})
    return out


def summarize_role(role):
    if role.get("super"):
        return "全部资源 · 全部动作"
    parts = []
    for rule in role.get("rules") or []:
        resources = rule.get("resources") or []
        actions = rule.get("actions") or []
        res_label = "全部资源" if "*" in resources else "、".join(
            RESOURCE_LABEL.get(r, r) for r in resources[:4]) + ("…" if len(resources) > 4 else "")
        act_label = "全部动作" if "*" in actions else "、".join(
            dict(ACTION_LABELS).get(a, a) for a in actions)
        parts.append("%s → %s" % (res_label, act_label))
    return "；".join(parts)
