"""Synthetic fast contracts against actual selected source. No production IO."""
import ast, copy, importlib.util, json, re, sys, tempfile, unittest
from pathlib import Path
from decimal import Decimal
ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

class RPGGuards(unittest.TestCase):
    def setUp(self):
        self.gates = module("fast_gates", "opt/d4follow/gates.py")
        sys.modules["gates"] = self.gates
        self.engine = module("fast_engine", "opt/d4follow/engine.py")
    def test_binding_quantity_drift_stops_without_mutation(self):
        cfg = {"p2pah":{"商品ID映射":{"KEY_X10":"101"}},
               "商品映射":{"对照项":[{"key":"KEY_X10","装量":10,"p2pah":{"商品名关键词":"Key"}}]}}
        before = copy.deepcopy(cfg)
        drift, checked = self.gates.detect_binding_drift(cfg,[{"id":"101","title":"(1000) Key"}],log=lambda *a:None)
        self.assertEqual(checked,1)
        self.assertIn("qty_changed",[d["level"] for d in drift])
        self.assertEqual(cfg,before)
    def test_quantity_collision_is_reported(self):
        cfg={"商品映射":{"对照项":[{"key":"KEY_X10","装量":10},{"key":"KEY_X1000","装量":10}]}}
        self.assertTrue(self.gates.audit_qty_collisions(cfg,log=lambda *a:None))
    def test_step_limit_and_explicit_off(self):
        self.assertEqual(self.gates.clamp_round_step({},1,10),(1.5,True,.5))
        self.assertEqual(self.gates.clamp_round_step({"引擎":{"单轮幅度上限":0}},1,10),(10,False,0))
    def test_tick_cannot_raise_front_price_above_target(self):
        value=self.engine.fit_under_tick(.1003,.0001,.9,.0902,dec=4)
        self.assertLessEqual(round(value*.9,4),.0902)
        self.assertIsNone(self.engine.fit_under_tick(.0000947,.0001,1,.0000947,dec=4))

