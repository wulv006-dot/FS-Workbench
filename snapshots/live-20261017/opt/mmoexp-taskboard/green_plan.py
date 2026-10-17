"""Green plan: isolated tables, existing identity, stdlib only (Python 3.9)."""
import json
import re
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import urlsplit

SEED = Path(__file__).with_name('green-plan-seed.json')
BASE = '/api/green-plan'
STATUSES = ('todo', 'doing', 'blocked', 'review', 'done')
STRUCTURE = {'priority','stream','title','start','end','owner','support','depends','deliverable','acceptance','effort','assignee'}
EXECUTION = {'status','progress','notes','blocker','evidence'}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def init(conn):
    conn.executescript('''CREATE TABLE IF NOT EXISTS green_plan_tasks (
      id TEXT PRIMARY KEY, data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS green_plan_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
      at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, summary TEXT NOT NULL);''')
    seed = json.loads(SEED.read_text(encoding='utf-8-sig'))
    with conn:
        for src in seed['tasks']:
            task = dict(src, assignee='',status='todo',progress=0,notes='',blocker='',evidence='',
                        updatedAt='',updatedBy='',acceptedBy='',acceptedAt='')
            conn.execute('INSERT OR IGNORE INTO green_plan_tasks(id,data) VALUES(?,?)',
                         (task['id'],json.dumps(task,ensure_ascii=False)))


def all_tasks(conn):
    result = {}
    for row in conn.execute('SELECT id,data,revision FROM green_plan_tasks ORDER BY CAST(SUBSTR(id,2) AS INTEGER)'):
        task = json.loads(row['data'])
        task['revision'] = row['revision']
        result[row['id']] = task
    return result


def validate(task, tasks, conn, host):
    err = host.ApiError
    for key in STRUCTURE | EXECUTION:
        if key in ('depends','progress'):
            continue
        value = task.get(key)
        if not isinstance(value,str) or len(value) > (4000 if key in ('notes','blocker','evidence','deliverable','acceptance') else 500):
            raise err(400,'字段类型或长度无效：'+key)
    if not task['title'].strip() or not task['owner'].strip():
        raise err(400,'标题和责任岗位不能为空')
    if task['priority'] not in ('P0','P1','P2') or task['status'] not in STATUSES:
        raise err(400,'优先级或状态无效')
    if type(task['progress']) is not int or not 0 <= task['progress'] <= 100:
        raise err(400,'进度须为0到100整数')
    try:
        for key in ('start','end'):
            if date.fromisoformat(task[key]).isoformat() != task[key]:
                raise ValueError()
        if task['start'] > task['end']:
            raise ValueError()
    except (ValueError,TypeError):
        raise err(400,'日期无效或开始晚于结束')
    assignee = task['assignee']
    if assignee and assignee not in host.GUARD_ADMINS:
        member = conn.execute('SELECT active FROM members WHERE username=?',(assignee,)).fetchone()
        if not member or not member['active']:
            raise err(400,'只能指派已登记的有效成员')
    deps = task['depends']
    if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps)) != len(deps):
        raise err(400,'依赖须为不重复的任务编码列表')
    if any(d not in tasks or d == task['id'] for d in deps):
        raise err(400,'依赖不存在或指向自身')
    graph = dict(tasks, **{task['id']:task})
    visiting, visited = set(), set()
    def visit(code):
        if code in visiting:
            raise err(409,'任务依赖形成循环')
        if code in visited:
            return
        visiting.add(code)
        for dep in graph[code]['depends']:
            visit(dep)
        visiting.remove(code)
        visited.add(code)
    for code in graph:
        visit(code)
    if task['status'] == 'blocked' and not task['blocker'].strip():
        raise err(400,'阻塞任务必须填写原因')
    evidence = task['evidence'].strip()
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',evidence) and not evidence.startswith('https://'):
        raise err(400,'证据链接须为https或站内链接；也可填写描述')
    if evidence.startswith('//'):
        raise err(400,'证据链接不可为协议相对URL')
    if task['status'] == 'done':
        if not evidence or any(tasks[d]['status'] != 'done' for d in deps):
            raise err(409,'验收完成须有证据且所有依赖已验收')
    for other in graph.values():
        if other['status'] == 'done' and any(graph[d]['status'] != 'done' for d in other['depends']):
            raise err(409,'已有下游完成任务，请先重开下游再重开前置')


