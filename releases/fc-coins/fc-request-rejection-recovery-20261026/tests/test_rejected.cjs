const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../source/fc27-quote-cloud.js'),'utf8');
const api=source.slice(source.indexOf('  async function api('),source.indexOf('  function chosen('));
const submit=source.slice(source.indexOf('  async function submit('),source.indexOf("  $('refresh').onclick"));
const pending=source.slice(source.indexOf('  async function waitJob('),source.indexOf('  async function submit('));
function setup(status,data){
 const storage=new Map(),calls=[],messages=[];const env={BASE:'/api/fc27/cloud',busy:false,pendingKey:'pending',crypto:{randomUUID:()=> 'original-id'},
  sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  $:()=>({classList:{add(){}}}),buttons(){},status:s=>messages.push(s),error:e=>{env.lastError=e},checkPending:async()=>{},
  fetch:async(url,options)=>{calls.push({url,options});return {ok:status>=200&&status<300,status,json:async()=>data}}};
 vm.createContext(env);vm.runInContext(api+'\n'+submit,env);return {env,storage,calls,messages};
}
(async()=>{
 for(const kind of ['collect','preview','execute']){
  const x=setup(503,{error:'queue_mutation_busy',accepted:false,retryable:true});
  await x.env.submit('/pricing/'+kind,{},kind);assert.equal(x.storage.size,0);assert(x.messages.some(s=>s.includes('明确未受理')));assert.equal(x.calls.length,1);
  assert.equal(JSON.parse(x.calls[0].options.body).client_event_id,'original-id');
 }
 for(const data of [{error:'queue_unavailable'},{error:'uncertain',accepted:true}]){
  const x=setup(503,data);await x.env.submit('/reprice/execute',{preview_id:'original-preview'},'execute');
  assert.equal(JSON.parse(x.storage.get('pending')).id,'original-id');assert(x.messages.some(s=>s.includes('未知')));assert.equal(x.calls.length,1);
 }
 const rejected=setup(403,{error:'write_role_required'});await rejected.env.submit('/reprice/execute',{},'execute');assert.equal(rejected.storage.size,0);
 const unknown=setup(404,{error:'not_found'});unknown.storage.set('pending',JSON.stringify({id:'original-id',kind:'execute'}));
 vm.runInContext(pending,unknown.env);await unknown.env.checkPending();assert.equal(JSON.parse(unknown.storage.get('pending')).id,'original-id');assert.equal(unknown.calls.length,1);assert.equal(unknown.calls[0].options.method,undefined);
 const network=setup(200,{});network.env.fetch=async()=>{throw Error('network_lost')};await network.env.submit('/reprice/execute',{},'execute');assert.equal(JSON.parse(network.storage.get('pending')).id,'original-id');
 const html=fs.readFileSync(path.join(__dirname,'../source/fc27-coins.html'),'utf8');assert(html.includes('fc-request-rejection-20261026-v1'));assert(html.includes('临时按ItemD2R同平台、同量含赠送单价一致'));
 console.log('8 scenarios: explicit rejection released; unknown/network/GET404 retained; no replay');
})().catch(error=>{console.error(error);process.exitCode=1});
