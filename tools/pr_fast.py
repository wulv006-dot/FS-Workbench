"""One offline affected-test dispatcher. Unmapped code fails explicitly."""
import ast, io, json, os, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def require_success(result):
    if result.testsRun <= 0 or not result.wasSuccessful() or result.skipped:
        raise RuntimeError("required_tests_failed_or_empty_or_skipped")

def units(directory, names):
    # Each group runs in a fresh interpreter: avoid module-name/path collisions.
    code = """
import io,json,socket,subprocess,sys,unittest
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
    subprocess.run([sys.executable,"-I","-B","-c",code,str(ROOT),directory]+names,check=True,timeout=90,cwd=ROOT)

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
    if select(["README.md"]) or select(["tools/pr_fast.py"])!=["self"]:
        raise RuntimeError("docs_or_dispatcher_scope_changed")
    if select(["releases/fc-coins/noncore-emergency-20261009/source/fc27_quote_engine.py"]) != ["fc-noncore"]:
        raise RuntimeError("fc_noncore_scope_missing")
    print("path/structure selfcheck: HTML/CSS-only and mixed paths checked; valid/malformed examples and existing FC templates checked")
    print("coverage selfcheck: unmapped runtime formats/workflows and frontend deletions rejected; HTML non-void slash handled as open tag")
    rename_source_selfcheck()
    print("selfcheck: PASS and FAIL/error/skip/zero propagate correctly")

def select(paths):
    groups=set();unmapped=[]
    for name in paths:
        suffix=Path(name).suffix
        if name.startswith("releases/fc-coins/noncore-emergency-20261009/"):
            groups.add("fc-noncore");continue
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
        elif group=="builder":units("tools",["test_business_html_build"])
        elif group=="registration-delta":
            subprocess.run([sys.executable,"-I","-B",str(ROOT/"tests/registration-release-delta-qa-20261007/linux_delta_entry.py"),"--driver-check"],check=True,timeout=30,cwd=ROOT)
    print(json.dumps({"result":"PASS","affected_groups":groups,"syntax_scope":"changed files only","live_not_tested":True}))
if __name__=="__main__":main()

