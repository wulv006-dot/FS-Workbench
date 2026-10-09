"""Isolated browser fixtures; every request is intercepted, no production calls."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'source/web'
checks = 0

def check(value, description):
    global checks
    assert value, description
    checks += 1

def run():
    state = {'role': 'guest', 'items': [], 'posts': [], 'failure': {}, 'login': 401}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 700})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            path = urlsplit(request.url).path
            if '/api/' not in path:
                name = path.rsplit('/', 1)[-1] or 'index.html'
                if name not in {'index.html', 'app.js', 'access.css', 'base.css'}:
                    route.abort(); return
                route.fulfill(body=(WEB / name).read_bytes(), content_type={'html':'text/html', 'js':'text/javascript', 'css':'text/css'}[name.rsplit('.',1)[-1]])
                return
            action = path.rsplit('/', 1)[-1]
            status, result = 200, {}
            if action == 'bootstrap': result = {'csrf': 'fixture-csrf', 'account': {'role': state['role']}}
            elif action == 'requests': result = {'items': state['items']}
            elif action == 'audit': result = {'items': []}
            elif action in {'native-login', 'login'}:
                status = state['login']; result = {'error':'invalid credentials'}
                if status == 200: state['role'] = 'admin'
                if status == 0: route.abort(); return
            elif action in {'decision', 'revoke'}:
                body = request.post_data_json
                check(request.headers.get('x-csrf-token') == 'fixture-csrf', 'CSRF retained')
                state['posts'].append((action, body))
                status = state['failure'].get(body['request_id'], 200)
                if status == 0: route.abort(); return
                result = {'error': '�����ѱ仯����ˢ�º�����'}
            else:
                route.abort(); return
            route.fulfill(status=status, json=result)

        page.route('**/*', respond)
        def load():
            page.goto('http://127.0.0.1:9876/__auth/access/')
            page.wait_for_function("document.getElementById('native-box').hidden === (document.getElementById('admin').hidden === false)")

        load()
        for form_id in ['native-login', 'login']:
            form = page.locator('#' + form_id)
            form.locator('[name=username]').fill('fixture_user')
            form.locator('[name=password]').fill('wrong-fixture-password')
            form.locator('button').click()
            alert = form.get_by_role('alert')
            alert.wait_for(state='visible')
            check(alert.inner_text() == '�˺Ż����������������ԡ�', 'Chinese credential error beside each login')
            check(form.locator('[name=password]').input_value() == 'wrong-fixture-password', 'failed login preserves input')
            check(form.locator('button').is_enabled(), 'failed login permits retry')
            rect = alert.bounding_box()
            check(rect['y'] >= 0 and rect['y'] + rect['height'] <= 701, 'error is within viewport after submit')
        state['login'] = 0
        page.locator('#native-login button').click()
        page.wait_for_function("document.querySelector('#native-login [role=alert]').textContent.includes('�����ж�')")
        check(page.locator('#native-login button').is_enabled(), 'network failure recovers login button')
        state['login'] = 200
        page.locator('#native-login button').click()
        page.locator('#admin').wait_for(state='visible')
        check(page.locator('#native-box').is_hidden(), 'successful login restores admin panel')

        def rows(status='pending', count=3):
            return [{'id': str(i), 'name': 'fixture_' + str(i), 'status': status, 'version': i, 'team': '����', 'purpose': '��������', 'cursor': i} for i in range(1, count+1)]
        def refresh(items):
            state['items'] = items
            with page.expect_response(lambda response: '/api/requests' in response.url):
                page.locator('#refresh').click()
            page.wait_for_function('(n) => document.querySelectorAll("#requests article").length === n && document.getElementById("selection").textContent.includes("��ѡ 0")', arg=len(items))
        dialog_state = {'accept': True}
        page.on('dialog', lambda dialog: dialog.accept() if dialog_state['accept'] else dialog.dismiss())
        refresh(rows())
        check(page.locator('#bulk-approve').is_disabled(), 'empty selection cannot approve')
        page.locator('#select-all').check()
        check(page.locator('#bulk-approve').is_enabled() and page.locator('#bulk-revoke').is_disabled(), 'only matching pending actions enabled')
        page.locator('#bulk-approve').click()
        check(not state['posts'], 'blank reason sends no approval')
        page.locator('#bulk-reason').fill('�˹���ʵ����')
        dialog_state['accept'] = False
        page.locator('#bulk-approve').click()
        check(not state['posts'], 'cancel confirmation sends no approval')
        dialog_state['accept'] = True
        page.locator('#bulk-approve').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('����� 3 / 3')")
        check([b['request_id'] for _, b in state['posts']] == ['1','2','3'], 'exact selected IDs sent once in sequence')
        check(all(b['reason']=='�˹���ʵ����' and b['action']=='approve' and b['version']==int(b['request_id']) for _,b in state['posts']), 'reason and CAS versions retained')
        check(page.locator('#results p').count()==3, 'each result remains visible after refresh')
        check(page.locator('#bulk-approve').is_disabled(), 'selection cleared after operation')

        state['posts'] = []; state['failure'] = {'2':409}
        refresh(rows()); page.locator('#select-all').check(); page.locator('#bulk-reject').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('ʧ�� 1')")
        check(len(state['posts'])==3 and 'δ���' in page.locator('#results').inner_text(), 'CAS conflict reported separately; no false all-success')

        state['posts'] = []; state['failure'] = {'2':0}
        refresh(rows('approved')); page.locator('#select-all').check(); page.locator('#bulk-revoke').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('���ڴ��˶Խ��')")
        check(len(state['posts'])==2, 'unknown result stops remaining writes')
        check(all(a=='revoke' and 'action' not in b for a,b in state['posts']), 'revoke contract retained')
        check('��Ҫֱ������' in page.locator('#results').inner_text(), 'unknown instructions explicit')

        for status in [503, 403]:
            state['posts'] = []; state['failure'] = {'1':status}
            refresh(rows()); page.locator('#select-all').check(); page.locator('#bulk-reject').click()
            page.wait_for_function("document.getElementById('message').textContent.includes('����� 0 / 3')")
            page.wait_for_function("document.getElementById('refresh').disabled === false")
            check(len(state['posts'])==1, 'server uncertainty or permission denial stops further writes')

        state['failure'] = {}; state['posts'] = []
        mixed = rows(); mixed[1]['status'] = 'approved'
        refresh(mixed); page.locator('#select-all').check()
        check(all(page.locator('#bulk-' + a).is_disabled() for a in ['approve','reject','revoke']), 'mixed statuses cannot mass-change')
        page.locator('#select-all').uncheck()
        page.locator('#requests input').first.check()
        check(page.locator('#bulk-approve').is_enabled(), 'individual selection works')
        page.locator('#admin h2').click()
        page.screenshot(path=str(ROOT/'evidence/admin-ui.png'), full_page=True)
        check(not errors, 'no browser JavaScript errors')
        browser.close()
    return {'passed': True, 'checks': checks, 'environment': 'Windows Chrome, isolated intercepted HTTP fixtures', 'productionRequests': 0, 'realAccountActions': 0}

if __name__ == '__main__':
    result = run()
    (ROOT/'evidence/ui-test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
