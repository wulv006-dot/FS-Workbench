"""Actual Admin order/log association, private durable snapshots and safe aggregate reads."""
import hashlib
import json
import sqlite3
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import asdict

from .attribution import AppliedBenefit, BenefitRef, Binding, attribute
from .catalog import positive_id
from .core import ContractError, Money, canonical, identity, timestamp


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def source_time(value, config):
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            offset = config.get('source_utc_offset_minutes')
            if type(offset) is not int or not -840 <= offset <= 840 or not config.get('time_verification_ref'):
                raise ValueError()
            result = result.replace(tzinfo=timezone(timedelta(minutes=offset)))
        return result.isoformat()
    except (ValueError, TypeError):
        raise ContractError('SOURCE_TIME_MAPPING_REQUIRED') from None


def binding(value):
    copied = dict(value)
    copied['ref'] = BenefitRef(**copied['ref'])
    return Binding(**copied)


def binding_key(value):
    return canonical([value['site_id'], value['activity_id'], value['binding_version'], value['ref']])


def paid_money(row, config):
    if config.get('money_verified') is not True or not config.get('money_verification_ref'):
        raise ContractError('PAID_MONEY_MAPPING_REQUIRED')
    parts, code = row.get('pay_money_format2'), row.get('currency_code')
    if not isinstance(parts, list) or len(parts) != 2 or parts[0] != code:
        raise ContractError('PAID_CURRENCY_CONFLICT')
    money = Money.parse(parts[1], code, config.get('currency_scales', {}))
    return dict(currency=money.currency, scale=money.scale, minor=money.minor)


