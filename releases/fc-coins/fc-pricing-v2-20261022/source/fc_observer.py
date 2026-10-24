"""Project existing Coins ledgers for the dedicated read-only observation identity."""
import re


JOB_KINDS = {'auto_cycle', 'collect', 'execute', 'restore', 'recalculate',
             'preview', 'hermes_review'}
IDS = ('job_id', 'run_id', 'execution_id', 'preview_id', 'request_id', 'turn_id',
       'task_id', 'conversation_id')
TIMES = ('created_at', 'started_at', 'completed_at', 'checked_at', 'updated_at')
STATUS = ('status', 'phase', 'kind', 'applied', 'price_write_performed')


def pick(value, keys):
    # Never forward a new nested field added by a future job/model producer.
    if not isinstance(value, dict):
        return {}
    return {k: value[k] for k in keys if k in value
            and (value[k] is None or isinstance(value[k], (str, bool, int, float)))}


def platforms(value):
    return [p for p in value if p in ('PS', 'XBOX', 'PC')] if isinstance(value, list) else []


def review(value):
    result = pick(value, IDS + TIMES + STATUS)
    result['turn'] = pick((value or {}).get('turn'), ('id', 'state') + IDS)
    return result


def job(value):
    result = pick(value, IDS + TIMES + STATUS)
    result['result'] = pick(value.get('result'), IDS + ('status', 'quote_status'))
    result['hermes_review'] = review(value.get('hermes_review'))
    result['snapshot'] = pick(value.get('snapshot'), ('run_id', 'status', 'valid_competitors',
                                                   'valid_costs', 'fx_status', 'quote_status'))
    result['reconciliation'] = pick(value.get('reconciliation'), ('status', 'checked_at', 'sync_confirmed'))
    result['do_not_replay'] = True
    for key in ('unchanged_platforms', 'platforms'):
        result[key] = platforms(value.get(key))
    return result


def automation(value):
    result = pick(value, ('system_enabled', 'mode', 'interval_minutes',
                         'minimum_gross_margin_pct', 'revision', 'schedule_revision') + TIMES)
    result['platforms'] = platforms(value.get('platforms'))
    result['schedule'] = pick(value.get('schedule'), ('status', 'collection_status',
                             'last_job_id', 'last_status', 'last_result', 'next_at'))
    result['can_edit_discount_rules'] = False
    return result


def publication(value):
    result = pick(value, ('status', 'basis', 'write_mode', 'backend_checked_at',
                         'backend_written_at') + IDS)
    result['platforms'] = [pick(row, ('platform', 'status', 'backend_page_usd',
                                    'public_page_usd', 'public_checked_at'))
                           for row in value.get('platforms', []) if isinstance(row, dict)]
    return result


def quote(value):
    value = value or {}
    result = pick(value, IDS + TIMES + ('status', 'automation_policy_revision',
                  'snapshot_sha256', 'quote_engine_sha256', 'pricing_rules_sha256'))
    evidence = value.get('evidence') or {}
    result['source_checked_at'] = pick(evidence, ('checked_at',)).get('checked_at')
    result['costs'] = {p: pick((evidence.get('costs') or {}).get(p),
                     ('platform', 'record_id', 'trade_at', 'traded_at', 'cny_per_k',
                      'cny_per_1k', 'unit', 'status', 'checked_at', 'run_id'))
                       for p in ('PS', 'XBOX', 'PC')}
    result['fx'] = pick(evidence.get('fx'), ('status', 'cny_per_usd', 'published_at', 'checked_at'))
    numeric = ('platform', 'status', 'raw_cost_cny', 'cost_cny', 'cost_record_id',
               'cost_trade_at', 'proposal', 'auto_proposal', 'target_page_usd',
               'floor_usd_per_1k', 'gross_margin_pct', 'minimum_gross_margin_pct',
               'margin_below_minimum', 'profit_floor_applied', 'strategy_version',
               'own_bonus_k', 'lootbar_page_usd', 'main_page_usd', 'anchor_page_usd',
               'change_pct', 'break_even_order_multiplier', 'margin_basis')
    computed = value.get('result') or {}
    result['rows'] = [pick(row, numeric) for row in computed.get('rows', [])]
    for target,row in zip(result['rows'],computed.get('rows', [])):
        avg=row.get('estimated_average_margin') or {}
        target['estimated_average_margin']=pick(avg,('status','reason','observed_orders','eligible_orders','retained_ratio',
            'estimated_net_usd','estimated_procurement_gross_usd','procurement_margin_pct','scope','historical_mix_sha256'))
        target['estimated_average_margin']['period']=pick(avg.get('period'),('start','end'))
    result['decision_receipt'] = pick(computed.get('decision_receipt'),
           ('strategy_version', 'reference_version', 'reference_weights', 'hard_minimum_margin_pct', 'historical_average_minimum_margin_pct', 'minimum_retained_ratio', 'margin_basis',
            'promotions_exempt_from_margin_floor', 'historical_discount_mix_sha256',
            'promotion_envelope_sha256', 'code_sha256', 'sha256'))
    return result


def read_observation(api, parsed):
    """Read only the existing ledgers; no refresh, tasks, model calls or writes."""
    path = parsed.path
    if parsed.query or parsed.fragment:
        return 403, {'error': 'observer_read_scope_required'}
    try:
        if path == '/automation':
            result = automation(api.automation_view(api.load_policy(), 'dot_fc_observer'))
        elif path == '/monitor':
            value = api.monitor_view()
            result = pick(value, ('generated_at',))
            result['publication'] = publication(value.get('publication') or {})
            result['latest_attempt'] = pick(value.get('latest_attempt'), IDS + TIMES + ('status',))
            result['health'] = pick(value.get('health'), ('api', 'worker', 'queue_depth',
                                       'incomplete_executions', 'automation_timer'))
            result['automation'] = automation(value.get('automation') or {})
        elif path == '/pricing/state':
            from pricing_state import state
            value = state(root=api.ROOT, owner=None)
            result = pick(value, ('version', 'observed_at', 'hard_minimum_margin_pct',
                                 'execution_ready', 'quote_usable', 'effect_status'))
            result['quote'] = quote(value.get('quote'))
            result['recent'] = [job(row) for row in value.get('recent', [])
                                if row.get('kind') in JOB_KINDS]
        elif re.fullmatch(r'/jobs/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', path):
            job_id = path.rsplit('/', 1)[1]
            file = api.ROOT / 'jobs' / (job_id + '.json')
            if not file.exists():
                file = api.ROOT / 'queue' / (job_id + '.json')
            if not file.exists():
                return 404, {'error': 'not_found'}
            value = api.read_json(file)
            if value.get('job_id') != job_id or value.get('kind') not in JOB_KINDS:
                return 403, {'error': 'observer_job_scope_required'}
            result = job(value)
        else:
            return 403, {'error': 'observer_read_scope_required'}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return 503, {'error': 'observer_state_unavailable'}
    return 200, dict(result, observation_schema='fc-observer-v1', observer_can_execute=False)
