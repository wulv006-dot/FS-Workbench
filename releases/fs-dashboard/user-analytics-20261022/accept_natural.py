"""Read actual scheduled day advancement; never run a job, query, source or model."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/fs-hermes-fc')
from user_contract import stamp
from user_lifecycle import state
from user_runtime import load_store


def transition_sample(before, after, old_day, new_day, points):
    samples = []
    for cid in before.keys() & after.keys():
        a, b = before[cid], after[cid]
        if a['last_paid_at'] != b['last_paid_at'] or a['stage'] == b['stage'] or 'unverified' in (a['stage'], b['stage']):
            continue
        paid = stamp(b['last_paid_at'])
        assert a['stage'] == state(paid, old_day, points)
        assert b['stage'] == state(paid, new_day, points)
        samples.append(dict(before_stage=a['stage'], after_stage=b['stage'], unchanged_last_paid_at=b['last_paid_at']))
        if len(samples) == 3:
            break
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-baseline', action='store_true')
    args = parser.parse_args()
    store = load_store()
    root = store.root / 'acceptance-w6'
    baseline = root / 'baseline-20261023.json'
    current = json.loads((store.root / 'daily-state.json').read_text())
    if args.capture_baseline:
        assert current['day'] == '2026-10-23' and current['trigger'] == 'systemd', 'scheduled_baseline_required'
        root.mkdir(mode=0o700, exist_ok=True)
        assert not root.is_symlink() and not root.stat().st_mode & 0o077
        fd = os.open(baseline, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(current, output); output.flush(); os.fsync(output.fileno())
        print(json.dumps(dict(status='baseline_captured', snapshot_id=current['snapshot_id'], day=current['day'])))
        return
    assert baseline.is_file() and not baseline.is_symlink(), 'baseline_missing'
    old = json.loads(baseline.read_text())
    if current['day'] <= old['day']:
        print(json.dumps(dict(status='pending_actual_midnight', baseline_day=old['day'], current_day=current['day'])))
        return
    assert current['trigger'] == 'systemd', 'actual_scheduled_receipt_required'
    assert current['source_collection'] is False
    qa, a, pa = store.snapshot(old['snapshot_id'])
    qb, b, pb = store.snapshot(current['snapshot_id'])
    assert qa['scope'] == qb['scope'] == 'global' and qa['policy_version'] == qb['policy_version']
    assert a['lifecycle_policy'] == b['lifecycle_policy'] and a['coverage']['period_complete'] and b['coverage']['period_complete']
    old_day, new_day = (stamp(q['as_of']) - timedelta(microseconds=1) for q in (qa, qb))
    samples = transition_sample(pa['records'], pb['records'], old_day.date(), new_day.date(), b['lifecycle_policy']['thresholds_days'])
    assert samples, 'no_verified_no_purchase_stage_transition_yet'
    assert all(stamp(row['unchanged_last_paid_at']) < stamp(qa['as_of']) for row in samples)
    job = json.loads((store.root / 'job-status.json').read_text())
    assert job['status'] == 'complete', 'source_job_not_complete'
    unit = subprocess.check_output(['systemctl', 'show', 'fs-user-analytics.service', '-p', 'Result', '-p', 'ExecMainStatus'], text=True)
    assert 'Result=success' in unit and 'ExecMainStatus=0' in unit
    journal = subprocess.check_output(['journalctl', '-u', 'fs-user-analytics.service', '--since', current['day']+' 00:00:00', '--no-pager', '-o', 'short-iso'], text=True)
    assert current['day'] in journal and 'Starting FS purchase customer' in journal
    print(json.dumps(dict(status='passed_actual_scheduled_day_advance', baseline_snapshot=old['snapshot_id'], current_snapshot=current['snapshot_id'],
                          baseline_data_version=a['data_version'], current_data_version=b['data_version'], samples=samples,
                          source_job=job['receipts'][0]['job_id'], natural_failure_recovery='not_claimed_without_actual_failed_and_recovered_receipts')))


if __name__ == '__main__':
    main()
