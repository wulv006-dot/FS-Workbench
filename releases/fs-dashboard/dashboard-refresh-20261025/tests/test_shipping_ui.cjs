const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
for(const name of ['business.js','home-business.js','legacy-business.js']){
 const source=fs.readFileSync(path.join(__dirname,'../source',name),'utf8');
 let query={start:'2026-10-29',end:'2026-10-29',profit_site:'all',profit_category:'-1'},filters={site_group:'all',platform:'all'};
 const ctx=vm.createContext({currentSelection:()=>query,fcFilters:filters,rsSame:(a,b)=>['rs_site','rs_server','rs_category'].every(k=>a?.[k]===b?.[k]),rsScope:()=> 'RS'});
 vm.runInContext(source.slice(source.indexOf('function shippingMetrics('),source.indexOf('function shippingDailyDays(')),ctx);
 const period={start:'2026-10-29 00:00',end:'2026-10-30 00:00'},metric=value=>({value,status:'available'});
 const shipping={status:'available',currency:'CNY',sourceContract:'order-shipping-v1',profileKey:'FC27',period,shippingSelection:{site:'all',cid:'-1'},metrics:{profitCny:metric(40652.89),profitMarginPct:metric(28.48),shippingSalesCny:metric(142717.11),shippingCostCny:metric(102064.22)}};
 const profile={key:'FC27',shipping,supplement:{period,metrics:{profitMarginPct:metric(99)}}};
 assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,40652.89);assert.equal(ctx.shippingMetrics(profile,true).profitMarginPct.value,28.48);
 assert.equal(ctx.shippingMetrics(profile,false).profitCny.value,null);shipping.period={...period,end:'2026-10-29 12:00'};assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,null);shipping.period=period;
 filters.platform='PS';assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,null);filters.platform='all';
 shipping.stale=true;assert.equal(ctx.shippingMetrics(profile,true).profitCny.stale,true);shipping.metrics.profitCny=metric(-10);shipping.metrics.profitMarginPct=metric(-5);assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,-10);
 shipping.metrics.profitCny=metric(0);shipping.metrics.profitMarginPct={status:'not_applicable',value:null};assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,0);assert.equal(ctx.shippingMetrics(profile,true).profitMarginPct.status,'not_applicable');
 shipping.currency='USD';assert.equal(ctx.shippingMetrics(profile,true).profitCny.value,null);
 query={...query,rs_site:'rsorders',rs_server:'all',rs_category:'all'};
 const rs={key:'RS',supplement:{period},primary:{...shipping,currency:'CNY',sourceContract:'order-shipping-rs-v1',rsSelection:{...query}}};assert.equal(ctx.shippingMetrics(rs,true).profitCny.value,0);query.rs_site='rsmalls';assert.equal(ctx.shippingMetrics(rs,true).profitCny.value,null);
 assert.match(source,/data\.sources\?\.Shipping/);assert.match(source,/mode:'profit-history'/);assert.doesNotMatch(source.slice(source.indexOf('function renderProfit(){'),source.indexOf('function bindProfitTip(')),/procurementRead|fsEnsureProcurement/);
 console.log('PASS '+name+': native CNY values, scope/date/currency, FC filters, stale/loss/zero, RS and source polling');
}
