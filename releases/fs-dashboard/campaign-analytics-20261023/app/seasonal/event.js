(function(root){
  'use strict';
  const IDS=['fc','aion','diablo','maplestory'],LABELS={fc:'FC27',aion:'Aion2',diablo:'Diablo IV',maplestory:'MapleStory'},TIERS=[8,15,10];
  const english=(value,fallback)=>typeof value==='string'&&value.trim()&&!/\p{Script=Han}/u.test(value)?value:fallback;
  // Player titles arrive as "Name/89/LB++/Gold Non Rare". Show the name as the
  // headline and the attributes as a quiet second line instead of a ragged wrap.
  // The card already sits inside that game's own section, so the game name is not
  // repeated on the face. Keeping it out also keeps the product name on one line.
  function faceContent({title,attrs='',off,image,qty=''}){
    // The corner discount is a gold badge drawing now: one file per tier, so the
    // face keeps the artwork look instead of a CSS pill.
    const badge=off===null||off===undefined?'':'<span class="offer-badge"><img src="assets/badge-'+off+'.webp" alt="'+off+'% OFF" loading="lazy"></span>';
    const art=image?'<span class="product-art has-image"><img src="'+esc(image)+'" alt="" loading="lazy"></span>':'<span class="product-art is-empty" aria-hidden="true">✦</span>';
    return badge+art+'<strong>'+esc(qty+title)+'</strong>'+(attrs?'<span class="card-attrs">'+esc(attrs)+'</span>':'');
  }
  function titleParts(text){
    const raw=String(text||'').trim();
    const parts=raw.split('/').map(part=>part.trim()).filter(Boolean);
    if(parts.length<2)return {main:raw,attrs:''};
    return {main:parts[0],attrs:parts.slice(1).join(' · ')};
  }
  // One shared drawing per game and product type. The feed only publishes shop
  // photos for FC players, and those photos sit at the wrong relative path for
  // this page, so cards used to come up empty. A game-and-type drawing keeps
  // every card consistent regardless of which model the draw picked.
  const CATEGORY_ART={
    fc:{coins:'assets/product-fc-coins.webp',pack:'assets/product-fc-set.webp',player:'assets/product-fc-set.webp'},
    aion:{coins:'assets/product-aion-coins.webp'},
    diablo:{coins:'assets/product-diablo-coins.webp',item:'assets/product-diablo-item.webp'},
    maplestory:{coins:'assets/product-maplestory-coins.webp',item:'assets/product-maplestory-item.webp'}
  };
  const PACK_HINT=/\b(pack|packs|bundle|bundles|potm|evo|upgrade|stash|xi|cornucopia|mayhem|supernova|scream)\b/i;
  function artCategory(gameId,text){
    const title=String(text||'').trim();
    // MapleStory sells two things in this event: Mesos and gear. Only the
    // currency title gets the coin drawing, everything else is an item.
    if(gameId==='maplestory')return /\bmesos?\b/i.test(title)?'coins':'item';
    // Diablo IV sells gold and gear side by side: only the currency title gets the
  // coin drawing, the named items get the relic drawing.
  if(gameId==='diablo')return /\bgold\b/i.test(title)?'coins':'item';
  if(gameId!=='fc')return 'coins';
    if(/\bcoins?\b/i.test(title))return 'coins';
    // FC player titles lead with a name, packs and SBC bundles carry a product
    // word, so the word decides which drawing the face gets.
    return PACK_HINT.test(title)?'pack':'player';
  }
  function categoryArt(gameId,text,fallback){
    const table=CATEGORY_ART[gameId];
    if(!table)return fallback||null;
    return table[artCategory(gameId,text)]||table.coins||fallback||null;
  }
  const identifier=value=>typeof value==='string'&&value.trim()&&!/[\x00-\x20]/.test(value)?value:null;
  // The event ends and the daily picks reset at midnight US Eastern, so the page
  // and the draw agree on which day it is.
  const NY_ZONE='America/New_York';
  // The US Eastern calendar day decides when cards close again. Falls back to
  // UTC if the runtime has no timezone data.
  function nyDay(now=Date.now()){
    try{return new Intl.DateTimeFormat('en-CA',{timeZone:NY_ZONE,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(now));}
    catch{return new Date(now).toISOString().slice(0,10);}
  }
  function nyOffset(ts){
    const parts=new Intl.DateTimeFormat('en-US',{timeZone:NY_ZONE,hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).formatToParts(new Date(ts));
    const p={};for(const x of parts)p[x.type]=x.value;
    return Date.UTC(+p.year,+p.month-1,+p.day,(+p.hour)%24,+p.minute,+p.second)-Math.floor(ts/1000)*1000;
  }
  function nextNyMidnight(ts){
    const offset=nyOffset(ts),local=new Date(ts+offset);
    return Date.UTC(local.getUTCFullYear(),local.getUTCMonth(),local.getUTCDate()+1,0,0,0,0)-offset;
  }
  // A small clock widget instead of a sentence: segmented tiles make the moment
  // read as an upcoming drop rather than as body copy.
  function clockWidget(ms,label){
    if(!Number.isFinite(ms)||ms<=0)return '';
    const total=Math.floor(ms/1000),d=Math.floor(total/86400),h=Math.floor(total%86400/3600),m=Math.floor(total%3600/60),s=total%60;
    const pad=n=>String(n).padStart(2,'0');
    const seg=(value,unit)=>'<span class="countdown-seg"><b>'+pad(value)+'</b><small>'+unit+'</small></span>';
    const sep='<span class="countdown-sep" aria-hidden="true">:</span>';
    return '<span class="countdown" role="timer"><span class="countdown-label">'+label+'</span>'
      +(d?seg(d,'D')+sep:'')+seg(h,'H')+sep+seg(m,'M')+sep+seg(s,'S')+'</span>';
  }
  function project(config){
    const source=config?.halloween?.schema_version===1&&String(config.halloween.site_id)==='266'?config.halloween:{};
    const rows=Array.isArray(source.games)?source.games:[];
    const probabilities=Array.isArray(source.probabilities)&&source.probabilities.length===3&&new Set(source.probabilities.map(p=>p.off_percent)).size===3&&source.probabilities.every(p=>TIERS.includes(p.off_percent)&&Number.isInteger(p.weight)&&p.weight>=0&&p.weight<=10000)&&source.probabilities.reduce((n,p)=>n+p.weight,0)===10000?source.probabilities:null;
    const starts=Date.parse(source.starts_at),ends=Date.parse(source.ends_at),windowReady=Number.isFinite(starts)&&Number.isFinite(ends)&&ends>starts;
    return {status:source.status==='configured'?'configured':'unconfigured',probabilities,binding:source.tier_product_binding==='independent'?'independent':null,starts_at:windowReady?source.starts_at:null,ends_at:windowReady?source.ends_at:null,
      games:IDS.map((id,i)=>{const row=rows.find(g=>g?.id===id)||{},art=root.SeasonalHalloweenData?.games?.find(g=>g.id===id);return {id,label:LABELS[id],asset:art?.asset||'assets/game-'+(i+1)+'.png',...(art?.logo?{logo:art.logo}:{}),admin_game_id:identifier(Number.isSafeInteger(row.admin_game_id)&&row.admin_game_id>0?String(row.admin_game_id):row.admin_game_id),fixed_model:identifier(row.fixed_model),fixed_off_percent:TIERS.includes(row.fixed_off_percent)?row.fixed_off_percent:null,random_source:['category_dynamic','category_snapshot','quantity_tiers'].includes(row.random_source?.mode)?row.random_source.mode:'models',random_models:Array.isArray(row.random_models)?row.random_models.map(identifier).filter(Boolean):[],random_count:2,fixed_quantity:id==='fc'?{value:'1000',unit:'K',label:'1000K Coins',conversion_verified:false}:row.fixed_quantity?{...row.fixed_quantity,label:row.fixed_quantity.value+' '+row.fixed_quantity.unit+' '+(id==='aion'?'Kinah':'Gold')}:null};})};
  }
  function resolveModel(config,game,model=game.fixed_model){
    if(!model||!game.admin_game_id)return [];
    return (Array.isArray(config?.products)?config.products:[]).filter(p=>String(p.product_ref?.site_id)==='266'&&String(p.product_ref?.game_id)===game.admin_game_id&&String(p.product_ref?.model_id)===model);
  }
  const api={project,resolveModel};if(typeof module==='object'&&module.exports)module.exports=api;else root.SeasonalHalloweenView=api;
  if(!root.document)return;
  const doc=root.document,esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let config={},view=project(config),activeGame=null,media={},lastGameButton=null,referenceTimer=null;
  const revealed=new Set(),animatingSlots=new Set(),dialog=doc.querySelector('#event-dialog');
  let currentDay=nyDay(),lastSlotHtml=null;
  const receipts=new Map(),drawing=new Set();
  const fixedOffer=game=>({slot:'fixed',model_id:game.fixed_model,off_percent:game.fixed_off_percent,...(game.random_source==='quantity_tiers'?{quantity:{value:game.fixed_quantity.value,unit:game.fixed_quantity.unit}}:{})});
  const slotOffer=(game,slot)=>{if(slot==='fixed')return fixedOffer(game);const receipt=receipts.get(game.id),row=receipt?.slots.find(row=>row.slot===slot);return row?{...row,reveal_request_id:receipt.request_id}:null;};
  const status=message=>{doc.querySelector('#event-status').textContent=message;};
  function animateFlip(card){
    if(!card)return;
    const slot=card.closest('[data-offer-slot]')?.dataset.offerSlot||null;
    const selector='[data-offer-slot="'+(slot||'fixed')+'"] .flip-card';
    if(root.matchMedia?.('(prefers-reduced-motion: reduce)').matches){
      if(slot)animatingSlots.delete(slot);
      renderSlots();
      return;
    }
    // The detail block stays hidden until the edge has crossed and the sweep has
    // finished, so the price never appears while the card is still turning.
    if(slot)animatingSlots.add(slot);
    renderSlots();
    const fresh=doc.querySelector(selector);
    if(!fresh){if(slot)animatingSlots.delete(slot);return;}
    fresh.focus({preventScroll:true});
    fresh.classList.add('is-revealed','just-revealed');
    setTimeout(()=>{
      if(slot)animatingSlots.delete(slot);
      renderSlots();
      doc.querySelector(selector)?.focus({preventScroll:true});
    },1500);
  }
  // An anonymous visitor keeps the same draw across reloads and tabs. The durable
  // request id and receipt live in the runtime adapter; this view only replays it.
  function restoreReceipts(){
    for(const game of view.games){
      const receipt=root.SeasonalCommerce?.cachedReveal?.(game.id);
      if(!receipt||receipts.has(game.id))continue;
      receipts.set(game.id,receipt);
      // The runtime records the fixed pick as slot 'fixed' of the very same
      // receipt, so a reload has to turn it again as well. Skipping it here left
      // the first card closed while the two mystery cards came back flipped.
      for(const slot of receipt.slots||[])revealed.add(slot.slot==='fixed'?fixedToken(game):receipt.request_id+':'+slot.slot);
    }
  }

  const fixedToken=game=>[game.id,game.fixed_model,game.fixed_off_percent,game.fixed_quantity?.value].join(':');
  function contractFor(game,offer=fixedOffer(game)){
    const contract=config.seasonal_model_contracts?.[offer.model_id],products=resolveModel(config,game,offer.model_id);
    if(!contract||!products.length||String(contract.model_ref?.site_id)!=='266'||String(contract.model_ref?.game_id)!==game.admin_game_id||String(contract.model_ref?.model_id)!==offer.model_id)return null;
    try{
      root.SeasonalModelSelection.create(contract);
      if(!contract.combinations.every(c=>products.some(p=>p.key===c.product_key)))return null;
      return contract;
    }catch{return null;}
  }
  // Bridge a background refresh only until the original price expires.
  const lastPrices=new Map();
  function referenceFor(game,offer=fixedOffer(game)){
    const contract=contractFor(game,offer);if(!contract||offer.off_percent===null)return null;
    const key=game.id+':'+offer.model_id+':'+offer.off_percent+':'+(offer.quantity?.value||'');
    const previous=()=>{const price=lastPrices.get(key);if(Date.parse(price?.expires_at)>Date.now())return price;lastPrices.delete(key);return null;};
    try{const priced=offer.quantity?{...contract,combinations:contract.combinations.filter(c=>c.quantity.min===offer.quantity.value&&c.quantity.max===offer.quantity.value&&c.quantity.unit===offer.quantity.unit)}:contract;const price=root.SeasonalModelSelection.defaultPrice(priced,offer.off_percent);
      if(game.id==='fc'&&offer.slot==='fixed'&&(price.quantity.value!=='1000'||price.quantity.unit!=='K'))return previous();
      lastPrices.set(key,price);
      return price;
    }catch{return previous();}
  }
  function format(value,currency,scale){try{return new Intl.NumberFormat('en-US',{style:'currency',currency}).format(value/10**scale);}catch{return 'Reference price unavailable';}}
  function eventConfigured(){return view.status==='configured'&&view.probabilities&&view.binding&&view.starts_at&&view.ends_at&&Date.parse(view.starts_at)<=Date.now()&&Date.parse(view.ends_at)>=Date.now();}
  const cartAllows=(game,offer)=>root.SeasonalCommerce?.canOffer?.(game,offer)!==false;
  function cartLabel(game,offer){if(!cartAllows(game,offer))return 'Review current cart first';return ['selected','recoverable'].includes(root.SeasonalCommerce?.cartState?.().state)?'View selected offer':'Buy Now';}
  function paintCartGuidance(){
    const box=doc.getElementById('cart-guidance');if(!box)return;const state=root.SeasonalCommerce?.cartState?.().state||'untracked';box.hidden=['untracked','empty'].includes(state);
    const notes={checking:'Checking your current cart before enabling another offer.',selected:'Your selected offer is still in the cart. Open it without adding it twice, or remove it yourself before choosing another offer. There is no daily purchase limit.',recoverable:'Your previous add and all product options are confirmed in the cart. Open the selected offer without adding it again.',unknown:'The previous add is unconfirmed. Check your cart; do not submit it again while the result or product options remain unknown. Contact support if it cannot be confirmed.',occupied:'Your current cart was started with another offer. Complete that checkout or remove its items yourself before choosing an event offer.',unavailable:'Your cart status could not be verified. Check your connection and try Check cart status. No new items or codes were changed.'};
    doc.getElementById('cart-guidance-status').textContent=notes[state]||'';
  }
  function buyReady(game,offer=fixedOffer(game)){return Boolean(cartAllows(game,offer)&&eventConfigured()&&offer&&offer.off_percent!==null&&contractFor(game,offer)&&(referenceFor(game,offer)||root.SeasonalCommerce?.nativeOffer(game,offer)));}
  function showDialog(title,body){doc.querySelector('#dialog-title').textContent=title;doc.querySelector('#dialog-content').innerHTML=body;if(!dialog.open)dialog.showModal();}
  function renderHero(){
    const image=doc.querySelector('#hero-image'),source=doc.querySelector('#hero-mobile-source');
    if(media.hero_desktop?.url){image.src=media.hero_desktop.url;image.alt=english(media.hero_desktop.alt,'Halloween collection artwork');image.dataset.publishedMedia='true';}else{image.src='assets/halloween-max.png';image.alt='Max at the Halloween mystery store';}
    if(media.hero_mobile?.url){source.srcset=media.hero_mobile.url;source.dataset.publishedMedia='true';}else source.removeAttribute('srcset');
  }
  function renderGames(){
    const games=doc.querySelector('#games');
    games.innerHTML=view.games.map(game=>{const card=media.cards?.['game:'+game.id],image=card?.url||game.asset;
      const logo=game.logo?'<img class="game-logo" src="'+esc(game.logo)+'" width="2172" height="724" alt="" aria-hidden="true">':'';
      return '<button type="button" class="game-card" data-game-card="'+game.id+'" aria-controls="game-offers" aria-expanded="'+(activeGame===game.id)+'"><img class="game-art" src="'+esc(image)+'" alt="'+esc(english(card?.alt,game.label+' artwork'))+'"><span class="game-shade"></span>'+logo+'<span class="game-badge orange">'+(eventConfigured()?'8–15% OFF':'SURPRISE OFFERS')+'</span><span class="game-info"><h3>'+game.label+'</h3><span class="open-label">OPEN STORE <b aria-hidden="true">→</b></span></span></button>';
    }).join('');
    games.hidden=Boolean(activeGame);
    doc.querySelector('#picker-title').textContent=activeGame?view.games.find(g=>g.id===activeGame).label+' offers':'Choose your game';
    doc.querySelector('#store-count').hidden=Boolean(activeGame);doc.querySelector('#event-countdown').hidden=Boolean(activeGame);doc.querySelector('[data-action=all-games]').hidden=!activeGame;
  }
  function renderSlots(){
    clearTimeout(referenceTimer);let nextExpiry=Infinity;const region=doc.querySelector('#game-offers');region.hidden=!activeGame;if(!activeGame)return;
    const game=view.games.find(g=>g.id===activeGame),products=resolveModel(config,game),model=products[0],configured=Boolean(model&&game.fixed_off_percent!==null),open=revealed.has(fixedToken(game)),reference=referenceFor(game);
    doc.querySelector('#game-offers-title').textContent=game.label+' collection';
    doc.querySelector('#game-offers-note').textContent='One fixed pick. Two surprise offers. Flip a card to explore.';
    if(reference)nextExpiry=Math.min(nextExpiry,Date.parse(reference.expires_at));
    const title=english(model?.title,game.label+' model'),businessAmount=game.fixed_quantity?'<p class="business-quantity">'+esc(game.fixed_quantity.label)+'</p>':'';
    const price=reference?'<div class="reference-price"><span>Limited-Time Price</span><div class="price-line"><strong>'+format(reference.indicative_discounted_minor,reference.currency,reference.minor_unit_scale)+'</strong><del>'+format(reference.base_minor,reference.currency,reference.minor_unit_scale)+'</del></div></div>':'';
    const fixed='<article class="offer-slot fixed-slot" data-offer-slot="fixed"><span class="slot-label">MYSTERY PICK 01</span><button type="button" class="flip-card '+(open?'is-revealed':'')+'" data-fixed-reveal aria-expanded="'+open+'" '+(!configured?'disabled':'')+'><span class="card-back" '+(open?'aria-hidden="true"':'')+'><span class="mystery-mark" aria-hidden="true">?</span><strong>'+(configured?'Reveal your surprise':'Awaiting configuration')+'</strong><small>'+(configured?'Tap to turn your card':'Product model and offer binding unavailable')+'</small></span><span class="card-front" '+(!open?'aria-hidden="true"':'')+'>'+faceContent({title,off:game.fixed_off_percent,image:categoryArt(game.id,model?.title,model?.image)})+businessAmount+'</span><span class="reveal-rays" aria-hidden="true"></span></button><div class="slot-detail'+(open&&animatingSlots.has('fixed')?' is-pending':'')+'" '+(!open?'hidden':'')+'>'+price+'<button type="button" class="button primary buy-button" data-model-buy="'+esc(game.fixed_model||'')+'" '+(!buyReady(game)?'disabled':'')+'>'+cartLabel(game,fixedOffer(game))+'</button>'+(contractFor(game)?'':'<p class="slot-note">Verified model options are not connected. Purchasing is unavailable.</p>')+'</div></article>';
    const random=[1,2].map(n=>{
      const slot='random-'+n,offer=slotOffer(game,slot),receipt=receipts.get(game.id),token=receipt?.request_id+':'+slot,open=offer&&revealed.has(token),product=offer&&resolveModel(config,game,offer.model_id)[0],reference=offer&&referenceFor(game,offer);
      if(reference)nextExpiry=Math.min(nextExpiry,Date.parse(reference.expires_at));
      const price=reference?'<div class="reference-price"><span>Limited-Time Price</span><div class="price-line"><strong>'+format(reference.indicative_discounted_minor,reference.currency,reference.minor_unit_scale)+'</strong><del>'+format(reference.base_minor,reference.currency,reference.minor_unit_scale)+'</del></div></div>':'';
      const tp=titleParts(english(product?.title,'Mystery selection'));
      const qtyPrefix=offer?.quantity?offer.quantity.value+' '+offer.quantity.unit+' ':'';
      const detail=open?'<div class="slot-detail'+(animatingSlots.has(slot)?' is-pending':'')+'">'+price+'<button type="button" class="button primary buy-button" data-model-buy="'+esc(offer.model_id)+'" data-buy-slot="'+slot+'" '+(!buyReady(game,offer)?'disabled':'')+'>'+cartLabel(game,offer)+'</button></div>':'';
      return '<article class="offer-slot random-slot" data-offer-slot="'+slot+'"><span class="slot-label">MYSTERY PICK 0'+(n+1)+'</span><button type="button" class="flip-card '+(open?'is-revealed':'')+'" data-random-reveal="'+slot+'" aria-expanded="'+Boolean(open)+'" '+(!eventConfigured()||drawing.has(game.id)?'disabled':'')+'><span class="card-back" '+(open?'aria-hidden="true"':'')+'><span class="mystery-mark" aria-hidden="true">?</span><strong>'+(drawing.has(game.id)?'Opening your collection…':'Reveal your surprise')+'</strong><small>'+(eventConfigured()?'Tap to turn your card':'Offer probabilities and dates are not configured')+'</small></span><span class="card-front" '+(!open?'aria-hidden="true"':'')+'>'+faceContent({title:tp.main,attrs:tp.attrs,off:offer?.off_percent,image:categoryArt(game.id,product?.title,product?.image),qty:qtyPrefix})+'</span><span class="reveal-rays" aria-hidden="true"></span></button>'+detail+'</article>';
    }).join('');
    // Rebuilding identical markup resets focus and can replay transitions, so
    // only touch the DOM when the offers actually changed.
    const html=fixed+random;
    if(html!==lastSlotHtml){doc.querySelector('#offer-slots').innerHTML=html;lastSlotHtml=html;}
    for(const slot of ['fixed','random-1','random-2'])if(doc.querySelector('[data-offer-slot="'+slot+'"] .flip-card[aria-expanded="true"]'))track('exposure',game,slotOffer(game,slot));
    // Remove a visible price at its own expiry. A missing price polls at 60s,
    // rather than looping on the expired timestamp of a previous reference.
    const delay=Number.isFinite(nextExpiry)?Math.max(1,nextExpiry-Date.now()+1):60000;
    referenceTimer=setTimeout(()=>{renderSlots();root.SeasonalCommerce?.refresh().catch(()=>status('Prices could not be refreshed. Please use Refresh prices before continuing.'));},Math.min(2147483647,delay));

  }
  let countdownTimer=null;
  function startCountdown(){
    const paint=()=>{
      // Read the window on every tick: the first paint can happen before the
      // published configuration arrives.
      const now=Date.now(),end=view.ends_at?Date.parse(view.ends_at):null;
      const hero=doc.querySelector('#event-countdown'),refresh=doc.querySelector('#offers-refresh');
      if(hero)hero.innerHTML=Number.isFinite(end)&&end>now?clockWidget(end-now,'Ends in'):'';
      if(refresh)refresh.innerHTML=clockWidget(nextNyMidnight(now)-now,'Daily reset in');
    };
    paint();
    if(!countdownTimer)countdownTimer=setInterval(paint,1000);
  }
  function renderConfiguration(){
    const missing=[];if(!view.probabilities)missing.push('discount probabilities');if(!view.binding)missing.push('offer allocation');if(!view.starts_at||!view.ends_at)missing.push('event dates');if(view.games.some(g=>!g.fixed_model||!['category_dynamic','quantity_tiers'].includes(g.random_source)&&g.random_models.length<2||g.fixed_off_percent===null))missing.push('product models and offer bindings');
    doc.querySelector('.offer-availability').hidden=missing.length===0;
    doc.querySelector('#configuration-title').textContent='Offers are not available yet';
    doc.querySelector('#configuration-summary').textContent=missing.length?'Please check back soon. You can still explore the games in our main store.':'Published settings are available. Mystery slots still require a server-confirmed draw; final prices and eligibility require store confirmation.';
    startCountdown();
  }
  function track(action,game,offer={}){try{root.FCActivityAnalytics?.offer(action,{game_id:String(game?.admin_game_id||''),...offer});}catch{/* Analytics must never block offers. */}}
  function update(input){
    if(!input||typeof input!=='object')return;
    // A new US Eastern day closes every card again so it can be flipped afresh.
    const today=nyDay();
    if(today!==currentDay){currentDay=today;revealed.clear();receipts.clear();lastPrices.clear();}
    if(config.release_id!==input.release_id||config.config_hash!==input.config_hash){receipts.clear();revealed.clear();lastPrices.clear();}
    config=input;view=project(config);paintCartGuidance();media=config.page_media?.['seasonal-vault']||media;
    restoreReceipts();
    renderHero();renderGames();renderSlots();renderConfiguration();
  }
  root.addEventListener('seasonal-cart-state',()=>{paintCartGuidance();renderSlots();});
  doc.addEventListener('click',async event=>{
    const gameButton=event.target.closest('[data-game-card]');
    if(gameButton){lastGameButton=gameButton.dataset.gameCard;activeGame=lastGameButton;track('game_select',view.games.find(g=>g.id===activeGame));renderGames();renderSlots();doc.querySelector('[data-action=all-games]').focus();return;}
    if(event.target.closest('[data-action=all-games]')){activeGame=null;renderGames();renderSlots();doc.querySelector('[data-game-card="'+lastGameButton+'"]').focus();return;}
    if(event.target.closest('[data-fixed-reveal]')){const game=view.games.find(g=>g.id===activeGame);if(!game||!resolveModel(config,game).length||game.fixed_off_percent===null)return;if(revealed.has(fixedToken(game)))return;revealed.add(fixedToken(game));renderSlots();animateFlip(doc.querySelector('[data-fixed-reveal]'));status('Your fixed offer is ready. Choose your options to continue.');track('offer_reveal',game,fixedOffer(game));return;}
    const random=event.target.closest('[data-random-reveal]');
    if(random&&!random.disabled){
      const game=view.games.find(g=>g.id===activeGame),slot=random.dataset.randomReveal;if(!game||drawing.has(game.id))return;
      // A revealed card stays revealed: re-clicking must not replay the flip or
      // ask the store for a second draw.
      const prior=receipts.get(game.id);
      if(prior&&revealed.has(prior.request_id+':'+slot))return;
      drawing.add(game.id);renderSlots();let flipped=false;
      try{
        // One automatic retry: the same request id is reused, so a retry can
        // never produce a different draw, it only recovers a lost response.
        let receipt=null;
        for(let attempt=0;attempt<2&&!receipt;attempt++){
          if(attempt)await new Promise(resolve=>setTimeout(resolve,1200));
          try{receipt=await root.SeasonalCommerce.reveal(game.id);}catch{receipt=null;}
        }
        if(!receipt)throw Error('DRAW_FAILED');
        if(receipt.release_id!==config.release_id||receipt.config_hash!==config.config_hash)throw Error('RULE_VERSION_CONFLICT');
        receipts.set(game.id,receipt);revealed.add(receipt.request_id+':'+slot);flipped=true;status('Your mystery card is ready.');
      }catch(error){const message='This card did not open. Tap it to try again.';status(message);doc.querySelector('.draw-status').textContent=message;}
      finally{drawing.delete(game.id);renderSlots();if(flipped&&activeGame===game.id){animateFlip(doc.querySelector('[data-random-reveal="'+slot+'"]'));track('offer_reveal',game,slotOffer(game,slot));}}return;
    }
    const buy=event.target.closest('[data-model-buy]');if(buy&&!buy.disabled){
      const game=view.games.find(g=>g.id===activeGame),offer=slotOffer(game,buy.dataset.buySlot||'fixed');if(!game||!offer||!buyReady(game,offer))return;
      const detail={model_id:offer.model_id,game_id:game.admin_game_id,slot:offer.slot,off_percent:offer.off_percent,...(offer.quantity?{quantity:offer.quantity}:{}),...(offer.slot!=='fixed'?{reveal_request_id:receipts.get(game.id).request_id}:{})};
      showDialog('Choose your options','<p>Loading your selection…</p>');root.dispatchEvent(new CustomEvent('seasonal:model-buy',{detail}));return;
    }
    const action=event.target.closest('[data-action]')?.dataset.action;
    if(action==='cart-refresh'){void root.SeasonalCommerce?.refreshCart?.(true);return;}
    if(action==='close')dialog.close();
  });
  root.addEventListener('seasonal-published-catalog',event=>update(event.detail));
  root.addEventListener('seasonal-published-media',event=>{media=event.detail||{};renderHero();renderGames();renderSlots();});
  renderGames();renderSlots();renderConfiguration();if(root.SeasonalPublishedConfig)update(root.SeasonalPublishedConfig);
})(typeof window==='undefined'?globalThis:window);
