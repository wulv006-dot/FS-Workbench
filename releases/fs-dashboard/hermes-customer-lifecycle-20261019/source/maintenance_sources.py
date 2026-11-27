"""Read-only adapters for the user analysis publication and existing Admin proxy."""
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import cached_property
from itertools import chain
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

from customer_segments import tier
from maintenance_ledger import marks
from maintenance_review import coupon_time, email_key, member_id
from maintenance_stages import GID, SHANGHAI, cohort, day_end, day_start, payment


DB_PATH = Path('/var/lib/fs-user-analytics/customers.sqlite3')
HISTORY = date(2026, 1, 1)
SITE = '266'
ROW_BATCH = 128


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class AdminFacts:
    """Only the three read routes used by maintenance. All response pages are checked."""
    ROUTES = {
        'grants': '/admin/user.MemberCoupon/index',
        'usage': '/admin/user.MemberCouponLog/index',
        'orders': '/admin/order.Order/index',
    }

    def __init__(self, read=None):
        self.read = read or self._read

    @staticmethod
    def _read(path, query):
        opener = build_opener(NoRedirect())
        url = 'http://127.0.0.1:8911' + path + '?' + urlencode(query)
        with opener.open(url, timeout=25) as response:
            body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError('maintenance_admin_response_budget')
        value = json.loads(body)
        if not isinstance(value, dict) or value.get('code') != 1 or not isinstance(value.get('data'), dict):
            raise ValueError('maintenance_admin_read_failed')
        return value['data']

    def pages(self, kind, filters):
        params = {'limit': 100, 'order': 'id,desc'}
        for index, (field, op, value, *render) in enumerate(filters):
            if render:
                params[f'search[{index}][render]'] = render[0]
            for name, item in (('field', field), ('operator', op), ('val', value)):
                params[f'search[{index}][{name}]'] = item
        previous_total, found = None, {}
        for page in range(1, 201):
            payload = self.read(self.ROUTES[kind], dict(params, page=page))
            if not isinstance(payload, dict):
                raise ValueError('maintenance_admin_read_failed')
            rows, total = payload.get('list'), payload.get('total')
            if isinstance(total, str) and total.isascii() and total.isdecimal():
                total = int(total)
            if (type(total) is not int or not 0 <= total <= 20000 or not isinstance(rows, list)
                    or len(rows) > params['limit'] or previous_total not in (None, total)):
                raise ValueError('maintenance_admin_pagination')
            previous_total = total
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('maintenance_admin_read_failed')
                ident = member_id(row.get('id'))
                if not ident or ident in found:
                    raise ValueError('maintenance_admin_duplicate')
                found[ident] = row
            if len(found) == total:
                return list(found.values())
            if not rows or len(found) > total:
                break
        raise ValueError('maintenance_admin_incomplete')

    def grants(self, uid):
        return self.pages('grants', [('member_id', '=', uid)])

    def recent_grant_members(self, at):
        """Reuse the grant source for the entire shortlist in bounded date pages."""
        members = set()
        cutoff = at - timedelta(days=30)
        start = cutoff
        while start < at:
            end = min(at, start + timedelta(days=7))
            bound = ','.join(point.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
                             for point in (start, end))
            for row in self.pages('grants', [('site_id', '=', SITE), ('start_time', 'RANGE', bound, 'datetime')]):
                uid = member_id(row.get('member_id'))
                issued = coupon_time(row.get('start_time'))
                if str(row.get('site_id')) != SITE or not uid or not start.replace(microsecond=0) <= issued <= end:
                    raise ValueError('maintenance_grant_scope')
                if cutoff < issued <= at and not str(row.get('grant_batch_no') or '').startswith('FCSM_'):
                    members.add(uid)
            start = end
        return members

    def logs(self, start, stop):
        source_time = lambda at: at.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
        bound = source_time(start) + ',' + source_time(stop)
        rows = self.pages('usage', [('site_id', '=', SITE), ('use_time', 'RANGE', bound)])
        if any(str(row.get('site_id')) != SITE for row in rows):
            raise ValueError('maintenance_coupon_log_site')
        return [row for row in rows if start < coupon_time(row.get('use_time')) <= stop]

    def exceptions(self, orders):
        """Refresh actual refund and issue evidence from the exact local order numbers."""
        from vip_followup import project_order
        by_day = {}
        for row in orders:
            if row.get('test_order'):
                continue
            number = row.get('order_no')
            if not number or ',' in number:
                raise ValueError('maintenance_admin_order_number')
            paid = payment(row)
            by_day.setdefault(paid.date(), {})[number] = row
        findings = []
        for day, wanted in sorted(by_day.items()):
            window = f'{day} 00:00:00,{day} 23:59:59'
            numbers = sorted(wanted)
            for offset in range(0, len(numbers), 50):
                batch = numbers[offset:offset + 50]
                rows = self.pages('orders', [('site_id', '=', SITE), ('order_no', 'IN', ','.join(batch)),
                                             ('paytime', 'RANGE', window, 'datetime')])
                if ({row.get('order_no') for row in rows} != set(batch) or len(rows) != len(batch)
                        or any(str(row.get('site_id')) != SITE for row in rows)):
                    raise ValueError('maintenance_admin_order_scope')
                for row in rows:
                    view = project_order(row)
                    if coupon_time(view['paidAtShanghai']).astimezone(SHANGHAI).date() != day:
                        raise ValueError('maintenance_admin_order_scope')
                    if view['afterSales'] == 'unknown' or view['refundStatus'] == 'unknown':
                        raise ValueError('maintenance_admin_order_state_unknown')
                    reason = order_exception(view)
                    if reason:
                        local = wanted[row['order_no']]
                        findings.append(dict(order_key=local['order_key'], paid_at=local['paid_at'],
                                             reason=reason,
                                             after_sales=view['afterSales'], refund=view['refundStatus'],
                                             refund_amount=view['sourceRefundAmount'], pay_status=view['payStatus'],
                                             order_state=view['orderState']))
        return findings


