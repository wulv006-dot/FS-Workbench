(function(root){
  'use strict';
  const IDS=['fc','aion','wow','maplestory'],LABELS={fc:'FC27',aion:'Aion2',wow:'World of Warcraft',maplestory:'MapleStory'},TIERS=[8,15,10];
  const english=(value,fallback)=>typeof value==='string'&&value.trim()&&!/\p{Script=Han}/u.test(value)?value:fallback;
  const identifier=value=>typeof value==='string'&&value.trim()&&!/[\x00-\x20]/.test(value)?value:null;
  function project(config){
    const source=config?.halloween?.schema_version===1&&String(config.halloween.site_id)==='266'?config.halloween:{};
    const rows=Array.isArray(source.games)?source.games:[];
    const probabilities=Array.isArray(source.probabilities)&&source.probabilities.length===3&&new Set(source.probabilities.map(p=>p.off_percent)).size===3&&source.probabilities.every(p=>TIERS.includes(p.off_percent)&&Number.isInteger(p.weight)&&p.weight>=0&&p.weight<=10000)&&source.probabilities.reduce((n,p)=>n+p.weight,0)===10000?source.probabilities:null;
    const starts=Date.parse(source.starts_at),ends=Date.parse(source.ends_at),windowReady=Number.isFinite(starts)&&Number.isFinite(ends)&&ends>starts;
    return {status:source.status==='configured'?'configured':'unconfigured',probabilities,binding:source.tier_product_binding==='independent'?'independent':null,starts_at:windowReady?source.starts_at:null,ends_at:windowReady?source.ends_at:null,
      games:IDS.map((id,i)=>{const row=rows.find(g=>g?.id===id)||{};return {id,label:LABELS[id],asset:'assets/game-'+(i+1)+'.png',admin_game_id:identifier(Number.isSafeInteger(row.admin_game_id)&&row.admin_game_id>0?String(row.admin_game_id):row.admin_game_id),fixed_model:identifier(row.fixed_model),fixed_off_percent:TIERS.includes(row.fixed_off_percent)?row.fixed_off_percent:null,random_models:Array.isArray(row.random_models)?row.random_models.map(identifier).filter(Boolean):[],random_count:2,fixed_quantity:id==='fc'?{value:'1000',unit:'K',label:'1000K Coins',conversion_verified:false}:null};})};
  }
  function resolveModel(config,game){
    if(!game.fixed_model||!game.admin_game_id)return [];
    return (Array.isArray(config?.products)?config.products:[]).filter(p=>String(p.product_ref?.site_id)==='266'&&String(p.product_ref?.game_id)===game.admin_game_id&&String(p.product_ref?.model_id)===game.fixed_model);
  }
  const api={project,resolveModel};if(typeof module==='object'&&module.exports)module.exports=api;else root.SeasonalHalloweenView=api;
  if(!root.document)return;
  const doc=root.document,esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let config={},view=project(config),activeGame=null,media={},lastGameButton=null,referenceTimer=null;
  const revealed=new Set(),dialog=doc.querySelector('#event-dialog');
  const status=message=>{doc.querySelector('#event-status').textContent=message;};
  const fixedToken=game=>[game.id,game.fixed_model,game.fixed_off_percent].join(':');
  function contractFor(game){
    const contract=config.seasonal_model_contracts?.[game.fixed_model],products=resolveModel(config,game);
    if(!contract||!products.length||String(contract.model_ref?.site_id)!=='266'||String(contract.model_ref?.game_id)!==game.admin_game_id||String(contract.model_ref?.model_id)!==game.fixed_model)return null;
    try{
      root.SeasonalModelSelection.create(contract);
      if(!contract.combinations.every(c=>products.some(p=>p.key===c.product_key)))return null;
      return contract;
    }catch{return null;}
  }
  function referenceFor(game){
    // A draft flag cannot authorize conversion of the FC1000K business amount.
    if(game.id==='fc')return null;
    const contract=contractFor(game);if(!contract||game.fixed_off_percent===null)return null;
    try{return root.SeasonalModelSelection.defaultPrice(contract,game.fixed_off_percent);}catch{return null;}
  }
  function format(value,currency,scale){try{return new Intl.NumberFormat('en-US',{style:'currency',currency}).format(value/10**scale);}catch{return 'Reference price unavailable';}}
  function eventConfigured(){return view.status==='configured'&&view.probabilities&&view.binding&&view.starts_at&&view.ends_at&&Date.parse(view.starts_at)<=Date.now()&&Date.parse(view.ends_at)>Date.now();}
  function buyReady(game){return Boolean(eventConfigured()&&game.fixed_off_percent!==null&&contractFor(game)&&referenceFor(game));}
  function showDialog(title,body){doc.querySelector('#dialog-title').textContent=title;doc.querySelector('#dialog-content').innerHTML=body;if(!dialog.open)dialog.showModal();}
  function renderHero(){
    const image=doc.querySelector('#hero-image'),source=doc.querySelector('#hero-mobile-source');
    if(media.hero_desktop?.url){image.src=media.hero_desktop.url;image.alt=english(media.hero_desktop.alt,'Halloween collection artwork');image.dataset.publishedMedia='true';}else{image.removeAttribute('src');image.alt='';}
    if(media.hero_mobile?.url){source.srcset=media.hero_mobile.url;source.dataset.publishedMedia='true';}else source.removeAttribute('srcset');
  }
  function renderGames(){
    const games=doc.querySelector('#games');
    games.innerHTML=view.games.map(game=>{const card=media.cards?.['game:'+game.id],image=card?.url||game.asset;
      return '<button type="button" class="game-card" data-game-card="'+game.id+'" aria-controls="game-offers" aria-expanded="'+(activeGame===game.id)+'"><img src="'+esc(image)+'" alt="'+esc(english(card?.alt,game.label+' artwork'))+'"><span class="game-card-shade"></span><span class="game-card-copy"><small>HALLOWEEN COLLECTION</small><strong>'+game.label+'</strong><span>1 FIXED + 2 MYSTERY</span><b>Explore collection <i aria-hidden="true">↗</i></b></span></button>';
    }).join('');
    games.hidden=Boolean(activeGame);
  }
  function renderSlots(){
    clearTimeout(referenceTimer);const region=doc.querySelector('#game-offers');region.hidden=!activeGame;if(!activeGame)return;
    const game=view.games.find(g=>g.id===activeGame),products=resolveModel(config,game),model=products[0],configured=Boolean(model&&game.fixed_off_percent!==null),open=revealed.has(fixedToken(game)),reference=referenceFor(game);
    doc.querySelector('#game-offers-title').textContent=game.label+' collection';
    doc.querySelector('#game-offers-note').textContent='One fixed selection. Two server-drawn mystery slots. Viewing a card does not award a benefit.';
    if(reference)referenceTimer=setTimeout(renderSlots,Math.max(1,Math.min(2147483647,Date.parse(reference.expires_at)-Date.now()+1)));
    const title=english(model?.title,game.label+' model'),businessAmount=game.fixed_quantity?'<p class="business-quantity">'+esc(game.fixed_quantity.label)+'</p>':'';
    const price=reference?'<div class="reference-price"><span>Default combination reference</span><strong>'+format(reference.indicative_discounted_minor,reference.currency,reference.minor_unit_scale)+'</strong><small>Before offer: '+format(reference.base_minor,reference.currency,reference.minor_unit_scale)+'</small><p>First available store combination only. Your actual options require a new current quote.</p></div>':'<p class="unavailable-price">'+(game.id==='fc'?'1000K Coins purchase-unit conversion is not verified. Reference price and purchasing are unavailable.':'Default combination reference unavailable')+'</p>';
    const fixed='<article class="offer-slot fixed-slot" data-offer-slot="fixed"><span class="slot-label">FIXED SELECTION</span><button type="button" class="flip-card '+(open?'is-revealed':'')+'" data-fixed-reveal aria-expanded="'+open+'" '+(!configured?'disabled':'')+'><span class="card-back" '+(open?'aria-hidden="true"':'')+'><span class="vault-symbol" aria-hidden="true">✦</span><strong>'+(configured?'Your fixed pick':'Awaiting configuration')+'</strong>'+businessAmount+'<small>'+(configured?'View the configured offer':'Product model and offer binding unavailable')+'</small></span><span class="card-front" '+(!open?'aria-hidden="true"':'')+'><small>'+game.label+'</small><strong>'+esc(title)+'</strong>'+businessAmount+'<b>'+(game.fixed_off_percent===null?'Offer unavailable':game.fixed_off_percent+'% OFF')+'</b><small>Configured offer · store eligibility unconfirmed</small></span></button><div class="slot-detail" '+(!open?'hidden':'')+'>'+price+'<button type="button" class="button primary buy-button" data-model-buy="'+esc(game.fixed_model||'')+'" '+(!buyReady(game)?'disabled':'')+'>Buy Now · choose options</button><p class="slot-note">'+(contractFor(game)?'Platform, server, specifications and quantity are selected before a final quote.':'Verified model options are not connected. Purchasing is unavailable.')+'</p></div></article>';
    const random=[1,2].map(n=>'<article class="offer-slot random-slot" data-offer-slot="random-'+n+'"><span class="slot-label">MYSTERY PICK 0'+n+'</span><button type="button" class="flip-card" disabled aria-label="Mystery pick '+n+' unavailable: no server-confirmed draw"><span class="card-back"><span class="mystery-mark" aria-hidden="true">?</span><strong>Awaiting your surprise</strong><small>Server-confirmed draw unavailable</small></span></button><p class="slot-note">'+(!view.probabilities?'Offer probabilities are not configured.':'A server-confirmed draw is required.')+' No local offer is drawn.</p></article>').join('');
    doc.querySelector('#offer-slots').innerHTML=fixed+random;
  }
  function renderConfiguration(){
    const missing=[];if(!view.probabilities)missing.push('discount probabilities');if(!view.binding)missing.push('offer allocation');if(!view.starts_at||!view.ends_at)missing.push('event dates');if(view.games.some(g=>!g.fixed_model||g.random_models.length!==2||g.fixed_off_percent===null))missing.push('product models and offer bindings');
    doc.querySelector('#configuration-title').textContent=missing.length?'Offer configuration pending':'Published configuration loaded';
    doc.querySelector('#configuration-summary').textContent=missing.length?'Not configured: '+missing.join(', ')+'. Mystery offers remain unavailable; no draw or reward has been issued.':'Published settings are available. Mystery slots still require a server-confirmed draw; final prices and eligibility require store confirmation.';
    doc.querySelector('#campaign-date').textContent=view.starts_at&&view.ends_at?'Event window (UTC): '+new Date(view.starts_at).toISOString()+' — '+new Date(view.ends_at).toISOString():'Event window: not configured';
  }
  function update(input){
    if(!input||typeof input!=='object')return;
    config=input;view=project(config);media=config.page_media?.['seasonal-vault']||media;
    renderHero();renderGames();renderSlots();renderConfiguration();
  }
  doc.addEventListener('click',event=>{
    const gameButton=event.target.closest('[data-game-card]');
    if(gameButton){lastGameButton=gameButton.dataset.gameCard;activeGame=lastGameButton;renderGames();renderSlots();doc.querySelector('[data-action=all-games]').focus();return;}
    if(event.target.closest('[data-action=all-games]')){activeGame=null;renderGames();renderSlots();doc.querySelector('[data-game-card="'+lastGameButton+'"]').focus();return;}
    if(event.target.closest('[data-fixed-reveal]')){const game=view.games.find(g=>g.id===activeGame);if(!game||!resolveModel(config,game).length||game.fixed_off_percent===null)return;revealed.add(fixedToken(game));renderSlots();status('Configured fixed offer shown. No benefit was awarded.');return;}
    const buy=event.target.closest('[data-model-buy]');if(buy&&!buy.disabled){const game=view.games.find(g=>g.id===activeGame);if(!buyReady(game))return;showDialog('Choose your actual combination','<p>Platform, server, specifications and quantity must be verified before a current price can be quoted.</p><p id="model-buy-status" role="status">Model selection integration is pending. No cart, code or payment action has been performed.</p><button class="button primary" disabled>Continue to checkout</button>');root.dispatchEvent(new CustomEvent('seasonal:model-buy',{detail:{model_id:game.fixed_model,game_id:game.admin_game_id,slot:'fixed',off_percent:game.fixed_off_percent}}));return;}
    const action=event.target.closest('[data-action]')?.dataset.action;
    if(action==='close')dialog.close();
    if(action==='rules'){
      const probability=view.probabilities?view.probabilities.map(p=>p.off_percent+'% OFF: '+(p.weight/100)+'%').join(' · '):'Not configured';
      showDialog('Event details','<p>Planned discount tiers: 8% OFF, 15% OFF and 10% OFF. No tier is assigned to a mystery slot in this browser.</p><dl><dt>Discount probabilities</dt><dd>'+esc(probability)+'</dd><dt>Offer allocation</dt><dd>'+(view.binding?'Independently configured':'Not configured')+'</dd><dt>Event window</dt><dd>'+esc(view.starts_at&&view.ends_at?view.starts_at+' to '+view.ends_at:'Not configured')+'</dd></dl><p>Random offers require a server-confirmed result. Existing coupons, member points, cart contents and final eligibility are governed by the verified store integration.</p><p>No referral reward, refresh credit or local draw is granted by this page.</p>');
    }
  });
  root.addEventListener('seasonal-published-catalog',event=>update(event.detail));
  root.addEventListener('seasonal-published-media',event=>{media=event.detail||{};renderHero();renderGames();renderSlots();});
  renderGames();renderSlots();renderConfiguration();if(root.SeasonalPublishedConfig)update(root.SeasonalPublishedConfig);
})(typeof window==='undefined'?globalThis:window);
