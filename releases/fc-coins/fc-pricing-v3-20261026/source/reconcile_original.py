"""Reconcile one original FC Coins price operation without replaying Order save or sync."""
from datetime import datetime, timezone
from decimal import Decimal
from contextlib import closing
from fc_pricing_v3.platforms import action_key

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from automation_policy import load_policy
from coin_all_sync_job import (PRODUCTS, allowed_admin_usernames, api, atomic,
                               mirror_confirmed, read_row, reconcile_original as reconcile_all)

ROOT = Path('/run/fc27')
PLATFORMS = ('PS', 'XBOX', 'PC')


def same(left, right):
    return Decimal(str(left)) == Decimal(str(right))


def original_request(request):
    operation_id = request.get('v3_operation_id') or request.get('execution_id')
    if str(uuid.UUID(operation_id)) != operation_id or request.get('execution_id') != operation_id:
        raise ValueError('original_operation_identity_invalid')
    return operation_id


def read_order(audit):
    from playwright.sync_api import sync_playwright
    from isolated_backend import open_backend, close_backend
    from price_writer import PRICE_URL, _global_order, read_backend
    with sync_playwright() as playwright:
        browser = open_backend(playwright)
        if len(browser.contexts) != 1:
            raise ValueError('browser_context_ambiguous')
        _global_order.apply(browser.contexts[0])
        page = browser.contexts[0].new_page()
        try:
            page.goto(PRICE_URL, wait_until='domcontentloaded', timeout=35000)
            first = read_backend(page, audit['targets'], prepare=True)
            time.sleep(2)
            second = read_backend(page, audit['targets'], prepare=True)
            def basis(snapshot):
                return [(row['platform'],row['id'],str(Decimal(str(row['costPrice']))),
                         str(Decimal(str(row['b2c'])))) for row in snapshot['rows']]
            if basis(first) != basis(second):
                raise ValueError('original_order_readback_unstable')
            return second
        finally:
            close_backend(page)


def order_matches(audit, observed):
    before = {row['platform']:row for row in audit['before']['rows']}
    targets = {row['platform']:row for row in audit['targets']}
    actual = {row['platform']:row for row in observed['rows']}
    selected = set(audit['selected'])
    if set(before) != set(PLATFORMS) or set(targets) != set(PLATFORMS) or set(actual) != set(PLATFORMS):
        raise ValueError('original_order_scope_invalid')
    for platform in PLATFORMS:
        cost = targets[platform]['targetCost'] if platform in selected else before[platform]['costPrice']
        price = targets[platform]['quote'] if platform in selected else before[platform]['b2c']
        if not same(actual[platform]['costPrice'],cost) or not same(actual[platform]['b2c'],price):
            return False
    return True


def read_admin(manager, audit, sleep=time.sleep):
    expected = {row['platform']:row['b2c'] for row in audit['after']['rows']}
    if set(expected) != set(PRODUCTS):
        raise ValueError('original_admin_scope_invalid')
    previous = None
    for attempt in range(2):
        identity = api(manager, '/admin/index/index')
        if not isinstance(identity,dict) or identity.get('adminInfo',{}).get('username') not in allowed_admin_usernames():
            raise ValueError('original_admin_identity_invalid')
        current = {}
        for platform in PRODUCTS:
            row = read_row(manager,platform,266)
            if not same(row['unit_price'],expected[platform]):
                raise ValueError('original_admin_recipient_unconfirmed')
            current[platform] = dict(unit_price=str(row['unit_price']),tier_prices=row['more']['price'])
        if previous is not None and current != previous:
            raise ValueError('original_admin_recipient_unstable')
        previous = current
        if attempt == 0:sleep(2)
    return dict(basis='two_stable_original_admin_recipient_reads',checked_at=datetime.now(timezone.utc).isoformat(),
                snapshot_sha256=hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest(),sync_replayed=False)


