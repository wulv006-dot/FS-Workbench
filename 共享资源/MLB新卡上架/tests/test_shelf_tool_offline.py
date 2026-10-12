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
import time
import unittest
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent                      # 共享资源/MLB新卡上架/

sys.path.insert(0, str(TOOL / "server"))
import mlb_writeback as WB              # noqa: E402
import mlb_coins_rate as CR             # noqa: E402


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


#: 用于闸门用例的"存在即可"路径（闸门只判 isfile）
_WB_SRC = str(TOOL / "server" / "mlb_writeback.py")


def _wbcfg(**kw):
    """一份"全开"的 writeback 配置，用例按需覆盖单项。"""
    base = {"enabled": True, "dry_run": False, "require_approval": True,
            "python": sys.executable, "script": _WB_SRC, "cred": _WB_SRC,
            "archive_dir": "/tmp/a", "confirm": WB.DEFAULT_CONFIRM, "timeout": 60}
    base.update(kw)
    return base


def _cards():
    return [
        {"name": "Dennis Eckersley", "ovr": "99", "position": "CP",
         "team": "Athletics", "series": "Awards", "hash": "a" * 32,
         "product_name": "Dennis Eckersley/99/CP/Athletics/Awards",
         "sale_price": "1.49", "include": True},
        {"name": "Andy Pettitte", "ovr": "99", "position": "SP",
         "team": "Yankees", "series": "Awards", "hash": "b" * 32,
         "product_name": "Andy Pettitte/99/SP/Yankees/Awards",
         "sale_price": "1.14", "include": True},
    ]


class _FakeHub:
    """把 hub 的 read/update/writeback_update 换成内存版，避免碰数据库。

    ⚠️ `read` 必须真的返回**上一次写入的状态** —— 放行的幂等性就靠它，
       注入一个恒空的 read 会让"二次放行"用例变成假的绿灯。
    """

    def __init__(self):
        self.state = {}
        self.patches = []

    def read(self, tid):
        return dict(self.state)

    def update(self, tid, patch):
        self.patches.append(dict(patch))
        self.state.update(patch)


