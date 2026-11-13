// Synthetic D2 API responses only; no production access or data.
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
let state='pending';
const requests=[];
const summary=(orders,unknown=0)=>({orders,unknown_channel_orders:unknown,
  admin_paid_usd:orders?'100':'0',admin_paid_cny:orders?'700':'0',
  observed_cost_cny:'0',procurement_gross_cny:null,gross_covered_orders:0,
  missing_admin_usd_orders:0,missing_admin_cny_orders:0,cost_covered_orders:0,
  missing_cost_orders:orders,covered_revenue_cny:'0',missing_cost_revenue_cny:orders?'700':'0'});
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.endsWith('/data.json')){
    requests.push(Object.fromEntries(url.searchParams));
    res.setHeader('Content-Type','application/json');
    if(state==='refresh-pending'){state='available';res.writeHead(202);res.end(JSON.stringify({status:'pending',retryAfter:0.01}));return;}
    if(state==='pending'){res.writeHead(202);res.end(JSON.stringify({status:'pending',retryAfter:30}));return;}
    if(state==='error'){res.writeHead(503);res.end('{}');return;}
    if(state==='denied'){res.writeHead(403);res.end('{}');return;}
    const empty=state==='empty',zero=state==='zero',selected=url.searchParams.get('channel')==='unknown';
    const totals=summary(empty?0:selected?1:2,empty?0:1);
    if(zero)Object.assign(totals,{missing_cost_orders:0,cost_covered_orders:2,procurement_gross_cny:'0',gross_covered_orders:2,admin_paid_usd:'0'});
    res.end(JSON.stringify({version:'order-facts-api-20261113-v1',status:'available',admin_complete:true,
      ...(state==='deferred'?{refresh_deferred:true,refresh_reason:'recent_capture',retryAfter:60}:{}),
      effective_scope:Object.fromEntries(['start','end','site_id','gid'].map(k=>[k,url.searchParams.get(k)])),
      totals,channels:empty?[]:selected?[{channel:'unknown',...totals}]:[{channel:'Direct',...summary(1)},{channel:'unknown',...summary(1,1)}],
      coverage:{unlinked_admin_rows:0,unlinked_attribution_rows:3},
      revisions:{attribution:{publication_id:state==='revision'?'revision-2':'revision-1'}}}));return;
  }
  if(url.pathname.endsWith('runtime.js')){
    res.setHeader('Content-Type','text/javascript');res.end(`export async function sessionIdentity(){return {name:'fixture',role:'admin'}} export async function protectedRead(u,o,deny){const r=await fetch(u,o);if([401,403].includes(r.status))deny(r.status);if(!r.ok)throw Error('protected_read_failed_'+r.status);return r}`);return;
  }
  if(url.pathname.endsWith('fs-theme.js')){
    res.setHeader('Content-Type','text/javascript');res.end("window.FSTheme={get:()=>document.documentElement.dataset.fsTheme||'light',set:v=>{document.documentElement.dataset.fsTheme=v;dispatchEvent(new Event('fs-theme-change'))}};");return;
  }
  if(url.pathname.endsWith('.css')&&!url.pathname.endsWith('/channel.css')){
    res.setHeader('Content-Type','text/css');res.end(':root{--fs-font:system-ui;--fs-line:#ddd;--fs-text:#123;--fs-surface:#fff;--fs-bg:#eee}');return;
  }
  if(url.pathname.startsWith('/__hub/')){res.setHeader('Content-Type','text/javascript');res.end('');return;}
  const name=url.pathname.endsWith('/')?'index.html':url.pathname.split('/').pop();
  if(!['index.html','channel.js','channel.css'].includes(name)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',{'.html':'text/html','.js':'text/javascript','.css':'text/css'}[path.extname(name)]);
  res.end(fs.readFileSync(path.join(root,'ui',name)));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/dashboard/channel-effects/`);
    await page.locator('#status').filter({hasText:'正在从共享数据源'}).waitFor();
    assert.equal(await page.locator('#results').isVisible(),false);
    assert.equal(await page.locator('[name=mode]').inputValue(),'order-facts');
    assert.equal(await page.locator('[name=country]').isDisabled(),true);
    assert.equal(await page.locator('[name=q]').isVisible(),false);
    assert.equal(await page.getByRole('button',{name:'近28天',exact:true}).count(),1);
    state='available';await page.locator('#refresh').click();
    await page.locator('#results').waitFor({state:'visible'});
    assert.match(await page.locator('#source-attribution-title').innerText(),/后台归因渠道/);
    assert.match(await page.locator('#source-attribution').innerText(),/未知/);
    assert.match(await page.locator('#source-attribution-note').innerText(),/已归因 1 \/ 2 单/);
    assert.equal(await page.locator('#legacy-details').isVisible(),false);
    assert.match(await page.locator('#kpis').innerText(),/¥0/);
    assert.match(await page.locator('#kpis').innerText(),/—/);
    assert.equal(await page.locator('#status').getAttribute('data-state'),'partial');
    assert.match(await page.locator('#definitions').textContent(),/不称净利润/);
    assert.deepEqual(Object.keys(requests.at(-1)).sort(),['channel','end','gid','mode','refresh','site_id','start']);
    assert.equal(requests.at(-1).refresh,'1');
    assert.equal(requests.at(-1).site_id,'266');
    state='deferred';await page.locator('#refresh').click();
    await page.locator('#status').filter({hasText:'60 秒后可再次刷新'}).waitFor();
    assert.equal(await page.locator('#results').isVisible(),true);
    const beforeRefresh=requests.length;
    state='refresh-pending';await page.locator('#refresh').click();
    await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('仍有缺口'));
    assert.equal(requests[beforeRefresh].refresh,'1');
    assert.equal(requests.length-beforeRefresh,2);
    assert.equal(requests.at(-1).refresh,undefined);
    await page.locator('[name=channel]').selectOption('unknown');
    await page.waitForFunction(()=>document.querySelector('#source-attribution-note').textContent.includes('已归因 0 / 1 单'));
    assert.equal(requests.at(-1).channel,'unknown');
    assert.equal(await page.locator('#source-attribution tbody tr').count(),1);
    state='error';await page.locator('#refresh').click();
    await page.locator('#status[data-state=error]').waitFor();
    assert.equal(await page.locator('#results').isVisible(),true);
    assert.match(await page.locator('#source-attribution-note').innerText(),/0 \/ 1/);
    state='empty';await page.locator('#refresh').click();
    await page.locator('#status').filter({hasText:'没有付款订单'}).waitFor();
    assert.match(await page.locator('#kpis').innerText(),/\$0.00/);
    assert.match(await page.locator('#source-attribution').innerText(),/没有记录/);
    state='zero';await page.locator('[name=channel]').selectOption('all');
    await page.waitForFunction(()=>document.querySelector('#coverage').textContent.includes('完整成本 2 / 2'));
    assert.doesNotMatch(await page.locator('#kpis').innerText(),/—/);
    state='revision';await page.locator('#refresh').click();
    await page.locator('#freshness').filter({hasText:'revision-2'}).waitFor();
    for(const theme of ['dark','light']){
      await page.locator('#theme').selectOption(theme);
      assert.equal(await page.locator('html').getAttribute('data-fs-theme'),theme);
    }
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator('#source-attribution .table-wrapper').getAttribute('role'),'region');
    assert.equal(await page.locator('#source-attribution .table-wrapper').getAttribute('tabindex'),'0');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
    await page.getByRole('button',{name:'近28天',exact:true}).click();
    assert.equal(await page.evaluate(()=>{const f=document.querySelector('#filters');return(new Date(f.elements.end.value)-new Date(f.elements.start.value))/86400000}),27);
    state='denied';await page.locator('#refresh').click();
    await page.locator('#status').filter({hasText:'未获渠道效果看板授权'}).waitFor();
    assert.equal(await page.locator('#results').isVisible(),false);
    assert.equal(await page.locator('#refresh').isDisabled(),true);
    assert.deepEqual(errors,[]);
    console.log('D2 channel UI: pending, scoped requests, unknown, missing/zero, partial, empty, error retention, revision, themes/mobile, auth passed');
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
