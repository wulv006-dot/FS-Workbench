#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fs-iam 授权引擎测试
=====================

两条主线：

1. **等价性**：新引擎对「改造前就存在的 5 个账号」必须给出与旧 access_policy
   完全一致的状态码。这是上线的唯一硬条件 —— 换引擎不能顺带改了谁的权限。
2. **模型正确性**：默认拒绝、显式拒绝优先、通配符、资源解析、超级角色保护。

运行：python -m unittest discover -s tests -k fs_iam  或直接 python tests/test_fs_iam_rbac.py
"""
import ast
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_DIR = os.path.join(ROOT, "opt", "fs-access-policy")
sys.path.insert(0, POLICY_DIR)

import rbac  # noqa: E402
import access_policy  # noqa: E402

# 改造前真实存在的账号（htpasswd-dashboard / htpasswd-deploy 并集）
LEGACY_ADMINS = ("wulv", "chenchao", "DY", "fstech")
LEGACY_READONLY = ("mmoexp",)
UNBOUND = ("somebody-new", "reg:0f4a6f5e-1111-2222-3333-444455556666")

URIS = (
    "/dashboard/",
    "/dashboard/analytics/",
    "/dashboard/tasks/",
    "/dashboard/tasks/green-plan/",
    "/dashboard/tasks/api/tasks/12",
    "/dashboard/api/summary",
    "/dashboard/fc27-coins.html",
    "/dashboard/madden27-coins.html",
    "/d4/",
    "/d4/api/price",
    "/d4/api/collect",
    "/g2g/api/apply",
    "/sales/",
    "/nba2k27/",
    "/mlb/",
    "/bots/",
    "/tools/fc27-players/",
    "/s/",
    "/s/wulv/fc27-ops/",
    "/s/wulv/fc27-ops/api/collect",
    "/docs/",
    "/deploy/",
    "/deploy/api/run",
    "/admin/users",
    "/d4/admin/panel",
    "/dashboard/?action=delete",
    "/d4/?op=refresh_now",
    "/__auth/access/",
    "/__auth/iam/",
    "/verify",
    "/",
    "/favicon.ico",
)
METHODS = ("GET", "HEAD", "POST", "PATCH", "DELETE")
GROUPS = ("", "deploy")


class EquivalenceTest(unittest.TestCase):
    """新引擎 vs 旧实现的逐格对照。"""

    def setUp(self):
        self.policy = rbac.default_policy()
        rbac.validate(self.policy)
        self.tmp = tempfile.TemporaryDirectory(prefix="fs-iam-equivalence-")
        self.previous_path = rbac.LIVE_POLICY
        rbac.LIVE_POLICY = os.path.join(self.tmp.name, "policy.json")
        with open(rbac.LIVE_POLICY, "w", encoding="utf-8") as fh:
            json.dump(self.policy, fh)
        access_policy._refresh(force=True)

    def tearDown(self):
        rbac.LIVE_POLICY = self.previous_path
        access_policy._refresh(force=True)
        self.tmp.cleanup()

    def test_matrix_equals_legacy(self):
        mismatches = []
        for user in LEGACY_ADMINS + LEGACY_READONLY + UNBOUND:
            for uri in URIS:
                # /__auth/iam/ 是本次新增的控制台，改造前根本不存在，
                # 没有「等价」可言 —— 它的准入由 test_console_requires_manage 单独守。
                if uri.startswith("/__auth/iam"):
                    continue
                for method in METHODS:
                    for group in GROUPS:
                        if group and not uri.startswith("/deploy"):
                            continue
                        old = access_policy.legacy_authorize(user, method, uri, group)
                        # Registered accounts previously had a second route whitelist.
                        # Keep its unknown/sensitive denial after unifying the grant source.
                        if user.startswith("reg:") and rbac.resolve_resource(uri) in (rbac.UNMAPPED, "sensitive"):
                            old = 403
                        new = rbac.authorize(self.policy, user, method, uri, group)
                        if old != new:
                            mismatches.append((user, method, uri, group, old, new))
        self.assertEqual([], mismatches,
                         "新引擎与旧策略判定不一致，共 %d 处" % len(mismatches))

    def test_shim_matches_engine(self):
        """兼容层（线上实际被调用的是它）也要和引擎一致。"""
        for user in LEGACY_ADMINS + LEGACY_READONLY + UNBOUND:
            for uri in URIS:
                self.assertEqual(
                    rbac.authorize(self.policy, user, "GET", uri),
                    access_policy.authorize(user, "GET", uri),
                    "%s %s" % (user, uri))

    def test_admin_list_unchanged(self):
        self.assertEqual(frozenset(LEGACY_ADMINS), access_policy.ADMINS)


class ModelTest(unittest.TestCase):
    def setUp(self):
        self.policy = rbac.default_policy()

    def test_resource_resolution(self):
        cases = {
            "/dashboard/tasks/api/green-plan/tasks/G1": "green_plan",
            "/dashboard/tasks/": "tasks",
            "/dashboard/fc27-coins.html": "coins",
            "/s/wulv/fc27-ops/": "ops",
            "/s/wulv/fc27-ops/api/collect": "unmapped",   # 敏感路径
            "/d4/": "d4",
            "/d4something/": "unmapped",
            "/__auth/iam/": "admin",
            "/__auth/login": "identity",
            "/": "identity",
            "/whatever/else": "unmapped",
        }
        for uri, want in cases.items():
            self.assertEqual(want, rbac.resolve_resource(uri), uri)

    def test_encoding_escape_is_normalised(self):
        # 二次编码 / 反斜杠都不能绕过资源识别
        self.assertEqual("d4", rbac.resolve_resource("/d%34/api/price"))
        self.assertEqual("admin", rbac.resolve_resource("/__auth/%69am/"))
        self.assertEqual("admin", rbac.resolve_resource("/__auth\\iam/"))

    def test_actions(self):
        self.assertEqual(("d4", "view"), rbac.requirement("GET", "/d4/api/list"))
        self.assertEqual(("d4", "edit"), rbac.requirement("POST", "/d4/api/price"))
        self.assertEqual(("d4", "execute"), rbac.requirement("POST", "/d4/api/collect"))
        self.assertEqual(("d4", "execute"), rbac.requirement("GET", "/d4/?action=delete"))
        self.assertEqual(("d4", "deploy"), rbac.requirement("GET", "/d4/", "deploy"))
        self.assertEqual(("admin", "manage"), rbac.requirement("GET", "/__auth/iam/"))

    def test_deny_by_default(self):
        policy = rbac.default_policy()
        policy["bindings"]["lh"] = {"roles": ["Analyst"]}
        self.assertEqual(403, rbac.authorize(policy, "lh", "POST", "/d4/api/price"))
        self.assertEqual(200, rbac.authorize(policy, "lh", "GET", "/dashboard/analytics/"))
        self.assertEqual(403, rbac.authorize(policy, "lh", "GET", "/nba2k27/"))

    def test_explicit_deny_wins(self):
        policy = rbac.default_policy()
        policy["bindings"]["zhang"] = {"roles": ["PricingOps"],
                                       "deny": [{"resources": ["d4"], "actions": ["edit"]}]}
        self.assertEqual(403, rbac.authorize(policy, "zhang", "POST", "/d4/api/price"))
        self.assertEqual(200, rbac.authorize(policy, "zhang", "POST", "/nba2k27/api/price"))

    def test_multiple_roles_union(self):
        policy = rbac.default_policy()
        policy["bindings"]["wang"] = {"roles": ["Analyst", "CollabEditor"]}
        self.assertEqual(200, rbac.authorize(policy, "wang", "GET", "/dashboard/game-monitor/"))
        self.assertEqual(200, rbac.authorize(policy, "wang", "POST", "/dashboard/tasks/api/tasks/9"))
        self.assertEqual(403, rbac.authorize(policy, "wang", "POST", "/d4/api/price"))

    def test_identity_never_lockable(self):
        """哪怕角色一条规则都没有，也必须能访问门户自身（否则登不出去也进不来）。"""
        policy = rbac.default_policy()
        policy["roles"]["Blank"] = {"label": "空角色", "rules": [
            {"resources": ["docs"], "actions": ["view"]}]}
        policy["bindings"]["nobody"] = {"roles": ["Blank"]}
        for uri in ("/", "/__auth/access/", "/__auth/login", "/__auth/logout", "/verify"):
            self.assertEqual(200, rbac.authorize(policy, "nobody", "GET", uri), uri)
        self.assertEqual(403, rbac.authorize(policy, "nobody", "GET", "/d4/"))

    def test_last_admin_protected(self):
        policy = rbac.default_policy()
        for admin in LEGACY_ADMINS[1:]:
            policy["bindings"].pop(admin)
        self.assertEqual(frozenset(("wulv",)), rbac.admins(policy))
        policy["bindings"].pop("wulv")
        with self.assertRaises(rbac.PolicyError):
            rbac.validate(policy)

    def test_unbound_role_cannot_be_super(self):
        policy = rbac.default_policy()
        policy["unbound_role"] = rbac.ADMIN_ROLE
        with self.assertRaises(rbac.PolicyError):
            rbac.validate(policy)

    def test_console_requires_manage(self):
        policy = rbac.default_policy()
        self.assertEqual(200, rbac.authorize(policy, "chenchao", "GET", "/__auth/iam/"))
        self.assertEqual(403, rbac.authorize(policy, "mmoexp", "GET", "/__auth/iam/"))
        self.assertEqual(403, rbac.authorize(policy, "mmoexp", "POST", "/__auth/iam/api/member/roles"))

    def test_broken_policy_rejected(self):
        policy = rbac.default_policy()
        policy["roles"]["Broken"] = {"label": "坏", "rules": [
            {"resources": ["d4"], "actions": ["explode"]}]}
        with self.assertRaises(rbac.PolicyError):
            rbac.validate(policy)


class DriftTest(unittest.TestCase):
    """资源表是「URI → 资源」的唯一真源，改名等于改所有历史授权，必须锁死。"""

    EXPECTED = {
        # 业务模块（与注册账号那套 24 个模块 id 对齐）
        "unified-business", "data-analysis-tools", "management", "game-monitor",
        "brain", "coins", "fc27-bundles", "fc27-sbc", "ops", "players", "gallery",
        "odds", "mlb", "nba", "madden", "d4", "g2g", "sales", "bot-console",
        "tasks", "green_plan", "docs", "sites",
        "fc27-evolutions", "marketing", "activities",
        # 平台类
        "home", "identity", "admin", "deploy", "sensitive",
    }

    def test_resource_ids_frozen(self):
        self.assertEqual(self.EXPECTED, set(rbac.RESOURCE_IDS),
                         "资源 id 变动会让历史授权悄悄失效，改这里之前先想清楚")

    def test_every_resource_has_prefix(self):
        for rid, label, section, prefixes in rbac.RESOURCES:
            self.assertTrue(label, rid)
            self.assertIn(section, [s for s, _ in rbac.SECTIONS], rid)
            if rid not in ("sensitive",):
                self.assertTrue(prefixes, "%s 没有任何路径前缀，将永远匹配不到" % rid)

    def test_catalog_covers_all(self):
        seen = set()
        for section in rbac.catalog():
            for res in section["resources"]:
                seen.add(res["id"])
        self.assertEqual(self.EXPECTED, seen)


class SeedTest(unittest.TestCase):
    def test_seed_file_matches_default(self):
        path = os.path.join(POLICY_DIR, "policy.seed.json")
        with open(path, "r", encoding="utf-8") as fh:
            seed = json.load(fh)
        rbac.validate(seed)
        self.assertEqual(sorted(rbac.default_policy()["bindings"]), sorted(seed["bindings"]))
        self.assertEqual(sorted(rbac.default_policy()["roles"]), sorted(seed["roles"]))



class FCObserverTest(unittest.TestCase):
    def setUp(self):
        self.policy = rbac.default_policy()
        self.policy["roles"]["FCObserver"] = {"rules": [
            {"resources": ["coins"], "actions": ["view"]}]}
        self.policy["bindings"]["dot_fc_observer"] = {"roles": ["FCObserver"], "deny": [
            {"resources": ["*"], "actions": ["edit", "execute", "deploy", "manage"]}]}
        rbac.validate(self.policy)
        self.routes = ["/api/fc27/cloud/" + path for path in
                       ("automation", "monitor", "pricing/state",
                        "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")]

    def test_exact_reads_only_and_writes_before_compat(self):
        for uri in self.routes:
            self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", "GET", uri), 200)
            for method in ("HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"):
                self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", method, uri), 403)
        for uri in ("/dashboard/", "/__auth/access/", "/d4/", "/deploy/", "/api/fc27/cloud/health",
                    "/api/fc27/cloud/activity", "/api/fc27/cloud/quotes/a", "/api/fc27/cloud/jobs/invalid",
                    "/dashboard/tasks/api/green-plan/tasks/G123"):
            for method in ("GET", "POST", "PATCH"):
                self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", method, uri), 403)
        for uri in self.routes:
            for suffix in ("/", "?refresh=true", "?action=apply", "?x=1", "#fragment"):
                self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", "GET", uri + suffix), 403)

    def test_missing_binding_denied_without_viewer_fallback(self):
        self.policy["bindings"].pop("dot_fc_observer")
        for uri in self.routes + ["/dashboard/", "/d4/"]:
            self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", "GET", uri), 403)

    def test_explicit_revoke_denies_existing_observer(self):
        self.policy["bindings"]["dot_fc_observer"]["deny"].append(
            {"resources": ["coins"], "actions": ["view"]})
        for uri in self.routes:
            self.assertEqual(rbac.authorize(self.policy, "dot_fc_observer", "GET", uri), 403)

    def test_legacy_failure_mode_denies_observer_only(self):
        for uri in self.routes + ["/dashboard/", "/d4/"]:
            self.assertEqual(access_policy.legacy_authorize("dot_fc_observer", "GET", uri), 403)
        self.assertEqual(access_policy.legacy_authorize("wulv", "GET", "/dashboard/"), 200)
        self.assertEqual(access_policy.legacy_authorize("mmoexp", "GET", "/dashboard/"), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
