#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs-iam 控制台 · 成员 / 角色 / 授权 / 自检 / 审计
=================================================

挂在统一门户下：对外就是门户导航栏那个 `/__auth/access/`。nginx 把这个前缀
内部改写到后端的 `/iam/`，所以本文件里的路径常量仍然是 `/iam`（后端不对外暴露）；
页面里的相对路径 `./api/*` 由浏览器解析成 `/__auth/access/api/*`，同样被改写回来。

由 auth_portal 调用，不自己监听端口、不自己认证 —— 身份来自门户已签名的
Cookie，`portal.read_token()` 已经做了 epoch 校验，这里只做**授权**：

    能进控制台 <=> 该成员在策略里被授予 admin 资源的 manage 动作

设计参照阿里云 RAM 控制台的交互：左侧「成员管理 / 角色与策略 / 权限自检 /
审计日志」，右侧表格与抽屉。所有写操作都：
    1. 校验 CSRF（双提交 Cookie + Origin）
    2. 校验 revision（乐观锁，防止两人同时改覆盖对方）
    3. 落盘前 validate（含「至少保留一名超级管理员」）
    4. 追加审计（谁 / 何时 / 改了什么 / 前值 → 后值）
"""
import html
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rbac  # noqa: E402

WEB_DIR = os.path.join(HERE, "web")
CSRF_COOKIE = "FS_IAM_CSRF"
CSRF_HEADER = "X-CSRF-Token"
MAX_BODY = 256 * 1024

_STATIC = {
    "/iam": ("index.html", "text/html; charset=utf-8"),
    "/iam/": ("index.html", "text/html; charset=utf-8"),
    "/iam/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/iam/app.css": ("app.css", "text/css; charset=utf-8"),
}

PAGE_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
     "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
)

# ---------------------------------------------------------------- 基础工具

def _json(handler, code, payload, headers=None):
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return handler._send(code, body, "application/json; charset=utf-8", headers=headers)


def _cookie_of(portal, handler, name):
    return portal.parse_cookies(handler.headers.get("Cookie", "")).get(name) or ""


def _session_user(portal, handler):
    token = _cookie_of(portal, handler, portal.CFG["cookie"])
    payload = portal.read_token(token) if token else None
    return (payload or {}).get("u") or ""


def _csrf_token(portal, handler, issue=False):
    """双提交 CSRF：读 Cookie，没有就签发一个（供页面 JS 读取后回传 header）。"""
    token = _cookie_of(portal, handler, CSRF_COOKIE)
    header = None
    if not token and issue:
        token = os.urandom(18).hex()
        bits = ["%s=%s" % (CSRF_COOKIE, token), "Path=/", "SameSite=Lax", "Max-Age=43200"]
        if portal.CFG["secure"]:
            bits.append("Secure")
        header = ("Set-Cookie", "; ".join(bits))
    return token, header


def _origin_ok(portal, handler):
    """Origin/Referer 必须是本站。缺失时靠 SameSite=Lax + CSRF 双提交兜底。"""
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return True
    try:
        host = origin.split("://", 1)[1].split("/", 1)[0]
    except IndexError:
        return False
    allowed = {"47.85.224.112", "47.85.224.112:443", "127.0.0.1:8895", "localhost:8895"}
    return host in allowed


def _read_body(handler):
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None
    if length < 0 or length > MAX_BODY:
        return None
    if not length:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 成员与登录态

def _registration_store(portal):
    """冻结运行时里的注册库（只读）。拿不到就退化为「只有内置账号」。"""
    bridge = getattr(portal, "_registration_bridge", None)
    if bridge is None:
        return None
    try:
        return bridge.adapter.store
    except Exception:
        return None


def _registered_users(portal):
    store = _registration_store(portal)
    if store is None:
        return []
    out = []
    try:
        fence = getattr(getattr(store, "namespace", None), "fence", None)
        ctx = fence() if callable(fence) else None
        if ctx is None:
            class _Null(object):
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            ctx = _Null()
        with ctx:
            with store.connection() as db:
                for row in db.execute("SELECT id,name,state FROM users ORDER BY name"):
                    out.append({"id": row["id"], "name": row["name"], "state": row["state"]})
    except Exception:
        return []
    return out


_LOGIN_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[\w+\] 登录(成功|失败) user=(\S+)"
    r"(?: [^i]*)? ip=(\S+)")


def _recent_logins(portal):
    """从门户审计日志尾巴里取每个账号最近一次登录（成功优先）。"""
    path = os.path.join(portal.CFG["data_dir"], "audit.log")
    out = {}
    try:
        size = os.path.getsize(path)
        start = max(0, size - 400 * 1024)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            if start:
                fh.seek(start)
                fh.readline()
            lines = fh.readlines()
    except OSError:
        return out
    for line in reversed(lines):
        match = _LOGIN_RE.match(line.strip())
        if not match:
            continue
        stamp, ok, user, ip = match.groups()
        slot = out.setdefault(user, {"at": stamp, "ip": ip, "ok": ok == "成功"})
        if ok == "成功" and not slot["ok"]:
            slot.update(at=stamp, ip=ip, ok=True)
        elif ok == "成功":
            break
    return out


def _normalized_binding(binding):
    if binding is None:
        return []
    if isinstance(binding, list):
        return list(binding)
    return list(binding.get("roles") or [])


def _members(portal, policy):
    rows = {}
    for group, path in portal.GROUPS.items():
        for name in portal.load_htpasswd(path):
            row = rows.setdefault(name, {
                "subject": name, "name": name, "kind": "native",
                "source": "内置账号", "groups": [], "enabled": True, "state": "active",
            })
            row["groups"].append(group)
    for user in _registered_users(portal):
        subject = "reg:" + user["id"]
        rows[subject] = {
            "subject": subject, "name": user["name"], "kind": "registered",
            "source": "注册账号", "groups": ["dashboard"],
            "enabled": user["state"] == "readonly", "state": user["state"],
        }

    logins = _recent_logins(portal)
    roles = policy.get("roles") or {}
    out = []
    for subject, row in rows.items():
        bound = _normalized_binding((policy.get("bindings") or {}).get(subject))
        matrix = rbac.grant_matrix(policy, subject)
        writable = sorted(r for r, acts in matrix.items() if set(acts) & {"edit", "execute", "deploy", "manage"})
        row.update(
            roles=bound,
            admin=rbac.is_admin(policy, subject),
            roleLabels=[(roles.get(r) or {}).get("label", r) for r in bound],
            accessCount=len(matrix),
            writable=writable,
            lastLogin=logins.get(row["name"]) or logins.get(subject) or None,
        )
        out.append(row)
    out.sort(key=lambda r: (not r["admin"], r["kind"] != "native", r["name"].casefold()))
    return out


# ---------------------------------------------------------------- 视图数据

def _policy_view(policy, actor):
    roles = []
    members = _normalized_members(policy)
    for name, role in (policy.get("roles") or {}).items():
        roles.append({
            "name": name,
            "label": role.get("label") or name,
            "desc": role.get("desc") or "",
            "super": bool(role.get("super")),
            "rules": role.get("rules") or [],
            "summary": rbac.summarize_role(role),
            "members": sorted(s for s, rs in members.items() if name in rs),
            "builtin": name in ("PlatformAdmin", "Viewer"),
        })
    roles.sort(key=lambda r: (not r["super"], r["name"]))
    return {
        "revision": rbac.revision_of(policy),
        "generation": policy.get("generation"),
        "updatedAt": policy.get("updated_at"),
        "updatedBy": policy.get("updated_by"),
        "roles": roles,
        "bindings": members,
        "compat": policy.get("compat_exceptions") or [],
        "actor": actor,
    }


def _normalized_members(policy):
    out = {}
    for subject, binding in (policy.get("bindings") or {}).items():
        out[subject] = _normalized_binding(binding)
    return out


def _meta(policy):
    return {
        "revision": rbac.revision_of(policy),
        "generation": policy.get("generation"),
        "updatedAt": policy.get("updated_at"),
        "updatedBy": policy.get("updated_by"),
        "path": rbac.LIVE_POLICY,
    }


# ---------------------------------------------------------------- 写操作

def _mutate(portal, actor, note, mutate, revision_expect):
    """统一的「读-改-校验-落盘」流程，带乐观锁与锁死保护。"""
    policy = rbac.load_policy()
    current = rbac.revision_of(policy)
    if revision_expect and revision_expect != current:
        return 409, {"error": "策略已被他人修改，请刷新后重试", "revision": current}
    mutate(policy)
    try:
        rbac.validate(policy)
    except rbac.PolicyError as exc:
        return 400, {"error": "策略校验未通过：%s" % exc}
    if not rbac.is_admin(policy, actor):
        return 409, {"error": "这次改动会让你自己失去管理员权限，已阻止（防止把自己锁在门外）"}
    new_rev = rbac.save_policy(policy, actor, note=note)
    portal.log("IAM 策略变更 actor=%s note=%s rev=%s" % (actor, note, new_rev), "info")
    return 200, {"ok": True, "revision": new_rev, "generation": policy.get("generation")}


def _api_role_save(portal, actor, body):
    engine = rbac
    name = (body.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,39}", name or ""):
        return 400, {"error": "角色名需 2–40 位，字母开头，仅字母数字 _ . -"}
    label = (body.get("label") or name).strip()[:40]
    desc = (body.get("desc") or "").strip()[:200]
    rules = []
    for item in body.get("rules") or []:
        resources = [str(r) for r in (item.get("resources") or []) if str(r) in rbac.RESOURCE_IDS or str(r) == "*"]
        actions = [str(a) for a in (item.get("actions") or []) if str(a) in rbac.ACTIONS or str(a) == "*"]
        if resources and actions:
            rules.append({"resources": resources, "actions": actions})
    is_super = bool(body.get("super"))
    if name == rbac.ADMIN_ROLE and not is_super:
        return 400, {"error": "超级角色不能被降级，请另建管理员角色"}
    if not is_super and not rules:
        return 400, {"error": "至少勾选一个资源与动作，否则这个角色等于「什么都不给」"}

    def apply(policy):
        policy.setdefault("roles", {})[name] = {
            "label": label, "desc": desc, "super": is_super,
            "rules": [] if is_super else rules,
        }

    return _mutate(portal, actor, "角色保存：%s" % name, apply, body.get("revision"))


def _api_role_delete(portal, actor, body):
    name = (body.get("name") or "").strip()
    if name == rbac.ADMIN_ROLE:
        return 400, {"error": "超级角色不能删除"}
    policy = rbac.load_policy()
    if name not in (policy.get("roles") or {}):
        return 404, {"error": "角色不存在"}
    used = [s for s, rs in _normalized_members(policy).items() if name in rs]
    if used:
        return 409, {"error": "还有 %d 名成员在用这个角色：%s" % (len(used), "、".join(used[:5]))}

    def apply(policy2):
        policy2["roles"].pop(name, None)

    return _mutate(portal, actor, "角色删除：%s" % name, apply, body.get("revision"))


def _api_member_roles(portal, actor, body):
    subject = (body.get("subject") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,39}|reg:[a-f0-9-]{36}", subject):
        return 400, {"error": "成员标识无效"}
    roles = [str(r) for r in (body.get("roles") or [])]
    policy = rbac.load_policy()
    known = set(policy.get("roles") or {})
    unknown = [r for r in roles if r not in known]
    if unknown:
        return 400, {"error": "角色不存在：%s" % "、".join(unknown)}

    def apply(policy2):
        bindings = policy2.setdefault("bindings", {})
        old = bindings.get(subject)
        entry = dict(old) if isinstance(old, dict) else {}
        entry["roles"] = sorted(set(roles))
        if not entry["roles"] and not entry.get("grants"):
            bindings.pop(subject, None)
        else:
            bindings[subject] = entry

    return _mutate(portal, actor, "成员授权：%s → %s" % (subject, ",".join(roles) or "无"),
                   apply, body.get("revision"))


# ---------------------------------------------------------------- 审计

def _audit_entries(portal, limit=120):
    entries = rbac.read_audit(limit=limit)
    out = []
    for e in entries:
        out.append({
            "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(e.get("at") or 0))),
            "actor": e.get("actor"),
            "kind": e.get("kind"),
            "note": e.get("note"),
            "generation": e.get("generation"),
            "revision": e.get("revision"),
            "changes": e.get("changes") or [],
        })
    return out


# ---------------------------------------------------------------- 路由

def handle(portal, handler, path, qs):
    actor = _session_user(portal, handler)

    if handler.command in ("GET", "HEAD") and path in _STATIC:
        # 已登录但没权限 -> 403 说明页。
        if actor and portal._fs_policy.explain(actor, "GET", "/__auth/iam/", "").get("code") != 200:
            return _deny_page(handler, actor)
        # 未登录也返回页面本体，不 302：这个地址本身就是全站未登录的登录落点
        # （nginx @auth_login 就 302 到这里），302 的目标还是它自己。
        # 页面里的 app.js 先问 ./api/session，未登录就摆出登录框，
        # 并把 ?err=noperm|expired / ?msg= 的文案显示出来。
        return _page(portal, handler, path)

    if not path.startswith("/iam/api/"):
        return handler._send(404, "not found")

    if not actor:
        return _json(handler, 401, {"error": "登录状态已过期，请重新登录门户"})

    # 唯一的准入判定：admin 资源 + manage 动作
    decision = portal._fs_policy.explain(actor, "GET", "/__auth/iam/", "")
    if decision.get("code") != 200:
        return _json(handler, 403, {
            "error": "你没有「成员与授权」权限",
            "detail": decision,
        })

    endpoint = path[len("/iam/api/"):].strip("/")

    if handler.command in ("GET", "HEAD"):
        return _get(portal, handler, endpoint, qs)

    if handler.command != "POST":
        return _json(handler, 405, {"error": "method not allowed"})

    if not _origin_ok(portal, handler):
        return _json(handler, 403, {"error": "来源站点不合法"})
    token, _ = _csrf_token(portal, handler)
    sent = handler.headers.get(CSRF_HEADER) or ""
    if not token or not sent or token != sent:
        return _json(handler, 403, {"error": "CSRF 校验失败，请刷新页面"})

    body = _read_body(handler)
    if body is None:
        return _json(handler, 400, {"error": "请求体格式不正确"})

    if endpoint == "member/roles":
        code, payload = _api_member_roles(portal, actor, body)
    elif endpoint == "role/save":
        code, payload = _api_role_save(portal, actor, body)
    elif endpoint == "role/delete":
        code, payload = _api_role_delete(portal, actor, body)
    else:
        code, payload = 404, {"error": "unknown endpoint"}
    return _json(handler, code, payload)


def _page(portal, handler, path):
    name, ctype = _STATIC[path]
    token, header = _csrf_token(portal, handler, issue=True)
    headers = list(PAGE_HEADERS)
    if header:
        headers.append(header)
    try:
        with open(os.path.join(WEB_DIR, name), "rb") as fh:
            body = fh.read()
    except OSError:
        return handler._send(500, "控制台资源缺失")
    return handler._send(200, body, ctype, headers=headers)


_DENY_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>无权访问 · FS 访问控制</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f6fa;color:#1b2233;
font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.box{background:#fff;border:1px solid #e3e8f0;border-radius:12px;padding:28px 32px;max-width:520px;
box-shadow:0 8px 24px rgba(16,24,40,.06)}
h1{font-size:17px;margin:0 0 8px}p{color:#556072;margin:0 0 6px}
code{background:#eef1f6;border-radius:4px;padding:1px 6px;font-family:ui-monospace,monospace}
a{color:#2f6feb;text-decoration:none}
@media (prefers-color-scheme:dark){body{background:#0f131b;color:#e7ecf5}.box{background:#161c26;
border-color:#232c3a}p{color:#a4afc1}code{background:#1e2634}}
</style></head><body><div class="box">
<h1>这个账号没有「成员与授权」权限</h1>
<p>当前身份：<code>__USER__</code></p>
<p>访问成员与权限控制台需要在策略里被授予 <code>admin</code> 资源的
<code>manage</code> 动作。请联系管理员分配角色。</p>
<p style="margin-top:14px"><a href="../logout?next=/__auth/access/">换个账号登录</a> ·
<a href="../account/">账号与密码</a></p>
</div></body></html>"""


