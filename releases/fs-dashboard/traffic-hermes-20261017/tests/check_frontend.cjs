const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'../../../..'),source=fs.readFileSync(path.join(root,'ui-system/modules/native/google.js'),'utf8');
function extract(name){const start=source.indexOf('function '+name+'('),next=source.indexOf('\n}',start)+2;assert(start>=0&&next>start);return source.slice(start,next);}
const context={};vm.createContext(context);vm.runInContext(extract('selectedAccounts')+'\n'+extract('nativeFields')+'\nthis.probe={selectedAccounts,nativeFields}',context);
const rows=[{campaign_scope:'global_brand',metrics:{cost:100,conversionsValue:500}},{campaign_scope:'project',game_target:'FC27',metrics:{cost:2,clicks:4,impressions:8,conversions:1,conversionsValue:10,interactions:5,nativeCvr:.2}}];
const account=context.probe.selectedAccounts({adsAccounts:[{brand:'mmoexp',campaigns:rows.slice(0,1),calculation_campaigns:rows,campaign_calculation_complete:true}]})[0];
assert.equal(account.metrics.cost,2);assert.equal(account.metrics.platformRoas,5);assert.equal(account.global_brand.length,1);assert.equal(account.metrics.nativeCvr,.2);
const legacy=context.probe.selectedAccounts({adsAccounts:[{brand:'mmoexp',campaigns:rows.slice(0,1)}]})[0];assert.equal(legacy.metrics.cost,null);assert.equal(legacy.selection_complete,false);
const period={start:'2026-10-15',end:'2026-10-15'},range={start:'2026-10-15 00:00',end:'2026-10-16 00:00'},field=(system,value)=>({system,status:'available',stale:false,period:range,orders:value,revenueUsd:value,metrics:{}});
const value={profile:{primary:field('order.p2pah.cn',10),supplement:field('admin.p2pah.cn',0)}};
assert.equal(context.probe.nativeFields(value,period).revenueUsd.value,0);value.profile.supplement.stale=true;assert.equal(context.probe.nativeFields(value,period).revenueUsd.value,10);
value.profile.primary.period={...range,end:'2026-10-17 00:00'};assert.equal(context.probe.nativeFields(value,period).revenueUsd,undefined);
assert(source.includes('generation!==scope.rangeGeneration'));assert(source.includes('scope.rangePending||generation!==(scope.rangeGeneration||0)'));assert(source.includes("scope.trafficProject??='all'"));
assert(!source.includes('Order主源'));assert(!source.includes('order.p2pah全网站订单主源'));assert(!source.includes('09:00'));
const brain=fs.readFileSync(path.join(__dirname,'../source/brain.js'),'utf8');assert(brain.includes('expected_version:latest?.version||0'));assert(brain.includes('uncertainBody||'));assert(brain.includes("'&actions=1'"));
console.log('PASS: full campaign calculation, brand separation, Admin zero, period/stale guards and UI request identity');

const business=fs.readFileSync(path.join(root,'ui-system/modules/native/business.js'),'utf8');
const begin=business.indexOf('function fsMainSite('),end=business.indexOf('\nfunction fsOrderLabel',begin);const metricsContext={fcDetailState:{data:{coverage:{paid_complete:true},query:{start:'x',end:'y'},totals:{orders:20,revenue_usd:20}}},currentSelection:()=>({start:'x',end:'y'})};vm.createContext(metricsContext);vm.runInContext(business.slice(begin,end)+'\nthis.main=fsMainSite',metricsContext);
const admin={status:'available',period:{start:'x',end:'y'},dimensions:{channels:[{code:'www.mmoexp.com',orders:150,revenueUsd:150}]},metrics:{}};const profile={key:'FC27',supplement:admin,primary:{period:admin.period,status:'available',currency:'USD',metrics:{profitMarginPct:{status:'available',value:10}}}};
assert.equal(metricsContext.main(profile).metrics.orders.value,150);assert.equal(metricsContext.main(profile).metrics.revenueUsd.value,150);admin.dimensions.channels[0].orders=0;admin.dimensions.channels[0].revenueUsd=0;assert.equal(metricsContext.main(profile).metrics.orders.value,0);
assert(!business.includes('es-order-structure'));assert(source.includes('generation===scope.esGeneration'));assert(source.includes('data.period?.start!==q.start'));assert(source.includes('scope.esAbort?.abort();clearTimeout(scope.esTimer)'));assert(source.includes('account.ad_groups?.rows'));console.log('PASS ES headline isolation including Admin zero and request identity');

