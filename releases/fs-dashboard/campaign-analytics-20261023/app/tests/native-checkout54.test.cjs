const {test}=require('node:test');
const assert=require('node:assert/strict');
const {checkout}=require('../native-code-handoff.js');
function fixture(states=['confirmed']){
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};
 let posts=0,navigations=0;
 const opts={storage,options:{origin:'https://www.mmoexp.com',cartUrl:'/uk/Cart.html',sameTab:true,code:'SYNTHETIC',consumerBehaviorConfirmed:true},operationId:'synthetic-54',items:[{offer:{id:123,group:1,quantity:1,aid:456}}],liveVerified:true,
 host:{batch:()=>({run:async(items,progress)=>{posts++;const rows=states.map(state=>({id:123,state}));progress(rows);return rows;}})},navigate:()=>navigations++};
 return {opts,data,counts:()=>({posts,navigations})};
}
test('confirmed native batch stages once and same-tab navigates without claiming Apply',async()=>{
 const f=fixture();const r=await checkout(f.opts);assert.equal(r.state,'navigation_attempted_not_applied');assert.equal(f.data.get('pending_discount_code'),'SYNTHETIC');
 f.data.delete('pending_discount_code');await checkout(f.opts);assert.deepEqual(f.counts(),{posts:1,navigations:1});assert.equal(f.data.has('pending_discount_code'),false);
});
test('unknown or rejected native result retains operation and never stages code',async()=>{
 for(const state of ['unknown','rejected']){const f=fixture([state]);assert.equal((await checkout(f.opts)).state,'cart_incomplete_inspect_original');await checkout(f.opts);assert.deepEqual(f.counts(),{posts:1,navigations:0});assert.equal(f.data.has('pending_discount_code'),false);}
});
test('existing other offer and cross origin fail before cart mutation',async()=>{
 const f=fixture();f.data.set('pending_discount_code','EXISTING');await assert.rejects(checkout(f.opts),/PENDING_CODE_CONFLICT/);assert.equal(f.counts().posts,0);
 f.opts.options.origin='https://47.85.224.112';await assert.rejects(checkout(f.opts),/HANDOFF_ORIGIN_UNVERIFIED/);
 const g=fixture();g.opts.options.cartUrl=new URL('https://www.mmoexp.com/Cart.html');await assert.rejects(checkout(g.opts),/HANDOFF_ORIGIN_UNVERIFIED/);assert.equal(g.counts().posts,0);
});
test('same operation different contents fails; timeout reload cannot retry',async()=>{
 const f=fixture();f.opts.host.batch=()=>({run:async()=>{throw Error('timeout');}});assert.equal((await checkout(f.opts)).state,'unknown');f.opts.host.batch=()=>{throw Error('MUST NOT RUN');};assert.equal((await checkout(f.opts)).state,'unknown');
 f.opts.items[0].offer.quantity=2;await assert.rejects(checkout(f.opts),/OPERATION_CONFLICT/);
});
test('missing live verification and failed durable write cannot call cart',async()=>{
 const f=fixture();await assert.rejects(checkout({...f.opts,liveVerified:false}),/NOT_VERIFIED/);
 f.opts.storage.setItem=()=>{throw Error('quota');};await assert.rejects(checkout(f.opts),/quota/);assert.equal(f.counts().posts,0);
});
test('pending operation snapshots lines and code against concurrent UI edits',async()=>{
 const f=fixture(),core=require('../activity-core.js');let release;const pending=new Promise(r=>release=r),sent=[];
 f.opts.items.push({offer:{id:124,group:1,quantity:1,aid:456}});
 f.opts.host.batch=()=>core.createBatch(async data=>{sent.push(data);if(sent.length===1)await pending;return {code:1};});
 const operation=checkout(f.opts);f.opts.items[1].offer.quantity=99;f.opts.options.code='CHANGED';release();
 assert.equal((await operation).state,'navigation_attempted_not_applied');assert.equal(sent[1].num,'1');assert.equal(f.data.get('pending_discount_code'),'SYNTHETIC');
});