def _deny_page(handler, actor):
    body = _DENY_HTML.replace("__USER__", html.escape(actor))
    # 这一页带内联样式，所以不放 CSP 的 style-src 'self'；无脚本、无外部资源。
    return handler._send(403, body, "text/html; charset=utf-8", headers=[
        ("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff")])


def _get(portal, handler, endpoint, qs):
    def q(key, default=""):
        values = qs.get(key)
        return values[0] if values else default

    policy = rbac.load_policy()

    if endpoint == "session":
        token, _ = _csrf_token(portal, handler)
        actor = _session_user(portal, handler)
        return _json(handler, 200, {
            "user": actor,
            "admin": rbac.is_admin(policy, actor),
            "csrf": token,
            "meta": _meta(policy),
        })

    if endpoint == "overview":
        actor = _session_user(portal, handler)
        return _json(handler, 200, {
            "meta": _meta(policy),
            "members": _members(portal, policy),
            "policy": _policy_view(policy, actor),
            "catalog": rbac.catalog(),
            "actions": [{"id": a, "label": l} for a, l in rbac.ACTION_LABELS],
            "resources": [{"id": rid, "label": rbac.RESOURCE_LABEL[rid],
                           "section": rbac.RESOURCE_SECTION[rid]} for rid in rbac.RESOURCE_IDS],
            "degraded": portal._fs_policy.status().get("degraded") or "",
        })

    if endpoint == "audit":
        try:
            limit = max(1, min(500, int(q("limit", "120"))))
        except ValueError:
            limit = 120
        return _json(handler, 200, {"entries": _audit_entries(portal, limit)})

    if endpoint == "explain":
        subject = q("subject")
        method = q("method", "GET")
        uri = q("uri", "/")
        group = q("group")
        return _json(handler, 200, {
            "decision": portal._fs_policy.explain(subject, method, uri, group),
            "matrix": rbac.grant_matrix(policy, subject) if subject else {},
        })

    return _json(handler, 404, {"error": "unknown endpoint"})
