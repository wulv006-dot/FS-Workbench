(function(root){
  'use strict';
  const IDS=['fc','aion','wow','maplestory'],LABELS={fc:'FC27',aion:'Aion2',wow:'World of Warcraft',maplestory:'MapleStory'},TIERS=[8,15,10];
  const english=(value,fallback)=>typeof value==='string'&&value.trim()&&!/\p{Script=Han}/u.test(value)?value:fallback;
  const identifier=value=>typeof value==='string'&&value.trim()&&!/[\x00-\x20]/.test(value)?value:null;
  // The event ends and the daily picks reset at midnight US Eastern, so the page
  // and the draw agree on which day it is.
  const NY_ZONE='America/New_York';
  function nyOffset(ts){
    const parts=new Intl.DateTimeFormat('en-US',{timeZone:NY_ZONE,hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).formatToParts(new Date(ts));
    const p={};for(const x of parts)p[x.type]=x.value;
    return Date.UTC(+p.year,+p.month-1,+p.day,(+p.hour)%24,+p.minute,+p.second)-Math.floor(ts/1000)*1000;
  }
  function nextNyMidnight(ts){
    const offset=nyOffset(ts),local=new Date(ts+offset);
    return Date.UTC(local.getUTCFullYear(),local.getUTCMonth(),local.getUTCDate()+1,0,0,0,0)-offset;
  }
  function clock(ms){
    if(!Number.isFinite(ms)||ms<=0)return '00:00:00';
    const total=Math.floor(ms/1000),d=Math.floor(total/86400),h=Math.floor(total%86400/3600),m=Math.floor(total%3600/60),s=total%60;
    const pad=n=>String(n).padStart(2,'0');
    return (d?d+'d ':'')+pad(h)+':'+pad(m)+':'+pad(s);
  }
  function project(config){
    const source=config?.halloween?.schema_version===1&&String(config.halloween.site_id)==='266'?config.halloween:{};
    const rows=Array.isArray(source.games)?source.games:[];
    const probabilities=Array.isArray(source.probabilities)&&source.probabilities.length===3&&new Set(source.probabilities.map(p=>p.off_percent)).size===3&&source.probabilities.every(p=>TIERS.includes(p.off_percent)&&Number.isInteger(p.weight)&&p.weight>=0&&p.weight<=10000)&&source.probabilities.reduce((n,p)=>n+p.weight,0)===10000?source.probabilities:null;
    const starts=Date.parse(source.starts_at),ends=Date.parse(source.ends_at),windowReady=Number.isFinite(starts)&&Number.isFinite(ends)&&ends>starts;
    return {status:source.status==='configured'?'configured':'unconfigured',probabilities,binding:source.tier_product_binding==='independent'?'independent':null,starts_at:windowReady?source.starts_at:null,ends_at:windowReady?source.ends_at:null,
      games:IDS.map((id,i)=>{const row=rows.find(g=>g?.id===id)||{};return {id,label:LABELS[id],asset:'assets/game-'+(i+1)+'.png',admin_game_id:identifier(Number.isSafeInteger(row.admin_game_id)&&row.admin_game_id>0?String(row.admin_game_id):row.admin_game_id),fixed_model:identifier(row.fixed_model),fixed_off_percent:TIERS.includes(row.fixed_off_percent)?row.fixed_off_percent:null,random_source:['category_dynamic','category_snapshot','quantity_tiers'].includes(row.random_source?.mode)?row.random_source.mode:'models',random_models:Array.isArray(row.random_models)?row.random_models.map(identifier).filter(Boolean):[],random_count:2,fixed_quantity:id==='fc'?{value:'1000',unit:'K',label:'1000K Coins',conversion_verified:false}:row.fixed_quantity?{...row.fixed_quantity,label:row.fixed_quantity.value+' '+row.fixed_quantity.unit+' '+(id==='aion'?'Kinah':'Gold')}:null};})};
  }
  function resolveModel(config,game,model=game.fixed_model){
    if(!model||!game.admin_game_id)return [];
    return (Array.isArray(config?.products)?config.products:[]).filter(p=>String(p.product_ref?.site_id)==='266'&&String(p.product_ref?.game_id)===game.admin_game_id&&String(p.product_ref?.model_id)===model);
  }
  const api={project,resolveModel};if(typeof module==='object'&&module.exports)module.exports=api;else root.SeasonalHalloweenView=api;
  if(!root.document)return;
  const doc=root.document,esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let config={},view=project(config),activeGame=null,media={},lastGameButton=null,referenceTimer=null;
  const revealed=new Set(),dialog=doc.querySelector('#event-dialog');
  const receipts=new Map(),drawing=new Set();
  const fixedOffer=game=>({slot:'fixed',model_id:game.fixed_model,off_percent:game.fixed_off_percent,...(game.random_source==='quantity_tiers'?{quantity:{value:game.fixed_quantity.value,unit:game.fixed_quantity.unit}}:{})});
  const slotOffer=(game,slot)=>{if(slot==='fixed')return fixedOffer(game);const receipt=receipts.get(game.id),row=receipt?.slots.find(row=>row.slot===slot);return row?{...row,reveal_request_id:receipt.request_id}:null;};
  const status=message=>{doc.querySelector('#event-status').textContent=message;};
  function animateFlip(card){
    if(!card)return;card.focus({preventScroll:true});
    if(root.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
    // One controlled charge, then the edge crosses. The face swap is driven by
    // visibility inside the keyframes, so a mirrored face is never painted.
    card.classList.add('is-revealed','just-revealed');
    setTimeout(()=>{if(card.isConnected)card.classList.remove('just-revealed');},1500);
  }
  // An anonymous visitor keeps the same draw across reloads and tabs. The durable
  // request id and receipt live in the runtime adapter; this view only replays it.
  function restoreReceipts(){
    for(const game of view.games){
      const receipt=root.SeasonalCommerce?.cachedReveal?.(game.id);
      if(!receipt||receipts.has(game.id))continue;
      receipts.set(game.id,receipt);
      for(const slot of receipt.slots||[])if(slot.slot!=='fixed')revealed.add(receipt.request_id+':'+slot.slot);
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
  function referenceFor(game,offer=fixedOffer(game)){
    const contract=contractFor(game,offer);if(!contract||offer.off_percent===null)return null;
    try{const priced=offer.quantity?{...contract,combinations:contract.combinations.filter(c=>c.quantity.min===offer.quantity.value&&c.quantity.max===offer.quantity.value&&c.quantity.unit===offer.quantity.unit)}:contract;const price=root.SeasonalModelSelection.defaultPrice(priced,offer.off_percent);
      if(game.id==='fc'&&offer.slot==='fixed'&&(price.quantity.value!=='1000'||price.quantity.unit!=='K'))return null;
      return price;
    }catch{return null;}
  }
  function format(value,currency,scale){try{return new Intl.NumberFormat('en-US',{style:'currency',currency}).format(value/10**scale);}catch{return 'Reference price unavailable';}}
  function eventConfigured(){return view.status==='configured'&&view.probabilities&&view.binding&&view.starts_at&&view.ends_at&&Date.parse(view.starts_at)<=Date.now()&&Date.parse(view.ends_at)>=Date.now();}
  function buyReady(game,offer=fixedOffer(game)){return Boolean(eventConfigured()&&offer&&offer.off_percent!==null&&contractFor(game,offer)&&(referenceFor(game,offer)||root.SeasonalCommerce?.nativeOffer(game,offer)));}
  function showDialog(title,body){doc.querySelector('#dialog-title').textContent=title;doc.querySelector('#dialog-content').innerHTML=body;if(!dialog.open)dialog.showModal();}
  function renderHero(){
    const image=doc.querySelector('#hero-image'),source=doc.querySelector('#hero-mobile-source');
    if(media.hero_desktop?.url){image.src=media.hero_desktop.url;image.alt=english(media.hero_desktop.alt,'Halloween collection artwork');image.dataset.publishedMedia='true';}else{image.src='assets/halloween-max.png';image.alt='Max at the Halloween mystery store';}
    if(media.hero_mobile?.url){source.srcset=media.hero_mobile.url;source.dataset.publishedMedia='true';}else source.removeAttribute('srcset');
  }
  function renderGames(){
    const games=doc.querySelector('#games');
    games.innerHTML=view.games.map(game=>{const card=media.cards?.['game:'+game.id],image=card?.url||game.asset;
      return '<button type="button" class="game-card" data-game-card="'+game.id+'" aria-controls="game-offers" aria-expanded="'+(activeGame===game.id)+'"><img class="game-art" src="'+esc(image)+'" alt="'+esc(english(card?.alt,game.label+' artwork'))+'"><span class="game-shade"></span><span class="game-badge orange">'+(eventConfigured()?'8–15% OFF':'SURPRISE OFFERS')+'</span><span class="game-info"><h3>'+game.label+'</h3><span class="open-label">OPEN STORE <b aria-hidden="true">→</b></span></span></button>';
    }).join('');
    games.hidden=Boolean(activeGame);
    doc.querySelector('#picker-title').textContent=activeGame?view.games.find(g=>g.id===activeGame).label+' offers':'Choose your game';
    doc.querySelector('#store-count').hidden=Boolean(activeGame);doc.querySelector('[data-action=all-games]').hidden=!activeGame;
  }
  function renderSlots(){
    clearTimeout(referenceTimer);let nextExpiry=Infinity;const region=doc.querySelector('#game-offers');region.hidden=!activeGame;if(!activeGame)return;
    const game=view.games.find(g=>g.id===activeGame),products=resolveModel(config,game),model=products[0],configured=Boolean(model&&game.fixed_off_percent!==null),open=revealed.has(fixedToken(game)),reference=referenceFor(game);
    doc.querySelector('#game-offers-title').textContent=game.label+' collection';
    doc.querySelector('#game-offers-note').textContent='One fixed pick. Two surprise offers. Flip a card to explore.';
    if(reference)nextExpiry=Math.min(nextExpiry,Date.parse(reference.expires_at));
    const title=english(model?.title,game.label+' model'),businessAmount=game.fixed_quantity?'<p class="business-quantity">'+esc(game.fixed_quantity.label)+'</p>':'';
    const price=reference?'<div class="reference-price"><span>Default combination reference</span><div class="price-line"><strong>'+format(reference.indicative_discounted_minor,reference.currency,reference.minor_unit_scale)+'</strong><del>'+format(reference.base_minor,reference.currency,reference.minor_unit_scale)+'</del></div></div>':'<p class="unavailable-price">'+(game.id==='fc'?(root.SeasonalCommerce?.nativeFixed(game)?'The published native binding covers PS 1000K Coins. Final price and code eligibility are confirmed in the native cart.':'1000K Coins purchase-unit conversion is not verified. Reference price and purchasing are unavailable.'):'Default combination reference unavailable')+'</p>';
    const fixed='<article class="offer-slot fixed-slot" data-offer-slot="fixed"><span class="slot-label">FIXED SELECTION</span><button type="button" class="flip-card '+(open?'is-revealed':'')+'" data-fixed-reveal aria-expanded="'+open+'" '+(!configured?'disabled':'')+'><span class="card-back" '+(open?'aria-hidden="true"':'')+'><span class="vault-symbol" aria-hidden="true">✦</span><strong>'+(configured?'Your fixed pick':'Awaiting configuration')+'</strong>'+businessAmount+'<small>'+(configured?'Flip to reveal your offer':'Product model and offer binding unavailable')+'</small></span><span class="card-front" '+(!open?'aria-hidden="true"':'')+'><small>'+game.label+'</small><strong>'+esc(title)+'</strong>'+businessAmount+'<b>'+(game.fixed_off_percent===null?'Offer unavailable':game.fixed_off_percent+'% OFF')+'</b><small>Choose your server to continue</small></span><span class="reveal-rays" aria-hidden="true"></span></button><div class="slot-detail" '+(!open?'hidden':'')+'>'+price+'<button type="button" class="button primary buy-button" data-model-buy="'+esc(game.fixed_model||'')+'" '+(!buyReady(game)?'disabled':'')+'>Buy Now</button>'+(contractFor(game)?'':'<p class="slot-note">Verified model options are not connected. Purchasing is unavailable.</p>')+'</div></article>';
    const random=[1,2].map(n=>{
      const slot='random-'+n,offer=slotOffer(game,slot),receipt=receipts.get(game.id),token=receipt?.request_id+':'+slot,open=offer&&revealed.has(token),product=offer&&resolveModel(config,game,offer.model_id)[0],reference=offer&&referenceFor(game,offer);
      if(reference)nextExpiry=Math.min(nextExpiry,Date.parse(reference.expires_at));
      const price=reference?'<div class="reference-price"><span>Default combination reference</span><div class="price-line"><strong>'+format(reference.indicative_discounted_minor,reference.currency,reference.minor_unit_scale)+'</strong><del>'+format(reference.base_minor,reference.currency,reference.minor_unit_scale)+'</del></div></div>':'<p class="unavailable-price">Current reference price unavailable. Select your options to check the native store.</p>';
      const detail=open?'<div class="slot-detail">'+price+'<button type="button" class="button primary buy-button" data-model-buy="'+esc(offer.model_id)+'" data-buy-slot="'+slot+'" '+(!buyReady(game,offer)?'disabled':'')+'>Buy Now</button></div>':'';
      return '<article class="offer-slot random-slot" data-offer-slot="'+slot+'"><span class="slot-label">MYSTERY PICK 0'+n+'</span><button type="button" class="flip-card '+(open?'is-revealed':'')+'" data-random-reveal="'+slot+'" aria-expanded="'+Boolean(open)+'" '+(!eventConfigured()||drawing.has(game.id)?'disabled':'')+'><span class="card-back" '+(open?'aria-hidden="true"':'')+'><span class="mystery-mark" aria-hidden="true">?</span><strong>'+(drawing.has(game.id)?'Opening your collection…':'Reveal your surprise')+'</strong><small>'+(eventConfigured()?'Tap to turn your card':'Offer probabilities and dates are not configured')+'</small></span><span class="card-front" '+(!open?'aria-hidden="true"':'')+'><small>'+game.label+'</small><strong>'+esc((offer?.quantity?offer.quantity.value+' '+offer.quantity.unit+' ':'')+english(product?.title,'Mystery selection'))+'</strong><b>'+(offer?offer.off_percent+'% OFF':'')+'</b></span><span class="reveal-rays" aria-hidden="true"></span></button>'+detail+'</article>';
    }).join('');
    doc.querySelector('#offer-slots').innerHTML=fixed+random;
    if(Number.isFinite(nextExpiry))referenceTimer=setTimeout(()=>{renderSlots();root.SeasonalCommerce?.refresh().catch(()=>status('Prices could not be refreshed. Please use Refresh prices before continuing.'));},Math.max(1,Math.min(2147483647,nextExpiry-Date.now()+1)));

  }
  let countdownTimer=null;
  function startCountdown(){
    const paint=()=>{
      // Read the window on every tick: the first paint can happen before the
      // published configuration arrives.
      const now=Date.now(),end=view.ends_at?Date.parse(view.ends_at):null;
      const hero=doc.querySelector('#event-countdown'),refresh=doc.querySelector('#offers-refresh');
      if(hero)hero.textContent=Number.isFinite(end)&&end>now?'ENDS IN '+clock(end-now):'';
      if(refresh)refresh.textContent='Daily reset in '+clock(nextNyMidnight(now)-now)+' — new picks and discounts every day';
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
  function update(input){
    if(!input||typeof input!=='object')return;
    if(config.release_id!==input.release_id||config.config_hash!==input.config_hash){receipts.clear();revealed.clear();}
    config=input;view=project(config);media=config.page_media?.['seasonal-vault']||media;
    restoreReceipts();
    renderHero();renderGames();renderSlots();renderConfiguration();
  }
  doc.addEventListener('click',async event=>{
    const gameButton=event.target.closest('[data-game-card]');
    if(gameButton){lastGameButton=gameButton.dataset.gameCard;activeGame=lastGameButton;renderGames();renderSlots();doc.querySelector('[data-action=all-games]').focus();return;}
    if(event.target.closest('[data-action=all-games]')){activeGame=null;renderGames();renderSlots();doc.querySelector('[data-game-card="'+lastGameButton+'"]').focus();return;}
    if(event.target.closest('[data-fixed-reveal]')){const game=view.games.find(g=>g.id===activeGame);if(!game||!resolveModel(config,game).length||game.fixed_off_percent===null)return;if(revealed.has(fixedToken(game)))return;revealed.add(fixedToken(game));renderSlots();animateFlip(doc.querySelector('[data-fixed-reveal]'));status('Your fixed offer is ready. Choose your options to continue.');return;}
    const random=event.target.closest('[data-random-reveal]');
    if(random&&!random.disabled){
      const game=view.games.find(g=>g.id===activeGame),slot=random.dataset.randomReveal;if(!game||drawing.has(game.id))return;
      // A revealed card stays revealed: re-clicking must not replay the flip or
      // ask the store for a second draw.
      const prior=receipts.get(game.id);
      if(prior&&revealed.has(prior.request_id+':'+slot))return;
      drawing.add(game.id);renderSlots();let flipped=false;
      try{const receipt=await root.SeasonalCommerce.reveal(game.id);
        if(receipt.release_id!==config.release_id||receipt.config_hash!==config.config_hash)throw Error('RULE_VERSION_CONFLICT');
        receipts.set(game.id,receipt);revealed.add(receipt.request_id+':'+slot);flipped=true;status('Your mystery card is ready.');
      }catch(error){const message='Your collection could not be verified. Please try again to check the same request.';status(message);doc.querySelector('.draw-status').textContent=message;}
      finally{drawing.delete(game.id);renderSlots();if(flipped&&activeGame===game.id)animateFlip(doc.querySelector('[data-random-reveal="'+slot+'"]'));}return;
    }
    const buy=event.target.closest('[data-model-buy]');if(buy&&!buy.disabled){
      const game=view.games.find(g=>g.id===activeGame),offer=slotOffer(game,buy.dataset.buySlot||'fixed');if(!game||!offer||!buyReady(game,offer))return;
      const detail={model_id:offer.model_id,game_id:game.admin_game_id,slot:offer.slot,off_percent:offer.off_percent,...(offer.quantity?{quantity:offer.quantity}:{}),...(offer.slot!=='fixed'?{reveal_request_id:receipts.get(game.id).request_id}:{})};
      showDialog('Choose your options','<p>Loading your selection…</p>');root.dispatchEvent(new CustomEvent('seasonal:model-buy',{detail}));return;
    }
    const action=event.target.closest('[data-action]')?.dataset.action;
    if(action==='close')dialog.close();
  });
  root.addEventListener('seasonal-published-catalog',event=>update(event.detail));
  root.addEventListener('seasonal-published-media',event=>{media=event.detail||{};renderHero();renderGames();renderSlots();});
  renderGames();renderSlots();renderConfiguration();if(root.SeasonalPublishedConfig)update(root.SeasonalPublishedConfig);
})(typeof window==='undefined'?globalThis:window);
