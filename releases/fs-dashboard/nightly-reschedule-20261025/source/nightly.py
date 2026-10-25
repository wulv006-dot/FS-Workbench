"""Trusted FS scheduling only. No public route, credentials, shell or new process."""
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
import json
import os
import stat
import hashlib
import re

from pilot import digest, encoded

SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')
STARTS = {'daily': time(1, 40), 'management': time(2, 10), 'weekly': time(2, 40),
          'management_weekly': time(3, 25), 'monthly': time(4, 10)}
CUTOFF = time(7, 49)  # Reserve one minute to stop the native run and persist its terminal receipt.
QUESTIONS = {
    'daily': '复盘昨日FC经营，与前一日和上周同日比较。自主检查销售利润、客户商品、履约支付售后、运营策略复购、投放自然获客、现实节点活动、既有动作效果、风险机会及待决，按重要性侧重。先给关键判断、影响、优先动作和复查；区分事实、估算与假设。按现行报告方法自主呈现，图表与信息量相称、文字精炼、交互有用；复杂分析按需完整离线HTML，FS只展示归档原稿，不套固定模板，不执行业务。',
    'weekly': '调查上个完整自然周FC经营变化，回看上一期判断。自主检查销售利润、客户商品、履约支付售后、运营策略复购、投放自然获客、现实节点活动、既有动作效果、风险机会及待决，按重要性侧重趋势、成因、跨环节影响与安排。给关键判断、可行改进、优先动作及复查，区分事实、估算与假设。按现行报告方法自主呈现，图表紧凑、文字精炼、交互有用；按需完整离线HTML，FS只展示归档原稿，不套固定模板，不执行业务。',
    'monthly': '调查上个完整自然月FC经营变化，回看历史判断、持续变化与阶段拐点。自主检查销售利润、客户商品、履约支付售后、运营策略复购、投放自然获客、现实节点活动、既有动作效果、风险机会及待决，按重要性组织，不强制章节。给关键判断、影响、方案取舍、优先动作和复查；区分事实、估算与假设。按现行报告方法自主呈现，图表紧凑、文字精炼、交互有用；按需完整离线HTML，FS只展示归档原稿，不套固定模板，不执行业务。',
}
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'NEEDS_RECONCILE', 'REPORT_PENDING'}


def civil(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone_required')
    return now.astimezone(SHANGHAI)


def inside(now):
    return time(0, 10) <= civil(now).time().replace(tzinfo=None) < time(7, 50)


def closed_period(day, kind):
    if kind == 'management':
        end=day-timedelta(days=1);start=end.replace(day=1)
    elif kind == 'daily':
        start = end = day - timedelta(days=1)
    elif kind in {'weekly','management_weekly'}:
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
    if not inside(now) or now.time().replace(tzinfo=None) >= CUTOFF:
        return []
    result = []
    for kind, clock in STARTS.items():
        eligible = kind in {'daily','management'} or kind in {'weekly','management_weekly'} and now.weekday() == 0 or kind == 'monthly' and now.day == 1
        if eligible and now.time().replace(tzinfo=None) >= clock:
            start, end = closed_period(now.date(), kind)
            result.append({'kind': kind, 'request_id': 'night_'+kind+'_'+now.strftime('%Y%m%d'),
                           'start': start, 'end': end,
                           'deadline': datetime.combine(now.date(), CUTOFF, SHANGHAI).isoformat()})
    return result


def source_status(now, *, boss_root=Path('/var/lib/fs-boss-workspaces'),
                       marketing_record=Path('/opt/mmoexp-marketing/verification-20260930/integrated-run-record.json')):
    """Readiness gaps are disclosed; missing sources do not postpone scheduled reports."""
    day = civil(now).date().isoformat()
    warnings = []
    for kind in ('game-monitor', 'management'):
        path = boss_root / 'public' / (kind+'.status.json')
        if not path.is_file() or path.is_symlink():
            warnings.append(kind+'_preparation_missing');continue
        try:value = json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):
            warnings.append(kind+'_preparation_invalid');continue
        current=value.get('day')==day
        if kind=='game-monitor' and not current and value.get('status')=='succeeded':
            snapshot=boss_root/'public/game-monitor.json'
            if snapshot.is_file() and not snapshot.is_symlink():
                raw=snapshot.read_bytes();saved=json.loads(raw)
                try:
                    collected=datetime.fromisoformat(saved['collected_at'])
                    expires=datetime.fromisoformat(saved['stale_after'])
                    current=(saved.get('status')=='succeeded' and collected<=now<expires
                             and value.get('public_sha256')==hashlib.sha256(raw).hexdigest())
                except (KeyError,TypeError,ValueError):current=False
        if not current or value.get('phase') != 'completed':
            warnings.append(kind+'_preparation_not_finished');continue
        if kind == 'management' and value.get('status') == 'facts_ready':
            if value.get('fact_status') != 'available':
                warnings.append('management_facts_partial')
        elif value.get('status') != 'succeeded':
            warnings.append(kind+'_preparation_failed')
    if not marketing_record.is_file() or marketing_record.is_symlink():
        return True, warnings+['marketing_preparation_missing']
    try:value = json.loads(marketing_record.read_text('utf-8'))
    except (OSError,ValueError):return True,warnings+['marketing_preparation_invalid']
    finished = value.get('completed_at_utc')
    try:current=isinstance(finished,str) and civil(datetime.fromisoformat(finished)).date().isoformat()==day
    except ValueError:current=False
    if not current:
        return True, warnings+['marketing_preparation_not_finished']
    if not value.get('steps') or any(value['steps'].values()) or not value.get('publication_performed'):
        warnings.append('marketing_preparation_failed')
    return True, warnings


