"""CAS the original startup source and container, then verify one locked restart."""
from contextlib import ExitStack
from datetime import datetime,timezone
import base64
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0,'/opt/fc27-cloud-browser')
import automation_tick as tick
import fc27_cloud_api as api
from snapshot_layer import ROOT,atomic_json
import browser_lifecycle as lifecycle

FOLDER=Path(__file__).parent
TARGET=Path('/opt/fc27-cloud-browser/start.sh')
BEFORE='aaf1bd6e6103c000242e8986402808915d743655724dbe822b458cbc07f831fa'
AFTER='d646762e232c3dd161e4270967956368c4850bdb646bbf631924ddb86fc28f98'
RECEIPT=ROOT/'recovery-receipts/browser-startup-release-20261023.json'
COOKIE_PROBE=r'''
import hashlib,json,sys,time
sys.path.insert(0,'/opt/fc27-collector')
from playwright.sync_api import sync_playwright
from lootbar_server_collector import _is_product_page,load_reader,_park_product_page
with sync_playwright() as p:
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=4000,no_defaults=True)
 assert len(b.contexts)==1
 ctx=b.contexts[0]
 pages=[x for x in ctx.pages if _is_product_page(x) or x.url=='about:blank#fc27-idle']
 assert len(pages)==1
 page=pages[0]
 cookies=ctx.cookies(['https://www.lootbar.com/'])
 result={'cookie_count':len(cookies),'cookie_names_sha256':hashlib.sha256(json.dumps(sorted((c['name'],c['domain']) for c in cookies)).encode()).hexdigest()}
 if sys.argv[1]=='after':
  assert _is_product_page(page)
  page.wait_for_function('() => { '+load_reader()+'; return readVisibleOffer().loggedIn === true; }',timeout=20000)
  result['logged_in']=True
  _park_product_page(page)
  cdp=b.new_browser_cdp_session()
  try:
   deadline=time.monotonic()+2
   while True:
    result['lootbar_blob_workers']=len([x for x in cdp.send('Target.getTargets')['targetInfos'] if x.get('type')=='worker' and x.get('url','').startswith('blob:https://www.lootbar.com/')])
    if not result['lootbar_blob_workers'] or time.monotonic()>=deadline:break
    time.sleep(.05)
  finally:cdp.detach()
 print(json.dumps(result))
'''

def sha(data):return hashlib.sha256(data).hexdigest()

def inside(args,**kwargs):
    return subprocess.run(['docker','exec','-i','-u','0','fc27-cloud-browser',*args],capture_output=True,check=True,timeout=35,**kwargs)

def cookie_probe(action):
    result=subprocess.run(['docker','exec','-i','-u','fc27chrome','fc27-cloud-browser','python3','-',action],
                          input=COOKIE_PROBE,text=True,capture_output=True,timeout=30)
    if result.returncode:raise RuntimeError('session_readback_failed_preserve_original_receipt')
    return json.loads(result.stdout.splitlines()[-1])

