/* MMOEXP D4 Build Shop checkout. All native cart actions run on the storefront. */
(() => {
  'use strict';
  const realm = '15943';
  const source = 'https://mmoexp-d4-build-armory-nov16.workspace-584227.chatgpt.site';
  const shop = 'https://www.mmoexp.com';
  const idPattern = /^[1-9]\d{0,15}$/;
  const usd = (value, unit = false) => new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: unit ? 6 : 2
  }).format(value);
  function checkList(list) {
    if (list?.realm !== realm || !Number.isFinite(Date.parse(list.expiresAt)) ||
        Date.parse(list.expiresAt) <= Date.now()) throw Error('This selection has expired. Return to the Build Shop to refresh it.');
    if (!Array.isArray(list.lines) || !list.lines.length || list.lines.length > 120) throw Error('The selection is empty or invalid.');
    const seen = new Set();
    for (const line of list.lines) {
      if (!['gear','gem','rune'].includes(line.kind) || !idPattern.test(line.id) || seen.has(line.id) ||
          (line.number != null && !idPattern.test(line.number)) || !idPattern.test(line.categoryId) ||
          typeof line.name !== 'string' || !line.name.trim() || line.name.length > 512 ||
          !Number.isInteger(line.quantity) || line.quantity < 1 || line.quantity > 9999 ||
          (line.kind === 'gear' && line.quantity !== 1) || !(Number(line.price) > 0)) throw Error('A product in this selection is invalid.');
      seen.add(line.id);
    }
    return list;
  }
  function nativeOffer(line, row) {
    if (!row || String(row.id) !== line.id || String(row.gid) !== '456' || String(row.aid) !== realm ||
        String(row.cid) !== String(line.cid || line.categoryId) || Number(row.status) !== 1 ||
        ![0,1].includes(Number(row.auto_off))) return null;
    if (line.number && String(row.mid) !== String(line.number)) return null;
    if (line.kind === 'gear' && line.number && !String(row.title).trim().endsWith('#' + line.number)) return null;
    if (row.has_sku === true || Number(row.has_sku) === 1 || Object.keys(row.saleprop || {}).length) return null;
    const group = Number(row.num), minimum = Number(row.min_qty);
    if (!Number.isSafeInteger(minimum) || minimum < 1 || line.quantity < minimum ||
        !Number.isSafeInteger(group) || group < 1 ||
        (Number(row.max_qty) > 0 && line.quantity > Number(row.max_qty)) ||
        (Number(row.auto_off) === 1 && !(Number(row.total) >= group * line.quantity))) return null;
    const price = Number(row.price_discount ?? row.price);
    if (!Number.isFinite(price) || price <= 0) return null;
    return {name:String(row.title), price, quantity:line.quantity,
      payload:{category:'new_items', id:line.id, group:String(group), num:String(line.quantity), attr:'', aid:realm}};
  }
  function receipt(data) {
    const add = data?.data?.cart?.add || data?.cart?.add;
    if (data?.code === 0 || data?.code === '0' || data?.status === false || add?.status === false || add?.status === 0) return 'rejected';
    if (Number(data?.code) === 1 || (add && (add.details || add.cart || add.total != null))) return 'confirmed';
    return 'unknown';
  }
  if (typeof module === 'object' && module.exports) {module.exports = {checkList,nativeOffer,receipt};return;}
  const $ = id => document.getElementById(id);
  const message = text => { $('status').textContent = text; };
  const button = $('confirm');
  const token = new URLSearchParams(location.hash.slice(1)).get('list');
  const key = 'mmoexp:d4-build-cart:' + token;
  let list, offers = [], journal = {}, busy = false;
  const pending = () => list.lines.filter(line => journal[line.id] !== 'confirmed');
  const uncertain = () => Object.values(journal).includes('unknown');
  const post = async (path, data) => {
    const response = await fetch(path, {method:'POST',credentials:'same-origin',cache:'no-store',redirect:'error',
      signal:AbortSignal.timeout(20000),headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body:new URLSearchParams(data)});
    if (!response.ok) throw Error('The MMOEXP store could not be reached.');
    return response.json();
  };
  async function lookup(line) {
    const keyword = line.kind === 'gear' && line.number ? line.number : line.name;
    for (let page=1;page<=10;page++) {
      const data = await post('/ajax/goods',{site_id:'266',Game_id:'456',page:String(page),top_cid:'2',category_id:String(line.categoryId),
        level:'1',get_about_multi_by_cid:'1',perpage:'28',aid:realm,keyword});
      const index = data?.goods?.index;
      if (!Array.isArray(index?.list)) throw Error('The store did not return a product list.');
      const matches = index.list.filter(row => String(row.id) === line.id);
      if (matches.length) return matches.length === 1 ? nativeOffer(line,matches[0]) : null;
      if (page * (Number(index.perpage) || 28) >= Number(index.total) || !index.list.length) break;
    }
    return null;
  }
  async function refresh() {
    const fresh = [...offers];
    // Limit concurrent searches even for a full loadout.
    let next = 0;
    async function worker() {
      while (next < list.lines.length) {
        const i = next++;
        if (journal[list.lines[i].id] !== 'confirmed') fresh[i] = await lookup(list.lines[i]);
      }
    }
    await Promise.all(Array.from({length:Math.min(3,list.lines.length)},worker));
    return fresh;
  }
  function readJournal() {
    const data = JSON.parse(localStorage.getItem(key) || '{}');
    if (!data || typeof data !== 'object' || Array.isArray(data) ||
        Object.entries(data).some(([id,status])=>!list.lines.some(line=>line.id===id) || !['confirmed','unknown','rejected'].includes(status))) {
      throw Error('Your previous cart update could not be verified. Check your MMOEXP cart.');
    }
    return data;
  }
  function record(id, state) {
    journal = {...journal,[id]:state};
    const text = JSON.stringify(journal);
    localStorage.setItem(key,text);
    if (localStorage.getItem(key) !== text) throw Error('Your cart progress could not be saved. Check your MMOEXP cart.');
  }
  function render() {
    const fragment = document.createDocumentFragment();
    let total = 0; let available = true;
    for (const [i,line] of list.lines.entries()) {
      const offer=offers[i], done=journal[line.id]==='confirmed', unknown=journal[line.id]==='unknown';
      const li=document.createElement('li'), name=document.createElement('strong'), amount=document.createElement('span'), detail=document.createElement('small');
      name.textContent=offer?.name || line.name;
      amount.textContent=offer?usd(offer.price*line.quantity):'';
      const text = ['Quantity '+line.quantity];
      if (line.number) text.push('#'+line.number);
      if (done) text.push('Added to your cart');
      else if (unknown) text.push('Unconfirmed — check your cart');
      else if (!offer) { text.push('Currently unavailable');available=false; }
      else {
        total+=offer.price*line.quantity;
        text.push(usd(offer.price,true)+' each');
        if (Math.abs(offer.price-Number(line.price))>0.0000001) text.push('Build Shop estimate '+usd(line.price,true)+' each');
        if (journal[line.id]==='rejected') text.push('Store rejected the last attempt');
      }
      detail.textContent=text.join(' · ');li.append(name,amount,detail);fragment.append(li);
    }
    $('lines').replaceChildren(fragment);
    $('subtotal').textContent = available && pending().length && !uncertain() ? 'Items to add · '+usd(total) : '';
    button.hidden=!pending().length || uncertain() || !available;
    button.disabled=busy||button.hidden;
  }
  async function add() {
    if (busy) return;
    busy=true;button.disabled=true;
    try {
      await navigator.locks.request('mmoexp:d4-build-cart',{ifAvailable:true},async lock=>{
        if (!lock) throw Error('A cart update is in progress in another tab. Check your cart before continuing.');
        journal=readJournal();checkList(list);
        if (uncertain() || !pending().length) throw Error('Check your MMOEXP cart for this selection.');
        message('Checking current products and prices…');
        const updated=await refresh(), changed=JSON.stringify(offers)!==JSON.stringify(updated);
        offers=updated;
        if (changed || pending().some(line=>!offers[list.lines.indexOf(line)])) {
          message('The store updated this selection. Review each product and its current price.');return;
        }
        const cart = await fetch('/Cart.html',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(20000)});
        if (!cart.ok) throw Error('Your current cart could not be opened. Try again after checking the cart.');
        const template=document.createElement('template');template.innerHTML=await cart.text();
        if (!template.content.querySelector('li[data-cart-category],.no-c-box .no-title')) throw Error('Your store cart could not be verified. Open your cart and try again.');
        for (const [i,line] of list.lines.entries()) {
          if (journal[line.id]==='confirmed') continue;
          checkList(list);record(line.id,'unknown');
          message('Adding '+line.name+'…');
          let state='unknown';
          try {state=receipt(await post('/Cart/add.html',offers[i].payload));} catch { /* Reconcile an unknown write in the cart. */ }
          record(line.id,state);
          if (state!=='confirmed') {message(state==='unknown'?'The store could not confirm this item. Open your cart to check it before starting a new selection.':'The store declined this item. Check your cart and availability before retrying.');return;}
        }
        message('Your selected items have been added. Opening your cart…');location.assign('/Cart.html');
      });
    } catch(error) {message(error.message || 'Check your MMOEXP cart before continuing.');}
    finally {busy=false;if(list)render();}
  }
  async function start() {
    if (location.origin!==shop || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(token||'')) throw Error('Open a selection from the D4 Build Shop to continue.');
    const response=await fetch(source+'/api/loadouts/'+token,{credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer',signal:AbortSignal.timeout(20000)});
    if(!response.ok) throw Error(response.status===404||response.status===410?'This selection has expired. Return to the Build Shop for a fresh list.':'The Build Shop selection could not be loaded. Try again.');
    list=checkList(await response.json());journal=readJournal();
    if (!navigator.locks?.request) throw Error('Open this confirmation in a current browser to add your selection.');
    if (uncertain() || !pending().length) {
      render();message(uncertain()?'A previous cart update is unconfirmed. Open your cart to check it.':'This selection has already been added. Open your cart to review it.');return;
    }
    message('Checking live prices and availability…');offers=await refresh();render();
    message(button.hidden?'One or more products are unavailable. Return to the Build Shop to update your selection.':'Review the current items and prices before adding them to your existing cart.');
    button.addEventListener('click',add);
  }
  start().catch(error=>{message(error.message || 'The store could not load this selection.');button.hidden=true;});
})();