class RPGModuleContracts(unittest.TestCase):
    """并入 d4follow 模块的最小离线合同检查（纯函数/结构；无网络、无子进程）。

    范围声明：只验证「Python 3.9 语法可解析 + 关键符号存在 + 加签纯函数确定性 +
    凭据未配置时不抛错」。不替代集成验收，不替代线上 UI/发布验收。
    """
    MERGED = (
        "opt/d4follow/app.py",
        "opt/d4follow/aion2_watch.py",
        "opt/d4follow/core_dd373_cost.py",
        "opt/d4follow/core_front.py",
        "opt/d4follow/core_g2g.py",
        "opt/d4follow/core_gold.py",
        "opt/d4follow/core_multi.py",
        "opt/d4follow/dingtalk_push.py",
        "opt/d4follow/switch_pricing_mode.py",
        "opt/d4follow/drop_monitor_item.py",
        "opt/d4follow/health_check_aion2.py",
        "opt/d4follow/manual_override.py",
        "opt/d4follow/push_data.py",
        "opt/d4follow/set_collect_interval.py",
        "opt/d4follow/simulate.py",
        "opt/d4follow/verify_aion2_after_1yi.py",
        "aion2_dd373_local_collect_20261006/dd373_local_collect.py",
        "aion2_dd373_local_collect_20261006/run_collect.py",
    )

    def test_merged_modules_parse_under_python39(self):
        for rel in self.MERGED:
            ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel,
                      feature_version=(3, 9))

    def test_dingtalk_signing_is_deterministic_and_offline(self):
        push = module("fast_dingtalk_push", "opt/d4follow/dingtalk_push.py")
        bot = push.DingTalkBot(
            webhook="https://oapi.dingtalk.com/robot/send?access_token=synthetic",
            secret="SEC" + "a" * 64)
        first = bot._sign_digest("1700000000000", 0)
        self.assertEqual(first, bot._sign_digest("1700000000000", 0))
        self.assertEqual(len(first), 32)
        signed = bot._signed_url(mode=0, ts="1700000000000")
        self.assertIn("timestamp=1700000000000", signed)
        self.assertIn("sign=", signed)
        # 4 种签名策略必须给出互不相同的摘要（"逐策略试错"实现的前提）
        self.assertEqual(len({bot._sign_digest("1700000000000", m) for m in range(4)}), 4)
        # 凭据未配置：必须能构造、不抛错；发送时才报明确错误且不发网络
        bare = push.DingTalkBot.from_env(prefix="__ABSENT_FOR_TEST__")
        self.assertFalse(bare.configured)
        self.assertEqual(bare._signed_url(), "")
        with self.assertRaises(push.DingTalkError):
            bare.send({})

    def test_pricing_mode_switch_declares_all_modes(self):
        sw = module("fast_switch_pricing_mode", "opt/d4follow/switch_pricing_mode.py")
        self.assertEqual(set(sw.VALID),
                         {"dd373_only", "g2g_cheapold", "dd373_markup", "multisrc"})

    def test_release_guard_refuses_unmanaged_and_is_offline(self):
        """受控发布器的守卫必须是「保守失败」：无法解释的远端内容一律拒发。"""
        rd = module("fast_release_d4follow", "tools/release_d4follow.py")
        known = {"a" * 64}
        target = "b" * 64
        self.assertEqual(rd.classify(None, target, known), "NEW")
        self.assertEqual(rd.classify(target, target, known), "SAME")
        self.assertEqual(rd.classify("a" * 64, target, known), "OLD")
        self.assertEqual(rd.classify("c" * 64, target, known), "UNMANAGED")
        remote, targets = {"app.py": "c" * 64}, {"app.py": target}
        actions, refusals = rd.plan_actions(remote, targets, {"app.py": known})
        self.assertEqual(len(refusals), 1)
        self.assertEqual(actions, [])
        actions, refusals = rd.plan_actions(remote, targets, {"app.py": known}, allow_unmanaged=True)
        self.assertEqual(refusals, [])
        self.assertEqual(actions[0][1], "OVERRIDE")

    def test_release_guard_path_id_and_credential_rules(self):
        rd = module("fast_release_d4follow", "tools/release_d4follow.py")
        self.assertEqual(rd.safe_rel("templates/index.html"), "templates/index.html")
        for bad in ("../x", "/etc/passwd", "a\\b.py", "data/x.py", "a/b/c.py", ""):
            with self.assertRaises(rd.Refused):
                rd.safe_rel(bad)
        for bad in ("", "../x", "a b"):
            with self.assertRaises(rd.Refused):
                rd.check_release_id(bad)
        # 凭据文件禁止从仓库发布（仓库版是脱敏占位，线上含真实 token）
        self.assertIn("set_dingtalk_secret.sh", rd.NEVER_PUBLISH)

    def test_release_publisher_parses_on_python39_and_uses_no_third_party(self):
        src = (ROOT / "tools/release_d4follow.py").read_text(encoding="utf-8")
        tree = ast.parse(src, filename="release_d4follow.py", feature_version=(3, 9))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & {"requests", "paramiko", "yaml", "fabric"})

