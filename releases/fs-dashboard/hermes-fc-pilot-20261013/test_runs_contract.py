import unittest
from runs_contract import WIRE_TOOLS, require_capabilities, submission, validate_admission, run_path


def capabilities():
    return {'object': 'hermes.api_server.capabilities', 'platform': 'hermes-agent',
            'runtime': {'mode': 'server_agent', 'tool_execution': 'server'}, 'auth': {'required': True},
            'features': {'run_submission': True, 'run_status': True, 'run_stop': True,
                         'runs_idempotency': {'supported': True, 'durable': True}}}


class RunsTests(unittest.TestCase):
    def test_capabilities_require_auth_and_durable_idempotency(self):
        require_capabilities(capabilities(), list(WIRE_TOOLS))
        for value in [False, None]:
            c = capabilities(); c['auth']['required'] = value
            with self.assertRaises(ValueError): require_capabilities(c, list(WIRE_TOOLS))
        c = capabilities(); c['features']['runs_idempotency']['durable'] = False
        with self.assertRaises(ValueError): require_capabilities(c, list(WIRE_TOOLS))

    def test_runtime_toolset_cannot_be_broader_or_narrower(self):
        for tools in [list(WIRE_TOOLS)+['terminal'], list(WIRE_TOOLS)[:-1], list(WIRE_TOOLS)+[WIRE_TOOLS[0]]]:
            with self.assertRaises(ValueError): require_capabilities(capabilities(), tools)

    def test_submission_is_stable_and_tenant_scoped(self):
        task = {'state': 'DISPATCH_UNKNOWN', 'owner': 'owner', 'id': 'task', 'spec': {'period': 'synthetic'}}
        first = submission(task)
        self.assertEqual(first, submission(task))
        self.assertEqual(set(first['body']), {'input', 'session_id'})
        changed = submission(dict(task, owner='another'))
        self.assertNotEqual(first['headers']['Idempotency-Key'], changed['headers']['Idempotency-Key'])
        with self.assertRaises(ValueError): submission(dict(task, state='QUEUED'))

    def test_admission_requires_actual_protocol_shape(self):
        run = 'run_'+'a'*32
        self.assertEqual(validate_admission(202, {'run_id': run, 'status': 'running'}), run)
        for status, value in [(200, {'run_id': run, 'status': 'running'}), (202, {'run_id': '../secret', 'status': 'running'}), (202, {'run_id': run, 'status': 'unknown'})]:
            with self.assertRaises(ValueError): validate_admission(status, value)

    def test_no_control_to_other_endpoint_or_path(self):
        run = 'run_'+'a'*32
        self.assertEqual(run_path(run, 'stop')['path'], '/v1/runs/'+run+'/stop')
        for value, action in [('../secret', 'status'), (run, 'approval'), (run, 'shell')]:
            with self.assertRaises(ValueError): run_path(value, action)


if __name__ == '__main__': unittest.main()
