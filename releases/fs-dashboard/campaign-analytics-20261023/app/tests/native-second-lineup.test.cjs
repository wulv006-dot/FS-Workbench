const {test}=require('node:test'),assert=require('node:assert/strict');
const {checkoutPublished}=require('../native-code-handoff.js');
// Repro: after a first lineup reached the cart page, a different lineup in the same
// tab (same sessionStorage) failed with OPERATION_CONFLICT before any cart request.
function fixture(){
  const keys=['p1','p2'],products=[],bindings=[];
  keys.forEach((key,i)=>{const goods=String(601+i);
    products.push({key,product_ref:{site_id:'266',game_id:'1327',model_id:String(201+i),goods_id:goods},platform:{code:'ps',attribute_id:'21587'},quantity:{min:'1',max:'1',step:'1',unit:'item',group:'1'},attributes:[]});
    bindings.push({activity_id:'fc27-season2',page_id:'fc27-weekly',product_key:key,quantity:{value:'1',unit:'item'},attributes:[],off_percent:10,code:'FIXTURE',native:{category:'new_items',id:goods,group:'1',num:'1',aid:'21587',attr:''}});});
  const snapshot={release_id:'fixture',config_hash:'a'.repeat(64),pages:[{page_id:'fc27-weekly',activity_id:'fc27-season2',active:true,product_keys:keys}],products,
    native_checkout:{status:'configured',verification_ref:'fixture',valid_from:'2020-01-01T00:00:00Z',valid_until:'2099-01-01T00:00:00Z',origin:'https://www.mmoexp.com',cart_path:'/Cart.html',consumer_behavior_confirmed:true,bindings}};
  const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};
  const state={posts:[],navigations:0,mode:'confirmed'};
  const host={batch:()=>({run:async(items,progress)=>{state.posts.push(items.map(x=>x.offer.id));const rows=items.map(x=>({id:x.offer.id,state:state.mode}));progress(rows);return rows;}})};
  const selection=key=>({activity_id:'fc27-season2',page_id:'fc27-weekly',off_percent:10,lines:[{product_key:key,quantity:{value:'1',unit:'item'},attributes:[]}]});
  const run=key=>checkoutPublished({snapshot,selection:selection(key),storage,host,navigate:()=>state.navigations++,origin:'https://www.mmoexp.com',couponClaimed:true,memberCouponId:99});
  return {data,state,run};
}
test('a different lineup after a finished hand-off starts a new operation',async()=>{
  const f=fixture();
  assert.equal((await f.run('p1')).state,'navigation_attempted_coupon_claimed');
  assert.equal((await f.run('p2')).state,'navigation_attempted_coupon_claimed');
  assert.deepEqual(f.state.posts,[[601],[602]]);assert.equal(f.state.navigations,2);
});
test('the same lineup again after a finished hand-off goes to the cart again',async()=>{
  const f=fixture();await f.run('p1');await f.run('p1');
  assert.deepEqual(f.state.posts,[[601],[601]]);assert.equal(f.state.navigations,2);
});
test('an unknown or incomplete operation still blocks a different lineup',async()=>{
  const f=fixture();f.state.mode='unknown';assert.equal((await f.run('p1')).state,'cart_incomplete_inspect_original');
  f.state.mode='confirmed';await assert.rejects(f.run('p2'),/OPERATION_CONFLICT/);assert.equal(f.state.posts.length,1);
});
