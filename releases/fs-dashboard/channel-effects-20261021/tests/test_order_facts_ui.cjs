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
    if(url.searchParams.has('snapshot_id')){
      if(state==='detail-expired'){res.writeHead(409);res.end('{}');return;}
      const snapshot_id=url.searchParams.get('snapshot_id');
      if(url.searchParams.has('detail_export')){res.end(JSON.stringify({snapshot_id,total:3,detail_csv:'channel,code,coupon\r\nReferral,synthetic-code,Launch\r\n'}));return;}
      res.end(JSON.stringify({snapshot_id,total:3,page:1,pages:1,orders:[{orderNo:'SYNTHETIC',channel:'Referral（引荐）',source:'YouTube',code:'synthetic-code',coupons:['Launch'],salesUsd:15}]}));return;
    }
    const missing=state==='shared-missing',empty=state==='empty'||missing,zero=state==='zero',channel=url.searchParams.get('channel'),selected=channel==='unknown';
    const referral=channel==='Referral', filtered=url.searchParams.has('coupon_template');
    const totals=summary(empty?0:selected||filtered?1:referral?3:4,empty||referral||filtered?0:1);
    if(zero)Object.assign(totals,{missing_cost_orders:0,cost_covered_orders:2,procurement_gross_cny:'0',gross_covered_orders:2,admin_paid_usd:'0'});
    const scope=Object.fromEntries(['start','end','site_id','gid','channel','status','country','payment','project','coupon_template']
      .filter(k=>url.searchParams.has(k)).map(k=>[k,url.searchParams.get(k)]));
    const associations={discount_code:{known_orders:0,unknown_orders:0},promoter:{known_orders:0,unknown_orders:0},
      coupon:{known_orders:1,unknown_orders:0},coupon_templates:[{label:'Launch',orders:1}],promotion_projects:[],order_sources:[]};
    const sourceRow=(label,orders)=>({label,...summary(orders),associations,cost_records:0,order_share:orders/totals.orders});
    const breakdown={dimension:channel==='all'?'channel':'source_detail',denominator_orders:totals.orders,
      rows:empty?[]:selected?[sourceRow('未提供',1)]:referral?(filtered?[sourceRow('YouTube',1)]:[sourceRow('YouTube',2),sourceRow('未提供',1)]):
        [sourceRow('Referral（引荐）',3),sourceRow('未知',1)]};
    const snapshot=state==='revision'?'revision-2':'revision-1';
    res.end(JSON.stringify({version:'order-facts-api-20261113-v1',status:missing?'unavailable':'available',admin_complete:!missing,
      ...(state==='deferred'?{refresh_deferred:true,refresh_reason:'recent_capture',retryAfter:60}:{}),
      effective_scope:state==='mismatch'?{...scope,gid:'999'}:scope,
      snapshot_id:snapshot,aggregate_csv:`gid,channel,snapshot\r\n${scope.gid},${scope.channel},${snapshot}\r\n`,
      trend:[{day:scope.start,...totals,status:'available'},
        {day:scope.end,...summary(0),admin_paid_usd:null,observed_cost_cny:null,status:'partial'}],
      totals,breakdown,channels:[],keyword_applied:url.searchParams.has('q'),discount_code_applied:url.searchParams.has('code'),coupon_batch_applied:url.searchParams.has('coupon_batch'),
      coverage:{unlinked_admin_rows:0,unlinked_attribution_rows:3,unverified_filter_orders:filtered?1:0,missing_days:missing?[scope.end]:[]},
      options:{games:[['1327','FC27'],['456','Diablo 4'],['1329','AION2']],country:['US'],payment:['PayPal'],coupon_templates:[['7','Launch']]},
      revisions:{attribution:{publication_id:state==='revision'?'revision-2':'revision-1'}}}));return;
  }
  if(url.pathname.endsWith('runtime.js')){
    res.setHeader('Content-Type','text/javascript');res.end(`export async function sessionIdentity(){return {name:'fixture',role:'admin'}} export async function protectedRead(u,o,deny){const r=await fetch(u,o);if([401,403].includes(r.status))deny(r.status);if(!r.ok)throw Error('protected_read_failed_'+r.status);return r}`);return;
  }
  if(url.pathname.endsWith('fs-theme.js')){
    res.setHeader('Content-Type','text/javascript');res.end("window.FSTheme={get:()=>document.documentElement.dataset.fsTheme||'light',set:v=>{document.documentElement.dataset.fsTheme=v;dispatchEvent(new Event('fs-theme-change'))}};");return;
  }
  if(url.pathname.endsWith('.css')&&!url.pathname.endsWith('/channel.css')){
    res.setHeader('Content-Type','text/css');res.end(':root{--fs-font:system-ui;--fs-line:#ddd;--fs-text:#123;--fs-surface:#fff;--fs-bg:#eee;--fs-brand:#075e60;--fs-surface-2:#eee}[data-fs-theme=dark]{--fs-brand:#61d2d1;--fs-surface-2:#293648}');return;
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
    assert.equal(await page.locator('[name=country]').isDisabled(),false);
    assert.equal(await page.getByRole('button',{name:'近28天',exact:true}).count(),1);
    state='available';await page.locator('#refresh').click();
    await page.locator('#results').waitFor({state:'visible'});
    assert.match(await page.locator('#source-attribution-title').innerText(),/各归因渠道订单占比/);
    assert.match(await page.locator('#source-attribution').innerText(),/未知/);
    assert.match(await page.locator('#source-attribution-note').innerText(),/共 4 单.*已归因 3 \/ 4 单/);
    const chart=page.locator('#source-attribution-chart svg');
    assert.equal(await page.getByRole('img',{name:'各归因渠道订单占比'}).count(),1);
    assert.match(await chart.textContent(),/Referral（引荐） 75.0%.*未知 25.0%/s);
    assert.equal(await page.locator('#source-attribution-chart [aria-hidden=true]').count(),2);
    const widths=await chart.locator('.distribution-bar').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width));
    assert.ok(widths[0]>200&&widths[1]>60&&Math.abs(widths[0]/widths[1]-3)<0.02);
    if(process.env.FS_CHANNEL_CHART_SCREENSHOT) await page.locator('.attribution-panel').screenshot({path:process.env.FS_CHANNEL_CHART_SCREENSHOT+'-all.png'});
    assert.equal(await page.locator('#legacy-details').isVisible(),false);
    assert.equal(await page.locator('#trend svg').isVisible(),true);
    assert.equal(await page.locator('#trend .sales').count(),1);
    await page.getByText('查看每日数据表',{exact:true}).click();
    assert.match(await page.locator('#trend-table tbody tr').last().innerText(),/—.*部分/s);
    assert.match(await page.locator('#kpis').innerText(),/¥0/);
    assert.match(await page.locator('#kpis').innerText(),/—/);
    assert.equal(await page.locator('#status').getAttribute('data-state'),'partial');
    assert.match(await page.locator('#definitions').textContent(),/不称净利润/);
    assert.deepEqual(Object.keys(requests.at(-1)).sort(),['channel','end','gid','mode','refresh','site_id','start']);
    assert.equal(requests.at(-1).refresh,'1');
    assert.equal(requests.at(-1).site_id,'266');
    assert.equal(await page.locator('[name=gid] option[value="456"]').textContent(),'Diablo 4');
    await page.locator('[name=channel]').selectOption('Referral');
    await page.locator('#source-attribution-title').filter({hasText:'Referral（引荐）'}).waitFor();
    assert.match(await page.locator('#source-attribution-note').innerText(),/所选渠道共 3 单/);
    assert.match(await chart.textContent(),/YouTube 66.7%.*未提供 33.3%/s);
    const shares=await chart.locator('.distribution-bar').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width));
    assert.ok(shares[0]>180&&Math.abs(shares[0]/shares[1]-2)<0.02);
    if(process.env.FS_CHANNEL_CHART_SCREENSHOT) await page.locator('.attribution-panel').screenshot({path:process.env.FS_CHANNEL_CHART_SCREENSHOT+'-referral.png'});
    const detailSummary=page.getByText('查看同一范围的订单、推广人、折扣码和优惠券',{exact:true});
    await detailSummary.click();
    await page.getByText('SYNTHETIC',{exact:true}).waitFor();
    assert.match(await page.locator('#facts-detail-table').innerText(),/YouTube.*synthetic-code.*Launch/s);
    assert.equal(requests.at(-1).channel,'Referral');
    assert.equal(requests.at(-1).snapshot_id,'revision-1');
    const [detailCsv]=await Promise.all([page.waitForEvent('download'),page.locator('#facts-detail-export').click()]);
    assert.match(fs.readFileSync(await detailCsv.path(),'utf8'),/Referral,synthetic-code,Launch/);
    state='detail-expired';await page.locator('#facts-detail-export').click();
    await page.getByText('本次快照已失效，请重新查询当前范围。',{exact:true}).waitFor();
    await detailSummary.click();state='available';
    await page.getByText('订单状态、渠道优惠与关键词',{exact:true}).click();
    await page.locator('[name=country]').selectOption('US');
    await page.waitForFunction(()=>document.querySelector('#scope').textContent.includes('美国（US）'));
    await page.locator('[name=coupon_template]').selectOption('7');
    await page.locator('#source-attribution-note').filter({hasText:'1 单筛选字段未核'}).waitFor();
    assert.match(await chart.textContent(),/YouTube 100.0%/s);
    assert.equal(requests.at(-1).country,'US');
    assert.equal(requests.at(-1).coupon_template,'7');
    await page.getByText('查看同单关联的订单来源、优惠券和推广项目',{exact:true}).click();
    assert.match(await page.locator('#attribution-association-table').innerText(),/Launch/);
    await page.locator('[name=coupon_template]').selectOption('');
    await page.waitForFunction(()=>!document.querySelector('#scope').textContent.includes('已筛优惠券'));
    await page.locator('[name=country]').selectOption('');
    await page.waitForFunction(()=>!document.querySelector('#scope').textContent.includes('美国（US）'));
    await page.locator('[name=channel]').selectOption('all');
    await page.locator('#source-attribution-title').filter({hasText:'各归因渠道订单占比'}).waitFor();
    await page.locator('[name=gid]').selectOption('456');
    await page.waitForFunction(()=>document.querySelector('#scope').textContent.includes('Diablo 4'));
    assert.equal(requests.at(-1).gid,'456');
    await page.locator('[name=gid]').selectOption('1327');
    await page.waitForFunction(()=>document.querySelector('#scope').textContent.includes('FC27'));
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
    const exportButton=page.locator('#export-facts');
    const beforeExport=requests.length;
    const [download]=await Promise.all([page.waitForEvent('download'),exportButton.click()]);
    assert.match(download.suggestedFilename(),/revision-1\.csv$/);
    assert.match(fs.readFileSync(await download.path(),'utf8'),/1327,unknown,revision-1/);
    assert.equal(requests.length,beforeExport);
    const oldStart=await page.locator('[name=start]').inputValue();
    await page.locator('[name=start]').fill(await page.locator('[name=end]').inputValue());
    assert.equal(await exportButton.isDisabled(),true);
    await page.locator('[name=start]').fill(oldStart);
    // Editing a date while an older response is in flight must keep its export disabled.
    let delayedRoute, reportHeld;
    const held = new Promise(resolve => { reportHeld = resolve; });
    await page.route('**/data.json?**', route => { delayedRoute = route; reportHeld(); }, {times:1});
    await page.locator('#refresh').click(); await held;
    await page.locator('[name=start]').fill(await page.locator('[name=end]').inputValue());
    const oldResponse = page.waitForResponse(r => r.url().includes('/data.json?'));
    await delayedRoute.continue(); await oldResponse;
    await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
    assert.equal(await exportButton.isDisabled(),true,'in-flight edit cannot export the older scope');
    await page.locator('[name=start]').fill(oldStart);
    state='mismatch';await page.locator('#refresh').click();
    await page.locator('#status[data-state=error]').waitFor();
    assert.match(await page.locator('#scope').innerText(),/FC27.*未知/);
    state='error';await page.locator('#refresh').click();
    await page.locator('#status[data-state=error]').waitFor();
    assert.equal(await page.locator('#results').isVisible(),true);
    assert.match(await page.locator('#source-attribution-note').innerText(),/0 \/ 1/);
    state='empty';await page.locator('#refresh').click();
    await page.locator('#status').filter({hasText:'没有付款订单'}).waitFor();
    assert.match(await page.locator('#kpis').innerText(),/\$0.00/);
    assert.match(await page.locator('#source-attribution').innerText(),/没有记录/);
    state='shared-missing';await page.locator('#refresh').click();
    await page.locator('#status').filter({hasText:'共享订单库暂未覆盖当前范围'}).waitFor();
    assert.match(await page.locator('#source-attribution-note').innerText(),/共享订单库缺 1 天/);
    assert.doesNotMatch(await page.locator('#kpis').innerText(),/\$0\.00/);
    assert.equal(await page.locator('#source-attribution-chart svg').count(),0);
    state='zero';await page.locator('[name=channel]').selectOption('all');
    await page.waitForFunction(()=>document.querySelector('#coverage').textContent.includes('完整成本 2 / 4'));
    assert.doesNotMatch(await page.locator('#kpis').innerText(),/—/);
    state='revision';await page.locator('#refresh').click();
    await page.locator('#freshness').filter({hasText:'revision-2'}).waitFor();
    const [newDownload]=await Promise.all([page.waitForEvent('download'),exportButton.click()]);
    assert.match(fs.readFileSync(await newDownload.path(),'utf8'),/1327,all,revision-2/);
    for(const theme of ['dark','light']){
      await page.locator('#theme').selectOption(theme);
      assert.equal(await page.locator('html').getAttribute('data-fs-theme'),theme);
      assert.equal(await page.locator('#source-attribution-chart .distribution-bar').first().evaluate(el=>getComputedStyle(el).fill),
        theme==='dark'?'rgb(97, 210, 209)':'rgb(7, 94, 96)');
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
    assert.equal(await exportButton.isDisabled(),true);
    assert.deepEqual(errors,[]);
    console.log('D2 channel UI: pending, scoped requests, unknown, missing/zero, partial, empty, error retention, revision, themes/mobile, auth passed');
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
