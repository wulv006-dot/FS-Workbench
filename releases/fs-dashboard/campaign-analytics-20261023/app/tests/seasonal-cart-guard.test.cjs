const test=require('node:test'),assert=require('node:assert/strict'),h=require('../native-code-handoff.js');
const memory=()=>{const values=new Map();return {get length(){return values.size;},key:i=>[...values.keys()][i]??null,getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),values};};
function fixture(){
 const durable=memory(),session=memory();let held=false,cart=[],calls=0,navigations=0,answer='confirmed',pause=null;
 const locks={async request(_name,_options,fn){if(held)return fn(null);held=true;try{return await fn({name:_name});}finally{held=false;}}};
 const host={async readCart(){return {status:'native_cart_read',items:structuredClone(cart)};},batch(){return {async run(items,progress){calls++;if(pause)await pause;const rows=items.map(item=>({id:item.offer.id,state:answer}));if(answer==='confirmed')cart.push(...items.map(item=>({category:item.native_payload.category,id:item.native_payload.id,num:item.native_payload.num})));progress(rows);return rows;}};}};
 const approved=(id='101',code='SYNTHETIC10')=>({options:{origin:'https://www.mmoexp.com',cartUrl:'/Cart.html',sameTab:true,code,consumerBehaviorConfirmed:true},items:[{product_key:'synthetic-'+id,native_payload:{category:'new_items',id,group:'1',num:'1',attr:'',aid:'100'},offer:{id:Number(id),group:1,quantity:1,aid:100}}]});
 const snapshot={release_id:'campaign-preview-1',config_hash:'a'.repeat(64)};
 const selection={page_id:'seasonal-vault',activity_id:'mmoexp-seasonal',game_id:'456',model_id:'fixture',slot:'fixed',off_percent:10};
 const submit=(a=approved(),guard=h.createCartGuard({storage:durable,locks}))=>guard.checkout({snapshot,selection,approved:a,storage:session,host,navigate(){navigations++;session.removeItem('pending_discount_code');}});
 return {durable,session,locks,host,approved,snapshot,selection,submit,get cart(){return cart;},set cart(v){cart=v;},get calls(){return calls;},get navigations(){return navigations;},set answer(v){answer=v;},set pause(v){pause=v;}};
}
test('existing confirmed item opens cart; deleted item can be bought again without a daily/game limit',async()=>{
 const f=fixture();await f.submit();assert.equal(f.calls,1);await f.submit();assert.equal(f.calls,1);assert.equal(f.navigations,2);
 f.cart=[];await f.submit();assert.equal(f.calls,2);assert.equal(f.navigations,3);assert.equal(f.cart.length,1);
 f.cart=[];await f.submit(f.approved('202','OTHERGAME15'));assert.equal(f.calls,3);assert.equal(f.cart[0].id,'202');
});
test('one offer per cart blocks another product even with the same code; a different code never replaces it',async()=>{
 const f=fixture();await f.submit();assert.equal((await f.submit(f.approved('202'))).state,'cart_offer_conflict');assert.equal(f.calls,1);assert.equal(f.cart.length,1);
 const before=structuredClone(f.cart);assert.equal((await f.submit(f.approved('303','DIFFERENT15'))).state,'cart_code_conflict');assert.deepEqual(f.cart,before);assert.equal(f.calls,1);assert.equal(f.session.getItem('pending_discount_code'),null);
});
test('an unrelated or unrecognised existing cart is preserved',async()=>{
 const f=fixture();f.cart=[{category:'new_items',id:'999',num:'1'}];assert.equal((await f.submit()).state,'cart_code_conflict');assert.equal(f.calls,0);assert.equal(f.navigations,0);assert.equal(f.cart[0].id,'999');
});
test('known rejection can retry, but timeout/unknown survives reload without a second add',async()=>{
 const f=fixture();f.answer='rejected';await f.submit();assert.equal(f.calls,1);f.answer='confirmed';await f.submit();assert.equal(f.calls,2);
 const u=fixture();u.answer='unknown';await u.submit();assert.equal(u.calls,1);assert.equal((await u.submit()).state,'cart_unknown_inspect_original');assert.equal(u.calls,1);
 const restored=h.createCartGuard({storage:u.durable,locks:u.locks});assert.equal((await u.submit(u.approved('202','OTHER15'),restored)).state,'cart_unknown_inspect_original');assert.equal(u.calls,1);
 u.cart=[{category:'new_items',id:'101',num:'1'}];await u.submit();assert.equal(u.calls,1);assert.equal(u.navigations,1);
});
test('two tabs / rapid clicks coordinate one native POST, including a delayed response',async()=>{
 const f=fixture();let release;f.pause=new Promise(r=>release=r);const first=f.submit();await new Promise(r=>setImmediate(r));assert.equal((await f.submit(f.approved('202'))).state,'cart_busy_inspect_original');assert.equal(f.calls,1);release();await first;assert.equal(f.cart.length,1);
});
test('cart read failure and unavailable coordination/storage never issue a POST',async()=>{
 const f=fixture();f.host.readCart=async()=>{throw Error('NATIVE_CART_READ_UNAVAILABLE');};await assert.rejects(f.submit());assert.equal(f.calls,0);
 const g=fixture();await assert.rejects(g.submit(g.approved(),h.createCartGuard({storage:g.durable,locks:{}})),/CART_SYNC_UNAVAILABLE/);assert.equal(g.calls,0);
 const s=fixture();await assert.rejects(s.submit(s.approved(),h.createCartGuard({storage:{getItem(){return null;},setItem(){throw Error('blocked');}},locks:s.locks})));assert.equal(s.calls,0);
});
test('changed quantities and release contexts require cart review without adding or replacing a code',async()=>{
 const f=fixture();await f.submit();f.cart[0].num='2';assert.equal((await f.submit()).state,'cart_code_conflict');assert.equal(f.calls,1);
 const g=fixture();await g.submit();g.snapshot.release_id='campaign-preview-2';assert.equal((await g.submit(g.approved('202'))).state,'cart_code_conflict');assert.equal(g.calls,1);
});

