"""FS rules use the existing monitor; no business state is written here."""
import hashlib, json, os, re, stat, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen
import importlib.util

WEB = Path('/var/www/dashboard/fs-home/transactions')
BUSINESS = Path('/var/lib/fc27-cloud')
PLATFORMS = ('PS', 'XBOX', 'PC')
QUERY_SOURCE = Path('/opt/fs-query-api/query_api.py')


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone_required')
    return result


def snapshot_probe(root=WEB, at=None):
    at = at or datetime.now(timezone.utc)
    result = {'module_id': 'business-snapshot', 'status': 'unavailable', 'codes': []}
    try:
        manifest = json.loads((root/'current.json').read_text())
        identity = manifest['snapshotId']
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}', identity):
            raise ValueError('snapshot_identity_invalid')
        if manifest.get('path') != 'snapshots/'+identity+'/snapshot.json':
            raise ValueError('snapshot_path_invalid')
        path = root/manifest['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('snapshot_path_invalid')
        if path.stat().st_size > 32_000_000:
            raise ValueError('snapshot_too_large')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != manifest['sha256']:
            raise ValueError('snapshot_digest_mismatch')
        data = json.loads(body)
        if (manifest.get('schemaVersion') != 2 or data.get('schemaVersion') != 2
                or data.get('snapshotId') != identity or data.get('scope') != 'all-websites'
                or data.get('scopeContractId') != manifest.get('scopeContractId')
                or manifest.get('scopeContractId') != 'all-websites-order-primary-admin-supplement-v1'
                or data.get('currency') != 'USD' or data.get('timezone') != 'Asia/Shanghai'
                or data.get('scopeApproved') is not True):
            raise ValueError('snapshot_contract_invalid')
        profiles = data.get('profiles')
        if not profiles or set(profiles) != set(data.get('requiredProfiles', [])):
            raise ValueError('snapshot_profiles_incomplete')
        for profile in profiles.values():
            primary = profile.get('primary', {})
            if (primary.get('status') != 'available' or primary.get('system') != 'order.p2pah.cn'
                    or primary.get('period') != profile.get('period') or not primary.get('capturedAt')):
                raise ValueError('snapshot_primary_contract_invalid')
        if root == WEB:
            import sys
            sys.path.insert(0, '/opt/fs-transaction-snapshot')
            from atomic_snapshot import validate
            validate(data)  # Reuse the actual primary/supplement/profit contracts.
            result['validation_source'] = 'existing_atomic_snapshot.validate'
        age = (at-utc(manifest['generatedAt'])).total_seconds()
        if age < -60:
            raise ValueError('snapshot_clock_invalid')
        result.update(snapshot_id=identity, generated_at=manifest['generatedAt'],
                      status='stale' if age > manifest['staleAfterSeconds'] else 'live',
                      legal_snapshot_retained=True)
        if result['status'] == 'stale':
            result['codes'].append('business_snapshot_stale')
        attempt = json.loads((root/'attempt.json').read_text())
        if attempt.get('status') == 'failed':
            result['status'] = 'stale'
            result['codes'].append('business_snapshot_build_failed')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        result['status'] = 'unavailable'
        result['legal_snapshot_retained'] = False
        result['codes'] = ['business_snapshot_unverified']
        result['error_type'] = type(exc).__name__
    return result


def unknown_operations(root=BUSINESS):
    # Keep original operation IDs. Never edit executions, locks or receipts.
    rows = []
    active_operations = set()
    for path in (root/'jobs').glob('*.json'):
        row = json.loads(path.read_text())
        if row.get('status') == 'running':
            # run_id is the collection, not the writer operation.
            active_operations.update(filter(None, (row.get('job_id'),
                (row.get('request') or {}).get('execution_id'))))
    for path in (root/'executions').glob('*.json'):
        row = json.loads(path.read_text())
        operation = row.get('execution_id')
        uncertain = row.get('status') == 'UNCERTAIN'
        stopped = row.get('status') in {'RUNNING', 'PARTIAL'} and operation not in active_operations
        if uncertain or stopped:
            if not re.fullmatch(r'[0-9a-f-]{36}', operation or ''):
                raise ValueError('operation_identity_unknown')
            rows.append({'operation_id':operation, 'state':'UNKNOWN',
                         'platforms':row.get('selected', list(PLATFORMS))})
    return rows


def read_catalog():
    if not QUERY_SOURCE.is_file():
        return None
    spec = importlib.util.spec_from_file_location('fs_query_monitor_reader', QUERY_SOURCE)
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)
    if provider.VERSION != 'fs-query-v1-20261012':
        return None
    # Reuse the authorized server consumer's metadata-only call; no new identity or business query.
    return provider.snapshot()


