const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../source/rs_filters.fragment.js'),'utf8');
const ctx={scope:{seed:{}},Number,Math,Object,String};vm.createContext(ctx);vm.runInContext(source,ctx);
const m=value=>({value,status:'available'}),period={start:'2026-10-23 00:00',end:'2026-10-24 00:00'};
const profile={key:'RS',period,supplement:{status:'available',period,scopeLabel:'RSOrders · 全部区服 · 货币',metrics:{revenueUsd:{...m(100),scope:'RSOrders'},orders:m(0)},rsSelection:{rs_site:'rsorders',rs_server:'all',rs_category:'currency'}},primary:{status:'available',period,metrics:{profitMarginPct:m(-15.81),orders:m(9)},scopeLabel:'Order 全部网站参考 · 货币'}};
let out=ctx.rsProjection(profile);assert.equal(out.metrics.orders.value,0);assert.equal(out.metrics.estimatedProfitUsd.value,-15.81);assert.match(out.metrics.profitMarginPct.scope,/全部网站参考/);
profile.primary.period={...period,end:'2026-10-25 00:00'};out=ctx.rsProjection(profile);assert.equal(out.metrics.profitMarginPct.value,null);assert.equal(out.metrics.estimatedProfitUsd.value,null);
assert.equal(ctx.rsChecked({b_rs_site:'rsorders',b_rs_category:'items'}).rs_site,'rsorders');assert.equal(ctx.rsChecked({rs_site:'<script>'}).rs_site,'all');
console.log('RS projection: Admin zero priority, negative reference profit, mismatched periods, source scope and saved-filter validation passed');
