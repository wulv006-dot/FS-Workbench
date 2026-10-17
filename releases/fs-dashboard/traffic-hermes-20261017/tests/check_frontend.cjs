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
assert(source.includes('generation!==scope.rangeGeneration'));assert(source.includes('scope.rangePending||generation!==(scope.rangeGeneration||0)'));assert(source.includes("scope.trafficProject??='FC27'"));
assert(!source.includes('Order主源'));assert(!source.includes('order.p2pah全网站订单主源'));assert(!source.includes('09:00'));
const brain=fs.readFileSync(path.join(__dirname,'../source/brain.js'),'utf8');assert(brain.includes('expected_version:latest?.version||0'));assert(brain.includes('uncertainBody||'));assert(brain.includes("'&actions=1'"));
console.log('PASS: full campaign calculation, brand separation, Admin zero, period/stale guards and UI request identity');