def postwrite_quote(operation_id, audit, root=ROOT):
    """Return current V3 authority only for unsent ALL steps of the original action."""
    from fc_pricing_v3.runtime import verify_quote
    control=root/'v3'/'control.sqlite3'
    authorization=root/'v3'/'postwrite-authorizations'/(operation_id+'.json')
    postwrite=json.loads(authorization.read_text()) if authorization.exists() else None
    with closing(sqlite3.connect('file:'+str(control.resolve())+'?mode=ro',uri=True,timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        def body(table,key):
            row=db.execute('SELECT body FROM '+table+' WHERE id=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
        operation=body('operations',operation_id)
        original=audit.get('pricing_decision_receipt') or {}
        if (not operation or operation.get('operation_id') != operation_id or
                operation.get('generation') != original.get('engine_generation') or
                original.get('decision_bundle_id') != operation_id or
                original.get('plan_id') != operation.get('plan_id') or
                original.get('sha256') != operation.get('bundle',{}).get('sha256') or
                operation.get('dispatch_context',{}).get('actor') != audit.get('actor') or
                operation.get('bundle',{}).get('action') != original.get('action')):
            raise ValueError('original_postwrite_operation_scope_invalid')
        generation=body('metadata','generation')
        if not generation or generation.get('id')!=operation['generation']:
            raise ValueError('original_postwrite_generation_retired')
        if postwrite:
            if (postwrite.get('operation_id')!=operation_id or
                    postwrite.get('original_operation_id')!=operation_id or
                    postwrite.get('generation')!=operation['generation'] or
                    postwrite.get('current_generation')!=generation['id'] or
                    postwrite.get('authorizes')!='original_unsent_ALL_steps_only'):
                raise ValueError('original_postwrite_authorization_invalid')
            plan=body('pricing_plans',postwrite.get('authorizing_plan_id'))
            if (not plan or plan.get('revision')!=postwrite.get('revision') or
                    plan.get('generation')!=generation['id'] or plan.get('state') not in ('ACTIVE','ENDING')):
                raise ValueError('original_postwrite_authorizing_plan_invalid')
            ancestor=plan;visited=set()
            while ancestor and ancestor['plan_id']!=operation['plan_id']:
                parent=ancestor.get('parent_plan_id')
                if not parent or parent in visited:
                    raise ValueError('original_postwrite_plan_lineage_changed')
                visited.add(parent);ancestor=body('pricing_plans',parent)
            if not ancestor:
                raise ValueError('original_postwrite_plan_lineage_changed')
        else:
            plan=body('pricing_plans',operation['bundle']['plan_id'])
            if (not plan or plan.get('state')!='ACTIVE' or
                    plan.get('ends_at') and datetime.fromisoformat(plan['ends_at'])<=datetime.now(timezone.utc)):
                raise ValueError('original_postwrite_plan_inactive')
        for resource in operation['bundle'].get('mutable_resources') or operation['resources']:
            owner=db.execute('SELECT plan_id,revision,generation FROM plan_ownership WHERE resource=?',(resource,)).fetchone()
            if owner!=(plan['plan_id'],plan['revision'],plan['generation']):
                raise ValueError('original_postwrite_resource_taken_over')
        reservation=body('reservations',operation_id)
        if operation['bundle'].get('budget_policy')!='none' and (not reservation or reservation.get('operation_id')!=operation_id or
                reservation.get('plan_id')!=operation['plan_id'] or reservation.get('state')!='RESERVED'):
            raise ValueError('original_postwrite_budget_reservation_missing')
    run_id=str(uuid.UUID(postwrite['quote_run_id'] if postwrite else audit['run_id']))
    quote=json.loads((root/'quotes'/(run_id+'.json')).read_text())
    if quote.get('evidence',{}).get('run_id')!=run_id:
        raise ValueError('original_postwrite_quote_run_changed')
    receipt=verify_quote(quote,load_policy(),list(PLATFORMS),for_execution=True,
                         **({'purpose':'original_unsent_ALL_steps_only'} if postwrite else {}))
    if postwrite:
        if (receipt.get('sha256')!=postwrite.get('quote_sha256') or
                receipt.get('authorization_purpose')!='original_unsent_ALL_steps_only' or
                receipt.get('decision_bundle_id')!=operation_id or
                receipt.get('engine_generation')!=generation['id'] or
                receipt.get('plan_id')!=plan['plan_id'] or receipt.get('revision')!=plan['revision'] or
                any(receipt.get('action',{}).get('base_prices',{}).get(action_key(receipt['action'],group)) is None or
                    not same(receipt['action']['base_prices'][action_key(receipt['action'],group)],original['action']['base_prices'][action_key(original['action'],group)])
                    for group in PLATFORMS)):
            raise ValueError('original_postwrite_action_changed')
    elif (receipt.get('action')!=original.get('action') or
            receipt.get('engine_generation')!=operation['generation'] or
            receipt.get('plan_id')!=operation['bundle'].get('plan_id')):
        raise ValueError('original_postwrite_action_changed')
    rows={row['platform']:row for row in audit['after']['rows']}
    if set(rows)!=set(PLATFORMS):
        raise ValueError('original_postwrite_order_scope_invalid')
    for platform in PLATFORMS:
        group=action_key(receipt['action'],platform)
        if not same(Decimal(str(rows[platform]['b2c']))*100,receipt['action']['base_prices'][group]):
            raise ValueError('original_postwrite_actual_price_changed')
    return lambda:quote


def all_manager():
    sys.path.insert(0,'/usr/local/bin')
    from p2pah_session_service import SessionManager,read_private_config
    manager=SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError('original_admin_session_unavailable')
    return manager


def reconcile(request, root=ROOT, order_reader=read_order, manager_factory=all_manager):
    operation_id=original_request(request)
    path=root/'executions'/(operation_id+'.json')
    audit=json.loads(path.read_text())
    if (audit.get('execution_id')!=operation_id or audit.get('preview_id')!=request.get('preview_id') or
            audit.get('actor')!=request.get('actor') or audit.get('selected')!=request.get('platforms') or
            audit.get('automation_policy_revision')!=request.get('policy_revision')):
        raise ValueError('original_audit_request_mismatch')
    if audit.get('status') not in ('RUNNING','UNCERTAIN','PARTIAL','CONFIRMED'):
        raise ValueError('original_audit_not_reconcilable')
    def save(value):atomic(path,value)
    if audit['status']=='CONFIRMED':
        if audit.get('sync_confirmed') is True and (audit.get('all_baseline') or {}).get('status')=='confirmed':
            return dict(status='CONFIRMED',execution_id=operation_id,original_proof_preserved=True)
        audit.update(status='PARTIAL',stage='original_reconciliation_pending')
        save(audit)
    observed=order_reader(audit)
    if not order_matches(audit,observed):
        return dict(status=audit['status'],execution_id=operation_id,reason='original_order_prices_or_cost_not_confirmed',
                    price_posts_retried=0,sync_replayed=False)
    audit['after']=observed
    manager=manager_factory()
    try:
        recipient=read_admin(manager,audit)
    except ValueError as error:
        return dict(status=audit['status'],execution_id=operation_id,reason=str(error),
                    price_posts_retried=0,sync_replayed=False)
    audit.update(status='PARTIAL',stage='all_baseline_pending',sync_confirmed=True,
                 sync_recipient_readback=recipient)
    save(audit)
    ledger_path=root/'all-coin-sync'/(operation_id+'.json')
    if ledger_path.exists():
        def persist(record):atomic(ledger_path,record)
        record=json.loads(ledger_path.read_text())
        result=reconcile_all(manager,audit,record,save,persist,load_policy)
        if result['status']=='confirmed':
            return dict(status='CONFIRMED',execution_id=operation_id,all=result,price_posts_retried=0,sync_replayed=False)
        if result['status']!='requires_fresh_postwrite_authorization':
            return dict(status='PARTIAL',execution_id=operation_id,all=result,price_posts_retried=0,sync_replayed=False)
    try:
        current_quote=postwrite_quote(operation_id,audit,root)
    except (ValueError,KeyError,FileNotFoundError) as error:
        return dict(status='PARTIAL',execution_id=operation_id,reason='requires_fresh_postwrite_authorization',
                    authorization_gap=str(error),price_posts_retried=0,sync_replayed=False)
    if ledger_path.exists():
        record=json.loads(ledger_path.read_text())
        result=reconcile_all(manager,audit,record,save,persist,load_policy,current_quote)
    else:
        result=mirror_confirmed(audit,load_policy(),save,root,load_policy,current_quote,manager=manager)
    return dict(status='CONFIRMED' if result.get('status')=='confirmed' else 'PARTIAL',
                execution_id=operation_id,all=result,price_posts_retried=0,sync_replayed=False)


def main():
    if sys.argv[1:] != ['--command=reconcile']:
        raise ValueError('original_reconcile_command_required')
    request=json.loads(Path('/run/request.json').read_text())
    print(json.dumps(reconcile(request),ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps(dict(status='FAILED',reason=str(error) if isinstance(error,ValueError) else type(error).__name__)))
        raise SystemExit(1)
