(function(){
  'use strict';
  const config=window.FC_ACTIVITY_CONFIG&&window.FCActivityContent.publicConfig(window.FC_ACTIVITY_CONFIG),core=window.FCActivityCore,root=document.getElementById('fc-activity');
  if(!config||!core||!root)return;
  const $=id=>document.getElementById(id),escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const t=(zh,en)=>en,product=key=>config.products[key],route=key=>config.sbc.routes[key]||{picks:config.sbc.fallbackPicks,alternatives:[],label:{zh:'自选搭配方向',en:'Build your own pairing'}};
  const state={lang:'en',view:root.dataset.defaultView||config.defaultView||'sbc',platform:'ps',core:config.sbc.defaultId,coreMode:'owned',companions:[...route(config.sbc.defaultId).picks],weekly:new Set(),trio:new Set(),chosenCompanions:new Set(),bundles:new Set(),busy:false,submitted:false};
  const standalone=window.CampaignStandalone?.enabled(document.documentElement),live=config.mode==='live'&&!standalone;let runtimeClient=null,published=null,publishedReady=!standalone;let pageTimer,priceRetryTimer,configGeneration=0,priceRetryCount=0,priceRefreshPending=false;let adapter=null,review=[],reviewFingerprint='',batch=null,priceGeneration=0,unavailableSelection=false,nativeReview=null;const currentDisplays=new Map();
  const pricing=config.activityPricing||{},priced=pricing.enabled===true;let liveQuoter;
  const content=window.FCActivityContent.create(config,live),{words,heroes}=content;
  function pageState(view){
    if(!standalone)return 'active';if(!publishedReady)return 'loading';
    const page=published?.pages?.find(p=>p.activity_id==='fc27-season2'&&p.page_id==='fc27-'+view);
    if(!page||page.active!==true)return 'disabled';
    const start=page.starts_at?Date.parse(page.starts_at):null,end=page.ends_at?Date.parse(page.ends_at):null,now=Date.now();
    if((start!==null&&!Number.isFinite(start))||(end!==null&&!Number.isFinite(end))||(start!==null&&end!==null&&start>=end))return 'disabled';
    if(end!==null&&now>=end)return 'expired';if(start!==null&&now<start)return 'upcoming';return 'active';
  }
  function scoped(keys,view=state.view){
    const valid=(keys||[]).filter(key=>product(key));if(!standalone)return valid;
    if(pageState(view)!=='active')return [];
    const page=published.pages.find(p=>p.page_id==='fc27-'+view&&p.activity_id==='fc27-season2');
    return valid.filter(key=>{const ref='fc-'+key+'-'+state.platform,role=page.product_roles?.[ref],kind=product(key).kind;return page.product_keys?.includes(ref)&&(!role||({player:'player',bundle:'bundle',core:'sbc',companion:'player'})[role]===kind);});
  }
  function pageMessage(){return ({loading:t('正在读取已发布活动配置。','Loading published activity configuration.'),disabled:t('当前活动未开放。','This activity is not available.'),upcoming:t('活动尚未开始。','This activity has not started yet.'),expired:t('活动已结束。','This activity has ended.')})[pageState(state.view)];}
  function guards(){
    if(!standalone)return;
    const blocked=pageState(state.view)!=='active';
    root.querySelectorAll('[data-view]').forEach(el=>{const unavailable=pageState(el.dataset.view)!=='active';el.hidden=unavailable;el.setAttribute('aria-disabled',String(unavailable));if(el.tagName==='BUTTON')el.disabled=unavailable||state.busy;});
    root.querySelectorAll('input,select').forEach(el=>{if(blocked||((el.id==='core-select'||el.name==='core-mode')&&!state.core))el.disabled=true;});
    if(blocked){$('review-selection').disabled=true;$('mobile-review').disabled=true;$('submit-selection').disabled=true;}
  }
  function neutral(){
    if($('weekly-hero-preview'))$('weekly-hero-preview').hidden=true;
    for(const id of ['product-grid','sbc-lineup','sbc-options','bundle-grid','activity-guide'])$(id).innerHTML='';
    for(const id of ['sbc-controls','sbc-lineup','sbc-options'])$(id).hidden=true;
    $('summary-count').textContent='0';$('summary-total').textContent='—';$('mobile-summary-total').textContent='0';$('summary-savings').textContent='';$('summary-note').textContent=pageMessage();
    $('activity-offer').hidden=true;$('activity-message').hidden=false;$('activity-message').textContent=pageMessage();
    root.querySelectorAll('input,select,[data-toggle-product],[data-toggle-bundle]').forEach(el=>el.disabled=true);guards();
    if($('review-dialog').open)$('review-dialog').close();
  }
  function missingNativePrices(){
    if(!standalone||!publishedReady||pageState(state.view)!=='active')return false;
    const keys=state.view==='sbc'?[...state.companions,...(state.coreMode==='service'?[state.core]:[])]:state.view==='trio'?config.trio.ids:config.weekly.ids;
    return scoped([...keys,...bundleIdsForView()]).some(key=>product(key)?.preview_only&&!core.nativeModelOffer(product(key),state.platform,published,'fc27-'+state.view)?.price);
  }
  async function refreshPublishedPrices(){
    if(document.hidden||state.submitted)return;
    if(state.busy){schedulePriceRetry();return;}
    await publishedConfig(state.view,true);if(!state.busy)render();
  }
  function schedulePriceRetry(){
    clearTimeout(priceRetryTimer);priceRefreshPending=false;
    if(!missingNativePrices()){priceRetryCount=0;return;}
    if(document.hidden||state.submitted)return;
    const view=state.view,platform=state.platform,generation=configGeneration,delay=[1000,3000,8000,30000][Math.min(priceRetryCount++,3)];
    priceRefreshPending=true;priceRetryTimer=setTimeout(()=>{if(view===state.view&&platform===state.platform&&generation===configGeneration)refreshPublishedPrices();},delay);
  }
  function scheduleBoundary(){
    clearTimeout(pageTimer);
    const dates=[...(published?.pages||[]).flatMap(p=>[p.starts_at,p.ends_at]),published?.native_checkout?.valid_until,...Object.values(published?.seasonal_model_contracts||{}).flatMap(c=>(c.combinations||[]).map(x=>x.price?.expires_at))].filter(Boolean).map(Date.parse).filter(time=>Number.isFinite(time)&&time>Date.now());
    if(dates.length)pageTimer=setTimeout(()=>{if(!state.busy)render();priceRetryCount=0;refreshPublishedPrices();scheduleBoundary();},Math.min(2147483647,Math.max(1,Math.min(...dates)-Date.now()+1)));
  }
  async function publishedConfig(view=state.view,background=false){
    const generation=++configGeneration;clearTimeout(priceRetryTimer);let client,next;
    try{client=window.CampaignStandalone.create({element:document.documentElement,pageId:'fc27-'+view,activityId:'fc27-season2'});await client.load();next=client.config;}catch(error){next=error.code==='PAGE_UNAVAILABLE'?client?.config:background?published:null;}
    if(generation!==configGeneration)return;published=next;
    window.dispatchEvent(new CustomEvent('fcactivity:published',{detail:published}));
    publishedReady=true;
    scheduleBoundary();schedulePriceRetry();
  }
  function selected(){
    if(standalone&&pageState(state.view)!=='active')return [];
    try{const keys=state.view==='sbc'?[...(state.coreMode==='service'?[state.core]:[]),...state.companions.filter(key=>state.chosenCompanions.has(key))]:state.view==='trio'?[...state.trio]:[...state.weekly];const ids=[...new Set([...keys,...state.bundles])];const items=scoped(ids).map(key=>offer(key));unavailableSelection=items.some(item=>!item);return items.filter(Boolean);}catch(error){unavailableSelection=true;return [];}
  }
  function currentMedia(){return config.page_media?.['fc27-'+state.view]||published?.page_media?.['fc27-'+state.view]||{};}
  // The published page config carries operator-edited hero copy. Hero text is
  // built before that config arrives, so overlay it per render instead of
  // rebuilding the whole content object.
  function hero(view){
    const base=heroes[view],copy=published?.pages?.find(page=>page.page_id==='fc27-'+view&&page.activity_id==='fc27-season2')?.copy;
    if(!copy||typeof copy!=='object')return base;
    const applied={...base};
    for(const key of ['heading','intro','body']){
      const value=typeof copy[key]==='string'?copy[key].trim():'';
      if(value)applied[key]=[value,value];
    }
    return applied;
  }
  function imageOptions(key){const ref=currentMedia().cards?.[key];return ref?.url?{image:ref.url,alt:ref.alt}:{};}
  function money(amount,currency='USD'){return new Intl.NumberFormat(state.lang==='zh'?'zh-CN':'en-US',{style:'currency',currency}).format(amount/100);}
  function display(item){
    if(item?.native_offer){const q=item.native_offer;if(Date.parse(q.price.expires_at)<=Date.now())return {text:'Price unavailable',amount:null,currency:'USD'};const binding=q.bindings.find(b=>b.page_id==='fc27-'+state.view),baseAmount=q.price.base_minor,amount=binding?Math.round(baseAmount*(100-binding.off_percent)/100):baseAmount;return {text:money(amount),amount,baseAmount,discountAmount:baseAmount-amount,originalText:amount<baseAmount?money(baseAmount):'',currency:q.price.currency};}
    if(item?.preview_only)return {text:'Price unavailable',amount:null,currency:'USD'};
    if(!item)return {text:t('暂不可用','Unavailable'),amount:null,currency:'USD'};
    if(currentDisplays.has(item.offer.id))return currentDisplays.get(item.offer.id);
    if(!priced&&pricing.strategy==='native_discount_code')return {text:'Price confirmed at checkout',amount:null,currency:'USD'};
    if(live)return {text:t('现价确认中','Checking current price'),amount:null,currency:'USD'};
    const price=core.activityPrice(item.amount,config);
    return {...price,text:money(price.amount),originalText:price.discountAmount?money(price.baseAmount):'',currency:'USD'};
  }
  function savings(items){
    const values=items.map(display),currency=values[0]?.currency||'USD';
    if(!priced||!items.length||items.some(item=>item.preview_only&&!item.native_offer?.checkout_ready)||values.some(v=>v.baseAmount===undefined||v.amount===null||v.currency!==currency))return '';
    const base=values.reduce((sum,v)=>sum+v.baseAmount,0),saved=values.reduce((sum,v)=>sum+v.discountAmount,0);
    return '<span class="fca-price-breakdown"><span><span>Listed subtotal</span><span>'+escape(money(base,currency))+'</span></span><span class="fca-saving-row"><span>Activity savings</span><strong>−'+escape(money(saved,currency))+'</strong></span></span><small class="fca-price-terms">Activity code applied in the original cart. Final eligibility, fees and payable total are confirmed there.</small>';
  }
  function totalLabel(items){return savings(items)?'Item total with activity code':'Item total · confirm in cart';}

  function total(items){if(items.some(item=>item.preview_only&&!item.native_offer))return 'Price unavailable';const values=items.map(display),currency=values[0]?.currency||'USD';if(unavailableSelection||values.some(v=>v.amount===null||v.currency!==currency))return t('点击核对现价','Check current total');const amount=values.reduce((sum,v)=>sum+v.amount,0);return live&&adapter?adapter.total(amount):money(amount,currency);}
  function meta(p){return [p.rating,p.position,p.version].filter(Boolean).join(' · ');}
  function offer(key){try{const p=product(key);if(p?.preview_only){const native=standalone&&published?core.nativeModelOffer(p,state.platform,published,'fc27-'+state.view):p.native_offers?.[state.platform];return {...p,...(native?{native_offer:native}:{}),offer:{id:p.platforms?.[state.platform]?.id??null,group:native?.quantity.group??null,quantity:native?.quantity.value??null},amount:native?.price.base_minor??null};}return core.line(p,state.platform);}catch(error){return null;}}
  function picked(key){return selected().some(p=>p.key===key);}
  function card(key,{label='',fixed=false,owned=false}={}){
    if(!product(key))return '';const item=offer(key);
    return content.card(product(key),{lang:state.lang,label,fixed,owned,picked:picked(key),price:display(item).text,originalPrice:display(item).originalText,discountPercent:config.activityPricing?.discountPercent,unavailable:!item,platform:state.platform,nativeOffer:item?.native_offer??null,...imageOptions(key)});
  }
  function renderSeo(){
    const ids=standalone?scoped(state.view==='sbc'?[state.core,...state.companions]:state.view==='trio'?config.trio.ids:config.weekly.ids):state.view==='sbc'?[state.core,...state.companions]:undefined;
    if(standalone&&!ids.length){$('activity-guide').innerHTML='';return;}
    const page=content.page(state.view,state.lang,ids);
    $('activity-breadcrumb').innerHTML='<ol>'+page.breadcrumbs.map((x,i)=>'<li>'+(i<2?'<a href="'+escape(x.url)+'">'+escape(x.name)+'</a>':'<span aria-current="page">'+escape(x.name)+'</span>')+'</li>').join('')+'</ol>';
    $('activity-guide').innerHTML=page.guide;
    if(config.manageDocumentLanguage===false)return;
    document.title=page.title;
    for(const [selector,value] of [['meta[name="description"]',page.description],['link[rel="canonical"]',page.canonical],['meta[property="og:title"]',page.title],['meta[property="og:description"]',page.description],['meta[property="og:url"]',page.canonical],['meta[property="og:image"]',page.image],['meta[property="og:locale"]',state.lang==='zh'?'zh_CN':'en_US'],['meta[name="twitter:title"]',page.title],['meta[name="twitter:description"]',page.description],['meta[name="twitter:image"]',page.image]]){const el=document.head.querySelector(selector);if(el){if(el.tagName==='LINK')el.href=value;else el.content=value;}}
    const schema=$('fc-seo-jsonld');if(schema)schema.textContent=window.FCActivityContent.json(page.schema);
  }
  function guardPublishedEnglish(){
    const clean=window.FCActivityContent.englishText,names={weekly:'FC 27 Weekly Player Picks',sbc:'FC 27 SBC Companions',trio:'FC 27 Player Trio'},name=names[state.view]||'FC 27 Player Picks';
    document.title=clean(document.title,name+' | MMOEXP');
    for(const meta of document.head.querySelectorAll('meta[content]'))if(!clean(meta.content)){
      if(/title/.test(meta.getAttribute('property')||meta.name))meta.content=name+' | MMOEXP';
      else if(/description/.test(meta.getAttribute('property')||meta.name))meta.content='Review the exact player items and platform before continuing. Preview only.';
    }
    const heading=$('campaign-published-title');if(heading)heading.textContent=clean(heading.textContent,name);
    document.querySelectorAll('#campaign-published-details p').forEach(element=>{element.textContent=clean(element.textContent,'Preview only. Main-site integration is still required.');});
    document.querySelectorAll('script[type="application/ld+json"]').forEach(script=>{try{const data=JSON.parse(script.textContent),visit=node=>{if(!node||typeof node!=='object')return;for(const [key,value] of Object.entries(node)){if(key==='inLanguage')node[key]='en';else if(typeof value==='string'&&['name','headline','description','text','caption'].includes(key))node[key]=clean(value,key==='description'?'Preview only. Main-site integration is still required.':name);else if(value&&typeof value==='object')Array.isArray(value)?value.forEach(visit):visit(value);}};visit(data);script.textContent=JSON.stringify(data).replace(/</g,'\\u003c');}catch{}});
  }
  function renderStatic(){
    root.querySelectorAll('button[data-view],a[data-view]').forEach(el=>el.dataset.i18n=({weekly:'navWeekly',sbc:'navSbc',trio:'navTrio'})[el.dataset.view]);
    document.querySelectorAll('.fc-activity [data-i18n],.fca-demo-header [data-i18n],.fca-demo-footer [data-i18n],.fca-skip[data-i18n]').forEach(el=>{const pair=words[el.dataset.i18n];if(pair)el.textContent=pair[state.lang==='zh'?0:1].replaceAll('Star Performer',config.trio.series);if(el.dataset.i18n==='navTrio')el.innerHTML=escape(config.trio.series)+'<span class="fca-trio-label">'+escape(t(' 三人组',' Trio'))+'</span>';});
    document.querySelectorAll('.fc-activity [data-i18n-aria],.fca-demo-header [data-i18n-aria]').forEach(el=>{const pair=words[el.dataset.i18nAria];if(pair)el.setAttribute('aria-label',pair[state.lang==='zh'?0:1]);});
    $('lang-zh')?.setAttribute('aria-pressed',String(state.lang==='zh'));$('lang-en')?.setAttribute('aria-pressed',String(state.lang==='en'));
    const footer=document.querySelector('[data-i18n="demoFooter"]');
    if(standalone&&published&&footer)footer.textContent='Final prices and availability are confirmed in the original MMOEXP cart.';
    document.documentElement.lang='en';guardPublishedEnglish();
    root.querySelectorAll('button[data-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.view===state.view)));
    root.querySelectorAll('a[data-view]').forEach(el=>{if(el.dataset.view===state.view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  }
  function render(){
    const focusId=document.activeElement?.id;
    renderStatic();if(standalone&&pageState(state.view)!=='active'){neutral();return;}
    if(standalone){const cores=scoped(config.sbc.ids,'sbc');if(!cores.includes(state.core)){state.core=cores[0]||null;state.companions=[...route(state.core).picks];}state.companions=scoped(state.companions,'sbc');}
    $('activity-offer').textContent=content.promotionText(state.lang);$('activity-offer').hidden=!content.promotionText(state.lang);root.dataset.view=state.view;const h=hero(state.view);
    $('hero-kicker').textContent=h.kicker;$('hero-title').innerHTML=`<span>${escape(h.title[state.lang==='zh'?0:2])}</span><strong>${escape(h.title[state.lang==='zh'?1:3])}</strong>`;$('hero-body').textContent=t(...h.body);$('hero-cta').textContent=t(...h.cta);$('view-heading').textContent=t(...h.heading);$('view-intro').textContent=t(...h.intro);
    const media=currentMedia(),image=$('hero-image');image.src=media.hero_desktop?.url||(state.view==='trio'?config.trio.hero:'assets/'+h.image+'-hero.webp');if(media.hero_desktop?.alt)image.alt=window.FCActivityContent.englishText(media.hero_desktop.alt,'Campaign artwork');let source=image.parentElement.querySelector('source');if(!source){source=document.createElement('source');source.media='(max-width: 700px)';image.before(source);}source.srcset=media.hero_mobile?.url||(state.view==='trio'?(config.trio.heroMobile||config.trio.hero):'assets/'+h.image+'-hero-mobile.webp');
    const sbc=state.view==='sbc';$('sbc-controls').hidden=!sbc;$('sbc-lineup').hidden=!sbc;$('sbc-options').hidden=!sbc;$('product-grid').hidden=sbc;
    const preview=$('weekly-hero-preview');
    if(preview){
      const picks=scoped(config.weekly.ids).map(offer).map(item=>({item,price:display(item)})).filter(({item,price})=>item&&price.amount!==null&&price.discountAmount>0&&(!standalone||item.native_offer?.checkout_ready)&&(!item.native_offer||item.native_offer.bindings.some(binding=>binding.page_id==='fc27-weekly'&&binding.off_percent===10)));
      preview.hidden=!picks.length;
      if(picks.length){
        const cheapest=picks.reduce((lowest,pick)=>pick.price.amount<lowest.price.amount?pick:lowest);
        $('weekly-hero-price').textContent='From '+money(cheapest.price.amount,cheapest.price.currency);
        $('weekly-hero-platform').textContent=config.platforms[state.platform].label;
      }
    }
    if(sbc){
      $('product-grid').innerHTML='';
      const select=$('core-select');select.innerHTML=scoped(config.sbc.ids,'sbc').map(key=>`<option value="${escape(key)}" ${key===state.core?'selected':''}>${escape(product(key).title)}</option>`).join('');
      $('core-mode-help').textContent=state.coreMode==='owned'?t('核心不加入购买清单，也不计入金额。你只购买两位搭档。','Your owned core is excluded. Add the recommended companions you want to your lineup.'):t('清单包含所选 SBC 代做服务与两张搭档球员卡。服务资源与交付要求沿用原 SBC 订单说明。','SBC completion is included. Add any recommended companions you want separately. Existing SBC order scope, resources and delivery requirements apply.');
      const current=route(state.core),pool=scoped([...new Set([...current.picks,...current.alternatives])],'sbc');
      $('sbc-lineup').innerHTML=card(state.core,{label:t('你的 SBC 核心','YOUR SBC CORE'),fixed:true,owned:state.coreMode==='owned'})+state.companions.map((key,i)=>card(key,{label:t('搭档 '+(i+1),'COMPANION '+(i+1)),fixed:false})).join('');
      $('sbc-options').innerHTML=state.companions.map((key,i)=>`<div class="fca-companion-picker"><label for="companion-${i}">${escape(t('搭档 '+(i+1)+' · '+current.label.zh,'Companion '+(i+1)+' · '+current.label.en))}</label><select id="companion-${i}" data-companion-slot="${i}" name="companion${i+1}">${pool.map(option=>`<option value="${escape(option)}" ${option===key?'selected':''} ${option===state.companions[1-i]?'disabled':''}>${escape(product(option).title)}</option>`).join('')}</select></div>`).join('')+`<p class="fca-inline-note fca-pairing-note">${escape(t('这是搭配灵感，不承诺满化学。请核对游戏内位置、联赛与现有阵容。','Pairing ideas do not guarantee full chemistry. Check in-game positions, leagues and your existing lineup.'))}</p>`;
    }else {$('sbc-lineup').innerHTML='';$('sbc-options').innerHTML='';$('product-grid').innerHTML=scoped(state.view==='trio'?config.trio.ids:config.weekly.ids).map((key,i)=>card(key,{label:state.view==='trio'?config.trio.roles[i][state.lang]:config.weekly.edition[state.lang],fixed:false})).join('');}
    $('bundle-heading').textContent=t('也可以选商店现有阵容包。','Or start with an existing player bundle.');
    $('bundle-grid').innerHTML=scoped(bundleIdsForView()).map(key=>content.bundle(product(key),{lang:state.lang,price:display(offer(key)).text,originalPrice:display(offer(key)).originalText,discountPercent:config.activityPricing?.discountPercent,checked:state.bundles.has(key),platform:state.platform,nativeOffer:offer(key)?.native_offer??null,...imageOptions(key)})).join('');
    const items=selected(),snapshotDate=new Intl.DateTimeFormat(state.lang==='zh'?'zh-CN':'en-GB',{year:'numeric',month:'short',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(config.capturedAt));$('summary-count').textContent=String(items.length);$('summary-total').textContent=total(items);$('summary-note').textContent=t('精确商品分别列出，已有核心不重复购买；当前展示为 '+snapshotDate+' 公开价格快照。','Exact items are listed separately. Owned cores are excluded. Public price snapshot: '+snapshotDate+'.');$('review-selection').disabled=!items.length||state.busy||state.submitted;
    $('summary-savings').innerHTML=savings(items);root.querySelector('.fca-summary-total-label').textContent=totalLabel(items);if(review.length)root.querySelector('.fca-review-total > span').textContent=totalLabel(review);
    if(priced&&standalone&&!unavailableSelection)$('summary-note').textContent=t('价格按所选平台从主站实时读取；活动优惠码由原购物车自动应用，券与积分不可叠加。','Your selected items on '+config.platforms[state.platform].label+'. Owned SBC players are excluded from the total.');
    if(!priced&&pricing.strategy==='native_discount_code')$('summary-note').textContent='Select the exact items and platform. Campaign offer not configured. Any code must be accepted by the main-site checkout before payment; coupons and member points cannot be combined.';
    if(unavailableSelection)$('summary-note').textContent=t('当前选择含暂不可用商品，请更换平台或搭档后再核对。','Your selection includes an unavailable item. Change platform or companions before continuing.');
    if(live&&!unavailableSelection)$('summary-note').textContent=t('价格来自现售商品，购买前再次确认。原购物车优惠及交付要求继续适用。','Current listed items are rechecked before purchase. Existing cart discounts and delivery requirements apply.');
    $('mobile-summary-total').textContent=items.length+' '+t('项','items')+' · '+total(items);$('mobile-review').textContent=t('核对方案','Review lineup');$('mobile-review').disabled=!items.length||state.busy||state.submitted;
    root.querySelectorAll('input,select,button[data-view],button[data-toggle-product],button[data-toggle-bundle]').forEach(el=>el.disabled=state.busy||state.submitted||(el.dataset.toggleBundle!==undefined&&!offer(el.dataset.toggleBundle)));
    renderSeo();guards();
    if(standalone){$('activity-message').hidden=false;$('activity-message').textContent=priced?t('价格按所选平台实时读取；结算在原购物车完成，活动优惠码由购物车自动应用。','Prices are read live for the selected platform. Checkout continues in the original cart, which applies the activity code; coupons and points cannot be combined.'):t('独立活动预览：主站交易接入待完成；价格及优惠为快照。','Campaign checkout is not connected. Select items for review; final prices and any code must be confirmed before payment.');}
    if(missingNativePrices())$('activity-message').textContent=priceRefreshPending?'Checking current prices from the original store. Items without a current price cannot be purchased.':'Current prices are unavailable. Refresh this page to check again. Items without a current price cannot be purchased.';
    signal('render');
    if(focusId&&$(focusId)&&document.activeElement!==$(focusId))$(focusId).focus({preventScroll:true});
  }
  function renderReview(){
    $('review-items').innerHTML=review.map(item=>`<div class="fca-row">${(imageOptions(item.key).image||item.image)?`<img src="${escape(imageOptions(item.key).image||item.image)}" alt="" width="65" height="90">`:'<span>Image unavailable</span>'}<div><h3>${escape(item.name)}</h3><p>${escape(meta(item))}<br>${escape(config.platforms[state.platform].label)} · ${escape(item.kind==='sbc'?t('SBC 代做服务','SBC completion service'):item.kind==='bundle'?t('固定球员组合','Fixed player bundle'):t('球员商品','Player item'))}</p>${item.included?`<p class="fca-review-includes">${escape(t('包含：','Includes: ')+item.included.map(x=>[x.name,x.rating,x.position,x.version].filter(Boolean).join(' · ')).join('; '))}</p>`:''}</div><strong class="fca-price">${display(item).originalText?'<del>'+escape(display(item).originalText)+'</del>':''}${escape(display(item).text)}</strong></div>`).join('');$('review-total').textContent=total(review);$('review-savings').innerHTML=savings(review);$('review-savings').parentNode.insertBefore($('review-savings'),root.querySelector('.fca-review-total'));root.querySelector('.fca-review-total > span').textContent=totalLabel(review);
  }
  function fingerprint(items){return JSON.stringify(items.map(item=>[item.offer.id,item.offer.group,item.offer.quantity,item.amount,display(item)]));}
  function priceQuoter(){
    if(live){try{return adapter||=window.FCActivityHost.create(config);}catch{return null;}}
    if(!standalone||!priced)return null;
    if(liveQuoter!==undefined)return liveQuoter;
    try{liveQuoter=window.FCActivityHost.createLivePrice(config);}catch{liveQuoter=null;}
    return liveQuoter;
  }
  async function freshReview(items){
    const quoter=priceQuoter();if(!quoter)return items;
    // Per-item best effort: a listing whose live price cannot be read keeps its
    // published snapshot value and never blocks the reviewed checkout.
    return Promise.all(items.map(async item=>{
      try{if(item.preview_only)return item;const quoted=(await quoter.quote([item]))[0];currentDisplays.set(quoted.offer.id,quoter.display(quoted));return quoted;}
      catch{return item;}
    }));
  }
  function status(text){$('review-status').textContent=window.FCActivityContent.englishText(text,'The request could not be verified. No successful checkout is confirmed.');}
  function signal(name,detail={}){root.dispatchEvent(new CustomEvent('fcactivity:'+name,{bubbles:true,detail:{view:state.view,platform:state.platform,preview:!live,language:state.lang,...detail}}));}
  function nativeSelection(items){return {activity_id:'fc27-season2',page_id:'fc27-'+state.view,off_percent:10,lines:items.map(item=>({product_key:item.native_offer?.product_key||'fc-'+item.key+'-'+state.platform,quantity:item.native_offer?{value:item.native_offer.quantity.value,unit:item.native_offer.quantity.unit}:{value:String(item.offer.quantity),unit:'item'},attributes:item.native_offer?.attributes||[]}))};}
  function nativePlan(items){return window.CampaignNativeCodeHandoff.publishedPlan(published,nativeSelection(items),{origin:window.location.origin});}
  async function openReview(override){
    if(standalone&&pageState(state.view)!=='active'){render();return;}
    if(state.busy||state.submitted)return;
    if(standalone){state.busy=true;render();await publishedConfig();state.busy=false;if(pageState(state.view)!=='active'){render();return;}}
    priceGeneration++;state.busy=true;render();
    try{const items=Array.isArray(override)?override:selected();review=await freshReview(standalone?items.filter(item=>item&&scoped([item.key]).length):items);if(!review.length)return;reviewFingerprint=fingerprint(review);renderReview();$('continue-cart').hidden=true;$('submit-selection').hidden=false;nativeReview=null;try{if(standalone&&!review.some(item=>item.preview_only&&!item.native_offer?.checkout_ready))nativeReview=nativePlan(review);}catch{}$('submit-selection').disabled=(config.activityPricing?.strategy==='native_discount_code'&&!nativeReview)||review.some(item=>item.preview_only&&!item.native_offer?.checkout_ready);status(nativeReview?'Continue adds these exact items to the native cart and carries the configured code. The cart may automatically Apply it; final eligibility and totals are confirmed there. Coupons and points cannot be combined.':review.some(item=>item.preview_only&&!item.native_offer?.checkout_ready)?'Preview only. Price, quantity and purchase mapping require verification.':live?t('商品与现价已重新确认。分别加入原购物车，原结算和交付说明继续适用。','Availability and prices refreshed. Items go into the existing cart with the original checkout and delivery requirements.'):t('本地体验价：按你指定的活动9折规则计算，尚未加购、下单或付款；券码与积分的抵扣需在原结算中核算。','No price or discount is confirmed. Campaign checkout is not connected; nothing has been added to the cart.'));$('review-dialog').showModal();signal('review',{ids:review.map(item=>item.offer.id),includeSbc:review.some(item=>item.kind==='sbc')});}
    catch(error){$('activity-message').hidden=false;$('activity-message').textContent=t('暂时无法确认当前商品，请到原商店核对后再试。','Unable to confirm the current items. Check the original shop before trying again.');}
    finally{state.busy=false;render();}
  }
  const bundleIdsForView=()=>state.view==='weekly'?(config.weekly.bundleIds??config.bundles.ids):state.view==='sbc'?(config.sbc.bundleIds??config.bundles.ids):config.bundles.ids;

  async function warmPrices(){
    const quoter=priceQuoter();
    if(!quoter)return;
    const generation=++priceGeneration;
    const keys=state.view==='sbc'?[state.core,...state.companions]:state.view==='trio'?config.trio.ids:config.weekly.ids;
    await Promise.allSettled([...new Set([...keys,...bundleIdsForView()])].map(async key=>{
      let item;try{item=offer(key);}catch{return;}
      try{if(item.preview_only)return;const quoted=(await quoter.quote([item]))[0];if(generation===priceGeneration)currentDisplays.set(quoted.offer.id,quoter.display(quoted));}catch{}
    }));
    if(generation!==priceGeneration)return;
    if(!state.busy)render();
  }
  async function submit(){
    if(standalone&&(pageState(state.view)!=='active'||!review.length||scoped(review.map(item=>item.key)).length!==review.length)){render();return;}
    if(state.busy||state.submitted)return;
    if(standalone&&nativeReview){
      state.busy=true;render();
      try{
        await publishedConfig();
        if(pageState(state.view)!=='active'||scoped(review.map(item=>item.key)).length!==review.length){nativeReview=null;status('Published product selection changed. Close this review and check the selection again. No cart request was sent.');return;}
        if(review.some(item=>item.preview_only)){const refreshed=review.map(item=>item.preview_only?offer(item.key):item);if(refreshed.some(item=>!item||item.preview_only&&!item.native_offer?.checkout_ready)||fingerprint(refreshed)!==reviewFingerprint){nativeReview=null;status('Current quote or item mapping changed. Close this review and check the selection again. No cart request was sent.');return;}review=refreshed;}
        const fresh=nativePlan(review);
        if(fresh.signature!==nativeReview.signature){nativeReview=null;status('Published configuration changed. Close this review and check the selection again. No cart request was sent.');return;}
        const selection=nativeSelection(review),host=window.FCActivityHost.createNative(published,selection);
        const result=await window.CampaignNativeCodeHandoff.checkoutPublished({snapshot:published,selection,storage:window.sessionStorage,host,origin:window.location.origin,onCartConfirmed:({items})=>signal('cart-result',{outcomes:items.map(item=>({id:item.native_payload.id,state:'confirmed'})),complete:true}),navigate:url=>window.location.assign(url)});
        state.submitted=true;status(result.state==='navigation_attempted_not_applied'?'Native cart handoff attempted. Discount Apply and final totals are not confirmed by this page.':'The original native operation requires inspection. Do not submit again; check the original cart.');
      }catch(error){status((error.code||error.message||'NATIVE_HANDOFF_UNAVAILABLE')+'. No successful checkout is confirmed. Inspect the original operation before another attempt.');}
      finally{state.busy=false;render();}
      return;
    }
    if(priced){status('This selection has no published native offer for the current platform. No cart or discount-code request was sent; recheck the selection and the published scope before retrying.');return;}
    if(pricing.strategy==='native_discount_code'){status('Campaign checkout is not connected. No cart or discount-code request was sent.');return;}
    if(review.some(item=>item.preview_only&&!item.native_offer?.checkout_ready)){status('Preview only. No quote or purchase is available.');return;}
    if(standalone){
      state.busy=true;render();
      try{
        await publishedConfig();if(pageState(state.view)!=='active'||!review.length){render();return;}
        if(scoped(review.map(item=>item.key)).length!==review.length){$('review-dialog').close();$('activity-message').textContent=t('发布的商品选择已更新，请重新核对方案。','Published product selection changed. Review your lineup again.');return;}
        const pageId='fc27-'+state.view;
        if(!runtimeClient||runtimeClient.pageId!==pageId){runtimeClient=window.CampaignStandalone.create({element:document.documentElement,pageId,activityId:'fc27-season2'});runtimeClient.pageId=pageId;}
        if(runtimeClient.pending?.unknown){await runtimeClient.lookup();status(runtimeClient.pending?.unknown?t('原操作结果待核对；已查询原操作，未重复提交。','Original operation remains unresolved; checked its status without resubmitting.'):runtimeClient.pending?.resolved?t('原操作结果已查明；未重复提交，可继续调整预览选择。','Original operation resolved without resubmitting. You may continue editing the preview selection.'):runtimeClient.describe());return;}
        await runtimeClient.load();
        await runtimeClient.select(review.map(item=>({product_key:item.native_offer?.product_key||'fc-'+item.key+'-'+state.platform,quantity:item.native_offer?{value:item.native_offer.quantity.value,unit:item.native_offer.quantity.unit}:{value:String(item.offer.quantity),unit:'item'},attributes:item.native_offer?.attributes||[]})));
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
  root.addEventListener('click',async event=>{
    const previewPlatform=event.target.closest('[data-preview-platform]');if(previewPlatform&&!state.busy){state.platform=previewPlatform.dataset.previewPlatform;const radio=root.querySelector('input[name=platform][value='+state.platform+']');if(radio)radio.checked=true;render();return;}
    const view=event.target.closest(standalone?'button[data-view],a[data-view]':'button[data-view]'),pick=event.target.closest('[data-toggle-product]'),bundle=event.target.closest('[data-toggle-bundle]');
    if(state.busy||state.submitted)return;
    if(view&&standalone){event.preventDefault();if(pageState(view.dataset.view)!=='active'){render();return;}state.busy=true;render();await publishedConfig(view.dataset.view);state.busy=false;if(pageState(view.dataset.view)!=='active'){render();return;}if(view.tagName==='A'){window.location.href=view.href;return;}}
    if(view){state.view=view.dataset.view;state.bundles.clear();render();warmPrices();signal('view');}
    if(standalone&&pageState(state.view)!=='active'){render();return;}
    if(pick){const key=pick.dataset.toggleProduct;if(standalone&&!scoped([key]).length)return;const chosen=state.view==='trio'?state.trio:state.view==='sbc'?state.chosenCompanions:state.weekly;chosen.has(key)?chosen.delete(key):chosen.add(key);render();signal('selection',{ids:selected().map(item=>item.offer.id),action:'product_toggle'});}
    if(bundle&&(!standalone||scoped([bundle.dataset.toggleBundle]).length))openReview([offer(bundle.dataset.toggleBundle)]);
  });
  root.addEventListener('change',event=>{
    if(state.busy||state.submitted)return;
    if(standalone&&pageState(state.view)!=='active'){render();return;}
    const el=event.target;
    if(el.name==='platform'){state.platform=el.value;currentDisplays.clear();priceRetryCount=0;}
    if(el.name==='core-mode')state.coreMode=el.value;
    if(el.id==='core-select'){state.core=el.value;state.companions=[...route(el.value).picks];state.chosenCompanions.clear();}
    if(el.dataset.companionSlot!==undefined){const slot=Number(el.dataset.companionSlot),previous=state.companions[slot],chosen=state.chosenCompanions.delete(previous);state.companions[slot]=el.value;if(chosen)state.chosenCompanions.add(el.value);}
    render();
    warmPrices();schedulePriceRetry();
    signal('selection',{ids:selected().map(item=>item.offer.id),action:el.name||el.id||'companion',coreId:product(state.core)?.platforms?.[state.platform]?.id,includeSbc:state.coreMode==='service'});
  });
  $('review-selection').addEventListener('click',openReview);$('mobile-review').addEventListener('click',openReview);$('submit-selection').addEventListener('click',submit);
  root.querySelector('[data-close-dialog]').addEventListener('click',()=>{if(!state.busy)$('review-dialog').close();});$('review-dialog').addEventListener('cancel',event=>{if(state.busy)event.preventDefault();});
  if(standalone){$('activity-message').hidden=false;$('activity-message').textContent=priced?t('价格按所选平台实时读取；结算在原购物车完成，活动优惠码由购物车自动应用。','Prices are read live for the selected platform. Checkout continues in the original cart, which applies the activity code; coupons and points cannot be combined.'):t('独立活动预览：主站交易接入待完成；价格及优惠为快照。','Campaign checkout is not connected. Select items for review; final prices and any code must be confirmed before payment.');}
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(priceRetryTimer);return;}if(missingNativePrices()){priceRetryCount=0;refreshPublishedPrices();}});
  document.querySelectorAll('.fca-language,#lang-zh,#lang-en').forEach(element=>element.remove());
  document.documentElement.lang='en';root.dataset.defaultLanguage='en';
  render();if(standalone)publishedConfig().then(()=>{render();warmPrices();signal('view');});else{warmPrices();signal('view');}
})();
