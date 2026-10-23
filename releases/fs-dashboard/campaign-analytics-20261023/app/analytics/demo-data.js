/* Deterministic synthetic journeys. No customer or actual sales data. */
window.activityDemoEvents=function(registry){
 const rows=[],productIds=window.FC_ACTIVITY_CONFIG.weekly.ids.slice(0,3),today=new Date();today.setUTCHours(0,0,0,0);
 registry.slice(0,3).forEach((a,j)=>{for(let day=0;day<7;day++)for(let n=0;n<100+j*20;n++){
  const stamp=today.getTime()-(6-day)*86400000+n*30000,id=`demo-${a.id}-${day}-${n}`;
  const p={activity_id:a.id,activity_visit_id:id,activity_session_id:id,environment:'demo',source:['organic','internal','google_ads','direct'][n%4],platform:['ps','ps','xbox','pc'][n%4],device:n%5?'mobile':'desktop',catalog_version:'demo-only'};
  const emit=(event,step,extra={})=>rows.push({event,timestamp:new Date(stamp+step*1500).toISOString(),properties:{...p,...extra,event_id:id+'-'+event}});
  emit('activity_view',0);emit('activity_engaged',1,{active_seconds:35+n%80});
  if(n%10<8){emit('activity_product_view',2,{product_id:productIds[n%productIds.length]});emit('activity_click',3);}
  if(n%10<5)emit('activity_selection',4,{product_ids:[productIds[n%productIds.length]],include_sbc:j===1&&n%2===0});
  if(n%10<4)emit('activity_review',5);
  if(n%10<(j===1?4:3))emit('activity_add_to_cart',6);
  if(n%10<2)emit('activity_begin_checkout',7);
  if(n%10===0)emit('activity_purchase',8,{order_key:id,currency:'USD',activity_paid_minor:2500+j*700+n*10});
 }});return rows;
};
