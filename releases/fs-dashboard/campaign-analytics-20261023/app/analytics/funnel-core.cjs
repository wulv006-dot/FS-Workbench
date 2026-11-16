(function(root,factory){if(typeof module==='object')module.exports=factory();else root.ActivityFunnel=factory();})(typeof globalThis==='object'?globalThis:this,function(){
  'use strict';
  const fcActivities=['fc27-season2','fc27-weekly','fc27-sbc','fc27-trio'];
  const canonicalActivity=id=>fcActivities.includes(id)?'fc27-season2':id;
  const activityMatches=(selected,id)=>!selected||selected==='all'||canonicalActivity(selected)===canonicalActivity(id);
  const steps=['activity_view','activity_product_view','activity_add_to_cart','activity_begin_checkout','activity_purchase'];
  const labels=['访问活动页','看到商品','加购成功','进入结账','支付成功'];
  const templates={commerce:{name:'商品购买',steps,labels},prediction:{name:'竞猜参与',steps:['prediction_match_view','prediction_started','prediction_accepted'],labels:['看到赛事','开始预测','预测保存成功']},reward:{name:'中奖奖励核销',steps:['prediction_reward_eligible','prediction_reward_issued','prediction_coupon_redeemed'],labels:['中奖可领资格','奖励真实到账','优惠券真实核销']}};
  function summarize(events,filter={}){
    const template=templates[filter.template]||templates.commerce,{steps,labels}=template,windowHours=Number(filter.windowHours)|| (filter.template==='reward'?720:24);
    if(!Number.isFinite(windowHours)||windowHours<1||windowHours>720)throw Error('转化窗口需为1–720小时');
    const groups=new Map(),ids=new Set();
    for(const e of events){const p=e.properties||{},t=Date.parse(e.timestamp);const journey=filter.template==='reward'?p.reward_journey_id:p.activity_visit_id;if(!Number.isFinite(t)||!journey||!p.activity_id||!steps.includes(e.event)&&!['activity_engaged','activity_click','activity_selection','activity_review','activity_cart_result','activity_coupon_claim'].includes(e.event))continue;
      if(p.event_id&&ids.has(p.event_id))continue;if(p.event_id)ids.add(p.event_id);
      if(filter.match&&filter.match!=='all'&&p.match_id!==filter.match)continue;
      if((filter.template==='prediction'||filter.template==='reward')&&!p.match_id)continue;
      const key=p.activity_id+':'+journey+':'+(filter.template==='prediction'||filter.template==='reward'?(p.match_id||'missing'): '');if(!groups.has(key))groups.set(key,[]);groups.get(key).push({...e,t});}
    const seasonalOffers=new Map(),journeys=new Map(),seasonalTotals=Object.fromEntries(['gameViews','revealed','selected','reviewed','cart','unconfirmed'].map(k=>[k,new Set()]));
    const counts=steps.map(()=>0),products=new Map(),sources=new Map(),daily=new Map(),visitors=new Set(),clickers=new Set();let active=0,revenue=0,orders=new Set(),reviews=0,sbcSelections=0,couponClaims=0,couponReused=0,visits=0;
    for(const rows of groups.values()){
      rows.sort((a,b)=>a.t-b.t);const first=rows.find(r=>r.event===steps[0]);if(!first)continue;const p=first.properties,date=first.timestamp.slice(0,10);
      if(!activityMatches(filter.activity,p.activity_id))continue;
      if(filter.device&&filter.device!=='all'&&p.device!==filter.device)continue;
      if(filter.platform&&filter.platform!=='all'&&p.platform!==filter.platform)continue;
      if(filter.source&&filter.source!=='all'&&p.source!==filter.source)continue;
      if(filter.from&&date<filter.from||filter.to&&date>filter.to)continue;
      let windowRows=rows.filter(r=>r.t>=first.t&&r.t<=first.t+windowHours*3600000);const visitor=p.distinct_id||p.activity_session_id||p.activity_visit_id||p.reward_journey_id;
      if(filter.game&&filter.game!=='all'){if(!windowRows.some(r=>String(r.properties.game_id)===filter.game))continue;windowRows=windowRows.filter(r=>r===first||String(r.properties.game_id)===filter.game);}
      visits++;visitors.add(visitor);const day=daily.get(date)||{date,visits:0,paid:0};day.visits++;daily.set(date,day);
      const source=sources.get(p.source||'direct')||{name:p.source||'direct',visits:0,paid:0};source.visits++;sources.set(source.name,source);
      let last=first.t,matched=0;
      for(let i=0;i<steps.length;i++){const row=windowRows.find(r=>r.t>=last&&r.event===steps[i]);if(!row)break;counts[i]++;matched++;last=row.t;}
      if(matched===steps.length){source.paid++;day.paid++;}
      if(windowRows.some(r=>r.event==='activity_review'))reviews++;
      if(windowRows.some(r=>r.event==='activity_coupon_claim'&&r.properties.coupon_state==='claimed'&&r.properties.coupon_reused!==true))couponClaims++;
      if(windowRows.some(r=>r.event==='activity_coupon_claim'&&r.properties.coupon_state==='claimed'&&r.properties.coupon_reused===true))couponReused++;
      if(windowRows.some(r=>r.event==='activity_selection'&&r.properties.include_sbc))sbcSelections++;
      const exposed=new Set(),clicked=new Set();
      for(const r of windowRows){const q=r.properties;
        if(q.activity_id==='mmoexp-seasonal'&&/^\d{1,20}$/.test(q.game_id||'')){
          const j=journeys.get(q.game_id)||{gameId:q.game_id,visits:new Set(),revealed:new Set(),selected:new Set(),reviewed:new Set(),cart:new Set(),unconfirmed:new Set()};
          j.visits.add(p.activity_visit_id);
          if(r.event==='activity_selection'&&q.action==='offer_reveal')j.revealed.add(p.activity_visit_id);
          if(r.event==='activity_selection'&&q.action==='product_select')j.selected.add(p.activity_visit_id);
          if(r.event==='activity_review')j.reviewed.add(p.activity_visit_id);
          if(r.event==='activity_add_to_cart'&&q.complete===true)j.cart.add(p.activity_visit_id);
          if(r.event==='activity_selection'&&q.action==='cart_unconfirmed')j.unconfirmed.add(p.activity_visit_id);
          if(r.event==='activity_product_view')seasonalTotals.gameViews.add(p.activity_visit_id);
          for(const key of ['revealed','selected','reviewed','cart','unconfirmed'])if(j[key].has(p.activity_visit_id))seasonalTotals[key].add(p.activity_visit_id);
          journeys.set(q.game_id,j);
        }
        if(q.activity_id==='mmoexp-seasonal'&&/^\d{1,20}$/.test(q.game_id||'')&&/^\d{1,20}$/.test(q.model_id||'')&&[8,10,15].includes(Number(q.off_percent))&&['fixed','random-1','random-2'].includes(q.slot)){
          const key=JSON.stringify([q.release_id,q.game_id,q.model_id,Number(q.off_percent),q.slot]);
          const item=seasonalOffers.get(key)||{releaseId:q.release_id,gameId:q.game_id,modelId:q.model_id,offPercent:Number(q.off_percent),slot:q.slot,codes:new Set(),exposed:new Set(),reveals:new Set(),selected:new Set(),cartConfirmations:0};
          if(typeof q.discount_code==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(q.discount_code))item.codes.add(q.discount_code);
          if(r.event==='activity_product_view')item.exposed.add(p.activity_visit_id);
          if(r.event==='activity_selection'&&q.action==='offer_reveal')item.reveals.add(p.activity_visit_id);
          if(r.event==='activity_selection'&&q.action==='product_select')item.selected.add(p.activity_visit_id);
          if(r.event==='activity_add_to_cart'&&q.complete===true)item.cartConfirmations++;
          seasonalOffers.set(key,item);
        }

        if(r.event==='activity_engaged')active+=Math.min(3600,Math.max(0,Number(q.active_seconds)||0));
        if(r.event==='activity_click')clickers.add(visitor);
        if(r.event==='activity_product_view'&&q.product_id)exposed.add(String(q.product_id));
        if(r.event==='activity_selection')for(const id of q.product_ids||[])clicked.add(String(id));
        // Revenue is a separate attributed-order metric, including orders with missing browser steps.
        if(r.event==='activity_purchase'&&q.order_key&&!orders.has(q.order_key)&&q.currency==='USD'&&Number.isSafeInteger(q.activity_paid_minor)&&q.activity_paid_minor>=0){orders.add(q.order_key);revenue+=q.activity_paid_minor;}
      }
      for(const id of new Set([...exposed,...clicked])){const item=products.get(id)||{id,exposures:0,selections:0};if(exposed.has(id))item.exposures++;if(clicked.has(id))item.selections++;products.set(id,item);}
    }
    return {template:filter.template||'commerce',windowHours,visits,visitors:visitors.size,clickers:clickers.size,activeSeconds:visits?Math.round(active/visits):null,revenueMinor:revenue,orders:orders.size,reviews,sbcSelections,couponClaims,couponReused,
      steps:steps.map((event,i)=>({event,label:labels[i],count:counts[i],rate:i&&counts[i-1]?counts[i]/counts[i-1]:i===0&&counts[0]?1:null})),
      seasonalTotals:Object.fromEntries(Object.entries(seasonalTotals).map(([k,v])=>[k,v.size])),seasonalGames:[...journeys.values()].map(j=>Object.fromEntries(Object.entries(j).map(([k,v])=>[k,v instanceof Set?v.size:v]))),
      seasonalOffers:[...seasonalOffers.values()].map(x=>({releaseId:x.releaseId,gameId:x.gameId,modelId:x.modelId,offPercent:x.offPercent,slot:x.slot,discountCodes:[...x.codes].sort(),exposedVisits:x.exposed.size,revealedVisits:x.reveals.size,selectedVisits:x.selected.size,cartConfirmations:x.cartConfirmations})),
      products:[...products.values()].sort((a,b)=>b.exposures-a.exposures),sources:[...sources.values()],daily:[...daily.values()].sort((a,b)=>a.date.localeCompare(b.date))};
  }
  function validateRegistry(items){
    if(!Array.isArray(items)||!items.length||items.length>100)throw Error('活动配置需为1–100条');
    const ids=new Set(),text=(v,max=80)=>typeof v==='string'&&v.length<=max?v:'';
    return items.map(a=>{
      if(!/^[a-z0-9-]{3,64}$/.test(a.id)||ids.has(a.id))throw Error('活动ID需唯一且仅含小写字母、数字和短横线');ids.add(a.id);
      if(!text(a.name).trim())throw Error('活动名称需为1–80字');
      if(typeof a.path!=='string'||!/^\/[A-Za-z0-9/_-]+(?:\.html|\/)$/.test(a.path))throw Error('路径须为站内HTML或目录地址');
      const type=a.type||'commerce',status=a.status&&['draft','testing','active','paused','archived'].includes(a.status)?a.status:'draft',windowHours=Number(a.windowHours||24);
      if(!['commerce','prediction'].includes(type)||!Number.isInteger(windowHours)||windowHours<1||windowHours>720)throw Error('活动类型或转化窗口无效');
      const origin=a.origin||'https://www.mmoexp.com';let u;try{u=new URL(origin);}catch{throw Error('域名格式无效');}if(u.protocol!=='https:'||u.origin!==origin||u.username||u.password)throw Error('仅接受无账户信息的HTTPS域名');
      const startAt=a.startAt||'',endAt=a.endAt||'';
      for(const v of [startAt,endAt])if(v&&!Number.isFinite(Date.parse(v)))throw Error('活动时间无效');
      if(startAt&&endAt&&Date.parse(startAt)>=Date.parse(endAt))throw Error('结束时间须晚于开始时间');
      const matches=a.matches||[];if(!Array.isArray(matches)||matches.length>100)throw Error('赛事最多100场');const matchIds=new Set();
      const normalized=matches.map(m=>{if(!/^[a-z0-9_-]{3,80}$/.test(m.id)||matchIds.has(m.id)||!text(m.name).trim())throw Error('赛事ID需唯一，名称必填');matchIds.add(m.id);const kickoff=m.kickoff||'',lockAt=m.lockAt||'';for(const v of [kickoff,lockAt])if(v&&!Number.isFinite(Date.parse(v)))throw Error('赛事时间无效');if(kickoff&&lockAt&&Date.parse(lockAt)>Date.parse(kickoff))throw Error('封盘不能晚于开赛');return {id:m.id,name:m.name,kickoff,lockAt};});
      return {id:a.id,name:a.name.trim(),path:a.path,origin,view:text(a.view)||a.id,type,status,owner:text(a.owner,60),version:text(a.version,40)||'1',startAt,endAt,windowHours,matches:normalized};
    });
  }
  return {steps,labels,templates,summarize,validateRegistry,canonicalActivity,activityMatches};
});
