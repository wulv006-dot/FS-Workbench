"""Server-only, explicitly confirmed recovery of a confirmed FC27 price execution."""
from __future__ import annotations

import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

from playwright.sync_api import sync_playwright

sys.path.insert(0, '/opt')
import writer  # noqa: E402
from automation_policy import load_policy  # noqa: E402


ROOT = writer.ROOT
PLATFORMS = writer.PLATFORMS


def restore_safety(rows, selected, expected=None):
    from pricing_v2 import verify_quote, envelope_ratio, prove_catalog, fingerprint,required_history_ratio
    from automation_policy import POLICY_FILE
    policy=load_policy()
    restored={r['platform']:r['restore_b2c'] for r in rows}
    if {'PS','XBOX'}<=set(selected) and Decimal(restored['PS'])!=Decimal(restored['XBOX']):
        raise ValueError('pricing_common_console_restore_required')
    newest=max((ROOT/'quotes').glob('*.json'),key=lambda p:p.stat().st_mtime,default=None)
    if newest is None:raise ValueError('restore_current_cost_quote_required')
    raw=newest.read_bytes();quote=json.loads(raw)
    verify_quote(quote,policy,selected,for_execution=True)
    current=json.loads((POLICY_FILE.parent/'pricing-inputs.json').read_text('utf-8'))
    ratio=envelope_ratio(current,datetime.now(timezone.utc))
    if current['sha256']!=quote['evidence']['promotion_envelope']['sha256']:
        raise ValueError('pricing_promotions_changed_since_quote')
    basis=dict(run_id=quote['run_id'],quote_sha256=hashlib.sha256(raw).hexdigest(),
               promotion_sha256=current['sha256'],policy_revision=policy['revision'])
    if expected is not None and expected!=basis:raise ValueError('restore_current_cost_basis_changed')
    by={r['platform']:r for r in quote['result']['rows']}
    for row in rows:
        p=row['platform']
        if p not in selected:continue
        prove_catalog(row['restore_b2c'],by[p]['cost_cny'],quote['evidence']['fx']['cny_per_usd'],
                      ratio,policy['minimum_gross_margin_pct'],current['packages'][p],
                      average_ratio=required_history_ratio(quote['evidence'],datetime.now(timezone.utc)))
    return basis


def source_audit(source_id):
    writer.parse_uuid(source_id)
    path = ROOT / 'executions' / f'{source_id}.json'
    audit = writer.read_json(path)
    if (audit.get('execution_id') != source_id or audit.get('status') != 'CONFIRMED'
            or audit.get('sync_confirmed') is not True or not audit.get('after')
            or not audit.get('before') or not audit.get('targets')):
        raise ValueError('restore_source_not_confirmed')
    if [row['platform'] for row in audit['before']['rows']] != list(PLATFORMS):
        raise ValueError('restore_source_platform_invalid')
    return audit, hashlib.sha256(path.read_bytes()).hexdigest()


def rows_by_platform(snapshot):
    return {row['platform']: row for row in snapshot['rows']}


def current_equals_source(page, current, source):
    if not writer.same_backend(page, current, source['after']):
        raise ValueError('restore_backend_changed_since_execution')


def connect_page(playwright):
    browser = playwright.chromium.connect_over_cdp(
        os.environ.get('FC27_CDP_ENDPOINT', 'http://127.0.0.1:9225'),
        timeout=8000, no_defaults=True)
    if len(browser.contexts) != 1:
        raise ValueError('browser_context_ambiguous')
    _global_order.apply(browser.contexts[0])
    page = browser.contexts[0].new_page()
    page.goto(writer.PRICE_URL, wait_until='domcontentloaded', timeout=35000)
    return page