class ApprovalGate(unittest.TestCase):
    """★ 人工确认闸门：**采集完成后不许自己写**，必须有人点「确认放行」。

    这道闸门存在的唯一意义是"防未经确认的线上写入"，所以用例的重点全在
    **不该写的时候一个字节都不能写**：
      · 没有 require_approval 之外的条件时也不许自动写；
      · 二次放行不许起第二个子进程（会建重复模型）；
      · 勾选之外的卡不许被顺手写进去；
      · 快照丢了/状态不对时一律 fail closed。
    """

    def setUp(self):
        self.hub = _FakeHub()
        self.td = tempfile.mkdtemp(prefix="wbrev-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.td, True))

    def _start(self, cards=None, **cfg):
        return WB.start(tid="t1", payload={"write_back": True},
                        cards=_cards() if cards is None else cards,
                        config={"writeback": _wbcfg(**cfg)},
                        update=self.hub.update, read=self.hub.read,
                        workdir=self.td, log=lambda *a: None)

    def _patch_runner(self):
        """把真正的写卡子进程换成记录桩，并返回调用记录。"""
        from unittest import mock
        calls = []
        obj = mock.Mock(side_effect=lambda **kw: (
            calls.append(kw), {"status": "ok", "counts": {}})[1])
        return mock.patch.object(WB, "run_once", obj), calls

    # ---------------------------------------------------------------- 默认值
    def test_require_approval_defaults_true(self):
        """配置漏写时必须**停下来等人**，而不是直接写线上。"""
        self.assertTrue(WB.cfg({})["require_approval"])
        self.assertTrue(WB.cfg({"writeback": {}})["require_approval"])

    def test_require_approval_can_be_turned_off_explicitly(self):
        self.assertFalse(WB.cfg({"writeback": {"require_approval": False}})
                         ["require_approval"])

    # ---------------------------------------------------------------- 停下等人
    def test_start_parks_and_writes_nothing(self):
        patcher, calls = self._patch_runner()
        with patcher:
            out = self._start()
        self.assertEqual(out["status"], "awaiting_review")
        self.assertEqual(out["cards_in"], 2)
        self.assertEqual(out["default_selected"], 2)
        self.assertEqual(calls, [], "未放行就跑了写卡子进程")
        self.assertEqual(self.hub.state.get("status"), "awaiting_review")
        self.assertTrue(os.path.isfile(WB.pending_path(self.td, "t1")),
                        "待审快照没落盘 → 重启后没法放行")

    def test_snapshot_keeps_full_cards_for_the_writer(self):
        """快照存的必须是**完整**卡片（写卡脚本要 hash/售价），不是预览精简版。"""
        self._start()
        snap = WB.read_pending(self.td, "t1")
        self.assertEqual(len(snap["cards"]), 2)
        self.assertEqual(snap["cards"][0]["hash"], "a" * 32)
        self.assertEqual(snap["sha256"], WB.cards_sha(_cards()))

    def test_new_result_replaces_snapshot(self):
        """任务被重跑 → 新结果整份替换快照，旧的人工确认随之作废。"""
        self._start()
        first = WB.read_pending(self.td, "t1")["sha256"]
        self._start(cards=_cards()[:1])
        snap = WB.read_pending(self.td, "t1")
        self.assertEqual(len(snap["cards"]), 1)
        self.assertNotEqual(snap["sha256"], first)

    def test_resume_review_after_hub_restart(self):
        """待审是**持久态**：hub 重启后仍然能放行（不必重跑采集）。"""
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, by="tester", log=lambda *a: None)
        self.assertEqual(r["status"], "running")
        self.assertEqual(len(calls), 1)

    def test_duplicate_result_does_not_double_fire(self):
        """执行器补传一次结果时，不得把正在跑的上架再触发一遍。

        ⚠️ 必须让假执行器**卡住**（Event）再断言：用秒返回的桩会立刻把状态
           写成 ok，那就测不到"running 期间重复触发"这条分支了（会变成假绿）。
        """
        import threading
        from unittest import mock
        calls = []
        release = threading.Event()

        def slow(**kw):
            calls.append(kw)
            release.wait(5)
            return {"status": "ok", "counts": {}}

        with mock.patch.object(WB, "run_once", mock.Mock(side_effect=slow)):
            self._start()
            WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                       update=self.hub.update, read=self.hub.read,
                       workdir=self.td, log=lambda *a: None)
            self.assertEqual(self.hub.state.get("status"), "running")
            again = self._start()                 # 此刻还在跑
            release.set()
            time.sleep(0.4)
        self.assertEqual(again["status"], "running")
        self.assertIn("忽略", again["reason"])
        self.assertEqual(len(calls), 1, "重复触发起了第二个写卡进程")
        self.assertEqual(len([p for p in self.hub.patches
                              if p.get("status") == "running"]), 1)

    # ---------------------------------------------------------------- 放行
    def test_approve_only_writes_selected_cards(self):
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=["Andy Pettitte/99/SP/Yankees/Awards"],
                           config={"writeback": _wbcfg()}, update=self.hub.update,
                           read=self.hub.read, workdir=self.td, by="wulv",
                           log=lambda *a: None)
            time.sleep(0.3)
        self.assertEqual(r["status"], "running")
        self.assertEqual(r["approved_cards"], 1)
        self.assertEqual(r["reviewed_cards"], 2)
        self.assertEqual(r["approved_names"],
                         ["Andy Pettitte/99/SP/Yankees/Awards"])
        self.assertEqual([c["product_name"] for c in calls[0]["cards"]],
                         ["Andy Pettitte/99/SP/Yankees/Awards"])
        # 留痕要同时进「任务状态」和「最终运行结果」——后者是 extra 传下去的
        self.assertEqual(self.hub.state["approved_names"],
                         ["Andy Pettitte/99/SP/Yankees/Awards"])
        self.assertEqual(calls[0]["extra"]["approved_names"],
                         ["Andy Pettitte/99/SP/Yankees/Awards"])

    def test_approve_all_when_names_missing(self):
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                       update=self.hub.update, read=self.hub.read,
                       workdir=self.td, log=lambda *a: None)
            time.sleep(0.3)
        self.assertEqual(len(calls[0]["cards"]), 2)

    def test_approve_is_idempotent(self):
        """★ 双击/网络重发只放行一次 —— 第二次必须 noop，不进子进程。"""
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            ok = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                            update=self.hub.update, read=self.hub.read,
                            workdir=self.td, log=lambda *a: None)
            self.hub.state["status"] = "ok"          # 模拟线程已跑完
            dup = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                             update=self.hub.update, read=self.hub.read,
                             workdir=self.td, log=lambda *a: None)
            time.sleep(0.3)
        self.assertEqual(ok["status"], "running")
        self.assertEqual(dup["status"], "noop")
        self.assertEqual(len(calls), 1, "第二次放行又起了一个写卡进程")

    def test_approve_rejects_names_outside_snapshot(self):
        """前端传了快照里没有的名字（UI 过期/人为构造）必须拒 —— 不能凭空写。"""
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=["Someone/99/CF/XXX/Awards"],
                           config={"writeback": _wbcfg()}, update=self.hub.update,
                           read=self.hub.read, workdir=self.td, log=lambda *a: None)
        self.assertEqual(r["status"], "noop")
        self.assertIn("快照外", r["reason"])
        self.assertEqual(calls, [])

    def test_approve_rejects_empty_selection(self):
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=[], config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, log=lambda *a: None)
        self.assertEqual(r["status"], "noop")
        self.assertEqual(calls, [])

    def test_approve_rejects_when_snapshot_missing(self):
        self._start()
        os.remove(WB.pending_path(self.td, "t1"))
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, log=lambda *a: None)
        self.assertEqual(r["status"], "noop")
        self.assertIn("快照", r["reason"])
        self.assertEqual(calls, [], "快照丢了还照样写 —— 这是最危险的一条路径")

    def test_approve_rejects_when_not_awaiting(self):
        for st in ("skipped", "running", "ok", "cancelled", None):
            self.hub.state = {} if st is None else {"status": st}
            r = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, log=lambda *a: None)
            self.assertEqual(r["status"], "noop", st)

    def test_approve_records_who_approved(self):
        self._start()
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, by="wulv", log=lambda *a: None)
            time.sleep(0.3)
        self.assertEqual(r["status"], "running")
        self.assertEqual(self.hub.state["approved_by"], "wulv")
        self.assertEqual(self.hub.state["sha256"],
                         WB.read_pending(self.td, "t1")["sha256"])
        # 留痕要一路带到最终结果里（否则事后查不到谁放行的）
        self.assertEqual(calls[0]["extra"]["approved_by"], "wulv")

    # ---------------------------------------------------------------- 取消
    def test_cancel_from_awaiting(self):
        self._start()
        r = WB.cancel(tid="t1", read=self.hub.read, update=self.hub.update,
                      workdir=self.td, by="wulv", log=lambda *a: None)
        self.assertEqual(r["status"], "cancelled")
        self.assertEqual(self.hub.state["status"], "cancelled")
        self.assertEqual(self.hub.state["cancelled_by"], "wulv")

    def test_cancel_refused_once_running(self):
        """已经在跑的不给取消：中途 kill 会留下状态未知的模型，更危险。"""
        self.hub.state = {"status": "running"}
        r = WB.cancel(tid="t1", read=self.hub.read, update=self.hub.update,
                      workdir=self.td, log=lambda *a: None)
        self.assertEqual(r["status"], "noop")

    # ---------------------------------------------------------------- 预览
    def test_preview_flags_missing_fields(self):
        cards = [{"product_name": "", "hash": "", "sale_price": "", "include": True}]
        pre = WB.review_preview(cards)
        self.assertEqual(pre[0]["issues"],
                         ["缺 product_name", "缺卡图 hash", "缺售价"])

    def test_preview_flags_duplicate_names(self):
        cards = [{"product_name": "X/99/CP/A/B", "hash": "h", "sale_price": "1",
                  "include": True}] * 2
        pre = WB.review_preview(cards)
        self.assertTrue(pre[1]["issues"], "同名重复没被标出来")

    def test_preview_issues_do_not_block_release(self):
        """静态提示只是提示 —— 人工确认后仍可放行（不代替人的判断）。"""
        self._start(cards=[{"name": "A", "product_name": "A/99/CP/X/S",
                            "include": True}])
        patcher, calls = self._patch_runner()
        with patcher:
            r = WB.approve(tid="t1", names=None, config={"writeback": _wbcfg()},
                           update=self.hub.update, read=self.hub.read,
                           workdir=self.td, log=lambda *a: None)
        self.assertEqual(r["status"], "running")

    def test_preview_tolerates_garbage(self):
        self.assertEqual(WB.review_preview(None), [])
        self.assertEqual(WB.review_preview([None, 1, "x"]), [])

    # ---------------------------------------------------------------- 其他
    def test_cards_sha_changes_with_content(self):
        a = WB.cards_sha(_cards())
        b = WB.cards_sha(_cards()[:1])
        self.assertNotEqual(a, b)
        self.assertEqual(WB.cards_sha(None), WB.cards_sha([]))

    def test_run_once_extra_cannot_override_status(self):
        """审批留痕是补充信息，绝不能覆盖运行结论（否则会把失败写成功）。"""
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            def fake_run(cmd, **kw):
                out = cmd[cmd.index("--out") + 1]
                with open(out, "w", encoding="utf-8") as f:
                    json.dump([{"verdict": "dry-run"}], f)
                return subprocess.CompletedProcess(cmd, 0, stdout=b"x\n")

            wb = _wbcfg(script="/opt/x/mlb_write_cards.py", dry_run=True)
            with mock.patch.object(WB.subprocess, "run", fake_run):
                res = WB.run_once(tid="t9", cards=_cards(), wb=wb, workdir=td,
                                  log=lambda *a: None,
                                  extra={"status": "ok", "approved_by": "wulv"})
        self.assertEqual(res["status"], "dry_run", "审批留痕把结论覆盖了")
        self.assertEqual(res["approved_by"], "wulv")

    def test_gate_still_runs_before_approval_logic(self):
        """四道闸门的第一道还是"任务勾选" —— 没勾就走不到冻结那一步。"""
        out = WB.start(tid="t1", payload={}, cards=_cards(),
                       config={"writeback": _wbcfg()}, update=self.hub.update,
                       read=self.hub.read, workdir=self.td, log=lambda *a: None)
        self.assertEqual(out["status"], "skipped")
        self.assertFalse(os.path.isfile(WB.pending_path(self.td, "t1")))

    def test_approval_off_keeps_old_auto_behaviour(self):
        """显式关掉人工确认时，行为回到"闸门过了就直接跑"。"""
        patcher, calls = self._patch_runner()
        with patcher:
            out = self._start(require_approval=False)
            time.sleep(0.3)
        self.assertEqual(out["status"], "running")
        self.assertEqual(len(calls), 1)
        self.assertFalse(os.path.isfile(WB.pending_path(self.td, "t1")),
                         "免确认模式不该产生待审快照")


