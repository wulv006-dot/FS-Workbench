/* Optional integration bridge. Does not wrap login, submit predictions, settle matches or issue coupons. */
(function(){
  'use strict';
  const permitted=new Set(['prediction_match_view','prediction_started','prediction_coupon_view_click','prediction_share_click']);
  window.createMatchdayAnalytics=function({activityId,version,capture}){
    if(!/^[a-z0-9-]{3,64}$/.test(activityId)||typeof capture!=='function')throw Error('Activity id and capture callback required');
    const visit=crypto.randomUUID(),seen=new Set();
    return {context(matchId){if(!/^[a-z0-9_-]{3,80}$/.test(matchId))throw Error('Invalid match id');return {activity_id:activityId,activity_visit_id:visit,catalog_version:String(version),match_id:matchId};},
      track(event,matchId){if(!permitted.has(event))throw Error('Only frontend behavior events are accepted');const key=event+':'+matchId;if(event==='prediction_match_view'&&seen.has(key))return;seen.add(key);capture(event,{...this.context(matchId),event_id:crypto.randomUUID()});}};
  };
})();
