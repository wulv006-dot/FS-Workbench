'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto'),{EventEmitter}=require('events');
const root=path.join(__dirname,'../..'),html=fs.readFileSync(path.join(root,'var/www/nba2k27/index.html'),'utf8');
const uiCode=html.slice(html.indexOf('  // One exact confirmed plan'),html.indexOf("  $('btnClearLog').addEventListener"));
function sharedBrowser(){
 const values=new Map();let queue=Promise.resolve();
 return {localStorage:{getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)},locks:{request:(k,fn)=>{const work=queue.then(fn);queue=work.catch(()=>{});return work;}}};
}
function browser(shared,transport,locks=shared.locks,immediateTimeout=false){
 let confirms=0,price=1;const elements={},logs=[];
 const ctx=vm.createContext({Promise,Error,JSON,Object,Array,String,Number,Uint8Array,AbortController,setTimeout:immediateTimeout?fn=>setTimeout(fn,1):setTimeout,clearTimeout,
  crypto:crypto.webcrypto,navigator:{locks},localStorage:shared.localStorage,API:'/synthetic-nba',
  window:{confirm:()=>{confirms++;return true;}},fetch:transport,
  $:id=>elements[id]||(elements[id]={addEventListener:()=>{},textContent:''}),log:(s)=>logs.push(s),
  DATA:[{area:'PS',cost:1}],hasRead:true,hasApplied:false,currentParams:()=>({rate:1,mMin:.2,mMax:.3,mode:'cost',rec:{}}),
  resolveSuggest:()=>({price,margin:.25}),pct:n=>String(n),refreshGate:()=>{}});
 vm.runInContext(uiCode,ctx);
 return {apply:()=>vm.runInContext('doApply()',ctx),check:()=>vm.runInContext('applyLock(()=>checkReceipt(savedApply()))',ctx),
  record:()=>vm.runInContext('savedApply()',ctx),setPrice:n=>price=n,confirms:()=>confirms,text:()=>elements.applyReceipt.textContent};
}
function transport(){
 const receipts=new Map(),calls=[];let lose=false,partial=false;
 const fetch=async(url,opts={})=>{
  calls.push({url,opts});
  if(url.includes('/api/receipt')){
   const id=new URL(url,'https://synthetic.invalid').searchParams.get('requestId');
   return {json:async()=>receipts.get(id)||{ok:false,requestId:id,planSha256:null,operator:'wulv',state:'unknown',error:'RECEIPT_NOT_FOUND'}};
  }
  const p=JSON.parse(opts.body),r={ok:!partial,requestId:p.requestId,planSha256:'f'.repeat(64),operator:'wulv',state:'completed',results:[],verify:{},error:partial?'SYNTHETIC_PARTIAL':undefined};
  receipts.set(p.requestId,r);
  if(lose)throw new Error('SYNTHETIC_NETWORK_LOSS');
  return {json:async()=>r};
 };
 return {fetch,calls,receipts,setLose:v=>lose=v,setPartial:v=>partial=v,posts:()=>calls.filter(c=>c.opts.method==='POST')};
}
async function uiTests(){
 let shared=sharedBrowser(),t=transport(),a=browser(shared,t.fetch),b=browser(shared,t.fetch);
 const [ar,br]=await Promise.all([a.apply(),b.apply()]);
 assert(ar.ok&&br.ok);assert.equal(t.posts().length,1);assert.equal(a.record().requestId,b.record().requestId);
 assert.equal(a.confirms()+b.confirms(),1);assert.match(t.posts()[0].opts.body,/requestId/);
 const id=a.record().requestId;await a.apply();assert.equal(t.posts().length,1);
 const refreshed=browser(shared,t.fetch);await refreshed.apply();assert.equal(t.posts().length,1);assert(refreshed.text().includes(id));
 refreshed.setPrice(2);await refreshed.apply();assert.equal(t.posts().length,2);assert.notEqual(refreshed.record().requestId,id);
 // A disconnect after fake effect retains the same identity across refresh and changed plans.
 shared=sharedBrowser();t=transport();t.setLose(true);a=browser(shared,t.fetch);
 await assert.rejects(a.apply(),/NETWORK_LOSS/);const unknown=a.record().requestId;assert.equal(a.record().state,'unknown');
 t.receipts.delete(unknown);b=browser(shared,t.fetch);b.setPrice(3);
 await assert.rejects(b.apply(),/未知/);assert.equal(t.posts().length,1);assert.equal(b.record().requestId,unknown);
 t.receipts.set(unknown,{ok:true,requestId:unknown,planSha256:'f'.repeat(64),operator:'wulv',state:'completed'});
 await assert.rejects(b.apply(),/重新确认/);assert.equal(t.posts().length,1);
 t.setLose(false);await b.apply();assert.equal(t.posts().length,2);assert.notEqual(b.record().requestId,unknown);
 // Partial completion and bound errors are preserved; identical plan only reads its receipt.
 shared=sharedBrowser();t=transport();t.setPartial(true);a=browser(shared,t.fetch);
 await assert.rejects(a.apply(),e=>e.receipt.state==='completed'&&e.receipt.operator==='wulv');
 await assert.rejects(a.apply(),/PARTIAL/);assert.equal(t.posts().length,1);
 // Rejected before effect is explicitly confirmed again with the same ID.
 shared=sharedBrowser();let posts=[];
 a=browser(shared,async(url,opts)=>{const p=JSON.parse(opts.body);posts.push(p);return {json:async()=>({ok:false,state:'rejected',requestId:p.requestId,operator:'wulv',planSha256:'f'.repeat(64),error:'PENDING_PERSIST_FAILED'})};});
 await assert.rejects(a.apply(),/PENDING/);await assert.rejects(a.apply(),/PENDING/);
 assert.equal(posts[0].requestId,posts[1].requestId);assert.equal(a.confirms(),2);
 // A mismatched receipt cannot clear the unknown block.
 shared=sharedBrowser();a=browser(shared,async()=>({json:async()=>({ok:true,requestId:'0'.repeat(32),state:'completed'})}));
 await assert.rejects(a.apply(),/不匹配/);assert.equal(a.record().state,'unknown');
 // Missing lock or persistent storage refuses before issuing any write.
 shared=sharedBrowser();t=transport();a=browser(shared,t.fetch,null);await assert.rejects(a.apply(),/Web Locks/);assert.equal(t.posts().length,0);
 shared=sharedBrowser();shared.localStorage.setItem=()=>{throw Error('SYNTHETIC_STORAGE_FAILURE')};t=transport();a=browser(shared,t.fetch);
  await assert.rejects(a.apply(),/STORAGE/);assert.equal(t.posts().length,0);
 // Exercise the actual AbortController timeout path, with no HTTP connection.
 shared=sharedBrowser();let timedPosts=0;
 a=browser(shared,(url,opts)=>{timedPosts++;return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('SYNTHETIC_TIMEOUT'))));},shared.locks,true);
 await assert.rejects(a.apply(),/TIMEOUT/);assert.equal(a.record().state,'unknown');assert.equal(timedPosts,1);
 console.log('PASS actual doApply: stable payload, same-plan clicks/tabs/refresh, changed plans, disconnect, same-ID lookup, partial/errors, capability refusal');
}
const serverSource=fs.readFileSync(path.join(root,'opt/nba-reprice/backend/server.js'),'utf8'),security=require(path.join(root,'opt/nba-reprice/backend/api_security.js'));
function serverFixture(writeReady='true'){
 let handler,writes=0,mode='ok';const receipts=new Map();let reads=0;
 const deny=()=>{throw Error('real network/filesystem/subprocess forbidden')};
 const mocked={crypto,http:{createServer:f=>{handler=f;return {listen:deny}},request:deny},https:{request:deny},child_process:{execFile:deny},
  fs:{readFileSync:p=>{reads++;const id=path.basename(p,'.json');if(!receipts.has(id)){const e=Error();e.code='ENOENT';throw e;}return receipts.get(id);}},path,url:require('url'),os:{homedir:()=>'/synthetic-home'},'./api_security':security};
 const ctx=vm.createContext({require:n=>{assert(n in mocked);return mocked[n]},module:{},process:{env:{OPERATORS:JSON.stringify({'synthetic-admin':'wulv','synthetic-other':'DY','synthetic-reader':'viewer'}),WRITE_READY:writeReady},platform:'linux'},__dirname:path.join(root,'opt/nba-reprice/backend'),console:{log:()=>{},error:()=>{}},Buffer,Date,Set,Promise});
 ctx.require.main={};vm.runInContext(serverSource,ctx);
 ctx.fakeWrite=async(prices,operator,id)=>{
  writes++;const binding=vm.runInContext(`planIdentity(${JSON.stringify(prices)},${JSON.stringify(operator)},${JSON.stringify(id)})`,ctx);delete binding.planJson;
  if(mode==='timeout')throw Error('SYNTHETIC_TIMEOUT');
  return {...binding,ok:mode==='ok',state:mode==='pending'?'unknown':'completed',persistence:'file-fsync-only-no-power-loss-guarantee',error:mode==='ok'?undefined:'SYNTHETIC_PARTIAL',results:[],verify:{}};
 };
 vm.runInContext('adminWrite=fakeWrite;appendApplyLog=()=>{};',ctx);
 return {receipts,mode:v=>mode=v,reads:()=>reads,writes:()=>writes,request:async(method,url,token='synthetic-admin',body={})=>{
  const req=new EventEmitter();Object.assign(req,{method,url,headers:{authorization:'Bearer '+token,'content-type':'application/json'},socket:{remoteAddress:'127.0.0.1'},destroy:deny});
  let status,raw;const res={setHeader:()=>{},writeHead:s=>status=s,end:s=>raw=s};
  const work=handler(req,res);req.emit('data',JSON.stringify(body));req.emit('end');await work;return {status,body:JSON.parse(raw)};
 }};
}
async function routeTests(){
 const f=serverFixture(),id='a'.repeat(32),payload={requestId:id,confirm:'NBA_PRICE_APPLY',platforms:[{area:'PS',price:1}]};
 const success=await f.request('POST','/api/apply','synthetic-admin',payload);
 assert.equal((await f.request('POST','/api/apply','synthetic-admin',null)).status,400);
 assert.equal(success.status,200);for(const k of ['requestId','planSha256','operator','state'])assert(success.body[k]);
 assert.equal(success.body.requestId,id);assert.equal(success.body.operator,'wulv');
 const disabled=serverFixture('false'),refusal=await disabled.request('POST','/api/apply','synthetic-admin',payload);
 assert.equal(refusal.status,403);assert.equal(refusal.body.requestId,id);assert.equal(refusal.body.planSha256,success.body.planSha256);assert.equal(refusal.body.operator,'wulv');assert.equal(refusal.body.state,'rejected');assert.equal(disabled.writes(),0);
 f.mode('partial');let r=await f.request('POST','/api/apply','synthetic-admin',payload);assert.equal(r.status,502);assert.equal(r.body.planSha256,success.body.planSha256);assert.equal(r.body.detail.requestId,id);assert.equal(r.body.state,'completed');
 f.mode('timeout');r=await f.request('POST','/api/apply','synthetic-admin',payload);assert.equal(r.body.state,'unknown');assert.equal(r.body.requestId,id);assert.equal(r.body.planSha256,success.body.planSha256);assert.equal(r.body.operator,'wulv');
 f.receipts.set(id,JSON.stringify(success.body));r=await f.request('GET','/api/receipt?requestId='+id);assert.deepEqual(r.body,success.body);
 const writes=f.writes(),reads=f.reads();
 assert.equal((await f.request('GET','/api/receipt?requestId='+id,'synthetic-reader')).status,403);assert.equal(f.reads(),reads);
 assert.equal((await f.request('GET','/api/receipt?requestId='+id,'invalid')).status,401);
 r=await f.request('GET','/api/receipt?requestId='+id,'synthetic-other');assert.equal(r.body.error,'RECEIPT_NOT_FOUND');assert.equal(r.body.planSha256,null);
 assert.equal((await f.request('POST','/api/receipt?requestId='+id)).status,405);
 assert.equal((await f.request('GET','/api/receipt?requestId=../bad')).status,400);
 f.receipts.set(id,JSON.stringify({...success.body,ok:false,state:'pending'}));assert.equal((await f.request('GET','/api/receipt?requestId='+id)).body.state,'unknown');
 f.receipts.set(id,'corrupt');assert.equal((await f.request('GET','/api/receipt?requestId='+id)).body.error,'RECEIPT_READ_FAILED');
 f.receipts.delete(id);assert.equal((await f.request('GET','/api/receipt?requestId='+id)).body.state,'unknown');assert.equal(f.writes(),writes);
 console.log('PASS actual HTTP handler: success/partial/timeout bindings; admin-owned GET receipt; readonly/other actor/method/path/corrupt/missing matrix; no lookup effect');
}
(async()=>{await uiTests();await routeTests();console.log(JSON.stringify({passed:true,scope:'actual doApply and HTTP handler in VM, synthetic browser/identities/receipts; all upstream and HTTP sockets forbidden'}));})().catch(e=>{console.error(e);process.exitCode=1;});
