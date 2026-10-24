const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..'),source=fs.readFileSync(path.join(root,'source/business.js'),'utf8');
const fragment=source.slice(source.indexOf('function fsProcurementProjection('),source.indexOf('function fsMainSite('));
const selection={start:'2026-10-15',end:'2026-10-21',grain:'day'};
const denominator={orders:10,completedOrders:8,coveredOrders:6,missingCostOrders:2,legacyRevenueOrders:0,pendingOrders:2,saleCny:1000,costCny:700,profitCny:300,margin:.3};
const payload=()=>({status:'available',revenueBasis:'admin_order_cny',period:{start:selection.start,end:selection.end},generatedAt:'2026-10-22T01:00:00Z',sources:{cost:{generatedAt:'2026-10-22T01:01:00Z'}},denominator:{...denominator}});
const pending=[],scope=new AbortController(),draws=[];
const ctx={scope:{signal:scope.signal},window:{addEventListener(){}},AbortController,URLSearchParams,Date,Number,JSON,Error,
 currentSelection:()=>({...selection}),fcFilters:{platform:'all',site_group:'main',customer:'all',product:'all',bucket:'all'},
 setTimeout:()=>1,clearTimeout(){},fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve})),
 fcWait:async()=>{},kpiCards:()=>draws.push(vm.runInContext('procurementRead?.id',ctx)),renderProfit(){},fcDetailShow(){}};
