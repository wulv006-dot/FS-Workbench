"""Pure, allowlisted reports. No credentials, raw API errors or sale prices."""
from datetime import datetime, timezone

def pick(value, keys):
    return {key: value.get(key) for key in keys}

def report(snapshot, assessment, services, evidence):
    health = snapshot.get('health', {})
    issues = list(assessment['issues'])
    for unit, state in services.items():
        if state != 'active':
            issues.append({'level': 'critical', 'code': 'service_unavailable:' + unit})
    job = evidence.get('coin', {})
    all_record = evidence.get('all', {})
    player = evidence.get('player', {})
    if job.get('status') == 'failed':
        issues.append({'level':'critical', 'code':'latest_coin_job_failed'})
    if job.get('result') == 'confirmed':
        steps = all_record.get('steps', [])
        if (all_record.get('status') != 'confirmed' or len(steps) != 3
                or {s.get('platform') for s in steps} != {'PS', 'XBOX', 'PC'}
                or any(s.get('status') != 'confirmed' for s in steps)):
            if job.get('order_public_confirmed_without_all') is True and not all_record.get('status'):
                issues.append({'level':'warning', 'code':'all_auth_deferred_before_dispatch'})
            else:
                issues.append({'level':'critical', 'code':'latest_coin_all_proof_unverified'})
        if job.get('player_expected'):
            if not job.get('player_job_id'):
                issues.append({'level':'critical', 'code':'player_dispatch_unverified'})
            elif player.get('request_price_check_waived') is True:
                pass  # Exact retired-check exception, supplied by the active runtime rule.
            elif player.get('status') not in {'confirmed'}:
                issues.append({'level':'critical', 'code':'linked_player_not_confirmed'})
            elif (player.get('coin_execution_id') != (job.get('execution_id') or all_record.get('execution_id'))
                  or player.get('category_response') != 'accepted'):
                issues.append({'level':'critical', 'code':'linked_player_request_proof_unverified'})
    # Disabled by the user is observed, never repaired; nochange needs no dispatch.
    status = 'critical' if any(i['level'] == 'critical' for i in issues) else 'warning' if issues else 'healthy'
    auto = snapshot.get('automation', {})
    gallery = snapshot.get('gallery', {})
    if auto.get('system_enabled') is False or auto.get('mode') == 'manual':
        issues.append({'level':'warning', 'code':'coin_automation_disabled_or_manual'})
    latest_gallery = next(iter(gallery.get('recent_jobs', [])), {})
    if latest_gallery.get('status') == 'failed':
        issues.append({'level':'critical', 'code':'latest_gallery_job_failed'})
    status = 'critical' if any(i['level'] == 'critical' for i in issues) else 'warning' if issues else 'healthy'
    return {'schema_version': 1, 'captured_at': snapshot['captured_at'], 'status':status,
            'issues':issues, 'service_states':services, 'gateway':snapshot.get('gateway', {}),
            'health':pick(health, ('worker','browser','p2pah_session','automation_timer','queue_depth',
                                   'incomplete_executions','disk_free_gb','sources','https_certificate')),
            'coin': {'config':pick(auto, ('system_enabled','mode','interval_minutes','revision')),
                     'schedule':pick(auto.get('schedule', {}), ('status','collection_status','last_job_id',
                                                               'last_status','last_result','next_at')),
                     'collection':snapshot.get('monitor', {}).get('latest_collection', {}),
                     'latest_attempt':pick(snapshot.get('monitor', {}).get('latest_attempt') or {},
                                           ('run_id','status','created_at')),
                     'job':job, 'all_proof':all_record},
            'player': {'config':pick(snapshot.get('player_sync', {}), ('enabled','revision','updated_at','price_verification')),
                       'linked_job':player},
            'gallery': {'config':pick(gallery.get('config', {}), ('revision','updated_at')),
                        'pause_present':bool(gallery.get('config', {}).get('pause_reason')),
                        'settings':gallery.get('settings', {}), 'blocked':gallery.get('blocked'),
                        'latest':gallery.get('latest', {}), 'schedule':gallery.get('schedule', {})},
            'publication':snapshot.get('publication', {}), 'thresholds':assessment.get('thresholds', {}),
            'evidence_scope':'existing_business_readbacks_and_ledgers; no fresh authenticated goods reads',
            'delivery': {'state':'not_configured', 'delivered':False}}

def unverified(error_type):
    return {'schema_version':1, 'captured_at':datetime.now(timezone.utc).isoformat(),
            'status':'unverified', 'issues':[{'level':'critical', 'code':'collection_unavailable'}],
            'error_type':error_type, 'delivery':{'state':'not_configured','delivered':False}}

def reader_health(latest, now):
    """For an independent reader; a saved healthy snapshot expires after 15 min."""
    try:
        age = (now - datetime.fromisoformat(latest['finished_at'].replace('Z','+00:00'))).total_seconds()
        if not -60 <= age <= 900:
            return 'monitor_stale_or_clock_invalid'
        return latest['status'] if latest['status'] in {'healthy','warning','critical','unverified'} else 'monitor_unavailable'
    except (KeyError, TypeError, ValueError):
        return 'monitor_unavailable'