class AnalysisStore:
    def __init__(self, path):
        # :memory: is explicitly useful for controller's private read-only source acceptance.
        self.db = sqlite3.connect(str(path), timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS facts(site TEXT, order_key TEXT, paid_at TEXT, body TEXT,
                PRIMARY KEY(site,order_key));
            CREATE TABLE IF NOT EXISTS fact_history(site TEXT, order_key TEXT, body_hash TEXT, body TEXT,
                observed_at TEXT, PRIMARY KEY(site,order_key,body_hash));
            CREATE TABLE IF NOT EXISTS bindings(binding_key TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS captures(id INTEGER PRIMARY KEY, site TEXT, window_from TEXT,
                window_to TEXT, body_hash TEXT, coverage TEXT, verified_at TEXT);
            CREATE TABLE IF NOT EXISTS watermarks(site TEXT PRIMARY KEY, through_time TEXT);
            CREATE TABLE IF NOT EXISTS site_versions(site TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS failures(id INTEGER PRIMARY KEY, site TEXT, reason TEXT, occurred_at TEXT);
        ''')

    def close(self):
        self.db.close()

    def bindings(self, additions):
        existing = {row['binding_key']: json.loads(row['body']) for row in self.db.execute('SELECT * FROM bindings')}
        normalized = [asdict(binding(value)) for value in additions]
        def versions(values):
            groups = {}
            for value in values:
                key = canonical([value['site_id'], value['activity_id'], value['binding_version']])
                groups.setdefault(key, set()).add(canonical(value))
            return groups
        previous, incoming = versions(existing.values()), versions(normalized)
        if any(key in previous and previous[key] != values for key, values in incoming.items()):
            raise ContractError('IMMUTABLE_BINDING_VERSION_CONFLICT')
        for value in normalized:
            key = binding_key(value)
            if key in existing and existing[key] != value:
                raise ContractError('IMMUTABLE_BINDING_VERSION_CONFLICT')
            existing[key] = value
        # Reuse the financial core's ambiguity validation, without inventing any order facts.
        attribute([], [binding(value) for value in existing.values()])
        return list(existing.values())

    def watermark(self, site_id):
        row = self.db.execute('SELECT through_time FROM watermarks WHERE site=?', (site_id,)).fetchone()
        return row[0] if row else None

    def revision(self, site_id):
        row = self.db.execute('SELECT revision FROM site_versions WHERE site=?', (site_id,)).fetchone()
        return row[0] if row else 0

    def failure(self, site_id, reason):
        with self.db:
            self.db.execute('INSERT INTO failures(site,reason,occurred_at) VALUES (?,?,?)', (site_id, reason, utc_now()))

    def save(self, site_id, start, end, facts, bindings, coverage, expected_revision):
        stamp = utc_now()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.revision(site_id) != expected_revision:
                raise ContractError('STALE_ANALYSIS_CAPTURE')
            # Recheck immutable registry under the write lock, not just before upstream reads.
            self.bindings(bindings)
            for value in bindings:
                self.db.execute('INSERT OR IGNORE INTO bindings VALUES (?,?)', (binding_key(value), canonical(value)))
            self.db.execute('DELETE FROM facts WHERE site=? AND paid_at>=? AND paid_at<=?', (site_id, start, end))
            for fact in facts:
                body = canonical(fact)
                self.db.execute('INSERT OR REPLACE INTO facts VALUES (?,?,?,?)',
                    (site_id, fact['order_key'], fact['raw_paid_at'], body))
                self.db.execute('INSERT OR IGNORE INTO fact_history VALUES (?,?,?,?,?)',
                    (site_id, fact['order_key'], digest(fact), body, stamp))
            self.db.execute('INSERT INTO captures(site,window_from,window_to,body_hash,coverage,verified_at) VALUES (?,?,?,?,?,?)',
                (site_id, start, end, digest(facts), canonical(coverage), stamp))
            previous = self.watermark(site_id)
            self.db.execute('INSERT OR REPLACE INTO watermarks VALUES (?,?)', (site_id, max(previous or end, end)))
            self.db.execute('INSERT OR REPLACE INTO site_versions VALUES (?,?)', (site_id, expected_revision + 1))
            self.summary(site_id)  # Reject inconsistent aggregates before committing over a successful snapshot.

    def summary(self, site_id, activity_id=None):
        site_id = positive_id(site_id)
        rows = [json.loads(row['body']) for row in self.db.execute('SELECT body FROM facts WHERE site=?', (site_id,))]
        captures = list(self.db.execute('SELECT * FROM captures WHERE site=? ORDER BY id', (site_id,)))
        registry = [binding(json.loads(row['body'])) for row in self.db.execute('SELECT body FROM bindings')
                    if json.loads(row['body'])['site_id'] == site_id]
        coverage = dict(source_orders=len(rows), paid_observations=sum(row['payment_state'] == 'paid' for row in rows),
            refunded_observations=(sum(row['payment_state'] == 'refunded' for row in rows)
                if rows and all(row.get('refund_state_verified') for row in rows) else None),
            coupon_log_rows=sum(row['coupon_log_rows'] for row in rows),
            associated_paid_observations=sum(row['payment_state'] == 'paid' and row['coupon_paid_observed'] for row in rows),
            bound_paid_orders=0, unbound_paid_orders=0, unresolved_orders=0,
            successful_runs=len(captures), window_from=captures[-1]['window_from'] if captures else None,
            window_to=captures[-1]['window_to'] if captures else None, latest_window_end=self.watermark(site_id),
            history_complete=False)
        warnings, global_buckets, activity_buckets = set(), {}, {}
        scales = {}
        if not captures:
            warnings.add('ORDER_READ_NOT_PERFORMED')
        last_failure = self.db.execute('SELECT * FROM failures WHERE site=? ORDER BY id DESC LIMIT 1', (site_id,)).fetchone()
        if last_failure and (not captures or last_failure['occurred_at'] > captures[-1]['verified_at']):
            warnings.add('LAST_RECONCILIATION_FAILED')
        for fact in rows:
            warnings.update(fact['warnings'])
            coverage['unresolved_orders'] += int(bool(fact['warnings']))
            if fact['payment_state'] != 'paid':
                continue
            matched = {}
            for raw_use in fact['uses']:
                use = AppliedBenefit(BenefitRef(**raw_use['ref']), raw_use['applied_at'])
                for item in registry:
                    if item.matches(site_id, use):
                        matched.setdefault(item.activity_id, item)
            if not matched:
                coverage['unbound_paid_orders'] += 1
                continue
            coverage['bound_paid_orders'] += 1
            money = fact['paid']
            if money is None:
                warnings.add('PAID_MONEY_MAPPING_REQUIRED')
            context = money or dict(currency=fact.get('observed_currency'), scale=fact.get('observed_scale'), minor=None)
            if context['scale'] is not None and context['currency'] in scales and scales[context['currency']] != context['scale']:
                raise ContractError('CURRENCY_OR_SCALE_CONFLICT')
            if context['scale'] is not None:
                scales[context['currency']] = context['scale']
            def add(container, key, activity=None):
                item = container.setdefault(key, dict(currency=context['currency'], scale=context['scale'],
                    paid_orders=0, associated_paid_minor=0, activity_paid_minor=None,
                    refund_minor=None, net_minor=None, **({'activity_id': activity} if activity else {})))
                item['paid_orders'] += 1
                if item['associated_paid_minor'] is not None and context['minor'] is not None:
                    item['associated_paid_minor'] += context['minor']
                else:
                    item['associated_paid_minor'] = None
            selected = matched if activity_id is None else {key: item for key, item in matched.items() if key == activity_id}
            if selected:
                add(global_buckets, (context['currency'], context['scale']))
            for activity in selected:
                add(activity_buckets, (activity, context['currency'], context['scale']), activity)
        if not registry:
            warnings.add('ACTIVITY_BINDINGS_REQUIRED')
        if global_buckets:
            warnings.update(('LINE_ALLOCATION_NOT_VERIFIED', 'REFUND_EVENTS_NOT_VERIFIED'))
        status = 'blocked' if not captures or not registry else ('partial' if warnings else 'ready')
        return dict(status=status, coverage=coverage, totals=list(global_buckets.values()),
            activities=list(activity_buckets.values()), warnings=sorted(warnings),
            verified_at=captures[-1]['verified_at'] if captures else None,
            scope=dict(site_id=site_id, activity_id=activity_id, basis='actual_applied_native_benefit_and_paid_status'),
            historical_refund_coverage='explicit_rescans_required_no_update_cursor_verified',
            scanned_windows=[dict(window_from=row['window_from'], window_to=row['window_to']) for row in captures],
            rescan_policy=dict(basis='explicit_paytime_windows', late_payment_requires_rescan=True,
                               historical_refunds_require_rescan=True, automatic_update_cursor_verified=False))


def _reconcile(reader, store, site_id, start, end, config=None):
    """Reads all actual rows into local memory; stores only whitelisted hashed-identity facts."""
    config = config or {}
    site_id = positive_id(site_id)
    revision = store.revision(site_id)
    try:
        begin, stop = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if begin.utcoffset() is not None or stop.utcoffset() is not None or not 0 <= (stop - begin).total_seconds() <= 28 * 86400:
            raise ValueError()
        # Require sortable source wall time, never compare arbitrary timestamp formats lexically.
        if any(value != datetime.fromisoformat(value).strftime('%Y-%m-%d %H:%M:%S') for value in (start, end)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ContractError('MAX_28_DAY_SOURCE_WINDOW_REQUIRED') from None
    bindings = store.bindings(config.get('bindings', []))
    orders = reader.orders(site_id, start, end)
    by_number = {}
    for row in orders:
        number = identity(row.get('order_no'))
        if (str(row.get('site_id')) != site_id or not start <= str(row.get('paytime')) <= end):
            raise ContractError('UPSTREAM_SCOPE_MISMATCH')
        if number in by_number:
            raise ContractError('DUPLICATE_ORDER_NUMBER')
        by_number[number] = row
    logs = reader.coupon_logs(site_id, list(by_number))
    grouped, seen = {}, {}
    for log in logs:
        number, log_id = identity(log.get('order_no')), positive_id(log.get('id'))
        if str(log.get('site_id')) != site_id or number not in by_number:
            raise ContractError('COUPON_ORDER_SCOPE_MISMATCH')
        selected = {key: log.get(key) for key in ('coupon_id', 'status', 'use_time', 'memberCoupon')}
        if log_id in seen and seen[log_id] != selected:
            raise ContractError('CONFLICTING_COUPON_LOG')
        if log_id not in seen:
            grouped.setdefault(number, []).append(log)
        seen[log_id] = selected
    # Check the full applicable catalog: an unbound native ID with the same folded code is also ambiguous.
    discount_codes = {}
    bound_discount_ids = {item.ref.native_id for item in (binding(value) for value in bindings)
                          if item.site_id == site_id and item.ref.kind == 'discount'}
    if bound_discount_ids:
        natives = reader.pages('discounts', [('site_id', 'IN', '0,' + site_id)],
            validate=lambda row: str(row.get('site_id')) in ('0', site_id))
        found = set()
        for native in natives:
            if (str(native.get('site_id')) not in ('0', site_id) or not isinstance(native.get('code'), str)
                    or not native['code'].strip()):
                raise ContractError('DISCOUNT_SCOPE_MISMATCH')
            native_id = positive_id(native.get('id'))
            found.add(native_id)
            discount_codes.setdefault(native['code'].strip().casefold(), set()).add(native_id)
        if not bound_discount_ids.issubset(found):
            raise ContractError('BOUND_DISCOUNT_NOT_FOUND')
    facts = []
    for number, row in sorted(by_number.items()):
        raw_state = row.get('pay_status')
        refund_verified = config.get('refund_state_verified') is True and bool(config.get('refund_state_verification_ref'))
        refunded = refund_verified and any(type(value) is type(raw_state) and value == raw_state
                                           for value in config.get('refunded_payment_states', []))
        state = 'paid' if type(raw_state) in (int, str) and raw_state in (1, '1') else ('refunded' if refunded else 'unknown')
        issues, uses = set(), []
        if state == 'unknown':
            issues.add('PAYMENT_STATE_UNKNOWN')
        paid = None
        try:
            paid = paid_money(row, config)
        except ContractError as error:
            issues.add(str(error))
        order_logs = grouped.get(number, [])
        paid_logs = []
        for log in order_logs:
            raw_status = log.get('status')
            if type(raw_status) not in (int, str) or raw_status not in (0, 1, '0', '1'):
                issues.add('COUPON_LOG_STATUS_UNKNOWN')
                continue
            if raw_status not in (1, '1'):
                continue
            paid_logs.append(log)
            try:
                native_id = positive_id(log.get('coupon_id'))
                batch = log.get('memberCoupon')
                batch_id = batch.get('grant_batch_no') if isinstance(batch, dict) else None
                if batch_id == '':
                    batch_id = None
                use = AppliedBenefit(BenefitRef('coupon', native_id, batch_id), source_time(log.get('use_time'), config))
                uses.append(dict(ref=dict(kind='coupon', native_id=native_id, batch_id=batch_id), applied_at=use.applied_at))
            except ContractError as error:
                issues.add(str(error))
        code = row.get('discount_code')
        if code:
            if not isinstance(code, str):
                raise ContractError('DISCOUNT_CODE_SCHEMA_UNKNOWN')
            matches = discount_codes.get(code.strip().casefold(), set())
            if len(matches) == 1:
                try:
                    time_field = config.get('discount_applied_at_field')
                    if not time_field or not config.get('discount_time_verification_ref'):
                        raise ContractError('DISCOUNT_APPLICATION_TIME_REQUIRED')
                    applied = source_time(row.get(time_field), config)
                    uses.append(dict(ref=dict(kind='discount', native_id=next(iter(matches)), batch_id=None), applied_at=applied))
                except ContractError as error:
                    issues.add(str(error))
            elif len(matches) > 1:
                issues.add('AMBIGUOUS_DISCOUNT_NATIVE_ID')
        code = row.get('currency_code')
        observed_currency = code if isinstance(code, str) and re.fullmatch('[A-Z]{3}', code) else None
        scale = config.get('currency_scales', {}).get(observed_currency)
        observed_scale = scale if type(scale) is int and 0 <= scale <= 6 else None
        facts.append(dict(order_key=digest([site_id, number]), raw_paid_at=row['paytime'],
            payment_state=state, paid=paid, coupon_log_rows=len(order_logs), coupon_paid_observed=bool(paid_logs),
            refund_state_verified=refund_verified, observed_currency=observed_currency,
            observed_scale=observed_scale, uses=uses, warnings=sorted(issues)))
    coverage = dict(source_orders=len(orders), coupon_log_rows=len(seen), associated_orders=len(grouped))
    store.save(site_id, start, end, facts, bindings, coverage, revision)
    summary = store.summary(site_id)
    summary['capture_sha256'] = digest(facts)
    return summary


def reconcile(reader, store, site_id, start, end, config=None):
    try:
        return _reconcile(reader, store, site_id, start, end, config)
    except Exception as error:
        try:
            store.failure(positive_id(site_id), str(error) if isinstance(error, ContractError) else 'RECONCILIATION_FAILED')
        except (ContractError, sqlite3.Error):
            pass
        raise
