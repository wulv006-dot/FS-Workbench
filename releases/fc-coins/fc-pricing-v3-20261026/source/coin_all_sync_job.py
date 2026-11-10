def allowed_admin_usernames():
    import sys
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import allowed_admin_usernames as allowed
    return allowed()
"""Mirror confirmed MMOEXP FC27 coin prices to its three ALL fallback products.

No price calculation, recalc, cache clear, policy change or automatic replay.
Run only after the existing writer confirms MMOEXP, under its existing lock.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time

PRODUCTS = {'PS': (163329309, 163329311, 21587),
            'XBOX': (163329275, 163329277, 21585),
            'PC': (163329343, 163329345, 21589)}
DEFAULT_KEYWORDS = {'PS':'fc 27 playstation 5 gold coins',
                    'XBOX':'fc 27 xbox series x s gold coins',
                    'PC':'fc 27 pc platform gold coins'}
# A just-dispatched ALL write can be served stale for a moment, so one read
# right after a POST is not proof of propagation. Confirmation re-reads are
# GET-only and bounded: the whole mirror normally takes well under 20s inside
# the writer's own 130s subprocess envelope, so the retry budget below stays
# far away from that envelope even when every product has to be re-read.
READBACK_STEP_SECONDS = 30        # budget for one product
READBACK_TOTAL_SECONDS = 45       # shared by every product of one mirror run
READBACK_INTERVAL_SECONDS = 3
READBACK_STABLE_ROUNDS = 2


def unchanged(before, after, platform, price_fields=False):
    """Allow only the native empty-to-exact catalog keyword normalization."""
    left = protected(before) if price_fields else editable(before)
    right = protected(after) if price_fields else editable(after)
    if (left.get('keywords') in ('', None)
            and right.get('keywords') == DEFAULT_KEYWORDS[platform]):
        right['keywords'] = left.get('keywords')
        if 'keywords' not in left: right.pop('keywords', None)
    return left == right


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('coin_price_invalid') from None
    if isinstance(value, bool) or not result.is_finite() or result <= 0:
        raise ValueError('coin_price_invalid')
    return result


def api(manager, path, payload=None, observer=None):
    # In particular, never retry a POST whose outcome is unknown.
    started = datetime.now(timezone.utc).isoformat()
    try:
        status, raw = manager.request(path, data=payload, token=manager.token)
    except Exception as error:
        if observer: observer({'path':path,'started_at':started,'received_at':datetime.now(timezone.utc).isoformat(),
                               'transport_error':type(error).__name__})
        raise
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        if observer: observer({'path':path,'started_at':started,'received_at':datetime.now(timezone.utc).isoformat(),
                               'http_status':status,'response_code':None,'response_sha256':hashlib.sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest()})
        raise ValueError('coin_backend_response_invalid') from None
    if observer: observer({'path':path,'started_at':started,'received_at':datetime.now(timezone.utc).isoformat(),
                           'http_status':status,'response_code':value.get('code'),'response_sha256':hashlib.sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest()})
    if status != 200 or value.get('code') != 1:
        raise ValueError('coin_backend_request_rejected')
    return value.get('data')


def editable(row):
    return deepcopy({k:v for k,v in row.items()
                     if not k.startswith(('_', 'stat_')) and v is not None})


def protected(row):
    value = editable(row)
    value.pop('unit_price', None)
    value['more'].pop('price', None)
    return value


def read_row(manager, platform, site, observer=None):
    all_id, site_id, aid = PRODUCTS[platform]
    product_id = all_id if site == 0 else site_id
    result = api(manager, '/admin/goods.Goods/edit?id=' + str(product_id), observer=observer)
    row = result.get('row') if isinstance(result, dict) else None
    expected = {'id':product_id, 'mid':41217957, 'gid':1327, 'cid':9623,
                'site_id':site, 'aid':aid, 'unit':'K', 'title':'coins', 'status':1}
    if not isinstance(row, dict) or any(str(row.get(k)) != str(v) for k,v in expected.items()):
        raise ValueError('coin_product_scope_changed')
    money(row.get('unit_price'))
    more = row.get('more')
    if not isinstance(more, dict) or not isinstance(more.get('gold'), list) or not more['gold']:
        raise ValueError('coin_tiers_invalid')
    for key in ('price','gold','discount','give','delivery_time','hot'):
        if not isinstance(more.get(key), list) or len(more[key]) != len(more['gold']):
            raise ValueError('coin_tiers_invalid')
    for price in more['price']:
        money(price)
    return row


def wait_sources(manager, audit, policy, record, persist, read_policy,
                 max_seconds=45, interval_seconds=5, clock=None, sleep=None):
    """Only GETs: two stable confirmations; no POST/auth retry on any failure."""
    clock = clock or time.monotonic; sleep = sleep or time.sleep
    rates = validate(audit, policy)
    old = {r['platform']:money(r['b2c']) for r in audit.get('before',{}).get('rows',[])}
    identity = api(manager,'/admin/index/index')
    if not isinstance(identity,dict) or identity.get('adminInfo',{}).get('username') not in allowed_admin_usernames():raise ValueError('coin_identity_invalid')
    deadline=clock()+max_seconds;previous=None;baseline={}
    evidence={'status':'waiting','started_at':datetime.now(timezone.utc).isoformat(),
              'deadline_at':datetime.fromtimestamp(time.time()+max_seconds,timezone.utc).isoformat(),
              'max_seconds':max_seconds,'interval_seconds':interval_seconds,'required_stable_rounds':2,'rounds':[]}
    record['source_confirmation']=evidence;persist(record)
    try:
        while True:
            if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
            current_policy=read_policy();validate(audit,current_policy)
            if current_policy!=policy:raise ValueError('coin_source_confirmation_policy_changed')
            round_evidence={'started_at':datetime.now(timezone.utc).isoformat(),'observations':[]}
            evidence['rounds'].append(round_evidence);persist(record)
            snapshot={};matched=True
            for platform in PRODUCTS:
                if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
                item={'platform':platform,'product_id':PRODUCTS[platform][1],
                      'expected_unit_price':str(rates[platform]),'allowed_before_unit_price':str(old.get(platform,rates[platform]))}
                round_evidence['observations'].append(item);persist(record)
                def observe(meta):item.update(meta);persist(record)
                row=read_row(manager,platform,266,observe)
                item.update(observed_unit_price=str(row['unit_price']),raw_value_type=type(row['unit_price']).__name__,
                            tier_prices=deepcopy(row['more']['price']),
                            record_timestamps={k:row[k] for k in ('update_time','updated_at','updatetime','create_time','createtime') if k in row})
                persist(record)
                if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
                value=money(row['unit_price'])
                if value not in (rates[platform],old.get(platform,rates[platform])):
                    raise ValueError('coin_source_or_before_changed')
                if platform in baseline and not unchanged(baseline[platform],row,platform,True):
                    raise ValueError('coin_source_protected_changed')
                baseline.setdefault(platform,deepcopy(row))
                matched=matched and value==rates[platform];snapshot[platform]=editable(row)
            round_evidence['all_rates_match']=matched;persist(record)
            if matched and previous==snapshot:
                evidence.update(status='confirmed',confirmed_at=datetime.now(timezone.utc).isoformat())
                persist(record);return snapshot
            previous=snapshot if matched else None
            remaining=deadline-clock()
            if remaining<=0:raise ValueError('coin_source_confirmation_timeout')
            sleep(min(interval_seconds,remaining))
    except Exception as error:
        evidence.update(status='stopped',stopped_at=datetime.now(timezone.utc).isoformat(),
                        reason=str(error) if isinstance(error,ValueError) else type(error).__name__)
        persist(record);raise


def validate(audit, policy):
    if (audit.get('status') not in ('CONFIRMED','PARTIAL') or audit.get('sync_confirmed') is not True
            or audit.get('automation_policy_revision') != policy.get('revision')
            or policy.get('system_enabled') is not True
            or set(policy.get('platforms', [])) != set(PRODUCTS)
            or (audit.get('automatic') is True and policy.get('mode') != 'auto')):
        raise ValueError('coin_all_sync_preflight_changed')
    if audit['status'] == 'PARTIAL' and audit.get('stage') != 'all_baseline_pending':
        raise ValueError('coin_all_sync_execution_unconfirmed')
    rows = audit.get('after', {}).get('rows', [])
    if len(rows) != 3 or {r.get('platform') for r in rows} != set(PRODUCTS):
        raise ValueError('coin_confirmed_rates_incomplete')
    return {r['platform']: money(r.get('b2c')) for r in rows}


def plan(manager, audit, policy):
    rates = validate(audit, policy)
    identity = api(manager, '/admin/index/index')
    if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') not in allowed_admin_usernames():
        raise ValueError('coin_identity_invalid')
    steps = []
    for platform in PRODUCTS:
        fallback, source = read_row(manager, platform, 0), read_row(manager, platform, 266)
        if money(source['unit_price']) != rates[platform]:
            raise ValueError('coin_mmoexp_confirmed_rate_mismatch')
        # Only mirror actual, already-confirmed prices. Do not invent tiers or discounts.
        if any(fallback['more'][k] != source['more'][k] for k in ('gold','discount','give')):
            raise ValueError('coin_tier_basis_changed')
        payload = editable(fallback)
        payload['unit_price'] = deepcopy(source['unit_price'])
        payload['more']['price'] = deepcopy(source['more']['price'])
        changed = (money(fallback['unit_price']) != rates[platform]
                   or fallback['more']['price'] != source['more']['price'])
        steps.append({'platform':platform, 'product_id':fallback['id'],
                      'source_product_id':source['id'], 'before':fallback,
                      'source':source, 'payload':payload, 'changed':changed})
    return steps


def synchronize(manager, audit, policy, save_audit, claim, persist, read_policy, current_quote=None):
    validate(audit, policy)
    # The main execution itself blocks later writes and Players until all six reads pass.
    audit.update(status='PARTIAL', stage='all_baseline_pending')
    save_audit(audit)
    record = {'execution_id':audit['execution_id'], 'status':'preflight', 'steps':[]}
    try:
        claim(record)  # Exclusive ledger: an interrupted invocation must be reconciled.
        confirmed_sources=wait_sources(manager,audit,policy,record,persist,read_policy)
        steps = plan(manager, audit, policy)
        if any(editable(s['source'])!=confirmed_sources[s['platform']] for s in steps):
            raise ValueError('coin_source_changed_after_confirmation')
        record['steps'] = [{k:deepcopy(step[k]) for k in ('platform','product_id','source_product_id',
                            'before','source','payload','changed')} | {'status':'pending'} for step in steps]
        persist(record)
        return drive(manager, audit, policy, steps, record, save_audit, persist, read_policy, current_quote)
    except Exception:
        # Never turn a possibly successful POST into an automatic retry.
        record['status'] = 'needs_reconcile'
        try:
            persist(record)
        except (OSError, ValueError):
            pass
        audit['all_baseline'] = {'status':'needs_reconcile'}
        save_audit(audit)
        raise


def confirm_timed_out_write(manager, audit, step, item, record, persist, read_policy,
                            clock=None, sleep=None):
    """Prove a landed original POST with two stable GET rounds; never POST again."""
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    deadline = clock() + 30
    proof = {'status':'checking','original_error':'TimeoutError','max_seconds':30,
             'required_stable_rounds':2,'rounds':[],'price_posts_retried':0}
    item['timeout_readback'] = proof
    persist(record)
    previous = None
    for attempt in range(2):
        if clock() >= deadline:
            raise ValueError('coin_timeout_readback_deadline')
        rates = validate(audit, read_policy())
        identity = api(manager, '/admin/index/index')
        if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') not in allowed_admin_usernames():
            raise ValueError('coin_identity_invalid')
        source = read_row(manager, step['platform'], 266)
        actual = read_row(manager, step['platform'], 0)
        if (not unchanged(step['source'], source, step['platform'])
                or money(source['unit_price']) != rates[step['platform']]):
            raise ValueError('coin_timeout_source_changed')
        verify_step(step, actual, source)
        observed = {'source':editable(source),'actual':editable(actual)}
        if clock() >= deadline or (previous is not None and observed != previous):
            raise ValueError('coin_timeout_readback_not_stable')
        proof['rounds'].append({'checked_at':datetime.now(timezone.utc).isoformat(),
            'product_id':step['product_id'],'source_product_id':step['source_product_id'],
            'snapshot_sha256':hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest()})
        persist(record)
        previous = observed
        if attempt == 0:
            sleep(5)
    proof.update(status='confirmed',confirmed_at=datetime.now(timezone.utc).isoformat())
    persist(record)


def drive(manager, audit, policy, steps, record, save_audit, persist, read_policy, current_quote=None):
    try:
        # One shared read-only budget for every post-dispatch confirmation below.
        readback_deadline = time.monotonic() + READBACK_TOTAL_SECONDS
        for step, item in zip(steps, record['steps']):
            validate(audit, read_policy())
            current_source = read_row(manager, step['platform'], 266)
            current = read_row(manager, step['platform'], 0)
            if not unchanged(step['source'], current_source, step['platform']):
                raise ValueError('coin_source_or_before_changed')
            if item['status'] == 'confirmed':
                # Explicitly reconciled landed write: read it, NEVER dispatch it again.
                verify_step(step, current, current_source)
                continue
            if item['status'] != 'pending' or editable(current) != editable(step['before']):
                raise ValueError('coin_source_or_before_changed')
            if step['changed']:
                from automation_policy import hooks_before_write
                native = (audit.get('pricing_decision_receipt') or {}).get('price_scope_contract') == 'fc27_three_platform_v1'
                scope = [step['platform']] if native else (['PS','XBOX'] if step['platform'] in ('PS','XBOX') else ['PC'])
                hooks_before_write(read_policy(), scope, audit.get('automatic') is True,
                                   current_quote=current_quote)
                item['status'] = 'dispatching'
                record['status'] = 'dispatching'
                persist(record)  # Durable intent BEFORE a single POST.
                def observe_post(meta):
                    item['post_response'] = meta
                    persist(record)
                try:
                    api(manager, '/admin/goods.Goods/edit?id=' + str(step['product_id']),
                        step['payload'], observer=observe_post)
                except TimeoutError:
                    confirm_timed_out_write(manager, audit, step, item, record, persist, read_policy)
            if step['changed']:
                # Confirm only by re-reading: a momentary stale row is not a failed write,
                # and the POST above is never repeated by this bounded GET loop.
                verify_dispatch_readback(manager, step, current_source, item, record, persist,
                                         max_seconds=readback_deadline - time.monotonic())
            else:
                verify_step(step, read_row(manager, step['platform'], 0), current_source)
            item['status'] = 'confirmed'
            persist(record)
        for step in steps:
            source = read_row(manager, step['platform'], 266)
            actual = read_row(manager, step['platform'], 0)
            if (not unchanged(step['source'], source, step['platform'])
                    or not unchanged(step['before'], actual, step['platform'], True)
                    or money(actual['unit_price']) != money(source['unit_price'])
                    or actual['more']['price'] != source['more']['price']):
                raise ValueError('coin_six_product_readback_mismatch')
        record.update(status='confirmed', completed_at=datetime.now(timezone.utc).isoformat())
        persist(record)
        audit.update(status='CONFIRMED', stage='readback_confirmed',
                     all_baseline={'status':'confirmed', 'platforms':list(PRODUCTS),
                                   'products':[s['product_id'] for s in steps],
                                   'completed_at':record['completed_at']})
        save_audit(audit)
        return {'status':'confirmed', 'platforms':list(PRODUCTS),
                'changed_products':[s['product_id'] for s in steps if s['changed']]}
    except Exception:
        # Never turn a possibly successful POST into an automatic retry.
        record['status'] = 'needs_reconcile'
        try:
            persist(record)
        except (OSError, ValueError):
            pass
        audit['all_baseline'] = {'status':'needs_reconcile'}
        save_audit(audit)
        raise


def verify_step(step, actual, source):
    if (not unchanged(step['before'], actual, step['platform'], True)
            or money(actual['unit_price']) != money(source['unit_price'])
            or actual['more']['price'] != source['more']['price']):
        raise ValueError('coin_all_readback_mismatch')


def verify_dispatch_readback(manager, step, source, item, record, persist,
                             max_seconds=None, interval_seconds=READBACK_INTERVAL_SECONDS,
                             clock=None, sleep=None):
    """Confirm a just-dispatched ALL product with bounded, read-only re-reads.

    The product is read again until READBACK_STABLE_ROUNDS consecutive rounds
    match the already confirmed MMOEXP source, so a momentary stale row cannot
    be mistaken for a failed write. This loop only ever issues GETs: the price
    POST is never dispatched again here, and the whole loop is bounded by
    max_seconds (itself capped by READBACK_STEP_SECONDS).
    """
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    budget = READBACK_STEP_SECONDS if max_seconds is None else max(0.0, max_seconds)
    budget = min(budget, READBACK_STEP_SECONDS)
    deadline = clock() + budget
    proof = {'status':'checking', 'read_only':True, 'price_posts_retried':0,
             'max_seconds':budget, 'interval_seconds':interval_seconds,
             'required_stable_rounds':READBACK_STABLE_ROUNDS, 'rounds':[]}
    item['dispatch_readback'] = proof
    persist(record)
    previous = None
    rounds = max(READBACK_STABLE_ROUNDS, int(budget // interval_seconds) + READBACK_STABLE_ROUNDS)
    for attempt in range(rounds):
        actual = read_row(manager, step['platform'], 0)
        try:
            verify_step(step, actual, source)
        except ValueError:
            matched = False
        else:
            matched = True
        observed = editable(actual)
        proof['rounds'].append({'checked_at':datetime.now(timezone.utc).isoformat(),
            'attempt':attempt, 'product_id':step['product_id'], 'matched':matched,
            'unit_price':str(actual.get('unit_price')),
            'row_sha256':hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()})
        persist(record)
        if matched and previous == observed:
            proof.update(status='confirmed', confirmed_at=datetime.now(timezone.utc).isoformat())
            persist(record)
            return actual
        previous = observed if matched else None
        if attempt == rounds - 1:
            break
        remaining = deadline - clock()
        # An exhausted budget only stops the waiting, never the minimum proof.
        if remaining > 0:
            sleep(min(interval_seconds, remaining))
    proof.update(status='stopped', stopped_at=datetime.now(timezone.utc).isoformat(),
                 reason='coin_all_readback_timeout')
    persist(record)
    raise ValueError('coin_all_readback_mismatch')


def resume_synchronize(manager, audit, policy, record, save_audit, persist, read_policy):
    """Explicit once-only reconciliation; unfinished dispatch must already read back."""
    validate(audit, policy)
    if (audit.get('kind') != 'all_baseline_repair'
            or record.get('execution_id') != audit['execution_id']
            or record.get('status') != 'needs_reconcile'
            or [s.get('platform') for s in record.get('steps', [])] != list(PRODUCTS)
            or [s.get('status') for s in record['steps']] != ['dispatching','pending','pending']):
        raise ValueError('coin_reconcile_scope_changed')
    steps = record['steps']
    # Validate every persisted identity and payload against the original snapshots.
    for step in steps:
        platform = step['platform']; all_id, source_id, aid = PRODUCTS[platform]
        if step['product_id'] != all_id or step['source_product_id'] != source_id:
            raise ValueError('coin_reconcile_scope_changed')
        expected = editable(step['before'])
        expected['unit_price'] = step['source']['unit_price']
        expected['more']['price'] = step['source']['more']['price']
        if step['payload'] != expected: raise ValueError('coin_reconcile_payload_changed')
        source = read_row(manager, platform, 266); current = read_row(manager, platform, 0)
        if (not unchanged(step['source'], source, platform)
                or money(source['unit_price']) != validate(audit, policy)[platform]):
            raise ValueError('coin_reconcile_source_changed')
        if step['status'] == 'dispatching': verify_step(step, current, source)
        elif editable(current) != editable(step['before']):
            raise ValueError('coin_reconcile_pending_changed')
    # Only ledger changes here; the PS business write is already independently proven.
    steps[0]['status'] = 'confirmed'
    steps[0]['reconciled_read_only_at'] = datetime.now(timezone.utc).isoformat()
    record['status'] = 'reconciled_continuation'
    persist(record)
    return drive(manager, audit, policy, steps, record, save_audit, persist, read_policy)


def resume_empty_preflight(manager, audit, policy, record, save_audit, persist, read_policy):
    """Continue only a proven empty ALL preflight; never repeat MMOEXP synchronization."""
    if (audit.get('status')!='PARTIAL' or audit.get('stage')!='stopped'
            or audit.get('error')!='coin_mmoexp_confirmed_rate_mismatch'
            or audit.get('sync_confirmed') is not True or audit.get('automatic') is not True
            or record.get('execution_id')!=audit.get('execution_id')
            or record.get('status')!='needs_reconcile' or record.get('steps')!=[]):
        raise ValueError('coin_empty_recovery_scope_changed')
    context=deepcopy(audit);context['stage']='all_baseline_pending'
    validate(context,policy)
    confirmed_sources=wait_sources(manager,context,policy,record,persist,read_policy)
    steps=plan(manager,context,policy)
    if any(editable(s['source'])!=confirmed_sources[s['platform']] for s in steps):
        raise ValueError('coin_source_changed_after_confirmation')
    record['steps']=[{k:deepcopy(s[k]) for k in ('platform','product_id','source_product_id','before','source','payload','changed')}|{'status':'pending'} for s in steps]
    record['status']='continued_after_source_confirmation';persist(record)
    audit.setdefault('recovery_history',[]).append({'stage':audit['stage'],'error':audit['error'],
        'continued_at':datetime.now(timezone.utc).isoformat(),'mmoexp_replayed':False})
    audit.update(stage='all_baseline_pending');save_audit(audit)
    return drive(manager,audit,policy,steps,record,save_audit,persist,read_policy)


def atomic(path, value):
    fd, name = tempfile.mkstemp(prefix='.coin-all-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',',':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o640)
        if path.exists():
            os.chown(name, -1, path.stat().st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def mirror_confirmed(audit, policy, save_audit, root, read_policy, current_quote=None, manager=None):
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import SessionManager, read_private_config
    ledger = root / 'all-coin-sync' / (audit['execution_id'] + '.json')
    claimed = False
    def claim(record):
        nonlocal claimed
        with ledger.open('x', encoding='utf-8') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(ledger, 0o640)
        claimed = True
    def persist(record):
        if not claimed: raise ValueError('coin_all_ledger_not_owned')
        atomic(ledger, record)
    manager = manager or SessionManager(read_private_config())
    if not manager.ensure(): raise ValueError('coin_auth_unavailable')
    return synchronize(manager, audit, policy, save_audit, claim, persist, read_policy, current_quote)


def reconcile_original(manager, audit, record, save_audit, persist, read_policy,
                       current_quote=None, sleep=None):
    """Reconcile one original ALL ledger; only persisted pending steps may dispatch."""
    sleep = sleep or time.sleep
    if record.get('execution_id') != audit.get('execution_id') or record.get('status') not in (
            'preflight', 'dispatching', 'needs_reconcile', 'confirmed',
            'reconciled_continuation', 'continued_after_source_confirmation'):
        raise ValueError('coin_original_ledger_scope_invalid')
    steps = record.get('steps')
    if not isinstance(steps,list) or steps and [step.get('platform') for step in steps] != list(PRODUCTS):
        raise ValueError('coin_original_ledger_scope_invalid')
    rates = {r['platform']:money(r['b2c']) for r in audit.get('after',{}).get('rows',[])}
    if set(rates)!=set(PRODUCTS) or audit.get('sync_confirmed') is not True:
        raise ValueError('coin_original_order_confirmation_missing')
    if not steps:
        if current_quote is None:
            return dict(status='requires_fresh_postwrite_authorization',all_posts_retried=0)
        policy=read_policy()
        context=dict(audit,status='PARTIAL',stage='all_baseline_pending')
        confirmed=wait_sources(manager,context,policy,record,persist,read_policy)
        planned=plan(manager,context,policy)
        if any(editable(step['source'])!=confirmed[step['platform']] for step in planned):
            raise ValueError('coin_original_source_changed')
        record['steps']=[{k:deepcopy(step[k]) for k in ('platform','product_id','source_product_id',
                         'before','source','payload','changed')} | {'status':'pending'} for step in planned]
        record['status']='continued_after_source_confirmation';persist(record)
        return drive(manager,context,policy,record['steps'],record,save_audit,persist,read_policy,current_quote)
    for step in steps:
        platform=step['platform'];all_id,source_id,_=PRODUCTS[platform]
        if (step.get('product_id')!=all_id or step.get('source_product_id')!=source_id
                or step.get('status') not in ('pending','dispatching','confirmed')):
            raise ValueError('coin_original_ledger_scope_invalid')
        expected=editable(step['before'])
        expected['unit_price']=step['source']['unit_price']
        expected['more']['price']=step['source']['more']['price']
        if step.get('payload')!=expected:
            raise ValueError('coin_original_ledger_payload_changed')
    previous=None
    for attempt in range(2):
        identity=api(manager,'/admin/index/index')
        if not isinstance(identity,dict) or identity.get('adminInfo',{}).get('username') not in allowed_admin_usernames():
            raise ValueError('coin_identity_invalid')
        observed={}
        for step in steps:
            platform=step['platform']
            source=read_row(manager,platform,266)
            actual=read_row(manager,platform,0)
            if (not unchanged(step['source'],source,platform)
                    or money(source['unit_price'])!=rates[platform]):
                raise ValueError('coin_original_source_changed')
            if step['status'] in ('confirmed','dispatching'):
                verify_step(step,actual,source)
            elif editable(actual)!=editable(step['before']):
                verify_step(step,actual,source)
            observed[platform]=dict(source=editable(source),actual=editable(actual))
        if previous is not None and observed!=previous:
            raise ValueError('coin_original_all_readback_unstable')
        previous=observed
        if attempt==0:sleep(2)
    checked=datetime.now(timezone.utc).isoformat()
    for step in steps:
        if step['status']=='dispatching':
            step.update(status='confirmed',reconciled_read_only_at=checked,
                        original_post_not_retried=True)
        elif step['status']=='pending' and editable(previous[step['platform']]['actual'])==editable(step['payload']):
            step.update(status='confirmed',observed_target_without_original_post_at=checked,
                        original_post_not_retried=True)
    record['original_reconciliation']=dict(checked_at=checked,stable_rounds=2,
        readback_sha256=hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest(),
        price_posts_retried=0)
    persist(record)
    if any(step['status']=='pending' for step in steps):
        if current_quote is None:
            return dict(status='requires_fresh_postwrite_authorization',all_posts_retried=0)
        context=dict(audit,status='PARTIAL',stage='all_baseline_pending')
        return drive(manager,context,read_policy(),steps,record,save_audit,persist,read_policy,current_quote)
    record.update(status='confirmed',completed_at=checked)
    persist(record)
    audit.update(status='CONFIRMED',stage='readback_confirmed',sync_confirmed=True,
        all_baseline=dict(status='confirmed',platforms=list(PRODUCTS),
                          products=[step['product_id'] for step in steps],
                          completed_at=checked,reconciled_read_only=True))
    save_audit(audit)
    return dict(status='confirmed',platforms=list(PRODUCTS),all_posts_retried=0)
