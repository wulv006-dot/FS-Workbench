"""Named, audited FS reads; the catalog is not a general HTTP proxy."""
from copy import deepcopy
import json
from pathlib import Path
import re


class ValidationError(ValueError):
    code = 'invalid_arguments'
    status_code = 422


class CatalogPermissionError(PermissionError):
    def __init__(self, status_code=403):
        self.status_code = status_code
        self.code = 'login_required' if status_code == 401 else 'scope_denied'
        super().__init__(self.code)


class CatalogUnavailable(RuntimeError):
    code = 'authorization_unavailable'
    status_code = 503


def permit(authorize, principal, path, method):
    if not getattr(principal, 'subject', None) or not getattr(principal, 'session_cookie', None):
        raise CatalogPermissionError(401)
    try:
        status = authorize(principal, path, method)
    except CatalogPermissionError:
        raise
    except Exception:
        raise CatalogUnavailable('authorization_unavailable') from None
    if status is True or type(status) is int and status == 200:
        return
    if status is False or type(status) is int and status in (401, 403):
        raise CatalogPermissionError(401 if status == 401 else 403)
    raise CatalogUnavailable('authorization_unavailable')


def validate(arguments, schema):
    if not isinstance(arguments, dict) or set(arguments) - set(schema['properties']) or not set(schema.get('required', ())) <= set(arguments):
        raise ValidationError('invalid_arguments')
    for key, value in arguments.items():
        rule = schema['properties'][key]
        if rule['type'] == 'string':
            if not isinstance(value, str) or len(value) > rule.get('maxLength', 160) or len(value) < rule.get('minLength', 0):
                raise ValidationError('invalid_arguments')
            if 'pattern' in rule and not re.fullmatch(rule['pattern'], value):
                raise ValidationError('invalid_arguments')
            if any(ord(c) < 32 for c in value):
                raise ValidationError('invalid_arguments')
        elif rule['type'] == 'integer':
            if type(value) is not int or value < rule.get('minimum', 0) or value > rule.get('maximum', 2**53-1):
                raise ValidationError('invalid_arguments')
        elif rule['type'] == 'boolean':
            if type(value) is not bool:
                raise ValidationError('invalid_arguments')
        else:
            raise ValidationError('unsupported_schema')
        if 'enum' in rule and value not in rule['enum']:
            raise ValidationError('invalid_arguments')


class Catalog:
    def __init__(self, authorize, catalog_path=None):
        self.authorize = authorize
        self.document = json.loads(Path(catalog_path or Path(__file__).with_name('catalog.json')).read_text('utf-8'))
        self.operations = {row['name']: row for row in self.document['operations']}
        if len(self.operations) != len(self.document['operations']):
            raise ValueError('duplicate_operation')

    def operation(self, name):
        if not isinstance(name, str) or name not in self.operations:
            error = ValidationError('unknown_operation')
            error.code = 'unknown_operation'
            raise error
        return deepcopy(self.operations[name])

    def list(self, principal):
        visible = []
        checked = {}
        def allowed(path, method):
            key = (path, method)
            if key not in checked:
                try:
                    permit(self.authorize, principal, path, method)
                except CatalogPermissionError as error:
                    if error.status_code == 401:
                        raise
                    checked[key] = False
                else:
                    checked[key] = True
            return checked[key]
        for operation in self.operations.values():
            if not allowed(operation['permission_path'], operation['method']):
                continue
            visible.append({key: deepcopy(operation[key]) for key in ('name', 'module', 'description', 'input_schema', 'provenance', 'limits')})
        modules = {item['module'] for item in visible}
        return {'schema_version': 1, 'operations': visible,
                'coverage': [deepcopy(row) for row in self.document['coverage']
                    if row['module'] in modules or row.get('permission_path')
                    and allowed(row['permission_path'], 'GET')]}