def preview_restore(source_id):
    source, source_hash = source_audit(source_id)
    policy = load_policy()
    with sync_playwright() as playwright:
        page = connect_page(playwright)
        try:
            current = writer.read_backend(page, source['targets'], prepare=True)
            current_equals_source(page, current, source)
            before = rows_by_platform(source['before'])
            after = rows_by_platform(current)
            now = datetime.now(timezone.utc)
            rows = [{
                    'platform': platform,
                    'id': next(t['id'] for t in source['targets'] if t['platform'] == platform),
                    'current_cost': after[platform]['costPrice'],
                    'current_b2c': after[platform]['b2c'],
                    'restore_cost': before[platform]['costPrice'],
                    'restore_b2c': before[platform]['b2c'],
                } for platform in PLATFORMS]
            safety=restore_safety(rows,source['selected'])
            return {
                'restore_preview_id': str(uuid.uuid4()),
                'source_execution_id': source_id,
                'source_sha256': source_hash,
                'created_at': now.isoformat(),
                'expires_at': (now + timedelta(minutes=15)).isoformat(),
                'status': 'restore_review_only',
                'automation_policy_revision': policy['revision'],
                'available_platforms': source['selected'],
                'backend_before': current,
                'rows': rows,
                'pricing_guard': safety,
            }
        finally:
            page.close()


def verify_progress(snapshot, preview, selected, restored):
    before = {row['platform']: row for row in preview['rows']}
    for row in snapshot['rows']:
        platform = row['platform']
        original = before[platform]
        cost_expected = original['restore_cost'] if platform in restored else original['current_cost']
        if not writer.same_money(row['costPrice'], cost_expected):
            raise ValueError('restore_cost_changed:' + platform)
        allowed = ((original['current_b2c'], original['restore_b2c'])
                   if platform in restored else (original['current_b2c'],))
        if not any(writer.same_money(row['b2c'], value) for value in allowed):
            raise ValueError('restore_b2c_changed:' + platform)
        if platform not in selected and platform in restored:
            raise ValueError('restore_unselected_changed:' + platform)


