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
    print("path/structure selfcheck: HTML/CSS-only and mixed paths checked; valid/malformed examples and existing FC templates checked")
    print("coverage selfcheck: unmapped runtime formats/workflows and frontend deletions rejected; HTML non-void slash handled as open tag")
    print("selfcheck: PASS and FAIL/error/skip/zero propagate correctly")

def select(paths):
    groups=set();unmapped=[]
    for name in paths:
        suffix=Path(name).suffix
        if suffix in (".sql",".service",".timer") or (name.startswith(".github/workflows/") and name!=".github/workflows/pr-fast.yml"):
            unmapped.append(name);continue
        if name.startswith("tools/pr_fast") or name==".github/workflows/pr-fast.yml":
            groups.add("self");continue
        if suffix not in (".py",".js",".cjs",".sh",".html",".css"):continue
        if suffix in (".html",".css"):
            groups.add("frontend");continue
        if name.startswith("candidates/fc-coins/player-supersession-20261007-v4-2-3/source/") and "/app/" not in name:groups.add("supersession")
        elif name=="fc27_quote_engine.py" or name=="test_fc27_quote_engine.py" or name.startswith("docs/fc27-coins/discount-config-release-20261005/tests/"):groups.add("engine")
        elif name.startswith("fc27_cloud_browser/"):groups.add("fc-control")
        elif name=="fc27_players_cloud/player_web/price_lock.py":groups.add("players")
        elif name in ("opt/d4follow/engine.py","opt/d4follow/gates.py"):groups.add("rpg")
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
        elif group=="supersession":units("tools",["pr_fast_tests.CurrentSupersession"])
        elif group=="players":units("tools",["pr_fast_tests.PlayersLock"])
        elif group=="rpg":units("tools",["pr_fast_tests.RPGGuards"])
        elif group=="aion":node("aion2_dashboard_20261004/test_status.cjs")
        elif group=="nba":node("tests/integration/test_nba_pure_guards.cjs")
        elif group=="fc-control":
            if "engine" not in groups:units(".",["test_fc27_quote_engine"])
            units("fc27_cloud_browser",["test_automation_policy","test_coin_all_sync","test_source_confirmation","test_player_sync_recovery","test_player_sync_bulk"])
        elif group=="builder":units("tools",["test_business_html_build"])
    print(json.dumps({"result":"PASS","affected_groups":groups,"syntax_scope":"changed files only","live_not_tested":True}))
if __name__=="__main__":main()
