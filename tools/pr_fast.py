"""One offline affected-test dispatcher. Unmapped code fails explicitly."""
import ast, io, json, os, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

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
        def git(*args):
            return subprocess.check_output(["git","-c","user.name=Offline QA",
                "-c","user.email=qa@example.invalid","-c","commit.gpgsign=false",
                "-c","core.hooksPath=/dev/null",*args],cwd=root,stderr=subprocess.STDOUT)
        git("init","-q")
        for index,(old,new) in enumerate(pairs):
            path=root/old;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text("unique fixture "+str(index)+"\n",encoding="utf-8")
        regular=root/"fc27_quote_engine.py";regular.write_text("VALUE=1\n")
        git("add",".");git("commit","-qm","synthetic base")
        base=git("rev-parse","HEAD").decode().strip()
        for old,new in pairs:
            target=root/new;target.parent.mkdir(parents=True,exist_ok=True)
            (root/old).rename(target)
        regular.write_text("VALUE=2\n")
        git("add","-A");git("commit","-qm","synthetic moves and modification")
        head=git("rev-parse","HEAD").decode().strip()
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
    if select(["releases/fs-dashboard/traffic-yesterday-20261009/assets/business.js"]) != ["fs-period-ui"]:
        raise RuntimeError("fs_period_ui_mapping_missing")
    print("path/structure selfcheck: HTML/CSS-only and mixed paths checked; valid/malformed examples and existing FC templates checked")
    print("coverage selfcheck: unmapped runtime formats/workflows and frontend deletions rejected; HTML non-void slash handled as open tag")
    rename_source_selfcheck()
    print("selfcheck: PASS and FAIL/error/skip/zero propagate correctly")

def select(paths):
    groups=set();unmapped=[]
    for name in paths:
        suffix=Path(name).suffix
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
        print("affected group:",group,flush=True)
        if group in ("self","frontend"):continue
        if group=="engine":units(".",["test_fc27_quote_engine"])
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
        elif group=="aion":node("aion2_dashboard_20261004/test_status.cjs")
        elif group=="nba":node("tests/integration/test_nba_pure_guards.cjs")
        elif group=="hooks":units("ops/hooks",["test_hooks","test_monitor","test_notifier","test_rpg_alerts"])
        elif group=="fc-noncore":
            release="releases/fc-coins/noncore-emergency-20261009"
            for name in ("test_pipeline","test_selfheal","test_monitor","test_publishers"):
                subprocess.run([sys.executable,"-I","-B","-c",
                    "import sys,unittest;sys.path.insert(0,sys.argv[1]);import pr_fast;r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(sys.argv[2],pattern=sys.argv[3]+'.py'));pr_fast.require_success(r)",
                    str(ROOT/"tools"),str(ROOT/release/"tests"),name],check=True,timeout=90,cwd=ROOT)
            node(release+"/tests/test_js.cjs")
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







