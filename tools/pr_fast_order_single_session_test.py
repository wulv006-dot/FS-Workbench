import subprocess
import tempfile
import unittest
from pathlib import Path

import pr_fast


class OrderSingleSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.repo = Path(temp.name)
        cls.git("init", "-q")
        cls.write("legacy.py", 'path = "/admin/public/dologin.html"\n')
        cls.write("delete.py", 'path = "/new_captcha.html"\nstatus = "safe"\n')
        cls.write("existing_host.py", 'base = "https://order.p2pah.cn"\n')
        cls.write("existing_form.py", 'base = "https://order.p2pah.cn"\n'
                  'fields = {"password": value}\n')
        cls.write("existing_login.py", 'base = "https://order.p2pah.cn"\n'
                  'http.post(url, data={"password": value})\n')
        cls.base = cls.commit("base")

        cls.write("legacy.py", 'path = "/admin/public/dologin.html"\nstatus = "safe"\n')
        cls.write("delete.py", 'status = "safe"\n')
        cls.write("login.py", 'path = "/admin/public/dologin.html"\n')
        cls.write("two_factor.py", 'path = "dogooglelogin.html"\n')
        cls.write("captcha.py", 'path = "/new_captcha.html"\n')
        cls.write("existing_host.py", 'base = "https://order.p2pah.cn"\n'
                  'http.post(url, data={"password": value})\n')
        cls.write("existing_form.py", 'base = "https://order.p2pah.cn"\n'
                  'fields = {"password": value}\nhttp.post(url, data=fields)\n')
        cls.write("existing_login.py", 'base = "https://order.p2pah.cn"\n'
                  'http.post(url, data={"password": value})\n'
                  'http.post(delivery_url, data={"order_id": value})\n')
        cls.write("login.html", '<form method="post" action="https://order.p2pah.cn/login">\n'
                  '<input name="password"></form>\n')
        cls.write("login.cjs", 'const base = "https://order.p2pah.cn";\n'
                  'http.post(url, {captcha: code});\n')
        cls.write("comment.py", 'base = "https://order.p2pah.cn"\n'
                  'metadata = {"password": "unsupported"}\n')
        cls.write("other_host.py", 'http.post("https://example.test", data={"captcha": value})\n')
        cls.write("reader.py", 'base = "https://order.p2pah.cn"\n'
                  'http.post(url, data={"order_id": value})\n')
        for name in ("order_global_session_20261021/service.py",
                     "order_global_session_20261021/test_session.py",
                     "tools/pr_fast_order_single_session_test.py"):
            cls.write(name, 'path = "/admin/public/dologin.html"\n')
        cls.write("example/order_global_session_20261021/service.py", 'path = "/new_captcha.html"\n')
        for name in ("docs/example.md", "docs/planning/example.md",
                     "order_global_session_20261021/test_order_http.py",
                     "order_global_session_20261021/test_real_tables.py",
                     "order_global_session_20261021/fixtures/expired.html"):
            cls.write(name, 'Example path: /admin/public/dologin.html\n')
        cls.write("parse_login.py", 'base = "https://order.p2pah.cn"\n'
                  'response = http.get(base + "?" + urlencode(filters))\n'
                  'is_login = \'name="password"\' in response.text\n')
        cls.write("browser.py", 'page.goto("https://order.p2pah.cn/admin")\n'
                  'page.locator("#password").fill(value)\n'
                  'page.get_by_role("button").click()\n')
        cls.write("requests.py", 'requests.request("POST", "https://order.p2pah.cn/admin",\n'
                  '                 data={"password": value})\n')
        cls.write("curl_form.sh", 'curl -F "password=$value" "https://order.p2pah.cn/admin"\n')
        cls.write("curl_data.sh", 'curl --data "password=$value" "https://order.p2pah.cn/admin"\n')
        cls.head = cls.commit("head")

        cls.git("checkout", "--quiet", "--detach", cls.base)
        cls.write("legacy.py", 'status = "safe"\n')
        cls.base_tip = cls.commit("main removed the legacy login")
        cls.git("checkout", "--quiet", "--detach", cls.base)
        cls.write("legacy.py", 'path = "/admin/public/dologin.html"\nstatus = "safe"\n')
        cls.stale_head = cls.commit("PR added status only")

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Offline QA", "-c", "user.email=qa@example.test",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=cls.repo, text=True, timeout=10).strip()

    @classmethod
    def write(cls, name, source):
        path = cls.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    @classmethod
    def commit(cls, message):
        cls.git("add", ".")
        cls.git("commit", "-qm", message)
        return cls.git("rev-parse", "HEAD")

    def test_rejects_new_order_login_markers_and_form_submit(self):
        for name, line in (
            ("login.py", 1), ("two_factor.py", 1), ("captcha.py", 1),
            ("existing_host.py", 2), ("existing_form.py", 3), ("login.html", 2), ("login.cjs", 2),
            ("example/order_global_session_20261021/service.py", 1),
            ("browser.py", 2), ("requests.py", 2), ("curl_form.sh", 1), ("curl_data.sh", 1),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, "order-single-session.*fs_order_client.*order_http.*AGENTS.md") as error:
                    pr_fast.check_order_single_session(self.repo, self.base, self.head, [name])
                self.assertIn(f"{name}:{line}", str(error.exception))

    def test_ignores_old_deleted_whitelisted_and_nonlogin_lines(self):
        pr_fast.check_order_single_session(self.repo, self.base, self.head, [
            "legacy.py", "delete.py", "comment.py", "other_host.py", "reader.py", "existing_login.py",
            "order_global_session_20261021/service.py",
            "order_global_session_20261021/test_session.py",
            "tools/pr_fast_order_single_session_test.py",
        ])

    def test_ignores_explanatory_markdown_fixtures_and_read_only_html_detection(self):
        for name in (
            "docs/example.md", "docs/planning/example.md",
            "order_global_session_20261021/test_order_http.py",
            "order_global_session_20261021/test_real_tables.py",
            "order_global_session_20261021/fixtures/expired.html", "parse_login.py",
        ):
            with self.subTest(name=name):
                pr_fast.check_order_single_session(self.repo, self.base, self.head, [name])

    def test_old_pr_branch_is_measured_from_its_common_ancestor(self):
        pr_fast.check_order_single_session(self.repo, self.base_tip, self.stale_head, ["legacy.py"])
