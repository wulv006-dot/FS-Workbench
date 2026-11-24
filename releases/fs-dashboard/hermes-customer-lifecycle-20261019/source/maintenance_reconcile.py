"""Reconcile recorded attempts by original job and batch. This worker never grants."""
from datetime import timedelta

from maintenance_dispatch import CALL_TIMEOUT, invoke


RECOVERY_AGE = timedelta(seconds=CALL_TIMEOUT + 60)


def read_job(job, email, batch):
    return invoke('reconcile', job_id=job, email=email, batch=batch)


def reconcile(ledger, clock, lookup=read_job):
    ledger.recover_dispatches(clock(), RECOVERY_AGE)
    for row in ledger.reconcile_queue():
        try:
            receipt = lookup(row['job_id'], row['email'], row['batch'])
        except Exception as error:
            receipt = dict(state='unknown', error_code=type(error).__name__)
        ledger.result(row['id'], row['state'], receipt, clock(), 'system-maintenance-reconcile')