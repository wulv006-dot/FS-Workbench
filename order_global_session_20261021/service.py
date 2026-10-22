"""One Order session owner, validating the existing authenticated browser only."""
import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOCKETS = ('/run/fs-order-session/session.sock',
           '/var/lib/fc27-cloud/browser/lootbar/fs-order-session.sock',
           '/opt/madden-workbench/.fs-order-session.sock',
           '/opt/d4follow/_p2pah_srv/.fs-order-session.sock')
ALLOWED_UIDS = {0, 994, 11027}
IDENTITY_CHECK = r'''
def identity_ok(status, url, body):
    import re
    from urllib.parse import urlsplit
    target = urlsplit(url)
    return (status == 200 and target.scheme == 'https' and target.hostname == 'order.p2pah.cn'
            and target.path == '/admin/index/index.html'
            and bool(re.search(r'href=["\']/admin/public/logout\.html["\']', body, re.I))
            and not re.search(r'<input[^>]+type\s*=\s*["\']?password', body, re.I))
'''
PROBE = IDENTITY_CHECK + r'''
import json
from playwright.sync_api import sync_playwright, Error
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://127.0.0.1:9226', timeout=8000)
    assert len(browser.contexts) == 1
    ctx = browser.contexts[0]
    valid = False
    error = 'order_probe_transport_unavailable'
    # Retry transport failures before caching them; 8s CDP + 20s reads fit inside 35s.
    for budget in (12000, 8000):
        response = None
        try:
            response = ctx.request.get('https://order.p2pah.cn/admin/index/index.html', timeout=budget, fail_on_status_code=False)
            if response.status == 429 or response.status >= 500:
                continue
            valid = identity_ok(response.status, response.url, response.text())
            error = None if valid else 'order_identity_unverified'
            break
        except Error:
            pass
        finally:
            if response is not None:
                response.dispose()
    rows = ctx.cookies(['https://order.p2pah.cn/']) if valid else []
    rows = [r for r in rows if r['domain'].lstrip('.') == 'order.p2pah.cn']
    print(json.dumps({'ready': bool(rows), 'cookies': rows,
                      'error': None if rows else error or 'order_identity_unverified'}))
'''


class Session:
    def __init__(self, probe=None):
        self.lock = threading.Lock()
        self.checked = 0
        self.result = {'ready': False, 'error': 'not_checked'}
        self.probing = False
        self.probe_seconds = None
        self.probe = probe or self.browser_probe

    @staticmethod
    def browser_probe():
        proc = subprocess.run(['docker', 'exec', 'fc27-cloud-browser', 'python3', '-c', PROBE],
                              capture_output=True, timeout=35, text=True)
        if proc.returncode or len(proc.stdout) > 65536:
            raise RuntimeError('order_probe_unavailable')
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or type(result.get('ready')) is not bool:
            raise RuntimeError('order_probe_response_invalid')
        return result

    def get(self):
        with self.lock:
            if not self.checked or time.monotonic() - self.checked >= 20:
                started = time.monotonic()
                self.probing = True
                try:
                    self.result = self.probe()
                except Exception:
                    self.result = {'ready': False, 'error': 'order_probe_unavailable'}
                finally:
                    self.checked = time.monotonic()
                    self.probe_seconds = round(self.checked - started, 3)
                    self.probing = False
            return self.result

    def health(self):
        # Health never waits behind an upstream request; cookie issuance still uses get().
        age = time.monotonic() - self.checked if self.checked else None
        fresh = age is not None and age <= 45
        return {'service': 'fs-order-session', 'ready': fresh and self.result.get('ready') is True,
                'last_error': self.result.get('error') if fresh or age is None else 'order_probe_stale',
                'checking': self.probing, 'verified_age_seconds': round(age, 1) if age is not None else None,
                'probe_seconds': self.probe_seconds, 'probe_path': '/admin/index/index.html', 'login_attempts': 0}


SESSION = Session()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in ALLOWED_UIDS or self.rfile.readline(64) != b'cookies\n':
            return
        self.wfile.write(json.dumps(SESSION.get()).encode() + b'\n')


class UnixServer(socketserver.ThreadingMixIn, getattr(socketserver, 'UnixStreamServer', socketserver.TCPServer)):
    daemon_threads = True


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/health':
            self.send_error(404)
            return
        result = SESSION.health()
        body = json.dumps(result).encode()
        self.send_response(200 if result.get('ready') else 503)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    servers = []
    try:
        def upkeep():
            while True:
                SESSION.get()
                time.sleep(5)
        threading.Thread(target=upkeep, daemon=True).start()
        Path('/run/fs-order-session').mkdir(mode=0o755, exist_ok=True)
        os.chmod('/run/fs-order-session', 0o755)
        for path in SOCKETS:
            if Path(path).exists():
                if not Path(path).is_socket():
                    raise RuntimeError('socket_path_occupied')
                Path(path).unlink()
            server = UnixServer(path, Handler)
            os.chown(path, 0, 11027)
            # SO_PEERCRED enforces the uid allowlist, including fc27api outside this group.
            os.chmod(path, 0o666)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        ThreadingHTTPServer(('127.0.0.1', 8768), Health).serve_forever()
    finally:
        for server in servers:
            server.server_close()
            Path(server.server_address).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
