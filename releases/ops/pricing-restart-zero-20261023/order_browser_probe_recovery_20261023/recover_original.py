"""One original-container restart under existing business fences; never log in."""
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, '/opt/d4follow/_stage-p0-20261023')
sys.path.insert(0, '/opt/fc27-cloud-browser')
from deploy_order_isolation import business_idle, idle
from snapshot_layer import atomic_json

CONTAINER = 'fs-order-browser'
EXPECTED_ID = '19407709f0dbf35e140df40d7bc3f9b8de9e92ab68553c39ca049f5fa2eeb735'
EXPECTED_START = '2026-10-23T03:57:22.386534092Z'
SERVICE = Path('/opt/fs-order-session/service.py')
EXPECTED_SERVICE = 'e94f54cebe50cbede113ce4205ad2fe337b176438e0e864c1caa73ae90d3c88a'
RECEIPT = Path('/var/lib/fs-order-session/order-browser-oom-recovery-20261023-v1.json')
PROFILE = Path('/var/lib/fs-order-session/browser')


def inspect():
    return json.loads(subprocess.check_output(['docker','inspect','--format','{{json .}}',CONTAINER],text=True,timeout=5))


def evidence(value):
    root=Path('/sys/fs/cgroup/memory/docker')/value['Id']
    return dict(container_id=value['Id'],state={k:value['State'].get(k) for k in ('Running','Restarting','OOMKilled','StartedAt','FinishedAt')},
                restart_count=value['RestartCount'],image=value['Image'],memory_limit=value['HostConfig']['Memory'],
                cgroup={name:(root/name).read_text().strip() for name in ('memory.usage_in_bytes','memory.failcnt','memory.stat','memory.oom_control')})


def no_active_rpg_container():
    identities=subprocess.check_output(['docker','ps','--filter','ancestor=p2pah-srv:1','--format','{{.ID}}'],text=True,timeout=5).split()
    if identities:
        raise RuntimeError('active_rpg_execution_container')


def main():
    if RECEIPT.exists():
        raise RuntimeError('reconcile_original_restart_receipt_no_replay')
    event=None
    with business_idle(), ExitStack() as held:
        isolation=held.enter_context(Path('/run/fs-order-browser-isolation.lock').open('a+b'))
        fcntl.flock(isolation,fcntl.LOCK_EX|fcntl.LOCK_NB)
        idle(); no_active_rpg_container()
        assert hashlib.sha256(SERVICE.read_bytes()).hexdigest()==EXPECTED_SERVICE,'service_source_drift'
        before=inspect()
        assert before['Id']==EXPECTED_ID and before['State']['StartedAt']==EXPECTED_START,'container_changed_reconcile'
        assert before['State']['Running'] and not before['State']['Restarting'],'container_not_running'
        assert '--restore-last-session' in before['Config']['Cmd'],'durable_session_flag_missing'
        assert any(m['Source']==str(PROFILE) and m['Destination']==str(PROFILE) for m in before['Mounts']),'durable_profile_mapping_changed'
        active=subprocess.check_output(['systemctl','is-active','p2pah-srv-exec.service'],text=True,timeout=5).strip()=='active'
        assert active,'original_executor_inactive'
        event=dict(operation='order-browser-oom-recovery-20261023-v1',status='prepared',before=evidence(before),
                   service_sha256=EXPECTED_SERVICE,profile=str(PROFILE),profile_preserved=True,cookies_read=False,
                   price_requests=0,login_attempts=0,started_at=datetime.now(timezone.utc).isoformat())
        atomic_json(RECEIPT,event)
        execution=None
        try:
            subprocess.run(['systemctl','stop','p2pah-srv-exec.service'],check=True,timeout=20)
            execution=held.enter_context(Path('/opt/d4follow/data/srv_exec.lock').open('r+b'))
            fcntl.flock(execution,fcntl.LOCK_EX|fcntl.LOCK_NB)
            idle(); no_active_rpg_container()
            current=inspect()
            assert current['Id']==EXPECTED_ID and current['State']['StartedAt']==EXPECTED_START,'container_changed_reconcile'
            event['status']='unknown'; event['restart_issued_at']=datetime.now(timezone.utc).isoformat()
            atomic_json(RECEIPT,event)
            subprocess.run(['docker','restart','-t','20',CONTAINER],check=True,timeout=45,stdout=subprocess.DEVNULL)
            after=inspect();event['after']=evidence(after)
            assert after['Id']==EXPECTED_ID and after['State']['StartedAt']!=EXPECTED_START,'restart_unconfirmed'
            deadline=time.monotonic()+50
            while True:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8768/health',timeout=4) as response:
                        health=json.load(response)
                    event['health']={k:health.get(k) for k in ('ready','checking','last_error','verified_age_seconds','probe_seconds','login_attempts')}
                    checked=datetime.now(timezone.utc).timestamp()-float(health['verified_age_seconds'])
                    started=datetime.fromisoformat(after['State']['StartedAt'][:26]+'+00:00').timestamp()
                    if health.get('ready') is True and health.get('login_attempts')==0 and checked>=started:
                        break
                except (OSError,ValueError,TypeError,KeyError):
                    pass
                if time.monotonic()>=deadline:
                    raise RuntimeError('native_order_upkeep_identity_unverified')
                time.sleep(2)
            assert hashlib.sha256(SERVICE.read_bytes()).hexdigest()==EXPECTED_SERVICE,'service_changed_during_recovery'
            event.update(status='verified',finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as error:
            event.update(status='unknown',error=type(error).__name__)
            raise
        finally:
            if event is not None:atomic_json(RECEIPT,event)
            if execution is not None:
                fcntl.flock(execution,fcntl.LOCK_UN)
                execution.close()
            subprocess.run(['systemctl','start','p2pah-srv-exec.service'],check=True,timeout=20)
    print(json.dumps(event))


if __name__=='__main__':main()
