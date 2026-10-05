(function(root){'use strict';
const host=document.getElementById('fc-classification');if(!host)return;
const types=[['coins','Coins','--gold'],['items','Items','--cyan'],['boosting','Boosting','--purple']],cache=new Map();
let state={id:null,controller:null,data:null,result:null,selection:null,focus:'all',mode:'sales',status:'loading'},resizeTimer;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const valid=v=>typeof v==='number'&&Number.isFinite(v),money=v=>valid(v)?'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'未提供',count=v=>valid(v)?v.toLocaleString('en-US'):'未提供',pct=v=>valid(v)?v.toFixed(2)+'%':'未提供';
const color=key=>getComputedStyle(document.documentElement).getPropertyValue(types.find(t=>t[0]===key)?.[2]||'--tx3').trim();
const dateShift=(s,n)=>new Date(Date.parse(s+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
const stamp=s=>s?new Date(s).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未提供';
const isDay=s=>/^\d{4}-\d{2}-\d{2}$/.test(s),selectionKey=(d,s)=>JSON.stringify([d.snapshotId,s.start,s.end]);
const inPeriod=(day,a)=>day>=a.period.start.slice(0,10)&&day+' 00:00'<a.period.end;
const activeCats=a=>a.categories.filter(c=>state.focus==='all'||c.key===state.focus);
const tooltip=document.createElement('div');tooltip.className='fca-tooltip';tooltip.hidden=true;tooltip.setAttribute('role','tooltip');document.body.append(tooltip);
function tip(e,text){tooltip.textContent=text;tooltip.hidden=false;const rect=e.target.getBoundingClientRect(),x=e.clientX||rect.left+rect.width/2,y=e.clientY||rect.top;tooltip.style.left=Math.max(12,Math.min(innerWidth-tooltip.offsetWidth-12,x+12))+'px';tooltip.style.top=Math.max(12,Math.min(innerHeight-tooltip.offsetHeight-12,y+12))+'px';}
function drill(day){if(isDay(day)&&state.selection&&day>=state.selection.start&&day<=state.selection.end)root.FCAnalyticsBridge?.applyRange(day,day);}
function nodes(plot,points){plot.querySelectorAll('[data-point]').forEach(el=>{const p=points[Number(el.dataset.point)];el.addEventListener('pointerenter',e=>tip(e,p.text));el.addEventListener('pointermove',e=>tip(e,p.text));el.addEventListener('focus',e=>tip(e,p.text));el.addEventListener('pointerleave',()=>tooltip.hidden=true);el.addEventListener('blur',()=>tooltip.hidden=true);el.addEventListener('click',()=>{tip({target:el},p.text);if(p.day)drill(p.day);});el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(p.day)drill(p.day);}if(e.key==='Escape')tooltip.hidden=true;});});}
function legend(cats,other=false){return cats.map(c=>'<i><b style="background:'+color(c.key)+'"></b>'+esc(c.label)+'</i>').join('')+(other?'<i><b style="background:var(--tx3)"></b>其他原始类型（差额）</i>':'');}
function chartRows(c){const rows=(c.rows||[]).filter(r=>r.date>=state.selection.start&&r.date.slice(0,10)<=state.selection.end&&r.date<c.period.end);if(rows.length)return rows.map(r=>({label:r.date,orders:r.orders,amount:r.amount}));return c.nativeSeries||[];}
function daily(rows){const out=new Map();for(const r of rows){if(!/^\d{4}-\d{2}-\d{2}( \d{2}:00)?$/.test(r.label))continue;const d=r.label.slice(0,10),old=out.get(d)||{date:d,amount:0,orders:0};if(!valid(r.amount)||!valid(r.orders))continue;old.amount+=r.amount;old.orders+=r.orders;out.set(d,old);}return out;}
function plotLine(plot,series,unit,formatter,margin=false){
 const labels=[...new Set(series.flatMap(s=>s.rows.map(r=>r.label)))].sort();const values=series.flatMap(s=>s.rows.map(r=>r.value).filter(valid));
 if(!labels.length||!values.length){plot.innerHTML='<div class="fca-empty">暂无可验证的'+esc(margin?'逐日利润率':'分类趋势')+'数据<br>缺失值不会按0补齐</div>';return;}
 const w=Math.max(300,plot.clientWidth||600),h=245,l=58,r=18,t=18,b=42,lo=Math.min(0,...values),hi=Math.max(1,...values),span=hi-lo||1,min=lo<0?lo-span*.08:0,max=hi+span*.08;
 const x=i=>l+(w-l-r)*(labels.length===1?.5:i/(labels.length-1)),y=v=>h-b-(v-min)/(max-min)*(h-b-t),points=[];let svg='';
 for(let i=0;i<=4;i++){const v=min+(max-min)*i/4;svg+='<line class="fca-grid-line" x1="'+l+'" x2="'+(w-r)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text text-anchor="end" x="'+(l-8)+'" y="'+(y(v)+3)+'">'+esc(margin?v.toFixed(0)+'%':v>=1000?(v/1000).toFixed(1)+'k':v.toFixed(0))+'</text>';}
 if(min<0)svg+='<line x1="'+l+'" x2="'+(w-r)+'" y1="'+y(0)+'" y2="'+y(0)+'" stroke="var(--tx3)" stroke-dasharray="3 3"/>';
 const tick=Math.max(1,Math.ceil(labels.length/Math.max(2,Math.floor((w-l-r)/95))));labels.forEach((label,i)=>{if(i%tick===0||i===labels.length-1)svg+='<text text-anchor="middle" x="'+x(i)+'" y="'+(h-15)+'">'+esc(isDay(label.slice(0,10))?label.slice(5,10)+(label.length>10?' '+label.slice(11,13):''):label)+'</text>';});
 for(const s of series){const map=new Map(s.rows.map(r=>[r.label,r]));let path='',started=false;
  labels.forEach((label,i)=>{const row=map.get(label);if(!row||!valid(row.value)){started=false;return;}path+=(started?' L':' M')+x(i)+' '+y(row.value);started=true;});
  svg+='<path d="'+path+'" fill="none" stroke="'+color(s.key)+'" stroke-width="2.4"/>';
  labels.forEach((label,i)=>{const row=map.get(label);if(!row||!valid(row.value))return;const day=isDay(label.slice(0,10))?label.slice(0,10):null,text=label+'\n'+s.label+' · '+formatter(row.value)+'\n'+(row.note||'Order原生数据')+(day?'\n点击查看该自然日':'\n后台原生时间桶，不能按日下钻');points.push({text,day});svg+='<circle class="fca-point" cx="'+x(i)+'" cy="'+y(row.value)+'" r="3.5" fill="'+color(s.key)+'" tabindex="0" role="button" aria-label="'+esc(text)+'" data-point="'+(points.length-1)+'"/>';});
 }
 plot.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+esc(unit+'趋势')+'">'+svg+'</svg>';nodes(plot,points);
}
function margins(a){const rows=[];
 for(const [day,parts] of Object.entries(a.dailyMetrics||{})){if(!inPeriod(day,a)||dateShift(day,1)+' 00:00'>a.period.end)continue;
  for(const c of activeCats(a)){const record=parts[c.key];if(record&&valid(record.profitMarginPct))rows.push({key:c.key,label:day,value:record.profitMarginPct,note:record.period.start+' 至 '+record.period.end+'（末端不含）\n原生区间利润率 · 采集 '+stamp(record.capturedAt)});}}
 const days=[...new Set(rows.map(r=>r.label))];return {rows,days};
}
function plotMargins(a){const plot=host.querySelector('#fca-margin'),raw=margins(a),cats=activeCats(a);host.querySelector('#fca-margin-legend').innerHTML=legend(cats);
 if(raw.days.length>=2){host.querySelector('#fca-margin-title').textContent='逐日利润率';host.querySelector('#fca-margin-note').textContent='每点为该完整自然日的Order原生利润率。缺失日断线；不对日比例求和或平均。';
  const allDays=[];for(let d=raw.days.sort()[0];d<=raw.days.at(-1);d=dateShift(d,1))allDays.push(d);
  plotLine(plot,cats.map(c=>({key:c.key,label:c.label,rows:allDays.map(day=>raw.rows.find(r=>r.key===c.key&&r.label===day)||{label:day,value:null})})),'利润率 %',pct,true);return;}
 host.querySelector('#fca-margin-title').textContent='分类利润率比较';host.querySelector('#fca-margin-note').textContent='显示所选整段区间的Order原值；逐日原生利润率积累足够后显示趋势，当前不推算。';
 const available=cats.filter(c=>valid(c.profitMarginPct));if(!available.length){plot.innerHTML='<div class="fca-empty">所选区间未提供利润率<br>不会用项目利润率摊分</div>';return;}
 const w=Math.max(300,plot.clientWidth||450),h=245,l=75,r=55,lo=Math.min(0,...available.map(c=>c.profitMarginPct)),hi=Math.max(1,...available.map(c=>c.profitMarginPct)),scale=v=>l+(v-lo)/(hi-lo)*(w-l-r),points=[];let svg='<line class="fca-grid-line" x1="'+scale(0)+'" x2="'+scale(0)+'" y1="20" y2="215"/>';
 available.forEach((c,i)=>{const y=35+i*62,x=scale(Math.min(0,c.profitMarginPct)),width=Math.max(1,Math.abs(scale(c.profitMarginPct)-scale(0))),text=c.label+'\n'+pct(c.profitMarginPct)+' · 所选整段原值\n'+a.period.start+' 至 '+a.period.end+'（末端不含）\n采集 '+stamp(c.capturedAt);points.push({text});svg+='<text x="5" y="'+(y+24)+'">'+esc(c.label)+'</text><rect x="'+x+'" y="'+y+'" width="'+width+'" height="38" rx="5" fill="'+color(c.key)+'" tabindex="0" data-point="'+i+'" aria-label="'+esc(text)+'"/><text x="'+(scale(c.profitMarginPct)+7)+'" y="'+(y+24)+'">'+pct(c.profitMarginPct)+'</text>';});
 plot.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="所选区间原生利润率比较">'+svg+'</svg>';nodes(plot,points);
}
function shares(a){const plot=host.querySelector('#fca-share');host.querySelector('#fca-share-legend').innerHTML=legend(a.categories,true);
 const totalRows=chartRows(a.totals),labels=totalRows.map(r=>r.label),maps=a.categories.map(c=>new Map(chartRows(c).map(r=>[r.label,r.amount])));
 const rows=totalRows.map(row=>({label:row.label,total:row.amount,values:maps.map(m=>m.get(row.label))})).filter(row=>valid(row.total)&&row.total>0&&row.values.every(valid)&&row.values.reduce((v,n)=>v+n,0)<=row.total+.02);
 if(!rows.length){plot.innerHTML='<div class="fca-empty">占比需要同一时间桶的完整分类与总销售額<br>空区间或缺失分类不计算</div>';return;}
 const w=Math.max(300,plot.clientWidth||600),h=235,l=42,r=12,t=12,b=42,step=(w-l-r)/rows.length,bar=Math.max(2,Math.min(36,step*.7)),points=[];let svg='';
 for(const v of [0,25,50,75,100]){const y=h-b-v/100*(h-t-b);svg+='<line class="fca-grid-line" x1="'+l+'" x2="'+(w-r)+'" y1="'+y+'" y2="'+y+'"/><text x="3" y="'+(y+3)+'">'+v+'%</text>';}
 rows.forEach((row,i)=>{let y=h-b;const remain=row.total-row.values.reduce((v,n)=>v+n,0),vals=[...row.values,Math.max(0,remain)];
  const text=row.label+'\nOrder总销售额 '+money(row.total)+'\n'+a.categories.map((c,j)=>c.label+' '+money(row.values[j])+' · '+pct(row.values[j]/row.total*100)).join('\n')+'\n其他原始类型（算术差额） '+money(remain);
  points.push({text,day:isDay(row.label)?row.label:null});vals.forEach((v,j)=>{const height=v/row.total*(h-b-t);y-=height;svg+='<rect x="'+(l+step*i+(step-bar)/2)+'" y="'+y+'" width="'+bar+'" height="'+height+'" fill="'+(j<3?color(a.categories[j].key):'var(--tx3)')+'" opacity="'+(state.focus==='all'||j>=3||a.categories[j].key===state.focus?'1':'.3')+'"/>';});svg+='<rect x="'+(l+step*i)+'" y="'+t+'" width="'+step+'" height="'+(h-b-t)+'" fill="transparent" data-point="'+i+'" tabindex="0" role="button" aria-label="'+esc(text)+'"/>';
  if(i%Math.max(1,Math.ceil(rows.length/6))===0)svg+='<text text-anchor="middle" x="'+(l+step*(i+.5))+'" y="'+(h-15)+'">'+esc(isDay(row.label)?row.label.slice(5):row.label)+'</text>';
 });plot.innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="分类销售额占比变化">'+svg+'</svg>';nodes(plot,points);
}
// Calendar model: only remove a verified-zero prefix of selected months.
function calendarWindow(map,period,selection){
 const numeric=v=>typeof v==='number'&&Number.isFinite(v),shift=d=>new Date(Date.parse(d+'T00:00:00Z')+86400000).toISOString().slice(0,10),days=[],months=[];
 for(let day=selection.start;day<=selection.end;day=shift(day)){
  if(day<period.start.slice(0,10)||day+' 00:00'>=period.end)continue;
  const row=map.get(day),known=!!row&&numeric(row.amount)&&numeric(row.orders)&&row.orders>=0,month=day.slice(0,7);
  const item={day,month,row,known,active:known&&(row.amount!==0||row.orders>0)};
  days.push(item);let bucket=months.at(-1);if(bucket?.month!==month){bucket={month,days:[]};months.push(bucket);}bucket.days.push(item);
 }
 if(!days.length)return {status:'unavailable',days:[],hiddenMonths:[]};
 if(days.every(d=>d.known&&!d.active))return {status:'empty',days:[],hiddenMonths:months.map(m=>m.month)};
 const hiddenMonths=[];let cut=0;
 for(const month of months){if(!month.days.every(d=>d.known&&!d.active))break;hiddenMonths.push(month.month);cut+=month.days.length;}
 return {status:days.some(d=>d.active)?'available':'partial',days:days.slice(cut),hiddenMonths};
}
// End calendar model.
function heatmap(a){const section=host.querySelector('#fca-heat-section'),grid=host.querySelector('#fca-heat-grid'),map=daily(chartRows(a.totals));let fallback=false;
 const note=host.querySelector('#fca-heat-note');section.hidden=false;
 if(a.totals?.status==='available'&&a.totals.orders===0&&a.totals.revenueUsd===0){note.textContent='所选区间经核实没有销售活动。';grid.innerHTML='<p class="fca-calendar-empty" role="status">'+esc(a.period.start+' 至 '+a.period.end+'（末端不含）')+'</p>';return;}
 const base=state.resultBase||state.data;
 if(map.size<7&&base?.fcOps?.rows){for(const row of base.fcOps.rows)if(row.source_schema===3&&row.site==='all'&&inPeriod(row.d,a)&&valid(row.sales)&&!map.has(row.d)){map.set(row.d,{date:row.d,amount:row.sales,orders:row.orders});fallback=true;}}
 const model=calendarWindow(map,a.period,state.selection);section.hidden=false;
 if(model.status==='empty'){const conflict=(valid(a.totals?.orders)&&a.totals.orders>0)||(valid(a.totals?.revenueUsd)&&a.totals.revenueUsd!==0);note.textContent=conflict?'逐日明细与区间汇总不一致，日历数据暂不可用。':'所选区间逐日明细经核实没有销售活动。';grid.innerHTML='<p class="fca-calendar-empty" role="status">'+esc(a.period.start+' 至 '+a.period.end+'（末端不含）')+'</p>';return;}
 if(!model.days.some(d=>d.known)){note.textContent='所选区间未提供可核实的逐日销售数据，不能判定为零销售。';grid.innerHTML='<p class="fca-calendar-empty" role="status">日历数据不可用</p>';return;}
 const max=Math.max(1,...model.days.filter(d=>d.known).map(d=>Math.abs(d.row.amount)));
 note.textContent=(fallback?'日历使用同范围已发布日快照；分类指标仍为后台准确汇总。':'日历使用Order原生逐日金额。')+' '+(model.hiddenMonths.length?'已收起前部经核实无销售活动月份：'+model.hiddenMonths.join('、')+'。 ':'')+'颜色表示销售额；缺失日明确标记，不作为零销售。';
 let month='';grid.innerHTML=model.days.map(item=>{
  const {day,row,known}=item;let heading='';if(item.month!==month){month=item.month;heading='<h4 class="fca-calendar-month">'+month+'</h4>';}
  const text=day+'\n'+(known?'FC27所有网站销售 '+money(row.amount)+'\n'+count(row.orders)+' 订单':'逐日销售数据未提供，不能按零计算')+'\n'+(fallback?'已发布日快照 '+stamp(base.generatedAt):'Order原生时间桶');
  return heading+'<button type="button" class="fca-day" data-missing="'+(!known)+'" style="--heat:'+(known?10+Math.sqrt(Math.abs(row.amount)/max)*20:0).toFixed(0)+'%" data-day="'+day+'" aria-label="'+esc(text)+'"><time>'+day.slice(5)+'</time><strong>'+(known?money(row.amount):'未提供')+'</strong></button>';
 }).join('');
 host.querySelectorAll('.fca-day').forEach(b=>{b.onclick=()=>drill(b.dataset.day);b.onpointerenter=e=>tip(e,b.getAttribute('aria-label'));b.onpointerleave=()=>tooltip.hidden=true;b.onfocus=e=>tip(e,b.getAttribute('aria-label'));b.onblur=()=>tooltip.hidden=true;});
}
function render(){
 const a=state.result,loading=state.status==='loading',disabled=!a||loading;
 host.innerHTML='<div class="fca-title"><div><h2>FC27 分类经营</h2><p>Coins · Items · Boosting｜所有网站 · 所有平台 · Order主源</p></div><span class="fca-badge">120分钟快照 · 60秒检查</span></div><div class="fca-status" data-state="'+state.status+'" role="status" aria-live="polite">'+esc(loading?'正在读取所选区间的后台分类聚合…':state.status==='stale'?'新版本分类读取失败，保留上次成功数据；下面明确显示实际统计范围。':state.status==='refreshing'?'正在读取新版本；暂时保留上次成功数据与实际截止时间。':state.status==='error'?'分类数据读取失败；当前区间不显示旧值。':a?'统计 '+a.period.start+' 至 '+a.period.end+'（末端不含） · 分类采集 '+stamp(a.generatedAt):'等待统一快照')+((state.status==='stale'||state.status==='refreshing')&&a?' 实际统计 '+esc(a.period.start+' 至 '+a.period.end+' · '+stamp(a.generatedAt)):'')+((state.status==='error'||state.status==='stale')?'<button type="button" id="fca-retry">重试分类数据</button>':'')+'</div><div class="fca-categories">'+types.map(([key,label,css])=>{const c=a?.categories.find(c=>c.key===key),unavailable=loading?'待读取':'未提供';return '<button type="button" class="fca-category" data-focus="'+key+'" aria-pressed="'+(state.focus===key)+'" style="--category:var('+css+')"><h3><span class="fca-dot"></span>'+label+'</h3><div class="fca-revenue">'+(disabled?unavailable:money(c?.revenueUsd))+'</div><dl><div><dt>订单数</dt><dd>'+(!disabled?count(c?.orders):unavailable)+'</dd></div><div><dt>单均价 USD</dt><dd>'+(!disabled?money(c?.averageOrderUsd):unavailable)+'</dd></div><div><dt>利润率原值</dt><dd class="'+(c?.profitMarginPct<0?'fca-negative':'')+'">'+(!disabled?pct(c?.profitMarginPct):unavailable)+'</dd></div></dl><p class="fca-note">原始类型 '+({coins:1,items:2,boosting:4}[key])+' · 订单数不是商品件数</p></button>';}).join('')+'</div><div class="fca-toolbar"><button type="button" data-focus="all" aria-pressed="'+(state.focus==='all')+'">全部分类</button><span class="fca-spacer"></span><button type="button" data-mode="sales" aria-pressed="'+(state.mode==='sales')+'">销售额 USD</button><button type="button" data-mode="orders" aria-pressed="'+(state.mode==='orders')+'">订单数</button></div><div class="fca-grid"><section class="fca-panel"><h3>分类趋势<span class="fca-unit">'+(state.mode==='sales'?'USD':'订单数')+'</span></h3><p class="fca-note">悬停或键盘聚焦看原值；已识别自然日可点击下钻。</p><div id="fca-sales" class="fca-plot"></div><div id="fca-sales-legend" class="fca-legend"></div></section><section class="fca-panel"><h3 id="fca-margin-title">分类利润率</h3><p id="fca-margin-note" class="fca-note">原生比例，不按日平均。</p><div id="fca-margin" class="fca-plot"></div><div id="fca-margin-legend" class="fca-legend"></div></section><section class="fca-panel" style="grid-column:1/-1"><h3>销售额占比变化<span class="fca-unit">%</span></h3><p class="fca-note">分母为相同时间桶的Order全部类型销售额；其他为算术差额，不是新业务分类。</p><div id="fca-share" class="fca-plot"></div><div id="fca-share-legend" class="fca-legend"></div></section></div><section class="fca-panel fca-heat-section" id="fca-heat-section" hidden><h3>销售日历<span class="fca-unit">FC27全部类型 · USD</span></h3><p class="fca-note" id="fca-heat-note"></p><div class="fca-heat-grid" id="fca-heat-grid"></div></section><details><summary class="fca-summary">查看原始类型与指标口径</summary><p class="fca-note">Items覆盖原始类型2，尚未细拆Players/Packs/SBC。客户指标属于FC27全部品类，不分摊给分类。后台未公开毛/净利润及成本公式，不推算利润金额；商品TOP在可验证交易明细接入后开放。</p><div class="fca-table-wrap"><table class="fca-table"><thead><tr><th>原始类型</th><th>ID</th><th>Order订单数</th><th>销售额 USD</th></tr></thead><tbody>'+((a?.originalTypes||[]).map(r=>'<tr><td>'+esc(r.mapping==='unmapped'?'待分类 · '+r.rawName:r.rawName)+'</td><td>'+esc(r.rawTypeId)+'</td><td>'+count(r.orders)+'</td><td>'+money(r.revenueUsd)+'</td></tr>').join('')||'<tr><td colspan="4">'+(loading?'待读取':'未提供')+'</td></tr>')+'</tbody></table></div></details>';
 host.querySelectorAll('[data-focus]').forEach(b=>b.onclick=()=>{state.focus=b.dataset.focus;render();});host.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{state.mode=b.dataset.mode;render();});host.querySelector('#fca-retry')?.addEventListener('click',()=>update(state.data,state.selection,true));
 if(disabled){host.querySelectorAll('.fca-plot').forEach(p=>p.innerHTML='<div class="fca-empty">'+(loading?'正在读取…':'暂无当前区间分类数据')+'</div>');return;}
 const cats=activeCats(a);host.querySelector('#fca-sales-legend').innerHTML=legend(cats);plotLine(host.querySelector('#fca-sales'),cats.map(c=>({key:c.key,label:c.label,rows:chartRows(c).map(row=>({label:row.label,value:state.mode==='sales'?row.amount:row.orders,note:'Order原生数据 · 采集 '+stamp(c.capturedAt)}))})),state.mode==='sales'?'销售额 USD':'订单数',state.mode==='sales'?money:count);plotMargins(a);shares(a);heatmap(a);
}
function pause(ms,signal){return new Promise((resolve,reject)=>{const id=setTimeout(resolve,ms);signal.addEventListener('abort',()=>{clearTimeout(id);reject(new DOMException('Aborted','AbortError'));},{once:true});});}
async function load(d,s,signal){const query=new URLSearchParams({profile:'FC27',start:s.start,end:s.end,grain:'day',snapshotId:d.snapshotId,analysis:'fc27-categories'}),end=Date.now()+360000;
 while(Date.now()<end){const r=await fetch('/dashboard/fs-home/range.json?'+query,{credentials:'same-origin',cache:'no-store',redirect:'error',signal}),x=await r.json();if(r.status===202||r.status===429){await pause(Math.min(10,x.retryAfter||2)*1000,signal);continue;}if(!r.ok)throw Error('category_unavailable');if(x.baseSnapshotId!==d.snapshotId||x.query?.profile!=='FC27'||x.query?.analysis!=='fc27-categories'||x.query.start!==s.start||x.query.end!==s.end||x.fc27Analytics?.contractId!=='fc27-order-types-v1')throw Error('invalid_category_contract');return x.fc27Analytics;}throw Error('category_timeout');}
function match(period,s){return period&&period.start===s.start+' 00:00'&&period.end.slice(0,10)===(period.end.endsWith('00:00')?dateShift(s.end,1):s.end);}
function update(d,s,retry=false){if(!d||!s?.start||!s?.end)return;const id=selectionKey(d,s);if(!retry&&state.id===id)return;const sameRange=state.selection?.start===s.start&&state.selection?.end===s.end,retained=sameRange?state.result:null,retainedBase=state.resultBase||state.data;state.controller?.abort();const controller=new AbortController();state={...state,id,controller,data:d,selection:s,result:retained,resultBase:retained?retainedBase:null,status:retained?'refreshing':'loading'};render();
 const stored=cache.get(id),snapshot=d.fc27Analytics,source=snapshot?.status==='available'&&match(snapshot.period,s)?snapshot:snapshot?.history?.status==='available'&&match(snapshot.history.period,s)?{...snapshot.history,dailyMetrics:snapshot.dailyMetrics}:null;
 if(stored||source){state.result=stored||source;state.resultBase=d;state.status='available';render();return;}
 (async()=>{try{await pause(350,controller.signal);const a=await load(d,s,controller.signal);if(state.id!==id||controller.signal.aborted)return;cache.set(id,a);if(cache.size>12)cache.delete(cache.keys().next().value);state.result=a;state.resultBase=d;state.status='available';render();}catch(e){if(controller.signal.aborted||state.id!==id)return;state.status=state.result?'stale':'error';render();}})();
}
root.addEventListener('fc27-selection',e=>update(e.detail.data,e.detail.selection));root.addEventListener('fs-business-theme',render);new MutationObserver(()=>{if(state.result)render();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});root.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(render,150);});
root.addEventListener('keydown',e=>{if(e.key==='Escape')tooltip.hidden=true;});render();if(root.FCAnalyticsBridge?.current())update(root.FCAnalyticsBridge.current(),root.FCAnalyticsBridge.selection());
root.FCAnalyticsView={getState:()=>({id:state.id,status:state.status,focus:state.focus,mode:state.mode}),refresh:()=>update(state.data,state.selection,true)};
})(window);
