"""Local session handoff: only the existing Players service UID may connect."""
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading

SOCKET = Path('/run/fs-player-session/session.sock')
PLAYER_UID = 992


def start(manager):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != PLAYER_UID or self.rfile.readline(32) != b'session\n':
                return
            with manager.lock:
                token = manager.token if manager.status == 'ready' else None
                if not isinstance(token, str) or not token or len(token) > 8192:
                    self.wfile.write(b'{"error":"shared_session_unavailable"}\n')
                    return
                self.wfile.write(json.dumps({'token': token}).encode() + b'\n')

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # A disconnected local client must never log a session response.
            pass

    if SOCKET.exists() or SOCKET.is_symlink():
        info = SOCKET.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0 or info.st_gid != 987:
            raise RuntimeError('unexpected_player_session_socket')
        SOCKET.unlink()
    old_umask = os.umask(0o177)
    try:
        server = Server(str(SOCKET), Handler)
        # The root:987 setgid directory supplies the group without CAP_CHOWN.
        os.chmod(SOCKET, 0o660)
    finally:
        os.umask(old_umask)
    threading.Thread(target=server.serve_forever, daemon=True, name='player-session').start()
    return server
