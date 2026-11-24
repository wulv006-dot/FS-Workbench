const test=require('node:test');
const assert=require('node:assert/strict');
const {createStore,normalize,readCounts}=require('../d4-armory-store.js');
const native=require('../d4-armory-cart.js');
const gear={kind:'gear',id:'123',number:'100',categoryId:1943,cid:1945,quantity:1,name:'Helm #100',price:2.49};
const gem={kind:'gem',id:'456',number:'4560',categoryId:3867,quantity:3,name:'Grand Ruby',price:.01953};
const other={...gem,kind:'rune',id:'789',number:'7890',categoryId:3959,quantity:1,name:'Tir'};
const id='44444444-4444-4444-8444-444444444444';
const secondId='55555555-5555-4555-8555-555555555555';
function fixture({inventory=new Map(),quote,add,now=Date.now,lock=true}={}) {
  const stored=new Map(), calls=[],lookups=[],cart=new Map(inventory);let reads=0;
  const core={...native,lookup:async(line,strict)=>{
    assert.equal(strict,true);lookups.push(line.id);
    const price=quote?quote(line):line.price;if(price==null)return null;
    return {name:line.name,price,payload:{id:line.id,num:String(line.quantity)}};
  },add:async payload=>{
    calls.push(payload);
    const result=add?add(payload,calls.length,cart):{code:1};
    if(result.code===1)cart.set(payload.id,(cart.get(payload.id)||0)+Number(payload.num));
    return result;
  }};
  const checkout=createStore({goods:async()=>core,counts:async()=>{reads++;return new Map(cart);},now,
    locks:{request:async(k,o,f)=>f(lock?{}:null)},storage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v)}});
  return {run:(lines,opts={})=>checkout({attemptId:id,lines,...opts}),lookups,calls,cart,reads:()=>reads};
}
test('live lookup once per line, one original cart read, append with existing inventory intact',async()=>{
  const f=fixture({inventory:new Map([['999',4]])});const progress=[];
  const r=await f.run([gear,gem],{onProgress:x=>progress.push(x.phase)});
  assert.equal(r.state,'confirmed');assert.deepEqual(f.lookups,['123','456']);assert.equal(f.reads(),1);
  assert.deepEqual(f.calls,[{id:'123',num:'1'},{id:'456',num:'3'}]);assert.equal(f.cart.get('999'),4);
  assert.deepEqual(progress,['checking','adding','adding']);assert.equal((await f.run([gear,gem])).state,'confirmed');assert.equal(f.calls.length,2);
});
test('existing unique is not added twice even with a new intent; repeated regular items merge',async()=>{
  const f=fixture({inventory:new Map([['123',1]])});const r=await f.run([gear,gem,{...gem,quantity:2}]);
  assert.equal(r.lines[0].state,'already_in_cart');assert.deepEqual(f.calls,[{id:'456',num:'5'}]);
  await f.run([gear],{attemptId:secondId});assert.equal(f.calls.length,1);assert.throws(()=>normalize([gear,gear]));
});
test('stock or validation failures stop all new writes',async()=>{
  const f=fixture({quote:l=>l.kind==='gear'?null:l.price});
  const r=await f.run([gem,gear]);assert.equal(r.state,'unavailable');assert.equal(r.lines[1].state,'unavailable');assert.equal(f.calls.length,0);
  assert.equal((await f.run([{...gear,number:null}])).state,'unavailable');assert.equal(f.calls.length,0);
});
test('inline price confirmation uses buyer-visible precision and short acceptance reuses the checked row',async()=>{
  const f=fixture({quote:l=>l.kind==='gear'?2.49285:.02953});let calls=0;
  assert.equal((await f.run([gear,gem],{onPriceChange:async changes=>{calls++;assert.deepEqual(changes.map(x=>x.id),['456']);return false;}})).state,'cancelled');
  assert.equal(f.calls.length,0);
  const r=await f.run([gear,gem],{onPriceChange:()=>true});assert.equal(r.state,'confirmed');assert.equal(f.lookups.length,4);assert.equal(calls,1);
});
test('slow acceptance rechecks availability and cannot add sold equipment',async()=>{
  let time=Date.now(),inStock=true;
  const f=fixture({now:()=>time,quote:()=>inStock?4.99:null});
  const r=await f.run([gear],{onPriceChange:()=>{inStock=false;time+=40000;return true;}});
  assert.equal(r.state,'unavailable');assert.equal(f.calls.length,0);assert.equal(f.lookups.length,2);
});
test('uncertain post checks current native quantity and never automatically replays',async()=>{
  let sent=false;
  const f=fixture({add:(p,n,cart)=>{if (!sent){sent=true;cart.set(p.id,Number(p.num));throw Error('lost response');}return {code:1};}});
  assert.equal((await f.run([gem])).state,'confirmed');assert.equal(f.reads(),2);assert.equal(f.calls.length,1);
  assert.equal((await f.run([gem])).state,'confirmed');assert.equal(f.calls.length,1);
  const g=fixture({add:(p,n)=>{if(n===2)throw Error('unconfirmed');return {code:1};}});
  const r=await g.run([gem,other]);assert.equal(r.state,'unknown');assert.deepEqual(r.lines.map(x=>x.state),['confirmed','unknown']);
  assert.equal((await g.run([gem,other])).state,'unknown');assert.equal((await g.run([other],{attemptId:secondId})).state,'unknown');assert.equal(g.calls.length,2);
});
test('busy lock and explicit rejections are reported; partial success is preserved',async()=>{
  const b=fixture({lock:false});assert.equal((await b.run([gear])).state,'busy');assert.equal(b.calls.length,0);
  const f=fixture({add:(p,n)=>n===2?{code:1,data:{cart:{add:{status:false}}}}:{code:1}});
  const r=await f.run([gear,gem]);assert.equal(r.state,'rejected');assert.deepEqual(r.lines.map(x=>x.state),['confirmed','rejected']);
  assert.equal((await f.run([gear,gem])).state,'confirmed');assert.deepEqual(f.calls.map(c=>c.id),['123','456','456']);
});
test('changed attempt payload is refused even after completion',async()=>{
  const f=fixture();await f.run([gem]);assert.equal((await f.run([{...gem,quantity:6}])).state,'unavailable');assert.equal(f.calls.length,1);
});
test('native cart parser counts scoped item keys without executing markup and leaves other categories alone',()=>{
  const row=(cat,key,qty)=>({getAttribute:k=>k==='data-cart-category'?cat:key,querySelector:()=>({getAttribute:()=>qty})});
  function document(rows){return {createElement:()=>({content:{querySelectorAll:()=>rows,querySelector:()=>null}})};}
  assert.deepEqual([...readCounts('<ignored>',document([row('new_items',"'cart_key_new_items' + 'ITEM_123_1'",'2'),row('service',null,5)]))],[['123',2]]);
  assert.throws(()=>readCounts('',document([row('new_items','invalid','1')])));
});
test('actual native catalog lookup requires a positive equipment stock count and exact identity',async()=>{
  const oldFetch=globalThis.fetch;
  const listed={id:123,mid:100,gid:456,aid:15943,cid:1945,status:1,auto_off:1,total:1,num:1,min_qty:1,price_discount:'2.49',title:'Helm #100'};
  try {
    const probe=async patch=>{
      globalThis.fetch=async(path,opts)=>{
        assert.equal(path,'/ajax/goods');assert.equal(opts.credentials,'same-origin');
        const body=new URLSearchParams(opts.body);assert.equal(body.get('keyword'),'100');
        return {ok:true,json:async()=>({goods:{index:{list:[{...listed,...patch}],total:1}}})};
      };
      return native.lookup(gear,true);
    };
    assert.equal((await probe({})).payload.id,gear.id);
    for(const patch of [{auto_off:0},{auto_off:null},{total:0},{total:null},{total:'unknown'},{mid:99},{aid:3},{status:0}]) assert.equal(await probe(patch),null);
  } finally {globalThis.fetch=oldFetch;}
});
test('a completed intent reports earlier processing when its native item was removed and sends no new write',async()=>{
  const f=fixture();await f.run([gear]);f.cart.clear();
  const replay=await f.run([gear]);assert.equal(replay.state,'cancelled');assert.ok(replay.processed);assert.match(replay.message,/already processed/);assert.equal(f.calls.length,1);
});