def order_exception(view):
    from vip_followup import preferred_disposition
    # Completed refunds are ordinary exceptions. A severe disposition still wins.
    if preferred_disposition(dict(view, observedRefund=False)) == 'problem':
        return 'problem'
    refund_amount = view['sourceRefundAmount']
    if view['observedRefund'] or view['afterSales'] == 'after_sales' or (
            refund_amount is not None and Decimal(refund_amount) > 0):
        return 'after_sales'
    return None


def locally_flagged_order(row):
    if not row['valid']:
        return True
    if not row.get('status_format') and not row.get('source_refund_amount'):
        return False
    from vip_followup import project_order
    view = project_order(dict(row, id=None, paytime=row['paid_at']))
    return bool(order_exception(view))


class Coverage:
    def __init__(self, publication, jobs, token):
        self.publication = publication
        self.cutoff = coupon_time(publication['cutoff'])
        self.day = self.cutoff.date() - timedelta(days=1)
        self.token = token
        self.intervals = sorted((coupon_time(job['start']), coupon_time(job['end']))
                                for job in jobs if job['site'] == SITE and job['state'] == 'complete')

    def covered(self, start, end):
        if end > self.cutoff:
            return False
        if start >= end:
            return True
        for left, right in self.intervals:
            if left > start:
                break
            start = max(start, right)
            if start >= end:
                return True
        return False


class Facts(Coverage):
    def __init__(self, publication, orders, jobs, token, uid_pairs=(), identities=None):
        super().__init__(publication, jobs, token)
        self.orders = orders
        self.customers = defaultdict(list)
        self.by_order = {}
        self.uid_customers = defaultdict(set)
        self.email_customers = defaultdict(set)
        for customer, address in (identities or {}).items():
            key = email_key(address)
            if key:
                self.email_customers[key].add(customer)
        for row in orders:
            self.by_order[row['order_key']] = row
            customer = row.get('customer_id')
            if customer:
                self.customers[customer].append(row)
                key = email_key(row.get('email'))
                if key:
                    self.email_customers[key].add(customer)
                uid = member_id(row.get('uid'))
                if uid:
                    self.uid_customers[uid].add(customer)
        for pair in uid_pairs:
            uid = member_id(pair[1])
            if uid:
                self.uid_customers[uid].add(pair[0])

    def find_order(self, key):
        return self.by_order.get(key)

    def customer_orders(self, customer):
        return self.customers.get(customer, ())

    def stage_cohort(self, day, config):
        return cohort(self.orders, day, config, self.covered)

    def customer_groups(self):
        return self.customers.items()

    def effect_orders(self, customers, numbers):
        return (row for row in self.orders if row.get('customer_id') in customers or row.get('order_no') in numbers)

    def email_conflict(self, customer, address):
        return bool(self.email_customers.get(email_key(address), set()) - {customer})


