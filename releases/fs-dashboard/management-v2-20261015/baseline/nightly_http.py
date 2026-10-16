"""Absolute deadline for owned HTTP calls; never changes endpoints or credentials."""
from datetime import datetime, timezone
import http.client
import socket
import threading
import urllib.request


class Deadline:
    def __init__(self, at):
        self.at = at
        self.lock = threading.Lock()
        self.expired = False
        self.sockets = []
        self.timer = None

    def remaining(self):
        value = (self.at-datetime.now(timezone.utc)).total_seconds()
        if value <= 0 or self.expired:
            raise TimeoutError('nightly_deadline_exceeded')
        return value

    def register(self, sock):
        with self.lock:
            expired = self.expired
            if not expired:
                self.sockets.append(sock)
        if expired:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
            raise TimeoutError('nightly_deadline_exceeded')
        self.remaining()
        return sock

    def stop(self):
        with self.lock:
            self.expired = True
            sockets = list(self.sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def __enter__(self):
        self.timer = threading.Timer(self.remaining(), self.stop)
        self.timer.daemon = True
        self.timer.start()
        return self

    def __exit__(self, *args):
        if self.timer:
            self.timer.cancel()

    def run(self, callback):
        done = threading.Event()
        values, errors = [], []

        def work():
            try:
                self.remaining()
                values.append(callback())
            except BaseException as error:
                errors.append(error)
            finally:
                done.set()

        # DNS may ignore socket timeouts. This caller still stops; a late socket
        # is rejected by register before any HTTP authorization/body is sent.
        thread = threading.Thread(target=work, name='nightly-owned-http', daemon=True)
        thread.start()
        if not done.wait(self.remaining()):
            self.stop()
            raise TimeoutError('nightly_deadline_exceeded')
        self.remaining()
        if errors:
            raise errors[0]
        return values[0]

    def handlers(self, context=None):
        control = self

        class Connection:
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                connect = self._create_connection

                def bounded(*args, **kwargs):
                    control.remaining()
                    return control.register(connect(*args, **kwargs))

                self._create_connection = bounded

        class HTTPConnection(Connection, http.client.HTTPConnection):
            pass

        class HTTPSConnection(Connection, http.client.HTTPSConnection):
            def connect(self):
                http.client.HTTPConnection.connect(self)
                hostname = self._tunnel_host or self.host
                self.sock = self._context.wrap_socket(self.sock, server_hostname=hostname,
                                                     do_handshake_on_connect=False)
                control.register(self.sock)
                self.sock.do_handshake()
                control.remaining()

        class HTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, request):
                return self.do_open(HTTPConnection, request)

        class HTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, request):
                return self.do_open(HTTPSConnection, request, context=self._context)

        return HTTPHandler(), HTTPSHandler(context=context)
