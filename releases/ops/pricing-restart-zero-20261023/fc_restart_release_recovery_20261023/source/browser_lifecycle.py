"""Bound the existing FC browser while idle; never enqueue or repeat prices."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess
import uuid

CONTAINER = 'fc27-cloud-browser'
MEMORY_LIMIT = 1536 * 1024 * 1024
ORDER_ISOLATION = Path('/var/lib/fs-order-session/browser-isolation-20261023.json')
ORDER_SERVICE = Path('/opt/fs-order-session/service.py')
PROBE = r'''
import json,sys,os
sys.path.insert(0, '/opt/fc27-collector')
os.environ['FC27_CDP_ENDPOINT']='http://127.0.0.1:9225'
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
from lootbar_server_collector import _is_product_page, load_reader
IDLE_URL='about:blank#fc27-idle'
BASE_URL='https://www.lootbar.com/game-coins/fc27'
stage='playwright_start'
try:
    with sync_playwright() as p:
        stage='connect_over_cdp'
        b=p.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=4000,no_defaults=True)
        stage='page_identity'
        if len(b.contexts)!=1:raise ValueError('browser_context_not_unique')
        pages=[x for x in b.contexts[0].pages if _is_product_page(x) or x.url==IDLE_URL]
        if len(pages)!=1:raise ValueError('product_page_not_unique')
        page=pages[0]
        idle=page.url==IDLE_URL
        if sys.argv[1] in ('reload','release') and not idle:
            stage='release_product_document'
            import time
            from lootbar_server_collector import _release_product_document
            _release_product_document(page,deadline=time.monotonic()+6)
            # HTTP release already proved the old target gone; its Playwright close event may lag.
            pages=[x for x in b.contexts[0].pages if x.url==IDLE_URL]
            if len(pages)!=1:raise ValueError('idle_release_identity_unverified')
            page=pages[0]
            idle=True
        stage='document_readback'
        if not page.evaluate('!!document.documentElement'):
            raise ValueError('browser_document_unavailable')
        if idle:
            stage='owned_idle_worker_readback'
            owned=page.evaluate('url => location.href === "about:blank#fc27-idle" && document.readyState !== "loading" && document.querySelectorAll("a").length === 1 && document.querySelector("a").href === url',BASE_URL)
            session=b.new_browser_cdp_session()
            try:
                targets=session.send('Target.getTargets')['targetInfos']
                workers=[x for x in targets if x.get('type')=='worker' and x.get('url','').startswith('blob:https://www.lootbar.com/')]
                if sys.argv[1] in ('reload','release') and any(x.get('type')=='page' and x.get('url','').split('?')[0].rstrip('/')==BASE_URL for x in targets):
                    raise ValueError('product_target_release_unverified')
            finally:session.detach()
            if not owned or workers:raise ValueError('owned_idle_not_verified')
        result={'status':'ok'}
except ValueError as e: result={'status':'invalid','reason':str(e)}
except BrowserTimeout: result={'status':'failed','reason':'browser_connection_timeout:'+stage}
except Exception as e: result={'status':'failed','reason':'browser_probe_'+stage+':'+type(e).__name__}
print(json.dumps(result))
'''


def probe(action='check'):
    try:
        check = action == 'check'
        program = Path(__file__).with_name('browser_probe.js').read_text('utf-8') if check else PROBE
        command = (['/usr/local/lib/python3.10/dist-packages/playwright/driver/node', '-', '--fc-health'] if check else
                   ['python3', '-', action])
        p = subprocess.run(['docker', 'exec', '-i', '-u', 'fc27chrome', CONTAINER,
                            'timeout', '--kill-after=1s', '6s' if check else '13s'] + command,
                           input=program, text=True,
                           capture_output=True, timeout=16 if action in ('reload', 'release') else 8)
        if p.returncode:
            return {'status': 'failed', 'reason': 'browser_transport_or_page_unavailable'}
        if not p.stdout.splitlines():
            return {'status': 'failed', 'reason': 'browser_probe_empty_reply'}
        value = json.loads(p.stdout.splitlines()[-1])
        if (not isinstance(value, dict) or value.get('status') not in ('ok', 'invalid', 'failed')
                or set(value) != ({'status'} if value['status'] == 'ok' else {'status', 'reason'})):
            raise ValueError('browser_probe_contract')
        return value
    except subprocess.TimeoutExpired:
        return {'status': 'failed', 'reason': 'browser_connection_timeout'}


def memory_bytes():
    # shortcut: this host uses cgroup v1; adapt this reader before an OS migration.
    cid = subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', CONTAINER],
                                  text=True, timeout=5).strip()
    if len(cid) != 64 or any(c not in '0123456789abcdef' for c in cid):
        raise ValueError('browser_container_identity')
    return int((Path('/sys/fs/cgroup/memory/docker') / cid / 'memory.usage_in_bytes').read_text())


def decision(previous, health, memory, now):
    if previous.get('state') in ('started', 'unknown'):
        return 'reconcile_required'
    if health == 'invalid':
        return 'browser_identity_requires_review'
    if health != 'ok':
        first = previous.get('transport_failed_at')
        if first is None or now - first < 30:
            return 'confirm_transport_failure'
        return 'restart' if now - previous.get('last_restart_at', -3600) >= 3600 else 'restart_cooldown'
    if memory < MEMORY_LIMIT:
        return 'healthy'
    if previous.get('action') == 'reload' and previous.get('state') == 'verified' and now - previous['at'] <= 300:
        return 'restart' if now - previous.get('last_restart_at', -3600) >= 3600 else 'restart_cooldown'
    return 'reload'


def container_state():
    template = ('{"id":{{json .Id}},"restart_count":{{.RestartCount}},'
                '"started_at":{{json .State.StartedAt}},"running":{{.State.Running}},'
                '"restarting":{{.State.Restarting}}}')
    return json.loads(subprocess.check_output(['docker','inspect','--format',template,CONTAINER],
                                             text=True, timeout=5))


def reconcile_outcome(previous, current, health):
    if health == 'ok':
        return 'verified_after_unknown'
    before = previous.get('before_container', {})
    if (previous.get('action') == 'restart' and current.get('id') == before.get('id')
            and current.get('started_at') != before.get('started_at')
            and current.get('running') is True and not current.get('restarting')):
        return 'failed_after_restart'
    if previous.get('action') == 'reload':
        return 'failed_readonly_reload'
    return 'unknown'


def release_required(previous, current):
    before = previous.get('before_container', {})
    released = previous.get('idle_release', {})
    return (previous.get('action') == 'restart' and bool(previous.get('event_id'))
            and bool(before.get('id')) and current.get('id') == before.get('id')
            and bool(current.get('started_at')) and current['started_at'] != before.get('started_at')
            and current.get('running') is True and current.get('restarting') is False
            and released != {'container_id': current['id'], 'started_at': current['started_at'],
                             'event_id': previous['event_id']})


def release_restart(previous, current):
    result = probe('release')
    if result['status'] == 'ok':
        previous['idle_release'] = {'container_id': current['id'], 'started_at': current['started_at'],
                                    'event_id': previous['event_id']}
        previous['idle_release_verified_at'] = datetime.now(timezone.utc).isoformat()
    else:
        previous['idle_release_failure'] = result.get('reason', 'browser_release_unverified')
    return result


def maintain():
    import fcntl
    import automation_tick as tick
    import fc27_cloud_api as api
    import local_collection
    from snapshot_layer import atomic_json

    root = tick.ROOT
    policy = tick.load_policy()
    if not policy['system_enabled'] or policy['mode'] != 'auto' or local_collection.config()['mode'] != 'server':
        return {'status': 'not_applicable'}
    try:
        with tick.queue_mutation(), ExitStack() as held:
            for name in tick.RETRY_LOCKS:
                lock = held.enter_context((root / 'state' / name).open('rb'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if (tick.retry_guard() != 'ready' or list((root / 'queue').glob('*.json'))
                    or api.health()['incomplete_executions']
                    or any(json.loads(p.read_text()).get('status') in ('queued', 'running')
                           for p in (root / 'jobs').glob('*.json'))):
                return {'status': 'busy'}
            isolation = json.loads(ORDER_ISOLATION.read_text()) if ORDER_ISOLATION.exists() else {}
            if (isolation.get('status') != 'verified' or isolation.get('durability_verified') is not True
                    or isolation.get('container') != 'fs-order-browser'
                    or isolation.get('service_sha256') != hashlib.sha256(ORDER_SERVICE.read_bytes()).hexdigest()):
                return {'status': 'order_browser_isolation_required'}
            state_path = root / 'state/browser-lifecycle.json'
            previous = json.loads(state_path.read_text()) if state_path.exists() else {}
            if previous.get('state') in ('started', 'unknown'):
                current = container_state()
                health = probe()
                if health['status'] == 'ok' and release_required(previous, current):
                    health = release_restart(previous, current)
                outcome = reconcile_outcome(previous, current, health['status'])
                if outcome != 'unknown':
                    previous.update(state=outcome, reconciled_container=current,
                                    reconciled_at=datetime.now(timezone.utc).isoformat())
                    if outcome != 'verified_after_unknown':
                        previous['transport_failed_at'] = datetime.now(timezone.utc).timestamp()
                    event_path = root / 'recovery-receipts' / ('browser-lifecycle-' + previous['event_id'] + '.json')
                    atomic_json(event_path, previous)
                    atomic_json(state_path, previous)
                    return {'status': 'reconciled_without_replay', 'outcome': outcome, 'event_id': previous['event_id']}
                return {'status': 'reconcile_required', 'event_id': previous.get('event_id')}
            now = datetime.now(timezone.utc).timestamp()
            health = probe()
            current = container_state()
            if health['status'] == 'ok' and release_required(previous, current):
                health = release_restart(previous, current)
                atomic_json(root / 'recovery-receipts' / ('browser-lifecycle-' + previous['event_id'] + '.json'), previous)
                atomic_json(state_path, previous)
                return {'status': 'restart_idle_verified' if health['status'] == 'ok' else 'restart_idle_unverified',
                        'event_id': previous['event_id'], 'transport': health['status']}
            memory = memory_bytes()
            action = decision(previous, health['status'], memory, now)
            status = dict(status=action, checked_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                          container_usage_bytes=memory, transport=health['status'])
            if action == 'confirm_transport_failure':
                previous['transport_failed_at'] = previous.get('transport_failed_at', now)
                previous['transport_failure'] = health
                atomic_json(state_path, previous)
                return status
            if health['status'] != 'failed':
                previous.pop('transport_failed_at', None)
            if action not in ('reload', 'restart'):
                atomic_json(state_path, previous)
                return status
            event_id = str(uuid.uuid4())
            event_path = root / 'recovery-receipts' / ('browser-lifecycle-' + event_id + '.json')
            event = dict(state='started', action=action, event_id=event_id, at=now,
                         last_restart_at=previous.get('last_restart_at', -3600),
                         transport_failure=previous.get('transport_failure', health),
                         before=status, before_container=container_state(), price_requests=0, session_deleted=False)
            atomic_json(event_path, event)
            atomic_json(state_path, event)
            try:
                if action == 'restart':
                    event['last_restart_at'] = now
                    subprocess.run(['docker', 'restart', '-t', '20', CONTAINER], check=True,
                                   timeout=45, stdout=subprocess.DEVNULL)
                result = probe('reload') if action == 'reload' else release_restart(event, container_state())
                if result['status'] != 'ok':
                    raise RuntimeError(result.get('reason', 'browser_recovery_unverified'))
                event.update(state='verified', after_memory_bytes=memory_bytes())
                event.pop('transport_failed_at', None)
            except Exception as error:
                event.update(state='unknown', error=type(error).__name__)
                raise
            finally:
                atomic_json(event_path, event)
                atomic_json(state_path, event)
            return dict(status, status='verified', action=action, event_id=event_id)
    except BlockingIOError:
        return {'status': 'busy'}

