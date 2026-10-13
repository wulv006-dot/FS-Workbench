const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../frontend/fc-detail.js','utf8');
const line=source.split('\n').find(s=>s.startsWith('const fcQuery='));
const context={fcDetailState:{tab:'fulfillment'},fcPool:'current',fcFilters:{site_group:'main',platform:'PC'},currentSelection:()=>({start:'2026-10-11',end:'2026-10-11',grain:'day'})};
vm.createContext(context);vm.runInContext(line+'\nthis.query=fcQuery;',context);
assert.equal(context.query().pool,'current');
context.fcDetailState.tab='consumption';assert.equal(context.query().pool,'paid');
context.fcDetailState.tab='review';assert.equal(context.query().pool,'paid');
assert.equal(context.query({pool:'current'}).pool,'current');
assert.equal(context.query().platform,'PC');
console.log('FC query context: 5 assertions passed; consumption/report paid, fulfillment current, drill override retained.');

// Exercise the actual reader: stale HTTP 200 must render before the refresh ends.
const reader=source.slice(source.indexOf('async function fcRead('),source.indexOf('\nfunction fcDetailSync('));
const valid={contractId:'fc27-detail-analytics-v1',query:{start:'2026-10-11',end:'2026-10-11'},snapshot_id:'fc-detail-test'};
function harness(replies,onWait){
 const requests=[];
 const ctx={URLSearchParams,Date,DOMException,fcWait:async(ms,signal)=>{if(signal.aborted)throw new DOMException('Aborted','AbortError');onWait?.(ms);},
  fetch:async url=>{requests.push(url);const value=replies.shift();assert(value,'unexpected request');return {status:value.status||200,ok:!value.status||value.status===200,json:async()=>value.body};}};
 vm.createContext(ctx);vm.runInContext(reader+'\nthis.read=fcRead;',ctx);return {...ctx,requests};
}
(async()=>{
 const q={...valid.query,refresh:'true'},seen=[];
 const h=harness([{body:{...valid,stale:true,refreshing:true}},{body:{...valid,snapshot_id:'fc-detail-fresh'}}],ms=>{assert.equal(seen.length,1,'cached snapshot must precede wait');assert.equal(ms,10000);});
 await h.read(q,new AbortController().signal,d=>seen.push(d));
 assert.equal(seen.length,2);assert.equal(q.refresh,'true','reader must not mutate caller query');assert(!h.requests[1].includes('refresh='));
 const immediate=harness([{body:{...valid,stale:true,refreshing:true}}],()=>assert.fail('paging/export must not wait for background collection'));
 assert.equal((await immediate.read(valid.query,new AbortController().signal)).stale,true);assert.equal(immediate.requests.length,1);
 const pending=harness([{status:202,body:{retryAfter:3}},{body:valid}]);assert.equal((await pending.read(valid.query,new AbortController().signal)).snapshot_id,valid.snapshot_id);
 const denied=harness([{status:401,body:{error:'denied'}}]);await assert.rejects(denied.read(valid.query,new AbortController().signal));
 const wrong=harness([{body:{...valid,query:{start:'2026-10-10',end:'2026-10-11'}}}]);await assert.rejects(wrong.read(valid.query,new AbortController().signal));
 const cancel=new AbortController();cancel.abort();const stopped=harness([]);await assert.rejects(stopped.read(valid.query,cancel.signal),{name:'AbortError'});assert.equal(stopped.requests.length,0);
 let writes=0;const node={get textContent(){return 'same';},set textContent(v){writes++;}};
 vm.runInContext(source.split('\n').find(s=>s.startsWith('const fcSetText='))+'\nthis.setText=fcSetText;',context);context.setText(node,'same');assert.equal(writes,0);context.setText(node,'different');assert.equal(writes,1);
 console.log('FC responsiveness: stale-first, background refresh, immediate paging/export, pending, auth/range failure, cancellation and idempotent DOM passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
