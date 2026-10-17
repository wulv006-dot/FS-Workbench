"""Human-confirmed action history in the existing task DB; never executes an action."""
from datetime import datetime
import hashlib
import json
import re

TRANSITIONS = {
    'suggested': {'approved', 'adjusted'}, 'approved': {'executed', 'adjusted'},
    'executed': {'review_pending', 'insufficient', 'adjusted'},
    'review_pending': {'effective', 'ineffective', 'insufficient', 'adjusted'},
    'insufficient': {'review_pending', 'adjusted'}, 'effective': {'adjusted'},
    'ineffective': {'adjusted'}, 'adjusted': {'approved'},
}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS traffic_action_events('
               'report TEXT,action TEXT,version INTEGER,actor TEXT,request_id TEXT UNIQUE,'
               'body TEXT,created_at TEXT,PRIMARY KEY(report,action,version))')


def history(db, report=None):
    schema(db)
    sql = 'SELECT report,action,version,actor,body,created_at FROM traffic_action_events'
    rows = db.execute(sql+(' WHERE report=?' if report else '')+' ORDER BY rowid', (report,) if report else ()).fetchall()
    return [dict(report=r[0], action=r[1], version=r[2], actor=r[3], **json.loads(r[4]), recorded_at=r[5]) for r in rows]


def record(db, actor, body, confirmed_action, now):
    fields = {'kind', 'id', 'action', 'request_id', 'expected_version', 'status', 'note', 'review_at'}
    if not isinstance(body, dict) or set(body) != fields or body['kind'] != 'hermes_action': raise ValueError('action_fields')
    if not re.fullmatch(r'[a-f0-9]{32}', str(body['id'])) or not re.fullmatch(r'action-[1-9][0-9]{0,3}', str(body['action'])):
        raise ValueError('action_identity')
    if not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', body['request_id']): raise ValueError('action_request_id')
    if type(body['expected_version']) is not int or body['expected_version'] < 0: raise ValueError('action_version')
    if body['status'] not in TRANSITIONS: raise ValueError('action_status')
    if not isinstance(body['note'], str) or not 1 <= len(body['note'].strip()) <= 2000: raise ValueError('action_receipt_required')
    review = body['review_at']
    if review:
        parsed = datetime.fromisoformat(review)
        if parsed.tzinfo is None: raise ValueError('action_review_timezone')
    if body['status'] in {'executed', 'review_pending'} and not review: raise ValueError('action_review_required')
    schema(db)
    identity = hashlib.sha256((actor+'\0'+body['request_id']).encode()).hexdigest()
    old = db.execute('SELECT body FROM traffic_action_events WHERE request_id=?', (identity,)).fetchone()
    if old:
        if json.loads(old[0])['request'] != body: raise ValueError('action_idempotency_conflict')
        return history(db, body['id'])
    events = [x for x in history(db, body['id']) if x['action'] == body['action']]
    previous = events[-1] if events else {'version': 0, 'status': 'suggested'}
    if events and previous['action_snapshot'] != confirmed_action: raise ValueError('action_source_changed')
    if previous['version'] != body['expected_version']: raise ValueError('action_version_conflict')
    if body['status'] not in TRANSITIONS[previous['status']]: raise ValueError('action_transition')
    event = dict(request=body, status=body['status'], note=body['note'].strip(), review_at=review,
                 action_snapshot=confirmed_action, rule_version='traffic-admin-first-20261017-v2')
    db.execute('INSERT INTO traffic_action_events VALUES(?,?,?,?,?,?,?)',
               (body['id'], body['action'], previous['version']+1, actor, identity,
                json.dumps(event, ensure_ascii=False, sort_keys=True), now.isoformat()))
    return history(db, body['id'])
