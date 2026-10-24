"""Native coupon lifecycle, exact-ID scope and server-private verification gates."""
import hashlib
import re
import json

from .catalog import positive_id
from .core import ContractError, canonical, identity
from .ledger import ObjectOperationBusy, now

COUPON_FIELDS = ('title', 'brief', 'status', 'type', 'fetch_scene', 'mode_type', 'attain', 'reduce',
    'max_reduce', 'limit_qty', 'fetch_qty', 'used_qty', 'repeat_qty', 'time_effect', 'start_time',
    'end_time', 'days', 'site_id', 'game_id', 'product_type', 'goods_id', 'is_open')
DISCOUNT_FIELDS = ('status', 'type', 'attain', 'discount', 'site_id', 'gid', 'aid', 'cid',
                   'exclude_gids', 'repeat_qty', 'timestart', 'timeend')
REQUIRED_PROOFS = ('ownership_verified', 'exact_id_readback_verified', 'compensation_verified',
                   'status_zero_verified')


def safe_response_evidence(response=None, error=None):
    """Only numeric business codes and hash/length metadata cross the audit boundary."""
    result = dict(event='transport_exception' if error is not None else 'http_response',
        http_status=None, parse_status='transport_exception' if error is not None else 'body_unavailable',
        business_code=None, business_code_type='missing', business_code_sha256=None, business_code_length=None,
        msg_class='missing', msg_type='missing', msg_sha256=None, msg_length=None, msg_size_bytes=None,
        body_sha256=None, body_size=None, error_class=None, error_sha256=None, error_length=None, observed_at=now())
    def hashed(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
        raw = text.encode('utf-8', errors='surrogatepass')
        return hashlib.sha256(raw).hexdigest(), len(text), len(raw)
    if error is not None:
        name = type(error).__name__
        result['error_class'] = name if name in {'TimeoutError', 'Timeout', 'ReadTimeout', 'ConnectTimeout',
            'ConnectionError', 'HTTPError', 'SSLError', 'RequestException', 'OSError'} else 'other_exception'
        try:
            result['error_sha256'], result['error_length'], _ = hashed(str(error))
        except Exception:
            pass
        return result
    status = getattr(response, 'status_code', None)
    if type(status) is int and 100 <= status <= 599:
        result['http_status'] = status
    raw = getattr(response, 'content', None)
    if not isinstance(raw, bytes):
        return result
    result.update(body_sha256=hashlib.sha256(raw).hexdigest(), body_size=len(raw))
    if len(raw) > 65536:
        result['parse_status'] = 'body_too_large'
        return result
    try:
        payload = json.loads(raw)
    except Exception:
        result['parse_status'] = 'invalid_json'
        return result
    if not isinstance(payload, dict):
        result['parse_status'] = 'json_non_object'
        return result
    result['parse_status'] = 'json_object'
    if 'code' in payload:
        code = payload['code']
        result['business_code_type'] = ('null' if code is None else type(code).__name__
                                        if type(code) in (str, int, bool, float) else 'non_scalar')
        try:
            result['business_code_sha256'], result['business_code_length'], _ = hashed(code)
        except (TypeError, ValueError):
            pass
        if type(code) in (str, int) and re.fullmatch(r'-?\d{1,10}', str(code)) and -2147483648 <= int(code) <= 2147483647:
            result['business_code'] = code
    if 'msg' in payload:
        message = payload['msg']
        result['msg_type'] = 'null' if message is None else type(message).__name__
        result['msg_class'] = ('empty_text' if message == '' else 'nonempty_text_uninterpreted') if isinstance(message, str) else 'non_text'
        try:
            result['msg_sha256'], result['msg_length'], result['msg_size_bytes'] = hashed(message)
        except (TypeError, ValueError):
            pass
    return result


def row_hash(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def scoped_row(reader, kind, native_id, site_id):
    if kind not in ('coupon', 'discount'):
        raise ContractError('BENEFIT_KIND_UNKNOWN')
    native_id, site_id = positive_id(native_id), positive_id(site_id)
    row = reader.detail(kind, native_id)
    if str(row.get('site_id')) not in ('0', site_id):
        raise ContractError('BENEFIT_SCOPE_MISMATCH')
    return row


def object_policy(policy, kind, native_id, site_id, row):
    entry = policy.get('coupon_objects', {}).get(native_id, {}) if kind == 'coupon' else {}
    reasons = []
    if (not entry or str(entry.get('site_id')) != site_id
            or any(str(entry.get(key)) != str(row.get(key)) for key in ('site_id', 'game_id', 'goods_id'))):
        reasons.append('PROJECT_OBJECT_NOT_VERIFIED')
    if any(entry.get(proof) is not True for proof in REQUIRED_PROOFS + ('fs_bridge_acceptance_verified',)):
        reasons.append('NATIVE_WRITE_PROOFS_REQUIRED')
    if type(row.get('status')) not in (int, str) or row.get('status') not in (0, 1, '0', '1'):
        reasons.append('NATIVE_STATUS_UNKNOWN')
    return entry, reasons


def detail(reader, policy, kind, native_id, site_id):
    native_id, site_id = positive_id(native_id), positive_id(site_id)
    row = scoped_row(reader, kind, native_id, site_id)
    entry, reasons = object_policy(policy, kind, native_id, site_id, row)
    allowed = [] if reasons or entry.get('full_preserve_edit_verified') is not True or entry.get('fs_bridge_acceptance_verified') is not True else ['title', 'brief']
    fields = {}
    for key in (COUPON_FIELDS if kind == 'coupon' else DISCOUNT_FIELDS):
        if key not in row:
            continue
        value = row[key]
        if type(value) not in (str, int, list) or (isinstance(value, list) and any(type(v) not in (str, int) for v in value)):
            raise ContractError('BENEFIT_DETAIL_SCHEMA_UNKNOWN')
        fields[key] = value
    return dict(kind=kind, native_id=native_id, before_hash=row_hash(row),
        fields=fields,
        scope_status='global_read_only' if str(row.get('site_id')) == '0' else 'exact_site',
        editability=dict(allowed_changes=allowed, can_disable=not reasons and entry.get('disable_verified') is True and entry.get('full_preserve_toggle_verified') is True,
            can_enable=not reasons and entry.get('full_preserve_toggle_verified') is True and entry.get('enable_verified') is True and entry.get('activation_authorized') is True,
            blocked_reasons=sorted(set(reasons + ([] if allowed else ['FULL_PRESERVE_EDIT_NOT_VERIFIED'])))),
        verification=dict(detail_route='verified_readback_20261024',
                          write_semantics='frontend_contract_only_until_exact_object_proofs'))


# Exact observed native edit schema. Unknown extra/missing fields fail closed.
NATIVE_INTS = set('id create_time update_time type fetch_scene status mode_type limit_qty fetch_qty used_qty repeat_qty time_effect days site_id game_id product_type goods_id is_open'.split())
NATIVE_STRINGS = set('title brief attain reduce max_reduce remark jump_url param_code'.split())
NATIVE_TIMES = {'start_time', 'end_time'}
NATIVE_FIELDS = NATIVE_INTS | NATIVE_STRINGS | NATIVE_TIMES
RESTORE_FIXED = {'id', 'create_time', 'site_id', 'game_id', 'goods_id', 'product_type', 'type', 'fetch_qty', 'used_qty', 'title', 'brief'}


def native_valid(row, payload):
    return (isinstance(row, dict) and set(row) == NATIVE_FIELDS
        and all(type(row[key]) is int for key in NATIVE_INTS)
        and all(type(row[key]) is str for key in NATIVE_STRINGS)
        and all(type(row[key]) is str or (type(row[key]) is int and row[key] == 0) for key in NATIVE_TIMES)
        and row['id'] == int(payload['native_id']) and row['site_id'] == int(payload['site_id'])
        and all(str(row[key]) == value for key, value in payload['scope'].items()))


def successful_audit(audits, operation_id=None, payload_hash=None):
    # A matching-looking row after a timeout/non-success is not execution evidence.
    return (len(audits) == 1 and audits[0]['event'] == 'http_response'
        and audits[0]['http_status'] == 200 and audits[0]['parse_status'] == 'json_object'
        and type(audits[0]['business_code']) is int and audits[0]['business_code'] == 1
        and (operation_id is None or audits[0].get('operation_id') == operation_id)
        and (payload_hash is None or audits[0].get('request_payload_hash') == payload_hash))


def same_native(left, right, excluding=()):
    return canonical({k: v for k, v in left.items() if k not in excluding}) == canonical({k: v for k, v in right.items() if k not in excluding})


class CouponEdit:
    route = '/admin/market.Coupon/edit'

    def __init__(self, reader, payload, audit=None):
        self.reader, self.payload, self.enabled = reader, payload, True
        self.audit = audit
        self.save_state = self.get_state = self.get_audits = None

    def bind_native_response_audit(self, callback):
        self.audit = callback

    def bind_native_operation_state(self, save_state, get_state, get_audits):
        self.save_state, self.get_state, self.get_audits = save_state, get_state, get_audits

    def restore_source(self, payload, fresh=None):
        source = self.get_state(payload['restore_of'])
        if (not source or source['state'] != 'confirmed'
                or source['request'].get('action') != 'benefit_edit'
                or source['request'].get('kind') != 'coupon'
                or any(source['request'].get(k) != payload[k] for k in ('site_id', 'native_id', 'scope'))
                or not successful_audit(self.get_audits(payload['restore_of']), payload['restore_of'], row_hash(source['request']))):
            raise ContractError('RESTORE_SOURCE_NOT_CONFIRMED')
        if fresh is not None:
            expected = source['expected']
            if (not native_valid(fresh, payload) or fresh['fetch_qty'] != 0 or fresh['used_qty'] != 0
                    or not same_native(fresh, expected, NATIVE_FIELDS - RESTORE_FIXED)):
                raise ContractError('RESTORE_SOURCE_STATE_CHANGED')
        return {key: source['original'][key] for key in ('title', 'brief')}

    def readback(self, operation_id, payload):
        if self.get_state is None or self.get_audits is None:
            return dict(state='unknown', reason_code='NATIVE_EXECUTION_EVIDENCE_REQUIRED')
        snapshot = self.get_state(operation_id)
        if (not snapshot or not native_valid(snapshot['expected'], payload)
                or not successful_audit(self.get_audits(operation_id), operation_id, row_hash(payload))):
            return dict(state='unknown', reason_code='NATIVE_EXECUTION_EVIDENCE_REQUIRED')
        row = scoped_row(self.reader, 'coupon', payload['native_id'], payload['site_id'])
        if not native_valid(row, payload) or not same_native(row, snapshot['expected'], {'update_time'}):
            return dict(state='unknown', reason_code='NATIVE_STATE_NOT_CONFIRMED')
        return dict(state='confirmed', upstream_ref=payload['native_id'])

    def dispatch_once(self, operation_id, payload):
        row = scoped_row(self.reader, 'coupon', payload['native_id'], payload['site_id'])
        if row_hash(row) != payload['before_hash']:
            return dict(state='rejected', reason_code='BEFORE_HASH_CONFLICT', dispatch_state='not_started')
        if self.audit is None or self.save_state is None:
            raise ContractError('NATIVE_RESPONSE_AUDIT_REQUIRED')
        if not native_valid(row, payload):
            return dict(state='rejected', reason_code='FULL_NATIVE_SCHEMA_REQUIRED', dispatch_state='not_started')
        changes = payload['changes']
        if payload.get('action') == 'benefit_restore':
            try:
                if changes != self.restore_source(payload, row):
                    raise ContractError('RESTORE_SOURCE_STATE_CHANGED')
            except ContractError as error:
                return dict(state='rejected', reason_code=str(error), dispatch_state='not_started')
        elif payload.get('action') == 'benefit_toggle':
            if set(changes) != {'status'} or type(changes['status']) is not int or changes['status'] not in (0, 1):
                raise ContractError('CHANGE_FIELDS_NOT_ALLOWED')
        elif (not changes or set(changes) - {'title', 'brief'} or any(type(v) is not str for v in changes.values())):
            raise ContractError('CHANGE_FIELDS_NOT_ALLOWED')
        native = dict(row, **changes)
        if not native_valid(native, payload):
            raise ContractError('FULL_NATIVE_SCHEMA_REQUIRED')
        session = self.reader.session
        url = 'https://admin-api.p2pah.cn' + self.route
        try:
            retries = session.admin.get_adapter(url).max_retries
            retries_disabled = type(retries.total) is int and retries.total == 0
        except Exception:
            retries_disabled = False
        if not retries_disabled:
            return dict(state='rejected', reason_code='TRANSPORT_RETRY_NOT_DISABLED', dispatch_state='not_started')
        # Persist private original/expected material before dispatch. Response evidence commits before GET.
        self.save_state(operation_id, row, native)
        fresh = scoped_row(self.reader, 'coupon', payload['native_id'], payload['site_id'])
        if row_hash(fresh) != payload['before_hash']:
            return dict(state='rejected', reason_code='BEFORE_HASH_CONFLICT', dispatch_state='not_started')
        # This is a client read/CAS, not an atomic server conditional write.
        try:
            response = session.admin.post(url, json=native, headers={'batoken': session.token,
                'server': 'true', 'think-lang': 'zh-cn'}, timeout=30, allow_redirects=False)
        except Exception as error:
            self.audit(operation_id, safe_response_evidence(error=error))
            raise
        evidence = safe_response_evidence(response=response)
        self.audit(operation_id, evidence)
        if not successful_audit([evidence]):
            return dict(state='unknown', reason_code='NATIVE_RESPONSE_UNCONFIRMED')
        return self.readback(operation_id, payload)


def object_busy_result(ledger, requested_operation_id, error):
    original = [ledger.lookup(operation_id) for operation_id in error.operation_ids]
    active = [operation for operation in original if operation and operation['state'] in ('pending', 'unknown')]
    owner = (active or [operation for operation in original if operation])[0]
    return dict(owner, requested_operation_id=requested_operation_id, object_busy=True,
                recovery_operation_id=owner['operation_id'],
                recovery_operation_ids=[operation['operation_id'] for operation in active] or [owner['operation_id']],
                result=dict(reason_code='OBJECT_OPERATION_IN_PROGRESS'))


def mutate(reader, ledger, policy, request):
    operation_id = identity(request.get('operation_id'))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}', operation_id):
        raise ContractError('INVALID_OPERATION_ID')
    site_id, native_id = str(request.get('site_id')), str(request.get('native_id'))
    raw_changes = request.get('changes')
    restore_error = None
    restore_of = request.get('restore_of')
    restore_changes = {}
    if request.get('action') == 'benefit_restore':
        try:
            restore_of = identity(restore_of)
            source = ledger.native_state(restore_of)
            if not source:
                raise ContractError('RESTORE_SOURCE_NOT_CONFIRMED')
            restore_changes = {key: source['original'][key] for key in ('title', 'brief')}
        except ContractError as error:
            restore_error = str(error)
            restore_of = operation_id
    changes = ({'status': int(request['enabled'])} if request.get('action') == 'benefit_toggle'
        and type(request.get('enabled')) is bool else
        {key: value for key, value in raw_changes.items() if key in ('title', 'brief') and isinstance(value, str)}
        if isinstance(raw_changes, dict) else {})
    if request.get('action') == 'benefit_restore':
        changes = restore_changes
    entry = policy.get('coupon_objects', {}).get(native_id, {})
    payload = dict(action=request.get('action'), kind=request.get('kind'), site_id=site_id, native_id=native_id,
        before_hash=request.get('before_hash'), changes=changes,
        request_hash=row_hash({key: request.get(key) for key in ('action', 'site_id', 'kind', 'native_id', 'before_hash', 'changes', 'enabled', 'restore_of')}),
        scope={key: str(entry.get(key)) for key in ('site_id', 'game_id', 'goods_id')})
    if request.get('action') == 'benefit_restore':
        payload['restore_of'] = restore_of
    try:
        existing = ledger.lookup(operation_id)
        ledger.prepare(operation_id, payload)
    except ObjectOperationBusy as error:
        return object_busy_result(ledger, operation_id, error)
    except ContractError:
        original = ledger.lookup(operation_id)
        # A conflicting request cannot certify that another worker's original operation was not sent.
        return dict(operation_id=operation_id, state='unknown', dispatch_state='existing_operation',
                    result=dict(reason_code='REQUEST_CONFLICT')) if original else ledger.lookup(operation_id)
    if existing is not None:
        return existing
    try:
        positive_id(site_id)
        positive_id(native_id)
        if request.get('kind') != 'coupon':
            raise ContractError('COUPON_EDIT_ONLY')
        if request.get('action') not in ('benefit_edit', 'benefit_toggle', 'benefit_restore'):
            raise ContractError('ACTION_NOT_ALLOWED')
        view = detail(reader, policy, 'coupon', native_id, site_id)
        if request.get('before_hash') != view['before_hash']:
            raise ContractError('BEFORE_HASH_CONFLICT')
        allowed = view['editability']
        if request.get('action') == 'benefit_restore':
            if restore_error:
                raise ContractError(restore_error)
            if raw_changes is not None or 'enabled' in request:
                raise ContractError('CHANGE_FIELDS_NOT_ALLOWED')
            adapter = CouponEdit(reader, payload)
            ledger._bind_adapter(adapter)
            adapter.restore_source(payload, scoped_row(reader, 'coupon', native_id, site_id))
            permitted = set(changes).issubset(allowed['allowed_changes'])
        elif request.get('action') == 'benefit_toggle':
            if type(request.get('enabled')) is not bool:
                raise ContractError('EXPLICIT_ENABLED_REQUIRED')
            permitted = allowed['can_enable'] if request['enabled'] else allowed['can_disable']
        else:
            if not isinstance(raw_changes, dict) or not raw_changes or set(raw_changes) - {'title', 'brief'}:
                raise ContractError('CHANGE_FIELDS_NOT_ALLOWED')
            for key, value in raw_changes.items():
                if (not isinstance(value, str) or (key == 'title' and not value.strip())
                        or len(value) > (200 if key == 'title' else 2000) or '\x00' in value):
                    raise ContractError('INVALID_BENEFIT_TEXT')
            permitted = set(changes).issubset(allowed['allowed_changes'])
        if not permitted:
            raise ContractError('NATIVE_WRITE_PROOFS_REQUIRED')
    except ContractError as error:
        # Upstream failures are not a safe preflight certificate; an original worker may still be active.
        if str(error) == 'UPSTREAM_UNAVAILABLE':
            return dict(operation_id=operation_id, state='unknown', dispatch_state='unknown',
                        result=dict(reason_code='UPSTREAM_UNAVAILABLE'))
        return ledger.reject_unstarted(operation_id, payload, str(error))
    try:
        return ledger.execute(operation_id, payload, CouponEdit(reader, payload))
    except ObjectOperationBusy as error:
        return object_busy_result(ledger, operation_id, error)


def operation(ledger, reader, site_id, operation_id, reconcile=False):
    payload = ledger.request_payload(operation_id)
    if payload.get('site_id') != positive_id(site_id) or payload.get('kind') != 'coupon':
        raise ContractError('OPERATION_SCOPE_MISMATCH')
    current = ledger.lookup(operation_id)
    if reconcile and current['state'] == 'pending':
        # Fence the durable unclaimed operation atomically; an older preflight worker can no longer send.
        return ledger.reject_unstarted(operation_id, payload, 'PREFLIGHT_FENCED_BEFORE_DISPATCH')
    return ledger.reconcile(operation_id, CouponEdit(reader, payload)) if reconcile else current
