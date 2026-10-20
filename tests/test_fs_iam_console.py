#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs-iam 控制台接线测试
=======================

不起 nginx、不起真门户：用一个假的 portal 模块对象 + 假 handler，
把 iam_console.handle() 的完整链路跑通（登录态 → 授权 → CSRF → 落盘 → 审计）。

这样能在部署前就抓到「路由接错 / 少了 CSRF 校验 / 权限判断写反」这类
一上线就把人锁在门外的错误。
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_DIR = os.path.join(ROOT, "opt", "fs-access-policy")
sys.path.insert(0, POLICY_DIR)

import rbac  # noqa: E402
import access_policy  # noqa: E402
import iam_console  # noqa: E402

ADMIN = "chenchao"
VIEWER = "mmoexp"


class FakeHandler(object):
    def __init__(self, method="GET", cookie_user=None, headers=None, body=b"", csrf=None):
        self.command = method
        self.headers = dict(headers or {})
        if cookie_user:
            self.headers["Cookie"] = "MMOEXP_AUTH=%s" % cookie_user
        if csrf:
            self.headers["Cookie"] = (self.headers.get("Cookie", "") + "; FS_IAM_CSRF=" + csrf) \
                if self.headers.get("Cookie") else "FS_IAM_CSRF=" + csrf
            self.headers["X-CSRF-Token"] = csrf
            self.headers.setdefault("Origin", "https://47.85.224.112")
        self.headers["Content-Length"] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.response = None

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        self.response = {
            "code": code,
            "body": body.decode("utf-8") if isinstance(body, bytes) else body,
            "ctype": ctype,
            "headers": dict(headers or []),
        }
        return self.response

    def _redirect(self, location, extra_headers=None):
        self.response = {"code": 302, "body": "", "ctype": "", "headers": {"Location": location}}
        return self.response

    @property
    def json(self):
        return json.loads(self.response["body"])


def fake_portal(policy_path, audit_path):
    """最小可用的门户替身：只提供 iam_console 真正会用到的那几个接口。"""
    module = types.SimpleNamespace()
    module.CFG = {
        "cookie": "MMOEXP_AUTH",
        "secure": True,
        "prefix": "/__auth",
        "data_dir": os.path.join(os.path.dirname(policy_path), "data"),
    }
    os.makedirs(module.CFG["data_dir"], exist_ok=True)
    module.GROUPS = {"dashboard": "/etc/nginx/.htpasswd-dashboard"}
    module.parse_cookies = lambda header: dict(
        (k.strip(), v.strip()) for k, v in
        (part.split("=", 1) for part in header.split(";") if "=" in part))
    module.read_token = lambda token: {"u": token} if token else None
    module.load_htpasswd = lambda path: {"chenchao": "x", "wulv": "x", "mmoexp": "x"}
    module.log = lambda msg, kind="info": None
    module._registration_bridge = None
    module._fs_policy = access_policy
    return module


# ---------------------------------------------------------------- 改密码替身
#
# iam_console._password_core() 是「借 account_management 模块顶部的
# `import auth_candidate as core`」来拿 password_hash 的，所以它按
# type(accounts).__module__ 去找模块。下面这几个名字就是让本测试模块
# 冒充那个模块：core 提供 password_hash，SCHEMA 用真实建表语句
# （逐条 complete_statement 拆分的正确性也要靠它验证）。
core = types.SimpleNamespace(
    password_hash=lambda pw: "pbkdf2-test$" + pw if len(pw) >= 12 else None)

