// Execute the three production-derived shells and real business renderers locally.
// Only authentication, navigation discovery, Google data and backend API data are fictional.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {start,server}=require('./test_browser.cjs');
const repo=path.resolve(__dirname,'../../../..'),source=path.join(__dirname,'../source'),fixtures=path.join(__dirname,'fixtures');
const keys=['b_fc_platform','b_fc_site_group','b_fc_customer','b_fc_product','b_fc_bucket'];
const added=keys.map(k=>`'${k}'`).join(',')+',';
const cases=[
 ['shell.js','business.js','dca3ea6ed17296bb5efded9b7d8dab835ace6a35cb74c342b9965ed365d10595'],
 ['home-shell.js','home-business.js','66278928104b1edf1e78b9123b6f18c2781f8065423d886918b2ca2776c613d5'],
 ['legacy-shell.js','legacy-business.js','f6c776a5ec169f5d77338a83d312e55185410ab56f224e694bb7c181edb07047']
];
for(const [name,,baseline]of cases){
 const code=fs.readFileSync(path.join(source,name),'utf8').replace(/\r\n/g,'\n');
 assert.equal(code.split(added).length-1,1,name+' only adds the five state keys once');
 const beforeSummaryFix=code.replace(added,'')
  .replace("!['admin-paid-order-labelled-supplement-v2','admin-paid-order-labelled-supplement-v3-scope-repeat'].includes(data.scopeContractId)",name==='shell.js'?"data.scopeContractId!=='admin-paid-order-labelled-supplement-v2'":"data.scopeContractId!=='admin-main-order-labelled-supplement-v1'")
  .replace("const day=fsPeriodPolicy().shift(FSHomeMetrics.beijingDate(),-1);","const day=FSHomeMetrics.beijingDate();")
  .replace("'昨日MMOEXP '","'今日MMOEXP '")
  .replace(" const heading=document.querySelector('.section-heading h2');if(heading)heading.textContent='昨日经营';\n document.querySelector('.home-kpis')?.setAttribute('aria-label','MMOEXP 昨日经营');\n",'');
 assert.equal(crypto.createHash('sha256').update(beforeSummaryFix).digest('hex'),baseline,name+' preserves baseline outside explicit summary/date changes');
}
function detail(q){
 const row={orders:1,revenue_usd:20,issues:0,new:1,returning:0,unknown:0,unpriced_orders:0,unfinished:0,funding:0};
 const category={key:q.product==='all'?'Players':q.product,label:'球员卡',...row};
 return {contractId:'fc27-detail-analytics-v1',query:q,snapshot_id:'fictional-shell-state',as_of:'2026-10-24T08:00:00Z',scope_label:'模拟FC筛选',data_status:'complete',customer_status:'available',customer_basis:'模拟站内ID',coverage:{paid_complete:true,missing_days:[],backlog_status:'complete'},totals:row,site_groups:[{key:q.site_group==='all'?'main':q.site_group,...row}],buckets:[{key:'1',label:'20–40',...row}],user_buckets:[{key:'1',label:'20–40',users:1,revenue_usd:20}],orders_without_customer_id:0,dimensions:{platform:[{key:'PC',...row}]},signals:[],backlog_summary:{...row,orders:0,revenue_usd:0},slow_orders:0,orders:[],page:1,list_total:0,fc_dashboard:{contractId:'fc-dashboard-category-v1-20261106',totals:{...row,paying_customers:1},categories:[category],trend:[{date:q.start,...row,categories:[category]}],coverage:{classification_status:'complete'}}};
}
const google=`export function mount(scope){let value={...scope.seed,g_period:'7',phase:'available'};const emit=()=>scope.changed(value);scope.setTimeout(emit,0);return {state:()=>value,apply:s=>{value={...s,g_period:'7',phase:'available'};scope.setTimeout(emit,0);return true},resume:emit,update:emit};}`;
async function run(page,url,shellName,businessName){
 const code=fs.readFileSync(path.join(source,shellName),'utf8'),business=fs.readFileSync(path.join(source,businessName),'utf8');
 const html=fs.readFileSync(path.join(repo,'ui-system/modules/native/index.html'),'utf8').replace(/(<script type="module" src=")[^"]+\/shell\.js/, '$1/under-test/shell.js');
 const errors=[];page.on('pageerror',e=>errors.push(e.stack));
 await page.addInitScript(()=>{const OriginalDate=Date;window.Date=class extends OriginalDate{constructor(...args){super(...(args.length?args:['2026-10-24T08:00:00Z']));}static now(){return new OriginalDate('2026-10-24T08:00:00Z').getTime();}};});
 await page.route('**/*',route=>{
  const u=new URL(route.request().url()),file=path.posix.basename(u.pathname),q=Object.fromEntries(u.searchParams);
  const send=(body,contentType='text/javascript')=>route.fulfill({body,contentType});
  if(u.pathname==='/shell-state')return send(html,'text/html');
  if(u.pathname==='/under-test/shell.js')return send(code);
  if(file==='runtime.js')return send(fs.readFileSync(path.join(fixtures,'runtime.js'),'utf8'));
  if(file==='business.js')return send(business);
  if(file==='google.js')return send(google);
  if(file==='business.html')return send(fs.readFileSync(path.join(fixtures,'business.html'),'utf8'),'text/html');
  if(file==='google.html')return send('<p id="google-fixture">模拟Google数据模块</p>','text/html');
  if(file==='business.css')return send(fs.readFileSync(path.join(repo,'ui-system/modules/native/business.css'),'utf8'),'text/css');
  if(['fs-tokens.css','fs-ui.css','native-alias.css'].includes(file))return send(fs.readFileSync(path.join(fixtures,file),'utf8'),'text/css');
  if(file==='navigation.json')return route.fulfill({json:{schemaVersion:1,tools:[],sections:[]}});
  if(file==='range.json'&&q.mode==='fc-detail')return route.fulfill({json:detail(q)});
  if(file==='range.json'&&q.mode==='fc-daily')return route.fulfill({status:503,json:{error:'fictional_unavailable'}});
  if(file.endsWith('.css'))return send('','text/css');
  if(file.endsWith('.js'))return send('');
  return route.continue();
 });
 await page.goto(url+'/shell-state?mode=business&b_site=all&b_profile=FC27&b_group=sports&b_grain=day&b_range=yesterday');
 const filter=key=>page.locator(`[data-fc-filter=${key}]`);
 await filter('product').waitFor();
 await page.waitForFunction(()=>document.querySelector('.native-content')?.shadowRoot.querySelector('[data-fc-filter=customer]')?.disabled===false);
 await filter('product').selectOption('Players');
 await page.locator('.fc-more-filters summary').click();
 await filter('platform').selectOption('PC');
 await filter('site_group').selectOption('satellite');
 await filter('customer').selectOption('new');
 await filter('bucket').selectOption('1');
 const chosen={b_fc_platform:'PC',b_fc_site_group:'satellite',b_fc_customer:'new',b_fc_product:'Players',b_fc_bucket:'1'};
 const hasURL=values=>page.waitForFunction(v=>Object.entries(v).every(([k,value])=>new URL(location.href).searchParams.get(k)===value),values);
 const check=async values=>{await page.waitForFunction(()=>document.querySelector('.native-content')?.shadowRoot.querySelector('[data-fc-filter=bucket]')?.options.length>1);for(const [key,value]of Object.entries(values))assert.equal(await filter(key.slice(5)).inputValue(),value,shellName+' '+key);};
 await hasURL(chosen);await page.reload();await filter('product').waitFor();await check(chosen);
 await page.locator('#tab-google').click();await page.locator('#google-fixture').waitFor();await hasURL(chosen);
 await page.locator('#tab-business').click();await filter('product').waitFor();await check(chosen);
 await filter('product').selectOption('SBC');await hasURL({...chosen,b_fc_product:'SBC'});
 await page.goBack();await page.locator('#google-fixture').waitFor();await page.goBack();await filter('product').waitFor();await check(chosen);
 await page.goForward();await page.locator('#google-fixture').waitFor();await page.goForward();await filter('product').waitFor();await check({...chosen,b_fc_product:'SBC'});
 const unavailable=new URL(page.url());unavailable.searchParams.set('b_fc_bucket','missing');await page.goto(unavailable.href);await filter('product').waitFor();
 await page.waitForFunction(()=>document.querySelector('.native-content')?.shadowRoot.querySelector('[data-fc-filter=bucket]')?.options.length>1);
 assert.equal(await filter('bucket').inputValue(),'');assert.equal(new URL(page.url()).searchParams.get('b_fc_bucket'),'missing',shellName+' unavailable bucket must not silently become all');
 assert.deepEqual(errors,[],shellName+' real shell page errors');
 console.log(shellName+': real readURL/capture/save, reload, mode remount, back and forward retain all five FC filters');
}
(async()=>{
 const url=await start(),browser=await chromium.launch({headless:true});
 try{for(const [shell,business]of cases){const page=await browser.newPage();try{await run(page,url,shell,business);}finally{await page.close();}}}
 finally{await browser.close();server.closeAllConnections();server.close();}
})().catch(e=>{console.error(e);server.closeAllConnections();server.close();process.exitCode=1;});