def dashboard_probe(root=WEB):
    try:
        catalog = read_catalog()
        if catalog is None:
            return snapshot_probe(root)
        profiles = catalog.get('profiles')
        if (catalog.get('schemaVersion') != 2 or
                not re.fullmatch(r'catalog-[a-f0-9]{16}', catalog.get('catalogId', '')) or
                catalog.get('snapshotId') != catalog.get('catalogId') or
                catalog.get('scopeContractId') != 'all-websites-order-primary-admin-supplement-v1' or
                catalog.get('timezone') != 'Asia/Shanghai' or catalog.get('currency') != 'USD' or
                catalog.get('dataPolicy') != 'metadata-only; native values are queried by date' or
                not isinstance(profiles, dict) or not 1 <= len(profiles) <= 200 or
                any(not isinstance(p, dict) or p.get('primary', {}).get('status') != 'not_provided' or
                    p.get('metrics') != {} or p.get('dimensions') != {} for p in profiles.values())):
            raise ValueError('metadata_catalog_contract_invalid')
        historical = snapshot_probe(root)
        return {'module_id':'business-range', 'status':'queryable', 'codes':[],
                'catalog_id':catalog['catalogId'], 'profile_count':len(profiles),
                'data_freshness':'not_observed_no_business_query', 'semantic_queries_verified':False,
                'legal_snapshot_retained':historical.get('legal_snapshot_retained') is True,
                'historical_snapshot':dict(historical, historical_only=True)}
    except Exception as exc:
        return {'module_id':'business-range', 'status':'unavailable',
                'codes':['business_snapshot_unverified'], 'error_type':type(exc).__name__,
                'data_freshness':'not_observed_no_business_query'}


def extend_report(value, range_url='http://127.0.0.1:8931/health', snapshot_root=WEB, business_root=BUSINESS):
    dashboard = dashboard_probe(snapshot_root)
    value['dashboard'] = dashboard
    value['issues'].extend({'level':'critical', 'code':code} for code in dashboard['codes'])
    try:
        with urlopen(range_url, timeout=3) as response:
            health = json.loads(response.read(4096))
        if (not isinstance(health, dict) or health.get('ok') is not True
                or health.get('service') != 'fs-business-range'
                or health.get('readonly') is not True):
            raise ValueError('range_semantics_invalid')
        value['exact_range'] = {'status':'read_path_verified', 'semantic_queries_verified':False}
    except Exception as exc:
        value['exact_range'] = {'status':'unavailable', 'error_type':type(exc).__name__}
        value['issues'].append({'level':'critical','code':'exact_range_health_unavailable'})
    try:
        value['unknown_operations'] = unknown_operations(business_root)
    except Exception as exc:
        value['unknown_operations'] = None
        value['issues'].append({'level':'critical','code':'original_operation_state_unavailable'})
    job = value.get('coin', {}).get('job') or {}
    if job.get('status') == 'running':
        try:
            age = (datetime.now(timezone.utc)-utc(job['started_at'])).total_seconds()
            # Existing auto-cycle child budgets: collection, public read, quote,
            # preview, writer, cache, post-write public read. No process is killed.
            budget = 440+95+15+85+130+175+95
            if age < -60 or age > budget:
                value['issues'].append({'level':'critical','code':'coin_job_deadline_exceeded'})
        except (KeyError, TypeError, ValueError):
            value['issues'].append({'level':'critical','code':'coin_job_start_unverified'})
    value['status'] = ('critical' if any(x['level']=='critical' for x in value['issues'])
                       else 'warning' if value['issues'] else 'healthy')
    return value


