const {chromium}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=__dirname,meta={snapshot_id:'seo-2026-11-05',facts_hash:'fixture-only',publication_date:'2026-11-05',report_date:'2026-11-04',history_start:'2026-10-06',history_end:'2026-11-04',games:['FC27','D4','AION2','WOW_FOREVER'],sources:{gsc:'configured',ga4:'not_configured',orders:'not_configured'},data_status:'partial'};
let apiCalls=[], empty=false;
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.startsWith('/dashboard/analytics/seo/api/v1/')){
  apiCalls.push(url.pathname+url.search);
  res.setHeader('Content-Type','application/json');
  if(url.pathname.endsWith('ai-policy')){res.statusCode=503;return res.end('{}');}
  if(empty&&url.pathname.endsWith('current')){res.statusCode=404;return res.end('{}');}
  if(url.pathname.endsWith('current')||url.pathname.endsWith('manifest'))return res.end(JSON.stringify(meta));
  return res.end(JSON.stringify({snapshot_id:meta.snapshot_id,facts_hash:meta.facts_hash,game:url.searchParams.get('game'),next_cursor:null,rows:[{source_date:'2026-11-02',metrics:{gsc:{clicks:'3',impressions:'10',ctr:'.3'},ga4:null,admin:null,orders:null},estimate:{status:'missing'}},{source_date:'2026-11-04',metrics:{gsc:null,ga4:{sessions:'10',purchase_events:'3'},admin:{admin_customer_price_usd:'7.25'},orders:null},estimate:{status:'estimated',revenue_usd:'21.75'}}]}));
 }
 const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
 const file=name==='fs-tokens.css'?path.resolve(root,'../../tokens/fs-tokens.css'):name==='fs-theme.js'?path.resolve(root,'../../adapters/fs-theme.js'):path.resolve(root,name);
 if(!file.startsWith(root)&&!['fs-tokens.css','fs-theme.js'].includes(name)){res.statusCode=403;return res.end();}
 if(!fs.existsSync(file)){res.statusCode=404;return res.end();}
 res.setHeader('Content-Type',name.endsWith('.css')?'text/css':(name.endsWith('.mjs')||name.endsWith('.js'))?'text/javascript':'text/html');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.getByRole('table').waitFor();assert((await page.getByRole('table').innerText()).includes('2026-11-02'));
  await page.getByLabel('游戏').selectOption('D4');
  await page.waitForFunction(()=>document.querySelector('#scope').value==='D4'&&document.querySelector('#panel table'));
  assert(apiCalls.filter(p=>p.includes('/history')).every(p=>p.includes('/seo-2026-11-05/')));
  await page.getByRole('tab',{name:'自然搜索成交'}).click();
  await page.getByRole('cell',{name:'21.75',exact:true}).waitFor();
  await page.evaluate(()=>window.FSTheme.set('dark'));
  assert.equal(await page.evaluate(()=>document.documentElement.dataset.fsTheme),'dark');
  await page.getByRole('tab',{name:'行动与AI分析'}).click();
  await page.getByText('AI 设置暂不可用').waitFor();
  await page.getByRole('tab',{name:'总览'}).click();await page.getByRole('table').waitFor();
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert.equal(await page.getByRole('button',{name:/实时|立即采集/}).count(),0);
  await page.screenshot({path:process.env.SEO_SCREENSHOT||path.join(root,'../../../../../seo-ui-mobile.png'),fullPage:true});
  empty=true;await page.goto(new URL('/',page.url()).href);await page.getByText('暂无可读取的已发布数据。').waitFor();
  await page.getByRole('tab',{name:'行动与AI分析'}).click();
  await page.getByText('AI 设置暂不可用').waitFor();
  assert(!new URL(page.url()).searchParams.has('snapshot_id'));
  await page.getByRole('tab',{name:'总览'}).click();
  await page.getByText('等待首个夜间批次发布。').waitFor();
  console.log('PASS: four-game selection, frozen URLs, AI failure isolation, mobile overflow and no real-time action');
 }finally{await browser.close();}
})().then(()=>server.close()).catch(error=>{console.error(error);server.close();process.exitCode=1;});
