"""Unify the existing Feishu gateway with the FS server profile; preview first."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

OLD = Path('/var/lib/hermes-dingtalk/profile')
MAIN = Path('/var/lib/fs-hermes-fc/profile')
UNIT = Path('/etc/systemd/system/hermes-dingtalk.service')
BRIDGE = Path('/opt/fs-hermes-ops/host.py')
BACKUP = Path('/var/backups/hermes-server-unify-20261022')
JOB = '0018aa8c8439'
SERVICE = '''[Unit]
Description=Hermes Feishu gateway on the shared FS server profile
After=docker.service fs-hermes-desktop.service
Requires=docker.service
Wants=fs-hermes-desktop.service
PartOf=fs-hermes-desktop.service

[Service]
Type=simple
ExecStart=/usr/bin/docker exec --env HERMES_ALLOW_ROOT_GATEWAY=1 fs-hermes-desktop /opt/hermes/.venv/bin/python -m hermes_cli.main gateway run
ExecStop=/usr/bin/docker exec fs-hermes-desktop /opt/hermes/.venv/bin/python -m hermes_cli.main gateway stop
TimeoutStartSec=90
TimeoutStopSec=45
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
'''


def stop_existing_main_gateway():
    # Both transports must use the same process namespace as well as the same profile.
    return native('fs-hermes-desktop', '''
from pathlib import Path
import json,os,signal,time,psutil
p=Path('/profile/.local/state/hermes/gateway-locks/host-gateway.json')
if p.exists():
 d=json.loads(p.read_text());pid=d['pid']
 assert d['role']=='gateway' and d.get('home')=='/profile' and pid>1
 proc=psutil.Process(pid)
 args=proc.cmdline()
 assert 'gateway' in args and 'run' in args and any('hermes' in a for a in args)
 assert abs(proc.create_time()-d['createTime'])<1
 assert proc.environ().get('HERMES_HOME')=='/profile'
 proc.send_signal(signal.SIGTERM)
 for _ in range(150):
  if not proc.is_running() or proc.status()==psutil.STATUS_ZOMBIE:break
  time.sleep(0.2)
 else:raise RuntimeError('main_gateway_did_not_drain')
 print('existing_main_gateway_gracefully_stopped')
''')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run(args, data=None):
    return subprocess.run(args, input=data, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True).stdout


def native(container, code):
    return run(['docker', 'exec', '-i', container, '/opt/hermes/.venv/bin/python', '-'], code)


def atomic(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = path.stat() if path.exists() else None
    fd, name = tempfile.mkstemp(prefix='.unify-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        if previous is not None and hasattr(os, 'chown'):
            os.chown(name, previous.st_uid, previous.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_receipt(value):
    atomic(BACKUP/'receipt.json', json.dumps(value, ensure_ascii=False, indent=2).encode())


def preflight():
    assert OLD != MAIN and OLD.is_dir() and MAIN.is_dir()
    assert (OLD/'memories/MEMORY.md').read_bytes() == (MAIN/'memories/MEMORY.md').read_bytes()
    for p in (OLD/'business-context').glob('*.md'):
        assert p.read_bytes() == (MAIN/'business-context'/p.name).read_bytes()
    source_jobs = json.loads((OLD/'cron/jobs.json').read_text())['jobs']
    target_jobs = json.loads((MAIN/'cron/jobs.json').read_text())['jobs']
    job = next(j for j in source_jobs if j['id'] == JOB)
    assert len(source_jobs) == 1 and not any(j['id'] == JOB for j in target_jobs)
    assert job['enabled'] and job['no_agent'] and not job.get('fire_claim')
    assert job['schedule']['expr'] == '0 0,15,18,21 * * *'
    assert job['last_status'] == 'ok' and not job.get('failure_streak')
    assert job['script'] == '/profile/scripts/fs-ops-watchdog/watch.py'
    for container in ['hermes-dingtalk', 'fs-hermes-desktop']:
        count = native(container, '''
import sqlite3
from contextlib import closing
with closing(sqlite3.connect('file:/profile/cron/executions.db?mode=ro',uri=True)) as c:
 print(c.execute("SELECT count(*) FROM executions WHERE status IN ('claimed','running','queued')").fetchone()[0])
''')
        assert int(count) == 0
    assert BRIDGE.read_bytes().count(str(OLD/'ops-watchdog').encode()) == 1
    assert UNIT.read_bytes().count(('source='+str(OLD)+',target=/profile').encode()) == 1
    assert '--name hermes-dingtalk ' in UNIT.read_text()
    assert not (MAIN/'ops-watchdog').exists()
    assert not (MAIN/'scripts/fs-ops-watchdog').exists()
    assert not (MAIN/'skills/fs-operations/fs-ops-watchdog').exists()
    paths = [UNIT, BRIDGE, MAIN/'AGENTS.md', MAIN/'cron/jobs.json', OLD/'cron/jobs.json',
             OLD/'.env', MAIN/'.env', OLD/'memories/MEMORY.md', MAIN/'memories/MEMORY.md']
    hashes = {str(p): sha(p.read_bytes()) for p in paths}
    result = {'hashes': hashes, 'job_id': JOB, 'repeat': job['repeat'],
              'next_run_at': job['next_run_at'], 'target_existing_jobs': len(target_jobs)}
    return result, job


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-plan')
    parser.add_argument('--finish-gateway', action='store_true')
    parser.add_argument('--expected-unit')
    args = parser.parse_args()
    if args.finish_gateway:
        receipt=json.loads((BACKUP/'receipt.json').read_text())
        assert receipt['stage']=='started_readback_required'
        assert sha(UNIT.read_bytes())==args.expected_unit
        shutil.copy2(UNIT,BACKUP/'container-start-refused.service')
        stop_existing_main_gateway()
        atomic(UNIT,SERVICE.encode(),0o644)
        run(['systemctl','daemon-reload'])
        run(['systemctl','start','hermes-dingtalk.service'])
        receipt['gateway_strategy']='systemd-supervised process in existing FS server container'
        receipt['after_hashes'][str(UNIT)]=sha(UNIT.read_bytes())
        save_receipt(receipt)
        print(json.dumps(receipt))
        return
    plan, job = preflight()
    fingerprint = sha(json.dumps(plan, sort_keys=True).encode())
    if not args.apply:
        print(json.dumps({'preview': plan, 'plan_sha256': fingerprint}))
        return
    assert os.geteuid() == 0 and args.expected_plan == fingerprint, 'fresh preview required'
    assert not BACKUP.exists(), 'existing receipt must be reconciled before retry'
    BACKUP.mkdir(mode=0o700)
    receipt = {'plan_sha256': fingerprint, 'stage': 'backing_up', 'job_id': JOB}
    save_receipt(receipt)
    for p in [UNIT, BRIDGE, MAIN/'AGENTS.md', MAIN/'cron/jobs.json', OLD/'cron/jobs.json']:
        dest = BACKUP/str(p).lstrip('/')
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(p, dest)
    for label, base, container in [('old', OLD, 'hermes-dingtalk'), ('main', MAIN, 'fs-hermes-desktop')]:
        native(container, '''
import sqlite3
from pathlib import Path
from contextlib import closing
dest=Path('/profile/backups/server-unify-20261022/executions.db')
dest.parent.mkdir(parents=True,exist_ok=True)
assert not dest.exists()
with closing(sqlite3.connect('file:/profile/cron/executions.db?mode=ro',uri=True)) as c:
 with closing(sqlite3.connect(str(dest))) as out:c.backup(out)
''')
        shutil.copy2(base/'backups/server-unify-20261022/executions.db', BACKUP/(label+'-executions.db'))
    try:
        run(['systemctl', 'stop', 'fs-hermes-ops-bridge.timer'])
        run(['systemctl', 'stop', 'fs-hermes-ops-bridge.service'])
        native('hermes-dingtalk', "from cron import jobs\nj=jobs.pause_job('"+JOB+"', reason='Migrated to FS shared server profile on 2026-10-22')\nassert j and not j['enabled']\n")
        run(['systemctl', 'stop', 'hermes-dingtalk.service'])
        receipt['stage'] = 'old_gateway_stopped'
        save_receipt(receipt)
        for rel in ['ops-watchdog', 'scripts/fs-ops-watchdog', 'skills/fs-operations/fs-ops-watchdog']:
            (MAIN/rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(OLD/rel, MAIN/rel)
        archive = MAIN/'server-migration-20261022'
        archive.mkdir(mode=0o700)
        shutil.copy2(OLD/'memories/USER.md', archive/'previous-gateway-USER.md')
        shutil.copy2(BACKUP/'old-executions.db', archive/'old-executions.db')
        # Keep newer main skills and USER, and preserve the old differing USER for review.
        agents = (MAIN/'AGENTS.md').read_text()
        group = (OLD/'AGENTS.md').read_text().split('# 飞书群协作', 1)[1]
        group = group.replace('每小时只读巡检', '北京时间每日23/02/05/08点只读巡检')
        note = '\n\n## 2026-10-22 服务器统一入口\n飞书群、服务器客户端和FS共用本/profile记忆与技能。terminal.backend=local表示当前服务器容器，不是用户的Windows电脑。/fs与/fs-source已实际挂载；先核实工具和文件，不因local字样声称必须派给另一台服务器。\n'
        assert '# 飞书群协作' not in agents
        atomic(MAIN/'AGENTS.md', (agents+'\n\n# 飞书群协作'+group+note).encode(), (MAIN/'AGENTS.md').stat().st_mode & 0o777)
        old_unit = UNIT.read_bytes()
        assert sha(old_unit) == plan['hashes'][str(UNIT)]
        new_unit = SERVICE.encode()
        atomic(UNIT, new_unit, 0o644)
        old_bridge = BRIDGE.read_bytes()
        assert sha(old_bridge) == plan['hashes'][str(BRIDGE)]
        atomic(BRIDGE, old_bridge.replace(str(OLD/'ops-watchdog').encode(), str(MAIN/'ops-watchdog').encode()), 0o644)
        job_payload = repr(job)
        code = '''
import json,sqlite3
from pathlib import Path
from cron import jobs
job = JOB_PAYLOAD
with jobs._jobs_lock():
 before=jobs.load_jobs()
 assert not any(j['id']==job['id'] for j in before)
 c=sqlite3.connect('/profile/cron/executions.db')
 c.execute("ATTACH DATABASE '/profile/server-migration-20261022/old-executions.db' AS old")
 columns=[r[1] for r in c.execute('PRAGMA table_info(executions)')]
 assert columns==[r[1] for r in c.execute('PRAGMA old.table_info(executions)')]
 rows=c.execute('SELECT * FROM old.executions WHERE job_id=?',(job['id'],)).fetchall()
 assert all(c.execute('SELECT count(*) FROM executions WHERE id=?',(r[0],)).fetchone()[0]==0 for r in rows)
 for r in rows:c.execute('INSERT INTO executions VALUES ('+','.join('?' for _ in columns)+')',r)
 c.commit();c.close()
 jobs.save_jobs(before+[job])
 after=jobs.load_jobs()
 assert next(j for j in after if j['id']==job['id'])==job
 assert [j for j in after if j['id']!=job['id']]==before
 print(json.dumps({'migrated_executions':len(rows),'preserved_other_jobs':len(before)}))
'''.replace('JOB_PAYLOAD', job_payload)
        receipt['native_transfer'] = json.loads(native('fs-hermes-desktop', code))
        # Retain original execution logs under the identical job ID.
        outputs = OLD/'cron/output'/JOB
        if outputs.exists():
            assert not (MAIN/'cron/output'/JOB).exists()
            shutil.copytree(outputs, MAIN/'cron/output'/JOB)
        receipt['stage'] = 'main_profile_ready'
        save_receipt(receipt)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'start', 'fs-hermes-ops-bridge.service'])
        run(['systemctl', 'start', 'fs-hermes-ops-bridge.timer'])
        stop_existing_main_gateway()
        run(['systemctl', 'start', 'hermes-dingtalk.service'])
        receipt['stage'] = 'started_readback_required'
        receipt['after_hashes'] = {str(p):sha(p.read_bytes()) for p in [UNIT,BRIDGE,MAIN/'AGENTS.md',MAIN/'cron/jobs.json']}
        assert (OLD/'memories/MEMORY.md').read_bytes() == (MAIN/'memories/MEMORY.md').read_bytes()
        assert plan['hashes'][str(MAIN/'.env')] == sha((MAIN/'.env').read_bytes())
        save_receipt(receipt)
        print(json.dumps(receipt))
    except Exception as error:
        receipt['stage_failed'] = receipt['stage']
        receipt['error_type'] = type(error).__name__
        save_receipt(receipt)
        # Re-enable the unchanged snapshot timer even if the migration needs reconciliation.
        subprocess.run(['systemctl','start','fs-hermes-ops-bridge.timer'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise


if __name__ == '__main__':
    main()
