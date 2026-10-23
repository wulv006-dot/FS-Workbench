const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const api=require('../activity-core.js');
const config=require('./fixtures/catalog-baseline.json');
const fixture=require('./fixtures/cisse-live-catalog.json');
const state=()=>({view:'sbc',platform:'ps',core:config.sbc.defaultId,coreMode:'owned',companions:[...config.sbc.routes[config.sbc.defaultId].picks],weekly:new Set(config.weekly.ids),bundles:new Set()});
const cisse=()=>api.line(config.products['185916875'],'ps');

test('owned SBC core is excluded; completion mode adds its service exactly once',()=>{
 const s=state(),owned=api.selection(config,s);
 assert.equal(owned.length,2);assert(owned.every(x=>x.kind==='player'));
 assert.equal(owned.reduce((sum,x)=>sum+x.amount,0),3529);
 s.coreMode='service';const withService=api.selection(config,s);
 assert.equal(withService.length,3);assert.equal(withService.filter(x=>x.kind==='sbc').length,1);
 assert.equal(withService.reduce((sum,x)=>sum+x.amount,0),4153);
});
test('platform change uses actual distinct item IDs, not a console price multiplier',()=>{
 const s=state();s.platform='xbox';const xbox=api.selection(config,s);
 assert(xbox.some(x=>x.offer.id===185916883));assert(xbox.every(x=>x.offer.aid===21585));
 s.platform='pc';const pc=api.selection(config,s);
 assert(pc.some(x=>x.offer.id===185916879));assert.equal(pc.reduce((sum,x)=>sum+x.amount,0),3056);
});
test('baseline verifies the observed Star Performer IDs without a Signature substitution',()=>{
 const s=state();s.view='trio';const rows=api.selection(config,s);
 assert.deepEqual(rows.map(x=>x.offer.id),[185916899,185916875,185916851]);
 assert(rows.every(x=>x.version==='Star Performer'&&!x.title.includes('Signature')));
});
test('money math uses whole minor units and rejects malformed or free offers',()=>{
 assert.equal(api.minor('0.68'),68);assert.equal(api.minor('190.59'),19059);
 for(const value of ['-1','1e2','1.005','NaN','$1.00',''])assert.throws(()=>api.minor(value));
 const p=structuredClone(config.products['185916875']);p.platforms.ps.price='0.00';assert.throws(()=>api.line(p,'ps'));
 p.platforms.ps.price='8.01';p.platforms.ps.status=0;assert.throws(()=>api.line(p,'ps'));
});
test('cart payload matches shipped new_items controls and contains no invented bundle SKU',()=>{
 assert.deepEqual(api.payload(cisse()),{category:'new_items',id:'185916875',group:'1',num:'1',attr:'',aid:'21587'});
 const bundle=api.line(config.products[config.bundles.ids[0]],'ps');assert.equal(api.payload(bundle).category,'new_items');
});
test('live lookup accepts descriptive has_attr metadata from a real player record',async()=>{
 assert.equal(fixture.goods.index.list[0].has_attr,true);
 const calls=[];const row=await api.refreshLine(config,cisse(),async(url,body)=>{calls.push({url,body});return fixture;});
 assert.equal(row.amount,801);assert.equal(row.offer.group,fixture.goods.index.list[0].num);
 assert.equal(calls[0].url,'/ajax/goods');assert.equal(calls[0].body.keyword,'Alphadjo Cissè');
});
test('lookup finds the exact platform ID on a later page and rejects changed scope',async()=>{
 let calls=0;const result=await api.refreshLine(config,cisse(),async()=>++calls===1?{goods:{index:{list:[],total:13,perpage:12}}}:fixture);
 assert.equal(calls,2);assert.equal(result.offer.id,185916875);
 for(const change of [{gid:1},{title:'Different card version'},{aid:21589},{cid:9971},{status:0},{auto_off:1},{saleprop:[{id:1,name:'different option'}]}]){
  const bad=structuredClone(fixture);Object.assign(bad.goods.index.list[0],change);
  await assert.rejects(()=>api.refreshLine(config,cisse(),async()=>bad));
 }
});
test('response handling respects explicit nested rejection and legacy numeric/string success',()=>{
 assert.equal(api.result({code:1}).ok,true);assert.equal(api.result({code:'1'}).ok,true);
 assert.equal(api.result({code:1,data:{cart:{add:{status:false,msg:'off sale'}}}}).ok,false);
 assert.equal(api.result({data:{cart:{add:{total:3}}}}).ok,true);
 assert.equal(api.result({unexpected:true}).unknown,true);
});
test('successful batch sends each chosen item once, serially, and cannot be replayed',async()=>{
 const items=api.selection(config,{...state(),coreMode:'service'}),calls=[];
 const batch=api.createBatch(async body=>{calls.push(body.id);return {code:1};});
 const rows=await batch.run(items);assert.equal(rows.length,3);assert(rows.every(x=>x.state==='confirmed'));
 assert.deepEqual(calls,items.map(x=>String(x.offer.id)));await assert.rejects(()=>batch.run(items));assert.equal(calls.length,3);
});
test('partial rejection preserves confirmed receipts and never submits later items',async()=>{
 const items=api.selection(config,{...state(),coreMode:'service'});let calls=0;
 const batch=api.createBatch(async()=>++calls===1?{code:1}:{code:0,msg:'unavailable'});
 const rows=await batch.run(items);assert.deepEqual(rows.map(x=>x.state),['confirmed','rejected']);assert.equal(calls,2);
 await assert.rejects(()=>batch.run(items));assert.equal(calls,2);
});
test('transport uncertainty stops at that item and cannot silently retry',async()=>{
 const items=api.selection(config,{...state(),coreMode:'service'});let calls=0;
 const batch=api.createBatch(async()=>{calls++;if(calls===2)throw new Error('socket ended');return {code:1};});
 const rows=await batch.run(items);assert.deepEqual(rows.map(x=>x.state),['confirmed','unknown']);assert.equal(calls,2);
 await assert.rejects(()=>batch.run(items));assert.equal(calls,2);
});
test('every configured product has real three-platform IDs and an existing WebP',()=>{
 const current=require('../catalog.json');assert.equal(current.mode,'preview');assert(current.sbc.ids.length>0);assert(current.bundles.ids.length>0);
 for(const p of Object.values(current.products)){
  assert.equal(new Set(Object.values(p.platforms).map(x=>x.id)).size,3);
  for(const platform of ['ps','xbox','pc'])api.line(p,platform);
  const bytes=fs.readFileSync(path.join(__dirname,'..',p.image));assert.equal(bytes.toString('ascii',8,12),'WEBP');
 }
 assert.deepEqual(config.bundles.ids.map(key=>config.products[key].included.length),[4,5,7,7]);
 assert(!Object.values(config.products).some(p=>/Paris11|ManCity11|Player Pick/i.test(p.title)));
});
