(function(root){'use strict';
const cache=new Map(),states=new WeakMap();const endpoint='/dashboard/fs-home/range.json';let renderBase;
const keyOf=(d,key,s)=>JSON.stringify([d.snapshotId,key,s.start,s.end,s.grain||'day']);
const same=(a,b)=>a&&b&&a.start===b.start&&a.end===b.end&&(a.grain||'day')===(b.grain||'day');
function peek(d,key,s){return s?cache.get(keyOf(d,key,s)):null;}
function selected(d,key,s,result){const v=FSBusinessRange.select(d,s),profiles={...v.profiles};
 for(const pkey of Object.keys(profiles)){const exact=pkey===key?result:peek(d,pkey,s);if(exact)profiles[pkey]={...exact.profile,rangeSelected:true,rangeExact:true,rangeCovered:true,exactRangeGeneration:exact.rangeId};}
 return {...v,profiles,exactRange:result};}
function renderExact(host,d,key,s,result){renderBase(host,selected(d,key,s,result),key);const label=host.querySelector('.fsi-heading p');if(label)label.textContent=(result.profile.name||key)+' · '+s.start+' 至 '+s.end+' · 北京时间（所选结束日包含在内）';const hint=[...host.querySelectorAll('.fsi-note')].find(e=>e.textContent.startsWith('所选区间：订单和金额'));if(hint)hint.textContent='所选区间指标采用Order/Admin后台区间原值；人数、复购率和利润率不按日相加。四核心优先Order，新客占比按本区间Admin新客 ÷ Admin订单。';}
function note(host,state,result){const p=document.createElement('p');p.className=state==='loading'?'fsi-note':'fsi-empty';p.dataset.exactRangeStatus=state;
 p.textContent=state==='loading'?'正在读取后台准确区间聚合…':state==='available'?'准确区间聚合 · Order主源 / Admin补缺 · 支付时间截至 '+result.profile.period.end+'（结束边界不含） · 数据生成 '+new Date(result.generatedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间 · 基础快照 '+result.baseSnapshotId:
 '准确区间读取失败，可重试；不会按日估算人数或利润率。'+(result?.message||'可切换区间或检查新版本后重试。');if(state==='available'&&result.profile.primary.seriesGranularity==='upstream-undated')p.textContent+=' · 按日图表仍采用已发布日数据，区间指标采用后台准确汇总。';host.prepend(p);}
function pause(ms,signal){return new Promise((resolve,reject)=>{
 if(signal.aborted)return reject(new DOMException('Aborted','AbortError'));
 const aborted=()=>{clearTimeout(id);reject(new DOMException('Aborted','AbortError'));};
 const id=setTimeout(()=>{signal.removeEventListener('abort',aborted);resolve();},ms);
 signal.addEventListener('abort',aborted,{once:true});
});}
async function rangeRequest(url,signal,timeoutMs){
 if(signal.aborted)throw new DOMException('Aborted','AbortError');
 const abort=new AbortController();let timer,aborted;
 const bounded=new Promise((_,reject)=>{
  aborted=()=>{abort.abort();reject(new DOMException('Aborted','AbortError'));};
  signal.addEventListener('abort',aborted,{once:true});
  timer=setTimeout(()=>{abort.abort();reject(Error('区间请求超时，可重试。'));},timeoutMs);
 });
 try{return await Promise.race([bounded,(async()=>{
  const response=await fetch(url,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:abort.signal});
  const data=await response.json();return {response,data};
 })()]);}
 finally{clearTimeout(timer);signal.removeEventListener('abort',aborted);}
}
async function load(d,key,s,signal){const query=new URLSearchParams({profile:key,start:s.start,end:s.end,grain:s.grain||'day',snapshotId:d.snapshotId});const stop=Date.now()+240000;
 while(Date.now()<stop){const {response:r,data}=await rangeRequest(endpoint+'?'+query,signal,Math.min(30000,stop-Date.now()));
  if(r.status===202||r.status===429){const retry=Number(data.retryAfter);await pause(Math.min(Math.min(10,Number.isFinite(retry)&&retry>0?retry:2)*1000,Math.max(0,stop-Date.now())),signal);continue;}
  if(!r.ok)throw Error(r.status===409?'基础快照已更新，等待页面检查新版本。':r.status===422?'所选区间超出已发布日期范围。':'服务器未能完成该区间读取。');
  if(data.status!=='available'||data.baseSnapshotId!==d.snapshotId||data.profile?.key!==key||!same(data.query,s))throw Error('区间数据合同不符');return data;
 }throw Error('区间读取超时，当前快照数据保留。');}
function retry(host,d,key,s){const b=document.createElement('button');b.type='button';b.dataset.rangeRetry='true';b.textContent='重试该区间';b.onclick=()=>{states.delete(host);render(host,d,key,s);};host.prepend(b);}
function render(host,d,key='MMOEXP',s=null){if(!host)return;
 const id=s?keyOf(d,key,s):null,previous=states.get(host);if(previous?.id===id){const result=peek(d,key,s);if(result)renderExact(host,d,key,s,result);else renderBase(host,d,key,s,previous.loading?'loading':previous.error?'error':null);if(s&&previous.loading)note(host,'loading');else if(result)note(host,'available',result);else if(previous?.error){note(host,'error',{message:previous.error});retry(host,d,key,s);}return;}
 previous?.abort.abort();const abort=new AbortController(),state={id,abort,loading:false};states.set(host,state);
 const result=peek(d,key,s);if(result)renderExact(host,d,key,s,result);else renderBase(host,d,key,s);
 if(!s||!s.start||!s.end)return;
 if(result){note(host,'available',result);return;}
 // Today's exact native values already belong to the pinned snapshot; no extra collection.
 if(FSBusinessRange.matches(d.profiles?.[key]?.period,s)&&FSBusinessRange.matches(d.profiles?.[key]?.supplement?.period,s))return;
 state.loading=true;renderBase(host,d,key,s,'loading');note(host,'loading');
 (async()=>{try{await pause(250,abort.signal);const result=await load(d,key,s,abort.signal);if(states.get(host)!==state||abort.signal.aborted)return;
 cache.set(id,result);if(cache.size>80)cache.delete(cache.keys().next().value);state.loading=false;
 renderExact(host,d,key,s,result);note(host,'available',result);
 root.dispatchEvent(new CustomEvent('fs-exact-range',{detail:{key,selection:s,result}}));
 }catch(e){if(abort.signal.aborted||states.get(host)!==state)return;state.loading=false;state.error=e.message;renderBase(host,d,key,s,'error');note(host,'error',{message:e.message});retry(host,d,key,s);}})();
}
root.FSExactRange={peek,render};
renderBase=root.FSSupplementInsights.render;root.FSSupplementInsights.render=render;
root.dispatchEvent(new Event('fs-exact-ready'));
})(window);
