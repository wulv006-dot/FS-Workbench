"""Public IAM read projection; the original portal remains the authority for access."""
from copy import deepcopy

from .redaction import redact

from .backend import BackendError


def _fields(value, names):
    if not isinstance(value, dict):
        raise BackendError('unexpected_accounts_shape', 502)
    return {key: deepcopy(value[key]) for key in names if key in value}


def _rows(value, names):
    if not isinstance(value, list):
        raise BackendError('unexpected_accounts_shape', 502)
    return [_fields(row, names) for row in value]


def _clean(value):
    if isinstance(value, dict):
        secret = {'password', 'password_hash', 'token', 'access_token', 'refresh_token',
                  'csrf', 'csrf_token', 'cookie', 'cookies', 'session', 'sessions',
                  'session_cookie', 'authorization', 'api_key', 'secret', 'client_secret'}
        return {key: _clean(child) for key, child in value.items()
                if not key.startswith('_') and key.lower().replace('-', '_') not in secret}
    if isinstance(value, list):
        return [_clean(child) for child in value]
    return redact(value) if isinstance(value, str) else value


def project(value, view='overview'):
    if view == 'audit':
        if not isinstance(value, dict) or 'entries' not in value:
            raise BackendError('unexpected_accounts_shape', 502)
        entries = _rows(value['entries'], ('at', 'actor', 'kind', 'note', 'generation', 'revision', 'changes'))
        for entry in entries:
            entry['changes'] = _rows(entry.get('changes', []), ('op', 'role', 'subject', 'roles', 'from', 'to'))
        return _clean(dict(entries=entries))
    required = {'meta', 'members', 'policy', 'catalog', 'actions', 'resources', 'degraded'}
    if view != 'overview' or not isinstance(value, dict) or not required <= set(value):
        raise BackendError('unexpected_accounts_shape', 502)
    meta = _fields(value['meta'], ('revision', 'generation', 'updatedAt', 'updatedBy'))
    members = _rows(value['members'], ('subject', 'name', 'kind', 'source', 'groups', 'enabled', 'state',
        'roles', 'admin', 'roleLabels', 'accessCount', 'writable', 'extraGrants', 'lastLogin'))
    for member in members:
        if member.get('lastLogin') is not None:
            member['lastLogin'] = _fields(member['lastLogin'], ('at', 'ip', 'ok'))
        member['extraGrants'] = _rows(member.get('extraGrants', []), ('resources', 'actions'))
    policy = _fields(value['policy'], ('revision', 'generation', 'updatedAt', 'updatedBy', 'actor'))
    bindings = value['policy'].get('bindings', {})
    if (not isinstance(bindings, dict) or any(not isinstance(subject, str) or not isinstance(roles, list)
            or not all(isinstance(role, str) for role in roles) for subject, roles in bindings.items())):
        raise BackendError('unexpected_accounts_shape', 502)
    # Account names are values: a legitimate subject named "token" is not a secret field.
    policy['bindings'] = [dict(subject=subject, roles=deepcopy(roles)) for subject, roles in bindings.items()]
    policy['roles'] = _rows(value['policy'].get('roles', []),
        ('name', 'label', 'desc', 'super', 'rules', 'summary', 'members', 'builtin'))
    for role in policy['roles']:
        role['rules'] = _rows(role.get('rules', []), ('resources', 'actions'))
    policy['compat'] = _rows(value['policy'].get('compat', []),
        ('id', 'desc', 'methods', 'uri', 'excludeSubjectPrefix'))
    catalog = _rows(value['catalog'], ('id', 'label', 'resources'))
    for section in catalog:
        section['resources'] = _rows(section.get('resources', []), ('id', 'label', 'actions'))
    return _clean(dict(meta=meta, members=members, policy=policy, catalog=catalog,
        actions=_rows(value['actions'], ('id', 'label')),
        resources=_rows(value['resources'], ('id', 'label', 'section')), degraded=value['degraded']))
