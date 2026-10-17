"""Trusted FS scheduling only. No public route, credentials, shell or new process."""
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
import json
import os
import stat

from pilot import digest, encoded

SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')
STARTS = {'daily': time(0, 45), 'weekly': time(1, 45), 'monthly': time(3, 15)}
CUTOFF = time(6, 59)  # Reserve one minute to stop the native run and persist its terminal receipt.
QUESTIONS = {
    'daily': '复盘昨日FC经营，与前一日和上周同日比较。先读历史判断，按销售量、客单价、平台、品类和队列变化补查证据；区分事实、估算和假设。输出有价值的判断、优先动作及复查条件，保存完整HTML正文。',
    'weekly': '调查上个完整自然周FC经营变化。先读上一期判断，按变化拆量价结构、自主补查队列、历史与参考利润；列支持证据、替代解释和缺口。给优先处理对象、具体动作、条件和复查标准，保存完整HTML正文。',
    'monthly': '调查上个完整自然月FC经营变化。回看历史判断，找持续变化与阶段拐点，自主补查平台、商品、国家、支付、队列和参考利润；区分事实、估算与假设，输出最值得安排的行动和复查条件，保存完整HTML正文。',
}
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'NEEDS_RECONCILE', 'REPORT_PENDING'}


def civil(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone_required')
    return now.astimezone(SHANGHAI)


def inside(now):
    return civil(now).hour < 7


def closed_period(day, kind):
    if kind == 'daily':
        start = end = day - timedelta(days=1)
    elif kind == 'weekly':
        end = day - timedelta(days=day.weekday()+1)
        start = end - timedelta(days=6)
    elif kind == 'monthly':
        end = day.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:
        raise ValueError('report_kind')
    return start.isoformat(), end.isoformat()


def due(now):
    now = civil(now)
    if not inside(now):
        return []
    result = []
    for kind, clock in STARTS.items():
        eligible = kind == 'daily' or kind == 'weekly' and now.weekday() == 0 or kind == 'monthly' and now.day == 1
        if eligible and now.time().replace(tzinfo=None) >= clock:
            start, end = closed_period(now.date(), kind)
            result.append({'kind': kind, 'request_id': 'night_'+kind+'_'+now.strftime('%Y%m%d'),
                           'start': start, 'end': end,
                           'deadline': datetime.combine(now.date(), CUTOFF, SHANGHAI).isoformat()})
    return result


def preparation_status(now, *, boss_root=Path('/var/lib/fs-boss-workspaces'),
                       marketing_record=Path('/opt/mmoexp-marketing/verification-20260930/integrated-run-record.json')):
    """A failed completed preparation is disclosed, never relabelled as success."""
    day = civil(now).date().isoformat()
    warnings = []
    for kind in ('game-monitor', 'management'):
        path = boss_root / 'public' / (kind+'.status.json')
        if not path.is_file() or path.is_symlink():
            return False, [kind+'_preparation_missing']
        value = json.loads(path.read_text('utf-8'))
        if value.get('day') != day or value.get('phase') != 'completed':
            return False, [kind+'_preparation_not_finished']
        if value.get('status') != 'succeeded':
            warnings.append(kind+'_preparation_failed')
    if not marketing_record.is_file() or marketing_record.is_symlink():
        return False, ['marketing_preparation_missing']
    value = json.loads(marketing_record.read_text('utf-8'))
    finished = value.get('completed_at_utc')
    if not isinstance(finished, str) or civil(datetime.fromisoformat(finished)).date().isoformat() != day:
        return False, ['marketing_preparation_not_finished']
    if not value.get('steps') or any(value['steps'].values()) or not value.get('publication_performed'):
        warnings.append('marketing_preparation_failed')
    return True, warnings


class NightlyScheduler:
    def __init__(self, service, readiness=preparation_status):
        self.service, self.readiness = service, readiness
        with service.tasks.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS nightly_requests(request_id TEXT PRIMARY KEY, id TEXT UNIQUE, '
                       'owner TEXT, kind TEXT, deadline TEXT, state TEXT, error TEXT)')

    def config(self):
        path = self.service.root / 'nightly-schedule.json'
        if not path.exists():
            return None
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 or any(p.is_symlink() for p in path.parents):
            raise ValueError('nightly_configuration_boundary')
        if os.name == 'posix' and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError('nightly_configuration_owner')
        value = json.loads(path.read_text('utf-8'))
        if value != {'contract': 'fs-hermes-nightly-v1', 'enabled': True, 'owner': 'wulv', 'timezone': 'Asia/Shanghai'}:
            raise ValueError('nightly_configuration_contract')
        if not self.service.authorizer(value['owner']):
            raise PermissionError('nightly_owner_not_authorized')
        return value

    def deadline(self, key):
        with self.service.tasks.db() as db:
            row = db.execute('SELECT deadline FROM nightly_requests WHERE id=?', (key,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def status(self, owner):
        with self.service.tasks.db() as db:
            items=[dict(row) for row in db.execute('SELECT kind,id,deadline,state,error FROM nightly_requests WHERE owner=? ORDER BY rowid DESC LIMIT 12',(owner,))]
        configured=self.config()
        return {'enabled':bool(configured and configured['owner']==owner),'timezone':'Asia/Shanghai',
                'starts':{'daily':'00:45','weekly':'Mon 01:45','monthly':'1st 03:15'},
                'stop_at':'06:59','complete_before':'07:00','daytime_catchup':False,'items':items}

    def refresh(self, now):
        with self.service.tasks.db() as db:
            rows = db.execute("SELECT * FROM nightly_requests WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED','NEEDS_RECONCILE','REPORT_PENDING','EXPIRED')").fetchall()
        for row in rows:
            job = self.service.get_job(row['owner'], row['id'])
            if job and job['state'] in TERMINAL:
                state, error = job['state'], job.get('error')
            elif now >= datetime.fromisoformat(row['deadline']):
                if job:
                    if now>=datetime.fromisoformat(row['deadline'])+timedelta(minutes=1):
                        if job.get('task_id'):
                            task=self.service.tasks.get(job['task_id'],row['owner'])
                            if task['state'] in {'RUNNING','DISPATCH_UNKNOWN','CANCEL_REQUESTED'}:self.service.tasks.fence(task['id'],row['owner'])
                        self.service.update(row['id'],state='NEEDS_RECONCILE',error='nightly_stop_unconfirmed')
                        state,error='NEEDS_RECONCILE','nightly_stop_unconfirmed'
                    else:
                        if job['state']!='CANCEL_REQUESTED':self.service.cancel_job(row['owner'], row['id'], reason='nightly_deadline_exceeded')
                        state='CANCEL_REQUESTED'
                        error='nightly_deadline_exceeded'
                else:
                    state = 'EXPIRED'
                    error = 'nightly_deadline_exceeded'
            else:
                continue
            with self.service.tasks.db() as db:
                db.execute('UPDATE nightly_requests SET state=?,error=? WHERE id=?', (state, error, row['id']))

    def tick(self):
        now = self.service.clock()
        self.refresh(now)  # Deadlines remain enforced even if new scheduling is disabled.
        config = self.config()
        if config is None or not inside(now):
            return
        owner = config['owner']
        with self.service.tasks.db() as db:
            if db.execute("SELECT 1 FROM requests WHERE state IN ('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED') LIMIT 1").fetchone():
                return
        for item in due(now):
            key = digest({'owner': owner, 'request_id': item['request_id']})[:32]
            with self.service.tasks.db() as db:
                old = db.execute('SELECT state FROM nightly_requests WHERE id=?', (key,)).fetchone()
                if old and old[0] != 'WAITING':
                    continue
                if not old:
                    db.execute("INSERT INTO nightly_requests VALUES(?,?,?,?,?,'WAITING',NULL)",
                               (item['request_id'], key, owner, item['kind'], item['deadline']))
            ready, warnings = self.readiness(now)
            if not ready:
                with self.service.tasks.db() as db:
                    db.execute('UPDATE nightly_requests SET error=? WHERE id=?', (','.join(warnings), key))
                return
            body = {'kind': 'hermes_report', 'request_id': item['request_id'], 'start': item['start'], 'end': item['end'],
                    'question': QUESTIONS[item['kind']] + (' 数据准备缺口：'+','.join(warnings) if warnings else ''),
                    'mode': 'daily' if item['kind'] == 'daily' else 'investigation'}
            code, job = self.service.submit_scheduled(body)
            state = job.get('state', 'FAILED') if code in (200, 202) else 'FAILED'
            with self.service.tasks.db() as db:
                db.execute('UPDATE nightly_requests SET state=?,error=? WHERE id=?', (state, job.get('error'), key))
            return  # One preparation/model chain at a time; manual tasks remain available.
