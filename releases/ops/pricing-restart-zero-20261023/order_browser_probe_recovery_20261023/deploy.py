"""Original Order publisher, business fences and same-profile identity readback."""
from contextlib import ExitStack
from datetime import datetime,timezone
import fcntl,hashlib,json,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,'/opt/d4follow/_stage-p0-20261023')
sys.path.insert(0,'/opt/fc27-cloud-browser')
from deploy_fc import publish
from deploy_order_isolation import business_idle,idle
from snapshot_layer import atomic_json
TARGET=Path('/opt/fs-order-session/service.py')
BEFORE='e94f54cebe50cbede113ce4205ad2fe337b176438e0e864c1caa73ae90d3c88a'
AFTER='89e8b6bba49397499c39c697f54d44a8ab892aed23fefafe34df0824058c0353'
ISOLATION=Path('/var/lib/fs-order-session/browser-isolation-20261023.json')
RECEIPT=Path('/var/lib/fs-order-session/probe-deadline-recovery-20261023.json')
OP='order-browser-probe-deadline-20261023-v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inspect():return json.loads(subprocess.check_output(['docker','inspect','--format','{{json .}}','fs-order-browser'],text=True,timeout=5))
def health():
    with urllib.request.urlopen('http://127.0.0.1:8768/health',timeout=5) as response:return json.load(response)
def main(apply=False):
    candidate=Path(__file__).parent/'source/service.py'
    assert not RECEIPT.exists(),'reconcile_original_deployment'
    assert sha(TARGET)==BEFORE and sha(candidate)==AFTER
    assert subprocess.check_output(['docker','exec','fs-order-browser','timeout','--version'],text=True,timeout=5).startswith('timeout (GNU coreutils)')
    original_isolation=ISOLATION.read_bytes();proof=json.loads(original_isolation)
    assert proof.get('status')=='verified' and proof.get('durability_verified') is True and proof.get('service_sha256')==BEFORE
    with business_idle(),ExitStack() as held:
        lock=held.enter_context(Path('/run/fs-order-browser-isolation.lock').open('a+b'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        current=inspect();assert current['State']['Running'] and '--restore-last-session' in current['Config']['Cmd']
        assert any(m['Source']=='/var/lib/fs-order-session/browser' and m['Destination']==m['Source'] for m in current['Mounts'])
        before_health=health();assert before_health['ready'] is True and before_health['login_attempts']==0
        assert ISOLATION.read_bytes()==original_isolation and sha(TARGET)==BEFORE
        if not apply:return {'status':'checked','targets':1,'container_restart':False}
        started=datetime.now(timezone.utc)
        event=dict(operation=OP,status='started',before=BEFORE,after=AFTER,started_at=started.isoformat(),price_requests=0,
                   profile_preserved=True,container_restarted=False,original_isolation_sha256=hashlib.sha256(original_isolation).hexdigest())
        atomic_json(RECEIPT,event)
        backup=Path('/var/backups')/OP
        try:
            publish({str(TARGET):candidate.read_text('utf-8')},OP)
            (backup/'browser-isolation-before.json').write_bytes(original_isolation)
            assert sha(TARGET)==AFTER
            subprocess.run(['systemctl','restart','fs-order-session.service'],check=True,timeout=20)
            deadline=time.monotonic()+40
            while True:
                try:
                    value=health()
                    if value['ready'] is True and value['login_attempts']==0:break
                except (OSError,ValueError,KeyError):pass
                if time.monotonic()>=deadline:raise RuntimeError('new_probe_identity_unverified')
                time.sleep(1)
            after=inspect();assert after['Id']==current['Id'] and after['State']['StartedAt']==current['State']['StartedAt']
            assert sha(TARGET)==AFTER and ISOLATION.read_bytes()==original_isolation
            proof.update(service_sha256=AFTER,probe_deadline_recovery={'operation':OP,'service_before':BEFORE,'service_after':AFTER,
                         'verified_at':datetime.now(timezone.utc).isoformat(),'profile_preserved':True,'original_durability_proof_retained':True,
                         'container_id':after['Id'],'started_at':after['State']['StartedAt'],'login_attempts':0})
            atomic_json(ISOLATION,proof)
            event.update(status='verified',health={k:value.get(k) for k in ('ready','last_error','login_attempts','probe_seconds')},
                         finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            event.update(status='unknown',error=type(error).__name__)
            atomic_json(RECEIPT,event)
            raise
        atomic_json(RECEIPT,event)
        return event
if __name__=='__main__':print(json.dumps(main('--apply' in sys.argv)))