def batches(values):
    values = sorted(values)
    for offset in range(0, len(values), ROW_BATCH):
        yield values[offset:offset + ROW_BATCH]


def checked_order_number(row, body):
    number = body.get('order_no')
    if not isinstance(number, str) or row['order_key'] != 'admin:' + SITE + ':' + number:
        raise ValueError('maintenance_projection_order_identity')
    return number


class ProjectionFacts(Coverage):
    # Keep the receipt and version pin, and reopen a read snapshot for each
    # bounded read. A changed projection forces the caller to retry with a fresh pin.
    def __init__(self, source, publication, token, lower, target, indexed):
        super().__init__(publication, publication['jobs'], token)
        self.source = source
        self.lower = lower
        self.target = target
        self.current = int(token[1])
        self.indexed = indexed
        self._identities = None
        self._uid_owners = None

    @contextmanager
    def snapshot(self):
        with self.source.db() as db:
            if self.source._token(db) != self.token:
                raise LookupError('maintenance_projection_changed')
            yield db

    def _rows(self, db, *, end=None, customers=None, keys=None, fc=False, valid=False,
              columns=None, history_only=False):
        from user_version_index import COLUMNS
        upper = min(end, self.cutoff).isoformat() if end else self.cutoff.isoformat()
        lower = self.lower.isoformat()
        filters = ['site=?', 'paid_at>=?', 'paid_at<?']
        args = [SITE, lower, upper]
        for field, values in (('customer_id', customers), ('order_key', keys)):
            if values is not None:
                filters.append(f'{field} IN ({marks(values)})')
                args.extend(values)
        if valid:
            filters.append('valid=1')
        if fc:
            filters.append('gid=?')
            args.append(GID)
        suffix = ' AND ' + ' AND '.join(filters)
        fields = columns or COLUMNS

        if self.target < self.current and not self.indexed:
            needed = self.current - self.target
            if needed > 40:
                raise LookupError('maintenance_projection_waiting_for_revisions')
            count = db.execute('SELECT count(*) FROM revisions WHERE id>? AND id<=?',
                               (self.target, self.current)).fetchone()[0]
            if count != needed:
                raise LookupError('maintenance_projection_incomplete')

        if not history_only:
            yield from db.execute(f'SELECT {fields} FROM orders WHERE revision<=?' + suffix, (self.target, *args))
        if self.target == self.current:
            return
        if self.indexed:
            yield from db.execute(f'SELECT {fields} FROM user_order_versions WHERE revision<=? AND superseded>?' +
                                  suffix, (self.target, self.target, *args))
            return

        # The earliest superseding revision contains the version at the pin.
        # Record its key before applying any date, status or customer filters.
        restored = set()
        for (body,) in db.execute('SELECT body FROM revisions WHERE id>? AND id<=? ORDER BY id',
                                  (self.target, self.current)):
            for row in revision_orders(body):
                key = row['order_key']
                if key in restored or row['site'] != SITE or row['revision'] > self.target:
                    continue
                if keys is not None and key not in keys:
                    continue
                restored.add(key)
                if (lower <= row['paid_at'] < upper and (not fc or str(row['gid']) == GID)
                        and (not valid or row['valid'] == 1)
                        and (customers is None or row['customer_id'] in customers)):
                    yield row

    def _load_emails(self, db):
        if self._identities is not None:
            return self._identities
        emails, customers, conflicts = {}, {}, set()
        query = '''SELECT i.customer_id,i.email FROM identities i
                   WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id=i.customer_id AND o.site=?)'''
        for ident, address in db.execute(query, (SITE,)):
            if ident in emails and emails[ident] != address:
                raise ValueError('maintenance_projection_email_conflict')
            emails[ident] = address
            key = email_key(address)
            if key:
                if customers.setdefault(key, ident) != ident:
                    conflicts.add(key)
        self._identities = (emails, customers, conflicts)
        return self._identities

    def email_conflict(self, customer, address):
        key = email_key(address)
        if not key:
            return False
        identities = self._identities
        if identities is None:
            with self.snapshot() as db:
                identities = self._load_emails(db)
        _, customers, conflicts = identities
        return key in conflicts or customers.get(key, customer) != customer

    @cached_property
    def order_flags(self):
        try:
            return self.source._flags(self.publication, self.lower)
        except (OSError, LookupError, ValueError):
            return {}

    def _details(self, db, *, flags, **filters):
        emails, _, _ = self._load_emails(db)
        for row in self._rows(db, **filters):
            body = json.loads(row['body'])
            number = checked_order_number(row, body)
            order = dict(row)
            del order['body']
            order.update(order_no=number, uid=body.get('uid'), email=emails.get(row['customer_id']),
                         amount_usd=body.get('amount_usd'), pay_status=body.get('pay_status'),
                         test_order=bool(body.get('test_order')),
                         status_format=body.get('status_format'),
                         source_refund_amount=body.get('source_refund_amount'),
                         new_customer_flag=flags.get(hashlib.sha256(number.encode()).hexdigest()))
            yield order

    def find_order(self, key):
        with self.snapshot() as db:
            row = next(self._rows(db, keys=(key,), columns='order_key,customer_id,gid,valid,body'), None)
            if row is None:
                return None
            checked_order_number(row, json.loads(row['body']))
            return {column: row[column] for column in ('order_key', 'customer_id', 'gid', 'valid')}

    def customer_orders(self, customer):
        flags = self.order_flags
        with self.snapshot() as db:
            return list(self._details(db, customers=(customer,), flags=flags))

    def stage_cohort(self, day, config):
        end = day_end(day)
        totals = defaultdict(Decimal)
        with self.snapshot() as db:
            for row in self._rows(db, end=end, fc=True, valid=True,
                                  columns='order_key,customer_id,paid_at,body'):
                customer = row['customer_id']
                if not customer or payment(row) >= end:
                    continue
                body = json.loads(row['body'])
                checked_order_number(row, body)
                amount = body.get('amount_usd')
                totals[customer] += Decimal(str(amount)) if amount is not None else 0
        candidates = [customer for customer, total in totals.items() if tier(total, GID, config) is not None]
        result = {}
        if candidates:
            # Reading pinned ES files can take time. Keep it outside the SQLite snapshot.
            flags = self.order_flags
            with self.snapshot() as db:
                for batch in batches(candidates):
                    # Customer type uses the earliest valid main-site payment
                    # across games. Other non-FC orders need no body or flags.
                    first = {}
                    for row in self._rows(db, end=end, customers=batch, valid=True,
                                          columns='customer_id,order_key,paid_at,gid'):
                        paid = payment(row)
                        customer = row['customer_id']
                        rank = (paid, row['order_key'])
                        if paid < end and (customer not in first or rank < first[customer][0]):
                            first[customer] = (rank, row['gid'])
                    non_fc = [key for (_, key), gid in first.values() if str(gid) != GID]
                    fc_orders = self._details(db, end=end, customers=batch, fc=True, valid=True, flags=flags)
                    first_orders = self._details(db, end=end, keys=non_fc, valid=True,
                                                 flags=flags) if non_fc else ()
                    result.update(cohort(chain(fc_orders, first_orders), day, config, self.covered))
        return result

    def customer_groups(self):
        with self.snapshot() as db:
            customers = {row['customer_id'] for row in self._rows(db, fc=True, valid=True, columns='customer_id')
                         if row['customer_id']}
        for batch in batches(customers):
            flags = self.order_flags
            grouped = defaultdict(list)
            with self.snapshot() as db:
                for row in self._details(db, customers=batch, valid=True, flags=flags):
                    grouped[row['customer_id']].append(row)
            yield from grouped.items()

    def effect_orders(self, customers, numbers):
        with self.snapshot() as db:
            for batch in batches(customers):
                yield from self._details(db, customers=batch, flags={})
            for batch in batches({'admin:' + SITE + ':' + number for number in numbers}):
                for row in self._details(db, keys=batch, flags={}):
                    if row['customer_id'] not in customers:
                        yield row

    @property
    def uid_customers(self):
        if self._uid_owners is None:
            owners = defaultdict(set)
            with self.snapshot() as db:
                current = db.execute('SELECT customer_id,body FROM orders WHERE customer_id IS NOT NULL')
                for row in current:
                    uid = member_id(json.loads(row['body']).get('uid'))
                    if uid:
                        owners[uid].add(row['customer_id'])
                for row in self._rows(db, history_only=True, columns='customer_id,body'):
                    uid = member_id(json.loads(row['body']).get('uid'))
                    if uid and row['customer_id']:
                        owners[uid].add(row['customer_id'])
            self._uid_owners = owners
        return self._uid_owners


