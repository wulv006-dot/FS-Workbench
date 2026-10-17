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

// Render the actual overview helper, including mixed known/unknown source fields.
const overview=source.slice(source.indexOf('function fcRiskOverview('),source.indexOf('\nconst fcTable='));
const renderContext={esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),fcMoney:v=>'$'+v.toFixed(2)};
vm.createContext(renderContext);vm.runInContext(overview+'\nthis.render=fcRiskOverview;',renderContext);
const metric={orders:2,known_orders:2,amount_usd:40,known_amount_usd:40,missing_amount_orders:0,unknown_selection_orders:0};
const risk={status:'available',as_of:'2026-10-14T12:00:00+08:00',high_amount_usd:300,issues:metric,waiting24:metric,high_amount:metric,
 aging:{under24:1,'24to72':2,at_least72:3,unknown_time:0,created_time_fallback:1}};
const html=renderContext.render({current_risks:risk});
assert(html.includes('当前问题单')&&html.includes('等待至少24小时')&&html.includes('高金额未结案'));
assert(html.includes('2 单 · $40.00')&&html.includes('不是损失')&&html.includes('不受所选支付日期限制'));
assert(html.includes('回退下单时间')&&html.includes('三组可重叠，不相加'));
assert.equal(renderContext.render({current_risks:risk}),html,'same snapshot rendering is idempotent');
const unknown={...risk,status:'partial',issues:{...metric,amount_usd:null,known_amount_usd:40,missing_amount_orders:1},
 waiting24:{...metric,orders:null,known_orders:1},high_amount:{...metric,orders:null,known_orders:0,unknown_selection_orders:1},aging:{...risk.aging,unknown_time:2}};
const partial=renderContext.render({current_risks:unknown});
assert(partial.includes('已知 1 单')&&partial.includes('已知金额')&&partial.includes('缺金额 1 单')&&partial.includes('时间暂缺 2 单'));
assert(partial.includes('未判定是否高金额'));
for(const r of [undefined,{status:'not_available'}]){const text=renderContext.render({current_risks:r});assert(text.includes('合计暂缺'));assert(!text.includes('0 单'));}
const unsafe=renderContext.render({current_risks:{...risk,issues:{...metric,amount_usd:'<img onerror=alert(1)>'}}});
assert(!unsafe.includes('<img'));
console.log('FC current-risk overview: scope, unknowns, incomplete/legacy data, escaping and idempotence passed.');

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
