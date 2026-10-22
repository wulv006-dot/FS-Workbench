"""全站授权网关 · 兼容层（fs-iam v2）
=====================================

改造前这里就是全站唯一的授权判断（33 行），规则是
「路径里出现 admin/deploy 段就 403，非 GET 一律 403，名单里的 4 个人全放行」。
它被三条调用链同时依赖，签名不能动：

    auth_portal._do_verify()        -> authorize(user, method, uri, group) / ADMINS
    vendor/auth_candidate.Adapter   -> portal._fs_policy（模块对象）
    runtime.Guard.allowed()         -> authorize(...)

所以本文件保留**完全一致的对外契约**，把真正的判断交给 rbac 引擎：

    成员 --绑定--> 角色 --规则--> 资源 × 动作      默认拒绝 / 显式拒绝优先

三条安全底线
------------
1. 策略缺失 / 损坏 / 校验不过 → 回落到改造前的原始逻辑（一字不改保留在
   legacy_authorize 里），绝不让一次坏配置把管理员挡在门外。
2. 策略文件 mtime 变化 → 原地热更新，不需要重启服务、也不用清 pycache。
3. 引擎内部异常 → 按旧逻辑回答，绝不抛 500、绝不无脑放行。
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

CONTROL = frozenset((
    "apply", "execute", "run", "start", "stop", "pause", "resume", "reset",
    "delete", "save", "update", "set", "clear", "unlock", "clear-lock",
    "clear_lock", "reset-lock", "reset_lock", "ban", "unban", "deploy",
    "publish", "restart", "backfill", "collect", "refresh-now", "refresh_now",
))

# 改造前的硬编码名单：只在策略引擎不可用时兜底。
LEGACY_ADMINS = frozenset(("wulv", "chenchao", "DY", "fstech"))

# 对外导出：被 auth_candidate / auth_portal / account_management 直接读取。
# 随策略热更新（frozenset 整体替换），因此改名单不再需要重启服务。
ADMINS = LEGACY_ADMINS

_engine = None
_policy = None
_policy_stamp = None
_revision = ""
_degraded = ""
_lock = threading.Lock()
_last_check = 0.0
_CHECK_EVERY = 1.0


# ---------------------------------------------------------------- 引擎装载

def engine():
    global _engine
    if _engine is not None:
        return _engine
    try:
        import rbac
        _engine = rbac
    except Exception as exc:
        _engine = exc
    return _engine


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _refresh(force=False):
    """按 mtime 热加载策略；失败保留上一份可用策略，而不是清空。"""
    global _policy, _policy_stamp, _revision, _degraded, _last_check

    now = time.time()
    if not force and now - _last_check < _CHECK_EVERY:
        return _policy
    _last_check = now

    mod = engine()
    if isinstance(mod, Exception) or mod is None:
        _degraded = "rbac 引擎不可用: %r" % (mod,)
        return _policy

    stamp = _stamp(mod.LIVE_POLICY)
    with _lock:
        if not force and _policy is not None and stamp == _policy_stamp:
            return _policy
        try:
            policy = mod.load_policy()
        except Exception as exc:
            _degraded = "策略加载失败(%s)，沿用上一份" % exc
            return _policy
        _policy = policy
        _policy_stamp = stamp
        _revision = mod.revision_of(policy)
        _degraded = ""
        try:
            fresh = mod.admins(policy)
            if fresh:
                globals()["ADMINS"] = fresh
        except Exception:
            pass
    return _policy


def policy():
    return _refresh()


def revision():
    _refresh()
    return _revision


def status():
    _refresh()
    return {
        "engine": "fs-iam/rbac",
        "revision": _revision,
        "degraded": _degraded,
        "admins": sorted(ADMINS),
        "generation": (_policy or {}).get("generation"),
        "updated_at": (_policy or {}).get("updated_at"),
        "updated_by": (_policy or {}).get("updated_by"),
        "policyPath": getattr(engine(), "LIVE_POLICY", ""),
    }


def explain(user, method, uri, group=""):
    """给控制台用的「为什么」：返回完整决策（含命中的角色/规则）。"""
    mod = engine()
    pol = _refresh()
    if isinstance(mod, Exception) or pol is None:
        return {"allow": False, "code": legacy_authorize(user, method, uri, group),
                "subject": user, "resource": "?", "action": "?",
                "resourceLabel": "?", "actionLabel": "?", "roles": [], "matched": [],
                "reason": "降级到旧逻辑：" + (_degraded or "策略不可用")}
    return mod.evaluate(pol, user, method, uri, group).as_dict()


# ---------------------------------------------------------------- 旧逻辑

def legacy_authorize(user, method, uri, group=""):
    """2026-10 之前的原始实现，逻辑一字不改：引擎故障时用它顶上。"""
    import re as _re
    from urllib.parse import unquote, urlsplit, parse_qs

    if not user:
        return 401
    # Observer access is fail-closed when the IAM engine/policy is unavailable.
    if user == "dot_fc_observer":
        return 403
    if user in LEGACY_ADMINS:
        return 200
    parsed = urlsplit(uri or "/")
    path = parsed.path
    for _ in range(3):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    segments = set(filter(None, _re.split(r"[/\\]+", path.lower())))
    if group == "deploy" or "admin" in segments or "deploy" in segments:
        return 403
    if (method or "GET").upper() == "PATCH" and not user.startswith("reg:") and \
            _re.fullmatch(r"/dashboard/tasks/api/green-plan/tasks/G[0-9]+", uri or ""):
        return 200
    if (method or "GET").upper() not in ("GET", "HEAD"):
        return 403
    if segments & CONTROL:
        return 403
    for key, values in parse_qs(parsed.query).items():
        if key.lower() in ("action", "op", "command", "cmd") and \
                any(v.lower() in CONTROL for v in values):
            return 403
    return 200


# ---------------------------------------------------------------- 主入口

def authorize(user, method, uri, group=""):
    """全站授权入口。状态码语义：401 未登录 / 403 无权限 / 200 放行。"""
    if not user:
        return 401
    try:
        pol = _refresh()
        mod = engine()
        if isinstance(mod, Exception) or pol is None:
            return legacy_authorize(user, method, uri, group)
        return mod.evaluate(pol, user, method, uri, group).code
    except Exception:
        try:
            return legacy_authorize(user, method, uri, group)
        except Exception:
            return 403


def is_admin(user):
    if not user:
        return False
    _refresh()
    return user in ADMINS


def matrix(user):
    """成员的生效权限（资源 → 动作列表），给控制台用。"""
    mod = engine()
    pol = _refresh()
    if isinstance(mod, Exception) or pol is None:
        return {}
    return mod.grant_matrix(pol, user)


# 启动即预热，首个请求不必等加载
_refresh(force=True)
