import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from campaign_backend.benefits import CouponEdit, row_hash
from campaign_backend.core import ContractError
from campaign_backend.ledger import OperationLedger, ObjectOperationBusy
from test_benefit_operations import native_row


class Reader:
    def __init__(self, response, ledger, operation_id, fail_get=False, error=None):
        self.row = native_row()
        self.response, self.ledger, self.operation_id = response, ledger, operation_id
        self.fail_get, self.error = fail_get, error
        self.posts, self.gets = 0, 0
        self.session = SimpleNamespace(token='fixture-only', admin=SimpleNamespace(post=self.post))

    def post(self, *args, **kwargs):
        self.posts += 1
        if self.error:
            raise self.error
        return self.response

    def detail(self, *args):
        self.gets += 1
        if self.posts:
            # This is the first GET after POST; evidence must already be durably committed.
            if len(OperationLedger(self.ledger.path).native_response_audit(self.operation_id)) != 1:
                raise AssertionError('GET happened before response audit commit')
            if self.fail_get:
                raise ContractError('UPSTREAM_UNAVAILABLE')
        return dict(self.row)


class VerifiedTextEdit(CouponEdit):
    """Same low-level subclass call shape as the local native validation harness."""


class NativeResponseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'operations.sqlite3'
        self.ledger = OperationLedger(self.path)
        self.operation_id = 'fixture-response-operation'
        row = native_row()
        self.payload = dict(site_id='266', kind='coupon', native_id='123', before_hash=row_hash(row),
            changes={'title': 'Not yet applied'}, scope={key: str(row[key]) for key in ('site_id', 'game_id', 'goods_id')})

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, body, status=200, fail_get=False, error=None):
        reader = Reader(SimpleNamespace(status_code=status, content=body), self.ledger,
                        self.operation_id, fail_get=fail_get, error=error)
        result = self.ledger.execute(self.operation_id, self.payload, VerifiedTextEdit(reader, self.payload))
        return reader, result, self.ledger.native_response_audit(self.operation_id)

    def test_http_200_business_non_success_recorded_before_get_without_terminal_inference(self):
        body = b'{"code":0,"msg":"unverified business message"}'
        reader, result, audit = self.execute(body)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual((reader.posts, reader.gets), (1, 2))
        self.assertEqual(audit[0]['business_code'], 0)
        self.assertEqual(audit[0]['http_status'], 200)
        self.assertEqual(audit[0]['parse_status'], 'json_object')
        self.assertEqual(audit[0]['msg_class'], 'nonempty_text_uninterpreted')
        self.assertEqual(audit[0]['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(audit[0]['body_size'], len(body))
        self.assertEqual(audit[0]['operation_id'], self.operation_id)
        self.assertEqual(audit[0]['object_ref'], ['266', 'coupon', '123'])
        self.assertEqual(audit[0]['request_payload_hash'], result['payload_hash'])
        with self.assertRaises(ObjectOperationBusy):
            OperationLedger(self.path).execute('different-response-operation', self.payload,
                                              VerifiedTextEdit(reader, self.payload))
        self.assertEqual(reader.posts, 1)

    def test_json_exception_keeps_body_hash_and_does_not_lose_audit(self):
        body = b'\xff not JSON PRIVATE_RAW_BODY'
        _, result, audit = self.execute(body)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit[0]['parse_status'], 'invalid_json')
        self.assertEqual(audit[0]['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertIsNone(audit[0]['business_code'])

    def test_get_failure_still_has_committed_response_evidence(self):
        _, result, audit = self.execute(b'{"code":1,"msg":"not proof of native state"}', fail_get=True)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit[0]['business_code'], 1)
        self.assertEqual(OperationLedger(self.path).native_response_audit(self.operation_id), audit)

    def test_sensitive_message_and_non_numeric_business_code_never_stored_or_returned(self):
        message = 'PRIVATE_CUSTOMER@example.test batoken=PRIVATE_TOKEN code=PRIVATE_COUPON'
        body = json.dumps(dict(code='PRIVATE_COUPON', msg=message, data={'credential': 'PRIVATE_PASSWORD'})).encode()
        _, result, audit = self.execute(body)
        self.assertIsNone(audit[0]['business_code'])
        self.assertEqual(audit[0]['business_code_type'], 'str')
        self.assertEqual(audit[0]['msg_sha256'], hashlib.sha256(message.encode()).hexdigest())
        self.assertEqual(audit[0]['msg_length'], len(message))
        for serialized in (json.dumps(audit), json.dumps(result), self.path.read_bytes().decode('latin1')):
            self.assertNotIn('PRIVATE_', serialized)
        with self.assertRaisesRegex(ContractError, 'UNSAFE_NATIVE_RESPONSE_EVIDENCE'):
            evidence = {key: value for key, value in audit[0].items()
                        if key not in ('audit_id', 'operation_id', 'object_ref', 'request_payload_hash', 'recorded_at')}
            self.ledger.record_native_response(self.operation_id, dict(evidence, raw_msg=message))
        self.assertEqual(len(self.ledger.native_response_audit(self.operation_id)), 1)

    def test_transport_timeout_is_recorded_safely_without_following_get(self):
        reader, result, audit = self.execute(b'', error=TimeoutError('PRIVATE_TOKEN customer=PRIVATE_EMAIL'))
        self.assertEqual((reader.posts, reader.gets), (1, 1))
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit[0]['event'], 'transport_exception')
        self.assertEqual(audit[0]['error_class'], 'TimeoutError')
        self.assertIsNone(audit[0]['http_status'])
        self.assertIsNone(audit[0]['body_sha256'])
        self.assertNotIn('PRIVATE_', json.dumps(audit))

    def test_repeated_low_level_execute_never_reposts_or_rewrites_audit(self):
        reader, first, audit = self.execute(b'{"code":0,"msg":"not yet understood"}')
        restarted = OperationLedger(self.path)
        second = restarted.execute(self.operation_id, self.payload, VerifiedTextEdit(reader, self.payload))
        self.assertEqual(first, second)
        self.assertEqual(reader.posts, 1)
        self.assertEqual(restarted.native_response_audit(self.operation_id), audit)

    def test_non_200_is_audited_without_get_or_rejection_inference(self):
        reader, result, audit = self.execute(b'{"code":403,"msg":"PRIVATE_DETAILS"}', status=403)
        self.assertEqual((reader.posts, reader.gets), (1, 1))
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit[0]['http_status'], 403)
        self.assertEqual(audit[0]['business_code'], 403)

    def test_oversized_response_hashes_full_bytes_but_does_not_parse_message(self):
        body = b'PRIVATE_LARGE_BODY' * 5000
        _, result, audit = self.execute(body)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit[0]['parse_status'], 'body_too_large')
        self.assertEqual(audit[0]['body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(audit[0]['body_size'], len(body))

    def test_audit_storage_failure_stops_following_get_and_keeps_unknown(self):
        def fail_audit(*args):
            raise ContractError('AUDIT_STORAGE_UNAVAILABLE')
        self.ledger.record_native_response = fail_audit
        reader, result, audit = self.execute(b'{"code":1,"msg":"ok"}')
        self.assertEqual((reader.posts, reader.gets), (1, 1))
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(audit, [])

    def test_direct_post_without_ledger_audit_binding_is_blocked(self):
        reader = Reader(SimpleNamespace(status_code=200, content=b'{}'), self.ledger, self.operation_id)
        with self.assertRaisesRegex(ContractError, 'NATIVE_RESPONSE_AUDIT_REQUIRED'):
            VerifiedTextEdit(reader, self.payload).dispatch_once(self.operation_id, self.payload)
        self.assertEqual(reader.posts, 0)


if __name__ == '__main__':
    unittest.main()
