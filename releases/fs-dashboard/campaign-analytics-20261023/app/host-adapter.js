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
  function createNative(snapshot,selection){
    const approved=root.CampaignNativeCodeHandoff.publishedPlan(snapshot,selection,{origin:root.location.origin});
    const items=approved.items;
    return {async claimSelection(body){
      const prefix=root.document?.documentElement?.dataset.campaignRuntime||'/events/';
      if(!/^\/(?:[A-Za-z0-9_-]+\/)+$/.test(prefix))throw Error('INVALID_PUBLIC_PATH');
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try{const response=await root.fetch(prefix+'api/campaign/native_plan',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});const receipt=await response.json();if(!response.ok)throw Error(receipt.code||'NATIVE_SELECTION_UNAVAILABLE');return receipt;}finally{clearTimeout(timer);}
    },async verifySelection(body){
      const prefix=root.document?.documentElement?.dataset.campaignRuntime||'/events/';
      if(!/^\/(?:[A-Za-z0-9_-]+\/)+$/.test(prefix))throw Error('INVALID_PUBLIC_PATH');
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try{const response=await root.fetch(prefix+'api/campaign/halloween/resolve',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:controller.signal});const receipt=await response.json();if(!response.ok)throw Error(receipt.code||'HALLOWEEN_REVEAL_UNAVAILABLE');return receipt;}finally{clearTimeout(timer);}
    },batch(){let started=false;return {async run(sent,progress=()=>{}){
      if(started)throw Error('Original native operation already started');started=true;
      if(JSON.stringify(sent)!==JSON.stringify(items))throw Error('Native selection changed');const outcomes=[];
      for(const item of items){let state='unknown';
        try{
          const body=item.native_payload;
          if(body.category==='new_gold'&&!item.observed_serialization){
            const expected=root.FCActivityCore.coinsPayload({origin:root.location.origin,region:'us',currency:'USD',model_id:'41217957',goods_id:String(body.id),platform:'ps',quantity:'1000',unit:'K'});
            if(JSON.stringify(expected)!==JSON.stringify(body))throw Error('Coins serialization changed');
          }
          const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
          try{
            const response=await root.fetch('/Cart/add.html',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body:new URLSearchParams(body),signal:controller.signal});
            if(!response.ok)throw Error('Native cart response unavailable');const receipt=root.FCActivityCore.result(await response.json());state=receipt.ok?'confirmed':receipt.unknown?'unknown':'rejected';
          }finally{clearTimeout(timer);}
        }catch{/* An uncertain POST is never retried. */}
        outcomes.push({id:item.offer.id,state});progress([...outcomes]);if(state!=='confirmed')break;
      }return outcomes;
    }}}};
  }
  // Read the current main-store price for the exact pinned listings and project
  // the published activity price. Same-origin only: no cross-origin catalog, no
  // currency helpers from the legacy page. The original cart remains the
  // authority for the final payable amount and code eligibility.
  function createLivePrice(config){
    if(root.location?.origin!=='https://www.mmoexp.com')throw new Error('Live price requires the existing MMOEXP origin');
    if(typeof config?.api?.catalog!=='string'||!config.api.catalog.startsWith('/'))throw new Error('Live price requires a same-origin catalog route');
    if(!Number.isInteger(config?.activityPricing?.discountPercent))throw new Error('Activity pricing is not configured');
    const format=amount=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(amount/100);
    async function post(url,data){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
      try{
        const response=await root.fetch(url,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body:new URLSearchParams(data),signal:controller.signal});
        if(!response.ok)throw new Error('HTTP '+response.status);
        return await response.json();
      } finally {clearTimeout(timer);}
    }
    return {
      source:'main_catalog',
      quote(items){return Promise.all(items.map(item=>root.FCActivityCore.refreshLine(config,item,post)));},
      display(item){
        const price=root.FCActivityCore.activityPrice(item.amount,config);
        return {text:format(price.amount),amount:price.amount,baseAmount:price.baseAmount,discountAmount:price.discountAmount,currency:'USD'};
      }
    };
  }
  root.FCActivityHost={create,createNative,createLivePrice};
})(window);
