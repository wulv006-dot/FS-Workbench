/* Server-validated purchase entry. Demo draws and invitation receipts stay local. */
(() => {
  'use strict';
  const sdk = window.CampaignStandalone;
  const LIVE_ORIGIN='https://www.mmoexp.com';
  let client, refreshFlight=null, dialogRefreshHandler=null, publishedThemeApplied = false, selectionRevision=0, quoteContext=null;
  let nativeCartGuard,cartState={state:'untracked'},cartFlight=null,cartDirty=false;
  const guard=()=>nativeCartGuard ||= window.CampaignNativeCodeHandoff.createCartGuard();
  const paintCart=()=>window.dispatchEvent(new CustomEvent('seasonal-cart-state',{detail:structuredClone(cartState)}));
  async function refreshCart(force=false){
    if(window.location.origin!==LIVE_ORIGIN)return cartState;
    if(cartFlight){cartDirty=true;return cartFlight;}
    try{if(!force&&!guard().known()&&['untracked','empty'].includes(cartState.state))return cartState;}catch{cartState={state:'unavailable'};paintCart();return cartState;}
    cartState={state:'checking'};paintCart();
    cartFlight=guard().inspect(()=>window.FCActivityHost.readNativeCart()).then(value=>{cartState=value;paintCart();return value;}).catch(()=>{cartState={state:'unavailable'};paintCart();return cartState;}).finally(()=>{cartFlight=null;if(cartDirty){cartDirty=false;void refreshCart(true);}});
    return cartFlight;
  }
  function canOffer(game,offer){
    if(['untracked','empty'].includes(cartState.state))return true;
    const chosen=cartState.selection;
    return ['selected','recoverable'].includes(cartState.state)&&chosen&&String(game.admin_game_id)===chosen.game_id&&offer.model_id===chosen.model_id&&offer.slot===chosen.slot&&offer.off_percent===chosen.off_percent&&(offer.quantity?.value||null)===(chosen.quantity?.value||null)&&(offer.quantity?.unit||null)===(chosen.quantity?.unit||null);
  }
  // The live cart is rendered by the storefront and reads its own session cookies.
  // A visitor who lands on this event page directly has no storefront session yet,
  // so the cart POST creates one that the cart page then cannot see. A bare HEAD
  // establishes the same cookies as the storefront without downloading it.
  async function ensureStoreSession(){
    try{
      if(window.location.origin!==LIVE_ORIGIN)return;
      if(/(?:^|;\s*)PHPSESSID=/.test(document.cookie))return;
      await fetch('/',{method:'HEAD',credentials:'same-origin',cache:'no-store'});
    }catch{ /* The cart call still reports its own failure. */ }
  }
  const messages = {
    MAIN_INTEGRATION_REQUIRED: 'Preview only. Main-site cart integration is still required; no cart, discount or reward was changed.',
    SPEC_REQUIRED: 'The store requires product specifications. Open the original product to choose them; nothing has been ordered.',
    SPEC_INVALID: 'These specifications could not be verified. Open the original product; nothing has been ordered.',
    PRODUCT_UNAVAILABLE: 'This package is not enabled for server checkout. Product mapping or availability still needs verification; use the original store link.',
    RULE_VERSION_CONFLICT: 'The published offer changed. Review your selection again before continuing.',
    PROMOTION_NOT_STARTED: 'This published activity has not started yet. Checkout is unavailable before its published start time.',
    // commerce.active() uses this code for inactive pages as well as elapsed end times.
    PROMOTION_EXPIRED: 'This published activity is paused or has ended. Checkout is unavailable for this offer.',
    OPERATION_UNKNOWN: 'The original operation is pending or unknown. Check its status; do not submit it again.',
    PRICE_CHANGED: 'The store price changed. Review a new quote before continuing.',
    QUOTE_EXPIRED: 'This quote expired. Review your selection again.'
    ,MODEL_OPTIONS_UNAVAILABLE: 'Model options are not connected. Platform, server, specifications, quantity and authoritative pricing remain unavailable.'
    ,QUANTITY_INVALID: 'Choose a quantity within the verified limits for this combination.'
    ,SELECTION_CHANGED: 'Your selection changed. Discard the old quote and request a new one.'
  };
  function describe(error) {
    return messages[error?.code] || 'The store could not verify this request. No successful checkout is confirmed.';
  }
  const publicStatus=value=>typeof value==='string'&&/^[a-z][a-z0-9_ -]*$/i.test(value)?value:'unknown';
  function selectionFor(id,quantity) {
    const contract=client?.config?.seasonal_model_contracts?.[String(id)]??client?.config?.seasonal_model_contracts?.['seasonal-'+id];
    if(!contract||!window.SeasonalModelSelection)throw Object.assign(new Error(),{code:'MODEL_OPTIONS_UNAVAILABLE'});
    const scoped=quantity?{...contract,combinations:contract.combinations.filter(c=>c.quantity.min===quantity.value&&c.quantity.max===quantity.value&&c.quantity.unit===quantity.unit)}:contract;
    return window.SeasonalModelSelection.create(scoped);
  }
  function lines(bag) {
    return bag.map((item,i)=>{
      const selected=selectionFor(item.id),saved=item.selection;
      if(!saved||saved.catalog_version!==selected.contractVersion)throw Object.assign(new Error(),{code:'MODEL_OPTIONS_UNAVAILABLE'});
      for(const field of selected.fields())selected.select(field.id,saved.choices?.[field.id]);
      if(JSON.stringify(saved.model_ref)!==JSON.stringify(selected.modelRef))throw Object.assign(new Error(),{code:'MODEL_OPTIONS_UNAVAILABLE'});
      selected.setQuantity(saved.quantity);
      return {line_key:`seasonal-line-${i+1}`,...selected.line()};
    });
  }
  function publishTheme(config) {
    window.SeasonalPublishedConfig=config;window.dispatchEvent(new CustomEvent('seasonal-published-media',{detail:config?.page_media?.['seasonal-vault']||{}}));
    window.dispatchEvent(new CustomEvent('seasonal-published-catalog', {detail:config}));
    if (publishedThemeApplied) return;
    const publishedTheme = config?.seasonal_theme;
    if (Object.hasOwn(window.SeasonalData?.themes||{}, publishedTheme)) {
      publishedThemeApplied = true;
      window.dispatchEvent(new CustomEvent('seasonal-published-theme', {detail:publishedTheme}));
    }
  }
  window.SeasonalCommerce = {
    cartState:()=>structuredClone(cartState),refreshCart,canOffer,
    available: () => Boolean(sdk?.enabled(document.documentElement)),
    pending: () => Boolean(client?.pending?.unknown || client?.pending?.stage === 'prepare'),
    // Existing runtime remains preview/test only; no browser contract grants live permission.
    canPrepare: () => Boolean(quoteContext&&quoteContext.revision===selectionRevision&&Date.parse(quoteContext.expires_at)>Date.now()&&client?.capabilities?.integration_mode==='integration_test'&&client?.capabilities?.test_capabilities?.prepare_checkout===true&&client?.pending?.stage==='quoted'&&!client?.pending?.unknown),
    nativeFixed(game){
      return this.nativeOffer(game,{model_id:game.fixed_model,slot:'fixed',off_percent:game.fixed_off_percent});
    },
    nativeOffer(game,offer){
      try{const c=client?.config?.seasonal_model_contracts?.[offer.model_id];if(!c)return false;
        return c.combinations.some(combo=>{try{const selected=selectionFor(offer.model_id);for(const field of selected.fields())selected.select(field.id,combo.choices[field.id]);selected.setQuantity(combo.quantity.min);
          window.CampaignNativeCodeHandoff.publishedPlan(client.config,{activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:game.admin_game_id,...offer,lines:[selected.line()]},{origin:window.location.origin});return true;
        }catch{return false;}});
      }catch{return false;}
    },
    async refresh(){
      if(!client)throw Object.assign(Error(),{code:'MODEL_OPTIONS_UNAVAILABLE'});
      if(!refreshFlight)refreshFlight=client.load().then(({config})=>{publishTheme(config);return config;}).finally(()=>{refreshFlight=null;});
      return refreshFlight;
    },
    async reveal(gameId){if(!client)throw Object.assign(Error(),{code:'HALLOWEEN_NOT_CONFIGURED'});return client.reveal(gameId);},
    cachedReveal(gameId){try{return client?.cachedReveal?.(gameId)||null;}catch{return null;}},
    selectionFor,
    invalidate(){selectionRevision++;quoteContext=null;},
    canQuote(bag){try{return Boolean(bag.length&&!this.pending()&&lines(bag).length);}catch{return false;}},
    lines,
    async run(action, bag, report) {
      if (!this.available()) { report(messages.MAIN_INTEGRATION_REQUIRED); return; }
      try {
        client ||= sdk.create({element:document.documentElement, pageId:'seasonal-vault', activityId:'mmoexp-seasonal'});
        if (action === 'lookup') {
          report('Checking the original request status…');
          const result = await client.lookup();
          if (client.pending?.unknown) report(messages.OPERATION_UNKNOWN);
          else if (client.pending?.resolved) report(`Original operation resolved: ${publicStatus(result?.status)}. Integration test only; no live cart change is confirmed.`);
          else report(`Original selection recovered: ${publicStatus(result?.quote?.status || result?.status)}. ${client.describe()} Demo discounts and invitation rewards remain simulations.`);
          return;
        }
        report('Checking the published store configuration…');
        const loaded = await client.load();
        publishTheme(loaded.config);
        if (action === 'prepare') {
          if(this.pending())throw Object.assign(new Error(),{code:'OPERATION_UNKNOWN'});
          if(quoteContext&&Date.parse(quoteContext.expires_at)<=Date.now()){quoteContext=null;throw Object.assign(new Error(),{code:'QUOTE_EXPIRED'});}
          if(!this.canPrepare())throw Object.assign(new Error(),{code:'SELECTION_CHANGED'});
          const result = await client.prepare();
          report(`Integration test result: ${publicStatus(result?.status)}. No live cart, payment, discount or reward is confirmed.`);
          return;
        }
        if (this.pending()) { report(messages.OPERATION_UNKNOWN); return; }
        if (!bag.length) { report('Choose a product before checking with the store.'); return; }
        report('Validating product quantities and required specifications…');
        const revision=selectionRevision,selection=lines(bag),signature=JSON.stringify(selection);
        const result = await client.select(selection);
        if(revision!==selectionRevision||signature!==JSON.stringify(lines(bag)))throw Object.assign(new Error(),{code:'SELECTION_CHANGED'});
        quoteContext=null;
        // Existing integration-test quotes are never authoritative display prices.
        if(result?.quote?.authoritative===true&&result.quote.test_only!==true&&result.quote.intent_id===result.intent?.intent_id&&result.quote.quote_id&&result.quote.currency==='USD'&&Number.isSafeInteger(result.quote.total_minor)&&result.quote.total_minor>=0&&Date.parse(result.quote.expires_at)>Date.now())quoteContext={revision,expires_at:result.quote.expires_at};
        // Test quotes never turn a DEMO draw into an approved discount or reward.
        report(`Server response: ${publicStatus(result?.quote?.status)}. ${client.describe()} Demo discounts and invitation rewards remain simulations.`);
      } catch (error) { report(client?.pending?.unknown ? messages.OPERATION_UNKNOWN : describe(error)); }
    }
  };
  // The new four-game page uses this one selection bridge. Missing verified
  // catalog data is visible; no fabricated region or snapshot SKU can substitute.
  window.addEventListener('seasonal:model-buy',event=>{
    const host=document.getElementById('dialog-content');if(!host)return;
    const detail=event.detail||{};let contract=client?.config?.seasonal_model_contracts?.[String(detail.model_id)];
    if(dialogRefreshHandler){window.removeEventListener('seasonal-published-catalog',dialogRefreshHandler);dialogRefreshHandler=null;}
    const message=value=>{const p=document.createElement('p');p.textContent=value;return p;};
    host.replaceChildren();
    if(window.SeasonalCommerce.pending()){host.append(message(messages.OPERATION_UNKNOWN));return;}
    let selection;
    try{
      if(!contract||contract.model_ref?.site_id!=='266'||contract.model_ref?.model_id!==String(detail.model_id)||contract.model_ref?.game_id!==String(detail.game_id))throw Error();
      selection=selectionFor(detail.model_id,detail.quantity);
    }catch{host.append(message(messages.MODEL_OPTIONS_UNAVAILABLE));return;}
    const english=(value,fallback)=>typeof value==='string'&&value.trim()&&!/\p{Script=Han}/u.test(value)?value:fallback;
    const CART_NOTE='Reveal all three offers, then use one event offer per cart, across all games. Finish the current checkout or remove its items before choosing another offer. There is no daily purchase limit. Coupons and points cannot be combined with an event code.';
    const fields=document.createElement('div'),price=message('Choose all required options to see the current reference price.'),status=message(CART_NOTE);
    let nativeReview=null,buying=false,lastTrackedSelection=null;
    const trackingFields=plan=>({game_id:String(detail.game_id),model_id:String(detail.model_id),slot:detail.slot,off_percent:detail.off_percent,product_id:String(plan.items[0].native_payload.id),server_id:String(plan.items[0].native_payload.aid||''),discount_code:plan.options.code,quantity_value:selection.line().quantity.value,quantity_unit:selection.line().quantity.unit});
    const track=(action,plan)=>{try{window.FCActivityAnalytics?.offer(action,trackingFields(plan));}catch{/* Never alter the checkout outcome for analytics. */}};
    const nativeSelection=()=>({activity_id:'mmoexp-seasonal',page_id:'seasonal-vault',game_id:String(detail.game_id),model_id:String(detail.model_id),slot:detail.slot,off_percent:detail.off_percent,...(detail.quantity?{quantity:detail.quantity}:{}),...(detail.reveal_request_id?{reveal_request_id:detail.reveal_request_id}:{}),lines:[selection.line()]});
    const buy=document.createElement('button');buy.type='button';buy.disabled=true;buy.textContent='Checkout unavailable';
    const cartLink=document.createElement('a');cartLink.href='/Cart.html';cartLink.textContent='Review your current cart';
    host.append(fields,price,status,buy,cartLink);
    // The live cart is pinned to the storefront origin. Say why the button is not
    // usable instead of leaving a single opaque label on every failure path.
    function blockedReason(code){
      if(code==='HANDOFF_ORIGIN_UNVERIFIED'||window.location.origin!==LIVE_ORIGIN)return 'This address cannot open the live cart. Open the event on '+LIVE_ORIGIN.replace('https://','')+' to check out.';
      if(!selection.ready())return 'Select every option and a valid quantity to continue.';
      if(code==='NATIVE_CONFIGURATION_EXPIRED')return 'This offer window has closed. Reopen the event page to continue.';
      if(code==='NATIVE_SCOPE_MISMATCH'||code==='NATIVE_CHECKOUT_UNCONFIGURED'||code==='HALLOWEEN_REVEAL_REQUIRED')return 'This exact combination is not enabled for the live cart. Choose another option or reopen the offer.';
      return 'The live cart cannot be prepared right now. Reopen the offer and try again.';
    }
    function render(){
      fields.replaceChildren();
      if(detail.quantity&&selection.fields().some(f=>f.id==='quantity_tier'))selection.select('quantity_tier',detail.quantity.value);
      for(const field of selection.fields()){
        if(detail.quantity&&field.id==='quantity_tier')continue;
        const label=document.createElement('label'),select=document.createElement('select');label.textContent=english(field.label,english(field.id,'Option'));
        const empty=document.createElement('option');empty.value='';empty.textContent='Choose '+english(field.label,english(field.id,'option'));select.append(empty);
        for(const item of selection.options(field.id)){const option=document.createElement('option');option.value=item.id;option.textContent=english(item.label,'Option '+(select.options.length));select.append(option);}
        select.value=selection.choices()[field.id]||'';select.disabled=select.options.length===1;
        select.addEventListener('change',()=>{selection.select(field.id,select.value);window.SeasonalCommerce.invalidate();render();});label.append(select);fields.append(label);
      }
      const limits=selection.quantity();
      if(limits){const label=document.createElement('label'),input=document.createElement('input');label.textContent='Quantity ('+english(limits.unit,'units')+')';input.type='number';input.min=limits.min;input.max=limits.max;input.step=limits.step;input.value=detail.quantity?.value||limits.min;input.readOnly=Boolean(detail.quantity);
        selection.setQuantity(input.value);input.addEventListener('input',()=>{selection.setQuantity(input.value);window.SeasonalCommerce.invalidate();showPrice();});label.append(input);fields.append(label);}
      showPrice();
    }
    function showPrice(){
      contract=client?.config?.seasonal_model_contracts?.[String(detail.model_id)];
      buy.disabled=true;nativeReview=null;
      let blocked=null;
      try{nativeReview=window.CampaignNativeCodeHandoff.publishedPlan(client.config,nativeSelection(),{origin:window.location.origin});}
      catch(error){blocked=error?.code||error?.message||null;}
      if(nativeReview&&!canOffer({admin_game_id:detail.game_id},detail)){buy.textContent='Review current cart first';status.textContent='This cart is reserved for another offer, or its status needs checking. Review your cart or check its status on the event page before choosing this offer.';}
      else if(nativeReview&&!buying){buy.disabled=false;buy.textContent='Go to cart';status.textContent=CART_NOTE;if(lastTrackedSelection!==nativeReview.signature){lastTrackedSelection=nativeReview.signature;track('options_ready',nativeReview);}}
      else if(nativeReview&&buying)buy.textContent='Preparing your cart…';
      else{buy.textContent=blocked==='HANDOFF_ORIGIN_UNVERIFIED'||window.location.origin!==LIVE_ORIGIN?'Open on mmoexp.com to check out':selection.ready()?'Checkout unavailable':'Select all options to continue';status.textContent=blockedReason(blocked);}
      try{const value=window.SeasonalModelSelection.selectedPrice(contract,selection,detail.off_percent),format=n=>new Intl.NumberFormat('en',{style:'currency',currency:value.currency}).format(n/10**value.minor_unit_scale);
        price.textContent=format(value.base_minor)+' → '+format(value.indicative_discounted_minor)+' ('+detail.off_percent+'% OFF). Reference for your selected combination; not a checkout quote.';
      }catch{price.textContent=selection.ready()?(nativeReview?'Current price unavailable. The native cart confirms final prices and code eligibility.':'A current price for this exact combination and quantity is unavailable. No checkout is enabled.'):'Choose all required options and a valid quantity.';}
    }
    buy.addEventListener('click',async()=>{
      if(buying||!nativeReview)return;buying=true;buy.disabled=true;fields.querySelectorAll('input,select').forEach(el=>el.disabled=true);
      buy.textContent='Preparing your cart…';
      let outcomeMessage=null,navigating=false;
      try{await ensureStoreSession();const before=nativeReview.signature;await client.load();publishTheme(client.config);const approved=window.CampaignNativeCodeHandoff.publishedPlan(client.config,nativeSelection(),{origin:window.location.origin});
        if(before!==approved.signature)throw Object.assign(Error('Published selection changed. Reopen this offer before continuing.'),{code:'NATIVE_SCOPE_CHANGED'});
        const selected=nativeSelection(),host=window.FCActivityHost.createNative(client.config,selected);
        const result=await window.CampaignNativeCodeHandoff.checkoutPublished({snapshot:client.config,selection:selected,storage:window.sessionStorage,host,cartGuard:guard(),origin:window.location.origin,onCartConfirmed:({code,items})=>track('cart_confirmed',{options:{code},items}),navigate:url=>window.location.assign(url)});navigating=result.state==='navigation_attempted_not_applied';
        if(result.state!=='navigation_attempted_not_applied'&&!result.suppressAnalytics)track('cart_unconfirmed',approved);
        const notes={cart_offer_conflict:'This cart already contains another event offer. Complete that checkout, or remove its items yourself, before choosing a different offer. No items or codes were changed.',cart_code_conflict:'Your cart has another offer or discount. Complete that checkout, or remove its items yourself, before starting a separate checkout. No items or codes were changed.',cart_quantity_changed:'This item is already in your cart with a different quantity. Review or change its quantity in the cart; it was not added again.',cart_busy_inspect_original:'Another event checkout is in progress in this browser. Review the current cart before trying again.',cart_unknown_inspect_original:'The previous add or its full product options could not be confirmed. Review your cart; do not submit again while its result is unknown. Contact support if it cannot be confirmed.'};
        outcomeMessage=notes[result.state]||(result.state==='navigation_attempted_not_applied'?'Opening your current cart. Final totals and code eligibility are confirmed there.':result.outcomes?.length===1&&result.outcomes[0].state==='rejected'?'The store rejected this add. Nothing was added by this request; you may check your options and try again.':'The add result is uncertain. Review your cart before trying again; no automatic retry will be sent.');
      }catch(error){outcomeMessage=['CART_SYNC_UNAVAILABLE','CART_JOURNAL_UNAVAILABLE'].includes(error.code||error.message)?'This browser cannot safely coordinate event checkout. Enable site storage and use a current browser, then reopen the offer. No add was attempted.':(error.message==='NATIVE_CART_READ_UNAVAILABLE'||error.name==='AbortError')?'Your cart could not be checked. Review the current cart and try again after the connection recovers. No new add was attempted.':(error.code||error.message||'Native handoff unavailable')+'. Review the current cart before trying again.';}
      finally{buying=false;if(!navigating)await refreshCart(true);if(document.getElementById('event-dialog')?.open){render();if(outcomeMessage)status.textContent=outcomeMessage;}}
    });
    render();
    const onRefresh=()=>{if(document.getElementById('event-dialog')?.open)showPrice();};
    dialogRefreshHandler=onRefresh;window.addEventListener('seasonal-published-catalog',onRefresh);
    window.addEventListener('seasonal-cart-state',onRefresh);
    const onReturn=()=>{buying=false;if(document.getElementById('event-dialog')?.open){render();status.textContent='Your cart will be checked before any add. An existing item opens the cart; a removed item can be added again.';}};
    window.addEventListener('pageshow',onReturn);
    document.getElementById('event-dialog')?.addEventListener('close',()=>{window.removeEventListener('pageshow',onReturn);window.removeEventListener('seasonal-cart-state',onRefresh);window.removeEventListener('seasonal-published-catalog',onRefresh);if(dialogRefreshHandler===onRefresh)dialogRefreshHandler=null;},{once:true});
  });
  if (window.SeasonalCommerce.available()) {
    ensureStoreSession();
    try {
      client = sdk.create({element:document.documentElement, pageId:'seasonal-vault', activityId:'mmoexp-seasonal'});
      client.load().then(({config})=>{void refreshCart();publishTheme(config);}).catch(()=>{});
    } catch { /* Invalid operation storage stays blocked and is reported on interaction. */ }
  }
  window.addEventListener('storage',event=>{if(event.key==='fs-seasonal-native-cart-v1')void refreshCart(true);});
  window.addEventListener('pageshow',()=>{if(client)void refreshCart();});
  document.addEventListener('visibilitychange',()=>{if(client&&document.visibilityState==='visible')void refreshCart();});
})();
