/* Server-validated purchase entry. Demo draws and invitation receipts stay local. */
(() => {
  'use strict';
  const sdk = window.CampaignStandalone;
  let client, publishedThemeApplied = false;
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
  };
  function describe(error) {
    return messages[error?.code] || 'The store could not verify this request. No successful checkout is confirmed.';
  }
  const publicStatus=value=>typeof value==='string'&&/^[a-z][a-z0-9_ -]*$/i.test(value)?value:'unknown';
  function lines(bag) {
    return bag.map((line, i) => {
      const p = window.SeasonalData.products.find(p => p.id === line.id);
      if (!p || !Number.isFinite(p.source.quantity) || p.source.quantity <= 0) throw Object.assign(new Error(), {code:'SPEC_INVALID'});
      return {line_key:`seasonal-line-${i + 1}`, product_key:`seasonal-${p.id}`,
        quantity:{value:String(p.source.quantity), unit:p.source.unit}, attributes:[]};
    });
  }
  function publishTheme(config) {
    window.SeasonalPublishedConfig=config;
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
    canPrepare: () => client?.capabilities?.integration_mode === 'integration_test' && client?.capabilities?.test_capabilities?.prepare_checkout === true && client?.pending?.stage === 'quoted' && !client?.pending?.unknown,
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
          const result = await client.prepare();
          report(`Integration test result: ${publicStatus(result?.status)}. No live cart, payment, discount or reward is confirmed.`);
          return;
        }
        if (this.pending()) { report(messages.OPERATION_UNKNOWN); return; }
        if (!bag.length) { report('Choose a product before checking with the store.'); return; }
        report('Validating product quantities and required specifications…');
        const result = await client.select(lines(bag));
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