def preparation_status(now, *, kind='daily'):
    from nightly_data import preparation_gaps, FALLBACK
    _, warnings = source_status(now)
    warnings = warnings + preparation_gaps(now, kind, Path('/var/lib/fs-hermes-fc/fs/source-snapshots'))
    return not warnings or civil(now).time().replace(tzinfo=None) >= FALLBACK, warnings


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
                'starts':{'daily':'01:40','management':'02:10','weekly':'周一 02:40',
                          'management_weekly':'周一 03:25','monthly':'每月1日 04:10'},
                'stop_at':'07:49','complete_before':'07:50','daytime_catchup':False,'items':items}

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
            ready, warnings = self.readiness(now, kind=item['kind']) if self.readiness is preparation_status else self.readiness(now)
            if not ready:
                with self.service.tasks.db() as db:
                    db.execute('UPDATE nightly_requests SET error=? WHERE id=?', (','.join(warnings), key))
                continue
            preparation = getattr(self.service, 'source_preparation', None)
            if preparation and preparation.thread and preparation.thread.is_alive():
                return
            from nightly_data import report_note
            management_question=None
            if item['kind'] in {'management','management_weekly'}:
                from management_context import scheduled_question,scheduled_weekly_question
                try:management_question=(scheduled_weekly_question if item['kind']=='management_weekly' else scheduled_question)(now)
                except (ValueError,OSError):
                    from nightly_data import FALLBACK
                    if civil(now).time().replace(tzinfo=None) < FALLBACK:
                        with self.service.tasks.db() as db:db.execute("UPDATE nightly_requests SET error=? WHERE id=?",('management_facts_not_ready',key))
                        continue
                    management_question='经营管理台全项目事实未准备完成。本次仅发布全项目经营建议缺数说明：列明已核缺口、正在补采及后续追加条件；禁止把FC数据当全项目数据，禁止编造全盘数字或目标判断。'
                    warnings=warnings+['management_facts_not_ready']
            body = {'kind': 'hermes_report', 'request_id': item['request_id'], 'start': item['start'], 'end': item['end'],
                    'question': (management_question or QUESTIONS[item['kind']]) + report_note(now) + (' 数据准备缺口：'+','.join(warnings) if warnings else '') + ' 缺失数据不阻塞本次发布。有可比趋势及已核相关证据才可推算；逐项标注“预估，真实数据暂未提供”，说明依据、方法、假设、范围和不确定性。无依据则保留未知。预估与真实数值分开，不能写回真实归档；回看此前估计，取得同范围真实值后核对误差并追加修订，保留原稿，不重放旧任务。',
                    'mode': 'kpi' if item['kind']=='management' else 'daily' if item['kind'] == 'daily' else 'investigation'}
            try:
                code, job = self.service.submit_scheduled(body)
            except ValueError as error:
                # Reconcile the original ID before retrying or allowing a later report.
                job = self.service.get_job(owner, key)
                message = str(error)
                reason = message if re.fullmatch(r'[a-z][a-z0-9_:.\-]{0,159}', message) else 'unstructured_error'
                state = job['state'] if job else 'WAITING'
                issue = (job.get('error') if job else None) or 'nightly_admission_ValueError:' + reason
                with self.service.tasks.db() as db:
                    db.execute('UPDATE nightly_requests SET state=?,error=? WHERE id=?', (state, issue, key))
                if job and state in {'PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE'}:
                    return
                continue
            state = job.get('state', 'FAILED') if code in (200, 202) else 'FAILED'
            with self.service.tasks.db() as db:
                db.execute('UPDATE nightly_requests SET state=?,error=? WHERE id=?', (state, job.get('error'), key))
            return  # One preparation/model chain at a time; manual tasks remain available.
