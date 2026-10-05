const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../../fs_range_read_state_20261001/exact-range-client.js'),'utf8');
const baseline=path.join(__dirname,'../../fs_range_read_state_20261001/exact-range-client.js');
function fixture(fetcher){
 const events=[],renders=[];
 const window={FSSupplementInsights:{render:(host,d,key,s,status)=>{host.items=[];renders.push({key,s,status,d});}},dispatchEvent:e=>events.push(e)};
 const ctx=vm.createContext({window,fetch:fetcher,AbortController,URLSearchParams,DOMException,Event:class {constructor(type){this.type=type}},CustomEvent:class {constructor(type,data){this.type=type;Object.assign(this,data)}},FSBusinessRange:{select:(d,s)=>d,matches:()=>false},document:{createElement:tag=>({tag,dataset:{},textContent:''})},setTimeout:(fn,ms)=>setTimeout(fn,ms>=30000?15:1),clearTimeout,Date,Map,WeakMap,Error,Number,Promise});
 // Expose closures only in the VM fixture. Production source has no testing export.
 vm.runInContext(source.replace('root.FSExactRange={peek,render};','root.FSExactRange={peek,render};root.__test={load,rangeRequest};'),ctx);
 return {window,events,renders};
}
const selection={start:'2026-09-01',end:'2026-09-02',grain:'day'},data={snapshotId:'synthetic-v1',profiles:{MMOEXP:{}}};
const ok=(s=selection)=>({status:'available',baseSnapshotId:data.snapshotId,profile:{key:'MMOEXP',name:'Synthetic',primary:{},period:{end:s.end},supplement:{metrics:{new_people:0,repeat_rate:null}}},query:s,generatedAt:'2026-10-05T00:00:00Z',rangeId:'SYNTHETIC'});
const response=(status,payload)=>({status,ok:status===200,json:async()=>payload});
const settle=()=>new Promise(r=>setTimeout(r,25));
(async()=>{
 let count=0, f=fixture(async()=>{count++;return response(count===1?202:count===2?429:200,count<3?{retryAfter:0.001}:ok());});
 const result=await f.window.__test.load(data,'MMOEXP',selection,new AbortController().signal);assert.equal(count,3);assert.equal(result.profile.supplement.metrics.new_people,0);assert.equal(result.profile.supplement.metrics.repeat_rate,null);
 for(const status of [409,422,503]){f=fixture(async()=>response(status,{}));await assert.rejects(f.window.__test.load(data,'MMOEXP',selection,new AbortController().signal));}
 f=fixture(async()=>response(200,{...ok(),baseSnapshotId:'stale-version'}));await assert.rejects(f.window.__test.load(data,'MMOEXP',selection,new AbortController().signal),/合同/);
 let captured;f=fixture((_,opts)=>{captured=opts.signal;return new Promise(()=>{});});await assert.rejects(f.window.__test.load(data,'MMOEXP',selection,new AbortController().signal),/超时/);assert(captured.aborted);
 f=fixture(async()=>({status:200,ok:true,json:()=>new Promise(()=>{})}));await assert.rejects(f.window.__test.load(data,'MMOEXP',selection,new AbortController().signal),/超时/);
 let ac=new AbortController();ac.abort();f=fixture(()=>{throw Error('fetch should not start')});await assert.rejects(f.window.__test.load(data,'MMOEXP',selection,ac.signal),{name:'AbortError'});
 ac=new AbortController();f=fixture(()=>new Promise(()=>{}));let waiting=f.window.__test.load(data,'MMOEXP',selection,ac.signal);ac.abort();await assert.rejects(waiting,{name:'AbortError'});
 // Late old selection must not overwrite the new selection even when fetch ignores abort.
 const pending=[];f=fixture((url,opts)=>new Promise(resolve=>pending.push({url,opts,resolve})));
 const host={items:[],prepend(v){this.items.unshift(v)},querySelector(){return null},querySelectorAll(){return []}};
 f.window.FSExactRange.render(host,data,'MMOEXP',selection);await new Promise(r=>setTimeout(r,5));
 const newer={...selection,end:'2026-09-03'};f.window.FSExactRange.render(host,data,'MMOEXP',newer);await new Promise(r=>setTimeout(r,5));
 assert.equal(pending.length,2);pending[1].resolve(response(200,ok(newer)));await new Promise(r=>setTimeout(r,3));pending[0].resolve(response(200,ok()));await settle();
 assert.equal(f.events.filter(e=>e.type==='fs-exact-range').length,1);assert.equal(f.events.find(e=>e.type==='fs-exact-range').detail.selection.end,newer.end);
 const final=f.renders.at(-1);assert.equal(final.d.exactRange.query.end,newer.end);
 // Cross-range failure renders explicit error, never an old exact response.
 f=fixture(async()=>response(422,{}));f.window.FSExactRange.render(host,data,'MMOEXP',selection);await settle();assert.equal(f.renders.at(-1).status,'error');assert(!f.renders.at(-1).d.exactRange);
 console.log(JSON.stringify({passed:true,scope:'candidate exact-range closures/renderer in synthetic DOM; 202/429,409/422,timeout/decode/abort/races/missing-vs-zero; no real browser/network'}));
})().catch(e=>{console.error(e);process.exitCode=1});
