(function(){
  'use strict';
  if(window.FCActivityAnalytics)return;
  const cfg=window.FC_ANALYTICS_CONFIG||{},catalog=window.FC_ACTIVITY_CONFIG||{},root=document.getElementById('fc-activity');
  if(!root)return;
  const preview=catalog.mode!=='live',local=/^(localhost|127\.0\.0\.1)$/.test(location.hostname);
  const uuid=()=>crypto.randomUUID(),safe=v=>typeof v==='string'&&/^[\w. /-]{1,100}$/.test(v)?v:undefined;
  let sdk=null,consent=false,state={},entry=null,seen=new Set(),last=performance.now(),active=0,observer,wasVisible=document.visibilityState==='visible';
  let session=uuid();function restoreSession(){try{session=sessionStorage.getItem('fc-analytics-session')||session;sessionStorage.setItem('fc-analytics-session',session);}catch{}}if(preview&&local)restoreSession();
  let testCsrf=null;const testMode=preview&&local&&new URLSearchParams(location.search).get('analytics_test')==='1';
  const journalKey='fc-activity-events-v1';
  function allowed(){return !preview&&cfg.enabled&&consent&&cfg.allowedHosts?.includes(location.hostname)&&sdk;}
  function properties(extra={}){
    const activity=cfg.registry?.find(a=>a.view===state.view);
    return {schema_version:1,activity_id:activity?.id||'unregistered',catalog_version:catalog.capturedAt,
      view:state.view,platform:state.platform||'ps',language:state.language||'zh',environment:preview?'preview':'production',
      device:matchMedia('(max-width: 700px)').matches?'mobile':'desktop',activity_visit_id:entry?.id,
      activity_session_id:session,source:entry?.source||'direct',campaign:entry?.campaign||'',...extra};
  }
  const permitted=new Set(['schema_version','activity_id','catalog_version','view','platform','language','environment','device','activity_visit_id','activity_session_id','source','campaign','product_id','product_ids','include_sbc','core_id','action','complete','confirmed_ids','failed_count','active_seconds','depth','target','event_id','distinct_id','token','$insert_id','$session_id','$window_id','$lib','$lib_version','$process_person_profile']);
  function clean(props){return Object.fromEntries(Object.entries(props).filter(([k])=>permitted.has(k)));}
  function emit(event,extra={}){
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
    observer=new IntersectionObserver(items=>{for(const item of items){const id=item.target.dataset.product;if(item.isIntersecting&&item.intersectionRatio>=.5&&!seen.has(id)&&document.visibilityState==='visible'){seen.add(id);emit('activity_product_view',{product_id:id});}}},{threshold:.5});
    root.querySelectorAll('[data-product]').forEach(el=>observer.observe(el));
  }
  root.addEventListener('fcactivity:view',e=>start(e.detail));
  root.addEventListener('fcactivity:render',e=>{state={...state,...e.detail};if(entry)observe();});
  root.addEventListener('fcactivity:selection',e=>{state={...state,...e.detail};emit('activity_selection',{product_ids:e.detail.ids||[],include_sbc:!!e.detail.includeSbc,core_id:e.detail.coreId,action:e.detail.action||'selection'});});
  root.addEventListener('fcactivity:review',e=>emit('activity_review',{product_ids:e.detail.ids||[],include_sbc:!!e.detail.includeSbc}));
  root.addEventListener('fcactivity:cart-result',e=>{const rows=e.detail.outcomes||[],confirmed=rows.filter(x=>x.state==='confirmed').map(x=>String(x.id));emit('activity_cart_result',{complete:!!e.detail.complete,confirmed_ids:confirmed,failed_count:rows.length-confirmed.length});if(!preview&&confirmed.length)emit('activity_add_to_cart',{product_ids:confirmed,complete:!!e.detail.complete});});
  root.addEventListener('click',e=>{const el=e.target.closest('button,a');if(!el||el.disabled)return;const id=el.id||el.dataset.toggleBundle||el.dataset.toggleProduct||el.dataset.view;if(id)emit('activity_click',{target:safe(id)||'control'});},true);
  let depth=0;window.addEventListener('scroll',()=>{const height=document.documentElement.scrollHeight-innerHeight,next=height<=0?100:Math.floor(scrollY/height*4)*25;if(next>depth){depth=next;emit('activity_scroll',{depth:Math.min(100,next)});}},{passive:true});
  setInterval(tick,10000);document.addEventListener('visibilitychange',()=>{tick();if(document.visibilityState==='hidden')flush();});window.addEventListener('pagehide',flush);
  if(testMode){const banner=document.createElement('p');banner.id='analytics-test-banner';banner.setAttribute('role','status');banner.style.cssText='position:fixed;top:0;left:0;right:0;padding:12px;background:#fff3cd;color:#382b00;z-index:10000;text-align:center';banner.textContent="PostHog test mode: anonymous test activity only; no cart or order is created.";document.body.append(banner);fetch('/analytics/api/connection').then(r=>r.json()).then(c=>{testCsrf=c.csrf;if(entry)start(state);}).catch(()=>{banner.textContent="Test connection unavailable. Use the configured analytics test service.";});}
  window.FCActivityAnalytics={
    connect(instance){if(!instance||typeof instance.capture!=='function')throw Error('PostHog SDK required');sdk=instance;},
    setConsent(value){consent=value===true;if(consent)restoreSession();active=0;last=performance.now();if(!consent){try{sdk?.opt_out_capturing();}catch{}}else if(sdk&&cfg.enabled&&!preview){try{sdk.opt_in_capturing({captureEventName:false});}catch{}if(entry)start(state);}},
    context(){if(!allowed()||!entry)return null;try{return {...properties(),distinct_id:sdk.get_distinct_id()};}catch{return null;}},
    sdkOptions:{api_host:cfg.apiHost,autocapture:false,capture_pageview:false,capture_pageleave:false,disable_session_recording:true,person_profiles:'never',opt_out_capturing_by_default:true,disable_surveys:true,advanced_disable_feature_flags:true,before_send(event){if(!consent||!event?.event?.startsWith('activity_'))return null;event.properties=clean(event.properties||{});return event;}},
    status(){return {preview,enabled:!!cfg.enabled,consent,connected:!!sdk,transmitting:!!allowed()};}
  };
})();
