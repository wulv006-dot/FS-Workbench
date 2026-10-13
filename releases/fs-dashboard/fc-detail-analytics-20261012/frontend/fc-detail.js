// This fragment runs inside the existing business mount and shares its date/auth lifecycle.
const fcTabs=[['overview','总览'],['consumption','用户与消费'],['fulfillment','履约与问题'],['structure','结构与分布'],['review','日报与复盘']];
const fcLabels={main:'MMOEXP主站',satellite:'卫星子站',new:'新客',returning:'老客',unknown:'未知'};
let fcHost=null,fcAbort=null,fcDrawerAbort=null,fcDrawerQuery=null,fcDrawerData=null,fcUserView=false,fcDimension='platform',fcPool='paid',fcNote='';
const fcSetText=(node,text)=>{if(node&&node.textContent!==text)node.textContent=text;};
const fcWait=(ms,signal)=>new Promise((resolve,reject)=>{const cancel=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},ms);if(signal.aborted)cancel();else signal.addEventListener('abort',cancel,{once:true});});
const fcFilters={platform:'all',site_group:'main',customer:'all',product:'all',bucket:'all'};
const fcMoney=v=>v==null?'暂缺':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const fcName=v=>fcLabels[v]||v;
const fcTable=(heads,rows)=>`<div class="fc-table-wrap"><table><thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${heads.length}">当前筛选暂无记录。</td></tr>`}</tbody></table></div>`;
const fcQuery=(extra={})=>({mode:'fc-detail',profile:'FC27',...currentSelection(),...fcFilters,pool:fcDetailState.tab==='fulfillment'?fcPool:'paid',...extra});
const fcDownload=(name,content,type)=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([content],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};

function fcDetailInit(){
 if(fcHost)return;
 fcHost=document.createElement('section');fcHost.id='fc-detail';document.getElementById('supplement-insights').after(fcHost);
 fcHost.innerHTML=`<div class="fc-toolbar"><div class="fc-heading"><b>FC27 经营看板</b><span>主站详细分析 · 子站汇总</span></div><label>平台 <select data-fc-filter="platform" aria-label="FC游戏平台"><option value="all">全部</option><option>PS</option><option>XBOX</option><option>PC</option><option value="unknown">未知</option></select></label><label class="fc-scope-filter">站点 <select data-fc-filter="site_group" aria-label="FC站点范围"><option value="all">主站 + 卫星子站</option><option value="main">MMOEXP主站</option><option value="satellite">卫星子站合计</option></select></label><details class="fc-more-filters"><summary>更多筛选</summary><div class="fc-more"><label>客户 <select data-fc-filter="customer" aria-label="FC客户类型"><option value="all">全部</option><option value="new">新客</option><option value="returning">老客</option><option value="unknown">未知</option></select></label><label>商品 <select data-fc-filter="product" aria-label="FC商品分类"><option value="all">全部</option>${['Coins','Items','Boosting','Accounts','Top Up','多品类','待分类'].map(v=>`<option>${v}</option>`).join('')}</select></label><label>金额档 <select data-fc-filter="bucket" aria-label="FC金额档"><option value="all">全部</option></select></label></div></details><div class="fc-toolbar-actions"><button type="button" data-fc-retry>更新明细</button><button type="button" data-fc-csv>导出明细</button></div></div><nav class="fc-tabs" role="tablist" aria-label="FC详细分析">${fcTabs.map(([key,label])=>`<button type="button" role="tab" data-fc-tab="${key}" aria-controls="fc-panel-${key}">${label}</button>`).join('')}</nav><p class="fc-state" role="status"></p><div class="fc-filter-tags"></div><div class="fc-panels">${fcTabs.map(([key,label])=>`<section id="fc-panel-${key}" role="tabpanel" aria-label="${label}" hidden></section>`).join('')}</div><dialog class="fc-drawer" aria-label="FC订单下钻"><header><h2>订单下钻</h2><button type="button" data-fc-close aria-label="关闭订单抽屉">关闭</button></header><div class="fc-drawer-content"></div></dialog>`;
 fcHost.addEventListener('change',e=>{const key=e.target.dataset.fcFilter;if(key){fcFilters[key]=e.target.value;fcDetailState.key='';fcDetailSync();}});
 fcHost.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.fcTab){fcDetailState.tab=b.dataset.fcTab;fcDetailShow();workspaceSync();}
  if(b.hasAttribute('data-fc-yesterday')){GRAIN='day';RANGE='yesterday';CUSTOM=null;selectionAnchor=todayStr();renderTabs();renderToolbar();renderAll();fcDetailState.tab='overview';fcDetailState.key='';fcDetailSync();workspaceSync();}
  if(b.dataset.fcDrill!==undefined)fcDrill({bucket:b.dataset.fcDrill,issue:b.dataset.fcIssue||'false',pool:'paid'});
  if(b.hasAttribute('data-fc-backlog'))fcDrill({pool:'current',list:'orders'});
  if(b.dataset.fcOrder)fcOrder(b.dataset.fcOrder);
  if(b.hasAttribute('data-fc-return'))fcDrawerRender();
  if(b.hasAttribute('data-fc-close'))fcHost.querySelector('dialog').close();
  if(b.dataset.fcPage)fcDrill({...fcDrawerQuery,page:b.dataset.fcPage});
  if(b.dataset.fcPool){fcPool=b.dataset.fcPool;fcDetailState.key='';fcDetailSync();}
  if(b.dataset.fcView){fcUserView=b.dataset.fcView==='user';fcDetailDraw();}
  if(b.dataset.fcDimension){fcDimension=b.dataset.fcDimension;fcDetailDraw();}
  if(b.dataset.fcSlice)fcDrill({[fcDimension]:b.dataset.fcSlice,pool:'paid'});
  if(b.hasAttribute('data-fc-csv'))fcExportCsv();
  if(b.hasAttribute('data-fc-report'))fcReport();
  if(b.hasAttribute('data-fc-retry')){fcDetailState.key='';fcDetailSync(true);}
  if(b.dataset.fcClear){fcFilters[b.dataset.fcClear]='all';fcHost.querySelector(`[data-fc-filter="${b.dataset.fcClear}"]`).value='all';fcDetailState.key='';fcDetailSync();}
 });
 fcHost.querySelector('.fc-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...fcHost.querySelectorAll('[role=tab]')],i=tabs.indexOf(document.activeElement),n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].click();tabs[n].focus();});
 fcHost.querySelector('dialog').addEventListener('close',()=>{fcDrawerAbort?.abort();fcHost.querySelector(`[data-fc-tab="${fcDetailState.tab}"]`)?.focus();});
 scope.signal.addEventListener('abort',()=>{fcAbort?.abort();fcDrawerAbort?.abort();},{once:true});
 for(const [key,value]of Object.entries(fcFilters))fcHost.querySelector(`[data-fc-filter="${key}"]`).value=value;
}

function fcDetailShow(){
 if(!fcHost)return;
 const on=KEY==='FC27';fcHost.hidden=!on;
 const body=fcHost.closest('.native-body');if(body.classList.contains('fc-view')!==on)body.classList.toggle('fc-view',on);
 if(!on){fcAbort?.abort();fcDrawerAbort?.abort();fcDetailState.key='';}
 for(const id of ['sideNav','secStruct','gameCard','geoCard','payRow','secDetail','tblCard','secCross','crossCard','profitWrap','calCard','fc-types']){const node=document.getElementById(id);if(node){if(on&&node.dataset.fcPreviousHidden===undefined)node.dataset.fcPreviousHidden=String(node.hidden);node.hidden=on?true:node.dataset.fcPreviousHidden==='true';if(!on)delete node.dataset.fcPreviousHidden;}}
 for(const id of ['secTrend','trendCard']){const node=document.getElementById(id);if(node)node.hidden=on&&fcDetailState.tab!=='overview';}
 const metrics=document.getElementById('supplement-insights');if(metrics){metrics.hidden=false;if(on){if(metrics.parentNode!==fcHost)fcHost.insertBefore(metrics,fcHost.querySelector('.fc-tabs'));[...metrics.querySelectorAll('.fsi-metric')].forEach((card,index)=>{card.hidden=!scope.metrics&&index>3;});}else if(metrics.parentNode===fcHost)fcHost.before(metrics);}
 if(on&&fcDetailState.data?.coverage.paid_complete){const label={main:'MMOEXP主站',satellite:'卫星子站合计',all:'主站 + 卫星子站'}[fcFilters.site_group],cards=metrics.querySelectorAll('.fsi-metric');fcSetText(cards[0]?.querySelector('span'),label+'订单数');fcSetText(cards[1]?.querySelector('span'),label+'销售额');fcSetText(metrics.querySelector('.fsi-reference-total'),'FC订单与销售额使用同一筛选；利润率为Order全站参考，预估利润不是实结。');}
 for(const note of document.querySelectorAll('#trendCard .order-reference-label')){if(on&&fcDetailState.data?.coverage.paid_complete){note.dataset.fcPreviousText??=note.textContent;fcSetText(note,'订单量与销售额来自FC订单明细及当前筛选。');}else if(note.dataset.fcPreviousText){fcSetText(note,note.dataset.fcPreviousText);delete note.dataset.fcPreviousText;}}
 for(const id of ['pfPane','pfDiv']){const node=document.getElementById(id);if(node)node.hidden=on;}
 const reference=document.querySelector('[aria-label="参考展示范围"]');if(reference){const holder=reference.closest('label')||reference;holder.hidden=on;}
 if(!on)return;
 for(const b of fcHost.querySelectorAll('[role=tab]')){const active=b.dataset.fcTab===fcDetailState.tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;}
 for(const [key] of fcTabs)fcHost.querySelector('#fc-panel-'+key).hidden=key!==fcDetailState.tab;
}

async function fcRead(query,signal,onSnapshot){
 const q={...query};
 const deadline=Date.now()+920000;
 do{if(signal.aborted)throw new DOMException('Aborted','AbortError');const r=await fetch('/dashboard/fs-home/range.json?'+new URLSearchParams(q),{signal,credentials:'same-origin',cache:'no-store'});const d=await r.json();
  delete q.refresh;
  if(r.status===202||r.status===429){await fcWait(Math.min(30,Math.max(3,d.retryAfter||3))*1000,signal);continue;}
  if(!r.ok||d.contractId!=='fc27-detail-analytics-v1'||d.query?.start!==q.start||d.query?.end!==q.end||!d.snapshot_id)throw Error('FC明细暂不可用，未将失败显示成零。');
  // Cached data is usable during refresh; only the visible dashboard follows the refresh.
  if(onSnapshot)onSnapshot(d);
  if(onSnapshot&&d.refreshing){await fcWait(10000,signal);continue;}
  return d;
 }while(Date.now()<deadline&&!signal.aborted);throw Error('FC明细读取超时，保留已取得的快照。');
}

function fcDetailSync(refresh=false){
 if(KEY!=='FC27'){fcDetailShow();return;}
 fcDetailInit();fcDetailShow();const q=fcQuery(),key=JSON.stringify(q);
 if(fcDetailState.key===key&&!refresh)return;
 if(refresh)q.refresh='true';
 fcAbort?.abort();fcAbort=new AbortController();fcDetailState.key=key;fcDetailState.error='';
 if(fcDetailState.data?.query.start!==q.start||fcDetailState.data?.query.end!==q.end||JSON.stringify(fcDetailState.data.query.platform)!==JSON.stringify(q.platform)||fcDetailState.data.query.customer!==q.customer||fcDetailState.data.query.bucket!==q.bucket||fcDetailState.data.query.site_group!==q.site_group||fcDetailState.data.query.product!==q.product)fcDetailState.data=null;
 fcDetailDraw();
 if(q.grain!=='day'){fcDetailState.error='FC明细暂按自然日提供；小时粒度可继续查看原总览。';fcDetailDraw();return;}
 const controller=fcAbort;
 const present=d=>{if(scope.signal.aborted||controller!==fcAbort||controller.signal.aborted)return;const previous=fcDetailState.data;fcDetailState.data=d;if(previous?.snapshot_id===d.snapshot_id&&previous.stale===d.stale&&previous.refreshing===d.refreshing&&previous.refresh_error===d.refresh_error)return;fcDetailDraw();kpiCards();renderMain();fcDetailShow();if(d.coverage.paid_complete){const note=document.getElementById('mainNote');fcSetText(note,d.scope_label+' · 与金额分档使用同一批订单与筛选');note.style.display='block';}workspaceSync();};
 (async()=>{try{await fcRead(q,controller.signal,present);}catch(e){if(scope.signal.aborted||controller!==fcAbort||controller.signal.aborted)return;fcDetailState.error=e.message;fcDetailDraw();}})();
}

function fcDetailDraw(){
 if(!fcHost)return;const d=fcDetailState.data;
 fcHost.querySelector('.fc-state').textContent=fcDetailState.error||(d?`${d.scope_label} · ${d.query.start} 至 ${d.query.end} · 读取 ${new Date(d.as_of).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} 北京时间${d.stale?(d.refreshing?' · 显示上次快照，后台更新中': ' · 上次快照，尚未更新'):''}${d.data_status==='partial'?' · 部分可用，缺失日不补零':''}${d.refresh_error?' · 最近刷新失败，保留原快照':''}`:'首次读取这个日期范围，正在采集订单。完成后页签和筛选共用快照，可先切换其他视图。');
 fcHost.querySelector('.fc-filter-tags').innerHTML=Object.entries(fcFilters).filter(([k,v])=>v!=='all'&&!['platform','site_group'].includes(k)).map(([k,v])=>`<button type="button" data-fc-clear="${k}">${esc(fcName(v))} ×</button>`).join('');
 if(!d){for(const [key]of fcTabs)fcHost.querySelector('#fc-panel-'+key).innerHTML=fcDetailState.error?'<button type="button" data-fc-retry>重试 FC 明细</button>':'';return;}
 const bucketSelect=fcHost.querySelector('[data-fc-filter=bucket]');if(bucketSelect.options.length===1){for(const b of d.buckets){const option=document.createElement('option');option.value=b.key;option.textContent=b.label;bucketSelect.append(option);}}
 for(const option of fcHost.querySelectorAll('[data-fc-filter=customer] option'))if(['new','returning'].includes(option.value))option.disabled=d.customer_status!=='available';
 const groupRows=['main','satellite'].map(group=>{const r=d.site_groups.find(r=>r.key===group)||{orders:0,revenue_usd:0};return `<div><b>${esc(fcName(group))}</b><span>${r.orders} 单 · ${fcMoney(r.revenue_usd)}</span></div>`;}).join('');
 fcHost.querySelector('#fc-panel-overview').innerHTML=`<div class="fc-overview-grid"><article class="fc-card fc-site-card"><h3>销售来源</h3><div class="fc-site-groups">${groupRows}</div><p>MMOEXP 为主要分析对象；其他站点按 FC 项目合计。</p></article><article class="fc-card fc-attention-card"><h3>运营关注</h3>${d.signals.length?d.signals.map(s=>`<p>${esc(s.text)} <button type="button" data-fc-tab="${s.tab}">查看 →</button></p>`).join(''):'<p>当前快照没有命中已接通的关注规则。</p>'}</article></div><div class="fc-shortcuts"><button type="button" data-fc-tab="consumption">消费结构 · ${d.totals.orders} 单 →</button><button type="button" data-fc-tab="fulfillment">当前未结案 · ${d.backlog_summary?.orders??'暂缺'} 单 →</button></div><details class="fc-explanation"><summary>FC明细的数据说明与缺口</summary><p>${esc(d.customer_basis)}；用户按站内客户 ID 去重，访客未伪造用户 ID。</p><p>订单金额为后台 USD 字段；缺金额 ${d.totals.unpriced_orders} 单。商品按订单主分类，多品类不重复计金额。</p><p>站点按你本轮口径分为主站与卫星子站，卫星站不逐站拆分。独立分销店铺标识尚未取得，未按引荐词或双源差额扣数据；当前覆盖为 Admin 网站订单。</p><p>缺失日期：${esc(d.coverage.missing_days?.join('、')||'无')}；当前未结案池：${d.coverage.backlog_status==='partial'?'部分可用，合计暂缺':'分页读取完成'}。</p><p>当前原因保留“待确认”，未读取账号资料或原始客服备注。支付日与当前未结案池分别统计；后者没有支付日期截断。</p></details>`;
 const total=d.totals.orders;
 const bucketRows=d.buckets.map(b=>`<tr><td><button type="button" data-fc-drill="${b.key}">${b.key==='unpriced'?'':'$'}${esc(b.label)}</button></td><td>${b.orders}</td><td>${total?(b.orders/total*100).toFixed(1)+'%':'—'}</td>${d.customer_status==='available'?`<td>${b.new}</td><td>${b.returning}</td><td>${b.unknown}</td>`:''}<td>${fcMoney(b.revenue_usd)}</td><td><button type="button" data-fc-drill="${b.key}" data-fc-issue="true">${b.issues}</button></td></tr>`);
 const chart=d.buckets.filter(b=>b.key!=='unpriced').map(b=>{const max=Math.max(...d.buckets.map(r=>r.orders),1);return `<div class="fc-bar-row"><button type="button" data-fc-drill="${b.key}">$${esc(b.label)}</button><div class="fc-bar-track">${[['new','新客'],['returning','老客'],['unknown','未知']].map(([key,label])=>`<span data-customer="${key}" style="width:${b[key]/max*100}%" title="${label} ${b[key]} 单"></span>`).join('')}</div><span>${b.orders}</span></div>`;}).join('');
 const userRows=d.user_buckets.map(b=>`<tr><td>$${esc(b.label)}</td><td>${b.users}</td><td>${fcMoney(b.revenue_usd)}</td></tr>`);
 fcHost.querySelector('#fc-panel-consumption').innerHTML=`<div class="fc-actions"><button type="button" data-fc-view="order" aria-pressed="${!fcUserView}">按订单金额</button><button type="button" data-fc-view="user" aria-pressed="${fcUserView}">按用户累计</button></div><article class="fc-card"><h3>${fcUserView?'用户累计消费':'订单金额分布'}</h3>${fcUserView?fcTable(['累计金额档','可识别用户数','金额小计'],userRows):`<p class="fc-subtle">${esc(d.customer_basis)}</p><div class="fc-consumption-grid"><div class="fc-bars">${chart}</div>${fcTable(['金额档','订单数','占比',...(d.customer_status==='available'?['新客','老客','未知']:[]),'USD','问题单'],bucketRows)}</div>`}<p>${fcUserView?`按站内 ID 去重；${d.orders_without_customer_id} 单没有可用客户 ID，未计为独立用户。跨站同人可能重复。`:'各档 + 金额暂缺回到本视图订单总数；$20 进入 20–40 档。'}</p></article>`;
 const problem=fcPool==='current'?d.backlog_summary:d.totals;
 fcHost.querySelector('#fc-panel-fulfillment').innerHTML=`<div class="fc-actions"><button type="button" data-fc-pool="paid" aria-pressed="${fcPool==='paid'}">所选支付日订单</button><button type="button" data-fc-pool="current" aria-pressed="${fcPool==='current'}">当前积压</button></div><p>${fcPool==='current'?'当前全部未结案 · 不按所选支付日期截断':'所选支付日期订单的当前状态；不代表当日新增或解决事件。'}</p><article class="fc-card"><h3>履约与问题</h3><div class="fc-status-grid">${[['问题单',problem?.issues],['待交付',problem?.unfinished],['资金待处理',problem?.funding],['涉及金额',fcMoney(problem?.revenue_usd)]].map(([label,value])=>`<div><span>${label}</span><strong>${value??'暂缺'}</strong></div>`).join('')}</div><p>当前等待超过 24 小时：${d.slow_orders??'暂缺'} 单（待跟进排序，非 SLA 违约判定）。</p><button type="button" data-fc-backlog>查看当前优先跟进订单 →</button><details><summary>当前原因与单龄说明</summary><p>缺结构化原因的订单为待确认；已完成、已退款和已结案记录不计当前积压。单龄优先按支付时间，只有下单时间时明确标注。</p></details></article>`;
 const dimensions=[['platform','游戏平台'],['product','商品分类'],['country','国家'],['payment','支付'],['device','访问设备'],['hour','时段'],['site_group','主站 / 子站']];
 const records=d.dimensions[fcDimension]||[],head=dimensions.find(r=>r[0]===fcDimension)?.[1]||'分布';
 const dimensionRows=records.slice(0,10).map(r=>`<tr><td><button type="button" data-fc-slice="${esc(r.key)}">${esc(fcName(r.key))}</button></td><td>${r.orders}</td><td>${fcMoney(r.revenue_usd)}</td><td>${r.issues}</td></tr>`);
 const remaining=records.slice(10);if(remaining.length)dimensionRows.push(`<tr><td>其他 ${remaining.length} 项</td><td>${remaining.reduce((n,r)=>n+r.orders,0)}</td><td>${fcMoney(remaining.reduce((n,r)=>n+(r.revenue_usd||0),0))}</td><td>${remaining.reduce((n,r)=>n+r.issues,0)}</td></tr>`);
 fcHost.querySelector('#fc-panel-structure').innerHTML=`<div class="fc-actions">${dimensions.map(([key,label])=>`<button type="button" data-fc-dimension="${key}" aria-pressed="${fcDimension===key}">${label}</button>`).join('')}</div><article class="fc-card"><h3>${head}</h3>${fcTable([head,'订单数','USD','问题单'],dimensionRows)}<p>前十项，其他合并；游戏平台 PC 与访问设备 Desktop 分开。</p></article>`;
 fcHost.querySelector('#fc-panel-review').innerHTML=`<article class="fc-card"><h3>事实日报与复盘</h3><p>完整导出包括核心、消费分档、问题池、已接通的各项结构、生成时间与范围，不受折叠或当前页签影响。</p><button type="button" data-fc-report>生成并导出 HTML 日报</button><label class="fc-note-label">运营备注与下一步<textarea aria-label="FC运营备注" placeholder="写下需核查的问题、负责人和复核日期；备注随本次日报导出。"></textarea></label><p>共享跟进复用已有任务台：<a href="/dashboard/tasks/" target="_blank" rel="noopener">打开项目工作任务台</a>。此处备注尚不写入服务器。</p><details><summary>已保存日报说明</summary><p>规则日报快照由服务器保存，原版本保留；人工备注仅进入本次下载。二期 AI 关闭，不产生模型调用。</p></details><p class="fc-report-status" role="status"></p></article>`;
 const note=fcHost.querySelector('textarea');note.value=fcNote;note.addEventListener('input',()=>{fcNote=note.value;});
 fcDetailShow();
}

async function fcDrill(extra={}){
 fcDrawerAbort?.abort();const controller=fcDrawerAbort=new AbortController();fcDrawerQuery=fcQuery({page:'1',...extra});const dialog=fcHost.querySelector('dialog');if(!dialog.open)dialog.showModal();
 fcHost.querySelector('.fc-drawer-content').textContent='正在读取同一范围的订单…';
 try{const d=await fcRead(fcDrawerQuery,controller.signal);if(!scope.signal.aborted&&!controller.signal.aborted){fcDrawerData=d;fcDrawerRender();}}catch(e){if(!scope.signal.aborted&&!controller.signal.aborted)fcHost.querySelector('.fc-drawer-content').textContent=e.message;}
}
function fcDrawerRender(){
 const d=fcDrawerData;if(!d)return;
 const rows=d.orders.map(r=>`<tr><td><button type="button" data-fc-order="${esc(r.id)}">${esc(r.id)}</button></td><td>${esc(fcName(r.site_group))} / ${esc(r.platform)}<br>${esc(r.product)}</td><td>${fcMoney(r.amount_usd)}</td><td>${esc(fcName(r.customer))}</td><td>${r.age_hours==null?'—':r.age_hours+' 小时'}<br>${esc(r.age_basis||'')}</td><td>${esc(r.status)}<br>${esc(r.reason)}</td></tr>`);
 fcHost.querySelector('.fc-drawer-content').innerHTML=`<p>${d.stale?'上次快照 · ':''}${new Date(d.as_of).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} 北京时间<br>${esc(d.query.start)} 至 ${esc(d.query.end)} · ${d.query.pool==='current'?'当前全部未结案（日期不截断）':'支付日订单'} · ${esc(fcName(d.query.platform))} · ${esc(fcName(d.query.customer))} · 金额档 ${esc(d.query.bucket||'all')}</p>${fcTable(['订单','范围 / 商品','USD','客户','等待','当前状态'],rows)}<div class="fc-pagination"><button type="button" data-fc-page="${d.page-1}" ${d.page===1?'disabled':''}>上一页</button><span>第 ${d.page} 页 · ${d.list_total} 单 · 10 条/页</span><button type="button" data-fc-page="${d.page+1}" ${d.page*10>=d.list_total?'disabled':''}>下一页</button></div>`;
}
function fcOrder(id){const r=fcDrawerData?.orders.find(r=>r.id===id);if(!r)return;fcHost.querySelector('.fc-drawer-content').innerHTML=`<button type="button" data-fc-return>← 返回订单列表</button><h3>${esc(r.id)}</h3><dl>${[['范围',fcName(r.site_group)],['平台',r.platform],['商品',r.product],['USD',fcMoney(r.amount_usd)],['客户',fcName(r.customer)],['支付时间',r.paid_at||'暂缺'],['当前状态',r.status],['原因',r.reason],['等待时长',r.age_hours==null?'暂缺':r.age_hours+' 小时'],['优先关注',(r.attention||[]).join('、')||'无已命中规则']].map(([k,v])=>`<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl><a href="/dashboard/tasks/" target="_blank" rel="noopener">到已有任务台记录跟进</a><p>看板跟进不改变订单后台状态。</p>`;}
async function fcExportCsv(){try{const d=await fcRead(fcQuery({format:'csv'}),scope.signal);fcDownload(`FC27_${d.query.start}_${d.query.end}.csv`,d.csv,'text/csv;charset=utf-8');}catch(e){fcHost.querySelector('.fc-state').textContent=e.message;}}
async function fcReport(){
 const status=fcHost.querySelector('.fc-report-status');status.textContent='正在保存同一快照的事实日报…';
 try{const d=await fcRead(fcQuery({mode:'fc-report',page:'1',format:'json'}),scope.signal),r=d.report;
  const core=[...document.querySelectorAll('#supplement-insights .fsi-metric')].slice(0,4).map(c=>[c.querySelector('span').textContent,c.querySelector('strong').textContent,c.querySelector('small').textContent]);
  const section=(title,records,keyLabel)=>`<h2>${esc(title)}</h2>${fcTable([keyLabel,'数量','USD','问题单'],records.map(x=>`<tr><td>${esc(fcName(x.key||x.label))}</td><td>${x.orders??x.users}</td><td>${fcMoney(x.revenue_usd)}</td><td>${x.issues??'—'}</td></tr>`))}`;
  const text=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FC27事实日报 ${esc(r.query.start)}</title><style>body{font:15px system-ui;max-width:1080px;margin:32px auto;padding:0 20px;color:#202a35}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:9px;border-bottom:1px solid #ddd}h2{margin-top:30px}p{line-height:1.7}pre{white-space:pre-wrap}</style><h1>FC27 · 事实日报</h1><p>${esc(r.query.start)} 至 ${esc(r.query.end)} · ${esc(r.scope_label)}<br>数据读取 ${esc(r.as_of)} · 报告生成 ${esc(r.generated_at)} · 版本 ${esc(r.report_id)}</p><p>当前筛选：${esc(JSON.stringify(fcFilters))}</p><h2>00 核心指标与来源参考</h2>${fcTable(['指标','值','来源与口径'],core.map(c=>`<tr>${c.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`))}<p>订单 ${r.totals.orders} · USD ${fcMoney(r.totals.revenue_usd)} · 问题 ${r.totals.issues} · 新 / 老 / 未知 ${r.customer_status==='available'?r.totals.new:'待接通'} / ${r.customer_status==='available'?r.totals.returning:'待接通'} / ${r.totals.unknown}</p>${section('01 主站与卫星子站',r.site_groups,'范围')}${section('02 订单金额分档',r.buckets.map(b=>({...b,key:b.label})),'金额档')}${section('02B 用户累计消费',r.user_buckets.map(b=>({...b,key:b.label})),'累计金额档')}<h2>03 当前未结案池</h2><p>${r.backlog_summary?.orders??'暂缺'} 单；涉及 ${fcMoney(r.backlog_summary?.revenue_usd)}，资金待处理 ${r.backlog_summary?.funding??'暂缺'} 单；等待超过 24 小时 ${r.slow_orders??'暂缺'} 单；不按所选支付日期截断。</p>${Object.entries(r.dimensions).map(([key,rows])=>section('结构 · '+key,rows,key)).join('')}<h2>运营备注与跟进</h2><pre>${esc(fcNote||'未填写；不代运营确认。')}</pre><h2>数据说明</h2><p>状态 ${esc(r.data_status)}；缺失日期 ${esc(r.coverage.missing_days?.join('、')||'无')}；积压池 ${esc(r.coverage.backlog_status||'未验证')}。</p><p>${esc(r.customer_basis)}；按站内客户 ID 去重，访客缺标识不造人数。缺 USD ${r.totals.unpriced_orders} 单。原始联系方式、EA 资料及客服备注未导出。当前原因保留待确认。Admin 网站订单按用户本轮口径分主站与卫星子站；独立分销店铺字段未取得，不声称已完整排除。此为规则事实日报，AI未开启。</p></html>`;
  fcDownload(`FC27事实日报_${r.query.start}_${r.report_id}.html`,text,'text/html;charset=utf-8');status.textContent='服务器规则日报已保存 · '+r.report_id+'；已导出含本次人工备注的 HTML。';
 }catch(e){status.textContent=e.message;}
}
