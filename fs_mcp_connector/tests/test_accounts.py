from copy import deepcopy
import json
import unittest

from fs_mcp_connector.accounts import project
from fs_mcp_connector.backend import Backend, BackendError
from fs_mcp_connector.catalog import Catalog, CatalogPermissionError, ValidationError
from fs_mcp_connector.portal import Principal


class AccountsTests(unittest.TestCase):
    def overview(self):
        return dict(meta=dict(revision='revision-1', generation=3, updatedAt='2026-11-09', updatedBy='alice', path='/private/policy.json'),
            members=[dict(subject='alice', name='Alice', kind='native', source='existing account', groups=['dashboard'],
                enabled=True, state='active', roles=['Manager'], admin=True, roleLabels=['Manager'], accessCount=2,
                writable=['users'], extraGrants=[dict(resources=['users'], actions=['view'])],
                lastLogin=dict(at='2026-11-09', ip='127.0.0.1', ok=True), password='must-not-leak')],
            policy=dict(actor='alice', revision='revision-1', generation=3, updatedAt='2026-11-09', updatedBy='alice',
                roles=[dict(name='Manager', label='Manager', desc='existing role', super=False,
                    rules=[dict(resources=['users'], actions=['view', 'manage'], token='must-not-leak')],
                    summary='Users', members=['alice'], builtin=False)],
                bindings={'alice': ['Manager']}, compat=[dict(id='original-exception', methods=['GET'], uri='/existing/read',
                    desc='original rule', excludeSubjectPrefix='reg:')]),
            catalog=[dict(id='business', label='Business', resources=[dict(id='users', label='Users', actions=['view'])])],
            actions=[dict(id='view', label='View')], resources=[dict(id='users', label='Users', section='business')],
            degraded='', csrf='must-not-leak', session_cookie='must-not-leak')

    def test_overview_retains_existing_members_permissions_and_catalog_without_auth_material(self):
        original = self.overview()
        unchanged = deepcopy(original)
        value = project(original)
        self.assertEqual(value['members'][0]['subject'], 'alice')
        self.assertEqual(value['members'][0]['extraGrants'], original['members'][0]['extraGrants'])
        self.assertEqual(value['policy']['bindings'], [{'subject': 'alice', 'roles': ['Manager']}])
        self.assertEqual(value['policy']['roles'][0]['rules'], [{'resources': ['users'], 'actions': ['view', 'manage']}])
        self.assertEqual(value['policy']['compat'], original['policy']['compat'])
        self.assertEqual(value['catalog'], original['catalog'])
        self.assertNotIn('must-not-leak', json.dumps(value))
        self.assertNotIn('/private/policy.json', json.dumps(value))
        self.assertEqual(original, unchanged)

    def test_audit_preserves_business_changes_and_reuses_original_redaction(self):
        original = dict(entries=[dict(at='2026-11-09', actor='alice', kind='member.roles', note='contact owner@example.test',
            generation=3, revision='revision-1', changes=[dict(op='member.roles', subject='alice',
                **{'from': ['Viewer'], 'to': ['Manager'], 'csrf': 'must-not-leak'})], token='must-not-leak')])
        value = project(original, 'audit')
        self.assertEqual(value['entries'][0]['changes'][0], {'op': 'member.roles', 'subject': 'alice', 'from': ['Viewer'], 'to': ['Manager']})
        self.assertIn('owner@example.test', json.dumps(value))
        self.assertNotIn('must-not-leak', json.dumps(value))

    def test_bootstrap_session_wrong_shapes_and_unknown_views_are_rejected(self):
        for value, view in [({'account': {}, 'csrf': 'secret'}, 'overview'), ({}, 'session'),
                            (dict(entries='wrong'), 'audit'), ([], 'overview')]:
            with self.subTest(view=view), self.assertRaises(BackendError):
                project(value, view)

    def test_account_named_token_is_business_identity_not_a_credential_field(self):
        original = self.overview()
        original['policy']['bindings'] = {'token': ['Viewer'], 'password': ['Manager']}
        value = project(original)
        self.assertEqual(value['policy']['bindings'],
            [{'subject': 'token', 'roles': ['Viewer']}, {'subject': 'password', 'roles': ['Manager']}])
        self.assertNotIn('must-not-leak', json.dumps(value))

    def test_fixed_backend_read_does_not_grant_access_from_response_admin_or_caller_name(self):
        allowed, calls = [200], []
        catalog = Catalog(lambda *args: allowed[0])
        def transport(*args):
            calls.append(args)
            return 200, json.dumps(self.overview()).encode()
        backend = Backend(catalog, 'https://fs.example', transport=transport)
        principal = Principal('alice', 'MMOEXP_AUTH=synthetic')
        value = backend.query(principal, 'accounts.overview', {})['data']
        self.assertEqual(value['policy']['actor'], 'alice')
        self.assertNotIn('must-not-leak', json.dumps(value))
        self.assertEqual(calls[0][0:2], ('GET', '/__auth/access/api/overview'))
        allowed[0] = 403
        with self.assertRaises(CatalogPermissionError):
            backend.query(principal, 'accounts.overview', {})
        allowed[0] = 200
        with self.assertRaises(ValidationError):
            backend.query(principal, 'accounts.overview', {'subject': 'admin'})
        self.assertEqual(len(calls), 1)

    def test_registered_audit_operation_forwards_only_bounded_limit(self):
        catalog, calls = Catalog(lambda *args: 200), []
        def transport(*args):
            calls.append(args)
            return 200, b'{"entries":[{"at":"2026-11-09","actor":"alice","kind":"role.update","changes":[]}],"csrf":"must-not-leak"}'
        backend = Backend(catalog, 'https://fs.example', transport=transport)
        principal = Principal('alice', 'MMOEXP_AUTH=synthetic')
        value = backend.query(principal, 'accounts.audit', {'limit': 20})['data']
        self.assertEqual(value['entries'][0]['kind'], 'role.update')
        self.assertNotIn('must-not-leak', json.dumps(value))
        self.assertEqual(calls[0][0:2], ('GET', '/__auth/access/api/audit?limit=20'))
        for arguments in [{'limit': 501}, {'subject': 'admin'}, {'limit': 0}]:
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                backend.query(principal, 'accounts.audit', arguments)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
