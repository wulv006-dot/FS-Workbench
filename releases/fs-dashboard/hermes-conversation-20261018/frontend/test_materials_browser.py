"""Real Chromium UI interactions with synthetic, routed responses. No model/server."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from openpyxl import Workbook
from playwright.sync_api import sync_playwright, expect

HERE = Path(__file__).resolve().parent
UI = next(p / 'ui-system' for p in HERE.parents if (p / 'ui-system').is_dir())
CID = 'a' * 32


def check():
    state = {'files': [], 'turns': [], 'bytes': {}, 'unknown': True, 'requests': []}
    book = Workbook()
    book.active.append(['amount', 7])
    output = io.BytesIO()
    book.save(output)
    book.close()
    class Downloads(BaseHTTPRequestHandler):
        def do_GET(self):
            fid = self.path.rsplit('/', 1)[-1]
            if fid not in state['bytes']:
                self.send_error(404)
                return
            content = state['bytes'][fid]
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', 'attachment; filename=result.xlsx')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass

    def serve(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        def response(value, status=200):
            route.fulfill(status=status, body=json.dumps(value), content_type='application/json')
        if path == '/':
            return route.fulfill(body=(HERE / 'index.html').read_bytes(), content_type='text/html')
        for name, source, mime in [('conversation.js', HERE / 'conversation.js', 'text/javascript'),
                ('conversation.css', HERE / 'conversation.css', 'text/css'),
                ('fs-tokens.css', UI / 'tokens/fs-tokens.css', 'text/css'),
                ('fs-ui.css', UI / 'components/fs-ui.css', 'text/css'),
                ('fs-theme.js', UI / 'adapters/fs-theme.js', 'text/javascript')]:
            if path.endswith('/' + name):
                return route.fulfill(body=source.read_bytes(), content_type=mime)
        if path == '/api/hermes/conversations':
            return response({'items': [{'conversation_id': CID, 'title': '材料核对'}]})
        base = '/api/hermes/conversations/' + CID
        if path == base:
            return response({'conversation_id': CID, 'title': '材料核对', 'turns': state['turns'], 'last_seq': 0})
        if path == base + '/events':
            return route.fulfill(body=': connected\n\n', content_type='text/event-stream')
        if path == base + '/files' and request.method == 'POST':
            rid = request.headers['x-fs-request-id']
            state['requests'].append(rid)
            fid = hashlib.sha256((CID + ':' + rid).encode()).hexdigest()[:32]
            content = request.post_data_buffer
            item = {'file_id': fid, 'filename': unquote(request.headers['x-fs-filename']),
                    'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'status': 'available',
                    'mime': 'text/csv', 'version': 1, 'parent_id': None, 'expires_at': 2000000000}
            if not any(f['file_id'] == fid for f in state['files']):
                state['files'].append(item)
                state['bytes'][fid] = content
            if state['unknown']:
                state['unknown'] = False
                return route.abort('failed')
            return response(item, 201)
        if path == base + '/files':
            query = parse_qs(parsed.query)
            if query:
                fid = hashlib.sha256((CID + ':' + query['request_id'][0]).encode()).hexdigest()[:32]
                found = next((f for f in state['files'] if f['file_id'] == fid), None)
                return response(found or {}, 200 if found else 404)
            return response({'items': state['files']})
        if path == base + '/turns':
            value = request.post_data_json
            inputs = [f for f in state['files'] if f['file_id'] in value.get('file_ids', [])]
            fid = ('d' if not state['turns'] else 'e') * 32
            derived = {'file_id': fid, 'filename': '核对结果.xlsx', 'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'size': len(output.getvalue()), 'sha256': hashlib.sha256(output.getvalue()).hexdigest(), 'version': len(state['turns']) + 2,
                'parent_id': inputs[0]['file_id'], 'status': 'available', 'expires_at': 2000000000}
            state['files'].append(derived)
            state['bytes'][fid] = output.getvalue()
            state['turns'].append({'turn_id': fid, 'client_request_id': value['client_request_id'], 'text': value['text'],
                'state': 'completed', 'files': {'inputs': inputs, 'generated': [derived]},
                'file_bindings': {'inputs': value['file_ids'], 'generated': [fid]}, 'reply': '已按要求修改。', 'artifacts': []})
            return response({'turn_id': fid, 'state': 'completed'}, 202)
        if path.startswith(base + '/files/'):
            return route.continue_()  # Real loopback response allows Chromium download completion.
        return route.fulfill(status=404, body='missing')

    shots = Path(tempfile.mkdtemp(prefix='fs-materials-ui-'))
    with ThreadingHTTPServer(('127.0.0.1', 0), Downloads) as server, sync_playwright() as playwright:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000}, accept_downloads=True)
        page.route(origin + '/**', serve)
        page.goto(origin + '/')
        expect(page.locator('#file-input')).to_be_enabled()
        page.locator('#attachments').evaluate('(element) => element.open = true')
        page.locator('#file-input').set_input_files({'name': '业务.csv', 'mimeType': 'text/csv', 'buffer': b'amount\n2\n'})
        page.get_by_role('button', name='核对原上传').wait_for()
        page.reload()
        page.locator('#attachments').evaluate('(element) => element.open = true')
        page.get_by_role('button', name='核对原上传').click()
        page.get_by_role('checkbox').wait_for()
        expect(page.get_by_role('checkbox')).to_be_enabled()
        page.get_by_role('checkbox').focus()
        page.keyboard.press('Space')
        assert page.get_by_role('checkbox').is_checked()
        page.get_by_label('给 Hermes 发消息').fill('核对并修改金额')
        page.get_by_label('给 Hermes 发消息').press('Control+Enter')
        page.get_by_role('button', name='用于下一轮追问').wait_for()
        assert len(state['requests']) == 1
        assert page.locator('iframe').count() == 0
        for theme in ('light', 'dark'):
            page.evaluate('(theme) => FSTheme.set(theme)', theme)
            assert page.locator('html').get_attribute('data-fs-theme') == theme
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(shots / (theme + '.png')), full_page=True)
        with page.expect_download() as received:
            page.get_by_role('link', name='下载文件', exact=True).last.click()
        received.value.save_as(str(shots / 'download.xlsx'))
        assert (shots / 'download.xlsx').read_bytes() == output.getvalue()
        page.get_by_role('button', name='用于下一轮追问').click()
        assert page.locator('#message-input').evaluate('(element) => element === document.activeElement')
        page.get_by_label('给 Hermes 发消息').fill('继续修改此版本')
        page.get_by_role('button', name='发送', exact=True).click()
        expect(page.locator('.message.assistant')).to_have_count(2)
        assert state['turns'][1]['file_bindings']['inputs'] == ['d' * 32]
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('#conversation-main').evaluate('(element) => element.getBoundingClientRect().bottom >= document.querySelector("#status").getBoundingClientRect().bottom')
        page.screenshot(path=str(shots / 'mobile-dark.png'), full_page=True)
        browser.close()
        server.shutdown()
        thread.join(timeout=5)
    print('materials Chromium UI interactions/theme/mobile/download passed; screenshots:', shots)


if __name__ == '__main__':
    check()
