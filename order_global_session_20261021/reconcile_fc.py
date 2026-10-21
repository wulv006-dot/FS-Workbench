"""Explicit continuation of this one empty ALL ledger, never repeats Order writes."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

ID = 'f1815592-9d7d-45ba-82c8-9c8da6ff42f4'
ROOT = Path('/var/lib/fc27-cloud')
APP = Path('/opt/fc27-cloud-browser')
sys.path.insert(0, str(APP))
spec = importlib.util.spec_from_file_location('p2pah_session_service', '/opt/fs-order-session/fc_shared_admin.py')
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)
# Host-side adapter configuration, without mounting or reading any passwords.
adapter.read_private_config = lambda: json.loads(Path('/etc/fc27-cloud/global-admin-principal.json').read_text())
import coin_all_sync_job as coin
from automation_policy import load_policy


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def order_check(audit):
    scripts = [str(APP / name) for name in ('repricing_logic.js', 'repricing_dom.js')]
    code = '''import sys,json
sys.path.insert(0,'/opt/fc27-collector')
import fs_order_client
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 stage='connect'
 b=p.chromium.connect_over_cdp('http://127.0.0.1:9226',timeout=8000)
 assert len(b.contexts)==1
 stage='shared_session'
 page=fs_order_client.new_page(b.contexts[0])
 try:
  stage='navigation'
  page.goto('https://order.p2pah.cn/game/admin_game_price/index.html?gid=1322',wait_until='domcontentloaded',timeout=45000)
  stage='inject'
  for script in SCRIPTS:page.add_script_tag(content=script)
  stage='read_filter'
  for attempt in range(40):
   state=page.evaluate('async () => await globalThis.FC27RepricingDOM.readAdminSnapshot()')
   if state.get('isRoute') and not state.get('login') and state.get('gameId')=='1322' and len(state.get('rows',[]))==3 and not state.get('allServerChecked') and state.get('selectedWebsites')==0 and state.get('b2cSelected'):break
   page.evaluate('async () => await globalThis.FC27RepricingDOM.prepareAdminFilter()')
   page.wait_for_timeout(500)
  else:raise RuntimeError('order_readback_filter_unverified')
  print(json.dumps(state))
 finally:page.close()
'''.replace('for script in SCRIPTS:', 'for script in ' + repr([Path(p).read_text() for p in scripts]) + ':')
    code = "stage='initializing'\ntry:\n" + textwrap.indent(code, ' ') + "\nexcept Exception as error:\n print(json.dumps({'error_type':type(error).__name__,'stage':stage}))\n raise SystemExit(1)\n"
    proc = subprocess.run(['docker', 'exec', '-i', 'fc27-cloud-browser', 'python3', '-c', 'import sys;exec(sys.stdin.read())'],
                          input=code, capture_output=True, text=True, timeout=85)
    if proc.returncode:
        detail = json.loads(proc.stdout) if proc.stdout else {'stage': 'process', 'error_type': 'no_result'}
        raise RuntimeError('order_readback_unavailable:' + detail['stage'] + ':' + detail['error_type'])
    actual, expected = json.loads(proc.stdout), audit['after']
    keys = ('id', 'gameId', 'platform', 'costPrice', 'lirunlv', 'b2c')
    assert [{k: r[k] for k in keys} for r in actual['rows']] == [{k: r[k] for k in keys} for r in expected['rows']], 'order_values_changed'
    return {'matched': True, 'checked_at': datetime.now(timezone.utc).isoformat()}


def main(apply):
    execution = ROOT / 'executions' / (ID + '.json')
    ledger = ROOT / 'all-coin-sync' / (ID + '.json')
    job = ROOT / 'jobs' / (ID + '.json')
    receipt = ROOT / 'recovery-receipts' / (ID + '.json')
    receipt.parent.mkdir(mode=0o700, exist_ok=True)
    with (ROOT / 'state/price-writer.lock').open('r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        audit, record, original_job = read(execution), read(ledger), read(job)
        assert original_job['status'] == 'failed' and original_job['error_detail'] == 'coin_identity_invalid'
        assert (audit['status'], audit['stage'], audit['error']) == ('PARTIAL', 'stopped', 'coin_identity_invalid')
        assert audit['sync_confirmed'] is True and audit['execution_id'] == ID
        assert record['execution_id'] == ID and record['status'] == 'needs_reconcile' and record['steps'] == []
        assert not list((ROOT / 'queue').glob('*.json'))
        hashes = {str(p): sha(p) for p in (execution, ledger, job, ROOT / 'config/automation.json', APP / 'coin_all_sync_job.py', Path('/opt/fs-order-session/fc_shared_admin.py'))}
        prior = read(receipt) if receipt.exists() else None
        if apply:
            assert prior and prior['status'] == 'checked' and prior['hashes'] == hashes, 'preflight_changed'
        policy = load_policy()
        assert policy['revision'] == audit['automation_policy_revision']
        proof = order_check(audit)
        manager = adapter.SessionManager(adapter.read_private_config())
        assert manager.ensure(), 'shared_admin_unavailable'
        context = deepcopy(audit)
        # This is an explicitly authorized manual continuation, preserving automatic history.
        context.update(stage='all_baseline_pending', automatic=False)
        planned_record = deepcopy(record)
        coin.wait_sources(manager, context, policy, planned_record, lambda r: None, load_policy)
        steps = coin.plan(manager, context, policy)
        if not apply:
            coin.atomic(receipt, {'status': 'checked', 'hashes': hashes, 'order': proof,
                                 'checked_at': datetime.now(timezone.utc).isoformat(),
                                 'price_posts_replayed': 0})
            print(json.dumps({'execution_id': ID, 'status': 'checked', 'order_matched': True,
                              'all_ledger_empty': True, 'admin_steps': len(steps),
                              'admin_changes': sum(s['changed'] for s in steps), 'order_posts': 0}))
            return
        assert all(sha(Path(p)) == digest for p, digest in hashes.items()), 'concurrent_change'
        backup = Path('/var/backups/order-global-fc-reconcile-20261021-v1')
        backup.mkdir(mode=0o700, exist_ok=False)
        for p in (execution, ledger, job):
            shutil.copy2(p, backup / (p.parent.name + '.json'))
        recovery = {'kind': 'manual_empty_preflight_continuation', 'original_error': audit['error'],
                    'original_automatic': True, 'order_posts_replayed': 0,
                    'claimed_at': datetime.now(timezone.utc).isoformat(), 'order': proof}
        context['recovery'] = recovery
        planned_record['recovery'] = recovery
        planned_record['steps'] = [{k: deepcopy(s[k]) for k in ('platform', 'product_id', 'source_product_id', 'before', 'source', 'payload', 'changed')} | {'status': 'pending'} for s in steps]
        planned_record['status'] = 'manual_continuation'
        def save_audit(value):
            saved = deepcopy(value)
            saved['automatic'] = audit['automatic']
            if saved['status'] == 'CONFIRMED':
                saved['original_failure'] = {'error': saved.pop('error', None), 'stage': 'stopped'}
            coin.atomic(execution, saved)
        coin.atomic(ledger, planned_record)
        result = coin.drive(manager, context, policy, steps, planned_record, save_audit,
                            lambda r: coin.atomic(ledger, r), load_policy)
        coin.atomic(receipt, {'status': result['status'], 'execution_id': ID, 'recovery': recovery,
                             'completed_at': datetime.now(timezone.utc).isoformat(), 'result': result})
        print(json.dumps({'execution_id': ID, 'status': result['status'], 'order_posts_replayed': 0,
                          'manual_reconciliation': True, 'changed_products': result['changed_products']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    main(parser.parse_args().apply)
