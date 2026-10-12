# -*- coding: utf-8 -*-
"""离线用例：MLB 新卡上架工作台（执行器 + 服务端）纯逻辑回归。

背景
----
本目录是 **2026-10-05「执行器检测不到」故障** 修复后的归档。七个根因里
有五个是"静默失败"（SQLite UPSERT 崩溃、认证换代被漏、bat 是 LF、
BOM+chcp 回归、模板发现不到），事发时表现都跟真实原因毫无关系，
事后极难定位。所以这里把它们固化成回归用例——同样的坑不能再踩第二次。

覆盖范围
--------
纯本地逻辑：不连网、不起服务、不写业务数据、不启动浏览器。

跑法
----
    python -m unittest discover -s 共享资源/MLB新卡上架/tests -p 'test_shelf_tool_offline.py'
"""
from __future__ import annotations

import ast
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent                      # 共享资源/MLB新卡上架/


def _text(rel: str) -> str:
    return (TOOL / rel).read_text(encoding="utf-8")


def _agent_constants(names: set) -> dict:
    """从 `client/mlb_agent.py` 抽出指定常量/函数，绕开 playwright 依赖。"""
    mod = ast.parse(_text("client/mlb_agent.py"))
    picked = []
    for node in mod.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    picked.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            picked.append(node)
    ns: dict = {"Decimal": Decimal}
    exec(compile(ast.Module(body=picked, type_ignores=[]), "subset", "exec"), ns)
    return ns


class BatNormalizerGate(unittest.TestCase):
    """`_normalize_bat.py` 是出包前的强制闸门，行为必须锁死。

    它是 10-05 第二轮修复的产物：把工具从"尽力转换"改成"检出即拒绝"。
    """

    @classmethod
    def setUpClass(cls):
        src = _text("_normalize_bat.py")
        ns: dict = {"__name__": "_normalize_bat_probe"}
        exec(compile(src, "_normalize_bat.py", "exec"), ns)
        # ⚠️ 必须用 staticmethod 包一层：普通函数挂到类属性上会被描述符协议
        # 绑定成方法，调用时自动多传一个 self（TypeError: takes 1 positional
        # argument but 2 were given）。
        cls.norm = staticmethod(ns["normalize"])

    def _normalize(self, raw: bytes) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.bat"
            p.write_bytes(raw)
            self.norm(str(p))
            return p.read_bytes()

    def test_lf_becomes_crlf(self):
        out = self._normalize(b"@echo off\necho hi\n")
        self.assertGreater(out.count(b"\r\n"), 0)
        self.assertEqual(out.count(b"\n") - out.count(b"\r\n"), 0,
                         "仍存在裸 LF —— cmd 会出现标签跳转偏移、整段静默不执行")

    def test_bom_removed(self):
        out = self._normalize(b"\xef\xbb\xbf@echo off\r\n")
        self.assertFalse(out.startswith(b"\xef\xbb\xbf"),
                         "BOM 会让首行变成 锘?echo off，echo off 永不生效 → 全屏回显")

    def test_non_ascii_rejected(self):
        """含中文必须直接 SystemExit，而不是"尽力转换"——这是 10-05 的教训。"""
        with self.assertRaises(SystemExit):
            self._normalize("@echo off\necho 中文\n".encode("utf-8"))

    def test_chcp_rejected(self):
        with self.assertRaises(SystemExit):
            self._normalize(b"chcp 65001\r\n@echo off\r\n")

    def test_forbidden_list_covers_chcp(self):
        self.assertIn("chcp ", _text("_normalize_bat.py"))

    def test_output_is_pure_ascii_7bit(self):
        out = self._normalize(b"@echo off\r\necho hello\r\n")
        self.assertTrue(all(b < 128 for b in out), "输出不是纯 7-bit ASCII")


