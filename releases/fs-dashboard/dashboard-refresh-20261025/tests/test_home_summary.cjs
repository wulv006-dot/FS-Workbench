// Real homepage and controller, fictional sources on localhost only.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const repo=path.resolve(__dirname,'../../../..');
const server=http.createServer((req,res)=>res.end('fixture'));
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  for(const file of ['ui-system/modules/native/shell.js',...['shell.js','home-shell.js','legacy-shell.js'].map(n=>'releases/fs-dashboard/dashboard-refresh-20261025/source/'+n)]){
   const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>{
    const u=new URL(route.request().url()),name=path.posix.basename(u.pathname),q=Object.fromEntries(u.searchParams);
    if(u.hostname!=='127.0.0.1')return route.abort();
    const send=(body,contentType='text/javascript')=>route.fulfill({body,contentType});
    if(u.pathname==='/')return send(fs.readFileSync(path.join(repo,'ui-system/modules/native/home.html'),'utf8'),'text/html');
    if(name==='shell.js')return send(fs.readFileSync(path.join(repo,file),'utf8'));
    if(name==='metrics.js')return send("window.FSHomeMetrics={beijingDate:()=> '2026-11-01'}");
    if(name==='runtime.js')return send("export const lifecycle=()=>{},moduleAvailable=()=>new Promise(resolve=>window.releaseProbe=()=>resolve(false)),sessionIdentity=async()=>({name:'fixture',groups:[]}),protectedRead=(...args)=>fetch(...args);");
    if(name==='navigation.json')return route.fulfill({json:{schemaVersion:1,tools:[{id:'management',path:'/slow',section:'sports'}],sections:[]}});
    if(name==='range.json'){
     assert.equal(q.start,'2026-10-31');assert.equal(q.end,'2026-10-31');
     const period={start:'2026-10-31 00:00',end:'2026-11-01 00:00'},metric=value=>({value,status:'available'});
     const supplement={status:'available',period,metrics:{orders:metric(4),revenueUsd:metric(100)},dimensions:{channels:[{code:'www.mmoexp.com',orders:4,revenueUsd:100}]}};
     return route.fulfill({json:{status:'available',scopeContractId:'admin-paid-order-labelled-supplement-v2',query:q,
      profile:{key:'MMOEXP',period,supplement},sources:{Admin:{status:'available'},Order:{status:'not_provided'}}}});
    }
    return send('',name.endsWith('.css')?'text/css':'text/javascript');
   });
   await page.goto('http://127.0.0.1:'+server.address().port);
   await page.locator('#orders').filter({hasText:'4'}).waitFor({timeout:2000});
   assert.equal(await page.locator('.global-nav a[data-section="sports"]').isHidden(),true);
   await page.evaluate(()=>window.releaseProbe());
   await page.locator('[data-tool=management][aria-disabled=true]').waitFor();
   assert.equal(await page.locator('#revenueUsd').innerText(),'100.00');
   assert.equal(await page.locator('.section-heading h2').first().innerText(),'昨日经营');
   assert.equal(await page.locator('#newCustomers').innerText(),'源未提供','unavailable Order does not hide Admin or invent profit');
   assert.deepEqual(errors,[]);await page.close();console.log('PASS yesterday homepage '+file);
  }
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
