from concurrent.futures import Future
import hashlib
import io
import json
from pathlib import Path
import sys
import threading
import time
import tempfile
import unittest
from urllib.error import HTTPError


from _paths import ROOT, RELEASE
from customer_tracking import DEFAULT_CONFIG
from tracking_private_session import PrivateReads,safe_source_failure
from tracking_controller import TrackingController,safe_client_failure


class DiagnosticTests(unittest.TestCase):
    def test_only_fixed_source_labels_are_exposed(self):
        self.assertEqual(safe_source_failure(ValueError('admin_day_sort_or_duplicate')),
                         'admin_day_sort_or_duplicate')
        self.assertEqual(safe_source_failure(PermissionError('admin_identity_unavailable')),
                         'admin_identity_unavailable')
        self.assertEqual(safe_source_failure(ValueError('admin_day_time: secret@example.invalid')),
                         'private_source_unavailable')
        self.assertEqual(safe_source_failure(RuntimeError('admin_day_pagination')),
                         'private_source_unavailable')
        self.assertEqual(safe_source_failure(RuntimeError('order SECRET-ORDER')),
                         'private_source_unavailable')
        self.assertEqual(safe_source_failure(json.JSONDecodeError('private customer', '{}', 0)),
                         'private_source_json_invalid')
        self.assertEqual(safe_source_failure(TimeoutError('secret@example.invalid')),
                         'private_source_timeout')
        self.assertEqual(safe_source_failure(KeyError('secret@example.invalid')),
                         'private_source_shape_invalid')

    def test_finished_failure_is_diagnostic_without_dispatching_again(self):
        body={'action':'scan','day':'2026-09-30','config':DEFAULT_CONFIG}
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        reads=object.__new__(PrivateReads)
        reads.lock=threading.RLock()
        future=Future()
        future.set_exception(ValueError('admin_day_pagination'))
        reads.jobs={fingerprint:{'future':future,'finished':time.monotonic(),
                                 'status':'unavailable'}}
        reads.manager=None
        result=reads.execute(body)
        self.assertEqual(result,{'status':'unavailable','reason':'admin_day_pagination'})
        self.assertEqual(len(reads.jobs),1)
        self.assertIs(reads.jobs[fingerprint]['future'],future)

    def test_client_errors_are_fixed_labels_and_persist_without_private_text(self):
        error=HTTPError('http://127.0.0.1/private?email=secret@example.invalid',403,
                        'secret order',{},io.BytesIO(b''))
        self.assertEqual(safe_client_failure(error),'private_client_http_403')
        self.assertEqual(safe_client_failure(TimeoutError('secret@example.invalid')),
                         'private_client_timeout')
        self.assertEqual(safe_client_failure(ValueError('private_result_size')),
                         'private_client_result_size')
        self.assertEqual(safe_client_failure(ValueError('secret@example.invalid')),
                         'private_client_unavailable')
        class Client:
            def read(self,body):raise error
        with tempfile.TemporaryDirectory() as dirname:
            service=TrackingController(dirname,lambda user:user=='admin',Client(),auto_start=False)
            service.store.begin_scan('2026-09-30','a'*32)
            service._poll_scan('2026-09-30')
            job=service.store.scan_job('2026-09-30')
            self.assertEqual(job['state'],'failed')
            self.assertEqual(job['reason'],'private_client_http_403')
            self.assertNotIn('secret',str(job))
        error.close()


if __name__=='__main__':unittest.main()
