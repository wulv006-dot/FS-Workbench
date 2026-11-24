"""Coupon attribution and deterministic program review for a maintenance entry."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re


MANUAL_COUPON_NOTICE = '人工券：仅核对已使用记录，已发未用的人工券暂不可见'
REVIEW_ACTOR = 'system-maintenance-review'
BATCH = re.compile(r'FCSM_[A-F0-9]{32}')
SHANGHAI = timezone(timedelta(hours=8))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


EMAIL = re.compile(r'^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$')


def valid_email(email):
    return (isinstance(email, str) and len(email) <= 254 and email == email.strip()
            and EMAIL.fullmatch(email) is not None)


def email_key(value):
    return value.strip().casefold() if isinstance(value, str) else None


def member_id(value):
    if type(value) in (str, int) and re.fullmatch(r'[1-9][0-9]*', str(value).strip()):
        return str(value).strip()
    return None


class CouponIndex:
    def __init__(self, orders, logs, uid_customers=None):
        self.matched = defaultdict(list)
        self.unattributed = []
        if logs is None:
            raise ValueError('maintenance_coupon_evidence_unavailable')
        by_order = {}
        by_uid = defaultdict(set)
        for order in orders:
            customer = order.get('customer_id')
            if order.get('order_no'):
                by_order[str(order['order_no'])] = customer
            uid = member_id(order.get('uid'))
            if customer and uid:
                by_uid[uid].add(customer)
        for uid, owners in (uid_customers or {}).items():
            by_uid[uid].update(owners)
        for log in logs:
            number = str(log.get('order_no') or '')
            member = log.get('memberCoupon') or {}
            uid = member_id(log.get('member_id')) or member_id(log.get('uid')) or member_id(member.get('member_id'))
            if number in by_order:
                owner = by_order[number]
            elif len(by_uid[uid]) == 1:
                owner = next(iter(by_uid[uid]))
            else:
                owner = None
            if not owner:
                self.unattributed.append(log)
            else:
                self.matched[owner].append(log)
        self.unattributed_digest = digest(sorted(self.unattributed, key=canonical))

    def for_customer(self, customer):
        return dict(matched=sorted(self.matched.get(customer, ()), key=canonical),
                    unattributed=len(self.unattributed), unattributed_digest=self.unattributed_digest)


def coupon_evidence(orders, logs, customer_id):
    return CouponIndex(orders, logs).for_customer(customer_id)


def review_evidence(*, coupons, payments, exceptions, automatic, contacts):
    checks = dict(payments=payments, exceptions=exceptions, automatic=automatic, contacts=contacts)
    if not isinstance(coupons, dict) or any(not isinstance(rows, list) for rows in checks.values()):
        raise ValueError('maintenance_review_evidence_unavailable')
    checks['manual_coupons'] = coupons['matched']
    evidence = {field: sorted(rows, key=canonical) for field, rows in checks.items()}
    evidence['attributed_coupon_digest'] = coupons.get('attributed_coupon_digest')
    evidence['unattributed_coupon_logs'] = coupons['unattributed']
    evidence['unattributed_coupon_digest'] = coupons['unattributed_digest']
    evidence['manual_coupon_uid_gaps'] = coupons.get('uid_gaps', [])
    notice = coupons.get('notice', MANUAL_COUPON_NOTICE)
    if coupons['unattributed'] and 'notice' not in coupons:
        notice += '；另有 {} 条用券记录无法归属客户'.format(coupons['unattributed'])
    reasons = [field for field, rows in checks.items() if rows]
    return dict(decision='hold' if reasons else 'pass', reasons=reasons,
                digest=digest(evidence), manual_coupon_notice=notice,
                unattributed_coupon_logs=coupons['unattributed'],
                manual_coupon_uid_gaps=coupons.get('uid_gaps', []),
                order_exceptions=evidence['exceptions'],
                matches={field: len(rows) for field, rows in checks.items()})

def coupon_time(value):
    if not isinstance(value, str):
        raise ValueError('maintenance_coupon_time')
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('maintenance_coupon_time') from None
    return at if at.utcoffset() is not None else at.replace(tzinfo=SHANGHAI)


def manual_evidence(orders, customer_id, now, read_grants, used=None):
    by_uid = defaultdict(set)
    customer_uids = set()
    for order in orders:
        uid = member_id(order.get('uid'))
        customer = order.get('customer_id')
        if uid and customer:
            by_uid[uid].add(customer)
            if customer == customer_id:
                customer_uids.add(uid)
    unique = sorted(uid for uid in customer_uids if by_uid[uid] == {customer_id})
    gaps = sorted(customer_uids.difference(unique)) if customer_uids else ['missing']
    cutoff = now - timedelta(days=30)
    matched = []
    for uid in unique:
        rows = read_grants(uid)
        if not isinstance(rows, list):
            raise ValueError('maintenance_grants_unavailable')
        for row in rows:
            if member_id(row.get('member_id')) != uid:
                raise ValueError('maintenance_grant_uid_mismatch')
            if str(row.get('site_id')) != '266' or str(row.get('grant_batch_no') or '').startswith('FCSM_'):
                continue
            if cutoff < coupon_time(row.get('start_time')) <= now:
                matched.append(row)
    used = used or dict(matched=[], unattributed=0, unattributed_digest=digest([]))
    notice = (MANUAL_COUPON_NOTICE + '，会员 UID 未能唯一归属' if gaps
              else '人工券：已按可唯一归属的会员 UID 核对发放记录')
    if used['unattributed']:
        notice += '；另有 {} 条用券记录无法归属客户'.format(used['unattributed'])
    by_coupon = {('coupon', member_id(row['id'])): row for row in matched}
    for row in used['matched']:
        coupon = member_id(row.get('member_coupon_id')) or member_id((row.get('memberCoupon') or {}).get('id'))
        key = ('coupon', coupon) if coupon else ('usage', row['id'])
        by_coupon.setdefault(key, row)
    return dict(matched=list(by_coupon.values()), uid_gaps=gaps, notice=notice,
                attributed_coupon_digest=digest(used['matched']),
                unattributed=used['unattributed'], unattributed_digest=used['unattributed_digest'])
