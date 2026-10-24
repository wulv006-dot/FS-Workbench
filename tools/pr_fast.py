"""One offline affected-test dispatcher. Unmapped code fails explicitly."""
import ast, io, json, os, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

#: 已在版本库里的 6 个 /opt 运营模块。它们不走 releases/ 的按批次分组，
#: 统一归 ops-modules（见 select 与 pr_fast_tests.OpsModuleContracts）。
OPS_MODULE_PATHS = (
    "opt/auth-portal/",          # 统一登录门禁 / 白名单告警
    "opt/fs-access-policy/",     # 全站写权限名单
    "opt/iggm-web/",             # IGGM/AOEAH/U4GM 抓取 Web 版
    "opt/mlb-online/",           # MLB 上架工作台（含写卡桥 + 取价）
    "opt/nba-reprice/",          # NBA 2K27 改价后端
    "opt/mmoexp-taskboard/",     # 任务台（含 green_plan）
)

def require_success(result):
    if result.testsRun <= 0 or not result.wasSuccessful() or result.skipped:
        raise RuntimeError("required_tests_failed_or_empty_or_skipped")

def units(directory, names, root_owned=False):
    # Each group runs in a fresh interpreter: avoid module-name/path collisions.
    code = """
import io,json,socket,subprocess,sys,unittest
import unittest.mock
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/sys.argv[2]),str(root)]
sys.path.append(str(root/'releases/fs-dashboard/user-analytics-20261022/source'))
real=socket.socket.connect
def local(self,address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
        raise AssertionError('offline_test_external_network')
    return real(self,address)
socket.socket.connect=local
def reject(*a,**k):raise AssertionError('offline_test_external_process')
subprocess.Popen=reject
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sys.argv[3:])
r=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'testsRun':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped)}))
sys.exit(0 if r.testsRun>0 and r.wasSuccessful() and not r.skipped else 1)
"""
    prefix=[]
    if root_owned:
        # The publisher requires root-owned staging; reproduce it inside the disposable CI checkout.
        subprocess.run(["sudo","chown","-R","0:0",str(ROOT/directory)],check=True,timeout=30)
        prefix=["sudo"]
    subprocess.run(prefix+[sys.executable,"-I","-B","-c",code,str(ROOT),directory]+names,check=True,timeout=90,cwd=ROOT)

def node(path):
    subprocess.run(["node",str(ROOT/path)],cwd=(ROOT/path).parent,check=True,timeout=30)

def browser_python(path):
    subprocess.run([sys.executable,"-I","-B",str(ROOT/path)],cwd=(ROOT/path).parent,check=True,timeout=45)

def css_structure(text):
    # Structural sanity only, not CSS standards validation or visual acceptance.
    stack=[];quote=None;comment=False;escape=False;i=0
    while i<len(text):
        char=text[i];pair=text[i:i+2]
        if comment:
            if pair=="*/":comment=False;i+=2;continue
        elif quote:
            if escape:escape=False
            elif char=="\\":escape=True
            elif char==quote:quote=None
        elif pair=="/*":comment=True;i+=2;continue
        elif char in ("'",'"'):quote=char
        elif char in "({[":stack.append(char)
        elif char in ")}]":
            if not stack or stack.pop()!=dict(zip(")}]","({["))[char]:
                raise RuntimeError("css_unbalanced_delimiter")
        i+=1
    if stack or quote or comment:raise RuntimeError("css_unclosed_structure")

def frontend_structure(name,text):
    if Path(name).suffix==".css":css_structure(text);return
    from html.parser import HTMLParser
    class Tags(HTMLParser):
        void=set("area base br col embed hr img input link meta param source track wbr".split())
        optional=set("li p dt dd rt rp optgroup option thead tbody tfoot tr td th colgroup".split())
        blocks=set("address article aside blockquote div dl fieldset footer form h1 h2 h3 h4 h5 h6 header hr main nav ol p pre section table ul".split())
        def __init__(self):super().__init__();self.stack=[];self.styles=[]
        def handle_starttag(self,tag,attrs):
            if self.stack and self.stack[-1]=="p" and tag in self.blocks:self.stack.pop()
            if self.stack and tag in self.optional and self.stack[-1]==tag:self.stack.pop()
            if tag not in self.void:self.stack.append(tag)
        def handle_startendtag(self,tag,attrs):
            if tag in self.void:return
            # Foreign-content self-closing syntax is valid; HTML non-void slash is ignored.
            if tag in ("svg","math") or any(t in ("svg","math") for t in self.stack):return
            self.handle_starttag(tag,attrs)
        def handle_endtag(self,tag):
            if tag in self.void:return
            while self.stack and self.stack[-1]!=tag and self.stack[-1] in self.optional:self.stack.pop()
            if not self.stack or self.stack.pop()!=tag:raise RuntimeError("html_tag_mismatch:"+tag)
        def handle_data(self,data):
            if self.stack and self.stack[-1]=="style":self.styles.append(data)
    tags=Tags();tags.feed(text)
    if tags.rawdata.startswith("<"):raise RuntimeError("html_incomplete_tag")
    tags.close()
    if any(tag not in tags.optional for tag in tags.stack):raise RuntimeError("html_unclosed_tag")
    for style in tags.styles:css_structure(style)

def require_changed_file(name,exists):
    if not exists and Path(name).suffix in (".html",".css"):
        raise RuntimeError("UNMAPPED_DELETION: register an affected consumer check before removing "+name)

def rename_source_selfcheck():
    # Exercise the actual workflow producer against a temporary offline Git history.
    import shlex, tempfile
    line=next(line.strip() for line in (ROOT/".github/workflows/pr-fast.yml").read_text().splitlines()
              if line.strip().startswith("git diff "))
    command=shlex.split(line.split(" > ",1)[0])
    pairs=[("ui/a.html","ui/b.html"),("ui/a.css","ui/b.css"),
           ("ops/schema.sql","notes/schema.txt"),("ops/worker.service","notes/worker.txt"),
           ("ops/worker.timer","notes/timer.txt"),
           (".github/workflows/old.yml","notes/workflow.md"),
           (".github/workflows/old.yaml","notes/workflow-yaml.md"),
           ("docs/old doc.md","docs/new doc.md"),
           ("ui/old\npage.html","ui/new\npage.html")]
    with tempfile.TemporaryDirectory(prefix="pr-fast-rename-") as directory:
        root=Path(directory)
        def git(*args,data=None):
            return subprocess.check_output(["git","-c","user.name=Offline QA",
                "-c","user.email=qa@example.invalid","-c","commit.gpgsign=false",
                "-c","core.hooksPath=/dev/null",*args],cwd=root,stderr=subprocess.STDOUT,input=data)
        git("init","-q")
        def snapshot(files,parent=None):
            # Git paths admit newline bytes that Windows working-tree filenames cannot represent.
            tree={}
            for name,content in files.items():
                node=tree
                parts=name.split('/')
                for part in parts[:-1]:node=node.setdefault(part,{})
                node[parts[-1]]=content.encode()
            def emit(node):
                rows=[]
                for name,value in sorted(node.items()):
                    kind,mode,sha=('tree','040000',emit(value)) if isinstance(value,dict) else (
                        'blob','100644',git('hash-object','-w','--stdin',data=value).decode().strip())
                    rows.append((mode+' '+kind+' '+sha+'\t').encode()+name.encode()+b'\0')
                return git('mktree','-z',data=b''.join(rows)).decode().strip()
            args=['commit-tree',emit(tree),'-m','synthetic workflow input']
            if parent:args+=['-p',parent]
            return git(*args).decode().strip()
        before={old:'unique fixture '+str(i)+'\n' for i,(old,new) in enumerate(pairs)}
        after={new:before[old] for old,new in pairs}
        before['fc27_quote_engine.py']='VALUE=1\n';after['fc27_quote_engine.py']='VALUE=2\n'
        base=snapshot(before);head=snapshot(after,base)
        command=[base if token=="$PR_BASE" else head if token=="$PR_HEAD" else token for token in command]
        paths=subprocess.check_output(command,cwd=root).decode("utf-8").rstrip("\0").split("\0")
        expected={name for pair in pairs for name in pair}|{"fc27_quote_engine.py"}
        if set(paths)!=expected:raise RuntimeError("rename_source_omitted_by_workflow")
        for old,new in pairs:
            if Path(old).suffix in (".html",".css"):
                try:require_changed_file(old,(root/old).exists())
                except RuntimeError as error:
                    if "UNMAPPED_DELETION" not in str(error):raise
                else:raise RuntimeError("rename_source_deletion_allowed")
            elif not old.startswith("docs/"):
                try:select([old,new])
                except RuntimeError as error:
                    if "UNMAPPED" not in str(error):raise
                else:raise RuntimeError("rename_source_runtime_coverage_allowed")
        if select(list(pairs[7])) or select(["fc27_quote_engine.py"])!=["engine"]:
            raise RuntimeError("ordinary_change_scope_regression")
    print("rename source selfcheck: actual workflow reports both paths; frontend removal/runtime coverage reject; docs rename and ordinary edit retain scope")

