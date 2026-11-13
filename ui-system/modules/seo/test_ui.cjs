const {chromium}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=__dirname,meta={snapshot_id:'seo-2026-11-05',facts_hash:'fixture-only',publication_date:'2026-11-05',report_date:'2026-11-04',history_start:'2026-10-06',history_end:'2026-11-04',games:['FC27','D4','AION2','WOW_FOREVER'],sources:{gsc:'configured',ga4:'configured',admin:'configured',serp:'not_configured',pages:'not_configured',orders:'not_configured'},data_status:'partial'};
let apiCalls=[],empty=false,historyError=false,hangAI=true,holdManifest=false,extras=false,recorded=false;const pending=[],manifests=[];
function historyRows(game){
 const rows=[{source_date:'2026-11-02',metrics:{gsc:{clicks:'3',impressions:'10',ctr:'.3',position:'4'},ga4:null,admin:null,orders:null},source_status:{gsc:{status:'available',source_timezone:'America/Los_Angeles'}},estimate:{status:'missing'}},{source_date:'2026-11-04',metrics:{gsc:null,ga4:{sessions:'10',purchase_events:game==='WOW_FOREVER'?'0':'3'},admin:{admin_customer_price_usd:'7.25'},orders:null},source_status:{ga4:{status:'provisional',source_timezone:'Asia/Shanghai'},admin:{status:'available',source_timezone:'Asia/Shanghai'}},estimate:{status:'estimated',revenue_usd:game==='WOW_FOREVER'?'0.00':'21.75'}}];
 if(!recorded)return rows;
 const contract='admin-recorded-order-attribution-v1',
  source={status:'available',source_timezone:'Asia/Shanghai',quality:{contract,source_revision:'admin-fixture',attribution_source_revision:'es-fixture',data_revision:'d0-12'}};
 rows[0].source_status.orders={status:'failed',source_timezone:'Asia/Shanghai',quality:{}};
 rows.splice(1,0,{source_date:'2026-11-03',metrics:{orders:{contract,paid_orders:0,seo_orders:0,seo_revenue_usd:'0',attributed_orders:0,attribution_amount_coverage:null,attribution_status:'available'}},source_status:{orders:source},estimate:{status:'missing'}});
 const latest=rows[2];latest.source_status.orders=source;
 latest.metrics.orders={contract,paid_orders:4,seo_orders:2,seo_revenue_usd:null,known_recorded_seo_revenue_usd:'25.60',missing_seo_revenue_orders:1,
  attributed_orders:2,attribution_amount_coverage:'0.4',attribution_status:'partial'};
 rows.unshift({source_date:'2026-11-01',metrics:{orders:{contract,paid_orders:1,seo_orders:null,seo_revenue_usd:null,attributed_orders:0,attribution_amount_coverage:null,attribution_status:'unknown'}},source_status:{orders:source},estimate:{status:'missing'}});
 return rows;
}
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.startsWith('/dashboard/analytics/seo/api/v1/')){
  apiCalls.push(url.pathname+url.search);res.setHeader('Content-Type','application/json');
  if(url.pathname.endsWith('ai-policy')){if(hangAI){pending.push(res);return;}res.statusCode=503;return res.end('{}');}
  if(empty&&url.pathname.endsWith('current')){res.statusCode=404;return res.end('{}');}
  if(url.pathname.endsWith('current')||url.pathname.endsWith('manifest')){if(holdManifest){manifests.push(res);return;}return res.end(JSON.stringify(meta));}
  if(historyError&&url.pathname.includes('/history')){res.statusCode=503;return res.end('{}');}
  const kind=url.pathname.split('/').at(-1),game=url.searchParams.get('game');
  if(extras&&kind==='markets'){
   const rows=[{country:'US',language:'en',device:'desktop',keyword:'fc27 coins',depth:10,source_date:'2026-11-04',observed_at:'2026-11-04T03:25:00+08:00',brand:'MMOEXP',rank:2,status:'found',effective_depth:8},{country:'US',language:'en',device:'desktop',keyword:'fc27 coins',depth:10,source_date:'2026-11-04',observed_at:'2026-11-04T03:25:00+08:00',brand:'IGGM',rank:null,status:'insufficient_depth',effective_depth:8},{country:'US',language:'en',device:'desktop',keyword:'fc27 coins',depth:10,source_date:'2026-11-04',brand:'U4GM',rank:null,status:'unresolved',effective_depth:8}];
   const cursor=Number(url.searchParams.get('cursor')||0);return res.end(JSON.stringify({snapshot_id:meta.snapshot_id,facts_hash:meta.facts_hash,game,rows:rows.slice(cursor,cursor+1),next_cursor:cursor+1<rows.length?cursor+1:null}));
  }
  if(extras&&kind==='calendar')return res.end(JSON.stringify({snapshot_id:meta.snapshot_id,facts_hash:meta.facts_hash,game,next_cursor:null,rows:[{key:'dated',title:'已发布日期事件',event_date:'2026-11-08',source_url:'https://official.example/notice',upstream_observed_at:'2026-11-01T00:00:00Z',source_status:'published',source_date:'2026-11-04'},{key:'undated',title:'无日期公告',event_date:null,published_at:'2026-11-01T00:00:00Z',source_url:'https://official.example/notice2',upstream_observed_at:'2026-11-01T00:00:00Z',source_status:'stale',source_date:'2026-11-04'}]}));
  return res.end(JSON.stringify({snapshot_id:meta.snapshot_id,facts_hash:meta.facts_hash,game,next_cursor:null,rows:kind==='history'?historyRows(game):[]}));
 }
 const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
 const file=name==='fs-tokens.css'?path.resolve(root,'../../tokens/fs-tokens.css'):name==='fs-theme.js'?path.resolve(root,'../../adapters/fs-theme.js'):path.resolve(root,name);
 if(!file.startsWith(root)&&!['fs-tokens.css','fs-theme.js'].includes(name)){res.statusCode=403;return res.end();}
 if(!fs.existsSync(file)){res.statusCode=404;return res.end();}
 res.setHeader('Content-Type',name.endsWith('.css')?'text/css':/\.(mjs|js)$/.test(name)?'text/javascript':'text/html');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}});await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.getByRole('heading',{name:'上游 · 需求走势',exact:true}).waitFor();
  assert.equal(await page.locator('.journey-card').count(),3);assert.equal(await page.getByRole('img').count(),2);
  assert(await page.locator('.journey-card').evaluateAll(cards=>cards.every(c=>c.getBoundingClientRect().height<=380)));
  assert.equal(await page.getByText('等待采样',{exact:true}).count(),8);
  assert((await page.locator('.sales .primary-metric').innerText()).includes('21.75'));
  assert((await page.locator('.demand .primary-metric').innerText()).includes('10'));
  assert((await page.locator('.search .primary-metric').innerText()).includes('3'));
  assert.equal(await page.locator('.demand circle').count(),1);
  assert((await page.getByText(/最近源日 2026-11-02/).innerText()).includes('太平洋时间'));
  // A permanently pending AI control read must not delay the real base layout.
  assert(pending.length>0);hangAI=false;pending.splice(0).forEach(res=>{res.statusCode=503;res.end('{}');});
  await page.getByText('AI设置暂不可用，基础数据可继续查看。').waitFor();
  for(const game of ['D4','AION2','WOW_FOREVER','FC27']){
   await page.getByLabel('监控游戏').selectOption(game);
   await page.waitForFunction(expected=>new URL(location.href).searchParams.get('game')===expected&&document.querySelector('#panel[aria-busy=false] .journey-card'),game);
   assert((await page.getByRole('link',{name:'导出当前版本'}).getAttribute('href')).includes('game='+game));
   if(game==='WOW_FOREVER')assert((await page.locator('.sales .primary-metric').innerText()).includes('$0'));
  }
  assert(apiCalls.filter(p=>p.includes('/history')).every(p=>p.includes('/seo-2026-11-05/')));
  await page.getByRole('button',{name:'查看成交预估明细',exact:true}).click();await page.getByRole('cell',{name:'21.75',exact:true}).waitFor();assert.equal(await page.getByRole('img').count(),1);
  assert.equal(await page.getByRole('heading',{name:'后台已记录为 SEO 的付款订单'}).count(),0);
  recorded=true;meta.sources.orders='configured';
  const callsBefore=apiCalls.length;
  await page.reload();await page.getByRole('heading',{name:'后台已记录为 SEO 的付款订单'}).waitFor({timeout:4000});
  const facts=page.getByRole('table',{name:'后台已记录的SEO付款订单，按北京时间'});
  const known=await facts.getByRole('row',{name:/2026-11-04/}).innerText();
  assert.match(known,/25\.6.*2 \/ 4.*40\.0%.*部分/s);
  assert.match(await facts.getByRole('row',{name:/2026-11-03/}).innerText(),/\b0\b.*\$0/s);
  assert.match(await facts.getByRole('row',{name:/2026-11-01/}).innerText(),/—.*0 \/ 1.*归因未知/s);
  assert.match(await facts.getByRole('row',{name:/2026-11-02/}).innerText(),/—.*采集失败/s);
  await page.getByText('查看后台归因来源修订',{exact:true}).click();
  assert.match(await page.getByRole('table',{name:'后台归因来源修订'}).innerText(),/admin-fixture.*es-fixture.*d0-12/s);
  assert.equal(await page.getByRole('cell',{name:'21.75',exact:true}).count(),1);
  assert(apiCalls.slice(callsBefore).every(p=>!p.includes('/orders')));
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.setViewportSize({width:1600,height:1100});
  recorded=false;meta.sources.orders='not_configured';
  await page.getByRole('tab',{name:'游戏日程',exact:true}).click();await page.getByRole('heading',{name:'游戏日程来源尚未接入',exact:true}).waitFor();
  await page.getByRole('tab',{name:'数据来源',exact:true}).click();await page.getByRole('heading',{name:'Google Search Console',exact:true}).waitFor();
  await page.getByText('查看快照校验与逐日来源明细').click();await page.getByText('fixture-only',{exact:true}).waitFor();
  await page.getByRole('button',{name:'AI增强设置',exact:true}).click();await page.getByText('AI 设置暂不可用',{exact:true}).waitFor();
  await page.getByRole('tab',{name:'经营全景',exact:true}).click();await page.getByRole('heading',{name:'上游 · 需求走势',exact:true}).waitFor();
  await page.getByText('展开每日数据，核对趋势与预估数值').click();await page.getByRole('table').waitFor();
  assert((await page.getByRole('table').innerText()).includes('2026-11-02'));
  await page.evaluate(()=>window.FSTheme.set('dark'));assert.equal(await page.evaluate(()=>document.documentElement.dataset.fsTheme),'dark');
  await page.screenshot({path:process.env.SEO_SCREENSHOT||path.join(root,'../../../../../seo-ui-demo-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:process.env.SEO_MOBILE_SCREENSHOT||path.join(root,'../../../../../seo-ui-demo-mobile.png'),fullPage:true});
  assert.equal(await page.getByRole('button',{name:/实时|立即采集|强刷|自动刷新/}).count(),0);assert(apiCalls.every(p=>!p.includes('refresh')));
  historyError=true;await page.reload();await page.getByRole('button',{name:'重试读取此快照'}).waitFor();historyError=false;await page.getByRole('button',{name:'重试读取此快照'}).click();await page.getByRole('heading',{name:'上游 · 需求走势',exact:true}).waitFor();
  empty=true;await page.goto(new URL('/',page.url()).href);await page.getByRole('heading',{name:'暂无可读取的已发布数据',exact:true}).waitFor();
  await page.getByRole('button',{name:'AI增强设置',exact:true}).click();await page.getByText('AI 设置暂不可用',{exact:true}).waitFor();assert(!new URL(page.url()).searchParams.has('snapshot_id'));
  empty=false;holdManifest=true;await page.goto(new URL('/',page.url()).href);await page.getByRole('button',{name:'AI增强设置',exact:true}).click();await page.getByText('AI 设置暂不可用',{exact:true}).waitFor();
  holdManifest=false;manifests.splice(0).forEach(res=>res.end(JSON.stringify(meta)));await page.waitForFunction(()=>new URL(location.href).searchParams.get('snapshot_id')==='seo-2026-11-05');
  assert.equal(new URL(page.url()).searchParams.get('tab'),'ai');await page.getByRole('heading',{name:'行动与AI分析',exact:true}).waitFor();
  extras=true;meta.sources.serp='configured';meta.sources.calendar='configured';await page.goto(new URL('/',page.url()).href);
  await page.getByRole('cell',{name:'#2',exact:true}).waitFor({timeout:2500});assert((await page.getByRole('table').innerText()).includes('未在前8名'));assert.equal(await page.getByText('等待采样',{exact:true}).count(),0);assert((await page.getByRole('table').innerText()).includes('链接待解析'));
  await page.getByRole('tab',{name:'游戏日程',exact:true}).click();await page.getByRole('heading',{name:'已发布日期事件',exact:true}).waitFor();await page.getByText('事件日期待核',{exact:true}).waitFor();assert.equal(await page.getByRole('link',{name:'查看来源公告',exact:true}).count(),2);
  assert((await page.locator('#panel').innerText()).includes('原来源读取'));assert((await page.locator('#panel').innerText()).includes('来源已过期'));
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert(apiCalls.filter(p=>p.includes('/markets')||p.includes('/calendar')).every(p=>p.includes('/seo-2026-11-05/')));
  meta.snapshot_id='seo-2026-11-05-manual-0123456789ab';meta.publication_mode='manual_observation';meta.observation_date='2026-11-05';
  await page.goto(new URL('/?snapshot_id='+meta.snapshot_id,page.url()).href);await page.getByText('手动观察 2026-11-05',{exact:false}).first().waitFor({timeout:2500});await page.getByRole('cell',{name:'#2',exact:true}).waitFor({timeout:2500});
  assert((await page.getByRole('link',{name:'导出当前版本',exact:true}).getAttribute('href')).includes(meta.snapshot_id));
  assert((await page.locator('#business-day').innerText()).includes('2026-11-04'));
  console.log('PASS: demo hierarchy, honest source gaps, four games, frozen URLs, AI hang/failure isolation, details, mobile, retry and empty state');
 }finally{await browser.close();}
})().then(()=>server.close()).catch(error=>{console.error(error);server.close();process.exitCode=1;});
