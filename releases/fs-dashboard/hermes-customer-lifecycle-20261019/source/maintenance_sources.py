"""Read-only adapters for the user analysis publication and existing Admin proxy."""
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

from maintenance_review import coupon_time, email_key, member_id
from maintenance_stages import SHANGHAI, day_start


DB_PATH = Path('/var/lib/fs-user-analytics/customers.sqlite3')
HISTORY = date(2026, 1, 1)
SITE = '266'


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
        if value.get('code') != 1 or not isinstance(value.get('data'), dict):
            raise ValueError('maintenance_admin_read_failed')
        return value['data']

    def pages(self, kind, filters):
        params = {'limit': 100, 'order': 'id,desc'}
        for index, (field, op, value) in enumerate(filters):
            for name, item in (('field', field), ('operator', op), ('val', value)):
                params[f'search[{index}][{name}]'] = item
        previous_total, found = None, {}
        for page in range(1, 201):
            payload = self.read(self.ROUTES[kind], dict(params, page=page))
            rows, total = payload.get('list'), payload.get('total')
            if isinstance(total, str) and total.isascii() and total.isdecimal():
                total = int(total)
            if (type(total) is not int or not 0 <= total <= 20000 or not isinstance(rows, list)
                    or len(rows) > params['limit'] or previous_total not in (None, total)):
                raise ValueError('maintenance_admin_pagination')
            previous_total = total
            for row in rows:
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

    def logs(self, start, stop):
        source_time = lambda at: at.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
        bound = source_time(start) + ',' + source_time(stop)
        rows = self.pages('usage', [('site_id', '=', SITE), ('use_time', 'RANGE', bound)])
        if any(str(row.get('site_id')) != SITE for row in rows):
            raise ValueError('maintenance_coupon_log_site')
        return [row for row in rows if start < coupon_time(row.get('use_time')) <= stop]

    def exceptions(self, orders):
        """Refresh actual refund and issue evidence from the exact local order numbers."""
        from vip_followup import preferred_disposition, project_order
        wanted = {row['order_no']: row['order_key'] for row in orders if row.get('order_no') and not row.get('test_order')}
        numbers = sorted(wanted)
        if any(',' in number for number in numbers):
            raise ValueError('maintenance_admin_order_number')
        findings = []
        for offset in range(0, len(numbers), 100):
            scope = set(numbers[offset:offset + 100])
            rows = self.pages('orders', [('site_id', '=', SITE), ('order_no', 'IN', ','.join(sorted(scope)))])
            if ({row.get('order_no') for row in rows} != scope or len(rows) != len(scope)
                    or any(str(row.get('site_id')) != SITE for row in rows)):
                raise ValueError('maintenance_admin_order_scope')
            for row in rows:
                view = project_order(row)
                if view['afterSales'] == 'unknown' or view['refundStatus'] == 'unknown':
                    raise ValueError('maintenance_admin_order_state_unknown')
                disposition = preferred_disposition(view)
                if disposition == 'problem' or view['afterSales'] != 'none_observed':
                    findings.append(dict(order_key=wanted[row['order_no']],
                                         reason='problem' if disposition == 'problem' else 'after_sales',
                                         after_sales=view['afterSales'],
                                         refund=view['refundStatus'], refund_amount=view['sourceRefundAmount'],
                                         pay_status=view['payStatus'], order_state=view['orderState']))
        return findings


class Facts:
    def __init__(self, publication, orders, jobs, token, uid_pairs=(), identities=None):
        self.publication = publication
        self.cutoff = coupon_time(publication['cutoff'])
        self.day = self.cutoff.date() - timedelta(days=1)
        self.orders = orders
        self.token = token
        self.customers = defaultdict(list)
        self.by_order = {}
        self.uid_customers = defaultdict(set)
        self.customer_uids = defaultdict(set)
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
                    self.customer_uids[customer].add(uid)
        for pair in uid_pairs:
            uid = member_id(pair[1])
            if uid:
                self.uid_customers[uid].add(pair[0])
        self.intervals = sorted((coupon_time(job['start']), coupon_time(job['end']))
                                for job in jobs if job['site'] == SITE and job['state'] == 'complete')

    def email_conflict(self, customer, address):
        return bool(self.email_customers.get(email_key(address), set()) - {customer})

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

    def token(self):
        with self.db() as db:
            receipt = self.receipt(db)
            revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            return receipt['publication_id'], revision

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

    @staticmethod
    def _read_rows(db, target, revision, lower, upper):
        if target > revision:
            raise ValueError('maintenance_publication_future_version')
        if target == revision:
            return db.execute('SELECT * FROM orders WHERE site=? AND paid_at>=? AND paid_at<?',
                              (SITE, lower, upper)).fetchall()
        import user_version_index
        if user_version_index.ready(db, revision):
            return [row for row in user_version_index.read(db, target, start=lower, end=upper)
                    if row['site'] == SITE]
        rows = {row['order_key']: row for row in db.execute(
            'SELECT * FROM orders WHERE site=? AND revision<=? AND paid_at>=? AND paid_at<?',
            (SITE, target, lower, upper))}
        needed = revision - target
        if needed > 40:
            raise LookupError('maintenance_projection_waiting_for_revisions')
        restored = set()
        for _, body in db.execute('SELECT id,body FROM revisions WHERE id>? AND id<=? ORDER BY id', (target, revision)):
            needed -= 1
            for row in json.loads(body):
                key = row['order_key']
                if key in restored or row['site'] != SITE or row['revision'] > target:
                    continue
                restored.add(key)
                if lower <= row['paid_at'] < upper:
                    rows[key] = row
        if needed:
            raise LookupError('maintenance_projection_incomplete')
        return list(rows.values())

    def read(self, now, *, latest=False):
        with self.db() as db:
            publication = self.receipt(db)
            cutoff = coupon_time(publication['cutoff'])
            if cutoff > now:
                raise ValueError('maintenance_publication_future')
            current = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            revision = int(current)
            lower = day_start(date.fromisoformat(publication['config'].get('history_backfill_start', HISTORY.isoformat())))
            target = revision if latest else int(publication['data_version'])
            rows = self._read_rows(db, target, revision, lower.isoformat(), cutoff.isoformat())
            emails = {}
            for ident, address in db.execute('SELECT DISTINCT customer_id,email FROM identities'):
                if ident in emails and emails[ident] != address:
                    raise ValueError('maintenance_projection_email_conflict')
                emails[ident] = address
            uid_pairs = db.execute("""SELECT DISTINCT customer_id, json_extract(body,'$.uid') FROM orders
                                      WHERE customer_id IS NOT NULL AND json_extract(body,'$.uid') IS NOT NULL""").fetchall()
        try:
            flags = self._flags(publication, lower)
        except (OSError, LookupError, ValueError):
            # A missing or conflicting ES label remains unverified.
            flags = {}
        orders = []
        for row in rows:
            body = json.loads(row['body'])
            number = body.get('order_no')
            if not isinstance(number, str) or row['order_key'] != 'admin:' + SITE + ':' + number:
                raise ValueError('maintenance_projection_order_identity')
            row = dict(row)
            row.pop('body', None)
            customer = row['customer_id']
            row.update(order_no=number, uid=body.get('uid'), email=emails.get(customer),
                       amount_usd=body.get('amount_usd'), pay_status=body.get('pay_status'),
                       test_order=bool(body.get('test_order')),
                       new_customer_flag=flags.get(hashlib.sha256(number.encode()).hexdigest()))
            orders.append(row)
        return Facts(publication, orders, publication['jobs'], (publication['publication_id'], current), uid_pairs, emails)