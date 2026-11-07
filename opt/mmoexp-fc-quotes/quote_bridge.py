"""Narrow local read-only product service; never accepts Admin paths or payloads."""
import argparse
import json
import os
import re
import socket
import socketserver
import sys

MAX_RESPONSE = 1024 * 1024
CATEGORIES = {'sbc', 'packs', 'evolutions', 'boosting', 'gallery', 'coins'}


def dispatch(provider, request):
    if not isinstance(request, dict) or set(request) != {'action', 'args'}:
        raise ValueError('Invalid request')
    action, args = request['action'], request['args']
    counts = {'catalog': 1, 'options': 1, 'quote': 2}
    if not isinstance(action, str) or action not in counts or not isinstance(args, list) or len(args) != counts[action]:
        raise ValueError('Invalid operation')
    if action == 'catalog':
        if not isinstance(args[0], str) or args[0] not in CATEGORIES:
            raise ValueError('Invalid category')
    else:
        if not isinstance(args[0], str) or not re.fullmatch(
                r'(?:sbc|packs|gallery|evolutions|boosting|coins):[1-9][0-9]{0,11}', args[0]):
            raise ValueError('Invalid product ID')
        if action == 'quote' and (not isinstance(args[1], str) or not re.fullmatch(r'[1-9][0-9]{0,11}', args[1])):
            raise ValueError('Invalid option ID')
    return getattr(provider, action)(*args)


class SocketProvider:
    def __init__(self, path):
        self.path = path

    def call(self, action, args):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(45)
            client.connect(self.path)
            client.sendall(json.dumps({'action': action, 'args': args}).encode() + b'\n')
            with client.makefile('rb') as stream:
                raw = stream.readline(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE or not raw.endswith(b'\n'):
                raise ValueError('Invalid response')
            value = json.loads(raw)
            if value.get('ok') is not True:
                raise RuntimeError('Price service unavailable')
            return value['data']

    def catalog(self, kind):
        return self.call('catalog', [kind])

    def options(self, product_id):
        return self.call('options', [str(product_id)])

    def quote(self, product_id, option_id):
        return self.call('quote', [str(product_id), str(option_id)])


def serve(provider, path):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(45)
            try:
                raw = self.rfile.readline(4097)
                if len(raw) > 4096 or not raw.endswith(b'\n'):
                    raise ValueError('Invalid request')
                result = {'ok': True, 'data': dispatch(provider, json.loads(raw))}
                response = json.dumps(result, ensure_ascii=False).encode() + b'\n'
                if len(response) > MAX_RESPONSE:
                    raise ValueError('Response too large')
            except Exception:
                response = b'{"ok":false}\n'
            try:
                self.wfile.write(response)
            except OSError:
                pass

    # RuntimeDirectory is service-owned; refuse an existing socket instead of unlinking another process.
    with socketserver.UnixStreamServer(path, Handler) as server:
        os.chmod(path, 0o660)
        server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', required=True)
    args = parser.parse_args()
    sys.path.insert(0, '/opt/fc27-sbc-tool')
    from admin_client import AdminClient
    from quote_catalog import QuoteCatalog
    serve(QuoteCatalog(AdminClient()), args.socket)
