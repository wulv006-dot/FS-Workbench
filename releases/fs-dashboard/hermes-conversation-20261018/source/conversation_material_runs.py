"""Real materials task ledger and official Runs recovery, hosted by existing FS.

No alternate runner/provider is implemented here. The host injects the existing
TaskStore, ConversationStore, authorization and official worker transport.
"""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from conversation_goals import _json, _sha, _pairs, _identifier

KIND = 'conversation_materials_v1'
TERMINAL = {'completed', 'failed', 'cancelled'}
PIN_FILES = {
    'api_server.py': '6a7e6fb0a0d5ea25ddc47d36a64e2c0bc50ded331d49e1c4521d801ca7189043',
    'api_server_runs.py': '8a7fcfd56183c32a14b41c7c43ce36b21b37bf49f2ed035dafe48899c0e8cbe7',
    'api_server_run_idempotency.py': '56f7762addc5e610569fd613729f1f0b3d5e99e4b76f56d9cfa509dfeb51636c',
}

READ_SCOPE_PREFIX = 'fs_material_read_scope_v1:'


def read_scope(execution):
    """Only a typed, server-frozen constraint can narrow a read request."""
    values = [v[len(READ_SCOPE_PREFIX):] for v in execution['handoff']['constraints']
              if v.startswith(READ_SCOPE_PREFIX)]
    if not values:
        return None
    if len(values) != 1:
        raise ValueError('material_read_scope_conflict')
    return json.loads(values[0], object_pairs_hook=_pairs)


def read_satisfied(row):
    summaries = {v['file_id']: v['analysis_coverage'] for v in row['coverage']
                 if 'analysis_coverage' in v}
    selected = read_scope(row['execution'])
    if selected is None:
        return all(summaries.get(v['file_id'], {}).get('workbook_complete') is True
                   for v in row['execution']['manifest']['files'])
    summary = summaries.get(selected['file_id'], {})
    if summary.get('status') != 'observed':
        return False
    for sheet in summary['observed_sheets']:
        if sheet['sheet'] == selected['sheet']:
            start, end = selected['offset'], min(selected['offset'] + selected['limit'], sheet['total_rows'])
            return start <= end and not any(a < end and b > start for a, b in sheet['missing_ranges'])
    return False


def runtime_pin_verified(directory):
    """A mismatch disables material POST/resolution, without affecting FC runs."""
    try:
        root = Path(directory)
        return all(not (root / name).is_symlink() and
                   hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
                   for name, sha in PIN_FILES.items())
    except OSError:
        return False


