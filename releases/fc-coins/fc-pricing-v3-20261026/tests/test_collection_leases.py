from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'source'))
from collection_cases import NOW, coordinator, identity, job, observation, policy


class CollectionLeases(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'collection.sqlite3'
        self.coordinator = coordinator(self.path)

    def claim(self, node='183', now=NOW):
        return self.coordinator.claim_job(identity(node), ['ItemD2R'], now)

    def test_concurrent_claim_has_one_owner_and_restart_keeps_lease(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = list(pool.map(self.claim, ['183', '187']))
        self.assertEqual(sum(task is not None for task in tasks), 1)
        from fc_collection.coordinator import Coordinator
        recovered = Coordinator(self.path)
        self.assertIsNone(recovered.claim_job(identity('187'), ['ItemD2R'], NOW))

    def test_enqueue_is_idempotent_without_resetting_attempts(self):
        task = self.claim()
        self.coordinator.enqueue(job())
        self.assertIsNone(self.claim('187'))
        self.assertEqual(task['lease_epoch'], 1)

    def test_ack_loss_returns_same_receipt_after_expiry_and_generation_change(self):
        task = self.claim()
        self.coordinator.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = observation(task)
        receipt = self.coordinator.submit_observation(identity(), body, NOW)
        self.coordinator.configure_source('ItemD2R', dict(policy(), generation=2, mode='off'))
        replay = self.coordinator.submit_observation(identity(), body, NOW + timedelta(seconds=1000))
        self.assertEqual(receipt, replay)
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(self.coordinator.accepted(task['job_id'], NOW), [])

    def test_same_observation_id_different_hash_and_other_identity_denied(self):
        task = self.claim()
        self.coordinator.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = observation(task)
        self.coordinator.submit_observation(identity(), body, NOW)
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.coordinator.submit_observation(identity('187'), body, NOW)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.coordinator.submit_observation(identity(), dict(body, reason_code='changed'), NOW)

    def test_old_epoch_late_first_result_rejected_after_safe_takeover(self):
        task = self.claim()
        newer = self.claim('187', NOW + timedelta(seconds=23))
        self.assertEqual(newer['lease_epoch'], 2)
        receipt = self.coordinator.submit_observation(identity(), observation(task), NOW + timedelta(seconds=23))
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(receipt['reason'], 'lease_invalid')

    def test_new_boot_cannot_reuse_old_lease_or_renew_it(self):
        task = self.claim()
        restarted = identity(boot='boot-2')
        self.coordinator.register_node(restarted, ['ItemD2R'], NOW + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.coordinator.renew_lease(restarted, task['job_id'], task['attempt_id'], 1, NOW)
        with self.assertRaises(ValueError):
            self.coordinator.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)

    def test_transaction_exception_rolls_back_no_false_completion(self):
        with self.assertRaises(RuntimeError):
            with self.coordinator.transaction() as db:
                db.execute("UPDATE collection_jobs SET state='COMPLETED'")
                raise RuntimeError('simulated_crash_before_commit')
        self.assertIsNotNone(self.claim())

    def test_unknown_identity_cannot_claim_and_deadline_cannot_be_extended(self):
        with self.assertRaises(ValueError):
            self.coordinator.claim_job(identity('unknown'), ['ItemD2R'], NOW)
        task = self.claim()
        changed = dict(job(), deadline_at=(NOW + timedelta(hours=1)).isoformat())
        with self.assertRaises(ValueError):
            self.coordinator.enqueue(changed)
        self.assertEqual(task['deadline_at'], job()['deadline_at'])

    def test_old_quote_cannot_be_relabelled_with_current_run_and_epoch(self):
        task = self.claim()
        self.coordinator.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = observation(task, NOW - timedelta(seconds=60))
        receipt = self.coordinator.submit_observation(identity(), body, NOW)
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(receipt['reason'], 'capture_predates_attempt')
        self.assertEqual(self.coordinator.accepted(task['job_id'], NOW), [])