admin.metrics.profitMarginPct={status:'available',value:0};assert.equal(metricsContext.main(profile).metrics.profitMarginPct.value,0);assert.equal(metricsContext.main(profile).metrics.profitMarginPct.source,'Admin');assert.equal(metricsContext.main(profile).metrics.estimatedProfitUsd.value,0);
profile.primary.metrics.orders={status:'available',value:17};profile.primary.metrics.revenueUsd={status:'available',value:34};admin.dimensions.channels=[];delete admin.metrics.orders;delete admin.metrics.revenueUsd;const supplemented=metricsContext.main(profile);assert.equal(supplemented.metrics.orders.value,17);assert.equal(supplemented.metrics.revenueUsd.value,34);assert.equal(supplemented.metrics.revenueUsd.source,'Order');assert(supplemented.metrics.revenueUsd.scope.includes('后台全站参考'));
admin.metrics.orders={status:'available',value:0};admin.metrics.revenueUsd={status:'available',value:0};assert.equal(metricsContext.main(profile).metrics.orders.value,0);assert.equal(metricsContext.main(profile).metrics.revenueUsd.value,0);console.log('PASS Admin margin zero, missing orders/revenue Order fallback and labelled scope');

// Exercise the actual ES query expression and endpoint; global default is six fields.
const esBody=source.slice(source.indexOf('function renderESStructure('),source.indexOf('function renderReportLinks('));
const esQuery=esBody.match(/const query=\(\)=>(\(\{mode:'hermes'.*?\}\));/)[1],esURL=esBody.match(/const response=await fetch\((.*?),\{credentials:/)[1];
const esRequestContext={URLSearchParams,profile:'ALL',period:{start:'2026-10-15',end:'2026-10-16'},group:{value:'game'},status:{value:'all'}};vm.createContext(esRequestContext);const esRequest=new URL(vm.runInContext('const q='+esQuery+';'+esURL,esRequestContext),'https://fs.invalid');
assert.equal(esRequest.pathname,'/dashboard/fs-home/advisor.json');assert.deepEqual(Object.fromEntries(esRequest.searchParams),{mode:'hermes',structure:'es',profile:'ALL',start:'2026-10-15',end:'2026-10-16',group_by:'game'});
assert(!source.includes('function renderDecisions('));assert(source.includes('尚未读取此窗口的ES结构'));assert.equal(context.probe.selectedAccounts({adsAccounts:[{brand:'mmoexp',calculation_campaigns:rows,campaign_count:rows.length,campaign_calculation_complete:true,metrics:{cost:102}}]},'D4')[0].metrics.cost,null);console.log('PASS global default, on-demand ES advisor query, business isolation and unsupported-game unknown');

const d4Rows=[...rows,{campaign_scope:'game_name_candidate',game_target:'D4',game_candidate:'D4',metrics:{cost:7}},{campaign_scope:'brand_scope_unverified',game_target:null,game_candidate:'D4',metrics:{cost:3}}];
const d4Period={game_profiles:[{code:'D4',scope:'name_hint_only'}],adsAccounts:[{brand:'mmoexp',calculation_campaigns:d4Rows,campaign_count:4,campaign_calculation_complete:true,metrics:{cost:112}}]};
const d4=context.probe.selectedAccounts(d4Period,'D4')[0];assert.equal(d4.metrics.cost,7);assert.equal(d4.unverified_brand.length,1);assert.equal(d4.unverified_brand[0].metrics.cost,3);assert.equal(context.probe.selectedAccounts(d4Period,'FC27')[0].metrics.cost,2);assert.equal(context.probe.selectedAccounts(d4Period,'AION2')[0].metrics.cost,null);assert.equal(d4Period.adsAccounts[0].metrics.cost,112);assert(source.includes('D4名称线索'));assert(source.includes('D4品牌归属待核广告组'));console.log('PASS D4 name hints exclude unverified brand and preserve native totals');

// Exercise the actual default-period upgrade controller with DOM-free form events.
(async()=>{
 class Node{constructor(){this.listeners={};this.dataset={};this.isConnected=true;}setAttribute(){}append(){}after(){}addEventListener(k,f){this.listeners[k]=f;}requestSubmit(){this.pending=this.listeners.submit({preventDefault(){}});}}
 const old={id:'legacy_week',start:'2026-10-05',end:'2026-10-11'},model={details:{periods:[old]}},root={},container=new Node();container.dataset={period:old.id,brand:'mmoexp'};container.isConnected=true;container.getRootNode=()=>root;
 const scope={root,model},scheduled=[],calls=[],rendered=[];
 const ctx={scope,URLSearchParams,structuredClone,Set,Intl,Date,el:()=>new Node(),setTimeout:f=>scheduled.push(f),currentTrafficPeriod:p=>p?.rule_version==='traffic-multigame-name-hints-20261017-v3',fetch:async url=>{calls.push(url);return {status:200,ok:true,json:async()=>({status:'available',start:old.start,end:old.end,period:{...old,game_projection_version:'traffic-game-projections-20261019-v1',rule_version:'traffic-multigame-name-hints-20261017-v3'}})};},render:(c,m)=>{rendered.push(m);c.querySelector=()=>({});}};
 vm.createContext(ctx);vm.runInContext(source.match(/function currentGamePeriod[^\n]+/)[0]+'\n'+extract('rangeControls')+'\nthis.rangeControls=rangeControls',ctx);
 const ensure=ctx.rangeControls(new Node(),container,model,[old],{value:old.id});ensure(old);assert.equal(calls.length,0);scheduled.shift()();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,1);assert(calls[0].startsWith('/dashboard/marketing/range.json?'));assert.equal(new URL(calls[0],'https://fs.invalid').searchParams.get('start'),old.start);assert.equal(rendered[0].details.periods.length,1);assert.equal(scope.customRange.period.rule_version,'traffic-multigame-name-hints-20261017-v3');
 ensure(old);assert.equal(scheduled.length,0);assert.equal(calls.length,1);
 const n=scheduled.length;ensure({start:old.start,end:old.end,game_projection_version:'traffic-game-projections-20261019-v1',rule_version:'traffic-multigame-name-hints-20261017-v3'});assert.equal(scheduled.length,n);
 assert(source.includes('全局维度参考 · 非所选游戏专属'));assert(source.includes('renderSourceBody(panel,p,site,scope.source)'));assert(source.includes("sites.setAttribute('aria-label','流量站点')"));assert(!source.includes('scrollIntoView'));
 console.log('PASS default legacy period upgrades via exact range once, current contract skips, ES remains separate, game details precede background');
})().catch(error=>{console.error(error);process.exitCode=1;});


// Real host capture applies restored URL state during its first notification.
// Notifications must be deferred to avoid recursively entering render/apply.
{
 const raf=[];let restored=false,applies=0,notifications=0;
 const ctx={workspaceQueued:false,scope:{root:{isConnected:true},changed(){notifications++;if(!restored){applies++;ctx.workspaceSync();restored=true;}}},requestAnimationFrame:f=>raf.push(f),workspaceState:()=>({g_source:'ga4'})};
 vm.createContext(ctx);vm.runInContext(source.match(/function workspaceSync[^\n]+/)[0]+'\nthis.workspaceSync=workspaceSync',ctx);
 ctx.workspaceSync();assert.equal(notifications,0);raf.shift()();raf.shift()();assert.equal(applies,1);assert.equal(notifications,2);assert.equal(raf.length,0);
 console.log('PASS shell URL restoration does not recursively re-enter render');
}

{
 const tasks=[],inputs={'流量开始日期':{},'流量结束日期':{}};let submitted=0,rendered=0;
 const form={isConnected:true,querySelector:q=>inputs[q.includes('开始')?'流量开始日期':'流量结束日期'],requestSubmit:()=>submitted++};
 const target={dataset:{},querySelector:()=>form};
 const ctx={scope:{model:{details:{periods:[]}},gameLabels:{all:'全部游戏'}},document:{getElementById:()=>target},window:{MMOEXPMarketing:{render:()=>rendered++}},setTimeout:f=>tasks.push(f)};
 vm.createContext(ctx);vm.runInContext(extract('workspaceApply')+'\nthis.apply=workspaceApply',ctx);
 assert.equal(ctx.apply({g_period:'custom_2026-10-01_2026-10-07',g_source:'ads',g_project:'all',g_brand:'mmoexp'}),true);
 assert.equal(rendered,1);assert.equal(inputs['流量开始日期'].value,'2026-10-01');assert.equal(inputs['流量结束日期'].value,'2026-10-07');tasks.shift()();assert.equal(submitted,1);assert.equal(ctx.scope.restoreRangeWanted,null);
 console.log('PASS custom date URL restores exact range without relabelling old results');
}
