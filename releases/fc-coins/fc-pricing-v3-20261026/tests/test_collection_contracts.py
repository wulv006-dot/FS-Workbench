from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'source'))
from collection_cases import NOW, context, job, observation


class CollectionContracts(unittest.TestCase):
    def setUp(self):
        from fc_collection import contracts
        self.contracts = contracts
        self.task = dict(job(), attempt_id='attempt-1', lease_epoch=1,
                         node_id='183', node_boot_id='boot-1',
                         lease_expires_at=(NOW + timedelta(seconds=20)).isoformat())

    def test_job_id_stable_for_same_run_and_canonical_context(self):
        changed = context()
        changed['requested_platforms'].reverse()
        equivalent = self.contracts.build_job(dict(run_id='run-1', created_at=NOW.isoformat()),
                                              'ItemD2R', changed, self.task['deadline_at'])
        self.assertEqual(job()['job_id'], equivalent['job_id'])
        different = self.contracts.build_job(dict(run_id='run-2', created_at=NOW.isoformat()),
                                             'ItemD2R', context(), self.task['deadline_at'])
        self.assertNotEqual(job()['job_id'], different['job_id'])

    def test_unregistered_sources_and_secret_context_fields_rejected(self):
        for source, change in [('IGGM', {}), ('ItemD2R', {'token': 'never-forward'}),
                               ('ItemD2R', {'requested_platforms': ['PS', 'PS']})]:
            with self.subTest(source=source, change=change), self.assertRaises(ValueError):
                self.contracts.build_job(dict(run_id='run-1', created_at=NOW.isoformat()),
                    source, dict(context(), **change), self.task['deadline_at'])

    def test_wrong_binding_unknown_schema_and_execution_fields_rejected(self):
        for change in ({'parent_run_id': 'run-2'}, {'schema_version': 2},
                       {'target_price': '0.01'}, {'policy_version': 'wrong'},
                       {'assignment_generation': 2}, {'task_context_hash': 'b' * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contracts.validate_observation(dict(observation(self.task), **change), self.task, NOW)

    def test_invalid_price_quantity_currency_scope_and_evidence_rejected(self):
        for change in ({'amount': 'NaN'}, {'amount': 'Infinity'}, {'amount': '-1'}, {'amount': 10.0},
                       {'delivered_quantity': '105'}, {'currency': 'SAR'}, {'region_id': 21},
                       {'platform': 'SWITCH'}, {'discount_source': None}, {'selection_verified': False},
                       {'sanitized_evidence_ref': 'https://example.com/?token=secret'},
                       {'cookie': 'never-forward'}, {'conditional': 'false'}):
            body = observation(self.task)
            body['offers'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contracts.validate_observation(body, self.task, NOW)

    def test_coin_and_K_explicit_conversion_does_not_invent_bonus(self):
        body = observation(self.task)
        body['offers'][0].update(quantity_unit='coin', purchase_quantity='100000',
                                 bonus_quantity='5000', delivered_quantity='105000')
        self.contracts.validate_observation(body, self.task, NOW)
        rows = self.contracts.to_fc_quote_rows([body], self.task, NOW)
        self.assertEqual(rows['offers'][0]['purchase_k'], '100')
        self.assertEqual(rows['offers'][0]['bonus_k'], '5')
        self.assertEqual(rows['offers'][0]['gross_usd'], '10.00')

    def test_time_endpoints_and_consumption_recheck(self):
        old_task = dict(self.task, created_at=(NOW - timedelta(seconds=901)).isoformat(),
                        lease_started_at=(NOW - timedelta(seconds=901)).isoformat())
        for age, valid in [(899.999, True), (900, True), (900.001, False), (-5, True), (-5.001, False)]:
            body = observation(self.task, NOW - timedelta(seconds=age))
            with self.subTest(age=age):
                if valid:
                    self.contracts.validate_observation(body, old_task, NOW)
                else:
                    with self.assertRaises(ValueError):
                        self.contracts.validate_observation(body, old_task, NOW)
        with self.assertRaises(ValueError):
            self.contracts.to_fc_quote_rows([observation(self.task)], self.task, NOW + timedelta(seconds=901))

    def test_batch_span_endpoints_and_duplicate_platform_rejected(self):
        old_task = dict(self.task, created_at=(NOW - timedelta(seconds=400)).isoformat(),
                        lease_started_at=(NOW - timedelta(seconds=400)).isoformat())
        for span, valid in [(299.999, True), (300, True), (300.001, False)]:
            body = observation(self.task)
            body['capture_started_at'] = (NOW - timedelta(seconds=span)).isoformat()
            body['offers'][0]['observed_at'] = body['capture_started_at']
            with self.subTest(span=span):
                if valid:
                    self.contracts.validate_observation(body, old_task, NOW)
                else:
                    with self.assertRaises(ValueError):
                        self.contracts.validate_observation(body, old_task, NOW)
        body = observation(self.task)
        body['offers'].append(deepcopy(body['offers'][0]))
        with self.assertRaises(ValueError):
            self.contracts.validate_observation(body, self.task, NOW)

    def test_partial_coverage_and_conditions_remain_missing(self):
        body = observation(self.task)
        body['status'] = 'partial'
        body['reason_code'] = 'platform_unavailable'
        body['offers'] = body['offers'][:1]
        body['offers'][0]['conditional'] = True
        rows = self.contracts.to_fc_quote_rows([body], self.task, NOW)
        self.assertEqual(rows['offers'], [])
        self.assertEqual(len(rows['missing']), 3)


if __name__ == '__main__':
    unittest.main()
