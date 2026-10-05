/* Aion2 consumes the existing authenticated atomic snapshot and exact-range client. */
(function(root){
 'use strict';
 function classify(key,phase,record,selection){
  if(key!=='AION2')return {state:'hidden',text:''};
  if(phase==='loading')return {state:'loading',text:'Aion2 所选区间正在读取，请稍候。'};
  if(phase==='error')return {state:'error',text:'Aion2 所选区间读取失败，请使用现有重试按钮重试。'};
  const p=record?.primary,f=p?.filters;
  if(!record||!p||p.status!=='available')return {state:'unavailable',text:'Aion2 所选区间数据尚不可用。'};
  if(p.system!=='order.p2pah.cn'||String(f?.gid)!=='826'||String(f?.status)!=='3'||
     (record.supplement?.status==='available'&&String(record.supplement.filters?.game)!=='891'))
   return {state:'unverified',text:'Aion2 数据来源核验未通过，请稍后重试。'};
  const s=p.period,selectedStart=selection?.start?.slice(0,10),selectedEnd=selection?.end?.slice(0,10);
  if(!s||s.start.slice(0,10)!==selectedStart||s.end.slice(0,10)<selectedEnd)return {state:'loading',text:'Aion2 所选区间正在读取，请稍候。'};
  if(!Number.isFinite(p.orders)||!Number.isFinite(p.revenueUsd))return {state:'unavailable',text:'Aion2 所选区间数据尚不可用。'};
  const scope='所有网站 · 已完成 · Order 游戏 826 / Admin 游戏 891';
  if(p.orders===0&&p.revenueUsd===0)return {state:'empty',text:'所选区间暂无 Aion2 已完成交易。'+scope+'；缺失指标显示“未提供”。'};
  return {state:'available',text:scope+' · 支付时间 '+s.start+' 至 '+s.end+'（结束边界不含）'};
 }
 root.FSAion2Status={classify};
 if(typeof document==='undefined')return;
 const style=document.createElement('style');
 style.textContent='#profileTabs [data-k="AION2"]>svg{width:22px;height:22px;flex:0 0 22px;vertical-align:middle}';
 document.head.append(style);
 let queued=false;
 function render(){
  queued=false;if(typeof KEY==='undefined'||typeof INSIGHTS_SNAPSHOT==='undefined')return;
  let box=document.getElementById('aion2-source-state');
  if(!box){const host=document.getElementById('profileTabs');if(!host)return;box=document.createElement('p');box.id='aion2-source-state';box.className='hint';box.setAttribute('role','status');box.setAttribute('aria-live','polite');box.style.cssText='margin:10px 0;line-height:1.6;overflow-wrap:anywhere;white-space:normal;max-width:100%;min-width:0;box-sizing:border-box';host.after(box);}
  const q=currentSelection(),phase=document.getElementById('supplement-insights')?.dataset.rangeReadState;
  const native=currentExact()?.profile;
  const base=INSIGHTS_SNAPSHOT?.profiles?.[KEY];
  const record=native||(root.FSBusinessRange?.matches(base?.period,q)?base:null);
  const state=classify(KEY,phase,record,q);
  box.hidden=state.state==='hidden';
  if(box.dataset.state!==state.state)box.dataset.state=state.state;
  if(box.textContent!==state.text)box.textContent=state.text;
 }
 function schedule(){if(!queued){queued=true;requestAnimationFrame(render);}}
 new MutationObserver(schedule).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['data-range-read-state']});
 addEventListener('fs-exact-range',schedule);addEventListener('fs-exact-ready',schedule);schedule();
})(typeof window==='undefined'?globalThis:window);
