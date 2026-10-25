"""Bounded public U4GM reads; same transport and field contract, no backend identity."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
import sys
import time

os.environ.setdefault('PLAYWRIGHT_NODEJS_PATH','/usr/local/node/bin/node')
sys.path.insert(0,'/opt/fc27-cloud-browser/collector')
from collect_competitor_browser import U4GM_READ,checked_offer,PLATFORMS,URLS,timeout_diagnostic
from playwright.async_api import async_playwright,TimeoutError as CollectorTimeoutError
import sports_outbound


def remaining_timeout(deadline,maximum):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise ValueError('source_deadline')
    return max(1,min(maximum,int(remaining*1000)))


async def route_public(route,deadline,failures,semaphore,executor):
    request=route.request
    if request.resource_type not in {'document','script','xhr','fetch','stylesheet'}:
        return await route.continue_()
    started=time.monotonic()
    try:
        headers={k:v for k,v in request.headers.items() if k.lower() not in {'cookie','authorization'}}
        async with semaphore:
            timeout=remaining_timeout(deadline,18000)/1000
            # Retain the existing streaming limit/Worker; never block Playwright's event loop.
            fetch=partial(sports_outbound.fetch,request.url,request.post_data_buffer,headers,timeout=timeout)
            body=await asyncio.get_running_loop().run_in_executor(executor,fetch)
        if body is None:return await route.continue_()
        kind='text/html' if request.resource_type=='document' else 'application/javascript' if request.resource_type=='script' else 'text/css' if request.resource_type=='stylesheet' else 'application/json'
        await route.fulfill(status=200,body=body,content_type=kind)
    except Exception as error:
        if len(failures)<32:
            failures.append({'resource_type':request.resource_type,'error_type':type(error).__name__,
                             'elapsed_seconds':round(time.monotonic()-started,3)})
        await route.abort('failed')


async def stable(page,deadline):
    prior=None;count=0
    for _ in range(12):
        remaining_timeout(deadline,6000)
        data=await page.evaluate(U4GM_READ)
        if data and data.get('ready'):
            signature=json.dumps(data,sort_keys=True);count=count+1 if signature==prior else 1
            if count>=2:return data
            prior=signature
        else:count=0;prior=None
        await page.wait_for_timeout(min(500,remaining_timeout(deadline,500)))
    raise ValueError('selector_or_value_unstable')


async def collect(context,deadline,diagnostic):
    rows=[]
    for platform,label,suffix in (('PS','PS 4/5',''),('XBOX','Xbox One/Series','?server_code=xbox_one_series'),('PC','PC','?server_code=pc')):
        url=URLS['U4GM']+suffix;diagnostic.update(platform=platform,phase='page_create')
        page=await context.new_page()
        try:
            diagnostic['phase']='page_navigation'
            response=await page.goto(url,wait_until='domcontentloaded',timeout=remaining_timeout(deadline,35000))
            if response is None or response.status in (401,403,429):raise ValueError('http_blocked')
            await page.wait_for_timeout(min(1000,remaining_timeout(deadline,1000)))
            if await page.evaluate("() => /just a moment|checking your browser|access denied|verify you are human/i.test(document.title+' '+document.body.innerText.slice(0,500))"):
                raise ValueError('challenge')
            diagnostic['phase']='package_click'
            await page.locator('[data-qty="100"]').click(timeout=remaining_timeout(deadline,5000))
            diagnostic['phase']='stable_price'
            data=await stable(page,deadline)
            if label not in data['platformText']:raise ValueError('platform_mismatch')
            rows.append(checked_offer('U4GM',platform,url,data['price'],100,data['bonus']))
        finally:await page.close()
    return rows


async def run():
    deadline=time.monotonic()+90;retries=[];failures=[];diagnostic={}
    executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix='u4gm-public')
    try:
        for attempt in range(2):
            try:
                async with async_playwright() as pw:
                    diagnostic.update(phase='browser_connection',platform=None)
                    browser=await pw.chromium.connect_over_cdp('http://127.0.0.1:9225',timeout=remaining_timeout(deadline,8000),no_defaults=True)
                    diagnostic['phase']='public_context'
                    context=await browser.new_context(locale='en-US',service_workers='block')
                    try:
                        semaphore=asyncio.Semaphore(4)
                        async def route_handler(route):await route_public(route,deadline,failures,semaphore,executor)
                        await context.route('https://www.u4gm.com/**',route_handler)
                        rows=await collect(context,deadline,diagnostic)
                    finally:await context.close()
                if [r['platform'] for r in rows]!=list(PLATFORMS):raise ValueError('platform_coverage_incomplete')
                return {'source':'U4GM','status':'valid','offers':rows,'read_retries':retries,'route_failures':failures}
            except Exception as error:
                reason,detail=timeout_diagnostic(error) if isinstance(error,CollectorTimeoutError) else (str(error) if isinstance(error,ValueError) else type(error).__name__,{})
                if attempt==0 and isinstance(error,CollectorTimeoutError) and deadline-time.monotonic()>=44:
                    retries.append(dict(diagnostic,reason=reason,price_actions=0));continue
                return {'source':'U4GM','status':'missing','reason':reason[:60],
                        'diagnostic':dict(detail,**diagnostic),'read_retries':retries,'route_failures':failures}
    finally:executor.shutdown(wait=True,cancel_futures=True)


if __name__=='__main__':
    result=asyncio.run(run());print(json.dumps(result));sys.exit(0 if result['status']=='valid' else 1)
