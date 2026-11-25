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
        cls.base = cls.commit("base")

        cls.write("legacy.py", 'path = "/admin/public/dologin.html"\nstatus = "safe"\n')
        cls.write("delete.py", 'status = "safe"\n')
        cls.write("login.py", 'path = "/admin/public/dologin.html"\n')
        cls.write("two_factor.py", 'path = "dogooglelogin.html"\n')
        cls.write("captcha.py", 'path = "/new_captcha.html"\n')
        cls.write("existing_host.py", 'base = "https://order.p2pah.cn"\n'
                  'http.post(url, data={"password": value})\n')
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
        cls.head = cls.commit("head")

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Offline QA", "-c", "user.email=qa@example.test",
             "-c", "commit.gpgsign=false", *args], cwd=cls.repo, text=True, timeout=10).strip()

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
            ("existing_host.py", 2), ("example/order_global_session_20261021/service.py", 1),
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, "order-single-session.*fs_order_client.*order_http.*AGENTS.md") as error:
                    pr_fast.check_order_single_session(self.repo, self.base, self.head, [name])
                self.assertIn(f"{name}:{line}", str(error.exception))

    def test_ignores_old_deleted_whitelisted_and_nonlogin_lines(self):
        pr_fast.check_order_single_session(self.repo, self.base, self.head, [
            "legacy.py", "delete.py", "comment.py", "other_host.py", "reader.py",
            "order_global_session_20261021/service.py",
            "order_global_session_20261021/test_session.py",
            "tools/pr_fast_order_single_session_test.py",
        ])