def execute_restore(request):
    preview_id = writer.parse_uuid(request['restore_preview_id'])
    execution_id = writer.parse_uuid(request['execution_id'])
    actor = request['actor']
    selected = request['platforms']
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', actor):
        raise ValueError('actor_invalid')
    if (not isinstance(selected, list) or not selected
            or len(selected) != len(set(selected))
            or any(x not in PLATFORMS for x in selected)):
        raise ValueError('restore_selection_invalid')
    preview = writer.read_json(ROOT / 'restore-previews' / f'{preview_id}.json')
    if preview.get('restore_preview_id') != preview_id or preview.get('status') != 'restore_review_only':
        raise ValueError('restore_preview_invalid')
    if datetime.now(timezone.utc) >= writer.utc(preview['expires_at']):
        raise ValueError('restore_preview_expired')
    if any(x not in preview['available_platforms'] for x in selected):
        raise ValueError('restore_platform_unavailable')
    policy = load_policy()
    if preview.get('automation_policy_revision') != policy['revision']:
        raise ValueError('automation_policy_changed')
    source_id = writer.parse_uuid(preview['source_execution_id'])
    if writer.parse_uuid(request['source_execution_id']) != source_id:
        raise ValueError('restore_source_mismatch')
    source, source_hash = source_audit(source_id)
    if source_hash != preview['source_sha256']:
        raise ValueError('restore_source_changed')
    safety=restore_safety(preview['rows'],selected,preview.get('pricing_guard'))
    for path in (ROOT / 'executions').glob('*.json'):
        status = writer.read_json(path).get('status')
        if status in {'RUNNING', 'UNCERTAIN', 'PARTIAL'}:
            raise ValueError('unresolved_execution_exists')
    record = {
        'execution_id': execution_id, 'kind': 'restore',
        'source_execution_id': source_id, 'restore_preview_id': preview_id,
        'actor': actor, 'selected': selected, 'changed': [],
        'status': 'RUNNING', 'stage': 'preflight', 'sync_confirmed': False,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'before': preview['backend_before'], 'targets': preview['rows'],
        'pricing_guard': safety,
    }
    with sync_playwright() as playwright:
        page = connect_page(playwright)
        try:
            current = writer.read_backend(page, source['targets'], prepare=True)
            if not writer.same_backend(page, preview['backend_before'], current):
                raise ValueError('restore_backend_changed_since_preview')
            current_equals_source(page, current, source)
            marker = ROOT / 'executions' / f'restore-{source_id}.used'
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            os.close(descriptor)
            writer.stage(record, 'started')
            target_map = {row['platform']: row for row in preview['rows']}
            for platform in selected:
                restore_safety(preview['rows'],selected,safety)
                current = writer.read_backend(page, source['targets'])
                verify_progress(current, preview, selected, record['changed'])
                target = target_map[platform]
                if not writer.same_money(target['current_cost'], target['restore_cost']):
                    writer.stage(record, 'restoring_' + platform)
                    page.evaluate('args => FC27RepricingDOM.setCost(...args)', [
                        platform, target['id'], target['current_cost'],
                        target['restore_cost'], target['current_b2c']])
                    current = writer.read_backend(page, source['targets'])
                    actual = rows_by_platform(current)[platform]
                    if not writer.same_money(actual['costPrice'], target['restore_cost']):
                        raise ValueError('restore_save_readback_mismatch:' + platform)
                record['changed'].append(platform)
                writer.stage(record, 'restored_' + platform)
            current = writer.read_backend(page, source['targets'])
            verify_progress(current, preview, selected, record['changed'])
            writer.stage(record, 'syncing')
            restore_safety(preview['rows'],selected,safety)
            feedback = page.evaluate("async () => FC27RepricingDOM.clickSync('mmoexp.com')")
            if not feedback or not feedback.get('success') or not feedback.get('message'):
                raise ValueError('restore_sync_feedback_unconfirmed')
            writer.stage(record, 'sync_feedback', sync_confirmed=True,
                         sync_message=str(feedback['message'])[:120])
            page.reload(wait_until='domcontentloaded', timeout=35000)
            after = writer.read_backend(page, source['targets'], prepare=True)
            before = target_map
            for platform, row in rows_by_platform(after).items():
                target = before[platform]
                cost_expected = (target['restore_cost'] if platform in selected
                                 else target['current_cost'])
                b2c_expected = (target['restore_b2c'] if platform in selected
                                else target['current_b2c'])
                if not writer.same_money(row['costPrice'], cost_expected) or not writer.same_money(row['b2c'], b2c_expected):
                    raise ValueError('restore_readback_mismatch:' + platform)
            writer.stage(record, 'readback_confirmed', status='RESTORED', after=after)
            return {'status': 'RESTORED', 'execution_id': execution_id,
                    'source_execution_id': source_id, 'platforms': selected,
                    'sync_confirmed': True}
        except Exception as exc:
            if (ROOT / 'executions' / f'{execution_id}.json').exists():
                reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                uncertain = record['stage'] in {'syncing', 'sync_feedback'}
                try:
                    observed = writer.read_backend(page, source['targets'])
                    for platform in selected:
                        target = next(row for row in preview['rows'] if row['platform'] == platform)
                        actual = rows_by_platform(observed)[platform]
                        if (writer.same_money(actual['costPrice'], target['restore_cost'])
                                and platform not in record['changed']):
                            record['changed'].append(platform)
                except Exception:
                    uncertain = True
                status = ('UNCERTAIN' if uncertain else 'PARTIAL' if record['changed']
                          else 'FAILED_BEFORE_WRITE')
                writer.stage(record, 'stopped', status=status, error=reason[:100])
            raise
        finally:
            page.close()


if __name__ == '__main__':
    try:
        request = json.loads(Path('/run/request.json').read_text(encoding='utf-8'))
        result = (preview_restore(request['source_execution_id'])
                  if request.get('mode') == 'preview' else execute_restore(request))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({'status': 'FAILED', 'reason': reason[:100]}))
        raise SystemExit(1)
