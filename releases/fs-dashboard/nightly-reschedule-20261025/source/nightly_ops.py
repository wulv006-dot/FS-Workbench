"""Use the original five-minute bridge, source services and notification outbox."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import subprocess
import sys
import types

TZ = timezone(timedelta(hours=8))
FS = Path('/var/lib/fs-hermes-fc/fs')
SERVICES = {'mmoexp-marketing-daily.service': 10,
            'fs-channel-cache.service': 20, 'fs-boss-management.service': 35}


def archive_management(now, folder):
    sys.path.insert(0, '/opt/fs-hermes-fc')
    from management_context import scheduled_question, scheduled_weekly_question, load
    from nightly import closed_period
    from nightly_data import save_book
    from source_snapshots import SnapshotStore
    day = now.astimezone(TZ).date()
    for kind in ['management'] + (['management_weekly'] if day.weekday()==0 else []):
        start,end = closed_period(day,kind)
        question = (scheduled_question if kind=='management' else scheduled_weekly_question)(now)
        facts = load(dict(question=question,mode='kpi' if kind=='management' else 'investigation',start=start,end=end))
        pointer = folder/(kind+'.json')
        if pointer.exists():
            entry = SnapshotStore(folder).read(pointer)
            if entry.get('snapshot_id') == facts['snapshotId']:
                continue
        ready = facts.get('status') == 'available'
        brief = {'collection_readiness':{'status':'ready' if ready else 'partial','gaps':[] if ready else ['management_facts_partial']}}
        book = types.SimpleNamespace(capture_id=facts['snapshotId'],evidence={'management_facts':facts})
        save_book(day.isoformat(),kind,start,end,book,brief,folder.parent)


def source_state(unit):
    value = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
        '-p', 'Result', '-p', 'ExecMainStartTimestamp', '-p', 'ExecMainExitTimestamp'],
        universal_newlines=True, timeout=8)
    return dict(line.split('=', 1) for line in value.splitlines() if '=' in line)


def retry_decision(now, state, attempts):
    minute = now.astimezone(TZ).hour * 60 + now.astimezone(TZ).minute
    if not 60 <= minute < 310 or state.get('ActiveState') not in ('inactive', 'failed'):
        return False
    if state.get('Result') in (None, '', 'success') or len(attempts) >= 3:
        return False
    if attempts:
        last = attempts[-1]
        if last['state'] in ('requesting', 'unknown'):
            return False
        if (now - datetime.fromisoformat(last['at'])).total_seconds() < 900:
            return False
        if state.get('ExecMainStartTimestamp') == last['before_start']:
            return False
    return True


def inspect_reports(now, fs=FS):
    sys.path.insert(0, '/opt/fs-hermes-fc')
    from nightly import enabled_kinds
    config_path = fs/'nightly-schedule.json'
    enabled = set(enabled_kinds(json.loads(config_path.read_text()))) if config_path.exists() else set()
    day = now.astimezone(TZ).strftime('%Y%m%d')
    with closing(sqlite3.connect((fs/'tasks.sqlite3').as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT kind,state,error FROM nightly_requests WHERE request_id LIKE ?', ('night_%_'+day,))]
    issues = ['nightly_report_'+r['kind']+'_'+r['state'].lower() for r in rows
              if r['kind'] in enabled and r['state'] in ('FAILED','NEEDS_RECONCILE','EXPIRED','CANCELLED')]
    if now.astimezone(TZ).hour >= 7:
        expected = {'management','daily'}
        if now.astimezone(TZ).weekday() == 0: expected.update(('weekly','management_weekly'))
        if now.astimezone(TZ).day == 1: expected.add('monthly')
        complete = {r['kind'] for r in rows if r['state'] == 'COMPLETED'}
        issues += ['nightly_report_'+kind+'_not_completed' for kind in sorted((expected & enabled)-complete)]
    return issues


def tick(now, write, read, fs=FS, state_reader=source_state, runner=subprocess.run):
    local = now.astimezone(TZ)
    minute = local.hour * 60 + local.minute
    folder = fs/'nightly-data'/local.date().isoformat()
    if not 10 <= minute < 480:
        return read(folder/'operations.json', {}).get('issues', [])
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    ledger_path = folder/'recovery.json'
    ledger = read(ledger_path, {'day':local.date().isoformat(),'services':{}})
    issues = []
    if minute >= 45:
        try:
            archive_management(now, folder)
        except (OSError,ValueError,KeyError,TypeError):
            if minute >= 90: issues.append('nightly_management_archive_unavailable')
    for unit, start in SERVICES.items():
        status = state_reader(unit)
        if minute >= start+30 and local.date().isoformat() not in status.get('ExecMainStartTimestamp', ''):
            status = dict(status, Result='not_run_today')
        attempts = ledger['services'].setdefault(unit, [])
        if retry_decision(now, status, attempts):
            # Record the intent before the systemd request; unknown requests are never replayed.
            attempt = dict(at=now.isoformat(), state='requesting', before_start=status.get('ExecMainStartTimestamp'),
                           operation_id=local.strftime('%Y%m%d')+':'+unit+':'+str(len(attempts)+1))
            attempts.append(attempt); write(ledger_path, ledger)
            try:
                result = runner(['systemctl','start','--no-block',unit], capture_output=True, text=True, timeout=10)
                attempt.update(state='submitted' if result.returncode == 0 else 'rejected', exit_code=result.returncode)
            except (OSError, subprocess.TimeoutExpired) as error:
                attempt.update(state='unknown', error=type(error).__name__)
            write(ledger_path, ledger)
        if minute >= max(90, start+30) and (status.get('ActiveState') == 'failed' or status.get('Result') == 'not_run_today'):
            issues.append('nightly_source_failed:'+unit)
    if minute >= 70:
        prep = read(fs/'source-snapshots'/('preparation-'+local.date().isoformat()+'.json'), {})
        if prep.get('day') != local.date().isoformat() or prep.get('status') != 'ready':
            if minute >= 95:
                issues.append('nightly_data_not_ready:'+local.date().isoformat())
            if minute < 90:
                write(folder/'operations.json', dict(at=now.isoformat(),issues=['nightly_preparation_partial'],phase='hermes_autonomous_recovery'))
                result = runner(['docker','exec','-u','0','-e','HERMES_HOME=/profile','fs-hermes-desktop',
                    '/opt/hermes/.venv/bin/python','-B','/fs-source/nightly_recovery_job.py'],
                    capture_output=True,text=True,timeout=20)
                write(folder/'hermes-dispatch.json',dict(at=now.isoformat(),exit_code=result.returncode,result=result.stdout[-1200:]))
    try:
        issues += inspect_reports(now, fs)
    except (sqlite3.Error, OSError, ValueError):
        issues.append('nightly_report_ledger_unreadable')
    write(folder/'operations.json', dict(at=now.isoformat(),issues=issues,
        repair_deadline='02:00',report_deadline='07:50',
        guidance='先原工具补查与原ID对账，失败通过原飞书群联系Codex；不重启运行中共享服务；02:00才允许缺项报告。'))
    return issues
