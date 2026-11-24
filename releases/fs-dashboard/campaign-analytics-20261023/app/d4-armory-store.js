/* Live, same-origin cart adapter for the D4 Build Shop. */
(() => {
  'use strict';
  const storeOrigin='https://www.mmoexp.com';
  const key='mmoexp:d4-inline-cart:v1';
  const validId=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const finished=state=>state==='confirmed'||state==='already_in_cart';
  function normalize(input) {
    if (!Array.isArray(input)||!input.length||input.length>120) throw Error('Choose at least one available product.');
    const rows=new Map();
    for (const raw of input) {
      const line={kind:raw.kind,id:String(raw.id),name:raw.name,number:raw.number==null?null:String(raw.number),
        categoryId:raw.categoryId,cid:raw.cid,quantity:raw.quantity,price:Number(raw.price)};
      if (!Number.isSafeInteger(line.quantity)||line.quantity<1||!Number.isFinite(line.price)||line.price<=0) throw Error('Invalid product quantity or price.');
      const prev=rows.get(line.id);
      if (prev) {
        if (line.kind==='gear'||prev.kind!==line.kind||prev.number!==line.number||prev.categoryId!==line.categoryId||prev.cid!==line.cid||prev.price!==line.price) throw Error('Conflicting entries for the same product.');
        prev.quantity+=line.quantity;
      } else rows.set(line.id,line);
    }
    return [...rows.values()];
  }
  function readCounts(markup,document) {
    const inert=document.createElement('template');
    inert.innerHTML=markup;
    const rows=[...inert.content.querySelectorAll('li[data-cart-category]')];
    if (!rows.length && !inert.content.querySelector('.no-c-box .no-title')?.textContent.toLowerCase().includes('empty')) throw Error('Your current cart could not be verified.');
    const counts=new Map();
    for (const row of rows) {
      if (row.getAttribute('data-cart-category')!=='new_items') continue;
      const binding=row.getAttribute(':class')||'';
      const parts=binding.match(/'[A-Za-z0-9_]+'/g)||[];
      if (binding.replace(/\s/g,'')!==parts.join('+')) throw Error('Your cart returned an unrecognized item.');
      const nativeKey=parts.map(part=>part.slice(1,-1)).join('');
      const id=nativeKey.match(/ITEM_([1-9]\d*)_/)?.[1];
      const quantity=Number(row.querySelector('input.item-num')?.getAttribute('value'));
      if (!id||!Number.isSafeInteger(quantity)||quantity<1) throw Error('Your current item quantities could not be verified.');
      counts.set(id,(counts.get(id)||0)+quantity);
    }
    return counts;
  }
  async function nativeCounts() {
    const r=await fetch('/Cart.html',{credentials:'same-origin',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(15000)});
    if (!r.ok) throw Error('Your existing cart could not be opened.');
    return readCounts(await r.text(),document);
  }
  function createStore({goods,counts,locks,storage,now=Date.now}) {
    return async function checkout({attemptId,lines:input,onProgress,onPriceChange,signal}={}) {
      let rows=[],results=[];
      const answer=(state,message)=>({state,lines:results.map(r=>({...r})),message});
      let writeStarted=false;
      try {
        if (!validId.test(attemptId)) throw Error('This cart attempt has no valid reference.');
        rows=normalize(input);
        const core=await goods();
        core.checkList({realm:'15943',expiresAt:new Date(now()+60000).toISOString(),lines:rows});
        if (rows.some(r=>r.kind==='gear'&&!r.number)) throw Error('The exact equipment listing number is missing.');
        results=rows.map(r=>({id:r.id,name:core.productText(r.name),quantity:r.quantity,state:'pending'}));
        if (!locks?.request) throw Error('Please use a browser that supports safe cart updates.');
        return await locks.request('mmoexp:d4-build-cart',{ifAvailable:true},async lock=>{
          if (!lock) return answer('busy','Another cart update is in progress. Try again when it finishes.');
          const data=JSON.parse(storage.getItem(key)||'{"attempts":{},"unresolved":{}}');
          if (!data?.attempts||!data?.unresolved) throw Error('Your saved cart progress could not be verified.');
          const signature=JSON.stringify(rows.map(({id,kind,number,quantity,cid,categoryId})=>[id,kind,number,quantity,cid,categoryId]));
          const journal=data.attempts[attemptId]||{signature,at:now(),items:{}};
          if (journal.signature!==signature) throw Error('This cart reference already belongs to a different selection.');
          const persist=()=>{
            const encoded=JSON.stringify(data);
            storage.setItem(key,encoded);
            if (storage.getItem(key)!==encoded) throw Error('Your browser could not preserve the cart progress.');
          };
          // Retain ambiguous operations. Completed interactions eventually expire from browser storage.
          for (const [id,old] of Object.entries(data.attempts)) {
            if (id!==attemptId && now()-old.at>30*86400000 && !Object.values(data.unresolved).some(u=>u.attempt===id)) delete data.attempts[id];
          }
          data.attempts[attemptId]=journal;
          const restore=()=>results.forEach(r=>Object.assign(r,journal.items[r.id]||{}));
          const update=(i,fields)=>{Object.assign(results[i],fields);journal.items[rows[i].id]={...results[i]};journal.at=now();persist();};
          restore();
          if (results.every(r=>finished(r.state))) {
            // A successful past receipt does not imply the shopper kept the item.
            try {
              const liveCart=await counts();
              if (results.every(r=>(liveCart.get(r.id)||0)>=r.quantity)) return {...answer('confirmed','This selection is already in your cart.'),processed:true};
            } catch { /* Never replay a completed attempt just because its cart cannot be read. */ }
            return {...answer('cancelled','This selection was already processed. View your cart or start a new selection.'),processed:true};
          }
          const report=event=>{try{onProgress?.(event);}catch{/* UI feedback cannot change a cart receipt. */}};
          report({phase:'checking',total:rows.length});
          const pending=rows.map((_,i)=>i).filter(i=>!finished(results[i].state));
          const live=new Array(rows.length);
          let next=0;
          const worker=async()=>{while(next<pending.length){const i=pending[next++];live[i]=await core.lookup(rows[i],true);}};
          const [current]=await Promise.all([counts(),...Array.from({length:Math.min(3,pending.length)},worker)]);
          for (const i of pending) {
            const line=rows[i], outstanding=data.unresolved[line.id];
            if (outstanding) {
              if ((current.get(line.id)||0)!==outstanding.after) {
                Object.assign(results[i],{state:'unknown',message:'Check the current cart before adding this product again.'});
                return answer('unknown','An earlier add is unconfirmed. Check your cart before continuing.');
              }
              const previous=data.attempts[outstanding.attempt];
              if (!previous?.items?.[line.id]) throw Error('Your earlier cart operation could not be verified.');
              previous.items[line.id].state='confirmed';delete data.unresolved[line.id];persist();
              if (outstanding.attempt===attemptId || line.kind==='gear') {
                update(i,{state:outstanding.attempt===attemptId?'confirmed':'already_in_cart'});continue;
              }
              // The earlier addition is accounted for. A new click may represent a new
              // purchase, but an unresolved consumable must never be silently added twice.
              return answer('cancelled','Your previous add is now confirmed. Review your cart before adding another quantity.');
            }
            if (line.kind==='gear'&&(current.get(line.id)||0)>0) {update(i,{state:'already_in_cart'});continue;}
            if (!live[i]) {Object.assign(results[i],{state:'unavailable',message:'This listing or quantity is no longer available.'});continue;}
            Object.assign(results[i],{state:'pending',price:live[i].price,name:core.productText(live[i].name)});
          }
          if (results.some(r=>r.state==='unavailable')) return answer('unavailable','One or more selected items are unavailable.');
          const active=pending.filter(i=>!finished(results[i].state));
          const changes=active.filter(i=>core.priceChanged(rows[i],live[i].price)).map(i=>({
            id:rows[i].id,name:results[i].name,quantity:rows[i].quantity,previousPrice:rows[i].price,price:live[i].price
          }));
          if (changes.length) {
            const shown=now();
            if (typeof onPriceChange!=='function'||await onPriceChange(changes)!==true) return answer('cancelled','The updated prices were not accepted.');
            if (now()-shown>30000) {
              for (const i of active) {
                const fresh=await core.lookup(rows[i],true);
                if (!fresh || fresh.price!==live[i].price || JSON.stringify(fresh.payload)!==JSON.stringify(live[i].payload)) {
                  Object.assign(results[i],{state:fresh?'pending':'unavailable',...(fresh?{price:fresh.price}:{})});
                  return answer(fresh?'cancelled':'unavailable','This listing changed while you were reviewing it. Check the current selection again.');
                }
              }
            }
          }
          for (const i of active) {
            if (signal?.aborted) return answer('cancelled','The remaining items were not added.');
            const line=rows[i], before=current.get(line.id)||0, after=before+line.quantity;
            report({phase:'adding',line:{...results[i]},index:i+1,total:rows.length});
            data.unresolved[line.id]={attempt:attemptId,before,after};
            update(i,{state:'unknown'});writeStarted=true;
            let state='unknown';
            try {state=core.receipt(await core.add(live[i].payload));}catch{/* Inspect the native cart for uncertain writes. */}
            if (state==='unknown') {
              try {if (((await counts()).get(line.id)||0)===after) state='confirmed';}catch{/* Retain the durable unknown. */}
            }
            if (state==='unknown') return answer('unknown','The store could not confirm this add. Check your existing cart.');
            delete data.unresolved[line.id];update(i,{state});writeStarted=false;
            if (state==='rejected') return answer('rejected','The store declined this item. Previously added items remain in your cart.');
            current.set(line.id,after);
          }
          return answer('confirmed','Your selection is in your MMOEXP cart.');
        });
      } catch(error) {
        return answer(writeStarted?'unknown':'unavailable',error.message||'The store could not check this selection.');
      }
    };
  }
  if (typeof module==='object' && module.exports) {module.exports={createStore,readCounts,normalize};return;}
  if (location.origin!==storeOrigin || location.pathname!=='/events/D4-Build-Shop.html') return;
  const load=import('./d4-armory-cart.js?v=3');
  const checkout=createStore({goods:async()=>{await load;return globalThis.ArmoryNativeGoods;},counts:nativeCounts,locks:navigator.locks,
    storage:{getItem:k=>localStorage.getItem(k),setItem:(k,v)=>localStorage.setItem(k,v)}});
  globalThis.ArmoryStore=Object.freeze({checkout});
})();