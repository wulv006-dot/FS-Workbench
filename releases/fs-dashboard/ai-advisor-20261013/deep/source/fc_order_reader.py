"""Server-only reader executed in the already authorized Order Chrome container."""
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
import json
import re
import time
from playwright.sync_api import sync_playwright
from fc_order_diagnostics import classify_logs, choose_sample, summarize

ORIGIN='https://order.p2pah.cn'
LIST='/order/admin_order/index.html'
DETAIL=re.compile(r'^/order/admin_order/look/id/[0-9]{1,12}\.html$')
HEADERS=['','ID','来源/ 商户订单号','游戏/ 服务器','产品','角色名','金额','总量/已交量','状态历时','提单时间','管理员/绑定下家/分组','状态','操作']
SAFE_REASONS={'source_login_or_page','source_filter_contract','source_scope_contract','detail_contract'}


def run():
    deadline=time.monotonic()+105
    rows=[];samples=[];errors=[];pages=0
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:9226',timeout=8000,no_defaults=True)
        page=browser.contexts[0].new_page()
        def readonly(route):
            req=route.request;u=urlsplit(req.url)
            safe_doc=req.resource_type=='document' and (u.path==LIST or DETAIL.fullmatch(u.path))
            static=req.resource_type in ('script','stylesheet','image','font')
            if req.method in ('GET','HEAD') and u.scheme=='https' and u.netloc=='order.p2pah.cn' and (safe_doc or static):route.continue_()
            else:route.abort()
        page.route('**/*',readonly)
        try:
            for n in range(1,4):
                if time.monotonic()>=deadline:errors.append('read_budget');break
                response=page.goto(ORIGIN+LIST+'?'+urlencode({'gid[]':'1322','status':'6','source[]':'www.mmoexp.com','page':str(n)}),wait_until='domcontentloaded',timeout=15000)
                raw=page.evaluate('''() => {
                  const table=[...document.querySelectorAll('table')].find(t=>[...t.querySelectorAll('thead th')].map(x=>x.textContent.trim())[1]==='ID');
                  return {origin:location.origin,path:location.pathname,login:!!document.querySelector('input[type=password]'),
                    filters:Object.fromEntries([...document.querySelectorAll('form select')].filter(e=>['status','gid[]','source[]'].includes(e.name)).map(e=>[e.name,[...e.selectedOptions].map(o=>o.value)])),
                    headers:table?[...table.querySelectorAll('thead th')].map(x=>x.textContent.trim()):[],
                    rows:table?[...table.querySelectorAll('tbody tr')].map(tr=>{const t=[...tr.querySelectorAll('td')];if(t.length!==13)return null;
                      const game=t[3].textContent;const source=t[2].textContent;const amount=t[6].textContent.match(/USD\\s*([\\d,.]+)/);const links=[...t[12].querySelectorAll('a')].map(a=>a.getAttribute('href')||a.getAttribute('onclick')||'');
                      const detail=links.map(s=>s.match(/\\/order\\/admin_order\\/look\\/id\\/\\d+\\.html/)).find(Boolean);
                      return {id:t[1].textContent.trim(),main:/(?:^|\\s)www\\.mmoexp\\.com(?:\\s|$)/.test(source),fc:/^FC\\s*27(?:\\s|$)/.test(game.trim()),
                        platform:/XBOX/i.test(game)?'XBOX':/\\bPC\\b/i.test(game)?'PC':/\\bPS\\b|PlayStation/i.test(game)?'PS':'unknown',
                        amount:amount?amount[1]:null,status:t[11].textContent.trim(),detail:detail?detail[0]:null};}).filter(Boolean):[],
                    hasNext:[...document.querySelectorAll('.pagination a')].some(a=>Number(a.textContent.trim())>Number(new URL(location.href).searchParams.get('page')||1))};
                }''')
                if not response or response.status!=200 or raw['login'] or raw['origin']!=ORIGIN or raw['path']!=LIST:raise ValueError('source_login_or_page')
                # Both labels were verified on the authorized local and server sessions.
                if raw['headers'] not in (HEADERS,HEADERS[:-1]+['Actions']) or raw['filters']!={'status':['6'],'gid[]':['1322'],'source[]':['www.mmoexp.com']}:raise ValueError('source_filter_contract')
                pages+=1
                for row in raw['rows']:
                    if not row['main'] or not row['fc'] or row['status']!='问题单' or not re.fullmatch(r'\d{1,12}',row['id']):raise ValueError('source_scope_contract')
                    if row['detail']!='/order/admin_order/look/id/'+row['id']+'.html':raise ValueError('detail_contract')
                    amount=float(row['amount'].replace(',','')) if row['amount'] is not None else None
                    rows.append({'id':row['id'],'platform':row['platform'],'amount_usd':amount,'detail':row['detail']})
                if not raw['hasNext']:break
            for row in choose_sample(rows):
                if time.monotonic()>=deadline:errors.append('sample_budget');break
                try:
                    response=page.goto(ORIGIN+row['detail'],wait_until='domcontentloaded',timeout=8000)
                    # Raw text exists only transiently inside this already-authorized server process.
                    # It is classified before stdout/cache; customer/account cells are not read at all.
                    raw=page.evaluate('''() => {
                      const table=[...document.querySelectorAll('table')].find(t=>[...t.querySelectorAll('th')].map(x=>x.textContent.trim()).join('|')==='日志ID|生成时间|操作人|订单状态|内容');
                      return {origin:location.origin,path:location.pathname,login:!!document.querySelector('input[type=password]'),found:!!table,
                        logs:table?[...table.querySelectorAll('tr')].slice(1,101).map(tr=>{const c=[...tr.querySelectorAll('td')];return c.length===5?{time:c[1].textContent.trim(),status:c[3].textContent.trim(),content:c[4].textContent.slice(0,4000)}:null}).filter(Boolean):[]};
                    }''')
                    if not response or response.status!=200 or raw['login'] or raw['origin']!=ORIGIN or raw['path']!=row['detail'] or not raw['found']:raise ValueError('detail_unavailable')
                    clue=classify_logs(raw['logs']);raw=None
                    samples.append({'ref':'order-'+row['id'],'platform':row['platform'],'amount_usd':row['amount_usd'],
                                    'review_url':ORIGIN+row['detail'],**clue})
                except Exception:errors.append('sample_unavailable')
        finally:page.close()
    return summarize(rows,samples,pages,errors,datetime.now(timezone.utc).isoformat())


if __name__=='__main__':
    try:print(json.dumps(run(),ensure_ascii=True,allow_nan=False))
    except Exception as error:
        reason=str(error) if str(error) in SAFE_REASONS else 'source_read_'+type(error).__name__
        print(json.dumps({'contract':'fc-order-problem-clues-v1','status':'unavailable','reason':reason,'captured_at':datetime.now(timezone.utc).isoformat()}))
