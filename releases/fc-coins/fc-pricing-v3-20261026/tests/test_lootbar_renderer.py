import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'source'))
from fc_collection import lootbar_browser


def service():
    path = ROOT/'opt/d4follow/_qd_render/qd_render_svc.py'
    spec = importlib.util.spec_from_file_location('fc_test_qd_render', path)
    mod = importlib.util.module_from_spec(spec)
    before = list(sys.path)
    try:
        with patch.dict(sys.modules, {'core_qd':types.ModuleType('core_qd')}):
            spec.loader.exec_module(mod)
    finally:
        sys.path[:] = before
    return mod


TASK = dict(platforms=['PS','XBOX','PC'], request_limit=128, timeout_seconds=60)


class RendererContract(unittest.TestCase):
    def test_shared_parser_real_original_function_wrapper_and_dom_contract(self):
        node=os.environ.get('FC_TEST_NODE') or shutil.which('node')
        if not node:raise RuntimeError('real_Node_required_for_shared_parser_contract')
        result=subprocess.run([node,str(Path(__file__).with_name('lootbar_coupon_parser.cjs'))],
            cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('5 shared real-parser cases passed',result.stdout)

    def test_browser_uses_only_own_context_and_closes_it_without_rpg_config(self):
        from test_lootbar_fallback import snapshot
        page=Mock();current=['PS']
        routes=[]
        def navigate(url,**_):
            current[0]='PS'  # The site may ignore a platform query until its control is selected.
            page.url=url
            handler=context.route.call_args.args[1]
            for kind,count in [('image',200),('font',30),('media',10),('ping',10)]:
                for i in range(count):
                    request_route=Mock()
                    request_route.request=types.SimpleNamespace(url='https://www.lootbar.com/assets/'+str(i),method='GET',resource_type=kind)
                    handler(request_route);routes.append((kind,request_route))
            for kind,path in [('document','/game-coins/fc27'),('stylesheet','/assets/site.css'),
                              ('script','/_next/static/app.js'),('xhr','/api/goods'),('fetch','/api/account')]:
                request_route=Mock()
                request_route.request=types.SimpleNamespace(url='https://www.lootbar.com'+path,method='GET',resource_type=kind)
                handler(request_route);routes.append((kind,request_route))
            return types.SimpleNamespace(status=200)
        page.goto.side_effect=navigate;page.evaluate.side_effect=lambda *_:snapshot(current[0])
        def locator(selector):
            if selector.startswith('[role="dialog"]'):return types.SimpleNamespace(count=lambda:0)
            return types.SimpleNamespace(click=lambda **_:current.__setitem__(0,{'a.icon-ps':'PS','a.icon-xbox':'XBOX','a.icon-pc':'PC'}[selector]))
        page.locator.side_effect=locator
        context=Mock();context.new_page.return_value=page
        browser=Mock();browser.new_context.return_value=context
        scope=Mock();scope.__enter__=Mock(return_value=types.SimpleNamespace(chromium=types.SimpleNamespace(launch=Mock(return_value=browser))))
        scope.__exit__=Mock(return_value=False)
        pw=types.ModuleType('playwright.sync_api');pw.sync_playwright=Mock(return_value=scope)
        ticks=iter(i/100 for i in range(10000))
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':pw}), \
                patch.object(lootbar_browser,'read_parser',return_value='function readVisibleOffer() {}'), \
                patch.object(lootbar_browser.time,'monotonic',side_effect=lambda:next(ticks)):
            result=lootbar_browser.collect(TASK)
        self.assertEqual(set(result['snapshots']),{'PS','XBOX','PC'})
        self.assertEqual(result['browser_requests_allowed'],5)
        self.assertEqual(page.goto.call_count,1)
        self.assertEqual(page.goto.call_args.args[0],lootbar_browser.BASE)
        for kind,route in routes:
            if kind in ('image','font','media','ping'):
                route.abort.assert_called_once();route.continue_.assert_not_called()
            else:route.continue_.assert_called_once()
        self.assertTrue(all('observed_at' in r for r in result['snapshots'].values()))
        context.close.assert_called_once_with();browser.close.assert_called_once_with()
        self.assertEqual(browser.new_context.call_args.kwargs,dict(locale='en-US',service_workers='block'))
        self.assertEqual([c.args[0] for c in page.locator.call_args_list if c.args[0].startswith('a.')],['a.icon-xbox','a.icon-pc'])

    def popup_case(self, when, *, closable=True, challenge=False, recognized=True, close_fails=False):
        from test_lootbar_fallback import snapshot
        page=Mock(); current=['PS']; popup=[when=='initial']; calls=[]; once=[False]
        dialog=Mock(); close=Mock()
        dialog.count.side_effect=lambda: int(popup[0] and recognized)
        dialog.locator.return_value=close
        close.count.side_effect=lambda: int(closable)
        def close_popup(**kwargs):
            calls.append('close')
            if close_fails:raise TimeoutError('close did not become actionable')
            popup[0]=False
        close.click.side_effect=close_popup
        def navigate(url,**kwargs):
            page.url=url;return types.SimpleNamespace(status=200)
        page.goto.side_effect=navigate
        page.title.return_value='Just a moment' if challenge else 'FC27 Coins'
        def read(*args):
            row=snapshot(current[0])
            if when=='after_pc' and current[0]=='PC' and not once[0]:
                popup[0]=True;once[0]=True
            return row
        page.evaluate.side_effect=read
        def locator(selector):
            if selector.startswith('[role="dialog"]'):
                calls.append('inspect_coupon');return dialog
            def click(**kwargs):
                if when=='during_click' and not once[0]:
                    popup[0]=True;once[0]=True
                if popup[0]:raise TimeoutError('coupon subtree intercepts pointer events')
                current[0]={'a.icon-ps':'PS','a.icon-xbox':'XBOX','a.icon-pc':'PC'}[selector]
                calls.append(current[0])
            return types.SimpleNamespace(click=click)
        page.locator.side_effect=locator
        context=Mock();context.new_page.return_value=page
        browser=Mock();browser.new_context.return_value=context
        scope=Mock();scope.__enter__=Mock(return_value=types.SimpleNamespace(chromium=types.SimpleNamespace(launch=Mock(return_value=browser))))
        scope.__exit__=Mock(return_value=False)
        pw=types.ModuleType('playwright.sync_api');pw.sync_playwright=Mock(return_value=scope)
        ticks=iter(i/100 for i in range(10000))
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':pw}), \
                patch.object(lootbar_browser,'read_parser',return_value='function readVisibleOffer() {}'), \
                patch.object(lootbar_browser.time,'monotonic',side_effect=lambda:next(ticks)):
            result=lootbar_browser.collect(dict(TASK,platforms=['PC','PS','XBOX']))
        return result,calls,dialog,close

    def test_observed_coupon_dialog_is_closed_without_claiming_before_platform_click(self):
        result,calls,dialog,close=self.popup_case('initial')
        self.assertEqual(set(result['snapshots']),{'PC','PS','XBOX'})
        self.assertEqual(calls.count('close'),1)
        self.assertLess(calls.index('close'),calls.index('PC'))
        dialog.locator.assert_called_with('button.dialog-coupon-close:visible')
        close.click.assert_called_once()
        self.assertNotIn('force',close.click.call_args.kwargs)

    def test_delayed_coupon_dialog_during_click_is_closed_then_selection_is_verified(self):
        result,calls,_,_=self.popup_case('during_click')
        self.assertEqual(set(result['snapshots']),{'PC','PS','XBOX'})
        self.assertEqual(calls.count('close'),1)

    def test_coupon_dialog_can_appear_after_pc_without_losing_platforms(self):
        result,calls,_,_=self.popup_case('after_pc')
        self.assertEqual(set(result['snapshots']),{'PC','PS','XBOX'})
        self.assertEqual(calls.count('close'),1)

    def test_missing_coupon_close_retains_failure_instead_of_clicking_through(self):
        result,calls,_,close=self.popup_case('initial',closable=False)
        self.assertEqual(set(result['snapshots']),{'PS'})
        self.assertEqual(set(result['platform_errors'].values()),{'lootbar_coupon_dialog_unclosed'})
        close.click.assert_not_called()
        self.assertNotIn('PC',calls)

    def test_non_coupon_dialog_is_not_closed_or_force_clicked(self):
        result,calls,_,close=self.popup_case('initial',recognized=False)
        self.assertEqual(set(result['snapshots']),{'PS'})
        self.assertEqual(set(result['platform_errors'].values()),{'lootbar_page_timeout'})
        close.click.assert_not_called()

    def test_coupon_close_failure_keeps_valid_current_platform_partial(self):
        result,calls,_,close=self.popup_case('initial',close_fails=True)
        self.assertEqual(set(result['snapshots']),{'PS'})
        self.assertEqual(set(result['platform_errors'].values()),{'lootbar_coupon_dialog_unclosed'})
        self.assertEqual(close.click.call_count,2)
        self.assertNotIn('force',close.click.call_args.kwargs)

    def test_challenge_does_not_close_even_an_identified_coupon_dialog(self):
        result,calls,_,close=self.popup_case('initial',challenge=True)
        self.assertFalse(result['snapshots'])
        self.assertEqual(set(result['platform_errors'].values()),{'challenge'})
        close.click.assert_not_called()
        self.assertNotIn('close',calls)

    def test_request_diagnostics_are_bounded_and_omit_queries_identifiers_and_headers(self):
        gate=lootbar_browser.RequestGate(128)
        for i in range(200):
            gate.allow('https://www.lootbar.com/api/coins/customer@example.com?token=secret'+str(i),'GET',resource_type='xhr')
        summary=gate.summary()
        self.assertEqual(summary['browser_requests_allowed'],128)
        self.assertEqual(summary['stop_reason'],'request_budget_exhausted')
        self.assertLessEqual(len(summary['paths']),25)
        text=json.dumps(summary)
        self.assertNotIn('secret',text);self.assertNotIn('@',text);self.assertNotIn('?',text)
        self.assertIn('/api/coins/*',text)

    def test_only_main_document_denial_stops_the_price_pass(self):
        page=types.SimpleNamespace(main_frame=object());gate=lootbar_browser.RequestGate(128)
        def response(status,kind,frame):
            return types.SimpleNamespace(status=status,request=types.SimpleNamespace(resource_type=kind),frame=frame)
        for status,kind,frame in [(401,'xhr',page.main_frame),(403,'image',page.main_frame),(403,'document',object())]:
            lootbar_browser.observe_document_response(gate,page,response(status,kind,frame))
            self.assertIsNone(gate.reason)
        lootbar_browser.observe_document_response(gate,page,response(429,'document',page.main_frame))
        self.assertEqual(gate.reason,'http_429')

    @unittest.skipUnless(os.name=='posix','real Linux flock/process contract')
    def test_original_shell_holds_source_lock_through_fallback_and_rejects_parallel_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);state=base/'state';evidence=base/'evidence';binary=base/'bin';binary.mkdir()
            pkg=base/'code/fc_collection';pkg.mkdir(parents=True);(pkg/'__init__.py').write_text('')
            marker=base/'held';release=base/'release'
            script='''import fcntl,json,os,time
from pathlib import Path
def main():
    lock=Path(LOCK)
    assert os.fstat(9).st_ino==lock.stat().st_ino
    with lock.open('a') as other:
        try:fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:pass
        else:raise AssertionError('source lock released before fallback')
    Path(MARKER).touch()
    end=time.monotonic()+10
    while not Path(RELEASE).exists() and time.monotonic()<end:time.sleep(.01)
    assert Path(RELEASE).exists()
    print(json.dumps(dict(stage='remote_complete',read_only=True,node_id='183',source_receipt_verified=True,offers=[dict(platform='PS')],missing=[dict(platform='PC')])))
def primary_ready():return True
'''
            script='LOCK='+repr(str(state/'lootbar.lock'))+'\nMARKER='+repr(str(marker))+'\nRELEASE='+repr(str(release))+'\n'+script
            (pkg/'lootbar.py').write_text(script)
            docker=binary/'docker';docker.write_text("#!/bin/sh\nprintf '%s\\n' '{\"stage\":\"cdp_connecting\"}' '{\"stage\":\"failed\",\"reason\":\"browser_connection_timeout\"}'\nexit 1\n");docker.chmod(0o755)
            original=Path(os.environ.get('FC_TEST_LOOTBAR_SHELL') or ROOT/'fc27_cloud_browser/collect_lootbar.sh').read_text()
            original=original.replace('state=/var/lib/fc27-cloud/state','state='+str(state)).replace('evidence=/var/lib/fc27-cloud/evidence','evidence='+str(evidence))
            original=original.replace('/opt/python39/bin/python3',sys.executable).replace('/opt/fs-fc-control/code',str(base/'code'))
            wrapper=base/'collect.sh';wrapper.write_text(original);wrapper.chmod(0o755)
            env=dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'])
            first=subprocess.Popen(['sh',str(wrapper),'original-run'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                end=time.monotonic()+8
                while not marker.exists() and time.monotonic()<end:time.sleep(.01)
                self.assertTrue(marker.exists(),'fallback did not reach held-lock assertion')
                second=subprocess.run(['sh',str(wrapper),'other-run'],env=env,capture_output=True,timeout=3)
                self.assertEqual(second.returncode,75)
                release.touch();out,err=first.communicate(timeout=5)
                self.assertEqual(first.returncode,0,(out,err))
                events=[json.loads(l) for p in evidence.glob('*.jsonl') for l in p.read_text().splitlines()]
                self.assertEqual(events[-1]['stage'],'remote_complete')
            finally:
                if first.poll() is None:first.kill();first.communicate()
    def test_new_endpoint_rejects_body_length_before_read(self):
        mod = service()
        for length in ['-1','2049','nope','']:
            h = mod.H.__new__(mod.H)
            h.path='/fc27_lootbar'
            h.headers={'Content-Length':length}
            h.rfile=Mock();h.rfile.read.side_effect=AssertionError('must not read invalid body')
            h._send=Mock()
            h.do_POST()
            self.assertEqual(h._send.call_args.args[0],400)

    def test_fc_busy_never_waits_or_touches_rpg_worker(self):
        mod = service()
        h=mod.H.__new__(mod.H);h.path='/fc27_lootbar'
        raw=json.dumps(TASK).encode();h.headers={'Content-Length':str(len(raw))};h.rfile=io.BytesIO(raw);h._send=Mock()
        mod._lock.acquire()
        try:
            with patch.dict(sys.modules, {'fc27_lootbar':lootbar_browser}), patch.object(mod,'run_worker',side_effect=AssertionError('RPG busy')):
                h.do_POST()
        finally:
            mod._lock.release()
        self.assertEqual(h._send.call_args.args,(503,dict(ok=False,reason='renderer_busy')))

    def test_fc_worker_never_reads_rpg_configuration(self):
        mod=service();out=io.StringIO()
        script=types.SimpleNamespace(collect=Mock(return_value=dict(snapshots={},platform_errors={})))
        with patch.dict(sys.modules, {'fc27_lootbar':script}), patch.object(mod,'read_cfg',side_effect=AssertionError('no RPG config')), \
                patch.object(sys,'stdin',io.StringIO(json.dumps(dict(kind='fc27_lootbar',payload=TASK)))),patch.object(sys,'stdout',out):
            self.assertEqual(mod.worker_main(),0)
        result=json.loads(out.getvalue().split(mod.WORKER_MARK)[1])
        self.assertTrue(result['ok']);script.collect.assert_called_once_with(TASK)

    def test_fixed_task_rejects_urls_scripts_extra_platforms_and_budget(self):
        for change in [dict(url='https://other.invalid'),dict(script='arbitrary'),dict(platforms=['PS','PS']),
                       dict(platforms=['RPG']),dict(request_limit=129),dict(timeout_seconds=76)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                lootbar_browser.validate_task(dict(TASK,**change))


if __name__ == '__main__':unittest.main()
