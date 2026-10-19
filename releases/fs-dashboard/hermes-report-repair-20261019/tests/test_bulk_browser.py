"""Isolated batch-delete behavior; no production reports are modified."""
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[4]
SOURCE=ROOT/'releases/fs-dashboard/hermes-report-repair-20261019/source'
BASELINE=SOURCE
URL='https://fs.invalid/dashboard/fs-home/brain/index.html'


def run(unknown=False):
    rows=[{'id':x*32,'state':'COMPLETED','owner':'test','can_delete':x!='c',
           'body':{'start':'2026-10-12','end':'2026-10-18','mode':'investigation','question':'TEST '+x}}
          for x in 'abc']
    posted=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1280,'height':900})
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            req=r.request;u=urlsplit(req.url);q=parse_qs(u.query)
            if u.path.endswith('index.html'):return r.fulfill(body=BASELINE.joinpath('brain-index.html').read_bytes(),content_type='text/html')
            if u.path.endswith('brain.js'):return r.fulfill(body=SOURCE.joinpath('brain.js').read_bytes(),content_type='text/javascript')
            if u.path.endswith('advisor.json'):
                if req.method=='POST':
                    body=req.post_data_json;posted.append(body['id'])
                    if body['id']=='b'*32:
                        if unknown:return r.abort('failed')
                        return r.fulfill(status=403,json={'error':'admin_required'})
                    rows[:]=[x for x in rows if x['id']!=body['id']]
                    return r.fulfill(json={'deleted':True,'recoverable':True})
                if 'structure' in q:return r.fulfill(status=403,json={'error':'admin_required'})
                return r.fulfill(json={'items':rows,'can_generate':False,'pool_scope':'shared','nightly':{'enabled':False}})
            return r.fulfill(body='',content_type='text/css' if u.path.endswith('.css') else 'text/javascript')
        page.route('**/*',route);page.goto(URL)
        page.get_by_role('button',name='选择当前页',exact=True).wait_for()
        page.wait_for_function("document.querySelectorAll('[data-report-select]').length===2")
        assert page.locator('[data-report-select]').count()==2
        page.get_by_role('button',name='选择当前页',exact=True).click()
        assert page.locator('[data-report-select]:checked').count()==2
        page.get_by_role('button',name='清空选择',exact=True).click()
        assert page.locator('[data-report-select]:checked').count()==0
        page.get_by_role('button',name='选择当前页',exact=True).click()
        page.once('dialog',lambda d:d.dismiss())
        page.get_by_role('button',name='移到回收站',exact=True).click();assert not posted
        page.once('dialog',lambda d:d.accept())
        page.get_by_role('button',name='移到回收站',exact=True).click()
        page.get_by_role('status').filter(has_text='已移除 1 份').wait_for()
        assert posted==['a'*32,'b'*32]
        assert page.locator('[data-report-select]:checked').count()==1
        assert len(rows)==2 and rows[0]['id']=='b'*32
        if unknown:assert page.get_by_text('有请求结果待核对',exact=False).count()==1
        page.set_viewport_size({'width':390,'height':844})
        assert page.get_by_role('button',name='选择当前页',exact=True).is_visible()
        page.locator('html').evaluate("e=>e.dataset.theme='dark'")
        assert not errors,errors
        browser.close()


if __name__=='__main__':
    run();run(unknown=True)
    print('bulk selection, cancel, partial failure, unknown stop, mobile: PASS')
