"""Both Hermes paths delegate to Service; registration is a separate live integration step."""
import json

from user_contract import VIEWS, aggregate_only

PROPERTIES = {
    'view': {'type': 'string', 'enum': list(VIEWS)},
    'scope': {'type': 'string', 'enum': ['global', 'site', 'series', 'project']},
    'scope_id': {'type': 'string'}, 'start': {'type': 'string'}, 'end_exclusive': {'type': 'string'},
    'as_of': {'type': 'string'}, 'policy_version': {'type': 'string'},
    'policy_mode': {'type': 'string', 'enum': ['per_project', 'uniform']},
    'snapshot_id': {'type': 'string'}, 'H': {'type': 'integer', 'enum': [7, 30]},
}
DESCRIPTION = ('Read frozen FS purchase-customer lifecycle aggregates. Interval purchasers, verified first/old/unknown buyers '
               'are separate from end-date recent/silent/lost/long-lost states. Guest customers are included. '
               'Preserve coverage, partial historical pool, refund-revision limits, mature cohort denominators and versions. '
               'No customer identifiers, SQL, URLs, collection, outreach, coupon or price changes. '
               'Use the same snapshot_id to compare dashboard evidence. Return changes, supported and alternative explanations, '
               'data gaps, an owner action, review metric and review date. Never estimate missing measured counts.')


def schema(name):
    return dict(name=name, description=DESCRIPTION,
                parameters=dict(type='object', properties=PROPERTIES, additionalProperties=False))


def invoke(service, user, args):
    if not isinstance(args, dict) or set(args) - set(PROPERTIES):
        raise ValueError('user_tool_fields')
    value = service.query(args, user)
    aggregate_only(value)
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
