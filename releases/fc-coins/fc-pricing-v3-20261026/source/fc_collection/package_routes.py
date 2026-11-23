"""Complete missing ordinary price slots in node order; the first usable slot wins."""
import sqlite3
import subprocess
from collections import defaultdict

from fc_pricing_v3.competitor_offers import normalize_offers


def collect_missing(source, run_id, wanted, read, clock):
    if source not in ('U4GM', 'IGGM'):
        raise ValueError('package_route_source')
    remaining = set(wanted)
    accepted, attempts = [], []
    nodes = ('187', '183', 'local') if source == 'IGGM' else ('187', '183')
    receipt_only = False
    for node in nodes:
        if not remaining:
            break
        requested = sorted(remaining)
        request = dict(source=source, run_id=run_id, wanted=requested, receipt_only=receipt_only)
        result = dict(node=node, requested=requested, accepted=[], errors=[])
        attempts.append(result)
        try:
            receipt = read(node, request)
            if (not isinstance(receipt, dict) or receipt.get('run_id') != run_id or receipt.get('source') != source
                    or not isinstance(receipt.get('offers'), list) or len(receipt['offers']) > 64):
                raise ValueError('package_receipt_scope')
            result['errors'].extend(reason for reason in receipt.get('errors', [])
                                    if isinstance(reason,str) and reason.isascii() and reason.replace('_','').isalnum()
                                    and len(reason)<=64)
            receipt_only = receipt_only or any(reason in ('http_401','http_403','http_429','challenge','captcha','source_access_restricted')
                                               for reason in result['errors'])
            slots = defaultdict(list)
            for raw in receipt['offers']:
                if not isinstance(raw, dict) or raw.get('source') != source or raw.get('run_id') != run_id:
                    continue
                slot = raw.get('platform'),raw.get('purchase_k')
                if slot not in remaining or raw.get('extra_bonus_tier') or raw.get('coupon_excluded') is not True:
                    continue
                try:
                    rows = normalize_offers([raw], run_id, clock())
                except ValueError:
                    continue
                if (rows and rows[0]['currency']=='USD' and rows[0]['regular_price'] and rows[0]['comparable']
                        and rows[0]['conditional'] is False and rows[0]['promotion_eligibility']=='all_customers'
                        and rows[0]['delivery_method']=='comfort_trade' and str(rows[0].get('region_id') or 0)=='0'):
                    slots[slot].append(rows[0])
            for slot, rows in slots.items():
                if len(rows) != 1:
                    result['errors'].append('ambiguous_package')
                    continue
                accepted.append(dict(rows[0], collection_node=node))
                remaining.remove(slot)
                result['accepted'].append(slot)
        except (OSError, ValueError, EOFError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            result['errors'].append(type(exc).__name__)
    return accepted, attempts



def record_restriction(request, receipt):
    from .client import DATABASE, utc
    from .coordinator import Coordinator
    if receipt.get('run_id') != request['run_id'] or receipt.get('source') != request['source']:
        raise ValueError('package_receipt_scope')
    errors = receipt.get('errors', [])
    blocked = any(code in errors for code in ('http_401', 'http_403', 'challenge', 'captcha'))
    if blocked or 'http_429' in errors:
        if not DATABASE.is_file() or DATABASE.is_symlink():
            raise ValueError('collection_original_ledger_required')
        coordinator = Coordinator(DATABASE)
        with coordinator.transaction() as db:
            policy = coordinator._get(db, 'collection_sources', request['source'])
            if not policy:
                raise ValueError('collection_source_not_ready')
            if blocked:
                policy['blocked'] = True
            if 'http_429' in errors:
                retry = receipt.get('retry_after_seconds', 0)
                if type(retry) != int or not 0 <= retry <= 31536000:
                    policy['blocked'] = True
                else:
                    until = utc().timestamp() + max(retry, policy['retry_after_seconds'])
                    policy['cooldown_until'] = max(until, policy['cooldown_until'])
            coordinator._put(db, 'collection_sources', request['source'], policy)
    return receipt


def read_node(node, request, started):
    import json
    from datetime import timedelta
    from pathlib import Path
    from .client import legacy_ready
    if not legacy_ready(request['source'], require_registered=True):
        request = dict(request, receipt_only=True)
    if node == 'local':
        from .package_relay import request_local
        return record_restriction(request, request_local(request))
    if node == '187':
        runner = Path(__file__).with_name('package_reader.py')
        python = '/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12'
        process = subprocess.run([python,'-I','-B',str(runner)], input=json.dumps(request),
                                 text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 check=True, timeout=30)
        return record_restriction(request, json.loads(process.stdout))
    from .client import ROUTING, collect_remote, read_routing_file
    source = request['source']
    if request.get('receipt_only'):
        return dict(source=source, run_id=request['run_id'], offers=[], errors=['source_access_restricted'])
    routing = read_routing_file(ROUTING.with_name(source.lower()+'-routing.json'))
    if routing['remote_result_mode'] != 'consume':
        return dict(source=source, run_id=request['run_id'], offers=[], errors=['collection_route_unavailable'])
    parent = dict(run_id=request['run_id'], created_at=started.isoformat(), deadline_at=(started+timedelta(seconds=100)).isoformat())
    receipt = collect_remote(parent, routing, source_id=source, wanted=request['wanted'])
    return dict(source=source, run_id=receipt['run_id'], offers=receipt['offers'], errors=receipt.get('errors',[]))