def selfcheck():
    if select(['tools/hermes_review_archive.py', 'knowledge/reviewed/fixture/record.json']) != ['hermes-review-archive']:
        raise RuntimeError('review_archive_mapping_missing')
    if select(["releases/ops/madden-browser-isolation-20261023/source/browser_runtime.py"]) != ["madden-browser-isolation"]:
        raise RuntimeError("madden_browser_isolation_mapping_missing")
    if select(["releases/ops/fc-reference-observer-ui-20261023/ui/source/fc27_cloud_api.py","releases/ops/fc-reference-observer-ui-20261023/trigger/source/observe.py"]) != ["fc-reference-observer-ui"]:
        raise RuntimeError("fc_reference_observer_ui_mapping_missing")
    if select(["releases/ops/fc-itemd2r-shadow-20261023/observer/source/observe.py","releases/ops/fc-itemd2r-shadow-20261023/shadow/source/reference_shadow.py"]) != ["fc-price-shadow"]:
        raise RuntimeError("fc_price_shadow_mapping_missing")
    if select(['releases/ops/pricing-followup-20261023/alerts/source/watch.py','releases/ops/pricing-followup-20261023/order/query_read.py','releases/ops/pricing-followup-20261023/browser/source/start.sh']) != ['pricing-followup']:
        raise RuntimeError('pricing_followup_mapping_missing')
    if select(['releases/ops/pricing-recovery-20261023/fc_lifecycle/source/browser_lifecycle.py',
               'releases/ops/pricing-recovery-20261023/fc_residency/source/lootbar_server_collector.py',
               'releases/ops/pricing-recovery-20261023/rpg/prepare_candidate.py',
               'releases/ops/pricing-recovery-20261023/order/service.py']) != ['pricing-recovery']:
        raise RuntimeError('pricing_recovery_mapping_missing')
    if select(["releases/fs-dashboard/user-analytics-20261022/source/user_query.py"]) != ["user-analytics"]:
        raise RuntimeError("user_analytics_checks_missing")
    if select(["releases/fs-dashboard/game-monitor-autopublish-20261022/source/controller.py"]) != ["game-monitor-auto"]:
        raise RuntimeError("game_monitor_auto_checks_missing")
    if select(["releases/fs-dashboard/game-monitor-sop-20261022/source/index.html"]) != ["game-monitor-sop"]:
        raise RuntimeError("game_monitor_sop_checks_missing")
    if select(["releases/fc-coins/fc-pricing-v2-20261022/source/pricing_v2.py"]) != ["fc-pricing-v2"]:
        raise RuntimeError("fc_pricing_v2_checks_missing")
    if select(['releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py']) != ['fc-pricing-v2','hermes-conversation']:
        raise RuntimeError('fc_conversation_consumers_missing')
    if select(["releases/fs-dashboard/hermes-server-unify-20261022/fs_readonly/__init__.py"]) != ["hermes-server-unify"]:
        raise RuntimeError("hermes_server_unify_checks_missing")
    if select(['releases/fs-dashboard/hermes-memory-approval-20261022/review_queue.py']) != ['hermes-memory-approval']:
        raise RuntimeError('hermes_skill_approval_checks_missing')
    if select(['releases/fs-dashboard/hermes-memory-approval-20261022/reviewed_skills.py']) != ['hermes-memory-approval','hermes-server-unify','knowledge-layering']:
        raise RuntimeError('hermes_reviewed_skill_consumers_missing')
    if select(['tools/prepare_learning_native_release.py']) != ['hermes-learning-closure']:
        raise RuntimeError('hermes_learning_native_producer_checks_missing')
    if select(['tools/prepare_learning_release.py']) != ['hermes-learning-closure']:
        raise RuntimeError('hermes_learning_fs_producer_checks_missing')
    if select(["releases/fs-dashboard/fc-coins-workflow-20261022/source/pricing_workflow.py"]) != ["fc-coins-workflow"]:
        raise RuntimeError("coins_workflow_checks_missing")
    if select(["releases/fs-dashboard/fc-coins-evidence-20261021/source/coins_evidence.py"]) != ["fc-coins-evidence"]:
        raise RuntimeError("coins_evidence_checks_missing")
    if select(["releases/fs-dashboard/business-procurement-20261022/source/business.js"]) != ["business-procurement"]:
        raise RuntimeError("business_procurement_checks_missing")
    if select(["releases/fs-dashboard/channel-effects-20261021/source/channel_effects.py"]) != ["channel-effects"]:
        raise RuntimeError("channel_effects_checks_missing")
    if select(["rea_admin_contract_20261021/monthly_paid.py"]) != ["admin-monthly-paid"]:
        raise AssertionError("monthly paid checks not selected")
    if select(["admin_session_continuity_20261021/session_state.py"]) != ["admin-session-continuity"]:
        raise RuntimeError("admin_continuity_affected_tests_missing")
    if select(["order_global_session_20261021/service.py"]) != ["order-global-session"]:
        raise RuntimeError("order_global_affected_tests_missing")
    if select(["shared_backend_session/shared_admin.py"]) != ["admin-single-owner"]:
        raise RuntimeError("shared_admin_affected_tests_missing")
    if select(['releases/fc-sbc/security-20261015/source/webapp.py'])!=['fc-sbc-security']:
        raise RuntimeError('SBC security checks missing')
    if select(['releases/fs-dashboard/hermes-report-tracks-20261015/source/pricing_report.py'])!=['hermes-report-tracks']:
        raise AssertionError('report track release must run affected checks')
    if select(['releases/fs-dashboard/hermes-fs-research-integration-20261015/source/official_intelligence.py'])!=['hermes-fs-research-integration']:
        raise RuntimeError('hermes_research_integration_mapping_missing')
    if select(['releases/fs-dashboard/hermes-conversation-20261018/source/conversation_store.py'])!=['hermes-conversation']:
        raise RuntimeError('hermes_conversation_mapping_missing')
    class Good(unittest.TestCase):
        def runTest(self):self.assertTrue(True)
    class Bad(unittest.TestCase):
        def runTest(self):self.fail("synthetic_failure")
    class Error(unittest.TestCase):
        def runTest(self):raise ValueError("synthetic_error")
    class Skip(unittest.TestCase):
        def runTest(self):self.skipTest("required_skip")
    runner=unittest.TextTestRunner(stream=io.StringIO())
    require_success(runner.run(Good()))
    for suite in (Bad(),Error(),Skip(),unittest.TestSuite()):
        try:require_success(runner.run(suite))
        except RuntimeError:continue
        raise RuntimeError("failure_propagation_selfcheck_failed")
    for paths in (["index.html"],["styles.css"],["index.html","README.md"]):
        if select(paths)!=["frontend"]:raise RuntimeError("frontend_path_not_checked")
    if select(["styles.css","fc27_quote_engine.py"])!=["engine","frontend"]:
        raise RuntimeError("mixed_frontend_path_not_checked")
    for name,text in (("ok.html","<main><p>ok</p><input><br/></main>"),
                      ("ok.html","<ul><li>a<li>b</ul>"),
                      ("ok.html","<div/></div>"),
                      ("ok.html","<svg><path d='M0 0'/></svg>"),
                      ("ok.css",'a{content:"}";color:var(--color)}'),
                      ("ok.css","/* { */ @media (width > 10px){a:hover{color:red}}")):
        frontend_structure(name,text)
    for name,text in (("bad.html","<div>"),("bad.html","<div></span>"),
                      ("bad.html","<div/>"),
                      ("bad.html","<style>a{color:red</style>"),
                      ("bad.css","a{color:red"),("bad.css","a{content:'oops}"),
                      ("bad.css","a{} /* unfinished")):
        try:frontend_structure(name,text)
        except RuntimeError:continue
        else:raise RuntimeError("malformed_frontend_structure_allowed")
    for name in ("schema.sql","worker.service","worker.timer",".github/workflows/new.yml",".github/workflows/new.yaml"):
        try:select([name])
        except RuntimeError as error:
            if "UNMAPPED" not in str(error):raise
        else:raise RuntimeError("unchecked_runtime_format_allowed:"+name)
    for name in ("removed.html","removed.css"):
        try:require_changed_file(name,False)
        except RuntimeError as error:
            if "UNMAPPED_DELETION" not in str(error):raise
        else:raise RuntimeError("unchecked_frontend_deletion_allowed")
        require_changed_file(name,True)
    require_changed_file("old-record.md",False)
    for name in ("fc27_ops_cloud/index.html","fc27_ops_cloud/data/fc-analytics.css"):
        frontend_structure(name,(ROOT/name).read_text(encoding="utf-8"))
    for path in ("source/game-monitor/index.html", "source/management/targets.json", "backend/boss_insights.py", "tests/management_polling.cjs"):
        if select(["releases/fs-dashboard/boss-workspaces-20261013/"+path]) != ["fs-boss-workspaces"]:
            raise RuntimeError("fs_boss_workspaces_scope_missing")
    if select(["releases/fs-dashboard/ai-advisor-20261013/deep/source/fc_deep_service.py"]) != ["fc-deep-advisor"]:
        raise RuntimeError("fc_deep_advisor_scope_missing")
    for path in ("controller.py","fs-hermes-fc.service","shared_candidate/range_api.py","skills/manifest.json"):
        if select(["releases/fs-dashboard/hermes-fc-pilot-20261013/"+path]) != ["hermes-fc-pilot"]:
            raise RuntimeError("hermes_scope_missing")
    if select(["README.md"]) or select(["tools/pr_fast.py"])!=["self"]:
        raise RuntimeError("docs_or_dispatcher_scope_changed")
    if select(["releases/auth/admin-entry-20261009/source/shell.js"]) != ["admin-entry"]:
        raise RuntimeError("admin_entry_scope_missing")
    if select(["mlb_admin_import_20261012/src/mlb_write_cards.py"]) != ["mlb-admin"]:
        raise RuntimeError("mlb_admin_scope_missing")
    if select(["mlb_admin_import_20261012/evidence/capture_20261012/entry.js"]) != ["mlb-admin"]:
        raise RuntimeError("mlb_admin_evidence_scope_missing")
    if select(["mlb_admin_import_20261012/tests/test_admin_write_channel.py"]) != ["mlb-admin"]:
        raise RuntimeError("mlb_admin_test_scope_missing")
    if select(["fc27_pack_bundles_20261013/src/pack_bundles_server.py"]) != ["fc27-pack-bundles"]:
        raise RuntimeError("fc27_pack_bundles_scope_missing")
    if select(["releases/fc-coins/lock-gate-hardening-20261013/source/coin_all_sync_job.py"]) != ["fc-lock-gate-hardening"]:
        raise RuntimeError("fc_hardening_mapping_missing")
    if select(["releases/fc-coins/gate-cycle-20261014/source/automation_policy.py"]) != ["fc-cycle-gate"]:
        raise RuntimeError("fc_cycle_gate_mapping_missing")
    if select(["releases/fc-coins/order-public-acceptance-20261013/source/report.py"]) != ["fc-order-public"]:
        raise RuntimeError("fc_order_public_mapping_missing")
    if select(["releases/fc-coins/coin-all-readback-retry-20261014/source/coin_all_sync_job.py"]) != ["fc-coin-all-readback-retry"]:
        raise RuntimeError("fc_coin_all_readback_retry_scope_missing")
    if select(["releases/fc-coins/coin-all-readback-retry-20261014/test_readback_retry.py"]) != ["fc-coin-all-readback-retry"]:
        raise RuntimeError("fc_coin_all_readback_retry_test_scope_missing")
    if select(["releases/fc-coins/coin-competitor-grid-20261015/source/fc27-quote-cloud.js"]) != ["fc-coin-competitor-grid"]:
        raise RuntimeError("fc_coin_competitor_grid_scope_missing")
    if select(["releases/fc-coins/coin-competitor-grid-20261015/tests/test_competitor_grid.cjs"]) != ["fc-coin-competitor-grid"]:
        raise RuntimeError("fc_coin_competitor_grid_test_scope_missing")
    if select(["releases/fc-coins/coin-competitor-grid-20261015/source/fc27-coins.html"]) != ["frontend"]:
        raise RuntimeError("fc_coin_competitor_grid_html_scope_changed")
    if select(["releases/fc-coins/coin-competitor-grid-20261015/baseline/fc27-quote-cloud.js"]) != ["fc-coin-competitor-grid"]:
        raise RuntimeError("fc_coin_competitor_grid_baseline_scope_missing")
    if select(["fc27_pack_bundles_20261013/vendor/p2pah_price.py"]) != ["fc27-pack-bundles"]:
        raise RuntimeError("fc27_pack_bundles_vendor_scope_missing")
    if select(["fc27_pack_bundles_20261013/tests/test_write_flow.py"]) != ["fc27-pack-bundles"]:
        raise RuntimeError("fc27_pack_bundles_test_scope_missing")
    if select(["共享资源/MLB新卡上架/server/mlb_server.py"]) != ["mlb-shelf-tool"]:
        raise RuntimeError("mlb_shelf_tool_scope_missing")
    if select(["共享资源/MLB新卡上架/deploy/install_mlb.sh"]) != ["mlb-shelf-tool"]:
        raise RuntimeError("mlb_shelf_tool_sh_scope_missing")
    if select(["共享资源/MLB新卡上架/client/启动执行器.bat"]) != ["mlb-shelf-tool"]:
        raise RuntimeError("mlb_shelf_tool_bat_scope_missing")
    if select(["releases/registration/account-management-20261009/source/web/app.js"]) != ["registration-management"]:
        raise RuntimeError("registration_management_scope_missing")
    if select(["releases/fs-dashboard/admin-main-20261009/assets/shell.js"]) != ["fs-admin-view"]:
        raise RuntimeError("fs_admin_view_mapping_missing")
    if select(["releases/fc-coins/lootbar-spec-repair-20261009/fc27_chrome_collector/lootbar_server_collector.py"]) != ["fc-lootbar"]:
        raise RuntimeError("lootbar_mapping_missing")
    for path,group in [("releases/fc-coins/browser-readiness-20261016/fc27_chrome_collector/lootbar_server_collector.py","fc-browser-readiness"),("releases/fc-coins/result-read-20261016/source/fc27-quote-cloud.js","fc-result-read"),("releases/fs-dashboard/business-refresh-20261016/source/live_summary.py","fs-business-refresh"),("fc27_players_cloud/player_web/main.py","fc-players-cloud10"),("releases/fs-dashboard/deployed-source-backfill-20261017/test_inventory.py","deployed-source-backfill")]:
        if select([path]) != [group]:raise RuntimeError("deployed_source_mapping_missing:"+path)
    for path in ("fc27_players_cloud/player_web/shared_session.py","fc27_players_cloud/tests_cloud/test_shared_session.py","releases/fc-players/shared-login-20261018/source/session/fc27-p2pah-session.service"):
        if select([path]) != ["fc-players-shared-login"]:raise RuntimeError("shared_login_mapping_missing:"+path)
    if select(["releases/fc-players/history-five-20261024/source/player_web/static/app.js"]) != ["fc-players-history-five"]:raise RuntimeError("players_history_mapping_missing")
    if select(["releases/fc-coins/prewrite-recovery-20261012/source/monitor/read_only_status.py"]) != ["fc-prewrite"]:
        raise RuntimeError("fc_prewrite_scope_missing")
    if select(["releases/fc-coins/noncore-emergency-20261009/source/fc27_quote_engine.py"]) != ["fc-noncore"]:
        raise RuntimeError("fc_noncore_scope_missing")
    if select(["releases/fc-coins/public-readback-retry-20261009/fc27_cloud_browser/fc27_cloud_worker.py"]) != ["fc-public-readback"]:
        raise RuntimeError("fc_public_readback_scope_missing")
    if select(["releases/fc-coins/coupon-consistency-20261009/fc27_cloud_browser/snapshot_layer.py"]) != ["fc-coupon-consistency"]:
        raise RuntimeError("fc_coupon_consistency_scope_missing")
    if select(["releases/fc-coins/coupon-parity-doc-20261009/release/source/lootbar_server_collector.py"]) != ["fc-coupon-parity-doc"]:
        raise RuntimeError("fc_coupon_parity_doc_scope_missing")
    if select(["releases/fs-dashboard/metrics-fix-20261009/assets/runtime.js"]) != ["fs-metrics-fix"]:
        raise RuntimeError("fs_metrics_fix_mapping_missing")
    # ops-modules 覆盖 6 个 /opt 模块；漏一条就等于放一条改动能不跑测试地进主干。
    for path in ("opt/auth-portal/auth_portal.py","opt/auth-portal/fs_ip_alert.py",
                 "opt/fs-access-policy/access_policy.py","opt/iggm-web/core.py",
                 "opt/mlb-online/mlb_writeback.py","opt/mmoexp-taskboard/green_plan.py",
                 "opt/nba-reprice/backend/server.js","opt/iggm-web/deploy/setup.sh"):
        if select([path]) != ["ops-modules"]:
            raise RuntimeError("ops_module_mapping_missing:"+path)
    for path in ("tests/test_fs_iam_rbac.py","tests/test_fs_iam_console.py","tests/test_fs_iam_password_request.cjs"):
        if select([path]) != ["iam"]:
            raise RuntimeError("iam_mapping_missing:"+path)
    if select(["opt/fs-access-policy/web/app.js"]) != ["iam","ops-modules"]:
        raise RuntimeError("iam_password_form_mapping_missing")
    if select(["opt/nba-reprice/backend/api_security.js"]) != ["nba","ops-modules"]:
        raise RuntimeError("nba_guard_mapping_regressed")
    if select(["opt/auth-portal/login.html"]) != ["frontend"]:
        raise RuntimeError("ops_module_html_must_stay_in_frontend")
    if select(["releases/fs-dashboard/traffic-yesterday-20261009/assets/business.js"]) != ["fs-period-ui"]:
        raise RuntimeError("fs_period_ui_mapping_missing")
    if select(["releases/fs-dashboard/hermes-report-theme-20261017/source/report.template.html"]) != ["hermes-report-theme"]:
        raise RuntimeError("hermes_report_theme_mapping_missing")
    if select(["releases/fs-dashboard/hermes-full-html-task-20261017/source/controller.py"]) != ["hermes-full-html"]:
        raise RuntimeError("hermes_full_html_mapping_missing")
    for area in ("source/controller.py","tests/test_workspace_evidence.py","frontend/data-workspace.js","skills/METHOD.md"):
        if select(["releases/fs-dashboard/hermes-data-workspace-20261018/"+area]) != ["hermes-data-workspace"]:
            raise RuntimeError("hermes_data_workspace_mapping_missing:"+area)
    for area in ("source/controller.py","tests/test_http_queries.py","deploy/prepare_release.py"):
        if select(["releases/fs-dashboard/hermes-generic-data-20261018/"+area]) != ["hermes-generic-data"]:
            raise RuntimeError("hermes_generic_data_mapping_missing:"+area)
    for area in ("source/customer_tracking.py","tests/test_customer_tracking.py","frontend/page.js","frontend/entry/brain.js","learning/CUSTOMER-METHOD.md","deploy/prepare_release.py"):
        if select(["releases/fs-dashboard/hermes-customer-tracking-20261018/"+area]) != ["hermes-customer-tracking"]:
            raise RuntimeError("hermes_customer_tracking_mapping_missing:"+area)
    print("path/structure selfcheck: HTML/CSS-only and mixed paths checked; valid/malformed examples and existing FC templates checked")
    print("coverage selfcheck: unmapped runtime formats/workflows and frontend deletions rejected; HTML non-void slash handled as open tag")
    rename_source_selfcheck()
    print("selfcheck: PASS and FAIL/error/skip/zero propagate correctly")

