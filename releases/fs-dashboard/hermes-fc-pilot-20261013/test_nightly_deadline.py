from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest.mock import patch

import direct_provider
from nightly_http import Deadline


class AbsoluteDeadlineTests(unittest.TestCase):
    def exchange(self, sender):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        done = threading.Event()

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.recv(8192)
                    sender(connection)
            except OSError:
                pass
            finally:
                done.set()
                listener.close()

        threading.Thread(target=serve, daemon=True).start()
        started = time.monotonic()
        with patch.object(direct_provider, 'BASE_URL', 'http://127.0.0.1:'+str(listener.getsockname()[1])), patch.object(direct_provider, '_load_key', return_value='sk-synthetic-nonsecret'):
            result = direct_provider._open('/chat/completions', b'{"stream":true}', deadline=datetime.now(timezone.utc)+timedelta(seconds=.15))
        self.assertEqual(result['status'], 'scheduled_deadline')
        self.assertLess(time.monotonic()-started, .3)
        self.assertTrue(done.wait(1))

    def test_dripping_response_headers_cannot_extend_deadline(self):
        def send(connection):
            connection.sendall(b'HTTP/1.1 200 OK\r\n')
            for index in range(6):
                connection.sendall(('X-QA-'+str(index)+': x\r\n').encode())
                time.sleep(.06)
        self.exchange(send)

    def test_dripping_http_error_body_cannot_extend_deadline(self):
        def send(connection):
            connection.sendall(b'HTTP/1.1 429 Too Many Requests\r\nTransfer-Encoding: chunked\r\nX-Request-ID: synthetic-request\r\n\r\n')
            for index in range(6):
                connection.sendall(b'1\r\nx\r\n')
                time.sleep(.06)
        self.exchange(send)

    def test_late_dns_or_connect_cannot_send_authorization_or_body(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        original = socket.create_connection
        received = []
        done = threading.Event()

        def late(*args, **kwargs):
            time.sleep(.3)
            return original(*args, **kwargs)

        def serve():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(1)
                    received.append(connection.recv(8192))
            finally:
                done.set()
                listener.close()

        threading.Thread(target=serve, daemon=True).start()
        with patch.object(direct_provider, 'BASE_URL', 'http://127.0.0.1:'+str(listener.getsockname()[1])), patch.object(direct_provider, '_load_key', return_value='sk-synthetic-nonsecret'), patch('nightly_http.socket.create_connection', side_effect=late):
            started = time.monotonic()
            result = direct_provider._open('/chat/completions', b'{"stream":true}', deadline=datetime.now(timezone.utc)+timedelta(seconds=.1))
            self.assertEqual(result['status'], 'scheduled_deadline')
            self.assertLess(time.monotonic()-started, .25)
            self.assertTrue(done.wait(1))
        self.assertEqual(received, [b''])


class ControllerCutoffTests(unittest.TestCase):
    def test_stopping_forever_is_fenced_at_seven_without_false_stop_or_replay(self):
        from test_controller import ControllerTests
        from pilot import digest
        fixture = ControllerTests('test_end_to_end_handshake_model_receipt_and_owner_idempotency')
        fixture.setUp()
        try:
            fixture.at = fixture.at.replace(hour=6, minute=58, second=55)
            service = fixture.service
            key = digest({'owner':'owner','request_id':fixture.body['request_id']})[:32]
            deadline = fixture.at.replace(hour=6, minute=59, second=0)
            with service.tasks.db() as db:
                db.execute('INSERT INTO nightly_requests VALUES(?,?,?,?,?,?,NULL)', ('synthetic',key,'owner','daily',deadline.isoformat(),'WAITING'))
            stops, gets = [], []

            def remote(method, path, body=None, idempotency=None, **kwargs):
                if path == '/v1/runs':
                    self.assertEqual(kwargs.get('deadline'),deadline)
                    return 202, {'run_id':'run_'+'a'*32,'status':'queued'}
                if method == 'POST':
                    stops.append(fixture.at)
                    return 202, {'status':'stopping'}
                gets.append(fixture.at)
                return 200, {'status':'stopping'}

            def wait(seconds):
                fixture.at += timedelta(seconds=5)

            def gateway(daily, tasks, book, **kwargs):
                return fixture.build_gateway(daily,tasks,book)

            with patch('controller.build_book', return_value=fixture.book), patch('controller.gateway', side_effect=gateway), patch.object(service,'remote',side_effect=remote), patch('controller.time.sleep',side_effect=wait):
                _, job = service.post(fixture.body,'owner',fixture.headers)
            self.assertEqual(job['state'],'NEEDS_RECONCILE',job)
            self.assertEqual(job['error'],'nightly_stop_unconfirmed')
            self.assertEqual(job['task_state'],'NEEDS_RECONCILE')
            self.assertEqual(len(stops),1)
            self.assertTrue(all(at<deadline+timedelta(minutes=1) for at in gets))
            self.assertFalse(job.get('result'))
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
