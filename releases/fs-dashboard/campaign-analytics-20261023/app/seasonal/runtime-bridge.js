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
    OPERATION_UNKNOWN: 'The original operation is pending or unknown. Check its status; do not submit it again.',
    PRICE_CHANGED: 'The store price changed. Review a new quote before continuing.',
    QUOTE_EXPIRED: 'This quote expired. Review your selection again.'
  };
  function describe(error) {
    return messages[error?.code] || 'The store could not verify this request. No successful checkout is confirmed.';
  }
  function lines(bag) {
    return bag.map((line, i) => {
      const p = window.SeasonalData.products.find(p => p.id === line.id);
      if (!p || !Number.isFinite(p.source.quantity) || p.source.quantity <= 0) throw Object.assign(new Error(), {code:'SPEC_INVALID'});
      return {line_key:`seasonal-line-${i + 1}`, product_key:`seasonal-${p.id}`,
        quantity:{value:String(p.source.quantity), unit:p.source.unit}, attributes:[]};
    });
  }
  function publishTheme(config) {
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
        report('Checking the published store configuration…');
        const loaded = await client.load();
        publishTheme(loaded.config);
        if (action === 'lookup') {
          const result = await client.lookup();
          report(result?.status === 'unknown' ? messages.OPERATION_UNKNOWN : `Original operation status: ${result?.status || 'unknown'}. No live cart change is confirmed.`);
          return;
        }
        if (action === 'prepare') {
          const result = await client.prepare();
          report(`Integration test result: ${result?.status || 'unknown'}. No live cart, payment, discount or reward is confirmed.`);
          return;
        }
        if (this.pending()) { report(messages.OPERATION_UNKNOWN); return; }
        if (!bag.length) { report('Choose a product before checking with the store.'); return; }
        report('Validating product quantities and required specifications…');
        const result = await client.select(lines(bag));
        // Test quotes never turn a DEMO draw into an approved discount or reward.
        report(`Server response: ${result?.quote?.status || 'quote received'}. ${client.describe()} Demo discounts and invitation rewards remain simulations.`);
      } catch (error) { report(describe(error)); }
    }
  };
  if (window.SeasonalCommerce.available()) {
    try {
      client = sdk.create({element:document.documentElement, pageId:'seasonal-vault', activityId:'mmoexp-seasonal'});
      client.load().then(({config})=>publishTheme(config)).catch(()=>{});
    } catch { /* Invalid operation storage stays blocked and is reported on interaction. */ }
  }
})();