def official_fingerprint(body):
    # Exact pinned Runs fingerprint; no gateway conversation key for materials.
    return hashlib.sha256(json.dumps({'body': body, 'gateway_session_key': ''},
        sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def readonly_official_run(path, *, scope, key, fingerprint, session_id, owner_alive, now=None, execution=None):
    """SELECT only: never call official lookup(), prune(), reserve() or hydrate()."""
    now = time.time() if now is None else now
    unknown = {'status': 'unknown', 'session_id': session_id}
    if not all(isinstance(v, str) and v for v in (scope, key, fingerprint, session_id)):
        raise ValueError('material_resolver_identity')
    if not re.fullmatch('mg_[a-f0-9]{64}', session_id):
        raise PermissionError('material_session_required')
    target = Path(path) if path else None
    if target is None or not target.is_absolute() or target.is_symlink() or not target.is_file():
        raise OSError('official_runs_store_unavailable')
    try:
        with closing(sqlite3.connect(target.resolve(strict=True).as_uri() + '?mode=ro',
                                     uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            row = db.execute('''SELECT fingerprint,run_id,status_json,owner_pid,owner_started,
                updated_at,retention_until,acknowledged_at FROM run_idempotency
                WHERE scope=? AND idempotency_key=?''', (scope, key)).fetchone()
        if row is None:
            return unknown
        if row[0] != fingerprint:
            raise PermissionError('material_runtime_fingerprint_conflict')
        status = json.loads(row[2], object_pairs_hook=_pairs)
        if not isinstance(status, dict) or status.get('session_id') != session_id:
            raise PermissionError('material_runtime_session_conflict')
        if not re.fullmatch('run_[a-f0-9]{32}', row[1]):
            raise ValueError('official_run_identity')
        state = status.get('status')
        if state in {'completed', 'failed', 'cancelled', 'interrupted'}:
            expired = ((row[7] is not None and row[7] <= now - 86400)
                       or (row[6] > 0 and row[6] <= now)
                       or (row[6] <= 0 and row[5] < now - 86400))
            if expired:
                return unknown
        elif not owner_alive(int(row[3] or 0), int(row[4] or 0)):
            state = 'interrupted'  # Same fail-closed outcome, without a DB write.
        if state not in {'queued', 'running', 'stopping', 'waiting_for_approval',
                         'completed', 'failed', 'cancelled', 'interrupted'}:
            return unknown
        result = {'run_id': row[1], 'status': state, 'session_id': session_id}
        proof = (status.get('runtime') or {}).get('fs_material_context')
        if execution is not None and isinstance(proof,dict):
            from material_execution import verify_context_proof
            if verify_context_proof(execution,proof,session_id=session_id,run_id=row[1]) is True:
                result['context_receipt']=proof
        return result
    except sqlite3.Error as exc:
        raise OSError('official_runs_store_unavailable') from exc


class MaterialRunLedger:
    """Real tasks rows plus immutable intent and single-POST attempt mapping."""
    def __init__(self, outbox):
        self.outbox = outbox
        with outbox._db() as db:
            outbox._namespace(db)
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_material_runs_v1 (
                owner TEXT NOT NULL, request_id TEXT NOT NULL, cid TEXT NOT NULL,
                goal_id TEXT NOT NULL, execution TEXT NOT NULL, execution_sha TEXT NOT NULL,
                task_id TEXT NOT NULL UNIQUE, lease TEXT NOT NULL, session_id TEXT NOT NULL UNIQUE,
                runtime_key TEXT NOT NULL UNIQUE, body TEXT NOT NULL, body_sha TEXT NOT NULL,
                attempted INTEGER NOT NULL, run_id TEXT, stopped INTEGER NOT NULL,
                revision INTEGER NOT NULL, generated TEXT NOT NULL, coverage TEXT NOT NULL, context_receipt TEXT,
                official_status TEXT, runtime_error TEXT, observed_at TEXT,
                PRIMARY KEY(owner,request_id))''')

    def create(self, execution, budget_policy_id):
        binding = self.outbox._binding(execution['binding'])
        encoded = _json(execution)
        fingerprint = _sha(_json({'project': 'FS', 'type': KIND, 'execution': execution}))
        task_id = fingerprint[:32]
        session = 'mg_' + _sha(_json(binding))
        body = {'input': execution['input'], 'session_id': session}
        spec = dict(period=None, snapshot_id=execution['snapshot_id'],
                    template_version=execution['template_version'],
                    knowledge_version=execution['knowledge_version'], budget_policy_id=budget_policy_id)
        created = False
        with self.outbox._db() as db:
            receipt, reserved = self.outbox._lookup(db, binding)
            if reserved is None:
                raise ValueError('material_outbox_reservation_required')
            original_handoff = json.loads(reserved['handoff_json'])
            if original_handoff != execution['handoff']:
                raise ValueError('material_handoff_conflict')
            old = db.execute('SELECT execution_sha FROM conversation_material_runs_v1 WHERE owner=? AND request_id=?',
                             (binding['owner'], binding['request_id'])).fetchone()
            if old:
                if old[0] != _sha(encoded):
                    raise ValueError('material_execution_conflict')
            else:
                created = True
                lease = secrets.token_hex(16)
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,0,NULL,NULL,0,0)',
                           (task_id, binding['owner'], fingerprint, _json(spec), 'QUEUED'))
                db.execute('INSERT INTO conversation_material_runs_v1 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,0,1,?,?,NULL,NULL,NULL,NULL)',
                           (binding['owner'], binding['request_id'], binding['cid'], binding['goal_id'],
                            encoded, _sha(encoded), task_id, lease, session, 'mg-' + _sha(_json(binding)),
                            _json(body), official_fingerprint(body), '[]', '[]'))
        self.outbox._authorize(binding)
        result = self.get(binding)
        result['fresh_created'] = created
        return result

    def get(self, binding):
        binding = self.outbox._binding(binding)
        with self.outbox._db() as db:
            self.outbox._namespace(db)
            row = db.execute('SELECT * FROM conversation_material_runs_v1 WHERE owner=? AND request_id=?',
                             (binding['owner'], binding['request_id'])).fetchone()
        if row is None:
            return None
        value = dict(row)
        execution = json.loads(value['execution'], object_pairs_hook=_pairs)
        from material_execution import validate_execution
        validate_execution(execution)  # Integrity only; expiry is rechecked before execution.
        if (execution['binding'] != binding or _sha(value['execution']) != value['execution_sha']
                or value['session_id'] != 'mg_'+_sha(_json(binding))
                or value['runtime_key'] != 'mg-'+_sha(_json(binding))
                or json.loads(value['body']) != {'input':execution['input'],'session_id':value['session_id']}
                or official_fingerprint(json.loads(value['body'])) != value['body_sha']):
            raise ValueError('material_execution_damaged')
        task=self.outbox.tasks.get(value['task_id'],binding['owner'])
        if (task['fingerprint'] != _sha(_json({'project':'FS','type':KIND,'execution':execution}))
                or set(task['spec']) != {'period','snapshot_id','template_version','knowledge_version','budget_policy_id'}
                or task['spec']['period'] is not None
                or any(task['spec'][k] != execution[k] for k in ('snapshot_id','template_version','knowledge_version'))
                or not isinstance(task['spec']['budget_policy_id'],str) or not task['spec']['budget_policy_id']
                or task['run_id'] != value['run_id']
                or (task['state'] in {'DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED'} and task['lease'] != value['lease'])):
            raise ValueError('material_actual_task_conflict')
        value['execution'] = execution
        value['generated'] = json.loads(value['generated'])
        value['coverage'] = json.loads(value['coverage'])
        value['context_receipt'] = json.loads(value['context_receipt']) if value['context_receipt'] else None
        value['official_status'] = json.loads(value['official_status']) if value['official_status'] else None
        self.outbox._authorize(binding)
        return value

    def claim_post(self, binding):
        row = self.get(binding)
        if row is None:
            raise LookupError('material_execution_missing')
        with self.outbox._db() as db:
            changed = db.execute('''UPDATE conversation_material_runs_v1 SET attempted=1,revision=revision+1
                WHERE owner=? AND request_id=? AND attempted=0 AND stopped=0''',
                (binding['owner'], binding['request_id']))
            if changed.rowcount != 1:
                return False
            changed = db.execute("UPDATE tasks SET state='DISPATCH_UNKNOWN',lease=?,version=version+1 "
                                 "WHERE id=? AND owner=? AND state='QUEUED'", (row['lease'], row['task_id'], binding['owner']))
            if changed.rowcount != 1:
                raise ValueError('material_task_dispatch_conflict')
        return True

    def bind_run(self, binding, run_id):
        if not re.fullmatch('run_[a-f0-9]{32}', run_id):
            raise ValueError('material_run_id')
        row = self.get(binding)
        with self.outbox._db() as db:
            current = db.execute('SELECT run_id FROM conversation_material_runs_v1 WHERE owner=? AND request_id=?',
                                 (binding['owner'], binding['request_id'])).fetchone()
            if current[0] is not None and current[0] != run_id:
                raise ValueError('material_run_conflict')
            db.execute('UPDATE conversation_material_runs_v1 SET run_id=?,revision=revision+1 WHERE owner=? AND request_id=?',
                       (run_id, binding['owner'], binding['request_id']))
            task = db.execute('SELECT state,lease,run_id FROM tasks WHERE id=? AND owner=?',
                              (row['task_id'], binding['owner'])).fetchone()
            terminal = task['state'] in {'VALIDATING','SUCCEEDED','PARTIAL','FAILED','CANCELLED','TIMED_OUT'}
            if (not terminal and task['lease'] != row['lease']) or task['run_id'] not in (None, run_id):
                raise PermissionError('material_task_fenced')
            if task['state'] in ('DISPATCH_UNKNOWN','CANCEL_REQUESTED'):
                state = 'CANCEL_REQUESTED' if task['state']=='CANCEL_REQUESTED' else 'RUNNING'
                db.execute('UPDATE tasks SET state=?,run_id=?,version=version+1 WHERE id=?', (state,run_id,row['task_id']))

    def stop(self, binding):
        row = self.get(binding)
        with self.outbox._db() as db:
            db.execute('UPDATE conversation_material_runs_v1 SET stopped=1,revision=revision+1 WHERE owner=? AND request_id=?',
                       (binding['owner'], binding['request_id']))
        self.outbox.tasks.cancel(row['task_id'], binding['owner'])
        return row

    def record_tool(self, binding, *, artifact=None, page=None):
        self.get(binding)
        with self.outbox._db() as db:
            row = db.execute('SELECT generated,coverage FROM conversation_material_runs_v1 WHERE owner=? AND request_id=?',
                             (binding['owner'], binding['request_id'])).fetchone()
            generated, coverage = json.loads(row[0]), json.loads(row[1])
            if artifact is not None and not any(v['file_id'] == artifact['file_id'] for v in generated):
                generated.append({k: artifact[k] for k in ('file_id', 'sha256', 'parent_id', 'version', 'size')})
            if page is not None and page not in coverage:
                # Keep B's merged observed ranges, not an ever-growing page log.
                coverage=[value for value in coverage if value['file_id']!=page['file_id']]+[page]
            if len(_json(coverage).encode('utf-8')) > 32768:
                raise ValueError('material_coverage_limit')
            db.execute('UPDATE conversation_material_runs_v1 SET generated=?,coverage=?,observed_at=?,revision=revision+1 WHERE owner=? AND request_id=?',
                       (_json(generated),_json(coverage),datetime.now(timezone.utc).isoformat(),binding['owner'],binding['request_id']))

    def terminal(self, binding, status):
        row = self.get(binding)
        if status not in TERMINAL | {'interrupted'}:
            raise ValueError('material_terminal_status')
        task = self.outbox.tasks.get(row['task_id'], binding['owner'])
        if task['state'] in {'RUNNING', 'CANCEL_REQUESTED'}:
            task = self.outbox.tasks.observe(row['task_id'], binding['owner'], row['lease'], status, worker_stopped=True)
        if task['state'] == 'VALIDATING':
            operation = row['execution']['operation']
            valid = (read_satisfied(row) if operation['mode'] == 'read' else bool(row['generated'])) and bool(row['context_receipt'])
            self.outbox.tasks.change(task, 'SUCCEEDED' if valid else 'FAILED')
        return self.get(binding)

    def record_context(self,binding,proof):
        row=self.get(binding)
        from material_execution import verify_context_proof
        if verify_context_proof(row['execution'],proof,session_id=row['session_id'],run_id=row['run_id']) is not True:
            raise PermissionError('material_effective_context_unverified')
        with self.outbox._db() as db:
            db.execute('UPDATE conversation_material_runs_v1 SET context_receipt=? WHERE owner=? AND request_id=?',
                       (_json(proof),binding['owner'],binding['request_id']))

    def official(self,binding,status):
        self.get(binding)
        with self.outbox._db() as db:
            db.execute('UPDATE conversation_material_runs_v1 SET official_status=? WHERE owner=? AND request_id=?',
                       (_json(status),binding['owner'],binding['request_id']))

    def error(self,binding,code):
        self.get(binding)
        with self.outbox._db() as db:
            db.execute('UPDATE conversation_material_runs_v1 SET runtime_error=? WHERE owner=? AND request_id=?',
                       (code,binding['owner'],binding['request_id']))


class MaterialRuntime:
    """One official POST per durable attempt; subsequent calls only reconcile."""
    def __init__(self, hermes, conversation, ledger, goals, rpc=None, clock=None):
        self.hermes, self.conversation = hermes, conversation
        self.ledger, self.goals = ledger, goals
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.rpc = rpc or self._rpc
        self.live = {}

    def _rpc(self, method, path, body=None, key=None):
        # Same original loopback listener and existing identity; never log headers.
        from urllib.request import Request, build_opener
        from controller import NoRedirect
        if not re.fullmatch(r'/v1/(?:capabilities|runs(?:/run_[a-f0-9]{32}(?:/stop)?)?|materials/mg_[a-f0-9]{64})', path):
            raise ValueError('material_runtime_route')
        token = (self.conversation.run_root / 'api-key').read_text('ascii').strip()
        headers = {'Authorization': 'Bearer ' + token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if key:
            headers['Idempotency-Key'] = key
        request = Request('http://127.0.0.1:8941' + path,
                          data=_json(body).encode('utf-8') if body is not None else None,
                          headers=headers, method=method)
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('material_runtime_response_too_large')
            return response.status, json.loads(raw)

    def _active_goal(self, binding):
        state = self.goals.load_goal(binding['goal_id'])
        if state is None or state['status'] != 'active' or state['work']['request_id'] != binding['request_id']:
            raise PermissionError('material_goal_inactive')
        return state

    def _verify_selection(self, row, db):
        from conversation_files import ConversationFiles
        files=ConversationFiles(self.conversation.store)
        for expected in row['execution']['manifest']['files']:
            actual=files.read(row['owner'],row['cid'],expected['file_id'],_db=db)
            if any(actual[k]!=v for k,v in expected.items()):
                raise PermissionError('material_selection_changed')

    def _admission(self, row, token, ready):
        from controller import atomic
        value = dict(session_id=row['session_id'], token=token, model=self.live[row['task_id']]['gateway'].budget.policy['model'],
                     prompt=row['execution']['system_prompt'], ready=ready, reasoning_effort='none',
                     materials=dict(key=row['runtime_key'], fingerprint=row['body_sha'],
                                    execution_sha256=row['execution']['payload_sha256'],
                                    execution=row['execution']))
        if row['run_id']:
            value['run_id'] = row['run_id']
        atomic(self.conversation.run_root / 'admissions' / (row['session_id'] + '.json'), value)

    def start(self, binding, *, fresh=False):
        from material_execution import validate_execution, operation_guard
        from conversation_file_bindings import ExecutionBoundFiles
        from conversation_file_tools import attach_conversation_file_tools
        from fs_inprocess import gateway, spending_hold
        from types import SimpleNamespace
        row = self.ledger.get(binding)
        if row['attempted'] or fresh is not True:
            return self.reconcile(binding)
        execution = validate_execution(row['execution'], now=self.clock())
        self._active_goal(binding)
        if spending_hold(self.hermes.daily, self.hermes.tasks, binding['owner']):
            raise RuntimeError('model_usage_hold')
        code, capabilities = self.rpc('GET', '/v1/capabilities')
        if code != 200 or capabilities.get('fs_materials') != {
                'verified_pin': True, 'readonly_original_lookup': True, 'single_post': True}:
            self.ledger.error(binding,'material_runtime_unverified')
            raise RuntimeError('material_runtime_unverified')
        context = ExecutionBoundFiles(self.conversation.store, self.goals, self.ledger, binding,
            self.hermes.authorizer, lambda name,args: operation_guard(execution,name,args,now=self.clock()))
        def denied(name, arguments):
            raise PermissionError('material_tool_denied')
        book = SimpleNamespace(capture_id=execution['snapshot_id'], call=denied, material_execution=True)
        def authorize_execution():
            with context.current():
                return True
        book.authorize_execution = authorize_execution
        attach_conversation_file_tools(book, context, scope='material_execution_files',
            operation_guard=lambda name,args: operation_guard(execution,name,args,now=self.clock()))
        item_gateway = gateway(self.hermes.daily, self.hermes.tasks, book,
                               deadline=datetime.fromisoformat(execution['deadline_at']), material_execution=True)
        if item_gateway.budget.policy['id'] != self.hermes.tasks.get(row['task_id'],binding['owner'])['spec']['budget_policy_id']:
            raise ValueError('material_effective_budget_changed')
        state = self._active_goal(binding)
        # The B host may already have recorded the immutable outbox's QUEUED
        # receipt. This is a fresh material claim, not another dispatch proposal.
        with self.conversation.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.conversation.store._owned(db,binding['owner'],binding['cid'])
            current = self.goals._read(db,binding['goal_id'])
            if (current['revision'] != state['revision'] or current['status'] != 'active'
                    or current['work']['request_id'] != binding['request_id']
                    or current['work']['status'] not in {'prepared','queued'}):
                raise PermissionError('material_goal_claim_conflict')
            self._verify_selection(row,db)
            if not self.ledger.claim_post(binding):
                return {'status':'unknown'}
        token = self.hermes.grants.mint(binding['owner'], row['task_id'], row['lease'], reasoning_effort='none')
        with self.hermes.lock:
            self.hermes.tokens[row['task_id']] = token
            self.hermes.books[row['task_id']] = book
            self.hermes.gateways[row['task_id']] = item_gateway
        self.live[row['task_id']] = dict(token=token, gateway=item_gateway)
        self._admission(row, token, False)
        try:
            code, response = self.rpc('POST', '/v1/runs', json.loads(row['body']), row['runtime_key'])
            if code != 202:
                return {'status':'unknown'}
            self.ledger.bind_run(binding, response['run_id'])
        except (OSError, ValueError, KeyError):
            return {'status':'unknown'}  # Never re-POST, including after restart.
        row = self.ledger.get(binding)
        try:
            self._active_goal(binding)
            validate_execution(execution, now=self.clock())
            with self.conversation.store.db() as db:
                self.conversation.store._owned(db,binding['owner'],binding['cid'])
                self._verify_selection(row,db)
            self._admission(row, token, True)
        except (PermissionError, ValueError):
            return self.stop(binding)
        return self.reconcile(binding)

    def reconcile(self, binding):
        row = self.ledger.get(binding)
        if not row['attempted']:
            return {'status': 'queued'}
        try:
            code, status = self.rpc('GET', '/v1/materials/' + row['session_id'])
            if code != 200 or status.get('session_id') != row['session_id']:
                self.ledger.official(binding,{'status':'unknown'})
                return {'status':'unknown'}
            run_id = status.get('run_id')
            if not run_id:
                self.ledger.official(binding,{'status':'unknown'})
                return {'status':'unknown'}
            self.ledger.bind_run(binding, run_id)
            self.ledger.official(binding,status)
            state = status.get('status')
            if status.get('context_receipt'):
                self.ledger.record_context(binding,status['context_receipt'])
            if state in TERMINAL | {'interrupted'}:
                if state=='completed':
                    from conversation_files import ConversationFiles
                    files=ConversationFiles(self.conversation.store)
                    try:
                        for expected in self.ledger.get(binding)['generated']:
                            actual=files.read(binding['owner'],binding['cid'],expected['file_id'])
                            if any(actual[k]!=expected[k] for k in expected):
                                raise ValueError('material_artifact_changed')
                    except (OSError,ValueError,LookupError,PermissionError):
                        state='failed'
                self.ledger.terminal(binding, state)
                self._release(row['task_id'])
            elif row['task_id'] not in self.live:
                # A restarted FS has no live book/token. Fence tools and stop the
                # original official run; never reconstruct history or re-submit.
                self.stop(binding)
                return {'run_id':run_id,'status':'unknown'}
            else:
                try:
                    self._active_goal(binding)
                    from material_execution import validate_execution
                    validate_execution(row['execution'],now=self.clock())
                    self.hermes.grants.renew(self.live[row['task_id']]['token'],binding['owner'],row['task_id'],row['lease'])
                    self._admission(self.ledger.get(binding),self.live[row['task_id']]['token'],True)
                except (PermissionError,ValueError):
                    return self.stop(binding)
            return {'run_id':run_id,'status':state}
        except (OSError, ValueError, KeyError):
            self.ledger.official(binding,{'status':'unknown'})
            return {'status':'unknown'}

    def receipt(self,binding):
        row=self.ledger.get(binding)
        task=self.hermes.tasks.get(row['task_id'],binding['owner'])
        status=(row['official_status'] or {}).get('status','unknown') if row['attempted'] else 'queued'
        if task['state']=='SUCCEEDED':status='completed'
        elif task['state'] in ('FAILED','CANCELLED'):status=task['state'].lower()
        elif status=='completed':status='unknown'
        elif status in ('stopping','interrupted','waiting_for_approval'):status='unknown'
        if status not in {'queued','running','completed','failed','cancelled'}:status='unknown'
        proof=dict(task_id=row['task_id'],task_version=task['version'],lease=row['lease'],run_id=row['run_id'],status=status,
                   execution_sha=row['execution_sha'],generated=row['generated'],coverage=row['coverage'],
                   context=row['context_receipt'],official_status=row['official_status'])
        receipt=dict(binding=deepcopy(binding),status=status,receipt_ref='material-receipt-'+_sha(_json(proof)))
        if status=='completed':
            references = {}
            for page in row['coverage']:
                for reference in page.get('evidence', []):
                    references[reference['ref']] = reference
            for item in row['execution']['manifest']['files']:
                key='file:'+item['file_id']+'@'+item['sha256']
                if key not in references:
                    references[key]=dict(ref=key,source='material_execution_files',as_of=row['observed_at'],
                        version=item['sha256'],coverage='not_read',
                        missing=['selected_file_not_read','business_data_not_read','long_term_goal_not_assessed'])
            receipt['evidence']=list(references.values())
            receipt['completed_actions']=['material-artifact:'+v['file_id'] for v in row['generated']]
        return receipt

    def verify_receipt(self,receipt,binding):
        return receipt==self.receipt(binding)

    def answer(self,binding):
        """User result channel, separate from SELECT-only UNKNOWN resolution.

        Uses the existing official status endpoint only after the immutable
        mapping contains the original run. Its normal hydration semantics are
        not advertised as a read-only idempotency lookup.
        """
        row=self.ledger.get(binding)
        if not row['run_id']:
            return dict(status='unknown',text='',truncated=False)
        code,value=self.rpc('GET','/v1/runs/'+row['run_id'])
        self.ledger.get(binding)  # Recheck current authorization after I/O.
        if (code!=200 or value.get('run_id')!=row['run_id'] or value.get('session_id')!=row['session_id']
                or value.get('status') not in TERMINAL|{'interrupted'}):
            return dict(status='unknown',text='',truncated=False)
        text=value.get('output','')
        if not isinstance(text,str):raise ValueError('material_result_shape')
        raw=text.encode('utf-8')
        return dict(status=value['status'],text=raw[:65536].decode('utf-8',errors='ignore'),truncated=len(raw)>65536)

    def _release(self, task_id):
        live = self.live.pop(task_id,None)
        if live:
            self.hermes.grants.revoke(live['token'])
        with self.hermes.lock:
            self.hermes.tokens.pop(task_id,None)
            self.hermes.books.pop(task_id,None)
            self.hermes.gateways.pop(task_id,None)

    def stop(self, binding):
        row = self.ledger.stop(binding)
        return self.fence_original(row)

    def fence_original(self, row):
        """Cancellation only, using an already verified server mapping.

        This path can revoke an existing execution after user access is lost;
        it cannot return private data, create a grant, resume or submit a run.
        """
        task=self.hermes.tasks.get(row['task_id'],row['owner'])
        attempted=bool(row['attempted'] or task['state'] not in {'QUEUED','CANCELLED'})
        if task['run_id']:
            row=dict(row,run_id=task['run_id'])
        self._release(row['task_id'])
        self.hermes.tasks.cancel(row['task_id'], row['owner'])
        if attempted and not row['run_id']:
            try:
                code, status = self.rpc('GET','/v1/materials/'+row['session_id'])
                if code==200 and status.get('session_id')==row['session_id'] and re.fullmatch('run_[a-f0-9]{32}',status.get('run_id','')):
                    row=dict(row,run_id=status['run_id'])
            except (OSError,ValueError,KeyError):
                pass
        if row['run_id']:
            try:
                self.rpc('POST','/v1/runs/'+row['run_id']+'/stop',{})
            except OSError:
                return {'status':'unknown','run_id':row['run_id']}
        return {'status':'stopping' if attempted else 'cancelled','run_id':row['run_id']}


class MaterialService:
    """Explicit FS material actions on existing authenticated conversation objects."""
    def __init__(self, hermes, conversation):
        self.hermes, self.conversation = hermes, conversation
        self.runtimes = {}
        self.recovery_errors = []

    def recover(self):
        """One startup pass: reconcile/fence original IDs, never dispatch.

        Read only this module's mappings in the existing authoritative TaskStore.
        No old queued intent is promoted into a fresh POST after a restart.
        """
        path=self.hermes.root/'tasks.sqlite3'
        if path.is_symlink() or path.resolve(strict=True)!=Path(self.hermes.tasks.path).resolve(strict=True):
            raise OSError('material_recovery_task_store')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_material_runs_v1'").fetchone():
                return
            rows=[dict(r) for r in db.execute('''SELECT m.* FROM conversation_material_runs_v1 m
                JOIN tasks t ON t.id=m.task_id AND t.owner=m.owner
                WHERE t.state IN ('QUEUED','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')''')]
        for row in rows:
            verified=False
            try:
                execution=json.loads(row['execution'],object_pairs_hook=_pairs)
                from material_execution import validate_execution
                validate_execution(execution)
                binding=execution['binding']
                fingerprint=_sha(_json({'project':'FS','type':KIND,'execution':execution}))
                task=self.hermes.tasks.get(row['task_id'],row['owner'])
                if (_sha(row['execution'])!=row['execution_sha'] or binding['owner']!=row['owner']
                        or binding['cid']!=row['cid'] or binding['goal_id']!=row['goal_id']
                        or binding['request_id']!=row['request_id'] or row['task_id']!=fingerprint[:32]
                        or task['fingerprint']!=fingerprint or row['session_id']!='mg_'+_sha(_json(binding))
                        or row['runtime_key']!='mg-'+_sha(_json(binding))
                        or json.loads(row['body'])!={'input':execution['input'],'session_id':row['session_id']}
                        or official_fingerprint(json.loads(row['body']))!=row['body_sha']):
                    raise ValueError('material_recovery_mapping')
                verified=True
                if self.hermes.authorizer(row['owner']) is True:
                    _,_,ledger,runtime=self._parts(row['owner'],row['cid'])
                    binding=execution['binding']
                    if row['attempted']:
                        runtime.reconcile(binding)
                    else:
                        runtime.stop(binding)
                else:
                    runtime=MaterialRuntime(self.hermes,self.conversation,None,None)
                    runtime.fence_original(row)
            except (OSError,ValueError,PermissionError,LookupError,KeyError,TypeError):
                # No fresh dispatch on damaged or inaccessible durable intent.
                self.recovery_errors.append('material_recovery_unavailable')
                if verified:self.hermes.tasks.cancel(row['task_id'],row['owner'])

    def _queue(self, owner, cid):
        from conversation_goal_tasks import ConversationGoalTasks
        if self.hermes.authorizer(owner) is not True:
            raise PermissionError('material_access_revoked')
        with self.conversation.store.db() as db:
            self.conversation.store._owned(db,owner,cid)
        queue = ConversationGoalTasks(self.hermes.tasks, owner, cid,
            lambda user,scope:self._scope(user,cid,scope), expected_path=self.hermes.root/'tasks.sqlite3')
        with queue._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_material_selections_v1 (
                owner TEXT NOT NULL,cid TEXT NOT NULL,request_id TEXT NOT NULL,scope_ref TEXT NOT NULL UNIQUE,
                request_sha TEXT NOT NULL,selection TEXT NOT NULL,PRIMARY KEY(owner,request_id))''')
        return queue

    def _scope(self, owner, cid, scope):
        if self.hermes.authorizer(owner) is not True:
            return False
        # Read only, outside any task write transaction. Never call the goal DB.
        path = self.hermes.root/'tasks.sqlite3'
        try:
            with closing(sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',uri=True)) as db:
                row=db.execute('SELECT 1 FROM conversation_material_selections_v1 WHERE owner=? AND cid=? AND scope_ref=?',
                               (owner,cid,scope)).fetchone()
            return row is not None
        except (OSError,sqlite3.Error):
            return False

    def _parts(self, owner, cid):
        from conversation_goals import ConversationGoals
        queue = self._queue(owner,cid)
        goals = ConversationGoals(self.conversation.store,owner,cid,lambda user,scope:self._scope(user,cid,scope))
        ledger = MaterialRunLedger(queue)
        key = (owner,cid)
        if key not in self.runtimes:
            self.runtimes[key] = MaterialRuntime(self.hermes,self.conversation,ledger,goals)
        return queue,goals,ledger,self.runtimes[key]

    def submit(self, owner, cid, body):
        from datetime import timedelta
        from conversation_file_bindings import normalize_file_ids
        from conversation_files import ConversationFiles
        from b2_goal_host import GoalHost
        from material_execution import prepare_materials,freeze_execution
        required={'client_request_id','goal','file_ids','operation'}
        if not isinstance(body,dict) or not required <= set(body) or set(body)-required-{'read_scope'}:
            raise ValueError('material_submit_fields')
        request_id=body['client_request_id'];_identifier(request_id)
        if not isinstance(body['goal'],str) or not 1<=len(body['goal'].strip())<=6000:
            raise ValueError('material_goal_text')
        ids=normalize_file_ids(body['file_ids'])
        if not ids:
            raise ValueError('material_selection_required')
        selected=body.get('read_scope')
        if selected is not None and (body['operation'] != {'mode':'read'} or not isinstance(selected,dict)
                or set(selected) != {'file_id','sheet','offset','limit'} or selected['file_id'] not in ids
                or any(type(selected[k]) is not int or selected[k]<0 for k in ('sheet','offset'))
                or type(selected['limit']) is not int or not 1<=selected['limit']<=200):
            raise ValueError('material_read_scope')
        queue,goals,ledger,runtime=self._parts(owner,cid)
        request_sha=_sha(_json(dict(body,file_ids=ids)))
        with queue._db() as db:
            old=db.execute('SELECT request_sha,selection FROM conversation_material_selections_v1 WHERE owner=? AND request_id=?',
                           (owner,request_id)).fetchone()
        if old:
            selection=json.loads(old['selection'])
            if old['request_sha']!=request_sha or selection['cid']!=cid:
                raise ValueError('material_original_request_conflict')
            return self.detail(owner,cid,request_id)
        now=datetime.now(timezone.utc)
        files=ConversationFiles(self.conversation.store)
        with files.transaction() as db:
            self.conversation.store._owned(db,owner,cid)
            metadata=[{k:v for k,v in files.read(owner,cid,fid,_db=db).items() if k!='content'} for fid in ids]
            if selected is not None:
                table=files.parsed(owner,cid,selected['file_id'],_db=db)
                if selected['sheet']>=len(table['sheets']) or selected['offset']>len(table['sheets'][selected['sheet']]['rows']):
                    raise ValueError('material_read_scope_bounds')
        goal_id='material-'+_sha(_json(dict(owner=owner,cid=cid,request_id=request_id)))
        scope='material-selection-'+_sha(_json(dict(owner=owner,cid=cid,goal_id=goal_id)))
        selection=dict(cid=cid,goal_id=goal_id,scope=scope,files=metadata,operation=body['operation'],
                       now=now.isoformat(),deadline=(now+timedelta(minutes=10)).isoformat())
        # Reject invalid operations before recording an immutable selection.
        prepare_materials(owner=owner,cid=cid,scope_ref=scope,selection_revision=1,
                          files=metadata,operation=body['operation'],now=now)
        with queue._db() as db:
            old=db.execute('SELECT request_sha FROM conversation_material_selections_v1 WHERE owner=? AND request_id=?',
                           (owner,request_id)).fetchone()
            if old:
                if old[0]!=request_sha:
                    raise ValueError('material_original_request_conflict')
                return {'request_id':request_id,'status':'unknown'}
            selection['revision']=1+db.execute('SELECT count(*) FROM conversation_material_selections_v1 WHERE owner=? AND cid=?',
                                               (owner,cid)).fetchone()[0]
            db.execute('INSERT INTO conversation_material_selections_v1 VALUES(?,?,?,?,?,?)',
                       (owner,cid,request_id,scope,request_sha,_json(selection)))
        facts=prepare_materials(owner=owner,cid=cid,scope_ref=scope,selection_revision=selection['revision'],
                                files=metadata,operation=body['operation'],now=now)
        policy_id=None
        from direct_provider import POLICY_ID
        policy_id=POLICY_ID
        created=[]
        class Dispatcher:
            def lookup(self,*,binding):return queue.lookup(binding=binding)
            def submit(self,*,binding,handoff):
                execution=freeze_execution(binding=binding,handoff=handoff,selection_revision=selection['revision'],
                    files=metadata,operation=body['operation'],deadline_at=selection['deadline'],now=now)
                receipt=queue.submit(binding=binding,handoff=handoff)
                row=ledger.create(execution,policy_id)
                if row['fresh_created']:created.append(binding)
                return receipt
        host=GoalHost(goals,owner=owner,cid=cid,authorize=lambda user,ref:self._scope(user,cid,ref),
                      dispatcher=Dispatcher(),verify_receipt=queue.verify_receipt)
        constraints=['Only explicitly selected material files; no business sources or business writes.']
        if selected is not None:
            constraints.append(READ_SCOPE_PREFIX+_json(selected))
        else:
            constraints.append('Read mode requires all rows and all sheets of every selected input, using pages.')
        host.create(goal_id,mutation_id='material-create-'+_sha(request_id),scope_ref=scope,objective=body['goal'],
                    constraints=constraints,
                    recheck_at=selection['deadline'],now=now,explicit_goal=True)
        result=host.step(goal_id,mutation_id='material-prepare-'+_sha(request_id),request_id=request_id,
                         fact_version=facts['fact_version'],now=now)
        if created and result['action']=='receipt_recorded':
            self.conversation.pool.submit(self._execute,runtime,created[0])
        return self.detail(owner,cid,request_id)

    def _execute(self,runtime,binding):
        original=runtime.ledger.get(binding)
        try:
            runtime.start(binding,fresh=True)
            while True:
                status=runtime.reconcile(binding)
                row=runtime.ledger.get(binding)
                if row['runtime_error'] or status['status'] in TERMINAL|{'interrupted'}:
                    break
                if datetime.now(timezone.utc)>=datetime.fromisoformat(row['execution']['deadline_at']):
                    runtime.stop(binding);break
                time.sleep(1)
            self._sync_goal(runtime,binding)
        except (OSError,ValueError,PermissionError,RuntimeError):
            # The immutable mapping/attempt survives. No automatic second POST.
            if self.hermes.authorizer(binding['owner']) is not True:
                runtime.fence_original(original)
            return

    def _sync_goal(self,runtime,binding):
        from b2_goal_host import GoalHost
        host=GoalHost(runtime.goals,owner=binding['owner'],cid=binding['cid'],
            authorize=lambda user,ref:self._scope(user,binding['cid'],ref),dispatcher=runtime.ledger.outbox,
            verify_receipt=runtime.verify_receipt)
        host.observe(binding['goal_id'],receipt=runtime.receipt(binding),now=datetime.now(timezone.utc))

    def detail(self, owner, cid, request_id):
        _identifier(request_id)
        queue,goals,ledger,runtime=self._parts(owner,cid)
        with queue._db() as db:
            saved=db.execute('SELECT selection FROM conversation_material_selections_v1 WHERE owner=? AND cid=? AND request_id=?',
                             (owner,cid,request_id)).fetchone()
            row=db.execute('SELECT execution FROM conversation_material_runs_v1 WHERE owner=? AND cid=? AND request_id=?',
                           (owner,cid,request_id)).fetchone()
        if saved is None:
            raise LookupError('material_request_not_found')
        selection=json.loads(saved[0])
        if row is None:
            return dict(request_id=request_id,goal_id=selection['goal_id'],status='unknown',files=[])
        execution=json.loads(row[0]);binding=execution['binding']
        row=ledger.get(binding)
        state=runtime.reconcile(binding) if row['attempted'] else {'status':'queued'}
        row=ledger.get(binding)
        if row['runtime_error']:state={'status':'unavailable'}
        task=self.hermes.tasks.get(row['task_id'],owner)
        if task['state']=='SUCCEEDED':state['status']='completed'
        elif task['state'] in ('FAILED','CANCELLED'):state['status']=task['state'].lower()
        self._sync_goal(runtime,binding)
        from conversation_files import ConversationFiles
        files=ConversationFiles(self.conversation.store)
        metadata=[]
        for item in row['generated']:
            meta=files.describe(owner,cid,item['file_id'])
            meta['download_url']='/api/hermes/conversations/'+cid+'/files/'+item['file_id']
            metadata.append(meta)
        return dict(request_id=request_id,goal_id=selection['goal_id'],task_id=row['task_id'],run_id=row['run_id'],
                    status=state['status'],files=metadata,coverage=row['coverage'],
                    context_receipt=row['context_receipt'],cost_microcny=None,goal_achieved=False)

    def result(self,owner,cid,request_id):
        _identifier(request_id)
        queue,_,ledger,runtime=self._parts(owner,cid)
        with queue._db() as db:
            row=db.execute('SELECT execution FROM conversation_material_runs_v1 WHERE owner=? AND cid=? AND request_id=?',
                           (owner,cid,request_id)).fetchone()
        if row is None:raise LookupError('material_request_not_found')
        binding=json.loads(row[0])['binding']
        ledger.get(binding)
        return dict(request_id=request_id,**runtime.answer(binding))

    def stop(self, owner, cid, request_id):
        queue,goals,ledger,runtime=self._parts(owner,cid)
        with queue._db() as db:
            row=db.execute('SELECT execution FROM conversation_material_runs_v1 WHERE owner=? AND cid=? AND request_id=?',
                           (owner,cid,request_id)).fetchone()
        if row is None:raise LookupError('material_request_not_found')
        binding=json.loads(row[0])['binding']
        from b2_goal_state import configure_goal
        state=goals.load_goal(binding['goal_id'])
        proposed=configure_goal(state,expected_revision=state['revision'],now=datetime.now(timezone.utc),
                                 authorize=lambda user,ref:self._scope(user,cid,ref),status='stopped')
        if proposed['state']!=state:
            goals.cas_goal(binding['goal_id'],expected_revision=state['revision'],
                mutation_id='material-stop-'+_sha(_json(dict(request_id=request_id,revision=state['revision']))),state=proposed['state'])
        runtime.stop(binding)
        return self.detail(owner,cid,request_id)
