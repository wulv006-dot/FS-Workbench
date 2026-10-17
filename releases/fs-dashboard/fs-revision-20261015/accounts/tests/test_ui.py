"""Headless Chrome with all requests intercepted; no production login or writes."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
WEB = HERE / 'candidate/runtime/web'
checks = []


def check(value, label):
    assert value, label
    checks.append(label)


def run():
    modules = [dict(id=key, label=label, can_edit=edit, href='/dashboard/') for key, label, edit in (
        ('business', '经营分析', False), ('marketing', '营销分析', False), ('weekly', '运营周报', False),
        ('tasks', '工作任务台', True), ('green_plan', '绿茵计划', True), ('fc_ops', 'FC运营看板', False), ('players', 'FC球员维护', False))]
    names = ['wulv', 'chenchao', 'DY', 'fstech', 'mmoexp', 'fc27admin', 'dongwenxin']
    items = [dict(subject='native:' + name, name=name, role='admin' if i < 4 else 'readonly', enabled=i < 5,
        modules={module['id']: 'readonly' for module in modules}, state='native' if i < 5 else 'legacy_only', sources=['portal'] if i < 5 else ['fc_legacy'], revision='synthetic-revision-' + name) for i, name in enumerate(names)]
    state = {'role': 'admin', 'posts': [], 'failure': 0}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1100, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            path = urlsplit(request.url).path
            if '/api/' not in path:
                name = path.rsplit('/', 1)[-1] or 'index.html'
                if name not in ('index.html', 'app.js', 'access.css', 'base.css'):
                    route.abort(); return
                route.fulfill(body=(WEB / name).read_bytes(), content_type={'html': 'text/html', 'js': 'text/javascript', 'css': 'text/css'}[name.rsplit('.', 1)[1]])
                return
            action = path.rsplit('/', 1)[-1]
            result = {'items': []}
            if action == 'bootstrap':
                result = {'csrf': 'synthetic-csrf', 'account': {'role': state['role'], 'name': 'wulv'}, 'permission_modules': modules}
            elif action == 'accounts':
                result = {'items': items}
            elif action in ('account-password', 'account-permissions'):
                state['posts'].append((action, request.post_data_json, request.headers))
                if state['failure'] == -1:
                    route.abort(); return
                if state['failure']:
                    route.fulfill(status=state['failure'], json={'error': '账号已变化，请刷新后重试'}); return
                body = request.post_data_json
                if action == 'account-permissions':
                    next(item for item in items if item['subject'] == body['subject']).update(enabled=body['enabled'], modules=body['modules'])
                result = {'ok': True, 'sessions_revoked': True, 'self_changed': body['subject'] == 'native:wulv'}
                if result['self_changed']:
                    state['role'] = 'guest'
            route.fulfill(json=result)

        page.route('**/*', respond)
        page.goto('http://127.0.0.1:9876/__auth/access/')
        page.wait_for_function("document.querySelectorAll('#all-accounts article').length===7")
        check(page.locator('#account-count').inner_text() == '全部账号：7 个', 'complete seven-account count')
        check(page.locator('#all-accounts article').count() == 7, 'seven rows shown')
        check('fstech' in page.locator('#all-accounts').inner_text(), 'fourth existing admin shown')
        check('旧 FC 账号库' in page.locator('#all-accounts').inner_text(), 'legacy source status transparent')
        check('先设置统一密码' in page.locator('#all-accounts').inner_text(), 'legacy activation steps visible')
        reader = page.locator('#all-accounts article').filter(has=page.get_by_role('heading', name='mmoexp · 普通账号 · 已启用', exact=True))
        reader.locator('summary').first.click()
        form = reader.locator('form').first
        check(form.locator('input[type=password]').count() == 3, 'new password confirmation and admin reauthentication')
        check(form.locator('[name=new_password]').get_attribute('minlength') == '12', 'password minimum enforced')
        form.locator('[name=new_password]').fill('Synthetic-new-password-91')
        form.locator('[name=confirm_password]').fill('Synthetic-new-password-91')
        form.locator('[name=admin_password]').fill('Synthetic-password-42')
        form.locator('[name=reason]').fill('合成忘记密码测试')
        form.locator('button').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('全部旧会话已失效')")
        action, body, headers = state['posts'][-1]
        check(action == 'account-password', 'password route used')
        check(body['subject'] == 'native:mmoexp', 'exact target subject retained')
        check(body['revision'] == 'synthetic-revision-mmoexp', 'opaque CAS revision retained')
        check(headers['x-csrf-token'] == 'synthetic-csrf', 'CSRF sent')
        check(len(state['posts']) == 1, 'single mutation request')
        check(page.locator('#all-accounts input[type=password]').evaluate_all('(inputs)=>inputs.every(input=>input.value==="")'), 'password fields cleared after save')
        reader = page.locator('#all-accounts article').filter(has=page.get_by_role('heading', name='mmoexp · 普通账号 · 已启用', exact=True))
        reader.locator('summary').nth(1).click()
        form = reader.locator('form').nth(1)
        check(form.locator('select').count() == 7, 'seven current modules editable')
        check(form.locator('option[value=editor]').count() == 2, 'editor restricted to two task modules')
        form.locator('select').first.select_option('none')
        form.locator('select').nth(3).select_option('editor')
        form.locator('[name=admin_password]').fill('Synthetic-password-42')
        form.locator('[name=reason]').fill('合成模块权限测试')
        form.locator('button').click()
        page.wait_for_function("document.querySelectorAll('#all-accounts input[type=password]').length===28 && [...document.querySelectorAll('#all-accounts input[type=password]')].every(input=>input.value==='')")
        body = state['posts'][-1][1]
        check(body['enabled'] is True, 'enabled is boolean')
        check(body['modules']['business'] == 'none' and body['modules']['tasks'] == 'editor', 'chosen grants preserved')
        check(set(body) == {'subject', 'revision', 'admin_password', 'reason', 'enabled', 'modules'}, 'no unintended mutation fields')
        admin = page.locator('#all-accounts article').first
        check(admin.locator('select').count() == 0, 'existing admin scope fixed')
        admin.locator('summary').nth(1).click()
        check('至少一名' in admin.inner_text(), 'last admin protection explained')
        reader = page.locator('#all-accounts article').filter(has=page.get_by_role('heading', name='mmoexp · 普通账号 · 已启用', exact=True))
        reader.locator('summary').first.click()
        form = reader.locator('form').first
        for key in ('new_password', 'confirm_password', 'admin_password'):
            form.locator('[name=' + key + ']').fill('Synthetic-new-password-91')
        form.locator('[name=reason]').fill('合成连接中断测试')
        state['failure'] = -1
        form.locator('button').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('连接中断')")
        check(len(state['posts']) == 3, 'unknown response is not retried')
        check(form.locator('input[type=password]').evaluate_all('(inputs)=>inputs.every(input=>input.value==="")'), 'password fields cleared on unknown response')
        check(form.locator('button').is_enabled(), 'failed request restores controls')
        page.set_viewport_size({'width': 390, 'height': 844})
        check(page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth'), 'narrow layout has no horizontal overflow')
        page.screenshot(path=str(HERE / 'ui-synthetic.png'), full_page=True)
        state['failure'] = 0
        admin.locator('summary').first.click()
        form = admin.locator('form').first
        for key in ('new_password', 'confirm_password', 'admin_password'):
            form.locator('[name=' + key + ']').fill('Synthetic-new-password-91')
        form.locator('[name=reason]').fill('合成本人密码测试')
        form.locator('button').click()
        page.wait_for_function("document.getElementById('message').textContent.includes('请重新登录')")
        check(page.locator('#admin').is_hidden() and page.locator('#guest').is_visible(), 'own password change returns to login')
        check(not errors, 'no browser JavaScript errors')
        browser.close()
    (HERE / 'ui-result.json').write_text(json.dumps({'status': 'passed', 'checks': len(checks), 'labels': checks, 'environment': 'Windows Chrome headless; all requests intercepted; synthetic accounts only'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': len(checks), 'status': 'passed'}))


if __name__ == '__main__':
    run()