def mutate(host,ctx,payload,code=None):
    if not isinstance(payload,dict):
        raise host.ApiError(400,'请求体必须为JSON对象')
    with host.WRITE_LOCK:
        conn = host.db_connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            tasks = all_tasks(conn)
            creating = code is None
            if creating:
                host.require_admin(ctx)
                code = 'G%d' % (max([int(c[1:]) for c in tasks] or [50])+1)
                task = {k:'' for k in STRUCTURE | EXECUTION}
                task.update(id=code,priority='P0',depends=[],status='todo',progress=0,
                            updatedAt='',updatedBy='',acceptedBy='',acceptedAt='')
                revision = 0
            else:
                if code not in tasks:
                    raise host.ApiError(404,'任务不存在')
                task = dict(tasks[code])
                host.require_task_edit(ctx,task)
                revision = task.pop('revision')
                if type(payload.get('expectedRevision')) is not int or payload['expectedRevision'] != revision:
                    raise host.ApiError(409,'任务已被更新，请刷新后重试')
            allowed = STRUCTURE | EXECUTION if ctx.is_admin else EXECUTION
            if set(payload)-allowed-({'expectedRevision'} if not creating else set()):
                raise host.ApiError(403,'包含无权修改的字段')
            if not ctx.is_admin and payload.get('status') == 'done':
                raise host.ApiError(403,'完成验收需要管理员')
            before = dict(task)
            if not creating and before['status'] == 'done':
                if not ctx.is_admin:
                    raise host.ApiError(403,'已验收任务只能由管理员维护')
                changed_acceptance = any(k not in ('expectedRevision','notes','status') and task.get(k) != v for k,v in payload.items())
                if changed_acceptance and payload.get('status','done') == 'done':
                    raise host.ApiError(409,'变更已验收内容须先明确重开任务')
            task.update({k:v for k,v in payload.items() if k != 'expectedRevision'})
            validate(task,tasks,conn,host)
            if task['status'] == 'done':
                task['progress'] = 100
                if before['status'] != 'done':
                    task.update(acceptedBy=ctx.user,acceptedAt=stamp())
            else:
                task.update(acceptedBy='',acceptedAt='')
            task.update(updatedBy=ctx.user,updatedAt=stamp())
            if creating:
                conn.execute('INSERT INTO green_plan_tasks(id,data,revision) VALUES(?,?,1)',
                             (code,json.dumps(task,ensure_ascii=False)))
            else:
                cur = conn.execute('UPDATE green_plan_tasks SET data=?,revision=revision+1 WHERE id=? AND revision=?',
                                   (json.dumps(task,ensure_ascii=False),code,revision))
                if cur.rowcount != 1:
                    raise host.ApiError(409,'并发更新冲突')
            changed = {k:{'old':before.get(k),'new':task.get(k)} for k in payload if k != 'expectedRevision' and before.get(k) != task.get(k)}
            conn.execute('INSERT INTO green_plan_events(task_id,at,actor,action,summary) VALUES(?,?,?,?,?)',
                         (code,stamp(),ctx.user,'create' if creating else 'update',json.dumps(changed,ensure_ascii=False)))
            conn.commit()
            task.update(revision=revision+1,canEdit=host.can_edit_task(ctx,task))
            return task
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def probes():
    now = datetime.now(timezone.utc)
    results = []
    specs = [('business','经营快照','/var/www/dashboard/fs-home/transactions/current.json','generatedAt',180),
             ('google','Google营销','/var/www/mmoexp-marketing/current/data.json','data_generated_at',1800),
             ('weekly','运营周报','/opt/mmoexp-weekly-report/public/current.json',None,None),
             ('fc-monitor','FC巡检','/var/lib/fc-ops-readonly-monitor/latest.json',None,None)]
    for code,title,path,key,minutes in specs:
        item = dict(id=code,title=title,status='unknown',observedAt=stamp(),detail='只读文件缺失或无法解析，不代表业务完成')
        try:
            raw = json.loads(Path(path).read_text(encoding='utf-8'))
            if key:
                value = raw.get(key)
                when = datetime.fromisoformat(str(value).replace('Z','+00:00'))
                if when.tzinfo is None:
                    raise ValueError('timestamp timezone missing')
                age = (now-when).total_seconds()/60
                item.update(status='ok' if 0 <= age <= minutes and (code != 'google' or raw.get('isMock') is False) else 'warning',detail='生成时间%s；%s，仅证明快照可读' % (value,'时效内' if 0 <= age <= minutes else '过期或未来时间'))
                if code == 'google' and raw.get('isMock') is not False:
                    item['detail'] += '；非模拟数据标识未通过'
            elif code == 'weekly':
                # 周报文件存在不证明自然周期；只返回明确来源和尝试信息。
                attempt_path = Path('/opt/mmoexp-weekly-report/public/attempt.json')
                attempt = json.loads(attempt_path.read_text(encoding='utf-8')) if attempt_path.is_file() else {}
                origin = raw.get('generationInvocation') or raw.get('publicationMode') or raw.get('mode') or raw.get('source') or raw.get('trigger') or 'unknown'
                item.update(status='warning',detail='当前周报可读；生成%s；来源%s；自然周期未验。最近尝试状态%s' % (raw.get('generatedAt','unknown'),origin,attempt.get('status','unknown')))
            else:
                state = raw.get('status','unknown')
                codes = raw.get('issueCodes') or [x.get('code','unknown') for x in (raw.get('issues') or raw.get('assessment',{}).get('issues',[])) if isinstance(x,dict)]
                value = raw.get('finished_at') or raw.get('captured_at')
                when = datetime.fromisoformat(str(value).replace('Z','+00:00'))
                if when.tzinfo is None:
                    raise ValueError('timestamp timezone missing')
                age = (now-when).total_seconds()/60
                healthy = state in ('ok','healthy') and not codes and 0 <= age <= 15
                item.update(status='ok' if healthy else 'warning',detail='巡检状态%s；时间%s；issueCodes=%s；%s，仅文件状态' % (state,value,json.dumps(codes,ensure_ascii=False)[:500],'本模块15分钟观测阈值内' if 0 <= age <= 15 else '超过本模块15分钟观测阈值或未来时间'))
        except (OSError,ValueError,TypeError,AttributeError):
            pass
        results.append(item)
    return results