def bot_ready(config=Path('/etc/fc-ops-readonly-monitor/hooks-bot.json'),
              receipt=Path('/var/lib/fc-ops-readonly-monitor/bot-acceptance.json')):
    # Readiness is bound to the credential actually accepted and received.
    try:
        from hooks_notifier import load_bot
        load_bot(config)
        meta=receipt.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid!=0 or meta.st_mode&0o077
                or meta.st_nlink!=1 or meta.st_size>8192):return False
        proof=json.loads(receipt.read_text(encoding='utf-8'))
        return (proof.get('provider_accepted') is True and proof.get('group_receipt')=='both_received'
                and proof.get('config_sha256')==hashlib.sha256(config.read_bytes()).hexdigest())
    except (OSError,ValueError,KeyError,TypeError):return False


def controls(value, previous=None, at=None):
    previous = previous or {}
    at = at or datetime.now(timezone.utc)
    coin = value.get('coin', {})
    cfg = coin.get('config', {})
    user_enabled = cfg.get('system_enabled') is True and cfg.get('mode') == 'auto'
    reasons = {p:[] for p in PLATFORMS}
    codes = {row['code'] for row in value.get('issues', [])}
    # These are FC dependencies. Dashboard/gallery errors do not suspend FC writers.
    shared = {'api_unhealthy_or_unknown', 'worker_unhealthy_or_unknown',
              'browser_unhealthy_or_unknown', 'p2pah_session_unhealthy_or_unknown',
              'automation_timer_inactive_or_unknown', 'source_coverage_unverified',
              'collection_stale_or_clock_invalid', 'collection_time_unverified',
              'original_operation_state_unavailable', 'collection_unavailable',
              'latest_coin_job_failed', 'latest_coin_all_proof_unverified',
              'coin_job_deadline_exceeded', 'coin_job_start_unverified',
              'service_unavailable:fc27-cloud-api.service',
              'service_unavailable:fc27-cloud-worker.service',
              'service_unavailable:fc27-gate.service',
              'service_unavailable:coin_api_http_gate',
              'service_unavailable:gallery_api_http_gate'}
    for platform in PLATFORMS:
        reasons[platform].extend(sorted(codes & shared))
        reasons[platform].extend(sorted({row['code'] for row in value.get('issues', [])
            if row.get('platform') == platform and row.get('level') == 'critical'
            and row.get('code', '').startswith('coin_v3_curve_')}))
        if not user_enabled:
            reasons[platform].append('user_disabled_or_not_auto')
    publication = value.get('publication', {})
    publication_rows = {row.get('platform'):row for row in publication.get('platforms', [])}
    v3_enabled=(value.get('v3') or {}).get('enabled') is True
    for platform in PLATFORMS:
        observed=publication_rows.get(platform, {}).get('status')
        # Public observation is independent of V3 writer completion.
        # A comparable mismatch still blocks the affected platform.
        if observed=='mismatch' or not v3_enabled and observed!='matched':
            reasons[platform].append('published_price_unverified')
    if not v3_enabled and 'three_platform_publication_unverified' in codes and not publication.get('platforms'):
        for platform in PLATFORMS:
            reasons[platform].append('published_price_unverified')
    for operation in value.get('unknown_operations') or []:
        for platform in operation['platforms']:
            if platform in reasons:
                reasons[platform].append('unknown_operation:'+operation['operation_id'])
    states = {}
    job_id = (coin.get('job') or {}).get('job_id')
    job = coin.get('job') or {}
    job_result = job.get('result_status') if v3_enabled else job.get('result')
    for platform in PLATFORMS:
        old = previous.get('platforms', {}).get(platform, {})
        same_policy = previous.get('policy_revision') == cfg.get('revision')
        clean = 0 if reasons[platform] else min(2, old.get('clean_observations', 0)+1) if same_policy else 1
        system_pause = bool(old.get('reasons')) and old.get('pause_source') == 'system_fault'
        recovery_from = ({'reasons':list(reasons[platform]), 'observed_at':at.isoformat()}
                         if reasons[platform] else old.get('recovery_from') if system_pause else None)
        ready = can_resume(user_intent='ENABLED' if user_enabled else 'DISABLED',
                           pause_source=old.get('pause_source'), revision_current=same_policy,
                           dependencies_verified=not reasons[platform],
                           unknown_operations=value.get('unknown_operations'),
                           business_safe=not reasons[platform], authorized=True)
        if not reasons[platform] and system_pause and (clean < 2 or not ready):
            reasons[platform] = ['recovery_confirmation_pending']
        phase = ('ESCALATED' if 'published_price_unverified' in reasons[platform]
                 else 'CONTAINED' if reasons[platform] else 'OBSERVING')
        resume_after = old.get('resume_after_job_id')
        if not reasons[platform] and system_pause:
            phase, resume_after = 'AWAITING_CYCLE', job_id
        elif not reasons[platform] and old.get('phase') == 'AWAITING_CYCLE':
            phase = ('RECOVERED' if job_id != resume_after and job_result in {'confirmed','no_price_change'}
                     else 'AWAITING_CYCLE')
        elif not reasons[platform] and old.get('phase') == 'RECOVERED':
            phase = 'RECOVERED'
        states[platform] = {'containment_scope':'automatic_writes_only',
                            'sales_protection_status':'UNAVAILABLE' if 'published_price_unverified' in reasons[platform] else 'not_invoked',
                            'reasons':reasons[platform], 'clean_observations':clean, 'phase':phase,
                            'recovery_from':recovery_from if reasons[platform] else None,
                            'resume_after_job_id':resume_after,
                            'pause_source':'system_fault' if user_enabled else 'user_intent'}
    changed = states != previous.get('platforms') or cfg.get('revision') != previous.get('policy_revision')
    return {'schema_version':1, 'module_id':'fc-coins', 'mode':'RULES_ARMED',
            'revision':previous.get('revision', 0)+int(changed), 'observed_at':at.isoformat(),
            'valid_until':(at+timedelta(minutes=15)).isoformat(), 'policy_revision':cfg.get('revision'),
            'user_intent':'ENABLED' if user_enabled else 'DISABLED', 'platforms':states,
            'unknown_operations':value.get('unknown_operations'),
            'safe_sales_adapter_ready':False, 'headless_agent_ready':False,
            'bot_delivery_ready':bot_ready()}


def persist_controls(directory, value):
    path = directory/'gates/control.json'
    previous = None
    if path.exists():
        previous = json.loads(path.read_text())  # Corrupt state must not reset a pause.
    control = controls(value, previous)
    body = json.dumps(control, sort_keys=True).encode()
    if len(body) > 32768:
        raise ValueError('control_size_exceeded')
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.control-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
        if os.name == 'posix':
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    value['hook_control'] = {k:control[k] for k in ('revision','mode','platforms','user_intent')}
    return control

def can_resume(*, user_intent, pause_source, revision_current, dependencies_verified,
               unknown_operations, business_safe, authorized):
    """Shared pure interface. RPG supplies its own contracts, writer and scopes."""
    return (user_intent == 'ENABLED' and pause_source == 'system_fault'
            and revision_current is True and dependencies_verified is True
            and unknown_operations == [] and business_safe is True and authorized is True)