SCHEMA = '''
CREATE TABLE account_state(subject TEXT PRIMARY KEY,version INTEGER NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),password TEXT NOT NULL,
 modules TEXT NOT NULL,custom INTEGER NOT NULL CHECK(custom IN (0,1)));
CREATE TABLE account_events(id INTEGER PRIMARY KEY,at INTEGER NOT NULL,
 actor TEXT NOT NULL,action TEXT NOT NULL,subject TEXT NOT NULL,
 version INTEGER NOT NULL,reason TEXT NOT NULL);
CREATE TRIGGER account_events_no_update BEFORE UPDATE ON account_events
 BEGIN SELECT RAISE(ABORT,'append-only account audit'); END;
CREATE TRIGGER account_events_no_delete BEFORE DELETE ON account_events
 BEGIN SELECT RAISE(ABORT,'append-only account audit'); END;
'''


class FakeAccounts(object):
    """只实现 iam_console 用到的那两个方法：inventory / has_schema。"""

    def __init__(self, rows, has_schema=False):
        self.rows = rows
        self._has = has_schema

    def inventory(self, db):
        return self.rows

    def has_schema(self, db):
        return self._has


class FakeStore(object):
    def __init__(self, db, accounts):
        self.db = db
        self.accounts = accounts
        self.committed = 0
        self.rolled_back = 0

    def now(self):
        return 1700000000

    @contextmanager
    def transaction(self):
        try:
            yield self.db
            self.db.commit()
            self.committed += 1
        except BaseException:
            self.db.rollback()
            self.rolled_back += 1
            raise


def _memory_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE users(id TEXT PRIMARY KEY,name TEXT,state TEXT,"
        "epoch INTEGER NOT NULL DEFAULT 0,password TEXT);"
        "CREATE TABLE sessions(id INTEGER PRIMARY KEY,user_id TEXT,legacy_user TEXT);")
    return db


