"""A single operator-reviewed D4 test entitlement. Never used for public claims."""
import hashlib
import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from match_rewards_delivery import CouponBridge


CONFIG = Path(__file__).with_name('d4-test-entitlement.json')


def entitlement(owner):
    if not CONFIG.is_file():
        return None
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    return cfg if cfg['discord_id'] == owner else None


def issue(state, owner, email, bridge=None):
    cfg = entitlement(owner)
    email = email.strip().lower()
    digest = hashlib.sha256(email.encode()).hexdigest()
    if not cfg or digest != cfg['recipient_sha256']:
        raise ValueError('Use the MMOEXP email approved for this private test.')
    if not (0 <= cfg['completed'] <= cfg['paid'] and cfg['paid'] >= 1 and cfg['completed'] < 5):
        raise ValueError('The reviewed account does not qualify for this test coupon.')
    coupon_id = cfg['coupon_id']
    adapter = bridge or CouponBridge()
    batch = 'FC27R_' + hashlib.sha256(('BF26-D4-single:' + digest).encode()).hexdigest()[:32].upper()
    with closing(sqlite3.connect(state / 'real-grant.sqlite3', timeout=10)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS grants (batch TEXT PRIMARY KEY, coupon INTEGER, status TEXT, job TEXT, receipt TEXT)')
        def read():
            return db.execute('SELECT coupon,status,job,receipt FROM grants WHERE batch=?', (batch,)).fetchone()
        row = read()
        if not row:
            detail = adapter.detail(coupon_id)
            expected = dict(id=coupon_id, type=1, status=1, site_id=266, game_id=1327, mode_type=1,
                            fetch_scene=4, time_effect=2, days=7, is_open=0, limit_qty=1, repeat_qty=1,
                            goods_id=0, product_type=0, attain=0, reduce=2)
            if (any(Decimal(str(detail.get(k))) != v for k,v in expected.items())
                    or detail.get('scope_bindings') not in ('', None, [])
                    or detail.get('title') != 'FC27 Black Friday D4 Pilot - $2 OFF'):
                raise ValueError('Coupon terms have changed. Contact the event host.')
            with db:
                inserted = db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?,NULL,NULL)',
                                      (batch,coupon_id,'submitted')).rowcount
            if inserted:
                result = adapter.grant(coupon_id, email, batch)
            else:
                row = read()
        if row:
            original, status, job, receipt = row
            if original != coupon_id:
                raise ValueError('The original test coupon must be reconciled.')
            if status != 'pending':
                return status, receipt
            result = adapter.reconcile(job,email,batch)
        status = result.get('state','unknown')
        receipt = str(result.get('member_coupon_id',''))
        if status == 'confirmed' and not (receipt.isascii() and receipt.isdigit() and int(receipt)>0):
            status = 'unknown'
        job = result.get('job_id') or (row[2] if row else None)
        if status == 'pending' and not job:
            status = 'unknown'
        with db:
            db.execute("UPDATE grants SET status=?,job=?,receipt=? WHERE batch=? AND status IN ('pending','submitted')",
                       (status,job,receipt if status=='confirmed' else None,batch))
        final = read()
        return final[1],final[3]
