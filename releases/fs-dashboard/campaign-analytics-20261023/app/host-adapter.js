(function(root){
  'use strict';
  function create(config) {
    if(root.location.origin!=='https://www.mmoexp.com')throw new Error('Live cart requires the existing MMOEXP origin');
    if(config.activityPricing?.strategy==='native_discount_code')throw new Error('Native discount-code handoff requires verification before live use');
    if(config.activityPricing?.enabled)throw new Error('Activity-source discount and stacked-margin checkout must be integrated before live use');
    const path=value=>typeof root.langPageUrl==='function'?root.langPageUrl(value):value;
    async function post(url,data) {
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try {
        const response=await fetch(url===config.api.catalog?url:path(url),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body:new URLSearchParams(data),signal:controller.signal});
        if(!response.ok)throw new Error('HTTP '+response.status);
        return await response.json();
      } finally {clearTimeout(timer);}
    }
    return {
      async quote(items) {
        return Promise.all(items.map(item=>root.FCActivityCore.refreshLine(config,item,post)));
      },
      batch() {return root.FCActivityCore.createBatch(data=>post(config.api.cartAdd,data));},
      display(item) {
        if(typeof root.js_rate!=='function'||typeof root.parseDisplayAmount!=='function')throw new Error('Existing currency helpers are required');
        const raw=item.currentRaw;
        const text=root.js_rate(raw.full_price*item.offer.quantity,0,raw.discount);
        const amount=root.parseDisplayAmount(text);
        if(!Number.isFinite(amount)||amount<=0)throw new Error('Current currency amount unavailable');
        return {text,amount:Math.round(amount*100),currency:root.GV?.valuta?.code||'USD'};
      },
      cartUrl:path(config.api.cart),
      total(amount){return root.js_rate(amount/100,0,100,1,2,{...(root.GV?.valuta||{code:'USD',sign:'$'}),rate:1});},
      refreshHeader(){if(typeof root.syncHeaderCartBadge==='function')root.syncHeaderCartBadge();}
    };
  }
  root.FCActivityHost={create};
})(window);
