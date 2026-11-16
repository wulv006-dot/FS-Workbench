"""Narrow local read-only product service; never accepts Admin paths or payloads."""
import argparse
import json
import os
import re
import socket
import socketserver
import sys

MAX_RESPONSE = 1024 * 1024
CATEGORIES = {'sbc', 'packs', 'evolutions', 'boosting', 'gallery', 'coins', 'players'}


def dispatch(provider, request):
    if not isinstance(request, dict) or set(request) != {'action', 'args'}:
        raise ValueError('Invalid request')
    action, args = request['action'], request['args']
    counts = {'catalog': 1, 'options': 1, 'quote': 2, 'quote_for_platform': 2,
              'player_search': 2, 'player_tags': 0, 'player_tag': 2, 'player_featured': 1, 'player_preview': 1, 'player_manage_search': 2,
              'player_manage_selection': 0, 'player_manage_tags': 0, 'player_manage_inspect': 1, 'player_manage_match': 1}
    if not isinstance(action, str) or action not in counts or not isinstance(args, list) or len(args) != counts[action]:
        raise ValueError('Invalid operation')
    if action == 'player_manage_search':
        if (not isinstance(args[0], str) or not 1 <= len(args[0].strip()) <= 80
                or any(ord(c) < 32 or c in '%_\\' for c in args[0])
                or type(args[1]) is not int or not 1 <= args[1] <= 10):
            raise ValueError('Invalid player search')
    elif action in ('player_search', 'player_tag'):
        if type(args[1]) is not int or not 1 <= args[1] <= (10 if action == 'player_search' else 200):
            raise ValueError('Invalid page')
        if (not isinstance(args[0], str) or (action == 'player_search' and
                (not 2 <= len(args[0].strip()) <= 80 or any(ord(c) < 32 or c in '%_\\' for c in args[0])))
                or (action == 'player_tag' and not re.fullmatch(r'[1-9][0-9]{0,11}', args[0]))):
            raise ValueError('Invalid player query')
    elif action in ('player_preview', 'player_manage_inspect', 'player_manage_match'):
        if not isinstance(args[0], str) or not re.fullmatch(r'[1-9][0-9]{0,11}', args[0]):
            raise ValueError('Invalid player ID')
    elif action == 'player_featured':
        if type(args[0]) is not int or not 1 <= args[0] <= 200:
            raise ValueError('Invalid page')
    elif action in ('player_tags', 'player_manage_tags', 'player_manage_selection'):
        pass
    elif action == 'quote_for_platform':
        if (not isinstance(args[0], str) or not re.fullmatch(r'players:[1-9][0-9]{0,11}', args[0])
                or not isinstance(args[1], str) or args[1] not in ('PC', 'Xbox Series X|S', 'PlayStation 5')):
            raise ValueError('Invalid player platform quote')
    elif action == 'catalog':
        if not isinstance(args[0], str) or args[0] not in CATEGORIES:
            raise ValueError('Invalid category')
    else:
        if not isinstance(args[0], str) or not re.fullmatch(
                r'(?:sbc|packs|gallery|evolutions|boosting|coins|players):[1-9][0-9]{0,11}', args[0]):
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

    def quote_for_platform(self, product_id, platform):
        return self.call('quote_for_platform', [str(product_id), platform])

    def player_search(self, query, page=1):
        return self.call('player_search', [query, page])

    def player_manage_inspect(self, model_id):
        return self.call('player_manage_inspect', [str(model_id)])

    def player_manage_match(self, model_id):
        return self.call('player_manage_match', [str(model_id)])

    def player_manage_search(self, query, page=1):
        return self.call('player_manage_search', [query, page])

    def player_manage_selection(self):
        return self.call('player_manage_selection', [])

    def player_manage_tags(self):
        return self.call('player_manage_tags', [])

    def player_preview(self, model_id):
        return self.call('player_preview', [str(model_id)])

    def player_featured(self, page=1):
        return self.call('player_featured', [page])

    def player_tags(self):
        return self.call('player_tags', [])

    def player_tag(self, tag_id, page=1):
        return self.call('player_tag', [str(tag_id), page])


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
    parser.add_argument('--config', default='/opt/mmoexp-fc-community/content.config.json')
    args = parser.parse_args()
    sys.path.insert(0, '/opt/fc27-sbc-tool')
    from admin_client import AdminClient
    from quote_catalog import QuoteCatalog
    from player_service import ProductProvider
    client = AdminClient()
    serve(ProductProvider(QuoteCatalog(client), client, args.config, tag_client=client), args.socket)
