"""Install only this new monitor namespace. Never changes business services or timers."""
import argparse, hashlib, json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

FILES={'collector.py','probe_worker.py','read_only_status.py','report.py','delivery.py',
       'test_monitor.py','fc-ops-readonly-monitor.service','fc-ops-readonly-monitor.timer'}
APP=Path('/opt/fc-ops-readonly-monitor')
DATA=Path('/var/lib/fc-ops-readonly-monitor')
UNITS=Path('/etc/systemd/system')
PROTECTED=[Path('/opt/fc27-cloud-browser')/name for name in
           ['fc27_cloud_api.py','fc27_cloud_worker.py','automation_tick.py','automation_policy.py',
            'player_sync_job.py','player_sync_policy.py','price_writer.py']]
PROTECTED += [Path('/var/lib/fc27-cloud/config')/name for name in ['automation.json','player-sync.json']]
SERVICES=['fc27-cloud-api.service','fc27-cloud-worker.service','fc27-gallery.service',
          'fc27-gate.service','fc27-player-tool.service','cloudmonitor.service']

def run(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=60)
    if p.returncode:raise RuntimeError('command_failed:'+args[0]+':'+str(p.returncode))
    return p.stdout

def baseline():
    return {'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED},
            'services':{u:run(['systemctl','show',u,'--property=MainPID','--property=ActiveState']).strip()
                        for u in SERVICES}}



def upgrade(stage, apply):
    import fcntl, shutil, tempfile
    names = {'collector.py','probe_worker.py','delivery.py','hooks.py','hooks_notifier.py'}
    rows = json.loads((stage/'hooks-monitor-manifest.json').read_text())['files']
    if os.geteuid()!=0 or {r['name'] for r in rows}!=names or len(rows)!=len(names):
        raise ValueError('exact_monitor_upgrade_required')
    for row in rows:
        source = stage/'source'/row['name']; target=APP/row['name']
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=row['after']:
            raise ValueError('payload_changed')
        actual=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if target.is_symlink() or actual!=row['before']:raise ValueError('monitor_baseline_changed')
        compile(source.read_text(),row['name'],'exec')
    tests=subprocess.run(['/usr/bin/python3','-B','-m','unittest','discover','-s',str(stage/'source'),'-p','test_*.py'],capture_output=True,text=True,timeout=60)
    (stage/'linux-tests.txt').write_text(tests.stderr,encoding='utf-8')
    if tests.returncode or 'skipped=' in tests.stderr or 'Ran 31 tests' not in tests.stderr:
        raise RuntimeError('required_linux_checks_failed')
    before=baseline(); receipt={'checks':'31 Linux checks, zero skips','applied':False,'before':before}
    if apply:
        with (DATA/'.collector.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            backup=DATA/'code-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backup.mkdir(parents=True,mode=0o700)
            for row in rows:
                target=APP/row['name']
                actual=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
                if actual!=row['before']:raise ValueError('monitor_baseline_changed_under_lock')
                if target.exists():shutil.copy2(target,backup/row['name'])
            metadata=DATA.stat();receipt['original_data_metadata']=[metadata.st_uid,metadata.st_gid,metadata.st_mode&0o7777]
            try:
                for row in rows:
                    target=APP/row['name'];temporary=APP/('.hooks-'+row['name'])
                    with temporary.open('xb') as stream:
                        stream.write((stage/'source'/row['name']).read_bytes());stream.flush();os.fsync(stream.fileno())
                    temporary.chmod(0o644);os.replace(temporary,target)
                gates=DATA/'gates';gates.mkdir(exist_ok=True);os.chown(gates,0,11028);gates.chmod(0o2750)
                os.chown(DATA,0,11028);DATA.chmod(0o710)
                receipt.update(applied=True,backup=str(backup))
            except Exception:
                for row in rows:
                    target=APP/row['name']
                    if row['before'] is not None:shutil.copy2(backup/row['name'],target)
                os.chown(DATA,metadata.st_uid,metadata.st_gid);DATA.chmod(metadata.st_mode&0o7777)
                raise
    receipt['after']=baseline();receipt['protected_unchanged']=receipt['after']==before
    if not receipt['protected_unchanged']:raise RuntimeError('protected_baseline_changed')
    (stage/'monitor-upgrade-receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--stage',required=True,type=Path)
    parser.add_argument('--apply',action='store_true'); parser.add_argument('--upgrade',action='store_true'); args=parser.parse_args()
    stage=args.stage.resolve()
    if not stage.name.startswith('fc-ops-monitor-stage-') or stage.parent!=Path('/opt') or args.stage.is_symlink():
        raise ValueError('fixed_isolated_stage_required')
    if args.upgrade:
        return upgrade(stage,args.apply)
    rows=json.loads((stage/'manifest.json').read_text())['files']
    if {r['name'] for r in rows}!=FILES or len(rows)!=len(FILES):raise ValueError('exact_files_required')
    for row in rows:
        p=stage/'source'/row['name']
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('payload_changed')
    targets={row['name']:(UNITS/row['name'] if row['name'].endswith(('.service','.timer')) else APP/row['name']) for row in rows}
    if APP.exists() or DATA.exists() or any(p.exists() or p.is_symlink() for p in targets.values()):
        raise ValueError('new_namespace_only_no_overwrite')
    before=baseline()
    tests=subprocess.run(['/usr/bin/python3','-B','-m','unittest','discover','-s',str(stage/'source'),'-p','test_monitor.py'],
                         capture_output=True,text=True,timeout=60)
    if tests.returncode or 'Ran 16 tests' not in tests.stderr or not tests.stderr.rstrip().endswith('OK'):
        raise RuntimeError('linux_tests_not_complete')
    (stage/'linux-tests.txt').write_text(tests.stderr,encoding='utf-8')
    verify=subprocess.run(['systemd-analyze','verify',str(stage/'source'/'fc-ops-readonly-monitor.service'),
                            str(stage/'source'/'fc-ops-readonly-monitor.timer')],capture_output=True,text=True,timeout=20,
                          env={**os.environ,'SYSTEMD_UNIT_PATH':str(stage/'source')+':/usr/lib/systemd/system'})
    if verify.returncode or verify.stderr.strip():raise RuntimeError('unit_validation_failed')
    receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'linux_tests':'16 passed',
             'unit_verify':'passed','before':before,'applied':False,'outbound_configured':False,
             'computer_inspection_replaced':False}
    if args.apply:
        APP.mkdir(mode=0o755); DATA.mkdir(mode=0o700)
        for name,target in targets.items():
            with target.open('xb') as stream:
                stream.write((stage/'source'/name).read_bytes()); stream.flush(); os.fsync(stream.fileno())
            target.chmod(0o644)
        run(['systemctl','daemon-reload'])
        receipt['applied']=True
    after=baseline(); receipt['after']=after; receipt['protected_unchanged']=before==after
    if before!=after:raise RuntimeError('protected_baseline_changed')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
