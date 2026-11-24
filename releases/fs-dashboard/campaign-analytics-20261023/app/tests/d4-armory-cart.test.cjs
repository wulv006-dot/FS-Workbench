const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {checkList,nativeOffer,receipt} = require('../d4-armory-cart.js');
const gear = {kind:'gear',id:'187713191',number:'45677343',categoryId:1943,cid:1945,quantity:1,price:2.02,name:'Helm #45677343'};
const gem = {kind:'gem',id:'169833273',number:'43039177',categoryId:3867,quantity:11,price:.01953,name:'Grand Ruby (Lv.30)'};
const row = line => ({id:Number(line.id),gid:456,aid:15943,cid:line.cid||line.categoryId,mid:Number(line.number),title:line.name,
  status:1,num:1,min_qty:1,auto_off:line.kind==='gear'?1:0,total:line.kind==='gear'?1:0,price:String(line.price),saleprop:[],has_sku:false});
const list = () => ({realm:'15943',expiresAt:new Date(Date.now()+60000).toISOString(),lines:[gear,gem]});
test('requires an unexpired realm-matched list with unique IDs',()=>{
  assert.ok(checkList(list()));
  for (const patch of [{realm:'1000'}, {expiresAt:'2020-01-01'}, {lines:[gear,gear]}]) assert.throws(()=>checkList({...list(),...patch}));
});
test('limited equipment and unlimited socket goods use native stock and exact product identity',()=>{
  assert.ok(nativeOffer(gear,row(gear)));
  assert.equal(nativeOffer(gem,row(gem)).price,.01953);
  assert.equal(nativeOffer(gem,row(gem)).payload.num,'11');
  for(const patch of [{total:0},{aid:1},{id:1},{mid:1},{cid:1},{gid:1},{title:'different #1'},{status:0},{has_sku:true},{saleprop:{x:{id:4}}}]) assert.equal(nativeOffer(gear,{...row(gear),...patch}),null);
  assert.equal(nativeOffer(gem,{...row(gem),min_qty:20}),null);
});
test('explicit failure takes precedence over top-level success; malformed data stays uncertain',()=>{
  assert.equal(receipt({code:1,cart:{add:{status:false}}}),'rejected');
  for(const no of [0,'0',false]) { assert.equal(receipt({code:1,data:{cart:{add:{status:no}}}}),'rejected');assert.equal(receipt({status:no,code:1}),'rejected'); }
  assert.equal(receipt({code:1,data:{cart:{add:{status:'pending'}}}}),'unknown');
  assert.equal(receipt({}),'unknown');assert.equal(receipt({code:1}),'confirmed');
});
const script=fs.readFileSync(require.resolve('../d4-armory-cart.js'),'utf8');
async function browser({storage=new Map(),answers=[],latePrice=false,hash='#list=8e3e6910-6d42-4c35-8e31-0ab16199a807'}={}) {
  const nodes=new Map(),requests=[],navigations=[];let lookups=0;
  const element=()=>({children:[],textContent:'',append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;},addEventListener(k,f){this[k]=f;}});
  for(const id of ['confirm','status','lines','subtotal']) nodes.set(id,element());
  const document={getElementById:id=>nodes.get(id),createDocumentFragment:element,
    createElement:tag=>tag==='template'?{content:{querySelector:()=>({})}}:element()};
  const location={origin:'https://www.mmoexp.com',hash,assign:url=>navigations.push(url)};
  const fetch=async(url,init)=>{
    requests.push([url,String(init.body||'')]);
    if (url.includes('/api/loadouts/')) return {ok:true,json:async()=>list()};
    if(url==='/Cart.html') return {ok:true,text:async()=>'<ul></ul>'};
    if(url==='/ajax/goods') {
      ++lookups;const line=init.body.get('keyword')===gear.number?gear:gem;
      const data=row(line);if(latePrice&&lookups>2)data.price='3.12';
      return {ok:true,json:async()=>({goods:{index:{list:[data],total:1,perpage:28}}})};
    }
    if(url==='/Cart/add.html') {const answer=answers.shift();if(answer instanceof Error)throw answer;return {ok:true,json:async()=>answer||{code:1}};}
    throw Error('Unexpected store request '+url);
  };
  vm.runInNewContext(script,{document,location,fetch,Intl,URLSearchParams,AbortSignal,Date,
    navigator:{locks:{request:async(k,o,f)=>f({})}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}});
  await new Promise(r=>setImmediate(r));return {nodes,requests,navigations,storage,button:nodes.get('confirm')};
}
test('appends exact lines without clearing the existing cart; reload cannot send a second batch',async()=>{
  const b=await browser();await b.button.click();assert.deepEqual(b.navigations,['/Cart.html']);
  const cart=b.requests.filter(([url])=>url.startsWith('/Cart'));assert.deepEqual(cart.map(r=>r[0]),['/Cart.html','/Cart/add.html','/Cart/add.html']);
  assert.ok(cart[2][1].includes('num=11'));const reopened=await browser({storage:b.storage});assert.ok(reopened.button.hidden);assert.equal(reopened.button.click,undefined);
});
test('reprice requires a new explicit click; ambiguous partial batch cannot be replayed',async()=>{
  const changed=await browser({latePrice:true});await changed.button.click();assert.equal(changed.requests.some(r=>r[0]==='/Cart/add.html'),false);
  await changed.button.click();assert.equal(changed.navigations.length,1);
  const b=await browser({answers:[{code:1},Error('timeout')]});await b.button.click();assert.equal(b.navigations.length,0);
  assert.deepEqual(Object.values(JSON.parse([...b.storage.values()][0])).sort(),['confirmed','unknown']);
  const reopened=await browser({storage:b.storage});assert.ok(reopened.button.hidden);assert.equal(reopened.button.click,undefined);
});
test('a direct visit offers a return link without requesting products or altering the cart',async()=>{const b=await browser({hash:''});assert.ok(b.button.hidden);assert.equal(b.requests.length,0);assert.match(b.nodes.get('status').textContent,/Open a selection/);});
