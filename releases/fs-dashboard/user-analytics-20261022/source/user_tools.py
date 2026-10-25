"""Both Hermes paths delegate to Service; registration is a separate live integration step."""
import json

from user_contract import VIEWS, aggregate_only, POLICIES, METRIC_DEFINITIONS
from user_lifecycle import coverage_runs

PROPERTIES = {
    'section': {'type': 'string', 'enum': [*VIEWS, 'coverage']},
    'view': {'type': 'string', 'enum': list(VIEWS)},
    'scope': {'type': 'string', 'enum': ['global', 'site', 'series', 'project']},
    'scope_id': {'type': 'string'}, 'start': {'type': 'string'}, 'end_exclusive': {'type': 'string'},
    'as_of': {'type': 'string'}, 'policy_version': {'type': 'string', 'description': 'short-term-v1 uses 7/14/30 days; long-term-v1 uses 14/30/60 days. Both apply the selected thresholds to all projects. Legacy versions and frozen snapshots keep their original rules.'},
    'state_basis': {'type': 'string', 'enum': ['period_cohort','current', 'period_end'], 'description': 'Default period_cohort: only emails purchasing from start through yesterday; end is fixed by server to today 00:00 Beijing, as_of forbidden. Period first-order ES flag supplies new/old; second order and stages use that period only. current and period_end retain legacy all-history views.'},
    'policy_mode': {'type': 'string', 'enum': ['per_project', 'uniform']},
    'snapshot_id': {'type': 'string'}, 'H': {'type': 'integer', 'enum': [7, 30], 'description': 'Second-purchase observation horizon only; never the recent/silent/lost thresholds.'},
    'evidence_id': {'type': 'string'},
}
DESCRIPTION = ('Read frozen FS purchase-customer lifecycle aggregates. Default period_cohort accepts a start date, automatically ends yesterday, and includes only emails with an effective order in that period. '
               'new_purchasers/old_flag_purchasers/customer_type_unknown use the first period order ES flag, not lifetime first-purchase proof. Repeat means at least two distinct valid period orders. Waiting means one order and not yet silent; repeat buyers may later be silent/lost. '
               'Legacy current and period_end still use all covered history. Guest customers are included. '
               'Preserve coverage, partial historical pool, refund-revision limits, mature cohort denominators and versions. '
               'No customer identifiers, SQL, URLs, collection, outreach, coupon or price changes. '
               'Use the same snapshot_id to compare dashboard evidence. Return changes, supported and alternative explanations, '
               'The default compact summary omits large project/trend tables; section reads those from the same frozen snapshot without recollecting. '
               'Use the returned lifecycle_policy and metric_definitions. H is cohort observation only. Zero in a partial historical pool never proves no company-wide loss. '
               'Project tables and migration use their own project_policy_versions, not the top summary policy. Source status 86 is a code, never a refund count. '
               'A return only proves a later purchase; it cannot prove a marketing response or its cause. '
               'data gaps, an owner action, review metric and review date. Never estimate missing measured counts.')


def schema(name):
    return dict(name=name, description=DESCRIPTION,
                parameters=dict(type='object', properties=PROPERTIES, additionalProperties=False))


