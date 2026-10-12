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
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent                      # 共享资源/MLB新卡上架/

sys.path.insert(0, str(TOOL / "server"))
import mlb_writeback as WB              # noqa: E402


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


class WritebackGate(unittest.TestCase):
    """自动上架的三道闸门与结论判定 —— 判错就是「误写线上」或「该报的没报」。

    闸门设计原则：**任何一项不确定，都往「不写」的方向倒**。
    """

    def _wb(self, **kw):
        base = {"enabled": True, "dry_run": False, "python": sys.executable,
                "script": __file__, "cred": __file__, "archive_dir": "/tmp/a",
                "confirm": WB.DEFAULT_CONFIRM, "timeout": 60}
        base.update(kw)
        return base

    def test_missing_task_flag_blocks(self):
        ok, why = WB.gate({}, self._wb())
        self.assertFalse(ok)
        self.assertIn("勾选", why)

    def test_service_switch_blocks(self):
        ok, why = WB.gate({"write_back": True}, self._wb(enabled=False))
        self.assertFalse(ok)
        self.assertIn("enabled", why)

    def test_missing_script_or_cred_blocks(self):
        ok, why = WB.gate({"write_back": True}, self._wb(script="/nope/x.py"))
        self.assertFalse(ok)
        self.assertIn("写卡脚本", why)
        ok, why = WB.gate({"write_back": True}, self._wb(cred="/nope/c.json"))
        self.assertFalse(ok)
        self.assertIn("凭据", why)

    def test_all_gates_pass(self):
        ok, why = WB.gate({"write_back": True}, self._wb())
        self.assertTrue(ok, why)

    def test_cfg_defaults_are_fail_safe(self):
        """配置缺失时必须**关**、且是 dry_run —— 宁可不上架也不能误写。"""
        wb = WB.cfg({})
        self.assertFalse(wb["enabled"])
        self.assertTrue(wb["dry_run"])
        self.assertEqual(WB.cfg(None)["enabled"], False)

    def test_build_cmd_dry_run_has_no_apply(self):
        cmd = WB.build_cmd(self._wb(dry_run=True), "r.json", "o.json")
        self.assertIn("--dry-run", cmd)
        self.assertNotIn("--apply", cmd)
        self.assertNotIn("--confirm", cmd)

    def test_build_cmd_live_has_apply_and_confirm(self):
        cmd = WB.build_cmd(self._wb(dry_run=False), "r.json", "o.json")
        self.assertIn("--apply", cmd)
        self.assertEqual(cmd[cmd.index("--confirm") + 1], WB.DEFAULT_CONFIRM)
        self.assertNotIn("--dry-run", cmd)

    def test_confirm_matches_writer_gate_literal(self):
        """两边口令必须字面一致，否则生产写入会被写卡脚本自己的闸门拒掉。"""
        self.assertEqual(WB.DEFAULT_CONFIRM, "mlb26-players")

    def test_summarize_unknown_is_needs_review(self):
        """`*-unknown(no-retry)` 是「不许重试」的信号，必须冒到顶层。"""
        for v in ("add-unknown(no-retry)", "edit-unknown(no-retry)",
                  "shelves-unknown(no-retry)"):
            s = WB.summarize([{"verdict": v}])
            self.assertEqual(s["status"], "needs_review", v)
            self.assertEqual(s["counts"]["review"], 1)

    def test_summarize_ok_and_skipped(self):
        s = WB.summarize([{"verdict": "ok"}, {"verdict": "skipped"}])
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["counts"], {"ok": 1, "skipped": 1, "dry": 0, "review": 0})

    def test_summarize_dry_run(self):
        s = WB.summarize([{"verdict": "dry-run"}])
        self.assertEqual(s["status"], "dry_run")

    def test_summarize_tolerates_garbage(self):
        self.assertEqual(WB.summarize(None)["cards"], 0)
        self.assertEqual(WB.summarize([None, {}, {"verdict": None}])["status"],
                         "needs_review")

    def test_run_once_never_raises_and_reports_failure(self):
        """脚本不存在时也必须返回结构化结果，不能把异常抛给 hub 线程。"""
        with tempfile.TemporaryDirectory() as td:
            res = WB.run_once(tid="t1", cards=[{"product_name": "X"}],
                              wb=self._wb(script="/definitely/not/here.py"),
                              workdir=td, log=lambda *a: None)
            self.assertIn(res["status"], ("failed", "timeout"))
            self.assertTrue(res.get("error") or res.get("log_tail") is not None)

    def test_run_once_parses_report_and_summarizes(self):
        """锁住 report→status 的映射。

        ⚠️ 这里**不能真的起子进程**：pr_fast 的隔离运行会把 `subprocess.Popen`
        直接换成抛断言的桩（`offline_test_external_process`），真跑必红。
        所以注入一个假的 `run`，只验证「命令怎么拼、报告怎么读、状态怎么定」。
        """
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            seen = {}

            def fake_run(cmd, **kw):
                seen["cmd"] = cmd
                out = cmd[cmd.index("--out") + 1]
                with open(out, "w", encoding="utf-8") as f:
                    json.dump([{"verdict": "ok", "mid": 1}], f)
                return subprocess.CompletedProcess(cmd, 0, stdout=b"done\n")

            with mock.patch.object(WB.subprocess, "run", fake_run):
                res = WB.run_once(tid="t2", cards=[{"product_name": "X"}],
                                  wb=self._wb(script="/opt/x/mlb_write_cards.py",
                                              dry_run=True),
                                  workdir=td, log=lambda *a: None)

            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["returncode"], 0)
            self.assertEqual(res["report"], [{"verdict": "ok", "mid": 1}])
            self.assertEqual(res["cards_in"], 1)
            # 结果 JSON 必须真的落盘给脚本读（CLI 契约就是文件，不是 stdin）
            self.assertTrue(os.path.isfile(os.path.join(td, "t2.result.json")))
            # 只读模式不得带 --apply
            self.assertIn("--dry-run", seen["cmd"])

    def test_start_skips_without_spawning_thread(self):
        """闸门没过时不得起线程 —— 否则只是把「不该跑」藏进后台。"""
        seen = []
        out = WB.start(tid="t3", payload={}, cards=[], config={},
                       update=lambda tid, patch: seen.append(patch),
                       workdir="/tmp", log=lambda *a: None)
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(seen, [])