def board(host,ctx):
    conn = host.db_connect()
    try:
        tasks = list(all_tasks(conn).values())
        for task in tasks:
            task['canEdit'] = host.can_edit_task(ctx,task)
        project = json.loads(SEED.read_text(encoding='utf-8-sig'))
        project.pop('tasks')
        members = host.members_json(conn)
        if ctx.is_admin and not any(m['username'] == ctx.user for m in members):
            members.append(dict(username=ctx.user,displayName=ctx.user,role='admin',active=True))
        events = [dict(id=r['id'],taskId=r['task_id'],at=r['at'],actor=r['actor'],action=r['action'],summary=r['summary'])
                  for r in conn.execute('SELECT * FROM green_plan_events ORDER BY id DESC LIMIT 200')]
        capabilities = probes()
        capabilities.append(dict(id='storage',title='共享任务存储',status='ok',observedAt=stamp(),detail='当前数据库读取成功；未执行写入探测'))
        return dict(project=project,title=project['title'],tasks=tasks,viewer=ctx.to_json(),members=members,events=events,capabilities=capabilities,serverTime=stamp())
    finally:
        conn.close()


def csrf(headers,host):
    if headers.get('Content-Type','').split(';')[0].strip().lower() != 'application/json':
        raise host.ApiError(415,'仅接受application/json')
    if headers.get('Sec-Fetch-Site','').lower() not in ('','same-origin','none'):
        raise host.ApiError(403,'禁止跨站写入')
    origin = headers.get('Origin')
    if origin:
        parsed = urlsplit(origin)
        expected = headers.get('Host','').lower()
        scheme = 'http' if expected.split(':')[0] in ('localhost','127.0.0.1','[::1]') else 'https'
        if parsed.scheme != scheme or parsed.netloc.lower() != expected or parsed.path or parsed.query or parsed.fragment:
            raise host.ApiError(403,'禁止跨源写入')


def route(handler,host,ctx,method,path):
    if path != BASE and not path.startswith(BASE+'/'):
        return False
    if path == BASE and method in ('GET','HEAD'):
        handler._json(200,board(host,ctx))
    elif path == BASE+'/tasks' and method == 'POST':
        body = handler._body()
        csrf(handler.headers,host)
        handler._json(201,dict(task=mutate(host,ctx,body)))
    elif re.fullmatch(re.escape(BASE)+r'/tasks/G\d+',path) and method == 'PATCH':
        body = handler._body()
        csrf(handler.headers,host)
        handler._json(200,dict(task=mutate(host,ctx,body,path.rsplit('/',1)[-1])))
    else:
        raise host.ApiError(404,'绿茵计划接口不存在')
    return True
