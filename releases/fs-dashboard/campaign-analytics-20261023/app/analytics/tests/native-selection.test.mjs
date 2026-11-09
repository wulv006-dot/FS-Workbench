import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {makeCenterStore,initialCenterDraft} from '../center-store.mjs';import {centerSeed} from '../center-seed.mjs';
const catalog=JSON.parse(fs.readFileSync(new URL('../../catalog.json',import.meta.url)));
test('publish scopes private checkout bindings to current page selection without mutating policy',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'native-selection-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const seed=centerSeed(catalog,{products:[]}),keys=seed.pageProductKeys['fc27-weekly'];assert(keys.length>1);
 const policy={status:'configured',verification_ref:'isolated-selection',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings:keys.map(key=>{const p=seed.seedProducts.find(x=>x.key===key);return {activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:key,quantity:{value:p.quantity.min,unit:'item'},attributes:[],off_percent:10,code:'SYNTHETIC-ONLY',native:{category:'new_items',id:p.product_ref.goods_id,group:p.quantity.group,num:p.quantity.min,attr:'',aid:p.platform.attribute_id}};})};
 const original=JSON.stringify(policy),publicDir=path.join(dir,'public'),store=makeCenterStore({dir:path.join(dir,'center'),publicDir,sourceRevision:'test',seedProvider:()=>seed,nativeCheckoutProvider:()=>policy});
 const draft=initialCenterDraft();draft.pages.find(p=>p.page_id==='fc27-weekly').product_keys=[keys[0]];
 store.save({revision:0,operation_id:randomUUID(),draft},'fixture');store.publish({revision:1,operation_id:randomUUID()},'fixture');
 const snapshot=JSON.parse(fs.readFileSync(path.join(publicDir,'current.json')));assert.deepEqual(snapshot.native_checkout.bindings.map(b=>b.product_key),[keys[0]]);assert.equal(JSON.stringify(policy),original);
 policy.bindings[0].native.aid='999';assert.throws(()=>store.publish({revision:2,operation_id:randomUUID()},'fixture'),{code:'NATIVE_CONFIGURATION_INVALID'});
});
