const test=require('node:test'),assert=require('node:assert/strict'),core=require('../analytics/funnel-core.cjs');
const p={activity_id:'fc27-sbc',activity_visit_id:'v1',activity_session_id:'s1',device:'mobile',platform:'ps',source:'organic'};
const row=(event,minute,extra={})=>({event,timestamp:new Date(Date.UTC(2026,9,23,0,minute)).toISOString(),properties:{...p,event_id:event+minute,...extra}});
test('ordered funnel, duplicate events and orders counted once',()=>{const events=core.steps.map((e,i)=>row(e,i,i===4?{order_key:'o1',currency:'USD',activity_paid_minor:1200}:{}));const r=core.summarize([...events,...events]);assert.deepEqual(r.steps.map(s=>s.count),[1,1,1,1,1]);assert.equal(r.revenueMinor,1200);assert.equal(r.orders,1);});
test('missing intermediate event is not payment conversion, revenue remains independent',()=>{const r=core.summarize([row('activity_view',0),row('activity_purchase',3,{order_key:'o1',currency:'USD',activity_paid_minor:1200})]);assert.deepEqual(r.steps.map(s=>s.count),[1,0,0,0,0]);assert.equal(r.revenueMinor,1200);});
test('24h conversion window and entry-day cohort',()=>{const events=core.steps.map((e,i)=>row(e,i===4?1441:i));assert.equal(core.summarize(events).steps[4].count,0);assert.equal(core.summarize(events,{from:'2026-10-24'}).visits,0);});
test('coupon claims count visits: new claims and reuse apart, unavailable or other states never',()=>{
 const claim=(visit,minute,props)=>row('activity_coupon_claim',minute,{activity_visit_id:visit,event_id:'claim-'+visit+minute,...props});
 const events=[row('activity_view',0,{activity_visit_id:'a',event_id:'va'}),claim('a',1,{coupon_state:'claimed',coupon_reused:false,coupon_id:1395}),claim('a',2,{coupon_state:'claimed',coupon_reused:false,coupon_id:1395}),
  row('activity_view',0,{activity_visit_id:'b',event_id:'vb'}),claim('b',1,{coupon_state:'claimed',coupon_reused:true,coupon_id:1395}),
  row('activity_view',0,{activity_visit_id:'c',event_id:'vc'}),claim('c',1,{coupon_state:'unavailable',coupon_reused:false}),
  row('activity_view',0,{activity_visit_id:'d',event_id:'vd'})];
 const r=core.summarize(events);assert.equal(r.couponClaims,1,'a visit claiming twice still counts once');assert.equal(r.couponReused,1);assert.equal(r.visits,4);
 const none=core.summarize([row('activity_view',0)]);assert.equal(none.couponClaims,0);assert.equal(none.couponReused,0);
});
test('different activity visit contexts never join',()=>{const events=core.steps.map((e,i)=>row(e,i,i>1?{activity_visit_id:'v2'}:{}));assert.equal(core.summarize(events).steps[2].count,0);});
test('same session multiple visits distinguishes denominators and filters',()=>{const events=[row('activity_view',0),row('activity_view',1,{activity_visit_id:'v2'})];const r=core.summarize(events);assert.equal(r.visits,2);assert.equal(r.visitors,1);assert.equal(core.summarize(events,{device:'desktop'}).visits,0);});
test('invalid amounts are never coerced into revenue',()=>{for(const value of [-2,3.2,'300'])assert.equal(core.summarize([row('activity_view',0),row('activity_purchase',1,{order_key:'o1',currency:'USD',activity_paid_minor:value})]).revenueMinor,0);});
test('registry rejects duplicates and nonlocal paths',()=>{const a={id:'fc27-new',name:'新活动',path:'/Fc-27/New.html'};assert.equal(core.validateRegistry([a]).length,1);assert.throws(()=>core.validateRegistry([a,a]));assert.throws(()=>core.validateRegistry([{...a,path:'https://evil.test'}]));});
