"""Complete missing ordinary price slots in node order; the first usable slot wins."""
import sqlite3
import subprocess
from collections import defaultdict, deque

from fc_pricing_v3.competitor_offers import normalize_offers


def collect_missing(source, run_id, wanted, read, clock):
    if source != 'U4GM':
        raise ValueError('package_route_source')
    remaining = set(wanted)
    accepted, attempts = [], []
    nodes = deque(('187', '183', 'local'))
    while remaining and nodes:
        node = nodes.popleft()
        requested = sorted(remaining)
        request = dict(source=source, run_id=run_id, wanted=requested)
        result = dict(node=node, requested=requested, accepted=[], errors=[], response_received=False)
        attempts.append(result)
        try:
            receipt = read(node, request)
            if not isinstance(receipt, dict) or receipt.get('run_id') != run_id or receipt.get('source') != source:
                raise ValueError('package_receipt_scope')
            result['errors'].extend(reason for reason in receipt.get('errors', [])
                                    if isinstance(reason,str) and reason.isascii() and reason.replace('_','').isalnum()
                                    and len(reason)<=64)
            if not isinstance(receipt.get('offers'), list) or len(receipt['offers']) > 64:
                raise ValueError('package_receipt_scope')
            result['response_received'] = receipt.get('response_received', True)
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
                if not rows:
                    continue
                delivery_ok = rows[0]['delivery_method'] == 'comfort_trade' or (
                    source == 'U4GM' and node == 'local' and receipt.get('provider') == 'windows_u4gm_snapshot'
                    and raw['platform'] in ('PS', 'XBOX') and rows[0]['delivery_method'] == 'default_storefront')
                if (rows[0]['currency']=='USD' and rows[0]['regular_price'] and rows[0]['comparable']
                        and rows[0]['conditional'] is False and rows[0]['promotion_eligibility']=='all_customers'
                        and delivery_ok and str(rows[0].get('region_id') or 0)=='0'):
                    slots[slot].append(rows[0])
            for slot, rows in slots.items():
                if len(rows) != 1:
                    result['errors'].append('ambiguous_package')
                    continue
                accepted.append(dict(rows[0], collection_node=node))
                remaining.remove(slot)
                result['accepted'].append(slot)
        except SourceRestricted as exc:
            result['errors'].append(str(exc))
            nodes.clear()
            if node != 'local':
                nodes.append('local')
        except (OSError, ValueError, EOFError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            result['errors'].append(type(exc).__name__)
        except Exception as exc:
            result['errors'].append(type(exc).__name__)
            break
        if set(result['errors']) & {'http_401','http_403','http_429','challenge','captcha','source_access_restricted'}:
            nodes.clear()
            if node != 'local':
                nodes.append('local')
    return accepted, attempts



class SourceRestricted(ValueError):
    pass


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


def package_permit(request, *, subprocess_owned=False):
    from .client import DATABASE, utc
    from .coordinator import Coordinator
    if not DATABASE.is_file() or DATABASE.is_symlink():
        raise ValueError('collection_original_ledger_required')
    count = len({p for p, _ in request['wanted']})
    return Coordinator(DATABASE).package_requests(request['source'], request['run_id'], count, utc(),
                                                 subprocess_owned=subprocess_owned)


def wait_for_lootbar_renderer(run_id, trace):
    from contextlib import closing
    import json
    import time
    from .client import DATABASE, utc
    from .lootbar import REQUEST_BUDGET, eligible_trigger

    if not DATABASE.is_file() or DATABASE.is_symlink() or trace.stat().st_size > 1048576:
        return
    events = [json.loads(line) for line in trace.read_bytes().splitlines() if line.strip()]
    if not eligible_trigger(events):
        return
    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)) as db:
        record = db.execute("SELECT body FROM collection_sources WHERE id='Lootbar'").fetchone()
        if not record:
            return
        policy = json.loads(record[0])
        cutoff = utc().timestamp() - policy['window_seconds']
        permit = db.execute('SELECT MAX(created), SUM(count) FROM collection_permits '
                            'WHERE origin=? AND job=? AND epoch=0 AND created>?',
                            (policy['origin'], run_id, cutoff)).fetchone()
    if permit[0] is not None and permit[1] + REQUEST_BUDGET > policy['max_requests']:
        remaining = permit[0] + policy['window_seconds'] - utc().timestamp()
        if remaining > 60:
            raise ValueError('request_budget_unavailable')
        if remaining > 0:
            time.sleep(remaining)


def lootbar_primary(run_id):
    """Called under the existing Lootbar lock before opening the browser."""
    import json
    from pathlib import Path
    from .lootbar import primary_ready
    if not primary_ready():
        return 75
    wanted = [(p, q) for p in ('PS', 'XBOX', 'PC') for q in ('100', '1000')]
    request = dict(source='Lootbar', run_id=run_id, wanted=wanted)
    worker = Path(__file__).with_name('package_reader.py')
    python = '/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12'
    if not Path(python).is_file():
        return 2
    with package_permit(request, subprocess_owned=True):
        result = subprocess.run([python, '-I', '-B', str(worker)], input=json.dumps(request),
                                capture_output=True, text=True, timeout=28, check=True)
        receipt = record_restriction(request, json.loads(result.stdout))
    restricted = any(code in ('http_401','http_403','http_429','challenge','captcha') for code in receipt['errors'])
    rows = receipt['offers']
    if not rows:
        return 75 if restricted else 2
    print(json.dumps(dict(stage='public_sku_complete', read_only=True, **receipt)))
    return 0


def read_node(node, request, started):
    import json
    from datetime import timedelta
    from pathlib import Path
    from .client import source_hold_reason
    if request['source'] != 'U4GM':
        raise ValueError('package_route_source')
    if node == 'local':
        from .package_relay import request_local
        receipt = request_local(dict(request, mode='cached_u4gm'))
        if receipt.get('provider') != 'windows_u4gm_snapshot':
            raise ValueError('package_cache_receipt_scope')
        return receipt
    hold_reason = source_hold_reason(request['source'], require_registered=True)
    if hold_reason:
        raise SourceRestricted(hold_reason)
    if node == '187':
        with package_permit(request, subprocess_owned=True):
            runner = Path(__file__).with_name('package_reader.py')
            python = '/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12'
            process = subprocess.run([python,'-I','-B',str(runner)], input=json.dumps(request),
                                     text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     check=True, timeout=30)
            receipt = json.loads(process.stdout)
            try:
                return record_restriction(request, receipt)
            except (OSError, ValueError, sqlite3.Error) as exc:
                raise SourceRestricted('source_receipt_not_recorded') from exc
    from .client import ROUTING, collect_remote, read_routing_file
    source = request['source']
    routing = read_routing_file(ROUTING.with_name(source.lower()+'-routing.json'))
    if routing['remote_result_mode'] != 'consume':
        return dict(source=source, run_id=request['run_id'], offers=[],
                    errors=['collection_route_unavailable'], response_received=False)
    parent = dict(run_id=request['run_id'], created_at=started.isoformat(), deadline_at=(started+timedelta(seconds=100)).isoformat())
    receipt = collect_remote(parent, routing, source_id=source, wanted=request['wanted'])
    return dict(source=source, run_id=receipt['run_id'], offers=receipt['offers'],
                errors=receipt.get('errors', []), response_received=receipt.get('response_received'))
