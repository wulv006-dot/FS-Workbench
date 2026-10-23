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
import json,sys
sys.path.insert(0, '/opt/fc27-collector')
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
from lootbar_server_collector import _is_product_page, load_reader
IDLE_URL='about:blank#fc27-idle'
BASE_URL='https://www.lootbar.com/game-coins/fc27'
try:
    with sync_playwright() as p:
        b=p.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=4000,no_defaults=True)
        if len(b.contexts)!=1:raise ValueError('browser_context_not_unique')
        pages=[x for x in b.contexts[0].pages if _is_product_page(x) or x.url==IDLE_URL]
        if len(pages)!=1:raise ValueError('product_page_not_unique')
        page=pages[0]
        idle=page.url==IDLE_URL
        if sys.argv[1]=='reload' and idle:
            from lootbar_server_collector import _park_product_page
            _park_product_page(page)
        elif sys.argv[1]=='reload':
            response=page.reload(wait_until='domcontentloaded',timeout=12000)
            if response is None or response.status!=200 or not _is_product_page(page):raise ValueError('product_page_refresh_failed')
            page.wait_for_function('() => { '+load_reader()+'; return readVisibleOffer().loggedIn === true; }',timeout=12000)
        if not page.evaluate('!!document.documentElement'):
            raise ValueError('browser_document_unavailable')
        if idle:
            owned=page.evaluate('url => location.href === "about:blank#fc27-idle" && document.readyState !== "loading" && document.querySelectorAll("a").length === 1 && document.querySelector("a").href === url',BASE_URL)
            session=b.new_browser_cdp_session()
            try:
                workers=[x for x in session.send('Target.getTargets')['targetInfos'] if x.get('type')=='worker' and x.get('url','').startswith('blob:https://www.lootbar.com/')]
            finally:session.detach()
            if not owned or workers:raise ValueError('owned_idle_not_verified')
        result={'status':'ok'}
except ValueError as e: result={'status':'invalid','reason':str(e)}
except BrowserTimeout: result={'status':'failed','reason':'browser_connection_timeout'}
print(json.dumps(result))
'''


def probe(action='check'):
    try:
        p = subprocess.run(['docker', 'exec', '-i', '-u', 'fc27chrome', CONTAINER,
                            'python3', '-', action], input=PROBE, text=True,
                           capture_output=True, timeout=32 if action == 'reload' else 8)
        if p.returncode:
            return {'status': 'failed', 'reason': 'browser_transport_or_page_unavailable'}
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
                outcome = reconcile_outcome(previous, current, probe()['status'])
                if outcome != 'unknown':
                    previous.update(state=outcome, reconciled_container=current)
                    if outcome != 'verified_after_unknown':
                        previous['transport_failed_at'] = datetime.now(timezone.utc).timestamp()
                    event_path = root / 'recovery-receipts' / ('browser-lifecycle-' + previous['event_id'] + '.json')
                    atomic_json(event_path, previous)
                    atomic_json(state_path, previous)
                    return {'status': 'reconciled_without_replay', 'outcome': outcome, 'event_id': previous['event_id']}
                return {'status': 'reconcile_required', 'event_id': previous.get('event_id')}
            now = datetime.now(timezone.utc).timestamp()
            health = probe()
            memory = memory_bytes()
            action = decision(previous, health['status'], memory, now)
            status = dict(status=action, checked_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                          container_usage_bytes=memory, transport=health['status'])
            if action == 'confirm_transport_failure':
                previous['transport_failed_at'] = previous.get('transport_failed_at', now)
                atomic_json(state_path, previous)
                return status
            if health['status'] != 'failed':
                previous.pop('transport_failed_at', None)
            if action not in ('reload', 'restart'):
                atomic_json(state_path, previous)
                return status
            event_id = str(uuid.uuid4())
            event_path = root / 'recovery-receipts' / ('browser-lifecycle-' + event_id + '.json')
            event = dict(previous, state='started', action=action, event_id=event_id, at=now,
                         before=status, before_container=container_state(), price_requests=0, session_deleted=False)
            atomic_json(event_path, event)
            atomic_json(state_path, event)
            try:
                if action == 'restart':
                    event['last_restart_at'] = now
                    subprocess.run(['docker', 'restart', '-t', '20', CONTAINER], check=True,
                                   timeout=45, stdout=subprocess.DEVNULL)
                result = probe('reload' if action == 'reload' else 'check')
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