vm.createContext(ctx);vm.runInContext(fragment,ctx);
let checks=0;const check=(name,fn)=>{fn();checks++;console.log('PASS',name);};
check('covered cohort is not applied to all paid revenue',()=>{const r=ctx.fsProcurementProjection(payload(),selection);assert.equal(r.profitCny,300);assert.equal(r.margin,.3);assert.equal(r.coveredOrders,6);assert.equal(r.orders,10);assert.notEqual(r.profitCny,1000/6*10*.3);});
check('revenue and cost dates kept separately',()=>{const r=ctx.fsProcurementProjection(payload(),selection);assert.notEqual(r.capturedAt,r.costCapturedAt);});
check('legacy delivery revenue rejected',()=>assert.throws(()=>ctx.fsProcurementProjection({...payload(),revenueBasis:'legacy_delivery'},selection)));
check('mixed legacy cohort rejected',()=>{const r=payload();r.denominator.legacyRevenueOrders=1;assert.throws(()=>ctx.fsProcurementProjection(r,selection));});
check('another date cannot be displayed',()=>assert.throws(()=>ctx.fsProcurementProjection(payload(),{...selection,end:'2026-10-20'})));
check('missing cost does not become zero',()=>{const r=payload();Object.assign(r.denominator,{coveredOrders:0,missingCostOrders:8,saleCny:null,costCny:null,profitCny:null,margin:null});assert.equal(ctx.fsProcurementProjection(r,selection).profitCny,null);});
check('valid empty source is zero gross, not zero margin',()=>{const r=payload();Object.assign(r.denominator,{orders:0,completedOrders:0,coveredOrders:0,missingCostOrders:0,pendingOrders:0,saleCny:null,costCny:null,profitCny:null,margin:null});const out=ctx.fsProcurementProjection(r,selection);assert.equal(out.profitCny,0);assert.equal(out.margin,null);assert.ok(!ctx.fsProcurementNote({data:out}).includes('¥null'));});
check('zero revenue loss remains visible, margin undefined',()=>{const r=payload();Object.assign(r.denominator,{saleCny:0,costCny:5,profitCny:-5,margin:null});assert.equal(ctx.fsProcurementProjection(r,selection).profitCny,-5);});
check('loss is not clamped by pricing guard',()=>{const r=payload();Object.assign(r.denominator,{costCny:1200,profitCny:-200,margin:-.2});assert.equal(ctx.fsProcurementProjection(r,selection).margin,-.2);});
check('invalid weighted rate rejected',()=>{const r=payload();r.denominator.margin=.4;assert.throws(()=>ctx.fsProcurementProjection(r,selection));});
check('coverage cannot exceed completed population',()=>{const r=payload();r.denominator.coveredOrders=9;assert.throws(()=>ctx.fsProcurementProjection(r,selection));});
check('untrusted counts cannot become markup in the coverage status',()=>{const r=payload();r.denominator.pendingOrders='<svg onload=alert(1)>';assert.throws(()=>ctx.fsProcurementProjection(r,selection));});
check('current native Admin game ID reused',()=>assert.equal(ctx.fsProcurementQuery({key:'FC27',supplement:{filters:{game:'1327'}}},false,selection).gid,'1327'));
check('missing game ID never falls back to all games',()=>assert.equal(ctx.fsProcurementQuery({key:'FC27'},false,selection),null));
check('global primary site can aggregate games',()=>assert.ok(!('gid' in ctx.fsProcurementQuery({key:'MMOEXP'},false,selection))));
check('all-site and hourly views retain their reference method',()=>{assert.equal(ctx.fsProcurementQuery({key:'MMOEXP'},true,selection),null);assert.equal(ctx.fsProcurementQuery({key:'MMOEXP'},false,{...selection,grain:'hour'}),null);});
check('FC filtered and satellite views cannot show whole-game actual margin',()=>{ctx.fcFilters.platform='PS';assert.equal(ctx.fsProcurementQuery({key:'FC27'},false,selection),null);ctx.fcFilters.platform='all';ctx.fcFilters.site_group='satellite';assert.equal(ctx.fsProcurementQuery({key:'FC27'},false,selection),null);ctx.fcFilters.site_group='main';});
check('both current UI variants keep layout and independently retain actual procurement',()=>{assert.ok(source.includes('struct:0, detail:1'));const home=fs.readFileSync(path.join(root,'source/home-business.js'),'utf8');assert.ok(home.includes('struct:1, detail:1'));for(const s of [source,home]){assert.ok(s.includes("Object.assign(mainMetrics,shippingMetrics(profile,all))"));assert.ok(s.includes("separate.dataset.procurementIndependent='true'"));assert.ok(!s.includes("source:revenueMetric.source+' × '+rateMetric.source"));}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const first=ctx.fsEnsureProcurement({key:'FC27',supplement:{filters:{game:'1327'}}});
 const second=ctx.fsEnsureProcurement({key:'NBA2K27',supplement:{filters:{game:'1329'}}});
 check('switch cancels previous filter read',()=>assert.ok(first.abort.signal.aborted));
 pending[0].resolve({status:200,ok:true,json:async()=>payload()});pending[1].resolve({status:200,ok:true,json:async()=>payload()});await flush();await flush();
 check('late first result cannot paint new game',()=>{assert.equal(first.data,null);assert.equal(second.data.profitCny,300);assert.ok(draws.every(id=>id===second.id));});
 check('request uses existing read-only channel endpoint and current game',()=>{assert.ok(pending[1].url.startsWith('/dashboard/channel-effects/data.json?'));assert.ok(pending[1].url.includes('gid=1329'));assert.equal(pending[1].options.credentials,'same-origin');assert.equal(pending[1].options.redirect,'error');});
 second.expiresAt=0;const denied=ctx.fsEnsureProcurement({key:'NBA2K27',supplement:{filters:{game:'1329'}}});pending[2].resolve({status:403,ok:false,json:async()=>{throw Error('HTML denial must not be parsed or retain old data');}});await flush();await flush();
 check('permission denial clears previous actual financial result',()=>{assert.equal(denied.data,null);assert.equal(denied.phase,'denied');});
 scope.abort();check('module close aborts and drops cost state',()=>{assert.ok(denied.abort.signal.aborted);assert.equal(vm.runInContext('procurementRead',ctx),null);});
 console.log(checks+' procurement checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