def invoke(service, user, args):
    if not isinstance(args, dict) or set(args) - set(PROPERTIES):
        raise ValueError('user_tool_fields')
    args = dict(args)
    section = args.pop('section', None)
    if section is not None and section not in (*VIEWS, 'coverage'):
        raise ValueError('user_tool_section')
    if 'evidence_id' in args:
        evidence = args.pop('evidence_id')
        if not isinstance(evidence, str) or len(evidence) != 35 or not evidence.startswith('ua_'):
            raise ValueError('user_evidence_id')
        snapshot = 'us_' + evidence[3:]
        if args.get('snapshot_id', snapshot) != snapshot:
            raise ValueError('user_evidence_snapshot_mismatch')
        args['snapshot_id'] = snapshot
    value = service.query(args, user)
    aggregate_only(value)
    section = section or value['query']['view']
    heavy = {'projects', 'migration', 'trend', 'cohort_weeks', 'trajectories', 'source_watermark'}
    result = {key: part for key, part in value.items() if key not in heavy}
    windows = value.get('source_watermark', [])
    runs = coverage_runs([dict(site=w['site'], start=w['start'], end=w['end_exclusive'], state=w['state']) for w in windows], sorted({w['site'] for w in windows}))
    result.update(source_coverage=[dict(site=site,start=a.isoformat(),end_exclusive=b.isoformat()) for site, intervals in runs.items() for a,b in intervals],
                  source_window_counts={state: sum(w['state']==state for w in windows) for state in ('complete','failed')})
    fields = {'summary': (), 'projects': ('projects',), 'transitions': ('migration',),
              'migration': ('migration',), 'trend': ('trend',), 'cohort': ('cohort_weeks',), 'trajectories': ('trajectories',), 'coverage': ()}[section]
    if any(key not in value for key in fields):
        raise ValueError('section_not_in_frozen_snapshot')
    result.update({key: value[key] for key in fields})
    policy = value.get('lifecycle_policy')
    if policy is None and value['policy_version'] in POLICIES:
        # These built-in v1 names retain their originally shipped definitions for old snapshots.
        policy = dict(version=value['policy_version'], thresholds_days=list(POLICIES[value['policy_version']]),
                      day_basis='Asia/Shanghai calendar days since last effective purchase', definition_source='versioned_builtin_contract')
    period_cohort = value['query'].get('state_basis') == 'period_cohort'
    result.update(lifecycle_policy=policy, metric_definitions=value.get('metric_definitions',METRIC_DEFINITIONS),
                  lifecycle_policies=value.get('lifecycle_policies', {name: list(points) for name, points in POLICIES.items()}),
                  project_policy_versions={row['project_id']: row['policy_version'] for row in value.get('projects', [])},
                  source_status_codes=dict(pay_status={'1': 'included by the confirmed effective-payment projection', '2': 'excluded'},
                                           order_status={'86': 'source partial-refund status code; not a number of orders'}),
                  interpretation=dict(H=('period first valid order + H*24h second-purchase horizon; includes ES-new and ES-old' if period_cohort else 'verified first purchase + H*24h second-purchase horizon')+'; does not set lifecycle thresholds',
                                      stock='Only purchasing emails in the selected period, ending yesterday; waiting is no repeat yet and below silence threshold. Other stages use last valid period order; previous/today orders do not enter. ES labels and lifetime first purchase are separate.' if period_cohort else 'state_basis=current uses today and all covered history; period_end uses historical cutoff. Interval dates never restrict the current customer pool. Partial history and observed zero do not prove no real churn',
                                      trend='each day recalculated from facts before its cutoff; early zero can follow short source history',
                                      high_value_entered_silent='interval entry event group; not current high-value silent stock',
                                      project_rules='project_policy_versions applies to project summaries and migration rows; top lifecycle_policy applies only to the selected summary',
                                      future_comparison='reuse one snapshot for its cards/tools; a later date or new data needs a new snapshot, preserving the old snapshot as baseline'))
    result.update(result_section=section, available_sections=[name for name, keys in (
        ('summary', ()), ('projects', ('projects',)), ('migration', ('migration',)),
        ('trend', ('trend',)), ('cohort', ('cohort_weeks',)), ('trajectories', ('trajectories',)), ('coverage', ())) if all(key in value for key in keys)])
    return result


def runtime_invoke(owner, args, detail=None):
    from user_runtime import build
    value = invoke(build(), owner, args)
    if detail is not None:
        from workspace_evidence import save
        archive = save(detail, 'user_analytics', value['query'], value)
        if archive.get('archive_id'):
            value = dict(value, workspace_archive_id=archive['archive_id'])
    return value


def research_schema():
    return dict(type='function', function=schema('mcp__fcro__fc_query_user_analytics'))


def research_call(service, owner, args):
    return invoke(service, owner, args)


def register_native(ctx, service, trusted_owner):
    # trusted_owner comes from the existing server profile, never browser request arguments.
    name = 'fs_query_user_analytics'
    def handler(args, **context):
        return json.dumps(invoke(service, trusted_owner, args), ensure_ascii=False, allow_nan=False)
    ctx.register_tool(name=name, toolset='fs_readonly', schema=schema(name), handler=handler)
