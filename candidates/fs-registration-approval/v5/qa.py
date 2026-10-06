"""Repeatable local tests + real Chromium guest/pending flow and labelled UI fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from auth_candidate import PREFIX
import test_candidate
import test_integration
import test_recovery
import test_schema
import test_posix


def browser_qa(out):
    from playwright.sync_api import sync_playwright
    from integrated_server import SYNTHETIC_PASSWORD
    from native_integration import policy
    checks=[];sandbox=tempfile.TemporaryDirectory(prefix='fs-registration-')
    process=subprocess.Popen([sys.executable,'-u','preview.py','--sandbox',sandbox.name],cwd=Path(__file__).parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        url=process.stdout.readline().strip().split('Local synthetic preview: ',1)[1]
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                user=browser.new_context(viewport={'width':390,'height':844}).new_page()
                errors=[];user.on('pageerror',lambda e:errors.append(str(e)))
                user.goto(url);user.locator('#register').wait_for(state='visible')
                user.locator('#theme').click();user.screenshot(path=str(out/'guest-mobile.png'),full_page=True)
                assert user.evaluate('document.documentElement.scrollWidth <= innerWidth')
                checks.append('real_local_guest_mobile_dark_layout')
                form=user.locator('#register')
                for field,value in {'username':'browser.integrated','password':SYNTHETIC_PASSWORD,'team':'Synthetic browser','purpose':'Native source HTTP integration'}.items():form.locator('[name='+field+']').fill(value)
                form.locator('button').click();user.get_by_text('注册成功，申请待审批。请登录查看进度。',exact=True).wait_for()
                form=user.locator('#login');form.locator('[name=username]').fill('browser.integrated');form.locator('[name=password]').fill(SYNTHETIC_PASSWORD);form.locator('button').click()
                user.locator('#account').wait_for(state='visible');assert '待审批' in user.locator('#state').inner_text()
                checks.append('real_local_pending_registration_login')
                admin=browser.new_context(viewport={'width':1440,'height':1000}).new_page()
                admin.goto(url);form=admin.locator('#native-login');form.locator('[name=username]').fill(sorted(policy.ADMINS)[0]);form.locator('[name=password]').fill(SYNTHETIC_PASSWORD);form.locator('button').click()
                admin.locator('#admin').wait_for(state='visible');admin.get_by_role('button',name='批准全局只读',exact=True).wait_for()
                checks.append('native_source_password_signature_live_group_admin_ui')
                admin.screenshot(path=str(out/'native-admin-real-local.png'),full_page=True)
                admin.on('dialog',lambda d:d.accept('Synthetic browser manually verified'))
                admin.get_by_role('button',name='批准全局只读',exact=True).click();admin.get_by_role('button',name='撤销授权',exact=True).wait_for()
                checks.append('real_admin_api_approval_no_route_fulfill')
                user.reload();user.locator('#approved').wait_for(state='visible')
                result=user.evaluate("async()=>{let r=await fetch('/dashboard/tasks/api/projects');return [r.status,await r.json()]}")
                assert result[0]==200 and result[1]['subject'].startswith('reg:') and result[1]['consumerRole']=='viewer'
                checks.append('registered_uuid_trusted_proxy_native_consumer_viewer')
                assert user.evaluate("async()=> (await fetch('/dashboard/tasks/api/projects',{method:'POST'})).status")==403
                checks.append('registered_write_denied_before_consumer')
                user.screenshot(path=str(out/'approved-mobile-real-local.png'),full_page=True)
                admin.get_by_role('button',name='撤销授权',exact=True).click();admin.get_by_text('审批状态已更新',exact=True).wait_for()
                # Wait for the actual revoked state rather than reusing a previous message.
                admin.locator("#requests article h3").filter(has_text="revoked").wait_for(state="visible")
                assert user.evaluate("async()=> (await fetch('/dashboard/tasks/api/projects')).status")==401
                checks.append('real_admin_revoke_existing_user_cookie_rejected')
                user.reload();user.locator('#guest').wait_for(state='visible')
                checks.append('revoked_ui_requires_login')
                admin.locator('#logout').click();admin.locator('#guest').wait_for(state='visible')
                checks.append('native_and_registration_logout_cookies_cleared')
                assert not errors;checks.append('no_javascript_errors')
            finally:browser.close()
    finally:
        process.terminate();process.wait(timeout=10);process.stdout.close();process.stderr.close();sandbox.cleanup()
    return checks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--browser', action='store_true')
    args=parser.parse_args()
    out=Path(args.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(m) for m in (test_candidate,test_integration,test_recovery,test_schema,test_posix)])
    with (out/'unit-tests.txt').open('w', encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    evidence={'at':datetime.now(timezone.utc).isoformat(),'scope':'local synthetic only',
              'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
              'skipped':[{'test':str(t),'reason':reason} for t,reason in result.skipped],
              'production_connected':False,'deployed':False,'browser':None}
    if args.browser:
        try:
            evidence['browser']={'checks':browser_qa(out),'passed':True,
                'admin':'real local native-source authentication and real approval API; synthetic credentials and business payload only; no route.fulfill'}
        except Exception as exc:
            evidence['browser']={'passed':False,'error_type':type(exc).__name__,'detail':str(exc)[:1200]}
    evidence['source_sha256']={str(p.relative_to(Path(__file__).parent)).replace('\\','/'):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.html','.css')}
    (out/'recovery-events.json').write_text(json.dumps(test_recovery.EVIDENCE,indent=2)+'\n',encoding='utf-8')
    (out/'schema-events.json').write_text(json.dumps(test_schema.EVIDENCE,indent=2)+'\n',encoding='utf-8')
    (out/'validation.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in evidence.items() if k!='source_sha256'},ensure_ascii=True))
    return 0 if result.wasSuccessful() and (not args.browser or evidence['browser']['passed']) else 1


if __name__=='__main__':
    sys.exit(main())
