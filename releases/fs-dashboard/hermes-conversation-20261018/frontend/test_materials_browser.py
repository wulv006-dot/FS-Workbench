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
NAV = UI.parent / 'releases/fs-dashboard/hermes-navigation-range-20261019/candidate'
NAV_JS = UI.parent / 'releases/fs-dashboard/campaign-analytics-20261023/navigation/source/nav.js'
CID = 'a' * 32
TITLE = '合成验收长中文会话标题：附件分页与确定性修订，不访问业务数据。' * 3


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
        if path == '/__hub/hermes-nav.css':
            return route.fulfill(body=(NAV / 'hermes-nav.css').read_bytes(), content_type='text/css')
        if path == '/__hub/nav.js':
            return route.fulfill(body=NAV_JS.read_bytes(), content_type='text/javascript')
        if path == '/__auth/verify':
            return route.fulfill(status=200, body='', headers={'X-Auth-User': 'synthetic-ui', 'X-Auth-Role': 'admin'})
        for name, source, mime in [('conversation.js', HERE / 'conversation.js', 'text/javascript'),
                ('conversation.css', HERE / 'conversation.css', 'text/css'),
                ('fs-tokens.css', UI / 'tokens/fs-tokens.css', 'text/css'),
                ('fs-ui.css', UI / 'components/fs-ui.css', 'text/css'),
                ('fs-theme.js', UI / 'adapters/fs-theme.js', 'text/javascript')]:
            if path.endswith('/' + name):
                return route.fulfill(body=source.read_bytes(), content_type=mime)
        if path == '/api/hermes/conversations':
            return response({'items': [{'conversation_id': CID, 'title': TITLE}] + [
                {'conversation_id': '%032x' % i, 'title': '历史合成会话 ' + str(i) + TITLE} for i in range(98)]})
        base = '/api/hermes/conversations/' + CID
        if path == base:
            return response({'conversation_id': CID, 'title': TITLE, 'turns': state['turns'], 'last_seq': 0})
        if '/materials' in path:
            raise AssertionError('legacy materials endpoint must not be called')
        if path == base + '/events':
            return route.fulfill(body=': connected\n\n', content_type='text/event-stream')
        if path == base + '/files' and request.method == 'POST':
            rid = request.headers['x-fs-request-id']
            state['requests'].append(rid)
            fid = hashlib.sha256((CID + ':' + rid).encode()).hexdigest()[:32]
            content = request.post_data_buffer
            if state.get('reject_upload'): return response({'error':'unsupported_file_type'},422)
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
        if path.startswith(base + '/runs/'):
            value = request.post_data_json
            if path.endswith('/stop'):
                state['turns'][-1]['state'] = 'cancelled'
            else: state['steer'] = value
            return response({'state':'accepted'},202)
        if path == base + '/turns':
            value = request.post_data_json
            inputs = [f for f in state['files'] if f['file_id'] in value.get('file_ids', [])]
            fid = ('d' if not state['turns'] else 'e') * 32
            derived = {'file_id': fid, 'filename': '核对结果.xlsx', 'mime': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'size': len(output.getvalue()), 'sha256': hashlib.sha256(output.getvalue()).hexdigest(), 'version': len(state['turns']) + 2,
                'parent_id': inputs[0]['file_id'] if inputs else None, 'status': 'available', 'expires_at': 2000000000}
            state['files'].append(derived)
            state['bytes'][fid] = output.getvalue()
            state['turns'].append({'turn_id': fid, 'client_request_id': value['client_request_id'], 'text': value['text'],
                'state': 'completed', 'files': {'inputs': inputs, 'generated': [derived]},
                'file_bindings': {'inputs': value.get('file_ids', []), 'generated': [fid]}, 'reply': '# 核对完成\n已结合附件保留完整回答。\n\n| 项目 | 结果 |\n| --- | --- |\n| 金额 | 7 |\n\n```python\nprint(7)\n```\n<script>此处仅作文字显示</script>\n[危险链接](javascript:alert(1))', 'artifacts': []})
            return response({'turn_id': fid, 'state': 'completed'}, 202)
        if path.startswith(base + '/files/'):
            return route.continue_()  # Real loopback response allows Chromium download completion.
        return route.fulfill(status=404, body='missing')

    shots = Path(tempfile.mkdtemp(prefix='fs-native-chat-ui-'))
    with ThreadingHTTPServer(('127.0.0.1', 0), Downloads) as server, sync_playwright() as playwright:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 800}, accept_downloads=True)
        page.route(origin + '/**', serve)
        page.goto(origin + '/')
        expect(page.locator('#file-input')).to_be_enabled()
        assert page.locator('#run-material').count() == 0
        assert page.locator('#material-jobs').count() == 0
        assert page.locator('input[type=checkbox]').count() == 0
        assert page.locator('#file-input').get_attribute('accept') is None
        page.screenshot(path=str(shots/'empty-light.png'), full_page=True)
        original = b'%PDF-synthetic-raw-original'
        page.locator('#file-input').set_input_files({'name':'说明_原始附件.pdf','mimeType':'application/pdf','buffer':original})
        page.get_by_role('button',name='核对原上传').wait_for()
        expect(page.get_by_role('button',name='发送',exact=True)).to_be_disabled()
        page.reload()
        page.get_by_role('button',name='核对原上传').click()
        expect(page.locator('#file-choices')).to_contain_text('说明_原始附件.pdf · 已上传')
        assert next(iter(state['bytes'].values())) == original
        assert len(state['requests']) == 1
        page.get_by_label('给 Hermes 发消息').fill('请结合这份附件，核对并说明金额。')
        page.get_by_label('给 Hermes 发消息').press('Shift+Enter')
        assert page.get_by_label('给 Hermes 发消息').input_value().endswith('\n')
        page.get_by_label('给 Hermes 发消息').press('Enter')
        expect(page.locator('.message.assistant')).to_have_count(1)
        expect(page.locator('.reply-body')).to_contain_text('<script>此处仅作文字显示</script>')
        assert page.locator('.reply-body script').count() == 0
        assert page.locator('a[href^="javascript:"]').count() == 0
        expect(page.locator('.reply-body table')).to_have_count(1)
        expect(page.locator('.reply-body pre code')).to_have_text('print(7)')
        expect(page.locator('#file-choices')).to_be_empty()
        assert page.get_by_label('给 Hermes 发消息').input_value() == ''
        assert not page.get_by_role('button',name='用于下一轮追问').count()
        assert page.locator('#conversation-title').get_attribute('title') == TITLE
        assert page.locator('#conversation-title').evaluate('(e)=>e.getBoundingClientRect().height < 70')
        with page.expect_download() as received:
            page.get_by_role('link',name='下载文件',exact=True).last.click()
        received.value.save_as(str(shots/'download.xlsx'))
        assert (shots/'download.xlsx').read_bytes() == output.getvalue()
        for width,name in ((1280,'desktop'),(390,'mobile')):
            page.set_viewport_size({'width':width,'height':844})
            for theme in ('light','dark'):
                page.evaluate('(theme)=>FSTheme.set(theme)',theme)
                page.get_by_label('给 Hermes 发消息').focus()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#attachments').evaluate('(e)=>getComputedStyle(e).overflowY !== "auto"')
                page.screenshot(path=str(shots/(name+'-'+theme+'.png')),full_page=True)
        page.set_viewport_size({'width':1280,'height':800})
        # Ordinary follow-up needs no file checkbox/rebinding UI. The fixture
        # proves the text route, not backend native SDK context inheritance.
        page.get_by_label('给 Hermes 发消息').fill('继续解释上一个结果文件。')
        page.get_by_role('button',name='发送',exact=True).click()
        expect(page.locator('.message.assistant')).to_have_count(2)
        assert state['turns'][1]['file_bindings']['inputs'] == []
        state['reject_upload'] = True
        page.locator('#file-input').set_input_files({'name':'被拒绝的附件.bin','mimeType':'application/octet-stream','buffer':b'synthetic'})
        expect(page.locator('#upload-list')).to_contain_text('上传失败')
        page.screenshot(path=str(shots/'upload-failed-dark.png'),full_page=True)
        page.get_by_role('button',name='移除附件',exact=True).click()
        state['reject_upload'] = False
        # Verify the real drag/drop handler routes original File bytes too.
        page.locator('#composer').evaluate("""element => {
            const data = new DataTransfer(); data.items.add(new File(['dropped bytes'],'拖放.txt',{type:'text/plain'}));
            element.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));
        }""")
        expect(page.locator('#file-choices')).to_contain_text('拖放.txt · 已上传')
        page.get_by_role('button',name='移除附件：拖放.txt',exact=True).focus()
        page.keyboard.press('Enter')
        expect(page.locator('#file-choices')).to_be_empty()
        state['turns'][-1]['state']='running'
        state['turns'][-1]['run_id']='run_'+'a'*32
        state['turns'][-1]['progress']={'type':'tool.started','tool':'mcp__fcro__fc_read_conversation_file'}
        page.reload()
        expect(page.get_by_role('button',name='停止当前任务')).to_be_visible()
        expect(page.get_by_role('button',name='添加附件',exact=True)).to_be_disabled()
        expect(page.locator('#file-help')).to_contain_text('可继续发送文字补充')
        page.get_by_label('给 Hermes 发消息').fill('请保留原文件，再补充说明。')
        page.get_by_role('button',name='补充当前任务').click()
        assert state['steer']['text']=='请保留原文件，再补充说明。'
        assert 'file_ids' not in state['steer']
        page.screenshot(path=str(shots/'running-dark.png'),full_page=True)
        page.get_by_role('button',name='停止当前任务').click()
        expect(page.get_by_role('button',name='停止当前任务')).to_be_hidden()
        expect(page.locator('#messages')).to_contain_text('已停止；上方保留停止前的回复。')
        page.screenshot(path=str(shots/'stopped-dark.png'),full_page=True)
        browser.close()
        server.shutdown()
        thread.join(timeout=5)
    print('native chat Chromium: raw upload/recovery/chips/Markdown/table/code/HTML safety/download/followup/drag/failure/steer/stop/light/dark/390 passed; screenshots:', shots)


if __name__ == '__main__':
    check()
