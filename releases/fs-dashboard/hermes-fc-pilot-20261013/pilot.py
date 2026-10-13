"""Offline FC pilot contract. No network, provider keys, shell or business writes."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import sqlite3

CONTRACT = 'hermes-fc-pilot-v1-candidate'
SHANGHAI = timezone(timedelta(hours=8))
TOOLS = ('fc.get_metric_definitions', 'fc.get_business_snapshot',
         'fc.get_order_reference', 'fc.compare_periods', 'fc.get_breakdown')
TERMINAL = {'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED', 'TIMED_OUT'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def money(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'-?\d+(?:\.\d{1,2})?', value):
        raise ValueError('decimal_string_required')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError('decimal_string_required') from None
    return format(number.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f')


def complete_week(at):
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise ValueError('timezone_required')
    today = at.astimezone(SHANGHAI).date()
    end = today - timedelta(days=today.weekday())
    return {'start': (end-timedelta(days=7)).isoformat(), 'end_exclusive': end.isoformat(),
            'timezone': 'Asia/Shanghai'}


def validate_spec(spec):
    fields = {'period', 'snapshot_id', 'template_version', 'knowledge_version', 'budget_policy_id'}
    if not isinstance(spec, dict) or set(spec) != fields:
        raise ValueError('task_fields')
    period = spec['period']
    if not isinstance(period, dict) or set(period) != {'start', 'end_exclusive', 'timezone'}:
        raise ValueError('period_fields')
    if period['timezone'] != 'Asia/Shanghai':
        raise ValueError('timezone_mismatch')
    try:
        lo, hi = date.fromisoformat(period['start']), date.fromisoformat(period['end_exclusive'])
    except (ValueError, TypeError):
        raise ValueError('period_invalid') from None
    if lo.isoformat() != period['start'] or hi.isoformat() != period['end_exclusive'] or lo.weekday() or hi-lo != timedelta(days=7):
        raise ValueError('complete_week_required')
    for key in fields-{'period'}:
        if not isinstance(spec[key], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', spec[key]):
            raise ValueError('invalid_identifier')
    return deepcopy(spec)


class TaskStore:
    """Dedicated task DB only; owner comes from a future authenticated FS adapter."""
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, owner TEXT NOT NULL, '
                       'fingerprint TEXT NOT NULL, spec TEXT NOT NULL, state TEXT NOT NULL, '
                       'version INTEGER NOT NULL, run_id TEXT UNIQUE, lease TEXT, tokens INTEGER NOT NULL, '
                       'rounds INTEGER NOT NULL, UNIQUE(owner,fingerprint))')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, task_id, owner):
        with self.db() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=? AND owner=?', (task_id, owner)).fetchone()
        if row is None:
            raise PermissionError('task_not_found')
        item = dict(row)
        item['spec'] = json.loads(item['spec'])
        return item

    def create(self, owner, spec):
        if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', owner):
            raise PermissionError('identity_required')
        spec = validate_spec(spec)
        fingerprint = digest({'project': 'FC27', 'type': 'fc_weekly_diagnosis', 'spec': spec})
        task_id = digest({'owner': owner, 'fingerprint': fingerprint})[:32]
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,0,NULL,NULL,0,0)',
                       (task_id, owner, fingerprint, encoded(spec), 'QUEUED'))
        return self.get(task_id, owner)

    def change(self, task, state, *, run_id=None, lease=None, tokens=None, rounds=None):
        if task['state'] in TERMINAL:
            raise ValueError('terminal_task')
        transitions = {'QUEUED': {'CANCELLED'}, 'DISPATCH_UNKNOWN': {'RUNNING', 'CANCEL_REQUESTED', 'NEEDS_RECONCILE'},
                       'RUNNING': {'RUNNING', 'CANCEL_REQUESTED', 'NEEDS_RECONCILE', 'VALIDATING', 'FAILED', 'CANCELLED'},
                       'CANCEL_REQUESTED': {'CANCELLED', 'NEEDS_RECONCILE'}, 'VALIDATING': {'SUCCEEDED', 'PARTIAL', 'FAILED'}}
        if state not in transitions.get(task['state'], set()):
            raise ValueError('transition_invalid')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute('UPDATE tasks SET state=?,version=version+1,run_id=?,lease=?,tokens=?,rounds=? '
                                 'WHERE id=? AND owner=? AND version=?',
                                 (state, run_id if run_id is not None else task['run_id'], lease,
                                  task['tokens'] if tokens is None else tokens,
                                  task['rounds'] if rounds is None else rounds,
                                  task['id'], task['owner'], task['version']))
            if updated.rowcount != 1:
                raise ValueError('stale_version')
        return self.get(task['id'], task['owner'])

    def reserve_dispatch(self, task_id, owner, lease):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', lease):
            raise ValueError('invalid_lease')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tasks WHERE id=? AND owner=?', (task_id, owner)).fetchone()
            if row is None:
                raise PermissionError('task_not_found')
            if row['state'] != 'QUEUED':
                raise ValueError('dispatch_requires_queued')
            busy = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN "
                              "('DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')").fetchone()[0]
            if busy:
                raise ValueError('pilot_busy')
            db.execute("UPDATE tasks SET state='DISPATCH_UNKNOWN',version=version+1,lease=? WHERE id=?", (lease, task_id))
        # This durable reservation precedes any future network admission.
        return self.get(task_id, owner)

    def bind_run(self, task_id, owner, lease, run_id):
        task = self.get(task_id, owner)
        if task['state'] != 'DISPATCH_UNKNOWN' or task['lease'] != lease:
            raise ValueError('dispatch_lease_mismatch')
        if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
            raise ValueError('invalid_run_id')
        return self.change(task, 'RUNNING', run_id=run_id, lease=lease)

    def cancel(self, task_id, owner):
        task = self.get(task_id, owner)
        if task['state'] in TERMINAL or task['state'] == 'CANCEL_REQUESTED':
            return task
        if task['state'] == 'QUEUED':
            return self.change(task, 'CANCELLED')
        return self.change(task, 'CANCEL_REQUESTED', lease=task['lease'])

    def observe(self, task_id, owner, lease, remote_status, *, worker_stopped=False):
        task = self.get(task_id, owner)
        if task['lease'] != lease or task['state'] not in {'RUNNING', 'CANCEL_REQUESTED'}:
            raise ValueError('worker_fenced')
        if remote_status in {'queued', 'running', 'stopping', 'waiting_approval'}:
            return task
        if remote_status == 'interrupted':
            return self.change(task, 'NEEDS_RECONCILE')
        if remote_status not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('remote_status_unknown')
        if not worker_stopped:
            return task
        state = 'CANCELLED' if task['state'] == 'CANCEL_REQUESTED' or remote_status == 'cancelled' else 'VALIDATING' if remote_status == 'completed' else 'FAILED'
        return self.change(task, state)

    def fence(self, task_id, owner):
        task = self.get(task_id, owner)
        if task['state'] not in {'RUNNING', 'DISPATCH_UNKNOWN', 'CANCEL_REQUESTED'}:
            raise ValueError('not_in_flight')
        return self.change(task, 'NEEDS_RECONCILE')

    def record_usage(self, task_id, owner, lease, tokens, rounds, *, token_cap, round_cap):
        task = self.get(task_id, owner)
        if task['state'] != 'RUNNING' or task['lease'] != lease:
            raise ValueError('worker_fenced')
        if any(type(x) is not int or x < 0 for x in (tokens, rounds, token_cap, round_cap)) or not token_cap or not round_cap:
            raise ValueError('usage_invalid')
        total, turns = task['tokens']+tokens, task['rounds']+rounds
        state = 'CANCEL_REQUESTED' if total >= token_cap or turns >= round_cap else 'RUNNING'
        return self.change(task, state, lease=lease, tokens=total, rounds=turns)

    def validate_result(self, task_id, owner, report, book):
        task = self.get(task_id, owner)
        if task['state'] != 'VALIDATING' or task['spec']['snapshot_id'] != book.capture_id:
            raise ValueError('validation_context')
        validate_report(report, book)
        return self.change(task, 'PARTIAL' if report['limitations'] else 'SUCCEEDED')


class EvidenceBook:
    """Only validated aggregate projections enter here; live capture is a separate gate."""
    def __init__(self, capture_id, windows):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', capture_id):
            raise ValueError('invalid_snapshot')
        self.capture_id = capture_id
        self.windows = deepcopy(windows)
        self.evidence = {}
        if not isinstance(windows, dict) or not 1 <= len(windows) <= 2:
            raise ValueError('snapshot_windows')
        for name, window in self.windows.items():
            if name not in {'target', 'previous'} or set(window) != {'source_system', 'period', 'as_of', 'currency', 'scope', 'orders', 'revenue_usd', 'order_reference', 'breakdown', 'warnings'}:
                raise ValueError('snapshot_fields')
            if window['source_system'] != 'Admin' or window['scope'] != 'FC27/main' or window['currency'] != 'USD':
                raise ValueError('source_scope_or_currency')
            validate_spec({'period': window['period'], 'snapshot_id': capture_id,
                           'template_version': 'v1', 'knowledge_version': 'v1', 'budget_policy_id': 'offline'})
            try:
                as_of = datetime.fromisoformat(window['as_of'])
            except (ValueError, TypeError):
                raise ValueError('as_of_invalid') from None
            if as_of.tzinfo is None:
                raise ValueError('as_of_invalid')
            codes = {'cost_coverage_missing', 'order_scope_differs', 'refund_adjustments', 'partial_source'}
            if not isinstance(window['warnings'], list) or any(x not in codes for x in window['warnings']):
                raise ValueError('warning_code_invalid')
            if type(window['orders']) is not int or window['orders'] < 0:
                raise ValueError('invalid_count')
            window['revenue_usd'] = money(window['revenue_usd'])
            for metric in ('orders', 'revenue_usd'):
                self.evidence[name+'.'+metric] = {'value': window[metric], 'source_system': 'Admin', 'capture_id': capture_id}
            reference = window['order_reference']
            if not isinstance(reference, dict) or set(reference) != {'status', 'source_system', 'scope', 'reference_margin_pct', 'estimated_profit_usd', 'cost_coverage_pct'}:
                raise ValueError('order_reference_fields')
            if reference['status'] not in {'available', 'partial', 'unavailable'} or reference['source_system'] != 'Order' or reference['scope'] != 'FC27/all-sites':
                raise ValueError('order_reference_scope')
            for metric in ('reference_margin_pct', 'estimated_profit_usd', 'cost_coverage_pct'):
                if reference[metric] is not None:
                    reference[metric] = money(reference[metric])
            margin = reference['reference_margin_pct']
            profit = reference['estimated_profit_usd']
            if profit is not None and (margin is None or profit != money(format((Decimal(window['revenue_usd'])*Decimal(margin)/100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f'))):
                raise ValueError('estimated_profit_mismatch')
            if reference['cost_coverage_pct'] is not None and not 0 <= Decimal(reference['cost_coverage_pct']) <= 100:
                raise ValueError('coverage_invalid')
            if reference['status'] == 'unavailable' and any(reference[k] is not None for k in ('reference_margin_pct', 'estimated_profit_usd', 'cost_coverage_pct')):
                raise ValueError('unavailable_with_values')
            if not isinstance(window['breakdown'], dict) or set(window['breakdown'])-{'platform', 'product', 'bucket'}:
                raise ValueError('breakdown_fields')
            for dimension, rows in window['breakdown'].items():
                if not isinstance(rows, list) or len(rows) > 200:
                    raise ValueError('breakdown_rows')
                keys = set()
                for row in rows:
                    if not isinstance(row, dict) or set(row) != {'key', 'orders', 'revenue_usd'}:
                        raise ValueError('breakdown_row_fields')
                    valid = {'PS', 'XBOX', 'PC'} if dimension == 'platform' else {'Coins', 'Items'} if dimension == 'product' else {str(i) for i in range(10)}
                    if row['key'] not in valid or row['key'] in keys or type(row['orders']) is not int or row['orders'] < 0:
                        raise ValueError('breakdown_row_invalid')
                    keys.add(row['key'])
                    row['revenue_usd'] = money(row['revenue_usd'])
                    for metric in ('orders', 'revenue_usd'):
                        self.evidence[name+'.'+dimension+'.'+row['key']+'.'+metric] = {
                            'value': row[metric], 'source_system': 'Admin', 'capture_id': capture_id}
        if set(self.windows) == {'target', 'previous'}:
            if self.windows['previous']['period']['end_exclusive'] != self.windows['target']['period']['start']:
                raise ValueError('periods_not_adjacent')

    def call(self, name, args):
        if name not in TOOLS or not isinstance(args, dict):
            raise PermissionError('tool_denied')
        if name == 'fc.get_metric_definitions':
            if args:
                raise ValueError('tool_fields')
            return {'version': CONTRACT, 'main_source': 'Admin', 'reference_source': 'Order',
                    'profit': 'estimated_only', 'executable_pricing': False, 'tools': list(TOOLS)}
        fields = {'snapshot_id'} if name == 'fc.compare_periods' else {'snapshot_id', 'window'}
        if name == 'fc.get_breakdown':
            fields.add('dimension')
        if set(args) != fields or args['snapshot_id'] != self.capture_id:
            raise ValueError('snapshot_or_fields')
        if name == 'fc.compare_periods':
            if set(self.windows) != {'target', 'previous'}:
                return {'status': 'unavailable', 'reason': 'comparison_missing'}
            old, new = self.windows['previous'], self.windows['target']
            result = {}
            for key in ('orders', 'revenue_usd'):
                before, after = Decimal(str(old[key])), Decimal(str(new[key]))
                result[key] = {'delta': str(after-before),
                               'pct': format(((after-before)/before*100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f') if before else None,
                               'evidence_ids': ['previous.'+key, 'target.'+key]}
            return {'snapshot_id': self.capture_id, 'data': result}
        window = self.windows.get(args['window'])
        if window is None:
            raise ValueError('window_invalid')
        if name == 'fc.get_business_snapshot':
            return deepcopy({k: v for k, v in window.items() if k not in {'order_reference', 'breakdown'}})
        if name == 'fc.get_order_reference':
            return deepcopy(window['order_reference'])
        if args['dimension'] not in {'platform', 'product', 'bucket'}:
            raise ValueError('dimension_invalid')
        return deepcopy(window['breakdown'].get(args['dimension'], {'status': 'unavailable'}))


def validate_report(report, book):
    if not isinstance(report, dict) or set(report) != {'snapshot_id', 'metrics', 'findings', 'recommendations', 'limitations'}:
        raise ValueError('report_fields')
    if report['snapshot_id'] != book.capture_id:
        raise ValueError('report_snapshot')
    if not isinstance(report['metrics'], list) or not report['metrics']:
        raise ValueError('report_metrics')
    for metric in report['metrics']:
        if not isinstance(metric, dict) or set(metric) != {'evidence_id', 'value'} or metric['evidence_id'] not in book.evidence:
            raise ValueError('metric_reference')
        expected = book.evidence[metric['evidence_id']]['value']
        if type(metric['value']) is not type(expected) or metric['value'] != expected:
            raise ValueError('metric_mismatch')
    if not isinstance(report['findings'], list) or not 1 <= len(report['findings']) <= 3:
        raise ValueError('findings_count')
    for finding in report['findings']:
        if not isinstance(finding, dict) or set(finding) != {'claim_type', 'text', 'evidence_ids', 'alternative', 'missing'}:
            raise ValueError('finding_fields')
        if finding['claim_type'] not in {'fact', 'hypothesis'} or not isinstance(finding['evidence_ids'], list) or not finding['evidence_ids'] or any(ref not in book.evidence for ref in finding['evidence_ids']):
            raise ValueError('finding_reference')
        if finding['claim_type'] == 'hypothesis' and not finding['alternative']:
            raise ValueError('alternative_required')
    if not isinstance(report['recommendations'], list) or len(report['recommendations']) > 3 or not isinstance(report['limitations'], list):
        raise ValueError('report_lists')
    strings = [x for finding in report['findings'] for x in (finding['text'], finding['alternative'], finding['missing'])]
    strings += report['recommendations'] + report['limitations']
    if any(not isinstance(x, str) or len(x) > 1000 for x in strings):
        raise ValueError('text_invalid')
    # Narrative numbers are rendered from validated metric cards in this first candidate.
    if any(re.search(r'\d|[$¥%]', x) for x in strings):
        raise ValueError('unverified_narrative_number')
    if re.search(r'sk-[A-Za-z0-9]|Bearer\s|Cookie\s*[:=]|password\s*[:=]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|已改价|已派单|已退款|已开启图库', encoded(strings), re.I):
        raise ValueError('sensitive_or_executed_statement')