def select(paths):
    groups=set();unmapped=[]
    for name in paths:
        if name.startswith("releases/fc-players/history-five-20261024/"):
            groups.add("fc-players-history-five");continue
        if name == 'tools/hermes_review_archive.py' or name.startswith(('releases/fs-dashboard/hermes-review-archive-20261024/', 'knowledge/reviewed/')):
            groups.add('hermes-review-archive');continue
        if name.startswith("releases/ops/madden-browser-isolation-20261023/"):
            groups.add("madden-browser-isolation");continue
        if name.startswith('releases/fs-dashboard/hermes-memory-approval-20261022/'):
            groups.add('hermes-memory-approval')
            if name.endswith('/reviewed_skills.py'):groups.update(('knowledge-layering','hermes-server-unify'))
            continue
        if name.startswith('releases/fs-dashboard/hermes-learning-closure-20261023/') or name in ('tools/prepare_learning_native_release.py','tools/prepare_learning_release.py'):
            groups.add('hermes-learning-closure');continue
        if name.startswith("releases/ops/fc-reference-observer-ui-20261023/"):
            groups.add("fc-reference-observer-ui");continue
        if name.startswith("releases/ops/fc-itemd2r-shadow-20261023/"):
            groups.add("fc-price-shadow");continue
        if name.startswith("releases/fs-dashboard/campaign-analytics-20261023/"):
            groups.add("campaign-analytics");continue
        if name.startswith('releases/ops/pricing-followup-20261023/'):
            groups.add('pricing-followup');continue
        if name.startswith('releases/ops/pricing-recovery-20261023/'):
            groups.add('pricing-recovery');continue
        if name.startswith(('releases/fs-dashboard/knowledge-layering-20261023/', 'knowledge/')) or name in ('tools/knowledge_closeout.py','tools/prepare_knowledge_release.py','tools/prepare_native_knowledge_release.py'):
            groups.add('knowledge-layering');continue
        if name.startswith("releases/fs-dashboard/game-monitor-autopublish-20261022/"):
            groups.add("game-monitor-auto");continue
        if name.startswith("releases/fs-dashboard/game-monitor-sop-20261022/"):
            groups.add("game-monitor-sop");continue
        if name.startswith("rea_admin_contract_20261021/"):
            groups.add("admin-monthly-paid");continue
        if name.startswith("releases/fc-coins/fc-pricing-v2-20261022/"):
            groups.add("fc-pricing-v2")
            if name=='releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py':groups.add('hermes-conversation')
            continue
        if name.startswith("releases/fs-dashboard/fc-coins-workflow-20261022/"):
            groups.add("fc-coins-workflow");continue
        if name.startswith("releases/fs-dashboard/fc-coins-evidence-20261021/"):
            groups.add("fc-coins-evidence");continue
        if name.startswith("releases/fs-dashboard/daily-archive-20261021/"):
            groups.add("daily-archive");continue
        if name.startswith("releases/fs-dashboard/rs-adapter-20261024/"):
            groups.add("rs-business-adapter");continue
        if name.startswith("releases/fs-dashboard/business-procurement-20261022/"):
            groups.add("business-procurement");continue
        if name.startswith("releases/fs-dashboard/user-analytics-20261022/"):
            groups.add("user-analytics");continue
        if name.startswith("releases/fs-dashboard/channel-effects-20261021/"):
            groups.add("channel-effects");continue
        if name.startswith("admin_session_continuity_20261021/"):
            groups.add("admin-session-continuity");continue
        if name.startswith("order_global_session_20261021/"):
            groups.add("order-global-session");continue
        if name.startswith("shared_backend_session/") or (name.startswith("sales_shared_session_20261021/") and not (ROOT/name).exists()):
            groups.add("admin-single-owner");continue
        if name.startswith("releases/fs-dashboard/fs-business-baseline-20261021/"):
            groups.add("fs-business-baseline");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-simulation-learning-20261021/"):
            groups.add("hermes-v2-simulation-learning");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-ui-fit-20261021/"):
            groups.add("hermes-v2-ui-fit");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-learning-evidence-20261021/"):
            groups.add("hermes-v2-learning-evidence");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-strategy-permissions-20261021/"):
            groups.add("hermes-v2-strategy-permissions");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-strategy-20261021/"):
            groups.add("hermes-v2-strategy");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-review-repair-20261021/"):
            groups.add("hermes-v2-review-repair");continue
        if name.startswith("releases/fs-dashboard/hermes-v2-core-20261020/"):
            groups.add("hermes-v2-core");continue
        if name.startswith("releases/fs-dashboard/hermes-server-unify-20261022/"):
            groups.add("hermes-server-unify");continue
        if name.startswith("releases/fs-dashboard/hermes-ops-20261020/"):
            groups.add("hermes-ops");continue
        if name.startswith("releases/fs-dashboard/hermes-admin-recovery-20261020/"):
            groups.add("hermes-admin-recovery");continue
        if name.startswith("releases/fc-players/shared-login-20261018/") or name in ("fc27_players_cloud/player_web/shared_session.py","fc27_players_cloud/tests_cloud/test_shared_session.py"):
            groups.add("fc-players-shared-login");continue
        if name.startswith("releases/fs-dashboard/hermes-data-workspace-20261018/"):
            groups.add("hermes-data-workspace");continue
        if name.startswith("releases/fs-dashboard/hermes-conversation-20261018/"):
            groups.add("hermes-conversation");continue
        if name.startswith("releases/fs-dashboard/hermes-report-repair-20261019/"):
            groups.add("hermes-report-repair");continue
        if name.startswith("releases/fs-dashboard/hermes-customer-tracking-20261018/"):
            groups.add("hermes-customer-tracking");continue
        if name.startswith("releases/fs-dashboard/hermes-generic-data-20261018/"):
            groups.add("hermes-generic-data");continue
        if name.startswith("releases/fs-dashboard/admin-data-tools-20261018/"):
            groups.add("admin-data-tools");continue
        if name.startswith("releases/fs-dashboard/hermes-report-method-20261017/"):
            groups.add("hermes-report-method");continue
        if name.startswith("releases/fs-dashboard/hermes-full-html-task-20261017/"):
            groups.add("hermes-full-html");continue
        if name.startswith(("releases/fs-dashboard/hermes-followup-evidence-20261017/","releases/fs-dashboard/hermes-report-kind-actions-20261017/")):
            groups.add("hermes-report-compat");continue
        if name.startswith("releases/fs-dashboard/traffic-content-details-20261017/"):
            groups.add("traffic-content-details");continue
        if name.startswith("releases/fs-dashboard/hermes-report-theme-20261017/"):
            groups.add("hermes-report-theme");continue
        if name.startswith(("releases/fs-dashboard/traffic-hermes-20261017/","mmoexp_google_data/details/")) or name in ("mmoexp_google_data/dashboard_module/marketing-module.js","mmoexp_google_data/dashboard_module/build_module.py"):
            groups.add("traffic-hermes");continue
        if name=="ui-system/modules/native/google.js":groups.add("traffic-hermes")
        if name.startswith("releases/fc-sbc/security-20261015/"):
            groups.add("fc-sbc-security");continue
        suffix=Path(name).suffix
        if name.startswith("releases/fs-dashboard/management-quality-20261016/"):
            groups.add("management-quality");continue
        if name.startswith("releases/fs-dashboard/hermes-learning-loop-20261016/"):
            groups.add("hermes-learning-loop");continue
        if name.startswith("releases/fs-dashboard/desktop-learning-20261016/"):
            groups.add("desktop-learning");continue
        if name.startswith("releases/fs-dashboard/management-v2-20261015/"):
            groups.add("fs-management-v2");continue
        if name.startswith(("ui-system/", "releases/fs-dashboard/ui-system-20261015/")):
            groups.add("fs-ui-system");continue
        if name.startswith("releases/fs-dashboard/hermes-weekly-upgrade-20261015/"):
            groups.add("hermes-weekly-upgrade");continue
        if name.startswith("releases/fs-dashboard/news-weekly-schedule-20261016/"):
            groups.add("news-weekly-schedule");continue
        if name.startswith("releases/fs-dashboard/game-monitor-news-cards-20261016/"):
            groups.add("game-monitor-news-cards");continue
        if name.startswith("releases/fs-dashboard/mmoexp-news-integration-20261016/"):
            groups.add("mmoexp-news");continue
        if name.startswith("releases/fs-dashboard/hermes-report-import-20261015/"):
            groups.add("hermes-report-import");continue
        if name.startswith("releases/fs-dashboard/hermes-report-tracks-20261015/"):
            groups.add("hermes-report-tracks");continue
        if name.startswith("releases/fs-dashboard/hermes-fs-research-integration-20261015/"):
            groups.add("hermes-fs-research-integration");continue
        if name.startswith("releases/fs-dashboard/hermes-market-sources-20261015/"):
            groups.add("hermes-market-sources");continue
        if name.startswith("releases/fs-dashboard/hermes-report-filter-race-20261015/"):
            groups.add("hermes-report-filter-race");continue
        if name.startswith("releases/fs-dashboard/hermes-shared-reports-20261015/"):
            groups.add("hermes-shared-reports");continue
        if name.startswith("releases/fs-dashboard/hermes-fs-config-isolation-20261015/"):
            groups.add("hermes-fs-config-isolation");continue
        if name.startswith("releases/fs-dashboard/hermes-report-actions-20261015/"):
            groups.add("hermes-report-actions");continue
        if name.startswith("releases/fs-dashboard/hermes-desktop-20261015/"):
            groups.add("hermes-desktop");continue
        if name.startswith("releases/fs-dashboard/hermes-report-quality-20261015/"):
            groups.add("hermes-report-quality");continue
        if name.startswith("releases/fs-dashboard/menu-cache-20261015/"):
            groups.add("fs-menu-cache");continue
        if name.startswith("releases/fs-dashboard/navigation-recovery-20261015/"):
            groups.add("navigation-recovery");continue
        if name.startswith("releases/fs-dashboard/fs-revision-20261015/"):
            groups.add("fs-revision-20261015");continue
        if name.startswith("releases/fs-dashboard/deployed-source-backfill-20261017/"):
            groups.add("deployed-source-backfill");continue
        if name.startswith("releases/fc-coins/browser-readiness-20261016/"):
            groups.add("fc-browser-readiness");continue
        if name.startswith("releases/fc-coins/result-read-20261016/"):
            groups.add("fc-result-read");continue
        if name.startswith("releases/fs-dashboard/business-refresh-20261016/"):
            groups.add("fs-business-refresh");continue
        if name.startswith("releases/fc-ops/active-frontend-20261017/"):
            groups.add("deployed-source-backfill");continue
        if name in ("fc27_players_cloud/player_web/existing_action_service.py","fc27_players_cloud/player_web/main.py","fc27_players_cloud/player_web/settings.py","fc27_players_cloud/player_web/static/app.js","fc27_players_cloud/VERSION","fc27_players_cloud/source_manifest.json") or name.startswith(("fc27_players_cloud/tests_cloud/","releases/fc-players/manual-recommend-cloud10-20261017/")):
            groups.add("fc-players-cloud10");continue
        if name in ("releases/fs-dashboard/hermes-fc-pilot-20261013/shared_candidate/release_navigation.py","releases/fs-dashboard/hermes-fc-pilot-20261013/test_nightly_release.py"):
            groups.add("hermes-nightly-publisher");continue
        if name in ("mmoexp_google_data/deployment/server_run_integrated.py","mmoexp_google_data/deployment/mmoexp-marketing-daily.timer","mmoexp_google_data/deployment/mmoexp-marketing-daily.service"):
            groups.add("hermes-fc-pilot");continue
        if name.startswith("releases/fs-dashboard/hermes-fc-pilot-20261013/"):
            groups.add("hermes-fc-pilot");continue
        if name.startswith("releases/fs-dashboard/ai-advisor-20261013/deep/"):
            groups.add("fc-deep-advisor");continue
        if name.startswith("releases/fs-dashboard/ai-advisor-20261013/homefix/"):
            groups.add("ai-advisor-home");continue
        if name.startswith("releases/fs-dashboard/ai-advisor-20261013/routefix/"):
            groups.add("ai-advisor-route");continue
        if name.startswith("releases/fs-dashboard/ai-advisor-20261013/activation/"):
            groups.add("ai-advisor-live");continue
        if name.startswith("releases/fs-dashboard/ai-advisor-20261013/"):
            groups.add("ai-advisor");continue
        if name.startswith("releases/fs-dashboard/boss-workspaces-20261013/"):
            groups.add("fs-boss-workspaces");continue
        if name.startswith("releases/fs-dashboard/fc-daily-20261013/"):
            groups.add("fc-daily");continue
        if name.startswith("releases/fs-dashboard/fc-detail-analytics-20261012/"):
            groups.add("fc-detail-analytics");continue
        if name.startswith("releases/fs-dashboard/on-demand-20261012/"):
            groups.add("fs-on-demand");continue
        if name.startswith("releases/fc-coins/lock-gate-hardening-20261013/"):
            groups.add("fc-lock-gate-hardening");continue
        if name.startswith("releases/fc-coins/gate-cycle-20261014/"):
            groups.add("fc-cycle-gate");continue
        if name.startswith("releases/fc-coins/order-public-acceptance-20261013/"):
            groups.add("fc-order-public");continue
        # FC 金币 ALL 镜像写后回读（2026-10-14）：把单次回读换成有界只读重试。
        if name.startswith("releases/fc-coins/coin-all-readback-retry-20261014/"):
            groups.add("fc-coin-all-readback-retry");continue
        # FC27 金币工作台竞品卡片栅格（2026-10-15）：列=竞品、行=区服，
        # 缺来源必须补「暂未获取」占位卡（否则第 4 列被下一区服首卡顶掉）；
        # 同批把成本口径说明段按 2026-09-26 原文补回页面。
        # ⚠️ 只管 .js/.cjs：本包的 .html 与仓库既有约定一致，继续走 frontend 结构校验
        #    （与 releases/fc-coins/player-price-verification-off-20261007 同口径）。
        if suffix in (".js",".cjs") and name.startswith("releases/fc-coins/coin-competitor-grid-20261015/"):
            groups.add("fc-coin-competitor-grid");continue
        # FC27 捆绑包定价工具（2026-10-13 一+二期）：Futbin 金币价 × b2c 单价 → Packs 改价。
        if name.startswith("fc27_pack_bundles_20261013/"):
            groups.add("fc27-pack-bundles");continue
        # MLB 后台直写链路（2026-10-12）：逆向证据 + 生产脚本 + 离线用例。
        # evidence/ 是交付物的一部分（它证明逆向过程可复核），必须保留。
        if name.startswith("mlb_admin_import_20261012/"):
            groups.add("mlb-admin");continue
        # MLB 新卡上架工作台（2026-10-05 故障修复归档）。
        if name.startswith("共享资源/MLB新卡上架/"):
            groups.add("mlb-shelf-tool");continue
        if name.startswith("releases/fs-dashboard/game-boards-all-20261012/"):
            groups.add("fs-game-boards-all");continue
        if name.startswith("releases/fs-dashboard/login-traffic-ui-20261011/"):
            groups.add("fs-login-traffic-ui");continue
        if name.startswith("releases/fs-dashboard/traffic-member-20261009/"):
            groups.add("fs-traffic-member");continue
        if name.startswith("releases/fs-dashboard/traffic-yesterday-20261009/"):
            groups.add("fs-period-ui");continue
        if name.startswith("releases/fs-dashboard/metrics-fix-20261009/"):
            groups.add("fs-metrics-fix");continue
        if name.startswith("releases/fs-dashboard/admin-main-20261009/"):
            groups.add("fs-admin-view");continue
        if name.startswith("releases/auth/admin-entry-20261009/"):
            groups.add("admin-entry");continue
        if name.startswith("releases/registration/account-management-20261009/"):
            groups.add("registration-management");continue
        if name.startswith("releases/fc-coins/lootbar-spec-repair-20261009/"):
            groups.add("fc-lootbar");continue
        if name.startswith("releases/fs-dashboard/business-period-cache-20261010/"):
            groups.add("fs-business-period-cache");continue
        if name.startswith("releases/fs-dashboard/order-latency-20261010/"):
            groups.add("fs-order-latency");continue
        if name.startswith("releases/fs-dashboard/business-live-20261010/"):
            groups.add("fs-business-live");continue
        if name.startswith("releases/fc-coins/prewrite-recovery-20261012/"):
            groups.add("fc-prewrite");continue
        if name.startswith("releases/fs-dashboard/nightly-pipeline-20261023/"):
            groups.add("nightly-pipeline");continue
        if name.startswith("releases/fc-coins/noncore-emergency-20261009/"):
            groups.add("fc-noncore");continue
        if name.startswith("releases/fc-coins/public-readback-retry-20261009/"):
            groups.add("fc-public-readback");continue
        if name.startswith("releases/fc-coins/coupon-consistency-20261009/"):
            groups.add("fc-coupon-consistency");continue
        if name.startswith("releases/fc-coins/coupon-parity-doc-20261009/"):
            groups.add("fc-coupon-parity-doc");continue
        if name.startswith("releases/green-plan/20261009-review-fix/"):
            groups.add("green-plan-review-fix");continue
        if name.startswith("releases/green-plan/20261009/"):
            groups.add("green-plan");continue
        if name in (
            "tests/registration-release-delta-qa-20261007/linux_delta_entry.py",
            "tests/registration-release-delta-qa-20261007/overlay-manifest.json",
            "tests/registration-release-delta-qa-20261007/EXECUTE.md",
            ".github/workflows/registration-target39-manual-qa.yml",
        ):
            groups.add("registration-delta");continue
        # g2gfollow（G2G 金币改价系统）2026-10-14 纳入版本管理。
        # 它的 systemd unit 与 tools/*.sh 若不在此处置，会落进下面「无主 .service /
        # 未映射」桶 ⇒ 一入仓就把 pr-fast 判红。整体归入 g2g 组，由
        # pr_fast_tests.G2GModuleContracts 做离线契约检查（纯 AST/文本，不 exec、不联网）。
        if name.startswith("opt/g2gfollow/") and suffix in (".py",".sh",".service"):
            groups.add("g2g");continue
        # Discord 机器人（2026-10-15 纳入版本管理）：MMOEXP GuardBot（防冒充守卫）
        # + Shugo-bot（AION2 迎新）+ 管这两个机器人的控制台页面 /bots/。
        # 与 g2g 同一个坑：它们的 systemd unit（.service）若不在此处置，会落进
        # 下面「无主 .service」桶 ⇒ 一入仓就把 pr-fast 判红。整体归入 bots 组，
        # 由 pr_fast_tests.BotModuleContracts 做离线契约检查（纯 AST / 文本，
        # 不 exec、不联网）。.mjs 一并归组：它不在下面的按后缀分流表里，
        # 不入组就只有 selfcheck 会跑，改了也没人看。
        if name.startswith(("opt/mmoexp-guardbot/","opt/shugo-bot/","opt/bot-console/")) \
                and suffix in (".py",".js",".cjs",".mjs",".service"):
            groups.add("bots");continue
        # 运营模块（2026-10-17 补登记）：/opt 下这 6 个模块早就在仓里，但映射表
        # 里没有它们的路径 ⇒ 任何改动都被判 UNMAPPED 全红，久而久之只能「绕过闸门改」。
        # 现按后缀统归 ops-modules，由 pr_fast_tests.OpsModuleContracts 做离线契约
        # 检查（纯 AST / 文本，不 exec、不联网）。.html/.css 不在此处拦，继续走
        # frontend 结构校验；.md/.bat/.json 按原有约定忽略。
        if name.startswith(OPS_MODULE_PATHS) and suffix in (".py",".js",".cjs",".sh",".service",".timer"):
            if name == "opt/fs-access-policy/web/app.js":
                groups.add("iam")
            # nba 的纯守卫用例是独立资产，不能被新组顶掉（select 按集合返回，可并存）。
            if name.startswith("opt/nba-reprice/backend/api_security"):
                groups.add("nba")
            groups.add("ops-modules");continue
        # 全站访问控制（2026-10-20 fs-iam）：策略引擎与控制台的离线用例。
        # 这两个文件不在任何 releases/ 批次里，必须显式登记，否则一入仓就 UNMAPPED。
        if name in ("tests/test_fs_iam_rbac.py", "tests/test_fs_iam_console.py", "tests/test_fs_iam_password_request.cjs"):
            groups.add("iam");continue
        if name.startswith("releases/fc-coins/publish-entry-20261020/") and suffix in (".py", ".json", ".sh"):
            groups.add("fc-publish-entry");continue
        if name.startswith("releases/fc-coins/monitor-health-20261020/") and suffix in (".py", ".json"):
            groups.add("monitor-health");continue
        if name.startswith("releases/fc-coins/source-policy-20261020/") and suffix in (".py", ".json"):
            groups.add("fc-source-policy");continue
        if name.startswith("releases/fc-coins/natural-recovery-20261020/") and suffix in (".py", ".sh"):
            groups.add("fc-natural-recovery");continue
        if name.startswith("releases/fs-dashboard/cohort-wording-20261020/") and suffix in (".py",".js",".cjs"):
            groups.add("cohort-wording");continue
        if name.startswith("releases/fs-dashboard/fc-order-wait-sort-20261020/") and suffix==".py":
            groups.add("fc-wait-sort");continue
        if name.startswith("releases/fs-dashboard/hermes-customer-lifecycle-20261019/") and suffix in (".py",".js",".cjs"):
            groups.add("customer-lifecycle");continue
        if name.startswith("releases/fs-dashboard/hermes-navigation-range-20261019/") and suffix in (".py",".js",".cjs"):
            groups.add("hermes-navigation-range");continue
        if suffix in (".sql",".service",".timer") or (name.startswith(".github/workflows/") and name!=".github/workflows/pr-fast.yml"):
            unmapped.append(name);continue
        if name.startswith("tools/pr_fast") or name==".github/workflows/pr-fast.yml":
            groups.add("self");continue
        if suffix not in (".py",".js",".cjs",".sh",".html",".css"):continue
        if suffix in (".html",".css"):
            groups.add("frontend");continue
        if name.startswith("candidates/fc-coins/player-supersession-20261007-v4-2-3/source/") and "/app/" not in name:groups.add("supersession")
        elif name.startswith("releases/fc-coins/player-price-verification-off-20261007/"):groups.add("player-price-rule")
        elif name=="fc27_quote_engine.py" or name=="test_fc27_quote_engine.py" or name.startswith("docs/fc27-coins/discount-config-release-20261005/tests/"):groups.add("engine")
        elif name.startswith("ops/hooks/"):groups.add("hooks")
        elif name.startswith("fc27_cloud_browser/"):groups.add("fc-control")
        elif name=="fc27_players_cloud/player_web/price_lock.py":groups.add("players")
        elif name.startswith("opt/d4follow/") or name.startswith("aion2_dd373_local_collect_20261006/") or name=="tools/release_d4follow.py":groups.add("rpg")
        elif name.startswith("aion2_dashboard_20261004/"):groups.add("aion")
        elif name.startswith("opt/nba-reprice/backend/api_security") or name=="tests/integration/test_nba_pure_guards.cjs":groups.add("nba")
        elif name in ("tools/build_business_html.py","tools/test_business_html_build.py"):groups.add("builder")
        else:unmapped.append(name)
    if unmapped:raise RuntimeError("UNMAPPED: add minimal affected synthetic test mapping in this PR: "+", ".join(unmapped))
    return sorted(groups)

