"""Candidate/release ledger in the existing FS task DB; no business/config writes."""
from datetime import datetime, timezone
import json
import re
import secrets
from pilot import digest, encoded

CONTRACT = 'hermes-controlled-learning-v1'
REVIEWER = 'bounded-visible-review-v1'
TYPES = ('core_contract', 'method', 'experience', 'fact_evidence', 'action_evidence', 'hypothesis')


def schema(db):
    definitions = {
        'learning_events': 'id TEXT PRIMARY KEY,owner TEXT,project TEXT,source TEXT,source_hash TEXT,baseline TEXT,event_type TEXT,state TEXT,attempt TEXT,input TEXT,result TEXT',
        'experience_versions': 'id TEXT PRIMARY KEY,event TEXT,owner TEXT,project TEXT,content TEXT,content_hash TEXT,risk TEXT,expires_at TEXT',
        'experience_releases': 'seq INTEGER PRIMARY KEY AUTOINCREMENT,experience TEXT,owner TEXT,project TEXT,state TEXT,actor TEXT,reason TEXT,created_at TEXT',
        'knowledge_uses': 'task TEXT,owner TEXT,project TEXT,knowledge TEXT,experience TEXT,PRIMARY KEY(task,experience)',
        'learning_control': 'owner TEXT,project TEXT,paused INTEGER,PRIMARY KEY(owner,project)',
    }
    for table, fields in definitions.items():
        db.execute('CREATE TABLE IF NOT EXISTS '+table+'('+fields+')')
        expected = [field.strip().split()[0] for field in fields.split(',') if not field.strip().startswith('PRIMARY KEY') and ')' not in field]
        actual = [row[1] for row in db.execute('PRAGMA table_info('+table+')')]
        if actual[:len(expected)] != expected:
            raise ValueError('learning_schema_conflict')


def identity(owner, project):
    if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', owner) or project not in ('FS', 'FC27'):
        raise PermissionError('learning_scope')


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('learning_timezone')
    return result


def set_paused(db, owner, project, paused):
    identity(owner, project);schema(db)
    if type(paused) is not bool:raise ValueError('learning_pause_boolean')
    db.execute('INSERT INTO learning_control(owner,project,paused) VALUES(?,?,?) ON CONFLICT(owner,project) DO UPDATE SET paused=excluded.paused', (owner,project,int(paused)))


def manifest(db, owner, project, now):
    identity(owner, project);schema(db)
    rows = db.execute('SELECT v.id,v.content,v.content_hash,v.expires_at,r.state FROM experience_versions v '
        'JOIN experience_releases r ON r.experience=v.id WHERE v.owner=? AND v.project=? '
        'AND r.seq=(SELECT max(x.seq) FROM experience_releases x WHERE x.experience=v.id) ORDER BY v.id', (owner, project)).fetchall()
    items = []
    for row in rows:
        if row[4] != 'published' or instant(row[3]) <= now:
            continue
        content = json.loads(row[1])
        if digest(content) != row[2]:
            raise ValueError('experience_hash_changed')
        items.append(dict(id=row[0], sha256=row[2], expires_at=row[3], content=content))
    result = dict(contract=CONTRACT, owner=owner, project=project, experiences=items)
    return dict(result, sha256=digest(result))


def enqueue(db, owner, project, source, baseline, event_type, snapshot):
    identity(owner, project);schema(db)
    control=db.execute('SELECT paused FROM learning_control WHERE owner=? AND project=?',(owner,project)).fetchone()
    if control and control[0]:return {'state':'paused','new_event_created':False}
    if event_type not in ('completed_report', 'user_correction', 'action_review'):
        raise ValueError('learning_event_type')
    if not re.fullmatch(r'[a-f0-9]{32}', str(source)) or not re.fullmatch(r'[a-f0-9]{64}', str(baseline)):
        raise ValueError('learning_source_identity')
    if not isinstance(snapshot, dict) or snapshot.get('source_kind') == 'learning':
        raise ValueError('recursive_learning_source')
    source_hash = digest(snapshot)
    key = digest(dict(owner=owner, project=project, source=source, source_hash=source_hash,
                      baseline=baseline, reviewer=REVIEWER, event_type=event_type))
    db.execute('INSERT OR IGNORE INTO learning_events VALUES(?,?,?,?,?,?,?,\'queued\',NULL,?,NULL)',
               (key, owner, project, source, source_hash, baseline, event_type, encoded(snapshot)))
    return event(db, owner, project, key)


def event(db, owner, project, key):
    identity(owner, project);schema(db)
    row = db.execute('SELECT * FROM learning_events WHERE id=? AND owner=? AND project=?', (key, owner, project)).fetchone()
    if row is None:
        raise PermissionError('learning_event_not_found')
    return dict(row)