def main():
    source=(FOLDER/'source/start.sh').read_bytes()
    assert sha(source)==AFTER and sha(TARGET.read_bytes())==BEFORE
    subprocess.run(['sh','-n',str(FOLDER/'source/start.sh')],check=True,timeout=5)
    assert not RECEIPT.exists(),'reconcile_original_restart'
    spec=importlib.util.spec_from_file_location('startup_fc_publisher',ROOT/'maintenance/local-collection-20261017/publish.py')
    pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
    with tick.queue_mutation(),ExitStack() as held:
        for path in ('/var/lock/fs-navigation-release.lock','/var/lock/fs-dashboard-release.lock'):
            lock=held.enter_context(Path(path).open('r+b'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for name in tick.RETRY_LOCKS:
            lock=held.enter_context((ROOT/'state'/name).open('rb'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert tick.retry_guard()=='ready' and api.health()['incomplete_executions']==0
        assert not list((ROOT/'queue').glob('*.json'))
        assert not any(json.loads(p.read_text()).get('status') in ('queued','running') for p in (ROOT/'jobs').glob('*.json'))
        proof=json.loads(lifecycle.ORDER_ISOLATION.read_text())
        assert proof['status']=='verified' and proof['durability_verified'] is True
        assert proof['service_sha256']==sha(lifecycle.ORDER_SERVICE.read_bytes())
        old_state=json.loads((ROOT/'state/browser-lifecycle.json').read_text())
        assert old_state.get('state') not in ('started','unknown')
        original=inside(['cat','/usr/local/bin/fc27-browser-start']).stdout
        assert sha(original)==BEFORE and sha(TARGET.read_bytes())==BEFORE
        backup=ROOT/'rollback/browser-startup-release-20261023';backup.mkdir(mode=0o700)
        (backup/'start.sh').write_bytes(original)
        atomic_json(backup/'lifecycle-before.json',old_state)
        before_cookies=cookie_probe('before')
        protected={str(p):sha(p.read_bytes()) for p in [ROOT/'config/automation.json',ROOT/'jobs/9c4fd616-9a97-45d6-990f-e8e8af598d4f.json']}
        now=datetime.now(timezone.utc).timestamp()
        event=dict(state='started',action='restart',event_id=str(uuid.uuid4()),at=now,last_restart_at=now,
                   before_container=lifecycle.container_state(),startup_source_sha256=AFTER,
                   price_requests=0,session_deleted=False,backup=str(backup),before_cookies=before_cookies,protected=protected)
        atomic_json(RECEIPT,event)
        pub.publish(FOLDER/'source/start.sh',TARGET,TARGET.stat())
        inner="""import base64,hashlib,os,stat,tempfile
from pathlib import Path
p=Path('/usr/local/bin/fc27-browser-start')
assert hashlib.sha256(p.read_bytes()).hexdigest()==%r
raw=base64.b64decode(%r);meta=p.stat()
fd,name=tempfile.mkstemp(prefix='.fc27-start-',dir=p.parent)
with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
os.chmod(name,stat.S_IMODE(meta.st_mode));os.chown(name,meta.st_uid,meta.st_gid)
assert hashlib.sha256(p.read_bytes()).hexdigest()==%r
os.replace(name,p)
assert hashlib.sha256(p.read_bytes()).hexdigest()==%r
"""%(BEFORE,base64.b64encode(source).decode(),BEFORE,AFTER)
        inside(['python3','-'],input=inner,text=True)
        assert sha(TARGET.read_bytes())==AFTER
        atomic_json(ROOT/'state/browser-lifecycle.json',event)
        try:
            subprocess.run(['docker','restart','-t','20','fc27-cloud-browser'],check=True,timeout=45,stdout=subprocess.DEVNULL)
            deadline=time.monotonic()+35
            while lifecycle.probe()['status']!='ok':
                if time.monotonic()>=deadline:raise RuntimeError('browser_startup_readback_timeout')
                time.sleep(1)
            after_cookies=cookie_probe('after')
            event['after_cookies']=after_cookies
            assert after_cookies['logged_in'] is True and after_cookies['lootbar_blob_workers']==0
            assert after_cookies['cookie_count']>0
            with urllib.request.urlopen('http://127.0.0.1:8768/health',timeout=4) as response:order=json.load(response)
            assert order['ready'] is True and order['login_attempts']==0
            assert all(sha(Path(p).read_bytes())==value for p,value in protected.items())
            assert sha(inside(['cat','/usr/local/bin/fc27-browser-start']).stdout)==AFTER
            event.update(state='verified',after_cookies=after_cookies,after_memory_bytes=lifecycle.memory_bytes(),
                         reconciled_container=lifecycle.container_state(),order_ready=True,
                         verified_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            event.update(state='unknown',error=type(error).__name__)
            raise
        finally:
            atomic_json(RECEIPT,event);atomic_json(ROOT/'state/browser-lifecycle.json',event)
        print(json.dumps(event))

if __name__=='__main__':main()