def main():
    if sys.argv[1:]==["--selfcheck"]:
        selfcheck();return
    paths=Path(sys.argv[1]).read_bytes().decode("utf-8").rstrip("\0").split("\0")
    paths=[p for p in paths if p]
    print(json.dumps({"base":sys.argv[2],"head":sys.argv[3],"python":sys.version,
        "tested_tree":subprocess.check_output(["git","-c","safe.directory="+str(ROOT),"-C",str(ROOT),"rev-parse","HEAD^{tree}"],text=True).strip(),
        "paths":paths,"production":False,"offline":True},ensure_ascii=False))
    for name in paths:
        p=ROOT/name
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT):raise RuntimeError("invalid_diff_path")
        require_changed_file(name,p.exists())
        if not p.exists():continue
        if p.suffix==".py":ast.parse(p.read_text(encoding="utf-8-sig"),filename=name,feature_version=(3,9))
        elif p.suffix in (".js",".cjs"):subprocess.run(["node","--check",str(p)],check=True,timeout=20)
        elif p.suffix==".sh":subprocess.run(["bash","-n",str(p)],check=True,timeout=20)
        elif p.suffix==".json":json.loads(p.read_text(encoding="utf-8-sig"))
        elif p.suffix in (".html",".css"):frontend_structure(name,p.read_text(encoding="utf-8-sig"))
    groups=select(paths)
    # Workflow/governance-only PR still tests the stable failure gate.
    selfcheck()
    for group in groups:
        if group=="madden-browser-isolation":
            units("releases/ops/madden-browser-isolation-20261023",["test_recovery","test_linux_runtime","test_publish","test_resource_boundaries","test_fc_isolation"])
            continue
        if group=="campaign-analytics":
            folder=ROOT/"releases/fs-dashboard/campaign-analytics-20261023/app"
            directories=[folder/"tests",folder/"runtime/tests",folder/"analytics/tests",folder.parent/"seasonal-source/tests"]
            tests=sorted(str(p) for d in directories for p in d.glob("*.test.*"))
            if not tests:raise RuntimeError("campaign tests missing")
            subprocess.run(["node","--test"]+tests,cwd=folder,check=True,timeout=90)
            units("releases/fs-dashboard/campaign-analytics-20261023",["test_publish","test_prepare_g1_release"])
            units("releases/fs-dashboard/campaign-analytics-20261023/backend",["test_backend_suite"])
            node("releases/fs-dashboard/campaign-analytics-20261023/app/tests/center-browser.cjs")
            node("releases/fs-dashboard/campaign-analytics-20261023/app/tests/fc-published-browser.cjs")
            node("releases/fs-dashboard/campaign-analytics-20261023/seasonal-source/tests/browser-check.cjs")
            continue
        print("affected group:",group,flush=True)
        if group == 'hermes-review-archive':
            units('releases/fs-dashboard/hermes-review-archive-20261024', ['test_archive'])
            continue
        if group=="fc-reference-observer-ui":
            units("releases/ops/fc-reference-observer-ui-20261023/ui/tests",["test_reference_observer_view"])
            units("releases/ops/fc-reference-observer-ui-20261023/trigger",["test_trigger"])
            node("releases/ops/fc-reference-observer-ui-20261023/ui/tests/test_ui.cjs")
            continue
        if group=="fc-price-shadow":
            units("releases/ops/fc-itemd2r-shadow-20261023/observer/tests",["test_itemd2r","test_observe"])
            units("releases/ops/fc-itemd2r-shadow-20261023/shadow",["test_reference_shadow"])
            continue
        if group=='pricing-followup':
            units('releases/ops/pricing-followup-20261023/alerts',['test_probe','test_watch'])
            units('releases/ops/pricing-followup-20261023/order',['test_query_read'])
            units('releases/ops/pricing-followup-20261023/browser/tests',['test_start'])
            continue
        if group=='pricing-recovery':
            units('releases/ops/pricing-recovery-20261023/fc_lifecycle/tests',['test_lifecycle','test_prewrite_rejection'])
            units('releases/ops/pricing-recovery-20261023/fc_residency/tests',['test_lootbar_server_collector','test_preserved_contract','test_residency','test_event_contract','test_document_release'])
            units('releases/ops/pricing-recovery-20261023/rpg',['test_public_contracts'])
            units('releases/ops/pricing-recovery-20261023/order',['test_service'])
            continue
        if group=='knowledge-layering':
            units('releases/fs-dashboard/knowledge-layering-20261023/tests',['test_knowledge','test_closeout','test_knowledge_release','test_native_plan','test_native_release','test_native_prepare','test_task_selection','test_learning_catalog'])
            continue
        if group=='hermes-memory-approval':
            units('releases/fs-dashboard/hermes-memory-approval-20261022',['test_review_queue','test_reviewed_skills','test_daily_review'])
            continue
        if group=='hermes-learning-closure':
            units('releases/fs-dashboard/hermes-learning-closure-20261023',['test_prepare'])
            units('releases/fs-dashboard/hermes-learning-closure-20261023/tests',['test_learning_native_release','test_routes_release'])
            continue
        if group in ("self","frontend"):continue
        if group=="game-monitor-auto":
            units("releases/fs-dashboard/game-monitor-autopublish-20261022/tests",["test_contract","test_controller","test_install"])
            node("releases/fs-dashboard/game-monitor-autopublish-20261022/tests/render.cjs")
            continue
        if group=="game-monitor-sop":
            units("releases/fs-dashboard/game-monitor-sop-20261022/tests",["test_content","test_prepare_release"])
            node("releases/fs-dashboard/game-monitor-sop-20261022/tests/test_render.cjs")
        elif group=="admin-monthly-paid":
            units("rea_admin_contract_20261021",["test_monthly_paid"])
            units("admin_session_continuity_20261021",["test_continuity"])
        elif group=="fc-pricing-v2":
            units("releases/fc-coins/fc-pricing-v2-20261022/tests",["test_pricing_v2","test_control","test_guards","test_bidirectional","test_sync_recipient","test_prewrite_diagnostics"])
            node("releases/fc-coins/fc-pricing-v2-20261022/tests/test_ui.js")
            units("releases/fs-dashboard/fc-coins-workflow-20261022/tests",["test_workflow"])
            units("releases/fs-dashboard/fc-coins-evidence-20261021/tests",["test_coins_evidence"])
        elif group=="fc-coins-workflow":
            units("releases/fs-dashboard/fc-coins-workflow-20261022/tests",["test_workflow"])
            units("releases/fs-dashboard/fc-coins-evidence-20261021/tests",["test_coins_evidence"])
        elif group=="fc-coins-evidence":
            units("releases/fs-dashboard/fc-coins-evidence-20261021/tests",["test_coins_evidence"])
        elif group=="daily-archive":
            units("releases/fs-dashboard/daily-archive-20261021/tests",["test_archive","test_jobs","test_release","test_report_readiness"])
        elif group=="rs-business-adapter":
            units("releases/fs-dashboard/rs-adapter-20261024/tests",["test_rs","test_shipping","test_shipping_readiness","test_existing_archive","test_existing_refresh","test_release"])
            node("releases/fs-dashboard/rs-adapter-20261024/tests/test_rs_projection.cjs")
            node("releases/fs-dashboard/rs-adapter-20261024/tests/test_procurement.cjs")
            node("releases/fs-dashboard/rs-adapter-20261024/tests/test_views.cjs")
            node("releases/fs-dashboard/rs-adapter-20261024/tests/test_browser.cjs")
        elif group=="business-procurement":
            units("releases/fs-dashboard/business-procurement-20261022/tests",["test_release"])
            node("releases/fs-dashboard/business-procurement-20261022/tests/test_procurement.cjs")
            node("releases/fs-dashboard/business-procurement-20261022/tests/test_views.cjs")
        elif group=="user-analytics":
            units("releases/fs-dashboard/user-analytics-20261022/tests",["test_users","test_integration","test_deploy","test_period","test_search_http"])
        elif group=="channel-effects":
            units("releases/fs-dashboard/channel-effects-20261021/tests",["test_channel_effects","test_channel_cache","test_publisher","test_pmax_source","test_pmax_publisher","test_pmax_traffic_ui","test_pmax_es_projection","test_mapping_reclassification"])
            node("releases/fs-dashboard/channel-effects-20261021/tests/test_ui.cjs")
        elif group=="admin-session-continuity":
            units("admin_session_continuity_20261021",["test_continuity"])
            units("order_global_session_20261021",["test_session","test_fc_admin","test_deploy","test_admin_read_patch"])
        elif group=="order-global-session":units("order_global_session_20261021",["test_session","test_fc_admin","test_deploy","test_admin_read_patch"])
        elif group=="admin-single-owner":units("shared_backend_session",["test_shared_admin","test_consumers","test_manual_captcha","test_sales_pagination"])
        elif group=="engine":units(".",["test_fc27_quote_engine"])
        elif group=="admin-entry":node("releases/auth/admin-entry-20261009/check-entry.cjs")
        elif group=="registration-management":
            release="releases/registration/account-management-20261009"
            node(release+"/tests/test_actions.cjs")
            subprocess.run([sys.executable,"-I","-B",str(ROOT/release/"tests/test_permissions.py")],cwd=ROOT,check=True,timeout=120)
            subprocess.run([sys.executable,"-I","-B",str(ROOT/release/"tests/test_release.py")],cwd=ROOT,check=True,timeout=60)
        elif group=="player-price-rule":units("releases/fc-coins/player-price-verification-off-20261007",["test_rule"])
        elif group=="supersession":units("tools",["pr_fast_tests.CurrentSupersession"])
        elif group=="players":units("tools",["pr_fast_tests.PlayersLock"])
        elif group=="rpg":units("tools",["pr_fast_tests.RPGGuards","pr_fast_tests.RPGModuleContracts"])
        elif group=="g2g":units("tools",["pr_fast_tests.G2GModuleContracts"])
        elif group=="bots":units("tools",["pr_fast_tests.BotModuleContracts"])
        elif group=="ops-modules":
            units("tools",["pr_fast_tests.OpsModuleContracts"])
            units("opt/mlb-online",["test_writeback_guards"])
        elif group=="iam":
            # 授权引擎的硬门槛：新引擎必须与改造前的旧实现逐格同判定。
            # 任何一个格子对不上，这里就红 —— 换引擎不许顺带改谁的权限。
            units("tests",["test_fs_iam_rbac","test_fs_iam_console"])
            node("tests/test_fs_iam_password_request.cjs")
        elif group=="aion":node("aion2_dashboard_20261004/test_status.cjs")
        elif group=="nba":node("tests/integration/test_nba_pure_guards.cjs")
        elif group=="hooks":units("ops/hooks",["test_hooks","test_monitor","test_notifier","test_rpg_alerts"])
        elif group=="deployed-source-backfill":
            units("releases/fs-dashboard/deployed-source-backfill-20261017",["test_inventory"])
        elif group=="fc-browser-readiness":
            units("releases/fc-coins/browser-readiness-20261016/fc27_chrome_collector",["test_lootbar_server_collector"])
        elif group=="fc-result-read":
            node("releases/fc-coins/result-read-20261016/test_result_read.cjs")
        elif group=="fs-business-refresh":
            units("releases/fs-dashboard/business-refresh-20261016/tests",["test_refresh"])
            node("releases/fs-dashboard/business-refresh-20261016/tests/test_refresh.cjs")
        elif group=="fc-players-shared-login":
            units("fc27_players_cloud",["tests_cloud.test_shared_session"])
            units("releases/fc-players/shared-login-20261018",["test_session_socket"])
        elif group=="fc-players-history-five":
            node("releases/fc-players/history-five-20261024/check_job_history.cjs")
        elif group=="fc-players-cloud10":
            units("fc27_players_cloud",["tests_cloud.test_manual_existing_recommend"])
            node("fc27_players_cloud/tests_cloud/check_manual_recommend_button.cjs")
        elif group=="fc-prewrite":
            release="releases/fc-coins/prewrite-recovery-20261012"
            for name in ("test_monitor","test_publishers"):
                units(release+"/tests",[name])
        elif group=="fc-noncore":
            release="releases/fc-coins/noncore-emergency-20261009"
            for name in ("test_pipeline","test_selfheal","test_monitor","test_publishers"):
                subprocess.run([sys.executable,"-I","-B","-c",
                    "import sys,unittest;sys.path.insert(0,sys.argv[1]);import pr_fast;r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[2],pattern=sys.argv[3]+'.py'));pr_fast.require_success(r)",
                    str(ROOT/"tools"),str(ROOT/release/"tests"),name],check=True,timeout=90,cwd=ROOT)
            node(release+"/tests/test_js.cjs")
        elif group=="hermes-desktop":
            units("releases/fs-dashboard/hermes-desktop-20261015",["test_context"])
            subprocess.run(["pwsh","-NoLogo","-NoProfile","-File",str(ROOT/"releases/fs-dashboard/hermes-desktop-20261015/Test-Connect.ps1")],check=True,timeout=30,cwd=ROOT)
        elif group=="hermes-report-quality":
            units("releases/fs-dashboard/hermes-report-quality-20261015",["test_report_constraints","test_report_quality","test_release_quality","test_proof_release","test_report_delivery","test_skill_bundle","test_research"])
            units("releases/fs-dashboard/hermes-shared-reports-20261015",["test_shared_reports"])
        elif group=="navigation-recovery":
            units("releases/fs-dashboard/navigation-recovery-20261015",["test_recovery"],root_owned=True)
        elif group=="fs-revision-20261015":
            release="releases/fs-dashboard/fs-revision-20261015"
            units(release+"/reports/tests",["test_renderer"])
            units(release+"/accounts/tests",["test_accounts","test_http","test_publisher"],root_owned=True)
            units(release+"/accounts/integration",["test_ai_publisher"],root_owned=True)
            units(release+"/ai",["test_retirement","test_official_workspace","test_boss_projection","test_boss_artifacts","test_business_context"])
            units(release+"/analytics",["test_fc_detail","test_fc_pool"])
            units(release+"/cleanup/tests",["test_cleanup","test_profit_queries"],root_owned=True)
            units(release+"/shared-release",["test_ui_release","test_combined_publisher"],root_owned=True)
            subprocess.run([sys.executable,"-B",str(ROOT/release/"shared-release/test_brain_contract.py")],check=True,timeout=30,cwd=ROOT)
            units(release+"/frontend-release",["test_native_release"],root_owned=True)
            for name in ("test_fc_lifecycle.cjs","test_management_existing.cjs","test_management_actuals.cjs","test_game_cards.cjs"):
                node(release+"/analytics/"+name)
            subprocess.run([sys.executable,"-B",str(ROOT/release/"ai/run_regression.py")],check=True,timeout=90,cwd=ROOT)
        elif group=="fc-detail-analytics":
            release="releases/fs-dashboard/fc-detail-analytics-20261012"
            units(release+"/tests",["test_fc_detail","test_fc_reader","test_fc_publisher"])
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/tests/test_fc_query.cjs")
        elif group=="fs-on-demand":
            release="releases/fs-dashboard/on-demand-20261012"
            units(release+"/tests",["test_catalog","test_range","test_profit_queries","test_query_api","test_grant_dy","test_weekly","test_release"],root_owned=True)
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            entry=ROOT/release/"entry-profit-refresh/frontend"
            if entry.exists():
                units(release+"/entry-profit-refresh/frontend",["test_release_workspace"],root_owned=True)
                subprocess.run(["node",str(ROOT/release/"tests/test_browser.cjs")],cwd=ROOT/release,check=True,timeout=30,env=dict(os.environ,FS_ASSET_PATH=str(entry/"assets")))
            else:node(release+"/tests/test_browser.cjs")
            node(release+"/tests/test_legacy.cjs")
        elif group=="fs-game-boards-all":
            release="releases/fs-dashboard/game-boards-all-20261012"
            units(release+"/tests",["test_games","test_release"],root_owned=True)
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/tests/test_all_sites.cjs")
            node(release+"/tests/test_browser.cjs")
            entry=ROOT/release/"entry-cache/frontend"
            if entry.exists():
                units(release+"/entry-cache/frontend",["test_release_workspace"],root_owned=True)
                subprocess.run(["node",str(ROOT/release/"tests/test_browser.cjs")],cwd=ROOT/release,check=True,timeout=30,
                    env=dict(os.environ,FS_ASSET_PATH=str(entry/"assets"),FS_OLD_CATALOG="1"))
        elif group=="fs-login-traffic-ui":
            release="releases/fs-dashboard/login-traffic-ui-20261011"
            units(release,["test_login_release"],root_owned=True)
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/test-actions.cjs")
        elif group=="fs-traffic-member":
            release="releases/fs-dashboard/traffic-member-20261009"
            units(release,["test_backend","test_publisher"])
            units(release+"/deploy/static",["test_release_workspace"],root_owned=True)
            node(release+"/test-glossary.cjs")
        elif group=="hermes-nightly-publisher":
            units("releases/fs-dashboard/hermes-fc-pilot-20261013",["test_nightly_release","test_release","test_autonomous_release","test_report_release","test_direct_release","test_continuation_release","test_capability_release"])
        elif group=="hermes-fc-pilot":
            release="releases/fs-dashboard/hermes-fc-pilot-20261013"
            units(release,["test_pilot","test_runs_contract","test_gateway","test_background","test_transport","test_source_projection","test_skill_bundle","test_research","test_controller","test_report_output","test_report_release","test_continuation","test_continuation_release","test_call_recovery","test_report_delivery","test_markdown_report","test_autonomous_release","test_nightly","test_nightly_deadline","test_nightly_preparation","test_task_context","test_nightly_release","test_provider","test_release","test_fs_evidence","test_history","test_admission_hold","test_context_gate","test_direct_provider","test_direct_ledger","test_direct_release","test_capability_wiring","test_capability_release","admin_order_capabilities_20261014.test_capabilities","admin_order_capabilities_20261014.test_wiring"])
            node(release+"/check_ui.cjs")
            subprocess.run([sys.executable,"-I","-B",str(ROOT/release/"test_browser_ui.py")],check=True,timeout=30)
            subprocess.run([sys.executable,"-I","-B",str(ROOT/release/"admission_smoke.py")],check=True,timeout=30)
            subprocess.run([sys.executable,"-I","-B",str(ROOT/release/"runtime_ci.py"),"--test"],check=True,timeout=420)
        elif group=="fc-deep-advisor":
            release="releases/fs-dashboard/ai-advisor-20261013/deep"
            units(release+"/tests",["test_ci"],root_owned=True)
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/check_deep_ui.cjs")
        elif group=="ai-advisor-home":
            units("releases/fs-dashboard/ai-advisor-20261013/homefix/frontend",["test_release_workspace"],root_owned=True)
        elif group=="ai-advisor-route":
            units("releases/fs-dashboard/ai-advisor-20261013/routefix/frontend",["test_release_workspace"],root_owned=True)
        elif group=="ai-advisor-live":
            release="releases/fs-dashboard/ai-advisor-20261013/activation"
            units(release+"/source",["test_ai_advisor","test_boss_insights","test_fc_daily","test_advisor_release"])
            units(release+"/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/source/check_ui.cjs")
        elif group=="ai-advisor":
            units("releases/fs-dashboard/ai-advisor-20261013/source",["test_ai_advisor","test_boss_insights","test_fc_daily","test_advisor_release"])
            node("releases/fs-dashboard/ai-advisor-20261013/source/check_ui.cjs")
        elif group=="fs-boss-workspaces":
            release="releases/fs-dashboard/boss-workspaces-20261013"
            for name in ("game-monitor.cjs","game-daily.cjs","management_test.cjs","management_polling.cjs","management_sandbox.cjs"):
                node(release+"/tests/"+name)
            units(release+"/backend",["test_boss_insights"])
            units(release+"/tests",["test_game_intelligence","management_daily_test","test_boss_daily","test_backend_release","test_insights_release"],root_owned=True)
        elif group=="fc-daily":
            units("releases/fs-dashboard/fc-daily-20261013/source",["test_fc_daily","test_fc_release"])
        elif group=="fs-business-period-cache":
            release="releases/fs-dashboard/business-period-cache-20261010"
            units(release+"/tests",["test_live_summary","test_latency","test_retention","test_backend_scope","test_period_cache"],root_owned=True)
            units(release+"/deploy/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/tests/test_frontend.mjs")
            node(release+"/tests/test_latency.mjs")
            node(release+"/tests/test_entry_refs.mjs")
            node(release+"/tests/test_period_policy.mjs")
            node(release+"/tests/test_order_recovery.cjs")
            node(release+"/tests/test_home_recovery.cjs")
        elif group=="fs-order-latency":
            release="releases/fs-dashboard/order-latency-20261010"
            units(release+"/tests",["test_live_summary","test_latency","test_retention","test_backend_scope"],root_owned=True)
            units(release+"/deploy/frontend",["test_release_workspace"],root_owned=True)
            node(release+"/tests/test_frontend.mjs")
            node(release+"/tests/test_latency.mjs")
            node(release+"/tests/test_entry_refs.mjs")
        elif group=="fs-business-live":
            release="releases/fs-dashboard/business-live-20261010"
            units(release+"/tests",["test_live_summary","test_release","test_session","test_cache_patch"],root_owned=True)
            units(release+"/deploy/frontend",["test_release_workspace"],root_owned=True)
            units(release+"/deploy/frontend-fixed",["test_release_workspace"],root_owned=True)
            node(release+"/tests/test_frontend.mjs")
            node(release+"/tests/test_entry_refs.mjs")
        elif group=="fs-period-ui":node("releases/fs-dashboard/traffic-yesterday-20261009/test-yesterday.mjs")
        elif group=="fs-metrics-fix":
            release="releases/fs-dashboard/metrics-fix-20261009"
            for name in ("test-fix.mjs","test-visibility.mjs","check-entry.cjs","test-assets.mjs"):node(release+"/"+name)
        elif group=="fs-admin-view":
            release="releases/fs-dashboard/admin-main-20261009"
            node(release+"/test-policy.mjs")
            node(release+"/test-visibility.mjs")
            node(release+"/test-assets.mjs")
        elif group=="fc-lootbar":
            release="releases/fc-coins/lootbar-spec-repair-20261009"
            units(release+"/fc27_chrome_collector",["test_lootbar_server_collector"])
            subprocess.run(["node",str(ROOT/release/"fc27_chrome_collector/test_lootbar_collection.cjs")],
                cwd=ROOT/release,check=True,timeout=30)
        elif group=="fc-public-readback":
            release="releases/fc-coins/public-readback-retry-20261009"
            subprocess.run([sys.executable,"-I","-B","-c",
                "import sys,unittest;sys.path.insert(0,sys.argv[1]);import pr_fast;r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[2],pattern=sys.argv[3]+'.py'));pr_fast.require_success(r)",
                str(ROOT/"tools"),str(ROOT/release/"fc27_cloud_browser"),"test_public_readback_retry"],check=True,timeout=90,cwd=ROOT)
        elif group=="fc-coupon-consistency":
            release="releases/fc-coins/coupon-consistency-20261009"
            subprocess.run([sys.executable,"-I","-B","-c",
                "import sys,unittest;sys.path.insert(0,sys.argv[1]);import pr_fast;r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[2],pattern=sys.argv[3]+'.py'));pr_fast.require_success(r)",
                str(ROOT/"tools"),str(ROOT/release/"fc27_cloud_browser"),"test_coupon_consistency"],check=True,timeout=90,cwd=ROOT)
        elif group=="fc-coupon-parity-doc":
            release="releases/fc-coins/coupon-parity-doc-20261009"
            subprocess.run([sys.executable,"-I","-B","tools/fc-check-doc-release.py",
                str(ROOT/release)],check=True,timeout=60,cwd=ROOT/release)
        elif group=="fc-control":
            if "engine" not in groups:units(".",["test_fc27_quote_engine"])
            units("fc27_cloud_browser",["test_automation_policy","test_coin_all_sync","test_source_confirmation","test_player_sync_recovery","test_player_sync_bulk"])
        elif group=="green-plan-review-fix":
            fix=ROOT/"releases/green-plan/20261009-review-fix"
            env=dict(os.environ,GREEN_AUTH_RUNTIME=str(ROOT/"registration_approval_runtime_v3_20261006"),
                GREEN_BACKEND=str(ROOT/"releases/green-plan/20261009/candidate/backend"),
                GREEN_AUTH_CANDIDATE=str(fix/"candidate/auth"))
            for name in ("test_auth_flow.py","test_rollback.py"):
                subprocess.run([sys.executable,"-B",str(fix/"tests"/name)],check=True,timeout=90,cwd=ROOT,env=env)
        elif group=="green-plan":
            for name in ("candidate/backend/test_green_plan.py","check_release.py"):
                subprocess.run([sys.executable,"-B",str(ROOT/"releases/green-plan/20261009"/name)],check=True,timeout=90,cwd=ROOT)
        elif group=="mlb-admin":
            # 离线用例：协议契约 / 幂等判定 / 凭据卫生 / 证据包结构。
            # 不连网、不写后台、不需要凭据（CI 隔离环境下已验证 23 项全绿）。
            units("mlb_admin_import_20261012/tests",["test_admin_write_channel"])
        elif group=="fc-lock-gate-hardening":
            units("releases/fc-coins/lock-gate-hardening-20261013",["test_hardening"])
        elif group=="fc-cycle-gate":
            units("releases/fc-coins/gate-cycle-20261014",["test_cycle_gate","test_publisher"])
        elif group=="fc-order-public":
            units("releases/fc-coins/order-public-acceptance-20261013",["test_acceptance"])
        elif group=="fc-coin-all-readback-retry":
            units("releases/fc-coins/coin-all-readback-retry-20261014",["test_readback_retry"])
        elif group=="hermes-weekly-upgrade":
            units("releases/fs-dashboard/hermes-weekly-upgrade-20261015/data",["test_weekly_data"])
            units("releases/fs-dashboard/hermes-weekly-upgrade-20261015/methods",["test_weekly_bundle"])
            units("releases/fs-dashboard/hermes-weekly-upgrade-20261015/visual",["test_visual"])
            units("releases/fs-dashboard/hermes-weekly-upgrade-20261015/tests",["test_prepare","test_weekly_release"])
            units("releases/fs-dashboard/hermes-weekly-upgrade-20261015/followup",["test_render_compat","test_release_compat","test_inventory_negation","test_intel_selection"])
            node("releases/fs-dashboard/hermes-weekly-upgrade-20261015/followup/test_report_buttons.cjs")
        elif group=="fc-sbc-security":
            units("releases/fc-sbc/security-20261015/tests",["test_security","test_publisher"])
        elif group=="news-weekly-schedule":
            units("releases/fs-dashboard/news-weekly-schedule-20261016/tests",["test_weekly","test_release_backend"])
            node("releases/fs-dashboard/news-weekly-schedule-20261016/tests/test_weekly_ui.cjs")
        elif group=="game-monitor-news-cards":
            units("releases/fs-dashboard/game-monitor-news-cards-20261016/tests",["test_news_translation","test_release_backend"])
            node("releases/fs-dashboard/game-monitor-news-cards-20261016/tests/test_cards_ui.cjs")
        elif group=="mmoexp-news":
            units("releases/fs-dashboard/mmoexp-news-integration-20261016/tests",["test_mmoexp_news","test_research_news","test_release_news","test_nightly_news"])
            node("releases/fs-dashboard/mmoexp-news-integration-20261016/tests/test_news_ui.cjs")
        elif group=="hermes-report-import":
            units("releases/fs-dashboard/hermes-report-import-20261015",["test_imported_reports","test_release"])
            node("releases/fs-dashboard/hermes-report-import-20261015/test_import_ui.cjs")
        elif group=="hermes-report-tracks":
            units("releases/fs-dashboard/hermes-report-tracks-20261015/tests",["test_report_tracks","test_pricing_report","test_artifact_tracks","test_release_tracks"])
            node("releases/fs-dashboard/hermes-report-tracks-20261015/check_tracks.cjs")
        elif group=="hermes-fs-research-integration":
            units("releases/fs-dashboard/hermes-fs-research-integration-20261015/tests",["test_integration","test_official_intelligence","test_intel_binding","test_practical_review","test_executive_render","test_release"])
        elif group=="hermes-market-sources":
            units("releases/fs-dashboard/hermes-market-sources-20261015",["test_market","test_release_market","test_runtime_isolation"])
        elif group=="hermes-report-filter-race":
            node("releases/fs-dashboard/hermes-report-filter-race-20261015/check_refresh.cjs")
        elif group=="hermes-shared-reports":
            units("releases/fs-dashboard/hermes-shared-reports-20261015",["test_shared_reports","test_release"])
        elif group=="hermes-fs-config-isolation":
            units("releases/fs-dashboard/hermes-fs-config-isolation-20261015",["test_isolation"])
        elif group=="hermes-report-actions":
            node("releases/fs-dashboard/hermes-report-actions-20261015/check.cjs")
        elif group=="management-quality":
            units("releases/fs-dashboard/management-quality-20261016/tests",["test_quality","test_publish"])
        elif group=="hermes-report-compat":
            units("releases/fs-dashboard/hermes-followup-evidence-20261017/tests",["test_continuation_sources","test_learning_append"])
            units("releases/fs-dashboard/hermes-report-kind-actions-20261017/tests",["test_report_kind"])
            node("releases/fs-dashboard/hermes-report-kind-actions-20261017/tests/check_actions.cjs")
        elif group=="hermes-data-workspace":
            release="releases/fs-dashboard/hermes-data-workspace-20261018"
            units(release+"/tests",["test_cohort_observation","test_cohort_reader","test_cohort_es_source","test_workspace_evidence","test_tool_chain","test_original_output","test_brain_handoff","test_single_method","test_receipt_metadata"])
            node(release+"/tests/test_brain_handoff.cjs")
            node(release+"/tests/test_cohort_prompt.cjs")
            node(release+"/frontend/test-workspace.cjs")
        elif group=="hermes-conversation":
            release="releases/fs-dashboard/hermes-conversation-20261018"
            units(release+"/tests",["test_conversation_store","test_conversation_service","test_worker_admission","test_lazy_evidence"])
            units(release+"/deploy",["test_http","test_release"])
        elif group=="hermes-report-repair":
            release="releases/fs-dashboard/hermes-report-repair-20261019"
            units(release+"/tests",["test_report_repair","test_management_cadence","test_followup_sources"])
            browser_python(release+"/tests/test_bulk_browser.py")
        elif group=="fc-publish-entry":
            # 宿主发布入口与调用端：策略/白名单/批准绑定/回退，全部注入假 git、systemd、monitor。
            units("releases/fc-coins/publish-entry-20261020/tests", ["test_publish_entry", "test_fc_publish", "test_calibrate"])
        elif group=="monitor-health":
            units("releases/fc-coins/monitor-health-20261020/tests", ["test_monitor", "test_publish"])
        elif group=="fc-source-policy":
            units("releases/fc-coins/source-policy-20261020", ["test_source_guard", "test_recovery_guard"])
            units("releases/fc-coins/natural-recovery-20261020", ["test_recovery"])
        elif group=="fc-natural-recovery":
            units("releases/fc-coins/natural-recovery-20261020", ["test_recovery"])
        elif group=="cohort-wording":
            node("releases/fs-dashboard/cohort-wording-20261020/tests/wording.cjs")
        elif group=="fc-wait-sort":
            units("releases/fs-dashboard/fc-order-wait-sort-20261020/tests",["test_wait_sort"])
        elif group=="customer-lifecycle":
            units("releases/fs-dashboard/hermes-customer-lifecycle-20261019/tests",["test_lifecycle"])
        elif group=="hermes-navigation-range":
            units("releases/fs-dashboard/hermes-navigation-range-20261019/tests",["test_contract"])
            node("releases/fs-dashboard/hermes-navigation-range-20261019/tests/range.cjs")
            node("releases/fs-dashboard/hermes-navigation-range-20261019/detail-feedback/tests/detail-feedback.cjs")
        elif group=="hermes-customer-tracking":
            release="releases/fs-dashboard/hermes-customer-tracking-20261018"
            units(release+"/tests",["test_customer_tracking","test_tracking_source","test_private_tracking","test_tracking_tool","test_customer_reports","test_legacy_consumers","test_safe_diagnostic","test_scope_filter"])
            browser_python(release+"/frontend/test_page.py")
        elif group=="hermes-generic-data":
            generic="releases/fs-dashboard/hermes-generic-data-20261018"
            workspace="releases/fs-dashboard/hermes-data-workspace-20261018"
            admin="releases/fs-dashboard/admin-data-tools-20261018"
            units(generic+"/tests",["test_http_queries","test_cohort_paid_source","test_admin_product_orders"])
            units(generic+"/deploy",["test_session_image_lifecycle"])
            units(admin,["test_admin_data_tools","test_publisher_boundary"])
            units(workspace+"/tests",["test_tool_chain","test_cohort_reader","test_cohort_observation","test_cohort_es_source"])
            node(workspace+"/frontend/test-workspace.cjs")
            browser_python(workspace+"/frontend/tools-page/test_page.py")
            node("releases/fs-dashboard/hermes-conversation-20261018/frontend/entry/test_data_handoff.cjs")
        elif group=="hermes-server-unify":
            units("releases/fs-dashboard/hermes-server-unify-20261022",["test_migrate","test_fs_readonly","test_native_knowledge","test_native_entry","test_knowledge_audit","test_native_task_learning"])
        elif group=="hermes-ops":
            units("releases/fs-dashboard/hermes-ops-20261020",["test_ops","test_schedule_alert"])
        elif group=="fs-business-baseline":
            units("releases/fs-dashboard/fs-business-baseline-20261021",["test_baseline"])
        elif group=="hermes-v2-simulation-learning":
            units("releases/fs-dashboard/hermes-v2-simulation-learning-20261021",["test_simulation_learning"])
        elif group=="hermes-v2-ui-fit":
            units("releases/fs-dashboard/hermes-v2-ui-fit-20261021",["test_ui_source"])
        elif group=="hermes-v2-learning-evidence":
            units("releases/fs-dashboard/hermes-v2-learning-evidence-20261021",["test_learning_evidence"])
        elif group=="hermes-v2-strategy-permissions":
            units("releases/fs-dashboard/hermes-v2-strategy-permissions-20261021",["test_permissions"])
        elif group=="hermes-v2-strategy":
            units("releases/fs-dashboard/hermes-v2-strategy-20261021",["test_strategy"])
            node("releases/fs-dashboard/hermes-v2-strategy-20261021/frontend/test_strategy.cjs")
            units("releases/fs-dashboard/hermes-v2-review-repair-20261021",["test_review_repair"])
            units("releases/fs-dashboard/hermes-v2-core-20261020",["test_core"])
        elif group=="hermes-v2-review-repair":
            units("releases/fs-dashboard/hermes-v2-review-repair-20261021",["test_review_repair"])
            units("releases/fs-dashboard/hermes-v2-core-20261020",["test_core"])
        elif group=="hermes-v2-core":
            units("releases/fs-dashboard/hermes-v2-core-20261020",["test_core"])
        elif group=="hermes-admin-recovery":
            units("releases/fs-dashboard/hermes-admin-recovery-20261020",["test_admin_recovery"])
        elif group=="hermes-report-method":
            units("releases/fs-dashboard/hermes-report-method-20261017/tests",["test_method","test_html_archive","test_followup_input","test_followup_admin_tools"])
            node("releases/fs-dashboard/hermes-report-method-20261017/tests/test_viewer.cjs")
        elif group=="hermes-full-html":
            units("releases/fs-dashboard/hermes-full-html-task-20261017/tests",["test_html_design"])
        elif group=="traffic-content-details":
            units("releases/fs-dashboard/traffic-content-details-20261017/tests",["test_content_details"])
            node("releases/fs-dashboard/traffic-content-details-20261017/tests/check_content.cjs")
        elif group=="hermes-report-theme":
            node("releases/fs-dashboard/hermes-report-theme-20261017/tests/theme-print.cjs")
        elif group=="admin-data-tools":
            units("releases/fs-dashboard/admin-data-tools-20261018",["test_admin_data_tools","test_publisher_boundary"])
        elif group=="traffic-hermes":
            units("releases/fs-dashboard/traffic-hermes-20261017/source-tabs-20261019",["test_release"])
            units("mmoexp_google_data/details",["test_details","test_game_dimensions","test_game_cache"])
            units("releases/fs-dashboard/traffic-hermes-20261017/tests",["test_traffic","test_controller_actions","test_supplements","test_es_structure","test_prepare_ui","test_prepare_ui_followup","test_publisher","test_report_inputs_patch","test_es_v3_publisher","test_prepare_ui_v3"])
            units("releases/fs-dashboard/traffic-hermes-20261017/learning",["test_learning","test_learning_bridge"])
            node("releases/fs-dashboard/traffic-hermes-20261017/tests/check_frontend.cjs")
        elif group=="nightly-pipeline":
            units("releases/fs-dashboard/nightly-pipeline-20261023/tests",["test_pipeline"])
        elif group=="hermes-learning-loop":
            units("releases/fs-dashboard/hermes-learning-loop-20261016/tests",["test_learning_loop","test_projection","test_release","test_titles_goals","test_acceptance_fixes","test_source_snapshots"])
        elif group=="desktop-learning":
            units("releases/fs-dashboard/desktop-learning-20261016/tests",["test_learning","test_publish"])
        elif group=="fs-management-v2":
            release="releases/fs-dashboard/management-v2-20261015"
            units(release+"/tests",["test_management_facts","test_management_context","test_management_runner","test_static_publisher","test_backend_publisher","test_skill_identity"])
            node(release+"/tests/check_frontend.cjs")
            node(release+"/tests/check_syntax.cjs")
        elif group=="fs-ui-system":
            units("ui-system/tests",["test_ui","test_release"])
            node("ui-system/tests/syntax.cjs")
            node("ui-system/tests/theme.cjs")
            node("ui-system/tests/navigation.cjs")
        elif group=="fs-menu-cache":
            release="releases/fs-dashboard/menu-cache-20261015"
            node(release+"/test_cache.cjs")
            units(release,["test_release"],root_owned=True)
        elif group=="fc-coin-competitor-grid":
            # Node 契约用例：把候选 JS 的渲染块原样抽出跑 5 场景 22 断言，
            # 校验 3x4 槽位不变量（缺来源补占位、列序不位移）。零网络、零依赖。
            node("releases/fc-coins/coin-competitor-grid-20261015/tests/test_competitor_grid.cjs")
        elif group=="fc27-pack-bundles":
            # 离线用例：定价公式与腾讯文档逐分对齐 / 写价闸门与假 transport 流程。
            # 零网络、零后台写入（CI 隔离环境已验证 23 项全绿）。
            units("fc27_pack_bundles_20261013/tests",["test_pack_bundles_offline","test_write_flow"])
        elif group=="mlb-shelf-tool":
            # 离线用例：bat 规范化闸门 / SQLite 3.7.17 兼容 / 认证通路 / 模板发现。
            units("共享资源/MLB新卡上架/tests",["test_shelf_tool_offline"])
        elif group=="builder":units("tools",["test_business_html_build"])
        elif group=="registration-delta":
            subprocess.run([sys.executable,"-I","-B",str(ROOT/"tests/registration-release-delta-qa-20261007/linux_delta_entry.py"),"--driver-check"],check=True,timeout=30,cwd=ROOT)
    print(json.dumps({"result":"PASS","affected_groups":groups,"syntax_scope":"changed files only","live_not_tested":True}))
if __name__=="__main__":main()
