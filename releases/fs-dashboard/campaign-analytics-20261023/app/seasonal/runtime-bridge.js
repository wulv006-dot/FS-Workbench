/* Server-validated purchase entry. Demo draws and invitation receipts stay local. */
(() => {
  'use strict';
  const sdk = window.CampaignStandalone;
  let client, publishedThemeApplied = false, selectionRevision=0, quoteContext=null;
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
  function selectionFor(id) {
    const contract=client?.config?.seasonal_model_contracts?.['seasonal-'+id];
    if(!contract||!window.SeasonalModelSelection)throw Object.assign(new Error(),{code:'MODEL_OPTIONS_UNAVAILABLE'});
    return window.SeasonalModelSelection.create(contract);
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
    if (Object.hasOwn(window.SeasonalData.themes, publishedTheme)) {
      publishedThemeApplied = true;
      window.dispatchEvent(new CustomEvent('seasonal-published-theme', {detail:publishedTheme}));
    }
  }
  window.SeasonalCommerce = {
    available: () => Boolean(sdk?.enabled(document.documentElement)),
    pending: () => Boolean(client?.pending?.unknown || client?.pending?.stage === 'prepare'),
    // Existing runtime remains preview/test only; no browser contract grants live permission.
    canPrepare: () => Boolean(quoteContext&&quoteContext.revision===selectionRevision&&Date.parse(quoteContext.expires_at)>Date.now()&&client?.capabilities?.integration_mode==='integration_test'&&client?.capabilities?.test_capabilities?.prepare_checkout===true&&client?.pending?.stage==='quoted'&&!client?.pending?.unknown),
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
  if (window.SeasonalCommerce.available()) {
    try {
      client = sdk.create({element:document.documentElement, pageId:'seasonal-vault', activityId:'mmoexp-seasonal'});
      client.load().then(({config})=>publishTheme(config)).catch(()=>{});
    } catch { /* Invalid operation storage stays blocked and is reported on interaction. */ }
  }
})();
