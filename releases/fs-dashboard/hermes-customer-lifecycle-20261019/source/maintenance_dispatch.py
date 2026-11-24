"""Validate a fresh template, reserve once, then invoke the existing coupon writer."""
import json
from pathlib import Path
import re
import subprocess

from maintenance_ledger import AWAITING
from maintenance_review import coupon_time


CALL_TIMEOUT = 105
BRIDGE = Path(__file__).resolve().with_name('maintenance_coupon_bridge.cjs')
EMAIL = re.compile(r'^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$')


def invoke(action, **payload):
    result = subprocess.run(['node', str(BRIDGE)], input=json.dumps(dict(action=action, **payload)).encode(),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=CALL_TIMEOUT, check=True)
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError('maintenance_coupon_bridge_result')
    return value


class Bridge:
    def detail(self, coupon):
        return invoke('detail', coupon_id=coupon)

    def grant(self, coupon, email, batch):
        return invoke('grant', coupon_id=coupon, email=email, batch=batch)


def checked_template(template, coupon, at):
    exact = dict(id=str(coupon), site_id='266', game_id='1327', fetch_scene='4', status='1')
    if not isinstance(template, dict) or any(str(template.get(key)) != val for key, val in exact.items()):
        raise ValueError('maintenance_coupon_template_scope')
    mode = str(template.get('time_effect'))
    if mode == '1':
        if coupon_time(template.get('end_time')) <= at:
            raise ValueError('maintenance_coupon_template_expired')
    elif mode != '2' or not str(template.get('days', '')).isdecimal() or int(template['days']) < 1:
        raise ValueError('maintenance_coupon_template_validity')
    return template


def valid_email(email):
    return (isinstance(email, str) and len(email) <= 254 and email == email.strip().lower()
            and EMAIL.fullmatch(email) is not None)


class Dispatcher:
    def __init__(self, ledger, bridge, prepare_recheck, clock):
        self.ledger = ledger
        self.bridge = bridge
        self.prepare_recheck = prepare_recheck
        self.clock = clock

    def once(self, ident):
        row = self.ledger.entry(ident)
        if not row or row['state'] not in AWAITING:
            return
        snapshot = row['rule_body']['template']
        coupon = snapshot['id']
        template = self.bridge.detail(coupon)
        now = self.clock()
        try:
            changed = checked_template(template, coupon, now) != snapshot
        except ValueError:
            changed = True
        if changed or not valid_email(row['email']):
            reason = 'template_changed' if changed else 'recipient_changed'
            self.ledger.claim(ident, now, lambda db, fresh: reason)
            return
        recheck = self.prepare_recheck(row, now)
        claimed = self.ledger.claim(ident, self.clock(), recheck)
        if claimed is None:
            return
        # The local reservation and original batch must be durable before this call.
        try:
            receipt = self.bridge.grant(coupon, claimed['email'], claimed['batch'])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            receipt = dict(state='unknown', error_code=type(error).__name__)
        self.ledger.result(ident, 'dispatching', receipt, self.clock())