import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {randomUUID} from 'node:crypto';
import {halloweenFixture} from './halloween-fixture.mjs';import {createCommerce} from '../commerce.mjs';import {projectRelease} from '../snapshot.mjs';import handoff from '../../native-code-handoff.js';
import {quantityFixture} from './quantity-fixture.mjs';
test('Aion/WoW use one model and three distinct amounts; replay and wrong quantity checks hold',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'quantity-reveal-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const snapshot=quantityFixture(),c=createCommerce({snapshot,dir});
 for(const id of ['aion','diablo']){
  const receipt=c.halloweenReveal({request_id:randomUUID(),game_id:id});assert.equal(new Set(receipt.slots.map(x=>x.model_id)).size,1);assert.deepEqual(receipt.slots.map(x=>Number(x.quantity.value)).sort((a,b)=>a-b),[10,30,100]);assert.deepEqual(c.halloweenRead(receipt.request_id),receipt);
  const slot=receipt.slots[1],g=snapshot.halloween.games.find(g=>g.id===id),p=snapshot.products.find(p=>p.product_ref.model_id===g.fixed_model),query={request_id:receipt.request_id,game_id:id,...slot};
  assert.equal(c.halloweenResolve(query).status,'selection_confirmed');assert.throws(()=>c.halloweenResolve({...query,quantity:{...slot.quantity,value:'10'}}),{code:'HALLOWEEN_REVEAL_MISMATCH'});
  const selection={activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:g.admin_game_id,reveal_request_id:receipt.request_id,...slot,lines:[{product_key:p.key,quantity:slot.quantity,attributes:[]}]};
  const plan=handoff.publishedPlan(projectRelease(snapshot),selection,{origin:'https://www.mmoexp.com'});assert.equal(plan.items[0].native_payload.group,slot.quantity.value);
  assert.throws(()=>handoff.publishedPlan(projectRelease(snapshot),{...selection,lines:[{...selection.lines[0],quantity:{...slot.quantity,value:'10'}}]},{origin:'https://www.mmoexp.com'}),{code:'NATIVE_SCOPE_MISMATCH'});
 }
});
test('quantity mode never silently applies to FC/MapleStory or duplicate amounts',()=>{
 for(const mutate of [s=>s.halloween.games.find(g=>g.id==='aion').random_quantities[0].value='10',s=>s.halloween.games.find(g=>g.id==='aion').random_quantities[0].unit='K',s=>s.halloween.games.find(g=>g.id==='maplestory').random_source.mode='quantity_tiers']){
  const s=quantityFixture();mutate(s);assert.throws(()=>projectRelease(s));
 }
});