class AgentContract(unittest.TestCase):
    """执行器常量与定价——列序改了会直接错位导入后台。"""

    @classmethod
    def setUpClass(cls):
        cls.ns = _agent_constants({
            "HEADERS", "FLOOR", "MARKUP", "DEFAULT_INTERVAL",
            "_TEMPLATE_DIRS", "_template_candidates",
        })

    def test_headers_table(self):
        h = self.ns["HEADERS"]
        self.assertEqual(len(h), 16, "后台按列序取值，列数必须 16")
        self.assertEqual(h[3], "产品名称")
        self.assertEqual(h[15], "分类ID（勿改）")

    def test_pricing_constants(self):
        self.assertEqual(self.ns["FLOOR"], Decimal("0.50"))
        self.assertEqual(self.ns["MARKUP"], Decimal("1.1"))
        self.assertEqual(self.ns["DEFAULT_INTERVAL"], 120)

    def test_template_dirs_cover_desktop_and_workdir(self):
        """10-05 根因：只扫工作目录 → 首跑即报「没有可用的 Excel 模板」。
        模板实际落在桌面「产品模型」下，发现范围必须覆盖。"""
        dirs = self.ns["_TEMPLATE_DIRS"]
        joined = "|".join(dirs)
        self.assertIn("MLB新卡上架", joined, "未覆盖默认工作目录")
        self.assertIn("Desktop", joined, "未覆盖桌面")
        self.assertIn("产品模型", joined)

    def test_template_candidates_is_callable_and_offline(self):
        cands = self.ns["_template_candidates"](Path("."))
        self.assertIsInstance(cands, list)


class SQLiteLegacyCompat(unittest.TestCase):
    """线上是 SQLite 3.7.17（CentOS 7 自带，2011 年），3.8+ 语法一律不可用。

    10-05 根因 1：服务器用 `ON CONFLICT ... DO UPDATE`（需 3.24+）→ 心跳每次崩，
    网页上永远显示离线。本机 SQLite 新会掩盖它，所以这里做静态闸门。
    """

    HOSTILE = (
        (r"ON\s+CONFLICT\s+DO\s+UPDATE", "UPSERT，需 3.24+"),
        (r"\bRETURNING\b", "RETURNING，需 3.35+"),
        (r"json_extract\s*\(", "json_extract，需 3.38+"),
        (r"json_each\s*\(", "json_each，需 3.38+"),
        (r"OVER\s*\(\s*PARTITION\s+BY", "窗口函数，需 3.25+"),
        (r"CREATE\s+TABLE[^;]*\bSTRICT\b", "STRICT 表，需 3.37+"),
    )

    #: 允许出现的"注释性提及"——只出现在说明为什么不用它
    ALLOW = ("# ", "; ", '"""', "'''")

    def _assert_clean(self, rel: str):
        text = _text(rel)
        for pat, why in self.HOSTILE:
            for m in re.finditer(pat, text, re.I | re.S):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line = text[line_start:text.find("\n", m.start())]
                if line.lstrip().startswith(("#", ";")) or '"""' in line:
                    continue        # 注释里说明"不要用 X"是允许的
                self.fail("%s 出现不可用的 SQLite 语法（%s）: %s"
                          % (rel, why, line.strip()[:90]))

    def test_server_sql_is_legacy_safe(self):
        self._assert_clean("server/mlb_server.py")

    def test_agent_sql_is_legacy_safe(self):
        self._assert_clean("client/mlb_agent.py")

    def test_heartbeat_uses_two_step_select_then_update_insert(self):
        """心跳必须用 SELECT 判存在 + UPDATE/INSERT 两步（兼容 3.7.17）。"""
        text = _text("server/mlb_server.py")
        i = text.find('path == "/api/heartbeat"')
        self.assertGreater(i, 0, "找不到 heartbeat 分支")
        seg = text[i:i + 2400]
        self.assertIn("SELECT 1 FROM agents WHERE name=?", seg)
        self.assertIn("UPDATE agents SET", seg)
        self.assertIn("INSERT INTO agents", seg)


