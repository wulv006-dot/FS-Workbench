"""Linux-only transport check with a fake manager; no Admin requests."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('player_session_socket', Path(__file__).parent / 'source/session/player_session_socket.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'Linux peer credentials required')
class TransportTests(unittest.TestCase):
    def test_peer_protocol_rotation_and_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.sock'
            manager = SimpleNamespace(lock=threading.RLock(), status='ready', token='first')
            with patch.object(module, 'SOCKET', path), patch.object(module, 'PLAYER_UID', os.getuid()):
                server = module.start(manager)
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)
                def request(raw=b'session\n'):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.settimeout(3)
                        connection.connect(str(path)); connection.sendall(raw)
                        try:
                            with connection.makefile('rb') as stream: return stream.readline()
                        except ConnectionResetError:
                            return b''
                self.assertEqual(path.stat().st_mode & 0o777, 0o660)
                self.assertEqual(json.loads(request()), {'token':'first'})
                manager.token = 'rotated'
                self.assertEqual(json.loads(request()), {'token':'rotated'})
                self.assertEqual(request(b'other\n'), b'')
                with patch.object(module, 'PLAYER_UID', -1):
                    self.assertEqual(request(), b'')
                manager.status = 'auth_unavailable'
                self.assertEqual(json.loads(request()), {'error':'shared_session_unavailable'})


if __name__ == '__main__':
    unittest.main()