def _member(subject, name, enabled=True, custom=False, version=0):
    return {
        "subject": subject, "name": name, "enabled": enabled,
        "modules": {"d4": "read"}, "custom": custom, "version": version,
        "_password": "", "state": "native",
    }


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fsiam-")
        self.policy_path = os.path.join(self.tmp, "fs-iam", "policy.json")
        self.audit_path = os.path.join(self.tmp, "fs-iam", "audit.jsonl")
        self._old = (rbac.LIVE_POLICY, rbac.AUDIT_LOG)
        rbac.LIVE_POLICY = self.policy_path
        rbac.AUDIT_LOG = self.audit_path
        os.makedirs(os.path.dirname(self.policy_path), exist_ok=True)
        with open(self.policy_path, "w", encoding="utf-8") as fh:
            json.dump(rbac.default_policy(), fh, ensure_ascii=False, indent=2)
        access_policy._refresh(force=True)
        self.portal = fake_portal(self.policy_path, self.audit_path)

    def tearDown(self):
        rbac.LIVE_POLICY, rbac.AUDIT_LOG = self._old
        access_policy._refresh(force=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, handler, path, qs=None):
        return iam_console.handle(self.portal, handler, path, qs or {})

    # ---- 认证与准入 ----
    def test_page_serves_to_anonymous(self):
        """未登录也必须 200 返回页面本体，绝不 302。

        这个地址（/__auth/access/）本身就是全站未登录的登录落点 —— nginx 的
        @auth_login 就是 302 到这里。如果这里再 302，浏览器会无限重定向，
        谁都登不进来。所以登录框必须由页面自己出。
        """
        h = FakeHandler("GET")
        self.call(h, "/iam/")
        self.assertEqual(200, h.response["code"])
        self.assertNotIn("Location", h.response["headers"])
        self.assertIn('id="login-view"', h.response["body"])
        self.assertIn('action="../login"', h.response["body"])

    def test_anonymous_gets_csrf_cookie(self):
        """未登录也要签发 CSRF 双提交 Cookie，否则登录后第一次写操作必然 403。"""
        h = FakeHandler("GET")
        self.call(h, "/iam/")
        self.assertIn("Set-Cookie", h.response["headers"])

    def test_anonymous_session_is_200_without_user(self):
        """页面启动第一件事就是问 session。

        这条用 401 会在浏览器控制台留一条红字，看起来像页面坏了；改成
        200 + user:"" 更干净，前端判断 !user 就摆登录框。其余端点仍是 401。
        """
        h = FakeHandler("GET")
        self.call(h, "/iam/api/session")
        self.assertEqual(200, h.response["code"])
        body = json.loads(h.response["body"])
        self.assertEqual("", body["user"])
        self.assertIs(False, body["admin"])
        # 其他端点不跟随：未登录就该是 401
        h2 = FakeHandler("GET")
        self.call(h2, "/iam/api/overview")
        self.assertEqual(401, h2.response["code"])

    def test_page_serves_to_admin(self):
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/")
        self.assertEqual(200, h.response["code"])
        self.assertIn('id="app-view"', h.response["body"])
        # 整页渲染，不再允许被任何页面嵌入（之前的 iframe 方案已废弃）
        self.assertEqual("DENY", h.response["headers"]["X-Frame-Options"])
        self.assertIn("frame-ancestors 'none'", h.response["headers"]["Content-Security-Policy"])

    def test_page_shares_platform_nav_and_back_link(self):
        """页头与导航必须和平台其他页面一致，而不是自成一套门面。

        左侧那条全站导航的唯一真源是 /var/www/hub/hubnav.js（nginx 给所有页面
        sub_filter 注入的那份）。本页不再自建竖侧栏，改成「平台通用页头 + 横向
        视图页签」，页头右侧给一个回平台的入口。导航脚本只在确认「已登录 + 是
        管理员」之后由 app.js 挂载 —— 这个 URL 同时是全站登录落点，不能给匿名
        访问者摆出整条导航。
        """
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/")
        body = h.response["body"]
        self.assertIn('class="platform-header"', body)
        self.assertIn('id="back-platform"', body)
        self.assertIn('href="/dashboard/"', body)
        self.assertNotIn('class="topbar"', body)

        js = FakeHandler("GET", cookie_user=ADMIN)
        self.call(js, "/iam/app.js")
        self.assertIn("/__hub/hubnav.js", js.response["body"])

    def test_csp_opens_inline_style_for_hubnav(self):
        """hubnav 是把导航样式以 <style> 内联注入的，CSP 必须放开内联样式。

        但只放开 style-src 和 speculation-rules：script-src 里绝不能出现
        'unsafe-inline'，否则等于把内联 <script> 也放进来。
        """
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/")
        csp = h.response["headers"]["Content-Security-Policy"]
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("script-src 'self' 'inline-speculation-rules'", csp)
        script_src = csp.split("script-src", 1)[1].split(";", 1)[0]
        self.assertNotIn("unsafe-inline", script_src)

    def test_anonymous_never_redirected_on_any_static(self):
        """静态资源也必须就地 200。

        页面里是相对路径 ./app.css、./app.js，浏览器会解析到同一个前缀下；
        任何一个 302 都会让样式或脚本加载成一页 HTML，整页白屏/错乱。
        """
        for path in ("/iam", "/iam/", "/iam/app.css", "/iam/app.js"):
            h = FakeHandler("GET")
            self.call(h, path)
            self.assertEqual(200, h.response["code"], path)
            self.assertNotIn("Location", h.response["headers"], path)

    def test_non_admin_gets_deny_page(self):
        """非管理员拿到 403 说明页，而不是控制台骨架（避免看到一堆空表格）。"""
        h = FakeHandler("GET", cookie_user=VIEWER)
        self.call(h, "/iam/")
        self.assertEqual(403, h.response["code"])
        self.assertIn(VIEWER, h.response["body"])

    def test_viewer_cannot_read_api(self):
        h = FakeHandler("GET", cookie_user=VIEWER)
        self.call(h, "/iam/api/overview")
        self.assertEqual(403, h.response["code"])
        self.assertIn("没有", h.response["body"])

    def test_viewer_cannot_write(self):
        h = FakeHandler("POST", cookie_user=VIEWER, csrf="t0k", body=b"{}")
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(403, h.response["code"])

    # ---- 读接口 ----
    def test_overview_shape(self):
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/api/overview")
        self.assertEqual(200, h.response["code"])
        data = h.json
        for key in ("meta", "members", "policy", "catalog", "actions", "resources"):
            self.assertIn(key, data)
        self.assertTrue(any(m["admin"] for m in data["members"]))
        self.assertTrue(any(m["name"] == VIEWER and not m["admin"] for m in data["members"]))

    def test_explain_endpoint(self):
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/api/explain",
                  {"subject": [VIEWER], "method": ["POST"], "uri": ["/d4/api/price"]})
        self.assertEqual(200, h.response["code"])
        decision = h.json["decision"]
        self.assertEqual(403, decision["code"])
        self.assertEqual("d4", decision["resource"])
        self.assertEqual("edit", decision["action"])

    # ---- 写接口 ----
    def test_missing_csrf_rejected(self):
        body = json.dumps({"subject": VIEWER, "roles": ["Analyst"]}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body)
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(403, h.response["code"])
        self.assertIn("CSRF", h.response["body"])

    def test_role_assignment_persists_and_audits(self):
        revision = rbac.revision_of(rbac.load_policy())
        body = json.dumps({"subject": VIEWER, "roles": ["PricingOps"],
                           "revision": revision}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body, csrf="t0k")
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(200, h.response["code"], h.response["body"])

        policy = rbac.load_policy()
        self.assertEqual(["PricingOps"], policy["bindings"][VIEWER]["roles"])
        # 改完立即生效：mmoexp 现在能改价，但仍然不能部署
        self.assertEqual(200, rbac.authorize(policy, VIEWER, "POST", "/d4/api/price"))
        self.assertEqual(403, rbac.authorize(policy, VIEWER, "GET", "/deploy/"))

        entries = rbac.read_audit()
        self.assertTrue(entries)
        self.assertEqual(ADMIN, entries[0]["actor"])
        self.assertTrue(any(c.get("subject") == VIEWER for c in entries[0]["changes"]))

    def test_stale_revision_conflict(self):
        body = json.dumps({"subject": VIEWER, "roles": ["Analyst"],
                           "revision": "deadbeefdeadbeef"}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body, csrf="t0k")
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(409, h.response["code"])

    def test_cannot_demote_self(self):
        revision = rbac.revision_of(rbac.load_policy())
        body = json.dumps({"subject": ADMIN, "roles": ["Viewer"],
                           "revision": revision}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body, csrf="t0k")
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(409, h.response["code"])
        self.assertIn("锁在门外", h.response["body"])
        self.assertEqual(["PlatformAdmin"], rbac.load_policy()["bindings"][ADMIN]["roles"])

    def test_role_save_and_delete(self):
        revision = rbac.revision_of(rbac.load_policy())
        body = json.dumps({
            "name": "Warehouse", "label": "仓库运营", "desc": "只看 d4 与 m crow",
            "rules": [{"resources": ["d4", "mlb"], "actions": ["view", "edit"]}],
            "revision": revision,
        }).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body, csrf="t0k")
        self.call(h, "/iam/api/role/save")
        self.assertEqual(200, h.response["code"], h.response["body"])
        policy = rbac.load_policy()
        self.assertIn("Warehouse", policy["roles"])

        # 有成员在用时不能删
        rbac2 = rbac.load_policy()
        rbac2["bindings"]["whoever"] = {"roles": ["Warehouse"]}
        rbac.save_policy(rbac2, ADMIN, note="test")
        revision = rbac.revision_of(rbac.load_policy())
        h = FakeHandler("POST", cookie_user=ADMIN, csrf="t0k",
                        body=json.dumps({"name": "Warehouse", "revision": revision}).encode())
        self.call(h, "/iam/api/role/delete")
        self.assertEqual(409, h.response["code"])

    def test_origin_check(self):
        revision = rbac.revision_of(rbac.load_policy())
        body = json.dumps({"subject": VIEWER, "roles": ["Analyst"],
                           "revision": revision}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body, csrf="t0k",
                        headers={"Origin": "https://evil.example.com"})
        self.call(h, "/iam/api/member/roles")
        self.assertEqual(403, h.response["code"])
        self.assertIn("来源", h.response["body"])

    def test_audit_endpoint(self):
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam/api/audit", {"limit": ["10"]})
        self.assertEqual(200, h.response["code"])
        self.assertIn("entries", h.json)

    def test_cli_grant_accepts_comma_list(self):
        """--roles 是「逗号分隔的字符串」，不是字符列表（踩过：按字符拆成了 O,P,c…）。"""
        import admin_cli
        rc = admin_cli.main(["grant", "--user", VIEWER,
                             "--roles", "PricingOps,Analyst", "--by", ADMIN])
        self.assertEqual(0, rc)
        policy = rbac.load_policy()
        # grant 是「追加」，原有 Viewer 保留，权限取并集
        self.assertEqual(["Analyst", "PricingOps", "Viewer"], policy["bindings"][VIEWER]["roles"])
        self.assertEqual(200, rbac.authorize(policy, VIEWER, "POST", "/d4/api/price"))

    def test_cli_rejects_unknown_role(self):
        import admin_cli
        self.assertEqual(1, admin_cli.main(["grant", "--user", VIEWER,
                                            "--roles", "NoSuchRole", "--by", ADMIN]))
        self.assertEqual(["Viewer"], rbac.load_policy()["bindings"][VIEWER]["roles"])

    # ---- 改密码 ----
    def attach_store(self, rows, has_schema=False):
        """把假注册库挂到 portal 上；返回 (store, db) 供断言。"""
        db = _memory_db()
        store = FakeStore(db, FakeAccounts(rows, has_schema=has_schema))
        self.portal._registration_bridge = types.SimpleNamespace(
            adapter=types.SimpleNamespace(store=store))
        return store, db

    def test_password_requires_super_admin(self):
        """改密码只给管理员，不给「能进控制台但只是成员管理员」的角色。"""
        store, db = self.attach_store({"native:wulv": _member("native:wulv", "wulv")})
        code, body = iam_console._api_password(
            self.portal, VIEWER, {"subject": "native:wulv", "password": "a" * 12})
        self.assertEqual(403, code)
        self.assertIn("管理员", body["error"])
        self.assertFalse(db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='account_state'").fetchone())

    def test_password_rejects_short_secret(self):
        """12 位下限不是产品偏好，是硬约束。

        底层 password_hash / password_matches 都校验 12–128；短于此写进去的
        哈希连自己都验不过，等于当场把账号锁死。
        """
        store, db = self.attach_store({"native:wulv": _member("native:wulv", "wulv")})
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:wulv", "password": "short11char"})
        self.assertEqual(400, code)
        self.assertIn("12", body["error"])
        self.assertFalse(db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='account_state'").fetchone())

    def test_password_rejects_bad_subject(self):
        self.attach_store({})
        for bad in ("", "wulv", "native:", "reg:xyz", "reg:../../etc", "native:a b"):
            code, _ = iam_console._api_password(
                self.portal, ADMIN, {"subject": bad, "password": "d" * 12})
            self.assertEqual(400, code, bad)

    def test_password_unknown_subject(self):
        self.attach_store({})
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:nobody", "password": "d" * 12})
        self.assertEqual(404, code)
        self.assertIn("找不到", body["error"])

    def test_password_writes_authoritative_store(self):
        """密码的权威存储是 account_state.password，不是 htpasswd。

        登录时 Accounts.authenticate() 是「有覆盖值就用覆盖值，没有才回落
        htpasswd」—— 所以只改 htpasswd 等于没改。
        """
        store, db = self.attach_store({"native:wulv": _member("native:wulv", "wulv")})
        db.execute("INSERT INTO sessions(user_id, legacy_user) VALUES(NULL,'wulv')")
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:wulv", "password": "a" * 12})
        self.assertEqual(200, code, body)

        row = db.execute("SELECT password,version,enabled,custom FROM account_state").fetchone()
        self.assertTrue(row["password"].startswith("pbkdf2-test$"))
        self.assertEqual(1, row["version"])
        self.assertEqual(1, row["enabled"])
        self.assertEqual(0, row["custom"])
        # 旧会话必须被踢掉，否则改完密码旧会话还能继续用
        self.assertEqual(0, db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        ev = db.execute("SELECT actor,action,subject FROM account_events").fetchall()
        self.assertEqual(1, len(ev))
        self.assertEqual(("chenchao", "password", "native:wulv"),
                         (ev[0]["actor"], ev[0]["action"], ev[0]["subject"]))
        self.assertEqual(1, store.committed)
        self.assertEqual(0, store.rolled_back)
        self.assertIs(False, body["selfChanged"])

    def test_password_updates_registered_account(self):
        """reg: 账号要同时改 users.password 并抬 epoch，否则它自己的登录绕开新密码。"""
        uid = "11111111-1111-1111-1111-111111111111"
        subject = "reg:" + uid
        store, db = self.attach_store({subject: _member(subject, "bob")})
        db.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, "bob", "readonly", 3, "old-hash"))
        db.execute("INSERT INTO sessions(user_id) VALUES(?)", (uid,))
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": subject, "password": "b" * 16})
        self.assertEqual(200, code, body)
        row = db.execute("SELECT password,epoch FROM users WHERE id=?", (uid,)).fetchone()
        self.assertTrue(row["password"].startswith("pbkdf2-test$"))
        self.assertEqual(4, row["epoch"])
        self.assertEqual(0, db.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,)).fetchone()[0])

    def test_password_self_change_is_flagged(self):
        """改自己的密码会撤销自己的会话，前端据此提示「你会被登出」。"""
        store, db = self.attach_store(
            {"native:chenchao": _member("native:chenchao", "chenchao")})
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:chenchao", "password": "c" * 12})
        self.assertEqual(200, code, body)
        self.assertIs(True, body["selfChanged"])

    def test_password_reuses_existing_schema(self):
        """account_state 已存在时不能再建一次（会报 table already exists）。"""
        store, db = self.attach_store(
            {"native:wulv": _member("native:wulv", "wulv")}, has_schema=True)
        db.executescript(SCHEMA)
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:wulv", "password": "f" * 12})
        self.assertEqual(200, code, body)
        self.assertEqual(1, db.execute("SELECT COUNT(*) FROM account_state").fetchone()[0])

    def test_password_needs_csrf(self):
        self.attach_store({"native:wulv": _member("native:wulv", "wulv")})
        body = json.dumps({"subject": "native:wulv", "password": "e" * 12}).encode()
        h = FakeHandler("POST", cookie_user=ADMIN, body=body)
        self.call(h, "/iam/api/member/password")
        self.assertEqual(403, h.response["code"])
        self.assertIn("CSRF", h.response["body"])

    def test_password_denied_to_viewer_over_http(self):
        """走完整 handle 链路时，非管理员在「成员与授权」门槛就被挡住。"""
        self.attach_store({"native:wulv": _member("native:wulv", "wulv")})
        body = json.dumps({"subject": "native:wulv", "password": "e" * 12}).encode()
        h = FakeHandler("POST", cookie_user=VIEWER, body=body, csrf="t0k")
        self.call(h, "/iam/api/member/password")
        self.assertEqual(403, h.response["code"])

    def test_password_survives_when_store_missing(self):
        """注册库不可用时应报 503，不能抛栈把控制台整页打挂。"""
        self.portal._registration_bridge = None
        code, body = iam_console._api_password(
            self.portal, ADMIN, {"subject": "native:wulv", "password": "g" * 12})
        self.assertEqual(503, code)
        self.assertIn("不可用", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
