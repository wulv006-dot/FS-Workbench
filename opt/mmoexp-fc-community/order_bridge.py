"""Fixed-scope read-only order bridge. Never forwards raw Admin rows.

Run under the existing supervised deployment identity. The socket directory must
be private and service-owned. No arbitrary URLs, paths, filters or email queries.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
from urllib.parse import urlencode
from urllib.request import Request

from order_service import ORDER_NUMBER, PROBLEM_SUPPORT, STATUS, order_not_found, project_order

SHARED = Path('/opt/fs-order-session/fc_shared_admin.py')
SHARED_SHA256 = 'c6eaf37907ef350459a3e980f8e8c8611db3e36c37755965e38d987e3f6a0327'
SOCKET = '/run/fc-order/order.sock'


def load_shared():
    info = SHARED.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
            or hashlib.sha256(SHARED.read_bytes()).hexdigest() != SHARED_SHA256):
        raise ValueError('Untrusted order transport')
    spec = importlib.util.spec_from_file_location('fc_order_shared', SHARED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExactReader:
    def __init__(self, shared):
        self.shared = shared
        self.session = shared.SessionManager({})

    def __call__(self, number):
        if not isinstance(number, str) or not ORDER_NUMBER.fullmatch(number):
            raise ValueError('Invalid order')
        params = {'page': '1', 'limit': '2', 'order': 'id,desc'}
        for i, (field, value) in enumerate((('site_id', '266'), ('gid', '1327'), ('order_no', number))):
            params.update({f'search[{i}][field]': field, f'search[{i}][operator]': '=',
                           f'search[{i}][val]': value})
        request = Request(self.shared.api_base(self.session.config) +
            '/admin/order.Order/index?' + urlencode(params),
            headers=dict(self.shared.HEADERS), method='GET')
        with self.session.opener.open(request, timeout=10) as response:
            if response.status != 200:
                raise ValueError('Order unavailable')
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError('Order unavailable')
        payload = json.loads(raw)
        if order_not_found(payload):
            return {'code': 1, 'data': {'total': 0, 'list': []}}
        safe = project_order(payload, number)
        if safe is None:
            raise ValueError('Order unavailable')
        # Only scope, supplied number and a constant allowlisted label cross IPC.
        label = ('问题订单' if safe['support'] == PROBLEM_SUPPORT else
                 next(key for key, value in STATUS.items() if value == safe['status']))
        return {'code': 1, 'data': {'total': 1, 'list': [{
            'order_no': number, 'site_id': 266, 'gid': 1327, 'status_format': label}]}}


def dispatch(reader, request):
    if (not isinstance(request, dict) or set(request) != {'action', 'args'}
            or request['action'] != 'lookup' or not isinstance(request['args'], list)
            or len(request['args']) != 1 or not isinstance(request['args'][0], str)
            or not ORDER_NUMBER.fullmatch(request['args'][0])):
        raise ValueError('Invalid request')
    return reader(request['args'][0])


def serve(reader, allowed_uid):
    parent = Path(SOCKET).parent
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o007):
        raise ValueError('Unsafe socket directory')

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(12)
            try:
                _, uid, _ = struct.unpack('3i', self.request.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                if uid not in (0, allowed_uid):
                    raise ValueError('Invalid peer')
                raw = self.rfile.readline(513)
                if len(raw) > 512 or not raw.endswith(b'\n'):
                    raise ValueError('Invalid request')
                result = dispatch(reader, json.loads(raw))
                output = json.dumps({'ok': True, 'data': result}).encode() + b'\n'
            except Exception:
                output = b'{"ok":false}\n'
            try:
                self.wfile.write(output)
            except OSError:
                pass

    # Refuse existing sockets: the publisher must reconcile stale runtime state.
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--allowed-uid', type=int, required=True)
    args = parser.parse_args()
    if args.allowed_uid < 0:
        parser.error('Invalid UID')
    serve(ExactReader(load_shared()), args.allowed_uid)
