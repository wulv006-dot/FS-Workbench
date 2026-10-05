(function(root){'use strict';
const nf=new Intl.NumberFormat('en-US'),usd=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'});
const text=(tag,value,cls)=>{const e=document.createElement(tag);if(value!=null)e.textContent=value;if(cls)e.className=cls;return e;};
const value=(m,key)=>m?.[key]?.value??null;
const count=n=>Number.isFinite(n)?nf.format(n):'未提供';
const money=n=>Number.isFinite(n)?usd.format(n):'未提供';
const pct=n=>Number.isFinite(n)?n.toFixed(2)+'%':'未提供';
function color(n){if(!Number.isFinite(n))return '#e7eaf0';const t=Math.min(Math.abs(n)/50,1);return n<0?`hsl(8 72% ${93-t*30}%)`:`hsl(158 52% ${94-t*38}%)`;}
function metricCard(label,number,detail){const e=text('article',null,'fsi-metric');e.append(text('span',label),text('strong',number),text('small',detail));return e;}
function table(title,rows,note,readState=null){const box=text('article',null,'fsi-dimension');box.append(text('h4',title),text('p',note,'fsi-note'));
 if(readState){box.append(text('p',readState==='loading'?'待读取':'读取失败，可重试','fsi-empty'));return box;}
 if(!Array.isArray(rows)){box.append(text('p','未提供','fsi-empty'));return box;}
 if(!rows.length){box.append(text('p','本期无记录','fsi-empty'));return box;}
 const scroller=text('div',null,'fsi-table-scroll'),t=text('table'),head=text('thead'),hr=text('tr');
 ['名称','订单数','金额 USD'].forEach(v=>hr.append(text('th',v)));head.append(hr);t.append(head);const body=text('tbody');
 rows.slice().sort((a,b)=>(b.orders??-1)-(a.orders??-1)).forEach(r=>{const tr=text('tr');tr.append(text('td',r.name||r.code||'未命名'),text('td',count(r.orders)),text('td',money(r.revenueUsd??r.amountUsd)));body.append(tr);});
 t.append(body);scroller.append(t);box.append(scroller);return box;
}
function layouts(items,x,y,w,h,out=[]){
 if(items.length===1){out.push({...items[0],x,y,w,h});return out;}
 const sum=items.reduce((a,i)=>a+i.amount,0);let a=0,k=0;
 while(k<items.length-1&&a<sum/2)a+=items[k++].amount;
 k=Math.max(1,k);const ratio=a/sum;
 if(w>=h){layouts(items.slice(0,k),x,y,w*ratio,h,out);layouts(items.slice(k),x+w*ratio,y,w*(1-ratio),h,out);}
 else{layouts(items.slice(0,k),x,y,w,h*ratio,out);layouts(items.slice(k),x,y+h*ratio,w,h*(1-ratio),out);}return out;
}
function projectRows(data){return Object.entries(data.profiles||{}).filter(([key])=>key!=='MMOEXP').map(([key,p])=>({key,name:p.name||key,amount:p.metrics?.revenueUsd?.value,
 rate:value(p.metrics,'profitMarginPct'),profit:null,period:p.period,
 status:p.primary?.filters?.status==='3'?'已完成':'全部状态'}));}
function renderMap(host,data,readState=null){const block=text('article',null,'fsi-map'),head=text('div',null,'fsi-map-head');head.append(text('h3','项目利润地图'),text('span','颜色：利润率 · 面积：主源营收','fsi-note'));block.append(head);
 if(readState){block.append(text('p',readState==='loading'?'所选项目准确区间待读取，利润地图稍后更新。':'所选区间读取失败，可重试后查看利润地图。','fsi-empty'));host.append(block);return;}
 const all=projectRows(data),rows=all.filter(r=>Number.isFinite(r.amount)&&r.amount>0).sort((a,b)=>b.amount-a.amount),detail=text('p','选择项目查看营收、利润率及统计区间。','fsi-map-detail');
 const total=value(data.profiles?.MMOEXP?.metrics,'profitMarginPct');
 block.append(text('p','全站Order利润率：'+pct(total)+' · 采用主源全站原值，不平均项目比例；成本及毛/净公式未公开。','fsi-note'));
 if(!all.some(r=>Number.isFinite(r.rate)))block.append(text('p','当前版本未提供可验证的Order利润率，灰色表示未提供，不能视为零利润。','fsi-empty'));
 if(rows.length){const scale=1000/Math.max(280,host.clientWidth-40),ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 1000 350');svg.setAttribute('class','fsi-treemap');svg.setAttribute('aria-label','按项目营收分配面积的利润地图，灰色项目利润率未提供');svg.setAttribute('role','group');
 for(const r of layouts(rows,0,0,1000,350)){
  const g=document.createElementNS(ns,'g'),rect=document.createElementNS(ns,'rect');rect.setAttribute('x',r.x);rect.setAttribute('y',r.y);rect.setAttribute('width',r.w);rect.setAttribute('height',r.h);rect.setAttribute('fill',color(r.rate));rect.setAttribute('stroke','#fff');rect.setAttribute('stroke-width','2');g.append(rect);
  const title=document.createElementNS(ns,'title');title.textContent=r.name+' · '+money(r.amount)+' · 利润率 '+pct(r.rate)+' · '+r.status;g.append(title);g.setAttribute('tabindex','0');g.setAttribute('role','button');g.setAttribute('aria-label',title.textContent);
  const select=()=>{detail.textContent=r.name+' · Order营收 '+money(r.amount)+' · Order利润率 '+pct(r.rate)+' · 利润金额 '+money(r.profit)+' · '+r.status+' · '+(r.period?.start||'—')+' 至 '+(r.period?.end||'—');};g.addEventListener('click',select);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}});
  if(r.w>85*scale&&r.h>42*scale){for(const [i,s] of [r.name,pct(r.rate)].entries()){const label=document.createElementNS(ns,'text');label.setAttribute('x',r.x+9*scale);label.setAttribute('y',r.y+(23+i*19)*scale);label.setAttribute('font-size',(i?13:16)*scale);label.setAttribute('fill','#263347');label.textContent=s;g.append(label);}}
  svg.append(g);
 }block.append(svg);}
 else block.append(text('p','当前项目无可绘制营收记录。','fsi-empty'));
 block.append(detail);const legend=text('div',null,'fsi-map-legend');for(const [label,c] of [['负利润','#edb1a3'],['0%','#eff9f3'],['正利润','#69bc9a'],['未提供','#e7eaf0']]){const item=text('span',label),i=text('i');i.style.background=c;item.prepend(i);legend.append(item);}block.append(legend);
 const list=text('div',null,'fsi-project-list');for(const r of all){const item=text('span',r.name+' '+money(r.amount)+' / '+pct(r.rate));list.append(item);}block.append(list);host.append(block);
}
function render(host,data,key='MMOEXP',selection=null,readState=null){
 data=root.FSBusinessRange?.select(data,selection)||data;
 if(!host)return;host.classList.add('fsi');host.replaceChildren();const p=data?.profiles?.[key];if(!p){host.append(text('p','补充统计未提供','fsi-empty'));return;}
 const phase=['loading','error'].includes(readState)?readState:null,placeholder=phase==='loading'?'待读取':'读取失败';host.dataset.rangeReadState=phase||'available';
 const showCount=n=>phase?placeholder:count(n),showMoney=n=>phase?placeholder:money(n),showPct=n=>phase?placeholder:pct(n);
 const s=p.supplement,m=s?.metrics||{},d=s?.dimensions||{},period=s?.period||p.period;
 const head=text('div',null,'fsi-heading');head.append(text('h3','客户、付款与利润'),text('p',(p.name||key)+' · '+(period?.start||'—')+' 至 '+(period?.end||'—')+' · 北京时间','fsi-note'));host.append(head);
 const makeCard=(label,n,detail)=>metricCard(label,n,phase?(phase==='loading'?'正在读取所选区间后台原值':'读取失败，可重试'):detail);
 const cards=text('div',null,'fsi-metrics');
 cards.append(makeCard('Order订单数量',showCount(value(p.metrics,'orders')),p.rangeSelected?'所选区间 · '+(p.rangeExact?'Order后台原值':'Order订单桶合计；缺少非可加指标聚合'):'Order后台原值 · 快照当日'),makeCard('Order订单金额',showMoney(value(p.metrics,'revenueUsd')),p.rangeSelected?'所选区间 · '+(p.rangeExact?'Order后台原值':'Order订单桶合计；缺少非可加指标聚合'):'Order后台原值 · 快照当日'),makeCard('Order单均价',showMoney(value(p.metrics,'averageOrderUsd')),p.rangeSelected?'所选区间 · '+(p.rangeExact?'Order后台原值':'Order订单桶合计；缺少非可加指标聚合'):'Order后台原值 · 快照当日'),makeCard('Order项目利润率',showPct(value(p.metrics,'profitMarginPct')),p.rangeSelected?'所选区间 · 未提供时不平均每日利润率':'Order后台原值 · 毛/净公式未公开'));
 for(const [label,k,format] of [['新客人数','newCustomers',count],['付款人数','payingCustomers',count],['新客付款金额','newCustomerRevenueUsd',money],['后台复购率','repeatRatePct',pct],['新客占比','newCustomerSharePct',pct],['纯销售额','pureSalesUsd',money],['退款金额','refundAmountUsd',money],['退款订单','refundOrders',count],['发货完成率','fulfillmentRatePct',pct],['支付成功率','paymentSuccessRatePct',pct]]){
  const item=m[k],desc=k==='newCustomerSharePct'?'admin新客 '+showCount(value(m,'newCustomers'))+' ÷ admin订单 '+showCount(value(m,'orders'))+' × 100':item?.definition||'补源未提供';
  const primary=p.metrics?.[k],selected=primary?.value!=null?primary:item;
  cards.append(makeCard(label,phase?placeholder:selected?.status==='not_computable'?'不可计算':format(selected?.value??null),selected?.source==='primary'?'Order后台原值':desc));
 }host.append(cards);if(p.rangeSelected&&!p.rangeCovered)host.append(text('p','所选区间超出快照覆盖或无记录，无法提供完整区间数字。','fsi-empty'));if(p.rangeSelected)host.append(text('p','所选区间：订单和金额按Order时间桶汇总；仅区间完全匹配时采用后台原值。人数、单均价原值、利润率、复购率及维度缺少该区间准确聚合时显示未提供，不能视为零。','fsi-note'));
 host.append(text('p','补源：admin订单统计 · 更新 '+(s?.capturedAt?new Date(s.capturedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—')+' 北京时间 · 复购率直接采用后台原值。纯销售额不是利润。','fsi-note'));
 const pm=p.metrics||{};
 host.append(text('p','Order主源金额项：最小订单 '+showMoney(value(pm,'minOrderAmountUsd'))+' · 最大订单 '+showMoney(value(pm,'maxOrderAmountUsd'))+' · 收款总额 '+(phase?placeholder:value(pm,'receiptsCny')===null?'未提供':'¥'+showCount(value(pm,'receiptsCny'))+' CNY')+' · 货款总额 '+(phase?placeholder:value(pm,'goodsPaymentCny')===null?'未提供':'¥'+showCount(value(pm,'goodsPaymentCny'))+' CNY')+'；保留原币种，不与USD销售额混算利润。','fsi-note'));
 renderMap(host,data,phase);
 const dims=text('div',null,'fsi-dimensions');const primary=p.dimensions;
 dims.append(table('来源渠道金额',primary?.channels,'order来源图；金额优先主源，未提供每渠道订单数',phase),table('网站来源分布',d.channels,'admin site_rank；不是GA4营销归因渠道',phase),table('国家 / 地区',d.countries,'admin country_rank；订单数与金额',phase),table('付款设备',d.devices,'admin chart_pay_device；按订单分布，未提供设备金额',phase),table('支付方式',d.payments,'admin chart_pay_style；订单数与金额',phase));
 host.append(dims);
}
root.FSSupplementInsights={render,color,layouts,projectRows};
})(typeof window!=='undefined'?window:globalThis);