class AuthIsCookieNotBasic(unittest.TestCase):
    """10-05 根因 2：门户换 auth_request 后 Basic 失效，未登录返回 302 而非 401。
    客户端若老实跟随重定向会拿到 HTML，报出"JSON 解析失败"这种无关错误。"""

    def test_agent_uses_portal_login_endpoint(self):
        text = _text("client/mlb_agent.py")
        self.assertIn("/__auth/login", text)
        self.assertIn("AUTH_LOGIN", text)

    def test_agent_handles_302_as_auth_failure(self):
        text = _text("client/mlb_agent.py")
        self.assertIn("302", text, "未见 302 处理逻辑")

    def test_agent_does_not_follow_redirects(self):
        """必须显式构造"不自动跟随重定向"的 opener，否则会拿到登录页 HTML。"""
        text = _text("client/mlb_agent.py")
        self.assertIn("_opener", text)
        self.assertRegex(text, r"不自动跟随重定向|no_redirect|HTTPRedirectHandler",
                         "未见禁止跟随重定向的机制")

    def test_basic_is_only_a_documented_fallback(self):
        """Basic 只能作为兜底分支存在，且必须带"已失效"说明，不能是主路径。"""
        text = _text("client/mlb_agent.py")
        self.assertIn("_use_basic", text)
        self.assertRegex(text, r"Basic Auth 保留为兜底|退回 Basic Auth",
                         "Basic 分支缺少兜底说明")

    def test_http_is_upgraded_to_https(self):
        """10-12 根因：nginx 对 /__auth/ 强制 308 → https，走 http 的登录
        POST 根本到不了门户，表现为「303/308 被重定向到登录页」。"""
        text = _text("client/mlb_agent.py")
        i = text.find("_normalize_site")
        self.assertGreater(i, 0)
        seg = text[i:i + 1600]
        self.assertIn("https://", seg)
        self.assertRegex(seg, r'startswith\("http://"\)', "未见 http → https 升级")


class ClientPackaging(unittest.TestCase):
    """`_make_agent_zip.py` 10-05 修掉了吞异常——出包失败必须能被看见。"""

    def test_make_zip_does_not_swallow_errors(self):
        text = _text("_make_agent_zip.py")
        self.assertNotIn("2>&1", text,
                         "出包脚本把错误重定向吞掉了，坏字节会照进包")

    def test_web_and_deploy_assets_present(self):
        self.assertTrue((TOOL / "web" / "index.html").is_file())
        self.assertTrue((TOOL / "deploy" / "install_mlb.sh").is_file())
        self.assertTrue((TOOL / "client" / "启动执行器.bat").is_file())

    def test_startup_bat_is_crlf_ascii_no_bom(self):
        """交付给用户的启动器必须已经合规（它是双击入口，坏了就全盘失效）。"""
        raw = (TOOL / "client" / "启动执行器.bat").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "启动器带 BOM")
        self.assertEqual(raw.count(b"\n") - raw.count(b"\r\n"), 0,
                         "启动器存在裸 LF")
        self.assertNotIn(b"chcp", raw.lower(), "启动器含 chcp")

    def test_bat_name_is_non_ascii_but_content_is_ascii(self):
        """文件名可以是中文（chcp 场景二），但内容必须纯 ASCII。"""
        raw = (TOOL / "client" / "启动执行器.bat").read_bytes()
        self.assertTrue(all(b < 128 for b in raw), "bat 内容含非 ASCII")


class RepairReportPreserved(unittest.TestCase):
    """修复报告是本次交付的核心证据，四个根因必须都留在里面。"""

    def test_report_present(self):
        p = TOOL / "故障修复报告_20261005.md"
        self.assertTrue(p.is_file(), "缺少故障修复报告")
        self.assertGreater(len(p.read_text(encoding="utf-8")), 2000)

    def test_report_documents_all_root_causes(self):
        text = _text("故障修复报告_20261005.md")
        for kw, why in (
            ("ON CONFLICT", "根因1 SQLite UPSERT"),
            ("3.7.17", "根因1 线上 SQLite 版本"),
            ("302", "根因2 认证换代"),
            ("CRLF", "根因3 bat 换行"),
            ("BOM", "根因4 BOM+chcp"),
            ("chcp", "根因4 chcp 回归"),
            ("9009", "根因7 py -3 引号"),
        ):
            self.assertIn(kw, text, "报告缺少 %s" % why)

    def test_report_has_rollback_section(self):
        """有变更就必须有回滚——这是交付规范的一部分。"""
        text = _text("故障修复报告_20261005.md")
        self.assertIn("回滚", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
