/* Existing FS source contracts translated into the new screen's view model. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.FSMonitorSources=factory();})(typeof window!=='undefined'?window:globalThis,()=>{
 'use strict';
 function https(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}}
 function day(value){return /^\d{4}-\d{2}-\d{2}$/.test(value||'')&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}
 function time(value){return typeof value==='string'&&Number.isFinite(Date.parse(value));}
 function weeklyExpiry(value){const local=new Date(Date.parse(value)+8*3600000);const days=(6-local.getUTCDay()+7)%7||7;return new Date(Date.UTC(local.getUTCFullYear(),local.getUTCMonth(),local.getUTCDate()+days,7)-8*3600000).toISOString();}
 function official(value){
  if(value?.schema_version!==1||value.status!=='succeeded'||!/^game-intel-[a-f0-9]{20}$/.test(value.version||'')||!Array.isArray(value.events)||!Array.isArray(value.source_status)||!time(value.collected_at)||!time(value.stale_after))throw Error('invalid_feed');
  for(const e of value.events){
   if(!['game_key','event_id','title','summary','source_id','source_url','collected_at'].every(k=>typeof e[k]==='string'&&e[k].length<=1000)||!['release','season','update','server','maintenance','delay','announcement'].includes(e.kind)||!https(e.source_url)||!time(e.collected_at)||e.event_date!==null&&!day(e.event_date)||e.event_time!==null&&(!e.event_date||!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(e.event_time))||e.timezone!==null&&!/^UTC(?:[+-](?:0\d|1[0-4]):[0-5]\d)?$/.test(e.timezone))throw Error('invalid_event');
  }
  return value;
 }
 function merge(games,feeds,failures=[],seedEvents=[]){
  const data={schema:'fs-monitor-view-v1',mode:'live',generatedAt:null,games,allTargets:games,health:[],observations:[],records:[],failures:[...failures],feeds:[]};
  const identities=new Set(games.map(g=>g.id));
  const known=new Map();
  for(const name of ['intelligence','daily']){
   if(!feeds[name])continue;
   const feed=official(feeds[name]);data.feeds.push({name,collectedAt:feed.collected_at,expiresAt:feed.stale_after,version:feed.version});
   if(!data.generatedAt||Date.parse(feed.collected_at)>Date.parse(data.generatedAt))data.generatedAt=feed.collected_at;
   for(const e of feed.events){
    if(!identities.has(e.game_key))continue;
    const identity=[e.game_key,e.source_url,e.kind,e.event_date,e.title].join('|');const previous=known.get(identity);if(previous&&previous.time>=Date.parse(e.collected_at))continue;
    const instant=e.event_date&&e.event_time&&e.timezone;
    const date=instant?e.event_date+'T'+e.event_time+':00'+(e.timezone==='UTC'?'Z':e.timezone.slice(3)):e.event_date;
    const event={id:name+'-'+e.event_id,title:e.title,summary:e.summary,sourceUrl:e.source_url,startDate:date,endDate:null,window:null,datePrecision:instant?'instant':date?'day':'unknown',timezone:instant?'UTC+8':e.timezone,category:e.kind,verification:'来源采集记录',sourceId:e.source_id,evidence:e.evidence||'',publishedAt:e.published_at};
    // Weekly deadlines are calendar-based; carried records retain their own original deadline.
    const expiresAt=time(e.expires_at)?e.expires_at:Date.parse(e.collected_at)===Date.parse(feed.collected_at)?feed.stale_after:name==='daily'?weeklyExpiry(e.collected_at):new Date(Date.parse(e.collected_at)+4*3600000).toISOString();
    const calendar={sourceId:name+'-'+e.source_id,gameId:e.game_key,kind:'calendar',observedAt:e.collected_at,expiresAt,payload:{events:[event]}};
    const news={sourceId:name+'-'+e.source_id,gameId:e.game_key,kind:'news',observedAt:e.collected_at,expiresAt,payload:{articles:[{id:event.id,title:e.title,summary:e.summary,url:e.source_url,publishedAt:e.published_at,sourceKind:'official'}]}};
    const index=previous?previous.index:data.observations.length;
    if(previous){data.observations[index]=calendar;data.observations[index+1]=news;}else data.observations.push(calendar,news);
    known.set(identity,{time:Date.parse(e.collected_at),index});
   }
   for(const s of feed.source_status){
    for(const id of s.games||[]){if(identities.has(id))data.health.push({id:name+'-'+s.source_id,gameId:id,name:s.source_id,kind:'news',sourceUrl:s.url,status:s.status==='available'?'fresh':'failed',lastAttemptAt:feed.collected_at,lastSuccessAt:s.status==='available'?feed.collected_at:null,expiresAt:feed.stale_after,error:s.reason||(s.search_reason?'搜索补充缺项：'+s.search_reason:null),method:name==='daily'||s.method==='existing_official_reader'?'原有官方采集':'DeepSeek 搜索/抓取'});}
   }
  }
  if(feeds.intelligence_status){
   const attempt=feeds.intelligence_status;
   if(attempt.schema_version!==1||!['pending','failed','succeeded'].includes(attempt.status)||!time(attempt.attempted_at))throw Error('invalid_attempt_status');
   if(attempt.status!=='succeeded'&&(!feeds.intelligence||Date.parse(attempt.attempted_at)>=Date.parse(feeds.intelligence.collected_at))){
    data.failures.push(attempt.status==='failed'?'intelligence采集失败':'intelligence采集中');
    for(const h of data.health.filter(h=>h.id.startsWith('intelligence-'))){h.status=attempt.status==='failed'?'degraded':'pending';h.lastAttemptAt=attempt.attempted_at;h.error=attempt.reason||'本轮未完成，保留上次记录';}
   }
  }
  if(feeds.seo){
   const feed=feeds.seo;
   if(feed.contract!=='mmoexp-seo-news-v1'||!Array.isArray(feed.documents)||!time(feed.collected_at)||!time(feed.stale_after))throw Error('invalid_seo_feed');
   for(const a of feed.documents){if(!https(a.source_url))throw Error('invalid_seo_article');const u=new URL(a.source_url);if(u.origin!=='https://www.mmoexp.com'||!/^\/News\/[a-z0-9][a-z0-9-]*\.html$/.test(u.pathname)||u.search||u.hash||a.source_kind!=='mmoexp_seo')throw Error('invalid_seo_article');for(const id of a.game_keys||[]){if(identities.has(id))data.observations.push({sourceId:'mmoexp-news',gameId:id,kind:'news',observedAt:feed.collected_at,expiresAt:feed.stale_after,payload:{articles:[{id:a.document_id||a.source_url,title:a.title_zh||a.title,summary:a.summary_zh||a.summary,url:a.source_url,publishedAt:a.published_at,sourceKind:'mmoexp_seo'}]}});}}
  }
  for(const e of seedEvents){
   if(!identities.has(e.gameId)||!https(e.sourceUrl)&&!(e.sourceUrl===null&&typeof e.sourceLabel==='string'&&e.sourceLabel.trim()))continue;
   data.observations.push({sourceId:'existing-calendar',gameId:e.gameId,kind:'calendar',observedAt:null,expiresAt:null,payload:{events:[e]}});
  }
  return data;
 }
 return {merge,official};
});
