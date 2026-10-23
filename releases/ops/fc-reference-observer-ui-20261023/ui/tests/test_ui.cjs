const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../source/fc27-reference-observer.js'),'utf8');
class Element {
  constructor(){this.children=[];this.textContent='';this.attributes={};}
  append(value){this.children.push(value);}
  replaceChildren(){this.children=[];}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(){}
}
async function run(data,status=200){
  const elements=new Map(),requests=[];
  const document={hidden:false,getElementById:id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:()=>new Element()};
  const context={document,Date,Number,Error,AbortController,setTimeout,clearTimeout,setInterval(){},fetch:async(url,options)=>{requests.push({url,options});return{ok:status===200,status,json:async()=>data};}};
  vm.runInNewContext(script,context);await new Promise(r=>setImmediate(r));return {elements,requests};
}
(async()=>{
  const empty={service:{ActiveState:'inactive'},observed_count:0,window_count:0,comparable_count:0,history:[]};
  let {elements,requests}=await run(empty);
  assert.match(elements.get('reference-meta').textContent,/没有成功采样/);
  assert.equal(elements.get('reference-prices').children.length,3);
  assert.equal(elements.get('reference-market').children.length,15);
  assert.equal(elements.get('reference-observer').attributes['aria-busy'],'false');
  assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/fc27/cloud/reference-observer');assert.equal(requests[0].options.method,undefined);
  const offer={source:'ItemD2R',platform:'PS',status:'valid',gross_usd:'9.85',purchase_k:'100',bonus_k:'0',effective_usd_per_k:'.0985',captured_at:'2026-10-23T07:44:00Z'};
  const sample={run_id:'original-id',status:'observed',itemd2r:[offer],market:[offer],weighted:[],simulation_status:'not_comparable_capture_span',completed_at:offer.captured_at};
  ({elements}=await run({...empty,latest_observed:sample,latest_attempt:sample,observed_count:1,window_count:1,history:[sample],service:{ActiveState:'failed'}}));
  assert.match(elements.get('reference-summary').textContent,/未完成/);
  assert.equal(elements.get('reference-prices').children[0].children[1].textContent,'$9.85');
  assert.match(elements.get('reference-meta').textContent,/相隔超过5分钟/);
  assert.equal(elements.get('reference-history').children.length,1);
  ({elements}=await run({},403));assert.match(elements.get('reference-error').textContent,/登录权限不可用/);
  assert.equal(elements.get('reference-refresh').disabled,false);
  console.log('observer UI: empty, prices, missing, failed service, denied auth, GET-only checks passed');
})().catch(e=>{console.error(e);process.exit(1);});
