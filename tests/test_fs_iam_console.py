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
import sys
import tempfile
import types
import unittest

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
    def test_page_requires_login(self):
        h = FakeHandler("GET")
        self.call(h, "/iam")
        self.assertEqual(302, h.response["code"])
        self.assertIn("/__auth/access/", h.response["headers"]["Location"])

    def test_page_serves_for_admin(self):
        h = FakeHandler("GET", cookie_user=ADMIN)
        self.call(h, "/iam")
        self.assertEqual(200, h.response["code"])
        self.assertIn("访问控制", h.response["body"])
        self.assertIn("Set-Cookie", h.response["headers"])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
