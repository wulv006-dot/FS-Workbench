(() => {
  'use strict';
  const data=globalThis.SeasonalData,core=globalThis.VaultCore;
  const games=new Map(data.games.map(g=>[g.id,g])),products=new Map(data.products.map(p=>[p.id,p]));
  const money=cents=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
  const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let storageKey='mmoexp-seasonal-vault-real-catalog-v3';
  let state;try{state=JSON.parse(localStorage.getItem(storageKey));}catch{}
  const featuredGames=data.featuredGames; // Operator examples, not measured popularity or inferred personal history.
  if(!core.valid(state,[...products.keys()]))state={version:2,cards:core.draw(data.products,8,[],Math.random,featuredGames),credits:0,round:1,receipts:[],selectedGames:data.games.map(g=>g.id),mode:'product',featuredGames};
  state.featuredGames=featuredGames;
  let theme=new URLSearchParams(location.search).get('theme');if(!Object.hasOwn(data.themes,theme))theme='halloween';
  let filter='all',storeFilter='all',busy=false,finishReveal=null,bag=[];
  const grid=document.querySelector('#products'),dialog=document.querySelector('#event-dialog');
  const status=message=>{document.querySelector('#event-status').textContent=message;};
  function save(){try{localStorage.setItem(storageKey,JSON.stringify(state));}catch{status('This browser cannot save the demo. Keep this page open to preserve your draw.');}}
  const cardFor=id=>state.cards.find(c=>c.id===id);
  const amount=card=>core.price(products.get(card.id).priceCents,card.discount);
  function artMarkup(product) {
    const game=games.get(product.game);
    return `<div class="product-art-wrap"><svg class="product-art" viewBox="${game.frames[product.artIndex].join(' ')}" role="img" aria-label="${escapeHTML(game.label)} ${escapeHTML(product.tier.toLowerCase())} treasure illustration"><svg x="${game.frames[product.artIndex][0]}" y="${game.frames[product.artIndex][1]}" width="${game.frames[product.artIndex][2]}" height="${game.frames[product.artIndex][3]}" viewBox="${game.frames[product.artIndex].join(' ')}" overflow="hidden"><image href="assets/art-${product.game}.webp" width="2172" height="724"/></svg></svg><span class="art-motif" aria-hidden="true">${data.themes[theme].motif}</span></div>`;
  }
  function cardMarkup(card,fixed=false){
    const p=products.get(card.id),g=games.get(p.game);
    if(p.previewOnly)return `<article class="product is-revealed" data-id="${escapeHTML(p.id)}"><div class="product-info"><p class="product-category">${escapeHTML(g.label)} · CATALOG PREVIEW</p><h3>${escapeHTML(p.name)}</h3><p>Product ID ${escapeHTML(p.source.goodsId)} · Model ${escapeHTML(p.source.modelId||'unverified')}</p><p>Platform attribute ${escapeHTML(p.source.aid||'unverified')}</p><p>Specifications, quantity and price require verification. Not eligible for a discount, preview bag or checkout.</p></div></article>`;
    const sealed=!fixed&&!card.revealed;
    const hiddenProduct=sealed&&state.mode==='product',hiddenDiscount=sealed&&!hiddenProduct;
    return `<article class="product ${sealed?'is-sealed':'is-revealed'} ${card.locked?'is-kept':''}" data-id="${p.id}" ${hiddenProduct?'data-mystery="true"':''} ${fixed?'data-fixed="true"':''} style="--game-color:${g.accent}"><div class="card-face" ${hiddenProduct?'inert aria-hidden="true"':''}><div class="product-top"><span class="game-tag"><i class="game-dot"></i>${g.label}</span><span class="tier">${fixed?'EVERYDAY EVENT':'MYSTERY EXCLUSIVE'}</span></div>${artMarkup(p)}<div class="product-info"><p class="product-category">${g.category}</p><h3>${escapeHTML(p.name)}</h3><p class="product-quantity">${escapeHTML(p.amount)}</p><p class="product-source">${escapeHTML(p.source.platform)}<br>SKU ${p.source.goodsId} · ${p.source.quantity}${p.source.unit}</p><div class="offer-area">${hiddenDiscount?`<button class="seal-button" data-reveal="${p.id}" aria-label="Reveal ${g.label} ${escapeHTML(p.name)} discount">Reveal my discount ✦</button><p class="seal-hint">SPECIAL DISCOUNT WAITING</p>`:`<div class="discount-headline">${card.discount}% <small>DEMO OFF</small></div><div class="price-row"><strong><span class="demo-label">SIMULATED </span>${money(amount(card))}</strong><span class="source-price">MMOEXP ${money(p.priceCents)}</span></div><button class="details-button" data-product="${p.id}" aria-label="View ${g.label} ${escapeHTML(p.name)} ${fixed?'fixed':'mystery'} offer" ${fixed?'data-fixed="true"':''}>Choose options & view pack ↗</button>${!fixed?`<button class="keep-button" data-keep="${p.id}" aria-pressed="${card.locked}" aria-label="Keep ${g.label} ${escapeHTML(p.name)}">${card.locked?'◆ Kept for next round':'◇ Keep this offer'}</button>`:''}`}</div></div></div>${hiddenProduct?`<button class="card-back" data-reveal="${p.id}" aria-label="Reveal sealed ${g.label} card ${state.cards.indexOf(card)+1}"><span class="back-game">${g.label}</span><span class="seal-orbit"><span>⚿</span></span><span class="back-title">A LITTLE<br><em>MYSTERY</em></span><span class="back-prompt">TOUCH TO UNSEAL</span><span class="back-number">${String(state.cards.indexOf(card)+1).padStart(2,'0')} / ${String(state.cards.length).padStart(2,'0')}</span></button>`:''}<div class="reveal-rays" aria-hidden="true"></div></article>`;
  }
  function renderProducts(){
    const cards=state.cards.filter(c=>filter==='all'||products.get(c.id).game===filter);
    grid.innerHTML=cards.length?cards.map(c=>cardMarkup(c)).join(''):`<div class="empty-pool"><h3>No ${(games.get(filter)?.label||'products')} in this draw.</h3><p>Find guaranteed offers below, or choose this game in your next pool.</p><a class="button outline" href="#fixed-store">Shop fixed offers ↓</a></div>`;
    document.querySelector('#selection-label').textContent=`YOUR VAULT · ${state.cards.length} CARDS · ROUND ${state.round}`;
    document.querySelector('#reveal-count').textContent=`${state.cards.filter(c=>c.revealed).length} / ${state.cards.length} revealed`;
    document.querySelector('#round-number').textContent=String(state.round).padStart(2,'0');
    document.querySelector('#key-count').textContent=state.credits;
    document.querySelector('#kept-count').textContent=`${state.cards.filter(c=>c.locked).length} kept`;
    document.querySelector('#collection-summary').textContent='Missing your game? Guaranteed fixed offers are just below.';
    document.querySelector('#bag-count').textContent=bag.length;
    window.SeasonalTracking?.render(theme);
  }
  function renderStore(){
    document.querySelector('#store-filters').innerHTML=[{id:'all',label:'All games'},...data.games].map(g=>`<button class="filter" data-store-filter="${g.id}" aria-pressed="${g.id===storeFilter}">${g.label}</button>`).join('');
    const list=storeFilter==='all'?data.products.filter(p=>p.previewOnly||p.displayRole==='fixed'||p.displayRole==='both'||!p.displayRole&&p.artIndex===0):data.products.filter(p=>p.game===storeFilter&&(p.previewOnly||p.displayRole!=='pool'));
    document.querySelector('#fixed-products').innerHTML=list.map(p=>cardMarkup({id:p.id,discount:games.get(p.game).fixedDiscountPercent},true)).join('');
  }
  function renderFilters(){document.querySelector('#game-filters').innerHTML=[{id:'all',label:'My whole draw',short:'✦'},...data.games].map(g=>`<button class="filter" data-filter="${g.id}" aria-pressed="${filter===g.id}"><span class="filter-icon">${g.short}</span>${g.label}</button>`).join('');}
  function setTheme(next){
    theme=Object.hasOwn(data.themes,next)?next:'halloween';const t=data.themes[theme];
    document.documentElement.dataset.theme=theme;document.documentElement.style.setProperty('--accent',t.accent);document.documentElement.style.setProperty('--base',t.base);
    document.querySelector('meta[name=theme-color]').content=t.base;document.querySelector('#theme-select').value=theme;
    document.querySelector('#hero-image').src=`assets/hero-${theme}.webp`;document.querySelector('#hero-image').alt=t.alt;document.querySelector('#hero-mobile-source').srcset=`assets/hero-${theme}.webp`;
    for(const [id,text] of Object.entries({'edition':t.edition,'hero-kicker':t.kicker,'hero-caption':`THE ${t.label.toUpperCase()} COLLECTION`,'hero-number':`${t.number} / 04`,'campaign-date':t.date})){
      const element=document.getElementById(id);
      if(id==='campaign-date'&&element.dataset.publishedSchedule==='true')continue;
      element.textContent=text;
    }
    document.querySelector('#hero-title').innerHTML=`${t.title}<br><em>${t.word}</em>`;document.querySelector('#hero-copy').innerHTML=t.copy;
    document.querySelector('#collection-title').innerHTML='Your mystery selection<span>.</span>';
    if(document.querySelector('#campaign-date').dataset.publishedSchedule!=='true')document.title=`${t.label} Seasonal Vault | MMOEXP`;
    const url=new URL(location.href);url.searchParams.set('theme',theme);history.replaceState(null,'',url);renderProducts();renderStore();window.SeasonalTracking?.render(theme);
  }
  function showDialog(title,content){document.querySelector('#dialog-title').textContent=title;document.querySelector('#dialog-content').innerHTML=content;if(!dialog.open)dialog.showModal();}
  function reveal(ids){
    if(busy)return;const pending=ids.filter(id=>cardFor(id)&&!cardFor(id).revealed);if(!pending.length){status('These cards are already revealed.');return;}
    busy=true;document.querySelector('#theme-select').disabled=true;
    document.querySelector('#reveal-progress').hidden=false;grid.setAttribute('aria-busy','true');
    const reduced=document.querySelector('#skip-animation').checked||matchMedia('(prefers-reduced-motion: reduce)').matches;
    let timer;finishReveal=()=>{if(!busy)return;clearTimeout(timer);pending.forEach(id=>cardFor(id).revealed=true);window.SeasonalTracking?.selection('reveal-complete',pending);save();busy=false;finishReveal=null;document.querySelector('#theme-select').disabled=false;document.querySelector('#reveal-progress').hidden=true;grid.removeAttribute('aria-busy');renderProducts();pending.forEach(id=>grid.querySelector(`[data-id="${id}"]`)?.classList.add('just-revealed'));grid.querySelector(`[data-product="${pending[0]}"]`)?.focus({preventScroll:true});status(`${pending.length} special offers revealed. Demo discounts only.`);};
    pending.forEach((id,index)=>{const el=grid.querySelector(`[data-id="${id}"]`);if(el){el.style.setProperty('--reveal-delay',`${Math.min(index,7)*100}ms`);el.classList.add('is-opening');el.querySelectorAll('button').forEach(b=>b.disabled=true);}});
    if(reduced)finishReveal();else timer=setTimeout(finishReveal,1800+Math.min(pending.length-1,7)*100);
  }
  function showProduct(id,fixed=false){
    const p=products.get(id);if(!p||p.previewOnly)return;const g=games.get(p.game),card=fixed?{id,discount:g.fixedDiscountPercent}:cardFor(id);if(!card||(!fixed&&!card.revealed))return;
    const options=[p.source.platform];
    showDialog(p.name,`${artMarkup(p)}<p class="eyebrow">${g.label} · ${fixed?'FIXED EVENT OFFER':'YOUR MYSTERY OFFER'}</p><p>${escapeHTML(p.amount)} · <strong>${card.discount}% OFF · DEMO</strong></p><div class="dialog-price">${money(amount(card))} <small>SIMULATED EVENT PRICE · USD</small></div><label class="option-label">Platform / server <select id="pack-platform">${options.map(o=>`<option>${o}</option>`).join('')}</select></label><p class="dialog-note">Real product mapping; event discounts remain a simulation. This snapshot covers only the platform / server shown. Verify the current price and availability on MMOEXP.</p><dl class="source-details"><dt>Original product</dt><dd>${g.label} · ${escapeHTML(p.source.originalTitle)}</dd><dt>MMOEXP base price</dt><dd>${money(p.priceCents)} USD · ${escapeHTML(p.amount)}</dd><dt>SKU / package</dt><dd>SKU ${p.source.goodsId}<br>Order quantity ${p.source.quantity}${p.source.unit||" bundle"}${p.source.bonus?` + ${p.source.bonus}${p.source.unit} free`:""}</dd><dt>Price checked</dt><dd>${escapeHTML(new Date(p.source.capturedAt).toLocaleString("en-GB",{timeZone:"Asia/Shanghai",hour12:false}))} UTC+8</dd></dl><button class="button gold" data-bag-add="${id}" ${fixed?'data-fixed="true"':''}>Add to preview bag</button><a class="text-button store-link" href="${p.source.url}" target="_blank" rel="noopener">Verify product on MMOEXP ↗</a>`);
  }
  function showCart(){
    window.SeasonalTracking?.review(bag.map(line=>line.id));
    showDialog('Your preview bag',`${bag.length?bag.map((line,i)=>`<div class="bag-line"><div><strong>${escapeHTML(products.get(line.id).name)}</strong><p>${games.get(products.get(line.id).game).label} · ${escapeHTML(line.platform)}<br>${escapeHTML(products.get(line.id).amount)} · SKU ${products.get(line.id).source.goodsId}<br>MMOEXP snapshot ${money(products.get(line.id).priceCents)}<br>${line.fixed?'Fixed event':'Mystery round '+line.round} · ${line.discount}% OFF · DEMO ${money(amount(line))}</p></div><button class="text-button" data-remove="${i}" aria-label="Remove ${escapeHTML(products.get(line.id).name)}">Remove</button></div>`).join(''):'<p>Your preview bag is empty. Reveal a card or choose a fixed offer.</p>'}<p class="dialog-note">Preview only — these items have not been added to your MMOEXP cart. A real event must use the original cart with server-confirmed promotion eligibility.</p><div class="runtime-checkout"><button class="button outline" data-action="store-quote" ${bag.length?'':'disabled'}>Check selection with store</button><button class="text-button" data-action="store-prepare" hidden>Run test checkout (no real cart)</button><button class="text-button" data-action="store-lookup">Check original operation status</button><p id="store-status" role="status" aria-live="polite">Server verification is required. DEMO prices and rewards do not apply to checkout.</p></div><a class="button gold" href="https://www.mmoexp.com/Cart.html" target="_blank" rel="noopener">Open my existing MMOEXP cart ↗</a>`);
  }
  function showPool(){
    showDialog('Your games. Your kind of mystery.',`<p>Choose the games you want to draw from. The fixed store follows the published page selection.</p><fieldset class="pool-options"><legend>Games in your next draw</legend>${data.games.map(g=>`<label><input type="checkbox" name="pool-game" value="${g.id}" ${state.selectedGames.includes(g.id)?'checked':''}>${g.label} <small>${data.products.filter(p=>p.game===g.id&&!p.previewOnly&&!['fixed','preview'].includes(p.displayRole)).length} draw-eligible packs</small></label>`).join('')}</fieldset><fieldset class="pool-mode"><legend>What would you like to reveal?</legend><label><input type="radio" name="reveal-mode" value="product" ${state.mode==='product'?'checked':''}> Mystery product + discount</label><label><input type="radio" name="reveal-mode" value="discount" ${state.mode==='discount'?'checked':''}> Show products; reveal discounts</label></fieldset><p class="dialog-note">Demo pool: ${data.products.length} configured products. Up to 8 unique cards per draw. Default featured games: ${featuredGames.map(id=>games.get(id).label).join(', ')}, one slot each when selected and space permits; the remaining slots come from your chosen pool. No browsing history is used. Each discount tier (10%, 15%, 20%, 25%) is equally likely in this demo; real tiers and odds are not approved.</p><p>Before your first reveal, you can change the pool freely. After revealing a card, pool changes apply on the next refresh and use 1 key. Kept offers stay unchanged; unlock cards from removed games first.</p><button class="button gold" data-action="save-pool">Save next-draw preferences</button><details class="pool-catalog"><summary>View all ${data.products.length} configured products</summary>${data.games.map(g=>`<h3>${g.label}</h3><p>${data.products.filter(p=>p.game===g.id).map(p=>escapeHTML(p.name)).join(' · ')}</p>`).join('')}</details><p id="pool-error" role="alert"></p>`);
  }
  function showRefresh(){
    if(!state.credits){showDialog('Your next draw starts with a friend.',`<p>You have no refresh keys yet. A completed eligible registration earns one. Your fixed offers remain available.</p><button class="button gold" data-action="invite">Invite a friend</button>`);return;}
    if(state.cards.every(c=>c.locked)){showDialog('Keep a little room for surprise.', '<p>All cards are kept. Unlock at least one before refreshing.</p>');return;}
    showDialog('Open a new round?',`<p><strong>${state.cards.filter(c=>c.locked).length} kept offers stay.</strong> All other mystery offers expire, including unkept items in your preview bag. Fixed offers stay available.</p><p>Costs 1 key. ${state.credits} available. A refresh may produce the same products or a lower discount; improvement is not guaranteed.</p><button class="button gold" data-action="confirm-refresh">Use 1 key & refresh</button><button class="text-button" data-action="close">Keep this round</button><p id="refresh-error" role="alert"></p>`);
  }
  function showInvite(){
    showDialog('A little mystery is better shared.',`<p>Invite a new friend to join MMOEXP. After their eligible registration is confirmed, receive a key for another draw.</p><div class="invite-meter"><b>${state.receipts.length} / 3</b><span>DEMO eligible registrations</span><b>${state.credits}</b><span>refresh keys available</span></div><label class="option-label">Example invitation code<input readonly value="DEMO-VAULT-FRIEND" aria-label="Example invitation code"></label><p class="dialog-note">This site is a private design preview. The demo code does not track registrations or award real rewards. Share text can be copied; the live referral link will be issued by MMOEXP after sign-in.</p><button class="button gold" data-action="copy-invite">Copy invitation text</button><button class="text-button" data-action="account">Sign in / create an MMOEXP account ↗</button><p id="share-status" role="status"></p><details class="simulation"><summary>预览工具：模拟好友完成有效注册</summary><p>仅用于体验流程，不是实际注册或奖励。每个示例注册回执仅计一次。</p>${[1,2,3].map(n=>`<button class="button outline" data-demo-receipt="DEMO-${n}" ${state.receipts.includes('DEMO-'+n)?'disabled':''}>模拟好友 ${n} 注册${state.receipts.includes('DEMO-'+n)?' · 已计入':''}</button>`).join('')}</details>`);
  }
  function showAccount(){showDialog('Your MMOEXP account',`<p>Use your existing MMOEXP account to keep event offers and receive verified invitation rewards. Shopping on MMOEXP remains available to guests.</p><a class="button gold" href="https://www.mmoexp.com/Ucenter.html" target="_blank" rel="noopener">Continue on MMOEXP ↗</a><p class="dialog-note">This private preview does not share the store's sign-in session. On the integrated store page, this button uses the existing MMOEXP sign-in / registration panel. Coming back here does not confirm a login or registration.</p>`);}
  function showRules(){showDialog('Inside the vault',`<ul><li>Product IDs, specifications and USD base prices come from MMOEXP public-page snapshots checked on 24 October 2026. Event discounts, dates and referral rewards remain design simulations. Base prices are not refreshed automatically; the store confirms current availability and checkout totals.</li><li>Fixed offers: all six games, each with its configured demo discount. Mystery offers: up to 8 distinct products, demo discount tiers 10%, 15%, 20%, 25%, equal likelihood per tier.</li><li>Featured game slots are filled from the selected pool before remaining slots. Products have equal selection probability within each applicable draw step, not across the whole pool.</li><li>Keep revealed offers before refreshing. Unkept offers expire. A new draw can repeat a product and may offer less discount.</li><li>Concept: one eligible new registration earns one refresh key, up to three. Shares, clicks and returning members alone do not earn keys.</li><li>Fixed and mystery discounts are alternatives, not stacked. Existing coupon / points / VIP terms must be confirmed by the original checkout.</li><li>Demo progress stays in this browser. Actual identity, draw results, referral qualification and checkout must be confirmed by MMOEXP servers.</li></ul>`);}
  document.querySelector('#theme-select').addEventListener('change',e=>setTheme(e.target.value));
  document.addEventListener('click',async event=>{
    const b=event.target.closest('button');if(!b)return;const action=b.dataset.action;
    if(busy){if(action==='skip-reveal')finishReveal?.();return;}
    if(b.dataset.filter){filter=b.dataset.filter;renderFilters();renderProducts();document.querySelector(`[data-filter="${filter}"]`).focus({preventScroll:true});}
    else if(b.dataset.storeFilter){storeFilter=b.dataset.storeFilter;renderStore();document.querySelector(`[data-store-filter="${storeFilter}"]`).focus({preventScroll:true});}
    else if(b.dataset.reveal)reveal([b.dataset.reveal]);
    else if(b.dataset.product)showProduct(b.dataset.product,b.dataset.fixed==='true');
    else if(b.dataset.keep){const c=cardFor(b.dataset.keep);if(c?.revealed){c.locked=!c.locked;save();renderProducts();grid.querySelector(`[data-keep="${c.id}"]`)?.focus({preventScroll:true});}}
    else if(b.dataset.bagAdd){const fixed=b.dataset.fixed==='true',c=fixed?{id:b.dataset.bagAdd,discount:games.get(products.get(b.dataset.bagAdd).game).fixedDiscountPercent}:cardFor(b.dataset.bagAdd);const platform=document.querySelector('#pack-platform').value; if(c&&!bag.some(l=>l.id===c.id&&l.fixed===fixed&&l.platform===platform))bag.push({...c,fixed,platform,round:state.round});window.SeasonalTracking?.selection('preview-bag-change',bag.map(l=>l.id));renderProducts();showCart();}
    else if(b.dataset.remove){bag.splice(Number(b.dataset.remove),1);window.SeasonalTracking?.selection('preview-bag-change',bag.map(l=>l.id));renderProducts();showCart();}
    else if(b.dataset.demoReceipt){state=core.award(state,b.dataset.demoReceipt);save();renderProducts();showInvite();}
    else if(action==='reveal-all'){filter='all';renderFilters();renderProducts();document.querySelector('#collection').scrollIntoView({behavior:'instant'});reveal(state.cards.map(c=>c.id));}
    else if(action==='pool'||b.id==='show-all')showPool();
    else if(action==='save-pool'){
      const selected=[...dialog.querySelectorAll('[name=pool-game]:checked')].map(i=>i.value);
      if(!data.products.some(p=>!p.previewOnly&&!['fixed','preview'].includes(p.displayRole)&&selected.includes(p.game))){status('No verified demo products in this selection. Catalog previews cannot enter a discount draw.');return;}
      if(!selected.length){document.querySelector('#pool-error').textContent='Choose at least one game.';return;}
      if(state.cards.some(c=>c.locked&&!selected.includes(products.get(c.id).game))){document.querySelector('#pool-error').textContent='Unlock kept cards from games you are removing first.';return;}
      state.selectedGames=selected;state.mode=dialog.querySelector('[name=reveal-mode]:checked').value;const firstDraw=state.round===1&&!state.cards.some(c=>c.revealed);if(firstDraw)state.cards=core.draw(data.products.filter(p=>!p.previewOnly&&!['fixed','preview'].includes(p.displayRole)&&selected.includes(p.game)),8,[],Math.random,featuredGames);save();dialog.close();filter='all';renderFilters();renderProducts();status(firstDraw?'Your first draw now uses your selected games.':'Pool preferences saved. They apply on your next refresh.');
    }
    else if(action==='refresh')showRefresh();
    else if(action==='confirm-refresh'){
      try{const keep=new Set(state.cards.filter(c=>c.locked).map(c=>c.id));state=core.refresh(state,data.products.filter(p=>!p.previewOnly&&!['fixed','preview'].includes(p.displayRole)&&state.selectedGames.includes(p.game)));bag=bag.filter(l=>l.fixed||keep.has(l.id));window.SeasonalTracking?.selection('refresh-complete',state.cards.map(c=>c.id));save();dialog.close();filter='all';renderFilters();renderProducts();document.querySelector('#collection').scrollIntoView({behavior:'instant'});status('New round ready. Kept offers preserved; other old mystery offers expired.');}
      catch(error){document.querySelector('#refresh-error').textContent=error.message;}
    }
    else if(action==='invite'||action==='invite-status')showInvite();
    else if(action==='copy-invite'){
      const text=`Discover the MMOEXP ${data.themes[theme].label} Seasonal Vault. Invitation concept: join to unlock another mystery draw. Demo code DEMO-VAULT-FRIEND — design preview only; no active reward or public referral link.`;
      try{await navigator.clipboard.writeText(text);document.querySelector('#share-status').textContent='Invitation text copied. No registration or key was awarded.';}
      catch{document.querySelector('#share-status').innerHTML=`<label>Copy manually<textarea readonly>${escapeHTML(text)}</textarea></label>`;}
    }
    else if(action==='store-quote'||action==='store-lookup'||action==='store-prepare'){b.disabled=true;await window.SeasonalCommerce?.run(action==='store-lookup'?'lookup':action==='store-prepare'?'prepare':'quote',bag,message=>{const output=document.querySelector('#store-status');if(output)output.textContent=message;});b.disabled=false;const prepare=document.querySelector('[data-action=store-prepare]');if(prepare)prepare.hidden=!window.SeasonalCommerce?.canPrepare();}
    else if(action==='account')showAccount();else if(action==='cart')showCart();else if(action==='rules')showRules();else if(action==='close')dialog.close();
  });
  dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
  const acceptedProducts=[...data.products];
  let appliedRelease=null;
  const applyPublishedCatalog=event=>{
    const config=event.detail,page=config?.pages?.find(p=>p.page_id==='seasonal-vault');
    if(!page||!Array.isArray(page.product_keys)||!Array.isArray(config.products)||config.release_id===appliedRelease)return;
    const gameIds={'1327':'fc','1329':'nba','1309':'madden','456':'diablo','552':'poe','891':'aion'};
    const next=page.product_keys.flatMap(key=>{
      const original=acceptedProducts.find(p=>'seasonal-'+p.id===key);if(original)return [{...original,displayRole:page.product_roles?.[key]}];
      const p=config.products.find(p=>p.key===key),game=gameIds[p?.product_ref?.game_id];
      if(!p?.preview_only||p.available!==false||!game)return [];
      return [{id:key,game,name:p.title,previewOnly:true,displayRole:page.product_roles?.[key]||'preview',artIndex:0,source:{goodsId:p.product_ref.goods_id,modelId:p.product_ref.model_id,aid:p.platform?.attribute_id}}];
    });
    finishReveal?.();appliedRelease=config.release_id;data.products=next;products.clear();next.forEach(p=>products.set(p.id,p));
    // Scope changed catalog state separately: the prior local draw and receipts remain recoverable.
    storageKey='mmoexp-seasonal-vault-real-catalog-v3:'+config.release_id;
    let saved;try{saved=JSON.parse(localStorage.getItem(storageKey));}catch{}
    state=core.valid(saved,[...products.keys()])?saved:{version:2,cards:next.some(p=>!p.previewOnly&&!['fixed','preview'].includes(p.displayRole))?core.draw(next.filter(p=>!p.previewOnly&&!['fixed','preview'].includes(p.displayRole)),8,[],Math.random,featuredGames):[],credits:0,round:1,receipts:[],selectedGames:data.games.map(g=>g.id),mode:'product',featuredGames};
    bag=[];filter='all';storeFilter='all';dialog.close();renderFilters();renderProducts();renderStore();
    status('Published product selection loaded. New unverified products are catalog previews only; no rewards or purchases were enabled.');
  };
  window.addEventListener('seasonal-published-catalog',applyPublishedCatalog);
  window.addEventListener('seasonal-published-theme',event=>setTheme(event.detail));
  renderFilters();setTheme(theme);save();
  if(window.SeasonalPublishedConfig)applyPublishedCatalog({detail:window.SeasonalPublishedConfig});
})();
