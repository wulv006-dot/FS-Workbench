"""Reconcile recorded attempts by original job and batch. This worker never grants."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import subprocess

from maintenance_ledger import Ledger, SHANGHAI
from maintenance_review import BATCH


BRIDGE = Path(__file__).resolve().with_name('maintenance_coupon_reconcile.cjs')
CALL_TIMEOUT = 105
RECOVERY_AGE = timedelta(seconds=CALL_TIMEOUT + 60)


def read_job(job, email, batch):
    request = json.dumps(dict(job_id=job, email=email, batch=batch)).encode()
    result = subprocess.run(['node', str(BRIDGE)], input=request, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=CALL_TIMEOUT, check=True)
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError('maintenance_coupon_reconcile_result')
    return value


def reconcile(ledger, clock, lookup=read_job):
    ledger.recover_dispatches(clock(), RECOVERY_AGE)
    for row in ledger.reconcile_queue():
        try:
            receipt = lookup(row['job_id'], row['email'].lower(), row['batch'])
        except Exception as error:
            receipt = dict(state='unknown', error_code=type(error).__name__)
        ledger.result(row['id'], row['state'], receipt, clock(), 'system-maintenance-reconcile',
                      reconciled=True)

class Reconciliation:
    def __init__(self, store):
        self.ledger = Ledger(store.db)
        self.clock = lambda: datetime.now(SHANGHAI)

    def run(self):
        reconcile(self.ledger, self.clock, read_job)

    def manual_view(self, offset):
        rows = self.ledger.manual_queue(limit=21, offset=offset)
        items = []
        for row in rows[:20]:
            reviews = self.ledger.reviews(row['id'])
            item = {key: value for key, value in row.items() if key != 'rule_body'}
            items.append(dict(item, review=reviews[-1] if reviews else None))
        return dict(status='ready', items=items, next_offset=offset+20 if len(rows) > 20 else None)

    def manual_result(self, actor, body):
        if set(body) != {'id', 'batch', 'state', 'evidence'}:
            raise ValueError('maintenance_request_fields')
        ident, batch, proof = body['id'], body['batch'], body['evidence']
        if not isinstance(ident, str) or re.fullmatch(r'm_[a-f0-9]{64}', ident) is None:
            raise ValueError('maintenance_id')
        row = self.ledger.entry(ident)
        if (not isinstance(batch, str) or BATCH.fullmatch(batch) is None
                or not row or batch != row['batch'] or not isinstance(proof, str)
                or not 1 <= len(proof.strip()) <= 300 or any(ord(char) < 32 for char in proof)):
            raise ValueError('maintenance_manual_evidence')
        return dict(changed=self.ledger.manual_result(ident, body['state'], actor, self.clock(), proof.strip()))