def claim(db, owner, project, key):
    current = event(db, owner, project, key)
    if current['state'] != 'queued':
        raise ValueError('learning_attempt_requires_reconcile')
    attempt = secrets.token_hex(16)
    updated = db.execute("UPDATE learning_events SET state='running',attempt=? WHERE id=? AND state='queued'", (attempt, key))
    if updated.rowcount != 1:
        raise ValueError('learning_claim_conflict')
    return attempt


def candidate(db, owner, project, key, attempt, value, now):
    current = event(db, owner, project, key)
    if current['state'] != 'running' or current['attempt'] != attempt:
        raise ValueError('learning_attempt_changed')
    fields = {'kind', 'lesson', 'applies_to', 'evidence_refs', 'counterexample', 'expires_at'}
    if not isinstance(value, dict) or set(value) != fields or value['kind'] != 'experience':
        raise ValueError('experience_fields')
    for field in ('lesson', 'applies_to', 'counterexample'):
        if not isinstance(value[field], str) or not 1 <= len(value[field].strip()) <= 2000:
            raise ValueError('experience_text')
    text = '\n'.join(value[k] for k in ('lesson', 'applies_to', 'counterexample'))
    from report_delivery import private_report
    if private_report(text) or re.search(r'Bearer\s|Cookie\s*[:=]|password\s*[:=]|sk-[A-Za-z0-9_-]{8,}', text, re.I):
        raise ValueError('experience_sensitive')
    if re.search(r'(当前|现在|实时).{0,10}(价格|售价|余额|成本|已完成)|chmod|sudo|自动.{0,5}(改价|写价)|忽略.{0,8}(规则|权限)|最低(毛利|利润).{0,8}[0-9]', text, re.I):
        raise ValueError('experience_requires_business_approval')
    refs = value['evidence_refs'];available = json.loads(current['input']).get('evidence_refs', [])
    if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x in available for x in refs) or len(set(refs)) != len(refs):
        raise ValueError('experience_source_refs')
    expiry = instant(value['expires_at'])
    if not now < expiry or (expiry-now).days > 366:
        raise ValueError('experience_expiry')
    key_version = digest(dict(event=key, content=value))
    db.execute('INSERT OR IGNORE INTO experience_versions VALUES(?,?,?,?,?,?,?,?)',
        (key_version, key, owner, project, encoded(value), digest(value), 'L1', value['expires_at']))
    db.execute("UPDATE learning_events SET state='completed',result=? WHERE id=? AND attempt=? AND state='running'",
               (encoded(dict(candidate=key_version, risk='L1', status='needs_human_review', business_benefit='unverified')), key, attempt))
    return dict(id=key_version, content_hash=digest(value), risk='L1', state='candidate', business_benefit='unverified')


def release(db, owner, project, key, expected_manifest, state, actor, reason, now):
    if state not in ('published', 'revoked') or actor != owner:
        raise PermissionError('knowledge_release_identity')
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 1000:
        raise ValueError('knowledge_review_reason')
    current = manifest(db, owner, project, now)
    if current['sha256'] != expected_manifest:
        raise ValueError('knowledge_manifest_conflict')
    row = db.execute('SELECT * FROM experience_versions WHERE id=? AND owner=? AND project=?', (key, owner, project)).fetchone()
    if row is None:
        raise PermissionError('experience_not_found')
    if state == 'published' and instant(row['expires_at']) <= now:
        raise ValueError('experience_expired')
    previous = db.execute('SELECT state FROM experience_releases WHERE experience=? ORDER BY seq DESC LIMIT 1', (key,)).fetchone()
    if previous and previous[0] == state:
        return current
    source = event(db, owner, project, row['event'])
    # Free text always requires this authenticated explicit review, never auto-publish.
    if source['state'] != 'completed' or digest(json.loads(row['content'])) != row['content_hash']:
        raise ValueError('experience_source_changed')
    db.execute('INSERT INTO experience_releases(experience,owner,project,state,actor,reason,created_at) VALUES(?,?,?,?,?,?,?)',
               (key, owner, project, state, actor, reason.strip(), now.isoformat()))
    return manifest(db, owner, project, now)


def context(receipt):
    parts = []
    for row in receipt['experiences']:
        parts.append(encoded(dict(id=row['id'], sha256=row['sha256'], **row['content'])))
    return ('\n已审经验（仅方法线索，核心合同优先；不作为当前价格/成本/订单事实、不增加权限，实际事实仍需本任务工具取证）：\n'
            + '\n'.join(parts)) if parts else ''


def record_use(db, task, owner, project, knowledge, receipt):
    identity(owner, project);schema(db)
    for row in receipt['experiences']:
        db.execute('INSERT OR IGNORE INTO knowledge_uses VALUES(?,?,?,?,?)', (task, owner, project, knowledge, row['id']))


def affected(db, owner, project, key):
    identity(owner, project);schema(db)
    return [dict(row) for row in db.execute('SELECT task,knowledge FROM knowledge_uses WHERE owner=? AND project=? AND experience=?', (owner, project, key))]
