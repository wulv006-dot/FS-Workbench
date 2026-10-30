(function(){
  'use strict';
  if(window.FCActivityAnalytics)return;
  const cfg=window.FC_ANALYTICS_CONFIG||{},catalog=window.FC_ACTIVITY_CONFIG||{},root=document.getElementById('fc-activity');
  if(!root)return;
  let published=null;const formal=location.origin==='https://www.mmoexp.com'&&location.pathname==='/events/seasonal/'&&(!document.documentElement.dataset.campaignRuntime||document.documentElement.dataset.campaignRuntime==='/events/');
  let preview=catalog.mode!=='live';const local=/^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  const uuid=()=>crypto.randomUUID(),safe=v=>typeof v==='string'&&/^[\w. /-]{1,100}$/.test(v)?v:undefined;
  let sdk=null,consent=false,state={},entry=null,seen=new Set(),last=performance.now(),active=0,observer,wasVisible=document.visibilityState==='visible';
  let session=uuid();function restoreSession(){try{const stored=sessionStorage.getItem('fc-analytics-session');session=stored&&(!formal||/^[a-f0-9-]{36}$/i.test(stored))?stored:session;sessionStorage.setItem('fc-analytics-session',session);}catch{}}if(preview&&local)restoreSession();
  let testCsrf=null;const testMode=preview&&local&&new URLSearchParams(location.search).get('analytics_test')==='1';
  const journalKey='fc-activity-events-v1';
  const params=new URLSearchParams(location.search),verification=formal&&params.get('analytics_test')==='1'?( /^[a-f0-9-]{36}$/i.test(params.get('analytics_run')||'')?params.get('analytics_run'):uuid()):null;
  const liveSeasonal=()=>formal&&cfg.seasonalEnabled===true&&published&&Date.parse(published.halloween.starts_at)<=Date.now()&&Date.now()<=Date.parse(published.halloween.ends_at);
  function allowed(){return !preview&&(formal?liveSeasonal():cfg.enabled)&&consent&&cfg.allowedHosts?.includes(location.hostname)&&sdk;}
  function properties(extra={}){
    const activity=cfg.registry?.find(a=>a.view===state.view);
    return {schema_version:1,activity_id:activity?.id||'unregistered',catalog_version:published?.release_id||catalog.capturedAt,...(published?{page_id:'seasonal-vault',release_id:published.release_id,config_hash:published.config_hash,...(state.game_id?{game_id:state.game_id}:{}),...(verification?{test_run_id:verification}:{} )}:{}),
      view:state.view,platform:state.platform||(published?'unknown':'ps'),language:state.language||(published?'en':'zh'),environment:preview?'preview':verification?'test':'production',
      device:matchMedia('(max-width: 700px)').matches?'mobile':'desktop',activity_visit_id:entry?.id,
      activity_session_id:session,source:entry?.source||'direct',campaign:entry?.campaign||'',...extra};
  }
  const permitted=new Set(['page_id','game_id','model_id','off_percent','discount_code','slot','release_id','config_hash','server_id','quantity_value','quantity_unit','test_run_id','schema_version','activity_id','catalog_version','view','platform','language','environment','device','activity_visit_id','activity_session_id','source','campaign','product_id','product_ids','include_sbc','core_id','action','complete','confirmed_ids','failed_count','active_seconds','depth','target','event_id','distinct_id','token','$insert_id','$session_id','$window_id','$lib','$lib_version','$process_person_profile']);
  function clean(props){return Object.fromEntries(Object.entries(props).filter(([k])=>permitted.has(k)));}
  function emit(event,extra={}){
    if(!entry)return; // Do not emit a restored-scroll event before the activity visit exists.
    const row={event,timestamp:new Date().toISOString(),properties:clean(properties({...extra,event_id:uuid()}))};
    if(preview&&local&&cfg.localPreviewJournal){try{const rows=JSON.parse(localStorage.getItem(journalKey)||'[]');rows.push(row);localStorage.setItem(journalKey,JSON.stringify(rows.slice(-1500)));}catch{/* Storage denial must not interrupt buying. */}}
    if(testMode&&testCsrf)fetch('/analytics/api/test-event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...row,csrf:testCsrf}),keepalive:true}).then(r=>{const banner=document.getElementById('analytics-test-banner');if(banner)banner.textContent=r.ok?"PostHog test event sent. Live shopping and payment remain disabled.":"PostHog test event is unconfirmed. Check the dashboard connection status.";}).catch(()=>{});
    if(allowed()){try{sdk.capture(event,row.properties);}catch{/* Analytics failure cannot block checkout. */}}
    window.dispatchEvent(new CustomEvent('fcactivity:analytics-debug',{detail:row}));
  }
  function tick(){const now=performance.now();if(wasVisible)active+=Math.min(now-last,15000);last=now;wasVisible=document.visibilityState==='visible';}
  function flush(){tick();if(active>=1000){emit('activity_engaged',{active_seconds:Math.floor(active/1000)});active=0;}}
  function start(detail){
    flush();state={...state,...detail};seen=new Set();active=0;last=performance.now();
    const params=new URLSearchParams(location.search),utm=safe(params.get('utm_source'));
    let source=utm||'direct';try{if(!utm&&document.referrer){const host=new URL(document.referrer).hostname;source=host===location.hostname?'internal':/(^|\.)(google|bing)\./.test(host)?'organic':'referral';}}catch{}
    depth=0;entry={id:uuid(),source,campaign:safe(params.get('utm_campaign'))||''};
    emit('activity_view');observe();
  }
  function observe(){
    observer?.disconnect();if(!window.IntersectionObserver)return;
    observer=new IntersectionObserver(items=>{for(const item of items){const id=item.target.dataset.product,exposure=published?[id,item.target.dataset.slot,item.target.dataset.offPercent].join(':'):id;if(published&&(!item.target.isConnected||item.target.dataset.releaseId!==published.release_id||item.target.dataset.configHash!==published.config_hash))continue;if(item.isIntersecting&&item.intersectionRatio>=.5&&!seen.has(exposure)&&document.visibilityState==='visible'){seen.add(exposure);emit('activity_product_view',{product_id:id,...(published?offerFields(item.target.dataset):{})});}}},{threshold:.5});
    root.querySelectorAll('[data-product]').forEach(el=>observer.observe(el));
  }
  root.addEventListener('fcactivity:view',e=>start(e.detail));
  root.addEventListener('fcactivity:render',e=>{state={...state,...e.detail};if(entry)observe();});
  root.addEventListener('fcactivity:selection',e=>{state={...state,...e.detail};emit('activity_selection',{product_ids:e.detail.ids||[],include_sbc:!!e.detail.includeSbc,core_id:e.detail.coreId,action:e.detail.action||'selection'});});
  root.addEventListener('fcactivity:review',e=>emit('activity_review',{product_ids:e.detail.ids||[],include_sbc:!!e.detail.includeSbc}));
  root.addEventListener('fcactivity:cart-result',e=>{const rows=e.detail.outcomes||[],confirmed=rows.filter(x=>x.state==='confirmed').map(x=>String(x.id));emit('activity_cart_result',{complete:!!e.detail.complete,confirmed_ids:confirmed,failed_count:rows.length-confirmed.length});if(!preview&&confirmed.length)emit('activity_add_to_cart',{product_ids:confirmed,complete:!!e.detail.complete});});
  root.addEventListener('click',e=>{const el=e.target.closest('button,a');if(!el||el.disabled)return;const id=el.id||el.dataset.toggleBundle||el.dataset.toggleProduct||el.dataset.view||el.dataset.gameCard||el.dataset.randomReveal||el.dataset.buySlot;if(id)emit('activity_click',{target:safe(id)||'control'});},true);
  let depth=0;window.addEventListener('scroll',()=>{const height=document.documentElement.scrollHeight-innerHeight,next=height<=0?100:Math.floor(scrollY/height*4)*25;if(next>depth){depth=next;emit('activity_scroll',{depth:Math.min(100,next)});}},{passive:true});
  setInterval(tick,10000);document.addEventListener('visibilitychange',()=>{tick();if(document.visibilityState==='hidden')flush();});window.addEventListener('pagehide',flush);
  if(testMode){const banner=document.createElement('p');banner.id='analytics-test-banner';banner.setAttribute('role','status');banner.style.cssText='position:fixed;top:0;left:0;right:0;padding:12px;background:#fff3cd;color:#382b00;z-index:10000;text-align:center';banner.textContent="PostHog test mode: anonymous test activity only; no cart or order is created.";document.body.append(banner);fetch('/analytics/api/connection').then(r=>r.json()).then(c=>{testCsrf=c.csrf;if(entry)start(state);}).catch(()=>{banner.textContent="Test connection unavailable. Use the configured analytics test service.";});}

  // Only the current formal route may enable this lane. Commerce mode stays untouched.
  const numberId=v=>typeof v==='string'&&/^[1-9]\d{0,19}$/.test(v);
  function offerFields(raw={}){
    const game_id=String(raw.game_id||raw.gameId||''),model_id=String(raw.model_id||raw.modelId||''),off_percent=Number(raw.off_percent||raw.offPercent),slot=raw.slot;
    if(!published||!numberId(game_id)||!published.halloween.games.some(g=>String(g.admin_game_id)===game_id))return {};
    const fields={game_id};
    if(numberId(model_id)&&published.products.some(p=>p.product_ref?.game_id===game_id&&p.product_ref?.model_id===model_id))fields.model_id=model_id;
    if([8,10,15].includes(off_percent))fields.off_percent=off_percent;
    if(['fixed','random-1','random-2'].includes(slot))fields.slot=slot;
    if(numberId(String(raw.product_id||''))&&published.products.some(p=>p.product_ref?.game_id===game_id&&p.product_ref?.model_id===model_id&&p.product_ref?.goods_id===String(raw.product_id)))fields.product_id=String(raw.product_id);
    if(typeof raw.discount_code==='string'&&raw.discount_code!=='CLAIM_REQUIRED'&&/^[A-Za-z0-9_-]{1,128}$/.test(raw.discount_code))fields.discount_code=raw.discount_code;
    if(numberId(String(raw.server_id||'')))fields.server_id=String(raw.server_id);
    if(typeof raw.quantity_value==='string'&&/^\d{1,12}(?:\.\d{1,6})?$/.test(raw.quantity_value))fields.quantity_value=raw.quantity_value;
    if(typeof raw.quantity_unit==='string'&&/^[A-Za-z]{1,20}$/.test(raw.quantity_unit))fields.quantity_unit=raw.quantity_unit;
    return fields;
  }
  function trackOffer(action,raw){
    if(!liveSeasonal()||!['exposure','game_select','offer_reveal','product_select','options_ready','cart_confirmed','cart_unconfirmed'].includes(action))return;
    const fields=offerFields(raw);if(!fields.game_id)return;
    state.game_id=fields.game_id;
    if(action==='cart_confirmed'){
      if(!fields.product_id||!fields.model_id||!fields.discount_code)return;
      emit('activity_cart_result',{...fields,complete:true,confirmed_ids:[fields.product_id],failed_count:0});
      emit('activity_add_to_cart',{...fields,product_ids:[fields.product_id],complete:true});return;
    }
    if(action!=='exposure')emit('activity_selection',{...fields,action,product_ids:fields.product_id?[fields.product_id]:[]});
    if(action==='options_ready')emit('activity_review',fields);
    if(action==='exposure'||action==='offer_reveal'||action==='product_select'){
      const element=document.querySelector('[data-offer-slot="'+fields.slot+'"]');
      if(element&&fields.model_id){element.dataset.product='model-'+fields.model_id;Object.assign(element.dataset,{gameId:fields.game_id,modelId:fields.model_id,offPercent:String(fields.off_percent),slot:fields.slot,releaseId:published.release_id,configHash:published.config_hash});observe();}
    }
  }
  const consentKey='mmoexp-event-analytics-consent-v1';let transportOptIn=false,distinct=uuid();
  // Reuse the existing public Capture API transport, with no SDK autocapture/replay.
  const transport={capture(event,props){
    if(!transportOptIn||!allowed())return;
    distinct='seasonal-'+props.activity_session_id;
    const properties={...clean(props),$process_person_profile:false,$geoip_disable:true};
    const payload={api_key:cfg.projectToken,event,distinct_id:distinct,uuid:props.event_id,timestamp:new Date().toISOString(),properties};
    fetch('https://us.i.posthog.com/i/v0/e/',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'omit',referrerPolicy:'no-referrer',body:JSON.stringify(payload),keepalive:true}).then(r=>{
      window.dispatchEvent(new CustomEvent('seasonal:analytics-receipt',{detail:{event_id:props.event_id,status:r.ok?'accepted':'rejected',http:r.status}}));
    }).catch(()=>window.dispatchEvent(new CustomEvent('seasonal:analytics-receipt',{detail:{event_id:props.event_id,status:'unknown'}})));
  },opt_in_capturing(){transportOptIn=true;},opt_out_capturing(){transportOptIn=false;},get_distinct_id(){return distinct;}};
  function consentControls(){
    if(document.getElementById('seasonal-analytics-choice'))return;
    const section=document.createElement('section');section.id='seasonal-analytics-choice';section.className='analytics-choice';section.setAttribute('aria-label','Anonymous analytics preferences');
    const label=document.createElement('p');label.textContent='Allow anonymous usage data to help improve this event? Your choice does not affect offers or purchases.';
    const yes=document.createElement('button'),no=document.createElement('button');yes.type=no.type='button';yes.textContent='Allow analytics';no.textContent='No thanks';
    const choose=value=>{window.FCActivityAnalytics.setConsent(value);try{localStorage.setItem(consentKey,value?'granted':'denied');}catch{}section.hidden=true;};
    yes.addEventListener('click',()=>choose(true));no.addEventListener('click',()=>choose(false));section.append(label,yes,no);
    const header=document.querySelector('.site-header');if(header?.after)header.after(section);else document.querySelector('.site-footer')?.before(section);
    const settings=document.createElement('button');settings.type='button';settings.className='analytics-settings';settings.textContent='Analytics preferences';settings.addEventListener('click',()=>{section.hidden=false;yes.focus();});document.querySelector('.site-footer')?.append(settings);
    try{const saved=localStorage.getItem(consentKey);if(saved==='granted'||saved==='denied'){section.hidden=true;window.FCActivityAnalytics.setConsent(saved==='granted');}}catch{}
  }
  window.addEventListener('seasonal-published-catalog',e=>{
    const next=e.detail,page=Array.isArray(next?.pages)?next.pages.find(p=>p?.page_id==='seasonal-vault'&&p.activity_id==='mmoexp-seasonal'):null;
    if(!formal)return;
    const startAt=Date.parse(next?.halloween?.starts_at),endAt=Date.parse(next?.halloween?.ends_at),now=Date.now();
    if(cfg.seasonalEnabled!==true||!cfg.projectToken||next?.schema_version!==1||page?.active!==true||next?.halloween?.status!=='configured'||!/^campaign-preview-\d+$/.test(next?.release_id||'')||!/^[a-f0-9]{64}$/.test(next?.config_hash||'')||!Number.isFinite(startAt)||!Number.isFinite(endAt)||startAt>now||endAt<now){
      // Revoke the old publication immediately; never flush it after a pause,
      // retain stale observer context, or fall back to the general enabled flag.
      published=null;preview=true;entry=null;state={};active=0;last=performance.now();seen=new Set();observer?.disconnect();transport.opt_out_capturing();return;
    }
    if(published?.release_id===next.release_id&&published?.config_hash===next.config_hash)return;
    flush();published=next;preview=false;entry=null;state={view:'seasonal',platform:'unknown',language:'en'};window.FCActivityAnalytics.connect(transport);window.FCActivityAnalytics.setConsent(consent);start(state);consentControls();
    if(verification&&!document.getElementById('seasonal-analytics-test')){const note=document.createElement('p');note.id='seasonal-analytics-test';note.textContent='Analytics verification mode: these events are labeled as test data.';document.querySelector('main')?.prepend(note);}
  });
  window.addEventListener('seasonal:model-buy',e=>trackOffer('product_select',e.detail));

  window.FCActivityAnalytics={
    offer:trackOffer,
    connect(instance){if(!instance||typeof instance.capture!=='function')throw Error('PostHog SDK required');sdk=instance;},
    setConsent(value){consent=value===true;if(consent)restoreSession();active=0;last=performance.now();if(!consent){try{sdk?.opt_out_capturing();}catch{}}else if(sdk&&(formal?liveSeasonal():cfg.enabled)&&!preview){try{sdk.opt_in_capturing({captureEventName:false});}catch{}if(entry)start(state);}},
    context(){if(!allowed()||!entry)return null;try{return {...properties(),distinct_id:sdk.get_distinct_id()};}catch{return null;}},
    sdkOptions:{api_host:cfg.apiHost,autocapture:false,capture_pageview:false,capture_pageleave:false,disable_session_recording:true,person_profiles:'never',opt_out_capturing_by_default:true,disable_surveys:true,advanced_disable_feature_flags:true,before_send(event){if(!consent||!event?.event?.startsWith('activity_'))return null;event.properties=clean(event.properties||{});return event;}},
    status(){return {preview,enabled:!!(formal?liveSeasonal():cfg.enabled),consent,connected:!!sdk,transmitting:!!allowed()};}
  };
})();