def revision_orders(body):
    # Revisions are canonical JSON arrays. Decode one prior row at a time.
    decoder = json.JSONDecoder()
    offset = 0

    def skip_space():
        nonlocal offset
        while offset < len(body) and body[offset] in ' \\t\\r\\n':
            offset += 1

    skip_space()
    if not body.startswith('[', offset):
        raise ValueError('maintenance_projection_revision_body')
    offset += 1
    skip_space()
    if body[offset:offset + 1] != ']':
        while True:
            row, offset = decoder.raw_decode(body, offset)
            yield row
            skip_space()
            if body[offset:offset + 1] == ']':
                break
            if body[offset:offset + 1] != ',':
                raise ValueError('maintenance_projection_revision_body')
            offset += 1
            skip_space()
    if body[offset + 1:].strip():
        raise ValueError('maintenance_projection_revision_body')


class UserProjection:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.flag_pin = None
        self.flags = {}

    @contextmanager
    def db(self):
        from user_store import safe
        safe(self.path)
        if not self.path.is_file():
            raise LookupError('maintenance_user_store_unavailable')
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            yield db

    @staticmethod
    def receipt(db):
        from user_weekly import META, checked
        row = db.execute('SELECT value FROM meta WHERE key=?', (META,)).fetchone()
        if not row:
            raise LookupError('maintenance_waiting_for_publication')
        if len(row[0].encode()) > 4 * 1024 * 1024:
            raise ValueError('maintenance_publication_budget')
        return checked(json.loads(row[0]))

    def _token(self, db):
        receipt = self.receipt(db)
        revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
        return receipt['publication_id'], revision

    def token(self):
        with self.db() as db:
            return self._token(db)

    def coupon_orders(self, numbers, token):
        """Resolve usage-log orders against the current private projection, outside the daily window."""
        keys = {'admin:' + SITE + ':' + number: number for number in numbers}
        if not keys:
            return []
        order_keys = list(keys)
        with self.db() as db:
            if self._token(db) != token:
                raise LookupError('maintenance_coupon_projection_changed')
            owners = []
            for offset in range(0, len(order_keys), 500):
                batch = order_keys[offset:offset + 500]
                placeholders = ','.join('?' for _ in batch)
                rows = db.execute('SELECT order_key,customer_id FROM orders WHERE site=? '
                                  f'AND order_key IN ({placeholders})', (SITE, *batch))
                owners.extend(dict(order_no=keys[row['order_key']], customer_id=row['customer_id'])
                              for row in rows)
        return owners

    def _flags(self, publication, start):
        from user_customer_types import read_pinned_flags
        pin = publication['publication_id']
        if pin != self.flag_pin:
            flags = {}
            cutoff = coupon_time(publication['cutoff'])
            cursor = start
            while cursor < cutoff:
                next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
                end = min(next_month, cutoff)
                labels, _ = read_pinned_flags(dict(start=cursor.isoformat(), end_exclusive=end.isoformat()),
                                              publication['flag_manifests'])
                for key, label in labels.items():
                    flags[key] = label if key not in flags or flags[key] == label else 'conflict'
                cursor = end
            self.flag_pin, self.flags = pin, flags
        return self.flags

    def read(self, now, *, latest=False):
        from user_version_index import ready
        with self.db() as db:
            publication = self.receipt(db)
            cutoff = coupon_time(publication['cutoff'])
            if cutoff > now:
                raise ValueError('maintenance_publication_future')
            current = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            revision = int(current)
            history = publication['config'].get('history_backfill_start', HISTORY.isoformat())
            lower = day_start(coupon_time(history).astimezone(SHANGHAI).date())
            target = revision if latest else int(publication['data_version'])
            if target > revision:
                raise ValueError('maintenance_publication_future_version')
            return ProjectionFacts(self, publication, (publication['publication_id'], current),
                                   lower, target, ready(db, revision))
