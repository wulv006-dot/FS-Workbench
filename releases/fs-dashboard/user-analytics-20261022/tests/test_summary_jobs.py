from pathlib import Path
import sys
from threading import Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_http import get
from user_contract import stamp
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

        from unittest.mock import Mock
        from user_query import Service
        service = Service(Mock(), lambda user, _query, _private: user in allowed)
        service.v4.jobs.query = query
        service.v4.read_context = Mock(return_value=(
            {'projects': {'456': {}, '552': {}}, 'history_backfill_start': '2026-01-01'},
            None, stamp('2026-02-01')))
        self.addCleanup(service.v4.jobs.pool.shutdown)
        self.addCleanup(unblock.set)
        route = '/users'
        submit = dict(action=['connector_summary'], start=['2026-01-01'], game=['456'])
        with patch('user_summary_jobs.wait'):
            status, pending = get(service, route, submit, 'caller')
        self.assertEqual(status, 202)
        self.assertEqual(pending['status'], 'pending')
        self.assertEqual(get(service, route, submit, 'caller'), (202, pending))
        poll = dict(action=['connector_summary'], query_id=[pending['query_id']])
        self.assertEqual(get(service, route, poll, 'other')[0], 404)
        self.assertEqual(get(service, route, dict(poll, game=['552']), 'caller')[0], 422)
        self.assertEqual(get(service, route, dict(submit, game=['552']), 'caller')[0], 429)
        unblock.set()
        service.v4.jobs.pool.shutdown()
        self.assertEqual(get(service, route, poll, 'caller'), (200, {'snapshot_id': 'frozen'}))
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]['start'], '2026-01-01T00:00:00+08:00')
        self.assertEqual(started[0]['game'], '456')
        allowed.clear()
        self.assertEqual(get(service, route, poll, 'caller')[0], 403)

    def test_saved_snapshot_stays_synchronous(self):
        jobs = SummaryJobs(lambda args, _user: args)
        self.addCleanup(jobs.pool.shutdown)
        self.assertEqual(jobs.read({'snapshot_id': 'frozen'}, 'caller'), (200, {'snapshot_id': 'frozen'}))
        self.assertFalse(jobs.jobs)
