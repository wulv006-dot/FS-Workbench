(function(){
  'use strict';
  const config=window.FC_ACTIVITY_CONFIG,core=window.FCActivityCore,root=document.getElementById('fc-activity');
  if(!config||!core||!root)return;
  const $=id=>document.getElementById(id),escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const t=(zh,en)=>state.lang==='zh'?zh:en,product=key=>config.products[key],route=key=>config.sbc.routes[key]||{picks:config.sbc.fallbackPicks,alternatives:[],label:{zh:'自选搭配方向',en:'Build your own pairing'}};
  const state={lang:root.dataset.defaultLanguage||config.defaultLanguage||'zh',view:root.dataset.defaultView||config.defaultView||'sbc',platform:'ps',core:config.sbc.defaultId,coreMode:'owned',companions:[...route(config.sbc.defaultId).picks],weekly:new Set([config.weekly.ids[0]]),bundles:new Set(),busy:false,submitted:false};
  const standalone=window.CampaignStandalone?.enabled(document.documentElement),live=config.mode==='live'&&!standalone;let runtimeClient=null;let adapter=null,review=[],reviewFingerprint='',batch=null,priceGeneration=0,unavailableSelection=false;const currentDisplays=new Map();
  const content=window.FCActivityContent.create(config,live),{words,heroes}=content;
  function selected(){try{const items=core.selection(config,state);unavailableSelection=false;return items;}catch(error){unavailableSelection=true;return [];}}
  function money(amount,currency='USD'){return new Intl.NumberFormat(state.lang==='zh'?'zh-CN':'en-US',{style:'currency',currency}).format(amount/100);}
  function display(item){
    if(!item)return {text:t('暂不可用','Unavailable'),amount:null,currency:'USD'};
    if(currentDisplays.has(item.offer.id))return currentDisplays.get(item.offer.id);
    if(live)return {text:t('现价确认中','Checking current price'),amount:null,currency:'USD'};
    const price=core.activityPrice(item.amount,config);
    return {...price,text:money(price.amount),originalText:price.discountAmount?money(price.baseAmount):'',currency:'USD'};
  }
  function savings(items){const values=items.map(display);if(!config.activityPricing?.enabled||!items.length||values.some(v=>v.baseAmount===undefined))return '';const base=values.reduce((sum,v)=>sum+v.baseAmount,0),saved=values.reduce((sum,v)=>sum+v.discountAmount,0);return t('现价合计 ','Listed subtotal ')+'<del>'+escape(money(base))+'</del> · '+t('活动立省 ','Activity savings ')+escape(money(saved));}

  function total(items){const values=items.map(display),currency=values[0]?.currency||'USD';if(unavailableSelection||values.some(v=>v.amount===null||v.currency!==currency))return t('点击核对现价','Check current total');const amount=values.reduce((sum,v)=>sum+v.amount,0);return live&&adapter?adapter.total(amount):money(amount,currency);}
  function meta(p){return [p.rating,p.position,p.version].filter(Boolean).join(' · ');}
  function offer(key){try{return core.line(product(key),state.platform);}catch(error){return null;}}
  function picked(key){return selected().some(p=>p.key===key);}
  function card(key,{label='',fixed=false,owned=false}={}){
    const item=offer(key);
    return content.card(product(key),{lang:state.lang,label,fixed,owned,picked:picked(key),price:display(item).text,originalPrice:display(item).originalText,discountPercent:config.activityPricing?.discountPercent,unavailable:!item});
  }
  function renderSeo(){
    const ids=state.view==='sbc'?[state.core,...state.companions]:undefined,page=content.page(state.view,state.lang,ids);
    $('activity-breadcrumb').innerHTML='<ol>'+page.breadcrumbs.map((x,i)=>'<li>'+(i<2?'<a href="'+escape(x.url)+'">'+escape(x.name)+'</a>':'<span aria-current="page">'+escape(x.name)+'</span>')+'</li>').join('')+'</ol>';
    $('activity-guide').innerHTML=page.guide;
    if(config.manageDocumentLanguage===false)return;
    document.title=page.title;
    for(const [selector,value] of [['meta[name="description"]',page.description],['link[rel="canonical"]',page.canonical],['meta[property="og:title"]',page.title],['meta[property="og:description"]',page.description],['meta[property="og:url"]',page.canonical],['meta[property="og:image"]',page.image],['meta[property="og:locale"]',state.lang==='zh'?'zh_CN':'en_US'],['meta[name="twitter:title"]',page.title],['meta[name="twitter:description"]',page.description],['meta[name="twitter:image"]',page.image]]){const el=document.head.querySelector(selector);if(el){if(el.tagName==='LINK')el.href=value;else el.content=value;}}
    const schema=$('fc-seo-jsonld');if(schema)schema.textContent=window.FCActivityContent.json(page.schema);
  }
  function renderStatic(){
    root.querySelectorAll('button[data-view],a[data-view]').forEach(el=>el.dataset.i18n=({weekly:'navWeekly',sbc:'navSbc',trio:'navTrio'})[el.dataset.view]);
    document.querySelectorAll('.fc-activity [data-i18n],.fca-demo-header [data-i18n],.fca-demo-footer [data-i18n],.fca-skip[data-i18n]').forEach(el=>{const pair=words[el.dataset.i18n];if(pair)el.textContent=pair[state.lang==='zh'?0:1].replaceAll('Star Performer',config.trio.series);if(el.dataset.i18n==='navTrio')el.innerHTML=escape(config.trio.series)+'<span class="fca-trio-label">'+escape(t(' 三人组',' Trio'))+'</span>';});
    document.querySelectorAll('.fc-activity [data-i18n-aria],.fca-demo-header [data-i18n-aria]').forEach(el=>{const pair=words[el.dataset.i18nAria];if(pair)el.setAttribute('aria-label',pair[state.lang==='zh'?0:1]);});
    $('lang-zh')?.setAttribute('aria-pressed',String(state.lang==='zh'));$('lang-en')?.setAttribute('aria-pressed',String(state.lang==='en'));
    if(config.manageDocumentLanguage!==false)document.documentElement.lang=state.lang==='zh'?'zh-CN':'en';
    root.querySelectorAll('button[data-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.view===state.view)));
    root.querySelectorAll('a[data-view]').forEach(el=>{if(el.dataset.view===state.view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  }
  function render(){
    const focusId=document.activeElement?.id;
    renderStatic();$('activity-offer').textContent=content.promotionText(state.lang);$('activity-offer').hidden=!config.activityPricing?.enabled;root.dataset.view=state.view;const h=heroes[state.view];
    $('hero-kicker').textContent=h.kicker;$('hero-title').innerHTML=`<span>${escape(h.title[state.lang==='zh'?0:2])}</span><strong>${escape(h.title[state.lang==='zh'?1:3])}</strong>`;$('hero-body').textContent=t(...h.body);$('hero-cta').textContent=t(...h.cta);$('view-heading').textContent=t(...h.heading);$('view-intro').textContent=t(...h.intro);
    const image=$('hero-image');image.src=state.view==='trio'?config.trio.hero:'assets/'+h.image+'-hero.webp';let source=image.parentElement.querySelector('source');if(!source){source=document.createElement('source');source.media='(max-width: 700px)';image.before(source);}source.srcset=state.view==='trio'?(config.trio.heroMobile||config.trio.hero):'assets/'+h.image+'-hero-mobile.webp';
    const sbc=state.view==='sbc';$('sbc-controls').hidden=!sbc;$('sbc-lineup').hidden=!sbc;$('sbc-options').hidden=!sbc;$('product-grid').hidden=sbc;
    if(sbc){
      $('product-grid').innerHTML='';
      const select=$('core-select');select.innerHTML=config.sbc.ids.map(key=>`<option value="${escape(key)}" ${key===state.core?'selected':''}>${escape(product(key).title)}</option>`).join('');
      $('core-mode-help').textContent=state.coreMode==='owned'?t('核心不加入购买清单，也不计入金额。你只购买两位搭档。','Your owned core is excluded from the purchase and total. You buy the two companions only.'):t('清单包含所选 SBC 代做服务与两张搭档球员卡。服务资源与交付要求沿用原 SBC 订单说明。','Your list includes the selected SBC completion service and two player items. Existing SBC order scope, resources and delivery requirements apply.');
      const current=route(state.core),pool=[...new Set([...current.picks,...current.alternatives])];
      $('sbc-lineup').innerHTML=card(state.core,{label:t('你的 SBC 核心','YOUR SBC CORE'),fixed:true,owned:state.coreMode==='owned'})+state.companions.map((key,i)=>card(key,{label:t('搭档 '+(i+1),'COMPANION '+(i+1)),fixed:true})).join('');
      $('sbc-options').innerHTML=state.companions.map((key,i)=>`<div class="fca-companion-picker"><label for="companion-${i}">${escape(t('搭档 '+(i+1)+' · '+current.label.zh,'Companion '+(i+1)+' · '+current.label.en))}</label><select id="companion-${i}" data-companion-slot="${i}" name="companion${i+1}">${pool.map(option=>`<option value="${escape(option)}" ${option===key?'selected':''} ${option===state.companions[1-i]?'disabled':''}>${escape(product(option).title)}</option>`).join('')}</select></div>`).join('')+`<p class="fca-inline-note fca-pairing-note">${escape(t('这是搭配灵感，不承诺满化学。请核对游戏内位置、联赛与现有阵容。','Pairing ideas do not guarantee full chemistry. Check in-game positions, leagues and your existing lineup.'))}</p>`;
    }else {$('sbc-lineup').innerHTML='';$('sbc-options').innerHTML='';$('product-grid').innerHTML=(state.view==='trio'?config.trio.ids:config.weekly.ids).map((key,i)=>card(key,{label:state.view==='trio'?config.trio.roles[i][state.lang]:config.weekly.edition[state.lang],fixed:state.view==='trio'})).join('');}
    $('bundle-heading').textContent=t('也可以选商店现有阵容包。','Or start with an existing player bundle.');
    $('bundle-grid').innerHTML=config.bundles.ids.map(key=>content.bundle(product(key),{lang:state.lang,price:display(offer(key)).text,originalPrice:display(offer(key)).originalText,discountPercent:config.activityPricing?.discountPercent,checked:state.bundles.has(key)})).join('');
    const items=selected(),snapshotDate=new Intl.DateTimeFormat(state.lang==='zh'?'zh-CN':'en-GB',{year:'numeric',month:'short',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(config.capturedAt));$('summary-count').textContent=String(items.length);$('summary-total').textContent=total(items);$('summary-note').textContent=t('精确商品分别列出，已有核心不重复购买；当前展示为 '+snapshotDate+' 公开价格快照。','Exact items are listed separately. Owned cores are excluded. Public price snapshot: '+snapshotDate+'.');$('review-selection').disabled=!items.length||state.busy||state.submitted;
    $('summary-savings').innerHTML=savings(items);
    if(config.activityPricing?.enabled)$('summary-note').textContent=t('活动价按 '+snapshotDate+' 现售价快照额外优惠 '+config.activityPricing.discountPercent+'% 预览；优惠券／码／会员积分可按原规则在结算时继续使用。','Activity price preview: '+config.activityPricing.discountPercent+'% off the '+snapshotDate+' listed-price snapshot. Eligible coupons, codes or member points apply later at checkout.');
    if(unavailableSelection)$('summary-note').textContent=t('当前选择含暂不可用商品，请更换平台或搭档后再核对。','Your selection includes an unavailable item. Change platform or companions before continuing.');
    if(live&&!unavailableSelection)$('summary-note').textContent=t('价格来自现售商品，购买前再次确认。原购物车优惠及交付要求继续适用。','Current listed items are rechecked before purchase. Existing cart discounts and delivery requirements apply.');
    $('mobile-summary-total').textContent=items.length+' '+t('项','items')+' · '+total(items);$('mobile-review').textContent=t('核对方案','Review lineup');$('mobile-review').disabled=!items.length||state.busy||state.submitted;
    root.querySelectorAll('input,select,button[data-view],button[data-toggle-product],button[data-toggle-bundle]').forEach(el=>el.disabled=state.busy||state.submitted||(el.dataset.toggleBundle!==undefined&&!offer(el.dataset.toggleBundle)));
    renderSeo();
    signal('render');
    if(focusId&&$(focusId)&&document.activeElement!==$(focusId))$(focusId).focus({preventScroll:true});
  }
  function renderReview(){
    $('review-items').innerHTML=review.map(item=>`<div class="fca-row"><img src="${escape(item.image)}" alt="" width="65" height="90"><div><h3>${escape(item.name)}</h3><p>${escape(meta(item))}<br>${escape(config.platforms[state.platform].label)} · ${escape(item.kind==='sbc'?t('SBC 代做服务','SBC completion service'):item.kind==='bundle'?t('固定球员组合','Fixed player bundle'):t('球员商品','Player item'))}</p>${item.included?`<p class="fca-review-includes">${escape(t('包含：','Includes: ')+item.included.map(x=>[x.name,x.rating,x.position,x.version].filter(Boolean).join(' · ')).join('; '))}</p>`:''}</div><strong class="fca-price">${display(item).originalText?'<del>'+escape(display(item).originalText)+'</del>':''}${escape(display(item).text)}</strong></div>`).join('');$('review-total').textContent=total(review);$('review-savings').innerHTML=savings(review);
  }
  function fingerprint(items){return JSON.stringify(items.map(item=>[item.offer.id,item.offer.group,item.offer.quantity,item.amount,display(item)]));}
  async function freshReview(items){
    if(!live)return items;
    adapter||=window.FCActivityHost.create(config);const quoted=await adapter.quote(items);
    for(const item of quoted)currentDisplays.set(item.offer.id,adapter.display(item));
    return quoted;
  }
  function status(text){$('review-status').textContent=text;}
  function signal(name,detail={}){root.dispatchEvent(new CustomEvent('fcactivity:'+name,{bubbles:true,detail:{view:state.view,platform:state.platform,preview:!live,language:state.lang,...detail}}));}
  async function openReview(override){
    if(state.busy||state.submitted)return;
    priceGeneration++;state.busy=true;render();
    try{review=await freshReview(Array.isArray(override)?override:selected());if(!review.length)return;reviewFingerprint=fingerprint(review);renderReview();$('continue-cart').hidden=true;$('submit-selection').hidden=false;$('submit-selection').disabled=false;status(live?t('商品与现价已重新确认。分别加入原购物车，原结算和交付说明继续适用。','Availability and prices refreshed. Items go into the existing cart with the original checkout and delivery requirements.'):t('本地体验价：按你指定的活动9折规则计算，尚未加购、下单或付款；券码与积分的抵扣需在原结算中核算。','Activity price preview: the configured 10% discount is applied. No cart, order or payment is created. Coupons and points are calculated by the existing checkout.'));$('review-dialog').showModal();signal('review',{ids:review.map(item=>item.offer.id),includeSbc:review.some(item=>item.kind==='sbc')});}
    catch(error){$('activity-message').hidden=false;$('activity-message').textContent=t('暂时无法确认当前商品，请到原商店核对后再试。','Unable to confirm the current items. Check the original shop before trying again.');}
    finally{state.busy=false;render();}
  }
  async function warmPrices(){
    if(!live)return;
    const generation=++priceGeneration;
    try{
      adapter||=window.FCActivityHost.create(config);
      const keys=state.view==='sbc'?[state.core,...state.companions]:state.view==='trio'?config.trio.ids:config.weekly.ids;
      await Promise.allSettled([...new Set([...keys,...config.bundles.ids])].map(async key=>{const item=(await adapter.quote([offer(key)]))[0];if(generation===priceGeneration)currentDisplays.set(item.offer.id,adapter.display(item));}));
      if(generation===priceGeneration&&!state.busy)render();
    }catch(error){/* Current prices remain unconfirmed until a successful catalog read. */}
  }
  async function submit(){
    if(state.busy||state.submitted)return;
    if(standalone){
      state.busy=true;render();
      try{
        const pageId='fc27-'+state.view;
        if(!runtimeClient||runtimeClient.pageId!==pageId){runtimeClient=window.CampaignStandalone.create({element:document.documentElement,pageId,activityId:'fc27-season2'});runtimeClient.pageId=pageId;}
        if(runtimeClient.pending?.unknown){await runtimeClient.lookup();status(runtimeClient.pending?.unknown?t('原操作结果待核对；已查询原操作，未重复提交。','Original operation remains unresolved; checked its status without resubmitting.'):runtimeClient.pending?.resolved?t('原操作结果已查明；未重复提交，可继续调整预览选择。','Original operation resolved without resubmitting. You may continue editing the preview selection.'):runtimeClient.describe());return;}
        await runtimeClient.load();
        await runtimeClient.select(review.map(item=>({product_key:'fc-'+item.key+'-'+state.platform,quantity:{value:String(item.offer.quantity),unit:'item'},attributes:[]})));
        status(runtimeClient.describe());
      }catch(error){status((['MAIN_INTEGRATION_REQUIRED','PRODUCT_UNAVAILABLE'].includes(error.code)?t('商品参数仍待核对，正式购买未开放；预览选择已保留，未加购、下单或付款。','Product mapping needs verification; purchasing is not open. Preview selection retained; no cart, order or payment created.'):t('运行时暂不可用或操作结果待核对：','Runtime unavailable or operation requires checking: '))+(['MAIN_INTEGRATION_REQUIRED','PRODUCT_UNAVAILABLE'].includes(error.code)?'':error.code||'RUNTIME_UNAVAILABLE'));}
      finally{state.busy=false;render();}
      return;
    }
    if(!live){status(t('这份搭配已确认，仅保存在当前体验中；没有写入网站购物车。','Lineup confirmed for this preview only. Nothing was added to the website cart.'));$('submit-selection').textContent=t('已确认 · 可继续调整','Confirmed · Keep exploring');return;}
    state.busy=true;$('submit-selection').disabled=true;render();
    try{
      const refreshed=await freshReview(review);
      if(fingerprint(refreshed)!==reviewFingerprint){review=refreshed;reviewFingerprint=fingerprint(review);renderReview();status(t('价格或商品选项已更新，请核对后再次确认。','Price or item options changed. Review the updated list, then confirm again.'));return;}
      batch||=adapter.batch();state.submitted=true;
      const outcomes=await batch.run(review,rows=>status(t('正在加入原购物车：','Adding to the existing cart: ')+rows.filter(row=>row.state==='confirmed').length+'/'+review.length));
      const all=outcomes.length===review.length&&outcomes.every(row=>row.state==='confirmed');
      signal('cart-result',{outcomes:outcomes.map(({id,state})=>({id,state})),complete:all});
      status(all?t('所选商品已逐项加入原购物车。请核对数量、现价与交付要求后结算。','Selected items were added to the existing cart. Review quantities, prices and delivery requirements before checkout.'):t('加购已停止：已确认项目保留，未重复提交。请先在购物车核对已加入商品，再决定后续操作。','Adding stopped. Confirmed items remain and were not replayed. Check the cart before taking further action.'));
      $('continue-cart').href=adapter.cartUrl;$('continue-cart').hidden=false;$('submit-selection').hidden=true;adapter.refreshHeader();
    }catch(error){status(t('当前商品暂时无法确认，未继续提交。请前往原商店核对。','The current items could not be confirmed. No further items were submitted; check the original shop.'));}
    finally{state.busy=false;render();if(!state.submitted)$('submit-selection').disabled=false;}
  }
  root.addEventListener('click',event=>{
    const view=event.target.closest('button[data-view]'),pick=event.target.closest('[data-toggle-product]'),bundle=event.target.closest('[data-toggle-bundle]');
    if(state.busy||state.submitted)return;
    if(view){state.view=view.dataset.view;state.bundles.clear();render();warmPrices();signal('view');}
    if(pick){const key=pick.dataset.toggleProduct;state.weekly.has(key)?state.weekly.delete(key):state.weekly.add(key);render();signal('selection',{ids:selected().map(item=>item.offer.id),action:'product_toggle'});}
    if(bundle)openReview([offer(bundle.dataset.toggleBundle)]);
  });
  root.addEventListener('change',event=>{
    if(state.busy||state.submitted)return;
    const el=event.target;
    if(el.name==='platform'){state.platform=el.value;currentDisplays.clear();}
    if(el.name==='core-mode')state.coreMode=el.value;
    if(el.id==='core-select'){state.core=el.value;state.companions=[...route(el.value).picks];}
    if(el.dataset.companionSlot!==undefined)state.companions[Number(el.dataset.companionSlot)]=el.value;
    render();
    warmPrices();
    signal('selection',{ids:selected().map(item=>item.offer.id),action:el.name||el.id||'companion',coreId:product(state.core).platforms[state.platform].id,includeSbc:state.coreMode==='service'});
  });
  $('lang-zh')?.addEventListener('click',()=>{if(!state.busy){state.lang='zh';render();if($('review-dialog').open)renderReview();}});$('lang-en')?.addEventListener('click',()=>{if(!state.busy){state.lang='en';render();if($('review-dialog').open)renderReview();}});
  $('review-selection').addEventListener('click',openReview);$('mobile-review').addEventListener('click',openReview);$('submit-selection').addEventListener('click',submit);
  root.querySelector('[data-close-dialog]').addEventListener('click',()=>{if(!state.busy)$('review-dialog').close();});$('review-dialog').addEventListener('cancel',event=>{if(state.busy)event.preventDefault();});
  if(standalone){$('activity-message').hidden=false;$('activity-message').textContent=t('独立活动预览：主站交易接入待完成；价格及优惠为快照。','Standalone preview: main-site integration pending. Prices and benefits are snapshots.');}
  render();warmPrices();signal('view');
})();