class G2GModuleContracts(unittest.TestCase):
    """g2gfollow（G2G 金币改价系统 · AION2 Kinah）2026-10-14 纳入版本管理的最小离线合同。

    范围声明：只验证「Python 3.9 语法可解析 + 关键定价常量与签名存在 + systemd
    unit 的单 worker 约束 + 凭据卫生」。**不 exec 这些模块** —— app.py 依赖 Flask，
    CI 隔离环境不装第三方包，只做 AST / 文本级断言。
    不替代集成验收，也不替代线上 UI / 写价验收。
    """
    UNIT = "opt/g2gfollow/"
    MODULES = (
        "app.py",
        "core_self.py",
        "pricing.py",
        "store.py",
        "tools/auto_cycle.py",
        "tools/g2g_token_refresher.py",
        "tools/recheck_writes.py",
        "tools/selftest.py",
        "tools/snapshot_config.py",
        "vendor/__init__.py",
        "vendor/core_dd373_cost.py",
        "vendor/core_g2g.py",
    )
    TRACKED = MODULES + (
        "README.md",
        "requirements.txt",
        "templates/index.html",
        "systemd/g2gfollow.service",
        "tools/sync_vendor.sh",
        ".gitignore",
    )
    # 疑似凭据：私钥块 / 裸 Bearer token / JWT
    CREDENTIAL = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY|"
        r"Bearer\s+[A-Za-z0-9\-_.]{20,}|"
        r"\beyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.")

    def _text(self, rel):
        return (ROOT / self.UNIT / rel).read_text(encoding="utf-8-sig")

    def _tree(self, rel):
        return ast.parse(self._text(rel), filename=self.UNIT + rel,
                         feature_version=(3, 9))

    def _assign(self, rel, name):
        """取模块级 `name = <字面量>` 的字面值；找不到返回 None。"""
        for node in self._tree(rel).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return ast.literal_eval(node.value)
        return None

    def test_all_modules_parse_under_python39(self):
        for rel in self.MODULES:
            self._tree(rel)

    def test_dd373_cost_keeps_pricing_baseline(self):
        """成本口径三条不能丢 —— 都是线上定过案的业务口径。"""
        rel = "vendor/core_dd373_cost.py"
        # 跳过综合排序第一个挂售订单（2026-10-14 老板定案：低价挂单会拉低成本均价）
        self.assertEqual(self._assign(rel, "SKIP_LOWEST_QUOTES"), 1)
        # 买满量 5 亿基纳；不足买满量时按条数吃满 10 条（2026-10-12 老板定案）
        self.assertEqual(self._assign(rel, "TARGET_WAN"), 50000.0)
        self.assertEqual(self._assign(rel, "FALLBACK_ITEMS"), 10)

    def test_orderbook_avg_exposes_skip_lowest(self):
        rel = "vendor/core_dd373_cost.py"
        args = None
        for node in ast.walk(self._tree(rel)):
            if isinstance(node, ast.FunctionDef) and node.name == "orderbook_avg":
                args = [a.arg for a in node.args.args]
        self.assertIsNotNone(args, "orderbook_avg 不见了")
        self.assertIn("skip_lowest", args)

    def test_systemd_unit_keeps_single_worker(self):
        """采集进度 / 推荐单是进程内全局状态 ⇒ 必须 -w 1（改多 worker 会串状态）。"""
        text = self._text("systemd/g2gfollow.service")
        self.assertIn("-w 1", text)
        self.assertIn("/opt/g2gfollow/venv/bin/gunicorn", text)
        self.assertIn("app:app", text)

    def test_gitignore_keeps_credentials_and_runtime_out(self):
        """入仓最易犯的错：把 var/ 下的 token / session 或 config.json 提交进来。"""
        rules = [line.strip() for line in self._text(".gitignore").splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        self.assertIn("var/", rules)             # accessToken + session cookie
        self.assertIn("config.json", rules)      # 与仓库根 **/config.json* 同口径
        self.assertIn("venv/", rules)
        self.assertIn("vendor/data/dd373_zone_tree.json", rules)   # 6h TTL 缓存
        self.assertNotIn("vendor/dd373_zone_tree.json", rules)     # 旧错路径，不得回退

    def test_no_hardcoded_credentials_in_tracked_files(self):
        for rel in self.TRACKED:
            self.assertIsNone(self.CREDENTIAL.search(self._text(rel)),
                              "%s 里出现疑似凭据" % rel)

class BotModuleContracts(unittest.TestCase):
    """Discord 机器人三件套（2026-10-15 纳入版本管理）的最小离线合同。

    范围 = MMOEXP GuardBot（防冒充守卫，Node）+ Shugo-bot（AION2 迎新，Python）
    + 管这两个机器人的控制台页面 /bots/（Python 后端 + 单文件前端）。

    只验证「Python 3.9 语法可解析 + 关键安全不变量还在 + systemd/nginx 接线没被
    改成裸奔 + 凭据卫生」。**不 exec、不联网、不起服务** —— CI 隔离环境里没有
    discord.js / discord.py，也不该为了跑一次检查去装。所以这不替代线上验收，
    也不替代控制台在真实浏览器里的行为验收。
    """
    GUARD = "opt/mmoexp-guardbot/"
    SHUGO = "opt/shugo-bot/"
    CONSOLE = "opt/bot-console/"

    PY_MODULES = (
        SHUGO + "bot.py",
        SHUGO + "news.py",
        SHUGO + "setup.py",
        SHUGO + "09_news_setup.py",
        CONSOLE + "server.py",
        CONSOLE + "_smoke_test.py",
        CONSOLE + "_test_classify.py",
        CONSOLE + "_e2e_browser.py",
        CONSOLE + "_e2e_nav_control.py",
        GUARD + "_ops_set_dryrun.py",
        GUARD + "_ops_xcheck.py",
    )

    # 疑似凭据：私钥块 / 裸 Bearer token / JWT / Discord Bot Token。
    # Discord 的三段式里，中段固定是 6 位 base64 时间戳、尾段 ≥27 位。
    # index.js 测试里那个哨兵 `…….SENTINEL.DO_NOT_LEAK_ME` 中段 8 位、尾段 14 位，
    # 两个条件都不满足 ⇒ 不误报（这是有意的：哨兵要能留在库里当反面样例）。
    CREDENTIAL = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY|"
        r"Bearer\s+[A-Za-z0-9\-_.]{20,}|"
        r"\beyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\.|"
        r"\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,110}\b")

    def _text(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8-sig")

    def _tree(self, rel):
        return ast.parse(self._text(rel), filename=rel, feature_version=(3, 9))

    def _assign(self, rel, name):
        """取模块级 `name = <字面量>` 的字面值；找不到返回 None。"""
        for node in self._tree(rel).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return ast.literal_eval(node.value)
        return None

    def _rules(self, rel):
        return [line.strip() for line in self._text(rel).splitlines()
                if line.strip() and not line.strip().startswith("#")]

    def test_all_python_modules_parse_under_python39(self):
        for rel in self.PY_MODULES:
            self._tree(rel)

    def test_guardbot_defaults_stay_fail_safe(self):
        """DEFAULTS 必须保持「默认不处置 + 默认严格匹配」。

        线上为了抓拼错前缀切到了 loose / ban，但**代码默认值**必须是保守的：
        默认值一改，任何新部署（或 config.json 被清掉）都会变成上线即封号。
        """
        block = self._text(self.GUARD + "index.js").split("const DEFAULTS = {", 1)[1].split("\n};", 1)[0]
        self.assertIn("dryRun: true", block)
        self.assertIn("action: 'kick'", block)
        self.assertIn("matchMode: 'strict'", block)

    def test_guardbot_keeps_admin_hard_protection(self):
        """第二道闸：带 Administrator 的官方管理组永不处理，与白名单无关。"""
        text = self._text(self.GUARD + "index.js")
        self.assertIn("function isProtectedAdmin", text)
        self.assertIn("PermissionFlagsBits.Administrator", text)

    def test_guardbot_paths_stay_relative_to_module_dir(self):
        """config.json / whitelist.json 从模块目录取，不写死 /opt 绝对路径 ——
        否则控制台注册表里的 dir 就骗人，也没法在别处复现。"""
        text = self._text(self.GUARD + "index.js")
        self.assertIn("const ROOT = __dirname;", text)
        self.assertIn("path.join(ROOT, 'config.json')", text)
        self.assertIn("path.join(ROOT, 'whitelist.json')", text)

    def test_shugo_takes_token_from_env_before_file(self):
        """令牌来源顺序：SHUGO_TOKEN 环境变量 > 同目录 token.txt。
        这条同时守住「顺序」和「版本库里两个都不能有真值」。"""
        text = self._text(self.SHUGO + "bot.py")
        env = text.index('os.environ.get("SHUGO_TOKEN"')
        self.assertLess(env, text.index('"token.txt"'))

    def test_console_registry_covers_both_bots(self):
        """控制台的机器人注册表就是 /bots/ 页面能管什么的事实源。"""
        bots = self._assign(self.CONSOLE + "server.py", "BOTS")
        self.assertEqual(sorted(bots), ["guard", "shugo"])
        self.assertEqual(bots["guard"]["service"], "mmoexp-guardbot")
        self.assertEqual(bots["guard"]["dir"], "/opt/mmoexp-guardbot")
        self.assertEqual(bots["guard"]["runtime"], "node")
        self.assertEqual(bots["shugo"]["service"], "shugo-bot")
        self.assertEqual(bots["shugo"]["dir"], "/opt/shugo-bot")
        self.assertEqual(bots["shugo"]["runtime"], "python")

    def test_console_binds_loopback_only(self):
        """控制台能启停服务、能换 Bot Token ⇒ 只能挂 127.0.0.1，公网必须经 nginx 门禁。"""
        text = self._text(self.CONSOLE + "server.py")
        self.assertIn('_env("BOTCONSOLE_BIND", "127.0.0.1")', text)
        self.assertIn('_env("BOTCONSOLE_PORT", "8936")', text)

    def test_console_service_scopes_write_paths(self):
        text = self._text(self.CONSOLE + "bot-console.service")
        self.assertIn("ExecStart=/opt/bot-console/venv/bin/python -B /opt/bot-console/server.py", text)
        self.assertIn("Environment=BOTCONSOLE_BIND=127.0.0.1", text)
        self.assertIn("ProtectSystem=full", text)
        # 控制台要写这两个机器人的配置目录，其余路径保持只读
        writable = text.split("ReadWritePaths=", 1)[1].split("\n", 1)[0]
        for path in ("/opt/mmoexp-guardbot", "/opt/shugo-bot", "/opt/bot-console/data"):
            self.assertIn(path, writable)

    def test_bots_page_stays_behind_the_login_gate(self):
        """/bots/ 是主导航里的入口，必须继承统一登录门禁：
        auth_request 先行，且身份头由 nginx 覆盖写入（客户端自带的同名头无效）。"""
        text = self._text(self.CONSOLE + "bot-console.locations.conf")
        self.assertIn("location /bots/", text)
        self.assertIn("auth_request /__auth_verify;", text)
        self.assertIn("proxy_pass http://127.0.0.1:8936/;", text)
        self.assertIn("proxy_set_header X-Auth-Role $bots_role;", text)

    def test_gitignore_keeps_credentials_and_runtime_out(self):
        """三个模块各自挡住最容易误提交的东西。"""
        guard = self._rules(self.GUARD + ".gitignore")
        self.assertIn("config.json", guard)        # 含 Bot Token
        self.assertIn("whitelist.json", guard)     # 控制台运行时改写
        self.assertIn("node_modules/", guard)

        shugo = self._rules(self.SHUGO + ".gitignore")
        self.assertIn("token.txt", shugo)          # 机器人令牌
        self.assertIn("config.json", shugo)
        self.assertIn("news_state.json", shugo)    # 去重表，每轮改写
        self.assertIn(".venv/", shugo)

        console = self._rules(self.CONSOLE + ".gitignore")
        self.assertIn("data/", console)            # audit.log + 含 token 的配置备份
        self.assertIn("venv/", console)

    def test_no_hardcoded_credentials_in_tracked_files(self):
        for rel in self.PY_MODULES + (self.GUARD + "index.js",):
            self.assertIsNone(self.CREDENTIAL.search(self._text(rel)),
                              "%s 里出现疑似凭据" % rel)

class OpsModuleContracts(unittest.TestCase):
    """6 个 /opt 运营模块（2026-10-17 补登记进闸门）的最小离线合同。

    范围 = 统一登录门禁 auth-portal + 全站写权限 fs-access-policy + 抓取站
    iggm-web + MLB 上架工作台 mlb-online + NBA 改价后端 nba-reprice + 任务台
    mmoexp-taskboard。

    只验证「Python 3.9 语法可解析 + 关键安全不变量还在 + 凭据卫生」。
    **不 exec（access_policy 除外，它只依赖标准库）、不联网、不起服务** ——
    CI 隔离环境里没有 flask / ddddocr / node 依赖，也不该为了跑一次检查去装。
    所以这不替代线上验收，也不替代真实浏览器里的行为验收。
    """
    AUTH = "opt/auth-portal/"
    POLICY = "opt/fs-access-policy/"
    IGGM = "opt/iggm-web/"
    MLB = "opt/mlb-online/"
    NBA = "opt/nba-reprice/"
    TASK = "opt/mmoexp-taskboard/"

    PY_MODULES = (
        AUTH + "auth_portal.py",
        AUTH + "fs_ip_alert.py",
        AUTH + "fs_ip_observe_report.py",
        POLICY + "access_policy.py",
        IGGM + "app.py",
        IGGM + "core.py",
        IGGM + "core_aoeah.py",
        IGGM + "core_u4gm.py",
        IGGM + "sites.py",
        IGGM + "url_guard.py",
        MLB + "mlb_server.py",
        MLB + "mlb_writeback.py",
        MLB + "mlb_coins_rate.py",
        MLB + "_selftest/tests/verify_writeback_e2e.py",
        NBA + "backend/p2pah_api.py",
        NBA + "backend/write_contract.py",
        NBA + "backend/ocr_captcha.py",
        TASK + "taskboard_server.py",
        TASK + "green_plan.py",
    )

    CREDENTIAL = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY|"
        r"Bearer\s+[A-Za-z0-9\-_.]{20,}|"
        r"\beyJ[A-Za-z0-9\-_]{8,}\.[A-Za-z0-9\-_]{8,}\."
        r"|\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,110}\b")

    def _text(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8-sig")

    def _tree(self, rel):
        return ast.parse(self._text(rel), filename=rel, feature_version=(3, 9))

    def test_all_python_modules_parse_under_python39(self):
        present = [rel for rel in self.PY_MODULES if (ROOT / rel).exists()]
        # 少一个文件不该静默跳过：登记表里写了就必须在库里。
        self.assertEqual(present, list(self.PY_MODULES))
        for rel in self.PY_MODULES:
            self._tree(rel)

    def test_access_policy_admins_stay_the_declared_four(self):
        """ADMINS 决定全站写权限。名单一改就等于改了「谁能改线上」，
        必须是显式改这个文件、而不是被某次回滚悄悄改掉。"""
        policy = module("fast_access_policy", self.POLICY + "access_policy.py")
        self.assertEqual(policy.ADMINS, frozenset(("wulv", "chenchao", "DY", "fstech")))

    def test_access_policy_denies_write_for_non_admin(self):
        """非管理员：写方法一律 403，控制类动词（含 query 里的 action=）也 403。"""
        policy = module("fast_access_policy2", self.POLICY + "access_policy.py")
        self.assertEqual(policy.authorize("reg:abc", "POST", "/dashboard/tasks"), 403)
        self.assertEqual(policy.authorize("someone", "GET", "/dashboard/tasks?action=deploy"), 403)
        self.assertEqual(policy.authorize("someone", "GET", "/dashboard/admin/panel"), 403)
        self.assertEqual(policy.authorize("", "GET", "/dashboard/tasks"), 401)
        self.assertEqual(policy.authorize("chenchao", "POST", "/dashboard/tasks"), 200)
        # 唯一被放行的写路径：任务台原生编辑器的那条 PATCH（且只给非 reg: 身份，
        # reg: 注册账号的模块权限由任务台自己按模块判，网关不替它开口子）。
        self.assertEqual(policy.authorize("someone", "PATCH", "/dashboard/tasks/api/green-plan/tasks/G1"), 200)
        self.assertEqual(policy.authorize("reg:x", "PATCH", "/dashboard/tasks/api/green-plan/tasks/G1"), 403)
        self.assertEqual(policy.authorize("someone", "PATCH", "/dashboard/tasks/api/other/G1"), 403)

    def test_auth_portal_binds_loopback_and_no_longer_bridges_fc_cookies(self):
        """登录门禁只挂 127.0.0.1；且外部 FC 会话不能再被提升为 dashboard 身份
        （`_verify_fc_read` / fc_read_scope 是已删除的旧桥，回归即等于权限串门）。"""
        text = self._text(self.AUTH + "auth_portal.py")
        self.assertIn('"bind":       _env("AUTH_BIND") or "127.0.0.1"', text)
        self.assertIn('_env_int("AUTH_PORT", 8895)', text)
        self.assertNotIn("_verify_fc_read", text)
        self.assertNotIn("from fc_read_scope import", text)

    def test_iggm_crawlers_keep_the_ssrf_guard(self):
        """三个抓取器都必须走 url_guard 的安全 opener —— 否则「抓个价格」就成了
        任意地址请求代理（内网 169.254 / 127.0.0.1 / file:// 全通）。"""
        for rel in (self.IGGM + "core.py", self.IGGM + "core_aoeah.py", self.IGGM + "core_u4gm.py"):
            text = self._text(rel)
            self.assertIn("from url_guard import safe_opener, parsed_destination", text)
            self.assertNotIn("urllib.request.build_opener(", text)
        self.assertIn("parsed_destination(", self._text(self.IGGM + "sites.py"))

    def test_mlb_side_lanes_run_as_child_processes(self):
        """写卡（要 ddddocr）与取价都在子进程里跑，主服务保持零第三方依赖；
        中间产物落在 data/ 下，不许污染 files/ 下载目录。"""
        server = self._text(self.MLB + "mlb_server.py")
        self.assertIn("import mlb_writeback as WB", server)
        self.assertIn("import mlb_coins_rate as CR", server)
        self.assertIn('WB_WORKDIR = os.path.join(HERE, "data", "writeback")', server)
        self.assertIn('RATE_DIR = os.path.join(HERE, "data", "pricing")', server)
        self.assertIn("subprocess.run(", self._text(self.MLB + "mlb_writeback.py"))

    def test_nba_backend_keeps_token_auth_and_loopback_default(self):
        """改价后端能直写商品价格 ⇒ 必须默认只听回环 + 令牌鉴权 + 状态目录不在源码树。"""
        server = self._text(self.NBA + "backend/server.js")
        self.assertIn("const BIND_HOST = process.env.BIND_HOST || '127.0.0.1';", server)
        self.assertIn("server.listen(PORT, BIND_HOST", server)
        self.assertIn("x-access-token", server)
        self.assertIn("NBA_DATA_DIR_MUST_BE_OUTSIDE_SOURCE",
                      self._text(self.NBA + "backend/p2pah_api.py"))

    def test_taskboard_wires_green_plan_and_verifies_identity_by_itself(self):
        """任务台必须自己回查门禁（不信任客户端头），并初始化 green-plan 表。"""
        text = self._text(self.TASK + "taskboard_server.py")
        self.assertIn("green_plan.init(conn)", text)
        self.assertIn("def _registration_verified_identity(handler):", text)
        self.assertIn("identity header conflict", text)
        self.assertIn('X-Auth-User', text)

    def test_no_hardcoded_credentials_in_tracked_files(self):
        for rel in self.PY_MODULES:
            self.assertIsNone(self.CREDENTIAL.search(self._text(rel)),
                              "%s 里出现疑似凭据" % rel)

class PlayersLock(unittest.TestCase):
    def test_missing_and_symlink_are_not_acquired(self):
        lock=module("fast_players_lock","fc27_players_cloud/player_web/price_lock.py")
        with tempfile.TemporaryDirectory() as tmp:
            missing=Path(tmp)/"missing"
            with lock.shared_price_lock(missing) as held:self.assertFalse(held)
            real=Path(tmp)/"lock";real.touch()
            link=Path(tmp)/"link";link.symlink_to(real)
            with lock.shared_price_lock(link) as held:self.assertFalse(held)
    def test_same_inode_exclusion_and_release(self):
        lock=module("fast_players_lock","fc27_players_cloud/player_web/price_lock.py")
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"lock";path.touch()
            with lock.shared_price_lock(path) as one:
                self.assertTrue(one)
                with lock.shared_price_lock(path) as two:self.assertFalse(two)
            with lock.shared_price_lock(path) as held:self.assertTrue(held)

class CurrentSupersession(unittest.TestCase):
    def setUp(self):
        current=ROOT/"candidates/fc-coins/player-supersession-20261007-v4-2-3/source"
        historical=ROOT/"candidates/fc-coins/player-supersession-20261007-v4-2"
        # Historical fixture supplies synthetic values only; tested implementation is current.
        sys.path[:0]=[str(current),str(historical/"tests")]
        self.impl=module("fast_current_supersede",str(current.relative_to(ROOT)/"supersede.py"))
        import test_supersession_increment as fixture
        self.fx=fixture.SupersessionTests();self.fx.setUp()
        self.audit=json.loads(self.fx.store.live["executions/"+self.fx.cid+".json"])
        ledger=json.loads(self.fx.store.live["all-coin-sync/"+self.fx.cid+".json"])
        self.approved=self.impl.approved_tiers(ledger,self.audit,self.fx.scope)
    def validate(self):
        f=self.fx
        return self.impl.validate_supersession_round(f.scope,f.ledger,f.job,self.audit,f.policy,f.proof,f.now,self.approved)
    def change_inputs(self):
        for sample in self.fx.proof["samples"]:
            sample["model_inputs"]["coefficient"]="1.2"
            for part in sample["public_readback"]:
                p=part["platform"]
                sample["model_inputs"][p]="20000"
                part["our_price_coins"]="20000";part["coefficient"]="1.2"
                target=Decimal("20")*Decimal(self.fx.proof["expected_rates"][p])*Decimal("1.2")
                part["target_usd"]=str(target)
                part["backend_match"]=abs(Decimal(part["backend_usd"])-target)<=Decimal(".001")
                part["public_match"]=abs(Decimal(part["public_usd"])-target)<=Decimal(".001")
    def test_current_valid_proof(self):self.assertTrue(self.validate())
    def test_current_input_update_not_historical_plan_replay(self):
        before=copy.deepcopy(self.fx.ledger["sample_before"])
        self.change_inputs()
        self.assertTrue(self.validate())
        self.assertEqual(self.fx.ledger["sample_before"],before)
    def test_model_public_mismatch_rejected(self):
        self.change_inputs()
        self.fx.proof["samples"][0]["model_inputs"]["PS"]="999"
        with self.assertRaisesRegex(ValueError,"player_inputs_changed"):self.validate()
    def test_identity_and_provenance_rejected(self):
        self.fx.proof["samples"][0]["products"][0]["id"]=999
        with self.assertRaisesRegex(ValueError,"linked_identity_changed"):self.validate()
        self.setUp();self.fx.proof["read_only"]=False
        with self.assertRaisesRegex(ValueError,"proof_origin_changed"):self.validate()
    def test_original_failure_evidence_preserved(self):
        f=self.fx;before=copy.deepcopy(f.store.live)
        after=self.impl.supersession_after(f.scope,before,[f.proof],f.now.isoformat(),"a"*64,"/synthetic/backup")
        for key,value in after.items():
            old=json.loads(before[key]);new=json.loads(value)
            self.assertEqual(new["status"],"superseded")
            self.assertTrue(new["supersession"]["needs_fresh_auto_cycle"])
            for field in ("error","error_detail","result","stage","completed_at"):
                self.assertEqual(old.get(field),new.get(field))
