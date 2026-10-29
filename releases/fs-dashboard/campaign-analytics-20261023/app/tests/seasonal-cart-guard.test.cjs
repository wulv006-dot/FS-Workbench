const test=require('node:test'),assert=require('node:assert/strict'),h=require('../native-code-handoff.js');
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k),values};};
function fixture(){
 const durable=memory(),session=memory();let held=false,cart=[],calls=0,navigations=0,answer='confirmed',pause=null;
 const locks={async request(_name,_options,fn){if(held)return fn(null);held=true;try{return await fn({name:_name});}finally{held=false;}}};
 const host={async readCart(){return {status:'native_cart_read',items:structuredClone(cart)};},batch(){return {async run(items,progress){calls++;if(pause)await pause;const rows=items.map(item=>({id:item.offer.id,state:answer}));if(answer==='confirmed')cart.push(...items.map(item=>({category:item.native_payload.category,id:item.native_payload.id,num:item.native_payload.num})));progress(rows);return rows;}};}};
 const approved=(id='101',code='SYNTHETIC10')=>({options:{origin:'https://www.mmoexp.com',cartUrl:'/Cart.html',sameTab:true,code,consumerBehaviorConfirmed:true},items:[{product_key:'synthetic-'+id,native_payload:{category:'new_items',id,group:'1',num:'1',attr:'',aid:'100'},offer:{id:Number(id),group:1,quantity:1,aid:100}}]});
 const snapshot={release_id:'campaign-preview-1',config_hash:'a'.repeat(64)};
 const submit=(a=approved(),guard=h.createCartGuard({storage:durable,locks}))=>guard.checkout({snapshot,approved:a,storage:session,host,navigate(){navigations++;session.removeItem('pending_discount_code');}});
 return {durable,session,locks,host,approved,snapshot,submit,get cart(){return cart;},set cart(v){cart=v;},get calls(){return calls;},get navigations(){return navigations;},set answer(v){answer=v;},set pause(v){pause=v;}};
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
