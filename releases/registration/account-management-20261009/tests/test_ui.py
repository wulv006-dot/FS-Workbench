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
    modules=[dict(id=key,label=label,can_edit=key in ('tasks','green_plan'),href='/dashboard/') for key,label in [('business','经营分析'),('marketing','营销分析'),('weekly','运营周报'),('tasks','工作任务台'),('green_plan','绿茵计划'),('fc_ops','FC运营看板'),('players','FC球员维护')]]
    defaults={m['id']:'readonly' for m in modules}
    state = {'role': 'guest', 'items': [], 'posts': [], 'failure': {}, 'login': 401, 'members': [], 'members_failure': 200, 'permission_failure':200}
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
            if action == 'bootstrap': result = {'csrf': 'fixture-csrf', 'account': {'role': state['role']},'permission_modules':modules}
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
                result = {'error': '申请已变化，请刷新后重试'}
            elif action == 'permissions':
                body=request.post_data_json;state['posts'].append((action,body));status=state['permission_failure']
                check(request.headers.get('x-csrf-token')=='fixture-csrf','permission update retains CSRF')
                if status==0:route.abort();return
                result=dict(version=42,modules=body['permissions'],sessions_revoked=True,member=dict(username='reg:12345678-1234-1234-1234-123456789abc',displayName='fixture_1',role='viewer',active=True) if 'editor' in body['permissions'].values() else None)
                if status==200:state['items'][0]['permissions']=dict(version=42,modules=body['permissions'])
            elif action == 'members':
                status=state['members_failure'];result={'members':state['members'],'error':'登记服务不可用'}
                if request.method=='POST':state['members'].append(request.post_data_json)
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
            check(alert.inner_text() == '账号或密码错误，请检查后重试。', 'Chinese credential error beside each login')
            check(form.locator('[name=password]').input_value() == 'wrong-fixture-password', 'failed login preserves input')
            check(form.locator('button').is_enabled(), 'failed login permits retry')
            rect = alert.bounding_box()
            check(rect['y'] >= 0 and rect['y'] + rect['height'] <= 701, 'error is within viewport after submit')
        state['login'] = 0
        page.locator('#native-login button').click()
        page.wait_for_function("document.querySelector('#native-login [role=alert]').textContent.includes('连接中断')")
        check(page.locator('#native-login button').is_enabled(), 'network failure recovers login button')
        state['login'] = 200
        page.locator('#native-login button').click()
        page.locator('#admin').wait_for(state='visible')
        check(page.locator('#native-box').is_hidden(), 'successful login restores admin panel')

        def rows(status='pending', count=3):
            return [{'id': str(i), 'name': 'fixture_' + str(i), 'status': status, 'version': i, 'team': '测试', 'purpose': '隔离验收', 'cursor': i} for i in range(1, count+1)]
        def refresh(items):
            state['items'] = items
            with page.expect_response(lambda response: '/api/requests' in response.url):
                page.locator('#refresh').click()
            page.wait_for_function('(n) => document.querySelectorAll("#requests article").length === n && document.getElementById("selection").textContent.includes("已选 0")', arg=len(items))
        dialog_state = {'accept': True}
        page.on('dialog', lambda dialog: dialog.accept('隔离权限调整原因' if dialog.type=='prompt' else None) if dialog_state['accept'] else dialog.dismiss())
        refresh(rows())
        check(page.locator('#bulk-approve').is_disabled(), 'empty selection cannot approve')
        page.locator('#select-all').check()
        check(page.locator('#bulk-approve').is_enabled() and page.locator('#bulk-revoke').is_disabled(), 'only matching pending actions enabled')
        page.locator('#bulk-approve').click()
        check(not state['posts'], 'blank reason sends no approval')
        page.locator('#bulk-reason').fill('人工核实测试')
        dialog_state['accept'] = False
        page.locator('#bulk-approve').click()
        check(not state['posts'], 'cancel confirmation sends no approval')
        dialog_state['accept'] = True
        page.locator('#bulk-approve').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('已完成 3 / 3')")
        check([b['request_id'] for _, b in state['posts']] == ['1','2','3'], 'exact selected IDs sent once in sequence')
        check(all(b['reason']=='人工核实测试' and b['action']=='approve' and b['version']==int(b['request_id']) for _,b in state['posts']), 'reason and CAS versions retained')
        check(page.locator('#results p').count()==3, 'each result remains visible after refresh')
        check(page.locator('#bulk-approve').is_disabled(), 'selection cleared after operation')

        state['posts'] = []; state['failure'] = {'2':409}
        refresh(rows()); page.locator('#select-all').check(); page.locator('#bulk-reject').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('失败 1')")
        check(len(state['posts'])==3 and '未完成' in page.locator('#results').inner_text(), 'CAS conflict reported separately; no false all-success')

        state['posts'] = []; state['failure'] = {'2':0}
        refresh(rows('approved')); page.locator('#select-all').check(); page.locator('#bulk-revoke').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('存在待核对结果')")
        check(len(state['posts'])==2, 'unknown result stops remaining writes')
        check(all(a=='revoke' and 'action' not in b for a,b in state['posts']), 'revoke contract retained')
        check('不要直接重试' in page.locator('#results').inner_text(), 'unknown instructions explicit')

        for status in [503, 403]:
            state['posts'] = []; state['failure'] = {'1':status}
            refresh(rows()); page.locator('#select-all').check(); page.locator('#bulk-reject').click()
            page.wait_for_function("document.getElementById('message').textContent.includes('已完成 0 / 3')")
            page.wait_for_function("document.getElementById('refresh').disabled === false")
            check(len(state['posts'])==1, 'server uncertainty or permission denial stops further writes')

        state['failure'] = {}; state['posts'] = []
        mixed = rows(); mixed[1]['status'] = 'approved'
        refresh(mixed); page.locator('#select-all').check()
        check(all(page.locator('#bulk-' + a).is_disabled() for a in ['approve','reject','revoke']), 'mixed statuses cannot mass-change')
        page.locator('#select-all').uncheck()
        page.locator('#requests input').first.check()
        check(page.locator('#bulk-approve').is_enabled(), 'individual selection works')
        state['posts']=[]
        approved=rows('approved',1);approved[0]['permissions']=dict(version=0,modules=dict(defaults))
        refresh(approved)
        details=page.locator('#requests details');details.locator('summary').click()
        check(details.locator('select').count()==7,'seven module access settings shown')
        check(details.locator('option[value=editor]').count()==2,'editing offered only for approved two modules')
        details.locator('select[data-module=business]').select_option('none')
        details.locator('select[data-module=tasks]').select_option('editor')
        details.locator('button').click()
        page.wait_for_function("document.getElementById('results').textContent.includes('执行人登记已核对')")
        check(state['posts'][-1][1]['permissions']['business']=='none' and state['posts'][-1][1]['permissions']['tasks']=='editor','selected per-module values submitted')
        check(state['members'][0]['role']=='viewer','member projection carries no independent editor or admin grant')
        check('旧会话已注销' in page.locator('#results').inner_text(),'session invalidation reported')
        state['members']=[];state['members_failure']=503
        page.locator('#requests details summary').click();page.locator('#requests details button').click()
        page.wait_for_function("document.getElementById('results').textContent.includes('权限保存已成功')")
        check('登记未完成或待核对' in page.locator('#results').inner_text(),'partial projection failure not reported as complete')
        state['permission_failure']=0;state['posts']=[]
        page.locator('#requests details summary').click();page.locator('#requests details button').click()
        page.wait_for_function("document.getElementById('results').textContent.includes('不要直接重试')")
        check(len(state['posts'])==1,'unknown permission save not automatically replayed')
        page.locator('#requests details summary').click()
        page.locator('#admin h2').click()
        page.screenshot(path=str(ROOT/'evidence/admin-ui.png'), full_page=True)
        check(not errors, 'no browser JavaScript errors')
        browser.close()
    return {'passed': True, 'checks': checks, 'environment': 'Windows Chrome, isolated intercepted HTTP fixtures', 'productionRequests': 0, 'realAccountActions': 0}

if __name__ == '__main__':
    result = run()
    (ROOT/'evidence/ui-test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
