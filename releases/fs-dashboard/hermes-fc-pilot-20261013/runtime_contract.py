"""Validate an inert isolation proposal; does not install or start anything."""
from copy import deepcopy
from runs_contract import PIN, WIRE_TOOLS


PLAN = {
    'schema': 'fs-hermes-isolation-proposal-v1', 'releaseReady': False,
    'source': {'repository': 'https://github.com/NousResearch/hermes-agent', **PIN},
    'python': '3.14', 'production_python_change': False,
    'identity': 'fs-hermes-fc', 'login': False, 'sudo': False,
    'read_roots': ['/opt/fs-hermes-fc/runtime', '/var/lib/fs-hermes-fc/input'],
    'write_roots': ['/var/lib/fs-hermes-fc/profile', '/var/lib/fs-hermes-fc/results'],
    'network': {'public_listeners': [], 'runtime_egress': [],
                'local_proxy': 'unix:/run/fs-hermes-fc/proxy.sock', 'approval': 'pending'},
    'provider': {'name': 'existing-bailian-deepseek', 'key_in_hermes': False,
                 'portal': False, 'stream': False, 'compatibility': 'not-tested'},
    'tools': list(WIRE_TOOLS),
    'builtin_memory_write': False, 'skill_install': False,
    'budget': {'concurrency': 1, 'rounds': 12, 'tokens': 32000, 'analysis_seconds': 600,
               'tool_seconds': 30, 'task_microcny': None, 'day_microcny': None},
    'linux_compatibility': 'not-tested', 'supervisor_stop': 'not-tested',
    'notes': 'Declarative FS proposal, NOT a native Hermes config or systemd unit.'}


def candidate():
    return deepcopy(PLAN)


def validate(plan):
    # No user-supplied paths, source refs, network expansion or implicit enablement.
    if plan != PLAN:
        raise ValueError('unreviewed_runtime_plan')
    return {'candidate_valid': True, 'launch_allowed': False,
            'blockers': ['identity_network_approval', 'money_limits_price_version',
                         'linux_runtime', 'local_proxy_transport', 'verified_token_bound',
                         'tool_discovery', 'worker_stop_and_recovery']}


def clean_environment():
    # Construct from literals instead of copying parent environ (which may contain keys).
    return {'PATH': '/opt/fs-hermes-fc/runtime/bin:/usr/bin:/bin',
            'HOME': '/var/lib/fs-hermes-fc/profile', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
