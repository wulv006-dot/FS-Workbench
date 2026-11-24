from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_http import get
from user_summary_jobs import SummaryJobs


class SummaryJobsTest(unittest.TestCase):
    def test_cold_connector_summary_reuses_original_work_and_rechecks_scope(self):
        unblock = Event()
        started = []
        allowed = {'caller'}

        def query(args, user):
            if user not in allowed:
                raise PermissionError('user_scope_denied')
            if 'snapshot_id' not in args:
                started.append(args)
                if not unblock.wait(5):
                    raise AssertionError('test did not release the query')
            return {'snapshot_id': 'frozen'}

        class Service:
            summary_jobs = SummaryJobs(query)

        service = Service()
        self.addCleanup(service.summary_jobs.pool.shutdown)
        self.addCleanup(unblock.set)
        route = '/users'
        submit = dict(action=['connector_summary'], start=['2026-01-01'], scope_id=['456'])
        with patch('user_summary_jobs.wait'):
            status, pending = get(service, route, submit, 'caller')
        self.assertEqual(status, 202)
        self.assertEqual(pending['status'], 'pending')
        self.assertEqual(get(service, route, submit, 'caller'), (202, pending))
        poll = dict(action=['connector_summary'], query_id=[pending['query_id']])
        self.assertEqual(get(service, route, poll, 'other')[0], 404)
        self.assertEqual(get(service, route, dict(poll, scope_id=['552']), 'caller')[0], 422)
        self.assertEqual(get(service, route, dict(submit, scope_id=['552']), 'caller')[0], 429)
        unblock.set()
        service.summary_jobs.pool.shutdown()
        self.assertEqual(get(service, route, poll, 'caller'), (200, {'snapshot_id': 'frozen'}))
        self.assertEqual(started, [{'start': '2026-01-01', 'scope_id': '456'}])
        allowed.clear()
        self.assertEqual(get(service, route, poll, 'caller')[0], 403)

    def test_saved_snapshot_stays_synchronous(self):
        jobs = SummaryJobs(lambda args, _user: args)
        self.addCleanup(jobs.pool.shutdown)
        self.assertEqual(jobs.read({'snapshot_id': 'frozen'}, 'caller'), (200, {'snapshot_id': 'frozen'}))
        self.assertFalse(jobs.jobs)