function legacyPage(f,id='legacy-operation'){
 const a=f.approved(),signature=JSON.stringify([f.snapshot.release_id,f.snapshot.config_hash,{},[],f.selection]);
 f.session.setItem('fs-native-page:mmoexp-seasonal:seasonal-vault:fixture:fixed:fixed',JSON.stringify({id,signature}));
 return {a,id};
}
test('upgrading an old UNKNOWN session never submits a fresh ID, even after reload with an empty cart',async()=>{
 const f=fixture(),{a,id}=legacyPage(f);f.answer='unknown';
 await h.checkout({storage:f.session,options:a.options,operationId:id,items:a.items,host:f.host,navigate(){},liveVerified:true});
 assert.equal(f.calls,1);const original=f.session.getItem('fs-native-cart:'+id);
 for(let i=0;i<3;i++){
  const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
  assert.equal(guard.known().attempt.id,id);assert.equal((await guard.inspect(()=>f.host.readCart())).state,'unknown');
  assert.equal((await f.submit(f.approved('202','OTHER15'),guard)).state,'cart_unknown_inspect_original');
  assert.equal(f.calls,1);assert.equal(f.session.getItem('fs-native-cart:'+id),original);
 }
 assert.equal([...f.session.values.keys()].filter(k=>k.startsWith('fs-native-cart:')).length,1);
});
test('an old pending page or malformed original result also blocks new adds',async()=>{
 for(const raw of [null,'{bad json']){
  const f=fixture(),{id}=legacyPage(f);if(raw)f.session.setItem('fs-native-cart:'+id,raw);
  const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
  if(raw)await assert.rejects(f.submit(f.approved(),guard),/CART_JOURNAL_UNAVAILABLE/);
  else assert.equal((await f.submit(f.approved(),guard)).state,'cart_unknown_inspect_original');
  assert.equal(f.calls,0);
 }
});
test('an old confirmed add opens its existing cart without a POST; confirmed deletion permits rebuy',async()=>{
 const f=fixture(),{a,id}=legacyPage(f);
 await h.checkout({storage:f.session,options:a.options,operationId:id,items:a.items,host:f.host,navigate(){f.session.removeItem('pending_discount_code');},liveVerified:true});
 const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
 assert.equal((await guard.inspect(()=>f.host.readCart())).state,'selected');
 assert.equal((await f.submit(a,guard)).existingCart,true);assert.equal(f.calls,1);
 f.cart=[];await f.submit(a,guard);assert.equal(f.calls,2);
});
test('an old UNKNOWN is reconciled only by its exact original line, and acknowledged beyond bounded history',async()=>{
 const f=fixture(),{a,id}=legacyPage(f);f.answer='unknown';
 await h.checkout({storage:f.session,options:a.options,operationId:id,items:a.items,host:f.host,navigate(){},liveVerified:true});
 f.cart=[{category:'new_items',id:'101',num:'1'}];
 const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
 assert.equal((await guard.inspect(()=>f.host.readCart())).state,'recoverable');
 await f.submit(a,guard);assert.equal(f.calls,1);
 f.answer='confirmed';for(let i=0;i<22;i++){f.cart=[];await f.submit(a,guard);}
 assert.equal(f.calls,23);const journal=JSON.parse(f.durable.getItem('fs-seasonal-native-cart-v1'));
 assert.equal(journal.history.length,20);assert(journal.legacy_resolved_ids.includes(id));
 assert(f.session.getItem('fs-native-cart:'+id));
});
test('an unresolved old operation in another game blocks even a newer confirmed journey',async()=>{
 const f=fixture();await f.submit();const {id}=legacyPage(f);
 f.session.setItem('fs-native-cart:'+id,JSON.stringify({id,state:'unknown',outcomes:[]}));f.cart=[];
 const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
 assert.equal((await f.submit(f.approved('202','OTHER15'),guard)).state,'cart_unknown_inspect_original');assert.equal(f.calls,1);
});

test('the published entry point preserves an actual pre-upgrade UNKNOWN instead of bypassing its ID',async()=>{
 const {pathToFileURL}=require('node:url'),path=require('node:path');
 const {halloweenFixture}=await import(pathToFileURL(path.resolve(__dirname,'../runtime/tests/halloween-fixture.mjs')).href);
 const snapshot=halloweenFixture(),game=snapshot.halloween.games.find(x=>x.id==='diablo'),product=snapshot.products.find(x=>x.product_ref.model_id===game.fixed_model);
 const selection={activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:game.admin_game_id,model_id:game.fixed_model,slot:'fixed',off_percent:game.fixed_off_percent,lines:[{product_key:product.key,quantity:{value:product.quantity.min,unit:product.quantity.unit},attributes:[]}]};
 const f=fixture();f.answer='unknown';const args={snapshot,selection,storage:f.session,host:f.host,origin:'https://www.mmoexp.com',navigate(){}};
 await h.checkoutPublished(args);assert.equal(f.calls,1);const before=[...f.session.values];
 const guard=h.createCartGuard({storage:f.durable,legacyStorage:f.session,locks:f.locks});
 assert.equal((await h.checkoutPublished({...args,cartGuard:guard})).state,'cart_unknown_inspect_original');
 assert.equal(f.calls,1);assert.deepEqual([...f.session.values],before);
});