class CoinsRateBridge(unittest.TestCase):
    """hub 侧取价：只做搬运 + 缓存，换算全在子进程里。

    两个必须守住的性质：
      ① 关掉/没配好时**绝不去连后台**（宁可让人工填）；
      ② 失败要**负缓存**，否则页面 5 秒一轮 = 每小时 720 次登录，账号会被试锁。
    """

    def setUp(self):
        CR._CACHE["data"] = None
        CR._NEG["data"] = None
        self.c = CR.cfg({"coins_rate": {
            "enabled": True, "python": sys.executable, "script": _WB_SRC,
            "cred": _WB_SRC, "gid": 922, "area": "PS 5", "multiplier": 100,
            "timeout": 30, "cache_sec": 600, "cache_dir": ""}})

    def test_cfg_defaults_are_fail_safe(self):
        d = CR.cfg({})
        self.assertFalse(d["enabled"], "配置缺失时必须**不**去连后台")
        self.assertEqual(d["gid"], 922)
        self.assertEqual(d["multiplier"], 100)
        self.assertEqual(d["area"], "PS 5")

    def test_status_exposes_booleans_not_paths(self):
        s = CR.status(self.c)
        blob = json.dumps(s)
        self.assertNotIn("/opt/", blob, "health 把服务器路径回给前端了")
        self.assertTrue(s["script_ok"] and s["cred_ok"])
        self.assertEqual(s["gid"], 922)

    def test_build_cmd_shape(self):
        cmd = CR.build_cmd(self.c, "/tmp/o.json")
        self.assertIn("--gid", cmd)
        self.assertEqual(cmd[cmd.index("--gid") + 1], "922")
        self.assertEqual(cmd[cmd.index("--multiplier") + 1], "100")
        self.assertEqual(cmd[cmd.index("--area") + 1], "PS 5")
        self.assertIn("--out", cmd)
        self.assertIn("--json", cmd)

    def test_disabled_never_spawns(self):
        from unittest import mock
        with mock.patch.object(CR.subprocess, "run") as run:
            r = CR.fetch(CR.cfg({}))
        self.assertFalse(r["ok"])
        self.assertEqual(r["step"], "disabled")
        run.assert_not_called()

    def test_missing_script_never_spawns(self):
        from unittest import mock
        with mock.patch.object(CR.subprocess, "run") as run:
            r = CR.fetch(CR.cfg({"coins_rate": {"enabled": True,
                                                "script": "/nope/x.py",
                                                "cred": "/nope/c.json"}}))
        self.assertFalse(r["ok"])
        self.assertEqual(r["step"], "config")
        run.assert_not_called()

    def test_fetch_parses_stdout_json(self):
        from unittest import mock
        payload = json.dumps({"ok": True, "b2c": 0.0429,
                              "rate_usd_per_100k": 4.29,
                              "formula": "0.0429(USD/1K) × 100 = 4.29(USD/100K)"})
        with tempfile.TemporaryDirectory() as td:
            def fake_run(cmd, **kw):
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=("[price] 登录成功\n" + payload + "\n").encode(),
                    stderr=b"")
            with mock.patch.object(CR.subprocess, "run", fake_run):
                r = CR.fetch(self.c, log=lambda *a: None, out_dir=td)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["rate_usd_per_100k"], 4.29)
        self.assertIn("× 100", r["formula"])

    def test_timeout_is_reported_not_raised(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            def boom(cmd, **kw):
                raise subprocess.TimeoutExpired(cmd, 1)
            with mock.patch.object(CR.subprocess, "run", boom):
                r = CR.fetch(self.c, log=lambda *a: None, out_dir=td)
        self.assertFalse(r["ok"])
        self.assertEqual(r["step"], "timeout")

    def test_failure_is_negatively_cached(self):
        """★ 失败后 60 秒内不再登录后台 —— 防把账号试锁。"""
        from unittest import mock
        calls = []
        with mock.patch.object(CR, "fetch",
                               side_effect=lambda c, **kw: (calls.append(1),
                                                            {"ok": False,
                                                             "error": "x"})[1]):
            CR.get(self.c, log=lambda *a: None)
            CR.get(self.c, log=lambda *a: None)
            CR.get(self.c, log=lambda *a: None)
        self.assertEqual(len(calls), 1, "失败没有负缓存，会打爆后台登录")
        # 显式强制重取时必须真的重取（页面上有「重试」）
        with mock.patch.object(CR, "fetch",
                               side_effect=lambda c, **kw: (calls.append(1),
                                                            {"ok": False})[1]):
            CR.get(self.c, force=True, log=lambda *a: None)
        self.assertEqual(len(calls), 2)

    def test_success_is_cached(self):
        from unittest import mock
        calls = []
        with mock.patch.object(CR, "fetch",
                               side_effect=lambda c, **kw: (calls.append(1),
                                                            {"ok": True,
                                                             "rate_usd_per_100k": 4.29})[1]):
            CR.get(self.c, log=lambda *a: None)
            r = CR.get(self.c, log=lambda *a: None)
        self.assertEqual(len(calls), 1)
        self.assertTrue(r["cached"])


class HubApprovalWiring(unittest.TestCase):
    """hub 侧接线：放行/取消两个接口，以及取价旁路的落点。"""

    def test_approve_and_cancel_routes_exist(self):
        text = _text("server/mlb_server.py")
        self.assertIn('path.endswith("/writeback/approve")', text)
        self.assertIn('path.endswith("/writeback/cancel")', text)
        self.assertIn("WB.approve(", text)
        self.assertIn("WB.cancel(", text)

    def test_approve_reads_state_from_server_not_from_client(self):
        """放行判断只认服务端状态（read=writeback_read），不信前端传参。"""
        text = _text("server/mlb_server.py")
        self.assertIn("def writeback_read(", text)
        i = text.find('path.endswith("/writeback/approve")')
        seg = text[i:i + 900]
        self.assertIn("read=writeback_read", seg)
        self.assertIn("update=writeback_update", seg)
        self.assertNotIn("body.get(\"status\")", seg)

    def test_start_receives_read_hook(self):
        text = _text("server/mlb_server.py")
        i = text.find("WB.start(")
        self.assertIn("read=writeback_read", text[i:i + 500])

    def test_health_exposes_require_approval_and_rate_booleans(self):
        text = _text("server/mlb_server.py")
        i = text.find('path == "/api/health"')
        seg = text[i:i + 1100]
        self.assertIn('"require_approval"', seg)
        self.assertIn("CR.status(", seg)
        self.assertNotIn('"script":', seg)      # 不回具体路径
        self.assertNotIn('"cred":', seg)

    def test_coins_rate_route_and_cache_dir(self):
        text = _text("server/mlb_server.py")
        self.assertIn('path == "/api/coins-rate"', text)
        self.assertIn('RATE_DIR = os.path.join(HERE, "data", "pricing")', text)
        self.assertNotIn('os.path.join(HERE, "files", "pricing")', text)

    def test_boot_sweep_also_handles_lost_review_snapshot(self):
        text = _text("server/mlb_server.py")
        i = text.find("def mark_interrupted_writebacks(")
        seg = text[i:i + 2200]
        self.assertIn("WB.AWAITING", seg)
        self.assertIn("review_lost", seg)
        self.assertIn("mark_interrupted_writebacks()", text[text.find("def main("):][:900])

    def test_no_schema_migration_still(self):
        text = _text("server/mlb_server.py")
        self.assertIsNone(re.search(r"""c\.execute\(\s*['"]\s*ALTER\s+TABLE""",
                                    text, re.I))


class WebApprovalUi(unittest.TestCase):
    """网页：能核对、能勾选、能放行，且**勾选不会被轮询重绘抹掉**。"""

    def test_review_panel_exists(self):
        text = _text("web/index.html")
        for kw in ("renderReview", "approveWriteback", "cancelWriteback",
                   'id="wbGo"', 'id="wbAck"', 'id="wbCancel"',
                   'id="wbSelCount"', 'id="wbMsg"'):
            self.assertIn(kw, text, "网页缺少 %s" % kw)

    def test_awaiting_review_has_status_and_label(self):
        text = _text("web/index.html")
        self.assertIn("awaiting_review", text)
        self.assertIn("待人工确认", text)
        self.assertIn("review_lost", text)

    def test_selection_state_lives_outside_dom(self):
        """★ 勾选状态必须存在 DOM 之外 —— 本页每 5 秒重绘一次当前任务。"""
        text = _text("web/index.html")
        self.assertIn("const WB_SEL = {}", text)
        self.assertIn("wbSelBox", text)
        self.assertRegex(text, r"if\(!\(nm in sel\)\) sel\[nm\]",
                         "缺少「首绘预置勾选」的逻辑")

    def test_approve_and_cancel_endpoints(self):
        text = _text("web/index.html")
        self.assertIn("/writeback/approve", text)
        self.assertIn("/writeback/cancel", text)

    def test_approve_button_requires_explicit_ack(self):
        """光有按钮不算闸门 —— 必须还有一个"我已核对"的勾才能点。"""
        text = _text("web/index.html")
        i = text.find("function wbBtnState(")
        self.assertGreater(i, 0)
        seg = text[i:i + 700]
        self.assertIn("ack.checked", seg)
        self.assertIn("n > 0", seg)

    def test_cancel_needs_two_clicks(self):
        text = _text("web/index.html")
        self.assertIn("WB_CANCEL_ARM", text)
        self.assertIn("再点一次", text)

    def test_stranded_review_task_can_be_reached_from_history(self):
        """新任务把待审任务挤下去之后，必须还能从历史里跳回去放行。"""
        text = _text("web/index.html")
        self.assertIn("pinTask", text)
        self.assertIn("去确认上架", text)
        self.assertIn("let PIN = null", text)

    def test_coins_rate_prefill_and_manual_override(self):
        text = _text("web/index.html")
        for kw in ("refreshCoinsRate", "/coins-rate", "RATE_TOUCHED",
                   'id="rateHint"', "重新取价"):
            self.assertIn(kw, text, "网页缺少 %s" % kw)
        # 人工改过之后不许被自动值覆盖
        self.assertIn("!RATE_TOUCHED || force", text)

    def test_rate_not_retried_every_poll(self):
        """取价失败不许每 5 秒重试（会打爆后台登录）。"""
        text = _text("web/index.html")
        self.assertIn("if(!RATE_AUTO || manual) jobs.push(refreshCoinsRate())", text)

    def test_approved_names_shown_in_audit_line(self):
        """留痕要能回答「到底放行了哪几张」—— 光有计数不够。"""
        text = _text("web/index.html")
        self.assertIn("approved_names", text)
        self.assertIn("放行卡片：", text)

    def test_cards_table_column_count_still_synced(self):
        text = _text("web/index.html")
        self.assertIn('colspan="9"', text)

    # ---- 写入量的口径：一张新卡 = 一个模型，同名卡不重建 ----

    def test_no_hardcoded_product_count_in_copy(self):
        """⛔ 上架提示里**不许**再出现写死的「N 个产品」。

        写入量 = 本次新增的卡数（一张新卡一个模型），每批都不一样；
        写死一个数字（曾经是 48）会让人以为那是本批总数 ——
        实际 48 是**单个模型**的渠道产品数。这个断言就是防它回来。
        """
        text = _text("web/index.html")
        self.assertNotRegex(text, r"\d+\s*个产品",
                            "页面上又出现了写死的「N 个产品」，应改为按卡数/逐行给出")
        # 只查这两段提示，别把 CSS 里的 `480px` 也算进来
        i = text.find('id="wbHint"')
        self.assertGreater(i, 0)
        segs = {"wbHint": text[i:i + 620]}
        k = text.find("function refreshWritebackHint(")
        self.assertGreater(k, 0)
        segs["refreshWritebackHint"] = text[k:k + 1600]
        for name, seg in segs.items():
            self.assertNotRegex(seg, r"\b48\b", "%s 里又写死了 48" % name)

    def test_copy_states_one_card_one_model(self):
        """文案必须讲清：一张新卡 = 一个模型；同名卡已存在不重复建。"""
        text = _text("web/index.html")
        self.assertIn("一张新卡 = 一个模型", text)
        self.assertIn("不会重复建", text)        # 静态提示
        self.assertIn("跳过不重建", text)        # 服务端状态刷新后的提示

    def test_writeback_report_labels_products_as_per_model(self):
        """报告里的「产品」是**每模型**的渠道产品数，不能让人当总数读。"""
        text = _text("web/index.html")
        self.assertIn("<th class=\"num\">渠道产品</th>", text)
        self.assertIn("不是本批总数", text)
        self.assertIn("模型（一张卡 = 一个）", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
