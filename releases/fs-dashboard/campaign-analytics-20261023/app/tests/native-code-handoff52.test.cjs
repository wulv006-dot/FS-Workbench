const test=require('node:test'),assert=require('node:assert/strict'),h=require('../native-code-handoff.js');
const opts={origin:'https://www.mmoexp.com',cartUrl:'/uk/Cart.html',sameTab:true,code:' SYNTHETIC-CODE ',consumerBehaviorConfirmed:true};
test('Same-tab native handoff preserves language path and never reports applied',()=>{
 const data=new Map([['unrelated','keep']]);const storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
 const operation={id:'synthetic-op'};
 assert.equal(h.stage(storage,opts,operation).state,'staged_not_applied');assert.equal(data.get('pending_discount_code'),'SYNTHETIC-CODE');assert.equal(data.get('unrelated'),'keep');
 assert.equal(h.stage(storage,opts,operation).cartUrl,'https://www.mmoexp.com/uk/Cart.html');
 assert.throws(()=>h.stage(storage,{...opts,code:'OTHER'},{id:'other'}),/CONFLICT/);assert.equal(data.get('pending_discount_code'),'SYNTHETIC-CODE');
 data.delete('pending_discount_code');h.stage(storage,opts,operation);assert.equal(data.has('pending_discount_code'),false);
 assert.throws(()=>h.stage(storage,{...opts,code:'OTHER'},operation),/OPERATION_CONFLICT/);
});
test('No cross-origin, new-tab, invented URL parameters or hidden auto Apply',()=>{
 for(const patch of [{origin:'https://47.85.224.112'},{origin:'https://mmoexp.com'},{cartUrl:'https://elsewhere.test/Cart.html'},{cartUrl:'/uk/Cart.html?code=x'},{sameTab:false},{consumerBehaviorConfirmed:false},{code:''}])assert.throws(()=>h.plan({...opts,...patch}));
});
test('Storage errors stay failures, no fallback clipboard/cookies or automatic retry',()=>{
 assert.throws(()=>h.stage({getItem(){throw Error('blocked');}},opts,{id:'blocked'}),/blocked/);
 const op={id:'unknown'};assert.throws(()=>h.stage({getItem(){return null;},setItem(){}},opts,op),/UNCONFIRMED/);assert.equal(op.state,'unknown');
 let writes=0;h.stage({getItem(){return null;},setItem(){writes++;}},opts,op);assert.equal(writes,0);
});
test('Durable record survives reload/consumption and interrupts before any retry',()=>{
 const data=new Map(),writes=[];const storage={getItem:k=>data.get(k)||null,setItem(k,v){writes.push(k);data.set(k,v);}};
 const result=h.stageDurable(storage,opts,'synthetic-durable');assert.equal(result.state,'staged_not_applied');assert.equal(writes[0],'fs-native-code:synthetic-durable');
 data.delete('pending_discount_code');const count=writes.length;assert.equal(h.stageDurable(storage,opts,'synthetic-durable').state,'staged_not_applied');assert.equal(writes.length,count);assert.equal(data.has('pending_discount_code'),false);
 const interrupted=new Map();const crash={getItem:k=>interrupted.get(k)||null,setItem(k,v){if(k==='pending_discount_code')throw Error('interruption');interrupted.set(k,v);}};
 assert.throws(()=>h.stageDurable(crash,opts,'interrupted'),/interruption/);assert.equal(JSON.parse(interrupted.get('fs-native-code:interrupted')).state,'unknown');assert.equal(h.stageDurable(crash,opts,'interrupted').state,'unknown');
});
