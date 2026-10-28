import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {createCommerce} from '../commerce.mjs';
import {projectRelease} from '../snapshot.mjs';
import handoff from '../../native-code-handoff.js';
import {d4SeasonalFixture,d4Selected} from './d4-seasonal-fixture.mjs';

test('D4 candidate draws two distinct items from exactly five and validates every discount/native payload without live cart writes',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'d4-seasonal-candidate-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const snapshot=d4SeasonalFixture(),release=projectRelease(snapshot),commerce=createCommerce({snapshot,dir}),game=snapshot.halloween.games.find(g=>g.id==='diablo');
 assert.equal(game.admin_game_id,'456');assert.equal(game.fixed_model,'5264');assert.equal(game.fixed_off_percent,10);assert.deepEqual(game.random_models,['43191217','43039181','43039069','43038035','43038033']);
 assert.equal(snapshot.products.filter(p=>p.product_ref.game_id==='456').length,6);
 for(const product of snapshot.products.filter(p=>p.product_ref.game_id==='456')){assert.equal(product.platform.attribute_id,'15943');assert.deepEqual(product.attributes,[]);const contract=snapshot.seasonal_model_contracts[product.product_ref.model_id];assert.deepEqual(contract.fields[0].values,[{id:'15943',label:'Season 15 Softcore'}]);}
 async function exercise(slot,requestId){
  const product=snapshot.products.find(p=>p.product_ref.model_id===slot.model_id),binding=snapshot.native_checkout.bindings.find(b=>b.product_key===product.key&&b.off_percent===slot.off_percent),expected=d4Selected.find(x=>x.model===slot.model_id);
  const selection={activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:'456',...slot,...(requestId?{reveal_request_id:requestId}:{}),lines:[{product_key:product.key,quantity:{value:expected.quantity,unit:expected.unit},attributes:[]}]};
  const prepared=commerce.nativePlan(selection);assert.equal(prepared.native_checkout.bindings.length,1);assert.deepEqual(prepared.native_checkout.bindings[0].native,{category:expected.category,id:expected.goods,group:expected.group,num:'1',attr:'',aid:''});
  const data=new Map(),posts=[];let navigations=0;
  const host={verifySelection:async body=>commerce.halloweenResolve(body),batch:()=>({run:async items=>{posts.push(...items.map(x=>x.native_payload));return items.map(x=>({id:Number(x.native_payload.id),state:'confirmed'}));}})};
  const result=await handoff.checkoutPublished({snapshot:release,selection,storage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},host,origin:'https://www.mmoexp.com',navigate:()=>{navigations++;}});
  assert.equal(result.state,'navigation_attempted_not_applied');assert.deepEqual(posts,[binding.native]);assert.equal(navigations,1);assert.equal(data.get('pending_discount_code'),'D4-CANDIDATE-'+slot.off_percent);
 }
 await exercise({slot:'fixed',model_id:'5264',off_percent:10});
 const seen=new Set();
 for(let i=0;i<600&&seen.size<15;i++){
  const request_id=randomUUID(),receipt=commerce.halloweenReveal({request_id,game_id:'diablo'});
  assert.deepEqual(receipt.slots[0],{slot:'fixed',model_id:'5264',off_percent:10});assert.equal(new Set(receipt.slots.map(s=>s.model_id)).size,3);
  for(const slot of receipt.slots.slice(1)){assert(game.random_models.includes(slot.model_id));assert([8,15,10].includes(slot.off_percent));const key=slot.model_id+':'+slot.off_percent;if(!seen.has(key)){seen.add(key);await exercise(slot,request_id);}}
 }
 assert.equal(seen.size,15,'all five random models must be validated at 8%, 15% and 10%');
});