class HubWritebackWiring(unittest.TestCase):
    """hub 侧接线：采集结果落地后自动触发上架，且不引入 schema 迁移。"""

    def test_result_branch_triggers_writeback(self):
        text = _text("server/mlb_server.py")
        i = text.find('path.endswith("/result")')
        self.assertGreater(i, 0, "找不到 /result 分支")
        seg = text[i:i + 3000]
        self.assertIn("WB.start(", seg)
        self.assertIn('if st == "done"', seg)

    def test_task_flag_read_from_request_body(self):
        self.assertIn('"write_back": bool(body.get("write_back"))',
                      _text("server/mlb_server.py"))

    def test_no_schema_migration_for_writeback(self):
        """写入状态塞进 result JSON —— 不 ADD COLUMN（回滚时删列很难）。

        ⚠️ 只查「真的执行了 ALTER TABLE」，不查注释：`writeback_update` 的
        docstring 里正是在解释**为什么不用**它。
        """
        text = _text("server/mlb_server.py")
        self.assertIsNone(re.search(r"""c\.execute\(\s*['"]\s*ALTER\s+TABLE""",
                                    text, re.I),
                          "出现了真的 ALTER TABLE 调用")
        self.assertIn("writeback_update", text)

    def test_boot_sweep_marks_interrupted(self):
        text = _text("server/mlb_server.py")
        self.assertIn("mark_interrupted_writebacks()", text)
        i = text.find("def main(")
        self.assertIn("mark_interrupted_writebacks()", text[i:i + 900],
                      "启动时未做 running 清扫，网页会永远显示「上架中」")

    def test_health_exposes_only_booleans(self):
        text = _text("server/mlb_server.py")
        self.assertIn('"script_ok"', text)
        self.assertIn('"cred_ok"', text)
        i = text.find('path == "/api/health"')
        seg = text[i:i + 900]
        self.assertNotIn('"cred":', seg, "health 把凭据路径回给前端了")
        self.assertNotIn('"script":', seg)

    def test_workdir_is_not_the_download_dir(self):
        """自动上架的中间产物不能混进 files/（那是给人下载的交付物）。"""
        text = _text("server/mlb_server.py")
        self.assertIn('WB_WORKDIR = os.path.join(HERE, "data", "writeback")', text)


class WebWritebackUi(unittest.TestCase):
    """网页侧必须能勾选、能看到上架结果 —— 否则整条链路是黑箱。"""

    def test_form_has_writeback_checkbox(self):
        text = _text("web/index.html")
        self.assertIn('id="writeBack"', text)
        self.assertIn("自动上架", text)

    def test_submit_sends_write_back(self):
        self.assertIn("write_back:", _text("web/index.html"))

    def test_renders_writeback_report(self):
        text = _text("web/index.html")
        for kw in ("renderWriteback", "needs_review", "archive_dir", "mid"):
            self.assertIn(kw, text, "网页缺少 %s" % kw)

    def test_cards_table_has_upload_column(self):
        """加了「上架」列就必须同步 colspan，否则空态那一行会错位。"""
        text = _text("web/index.html")
        self.assertIn("colspan=\"9\"", text)
        self.assertIn("上架", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
