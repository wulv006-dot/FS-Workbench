(async function(){
 'use strict';const $=id=>document.getElementById(id),core=window.ActivityFunnel,key='fc-activity-registry-v1',defaults=window.FC_ANALYTICS_CONFIG.registry.map(a=>({...a,path:window.FC_ACTIVITY_CONFIG.seo.pages[a.view]?.path||a.path}));
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=n=>Number(n).toLocaleString('zh-CN'),pct=n=>n==null?'—':(n*100).toFixed(1)+'%';
 let registry=core.validateRegistry(defaults),editing=null,generation=0,currentContext=null,currentDiagnostics=null,autoRefreshAllowed=true,lastFcReadAt=0;try{const saved=window.FC_ANALYTICS_CONFIG.serverManaged?null:localStorage.getItem(key);if(saved){registry=core.validateRegistry(JSON.parse(saved));for(const a of core.validateRegistry(defaults))if(!registry.some(x=>x.id===a.id))registry.push(a);}}catch{$('feedback').textContent='本地活动配置不可用，已使用随包配置。';}
 if(window.CampaignServer){try{const state=await CampaignServer.read();registry=core.validateRegistry(state.registry);$('registry-note').textContent='服务器保存 · 版本 '+state.revision+' · '+(state.updatedBy||'初始配置')+'。新增活动立即进入查询白名单；网站埋点仍需开发接入。';if(!state.canEdit){$('add').disabled=true;$('import').disabled=true;}}catch(error){$('feedback').textContent=error.message;return;}}
 const today=new Date(),from=new Date(today.getTime()-6*86400000);$('from').value=from.toISOString().slice(0,10);$('to').value=today.toISOString().slice(0,10);
 const scheduleControl=document.createElement('label');scheduleControl.id='statistics-scope-control';scheduleControl.innerHTML='统计范围<select id="statistics-scope"><option value="today">UTC 今日 · 计划汇总</option><option value="campaign">活动整期 · 计划汇总</option><option value="yesterday">UTC 昨日 · 每日汇总</option><option value="custom">自选区间 / 细分查询</option></select>';$('filters').insertBefore(scheduleControl,$('filters').querySelector('button[type=submit]'));
 const scheduleStatus=document.createElement('section');scheduleStatus.id='statistics-schedule';scheduleStatus.className='panel';scheduleStatus.setAttribute('role','status');scheduleStatus.setAttribute('aria-live','polite');$('feedback').before(scheduleStatus);scheduleStatus.hidden=true;
 if(!window.CampaignServer||new URLSearchParams(location.search).get('scope')==='custom')$('statistics-scope').value='custom';
 for(const id of ['from','to','game','device','source','windowHours'])$(id).addEventListener('change',()=>{
  $('statistics-scope').value='custom';
  if(window.CampaignServer&&scheduledActivity()){
   generation++;revenueGeneration++;trafficGeneration++;trafficState=null;currentDiagnostics=null;fcRevenue=null;scheduleStatus.hidden=true;show(null,$('mode').value);
   $('feedback').textContent='筛选条件已更改，尚未查询；请点击“更新分析”。';
   if(carnival()){couponGeneration++;couponUsage={status:'unavailable',message:'筛选条件已更改，请更新分析。'};renderCouponPanel();}
   if(!carnival()&&$('discount-revenue'))$('discount-revenue').innerHTML='<h2>活动码付款收入</h2><p>— · 尚未查询，请点击“更新分析”。</p>';
  }
 });
 $('statistics-scope').addEventListener('change',()=>{if($('statistics-scope').value!=='custom'){for(const id of ['game','device','source','platform','match'])$(id).value='all';$('mode').value='live';$('template').value='commerce';$('windowHours').value='24';}refresh();});
 function renderRegistry(){const selected=$('activity').value;$('activity').innerHTML=(window.CampaignServer&&!$('show-planned').checked?'':'<option value="all">全部活动</option>')+[...new Map(registry.filter(a=>!window.CampaignServer||a.status==='active'||$('show-planned').checked).map(a=>[core.canonicalActivity(a.id),a])).entries()].map(([id,a])=>`<option value="${esc(id)}">${esc(id==='fc27-season2'?'FC27 周更活动（三页合计）':id==='mmoexp-seasonal'?'万圣节神秘商店（已上线）':a.name)}</option>`).join('');const choices=[...$('activity').options].map(o=>o.value);$('activity').value=choices.includes(selected)?selected:choices.includes('mmoexp-seasonal')?'mmoexp-seasonal':choices[0]||'';if(!choices.length)$('activity').innerHTML='<option value="" disabled>暂无已上线活动</option>';if($('activity').value!==selected)activityFilters();$('activity-count').textContent=new Set(registry.filter(a=>a.status==='active').map(a=>core.canonicalActivity(a.id))).size;
  $('activities').innerHTML=registry.map(a=>`<article class="activity-card"><span class="pill">${esc(({draft:'草稿',testing:'联调中',active:'计划启用',paused:'计划暂停',archived:'归档'})[a.status]||'待接入')} · ${a.type==='prediction'?'赛事竞猜':'商品促销'}</span><h3>${esc(a.name)}</h3><code>${esc(a.id)}</code><p class="muted">${esc(a.origin+a.path)}<br>负责人：${esc(a.owner||'待指定')} · v${esc(a.version)}<br>${a.matches.length} 场赛事 · ${a.windowHours}h 窗口</p><button class="fs-btn" type="button" data-edit="${esc(a.id)}">编辑配置</button></article>`).join('');}
 const gameNames={'1327':'FC27','891':'Aion2','456':'Diablo IV','1333':'MapleStory'};
 const bjt=value=>value&&Number.isFinite(Date.parse(value))?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hour12:false}).format(new Date(value)):'尚未收到';
 const seasonal=()=>$('activity').value==='mmoexp-seasonal';
 const fcActivity=()=>core.canonicalActivity($('activity').value)==='fc27-season2';
 const carnival=()=>$('activity').value==='mmoexp-carnival';
 const scheduledActivity=()=>seasonal()||fcActivity()||carnival();
 const modelName=r=>currentContext?.models?.[r.gameId+':'+r.modelId]||'商品名称待匹配';
 function seasonalTable(rows){
  let section=document.getElementById('seasonal-offer-report');
  if(!section){section=document.createElement('section');section.id='seasonal-offer-report';section.className='panel';$('trend').parentElement.after(section);}
  section.hidden=!seasonal();if(section.hidden){section.replaceChildren();return;}
  section.innerHTML='<h2 id="offer-report-title">商品与折扣表现</h2><p class="muted">按活动版本、商品、折扣与卡位分别统计。同一访问可浏览多个游戏；分游戏数据不相加计算总访客。优惠码表示加购交接记录，不代表已核销或付款。</p><div class="report-table-wrap" tabindex="0" role="region" aria-labelledby="offer-report-title"><table><thead><tr>'+['游戏与商品','折扣与货架','查看批次','翻牌批次','选购批次','确认加购','使用的活动码'].map(t=>'<th scope="col">'+t+'</th>').join('')+'</tr></thead><tbody>'+(rows?.length?rows.map(r=>'<tr><th scope="row">'+esc(gameNames[r.gameId]||'其他游戏')+'<br>'+esc(modelName(r))+'<details><summary>查看记录标识</summary><small>模型 '+esc(r.modelId)+' · '+esc(r.releaseId||'历史版本')+'</small></details></th><td>'+esc(r.offPercent)+'% OFF<br>'+esc(({fixed:'固定优惠','random-1':'神秘货架一','random-2':'神秘货架二'})[r.slot]||r.slot)+'</td><td>'+num(r.exposedVisits)+'</td><td>'+num(r.revealedVisits)+'</td><td>'+num(r.selectedVisits)+'</td><td>'+num(r.cartConfirmations)+'</td><td>'+esc(r.discountCodes.join(', ')||'未发生用码交接')+'</td></tr>').join(''):'<tr><td colspan="7">当前筛选尚无商品行为数据</td></tr>')+'</tbody></table></div>';
 }
 let revenueGeneration=0,fcRevenue=null;
 function renderFcRevenueCard(){if(!fcActivity())return;const card=$('metrics').children[3];if(!card)return;card.innerHTML='<span>活动订单销售额 · USD</span><strong>'+(fcRevenue?.status==='available'?usd(fcRevenue.totals.paid_usd_minor):'—')+'</strong><small>FCSCOUT10 已付款整单金额 · 三页合计；未扣退款'+(fcRevenue?.status==='loading'?' · 正在读取':fcRevenue?.status==='unavailable'?' · 当前缺测':'')+'</small>';}

 const usd=minor=>'$'+(minor/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
 function completionSummary(completed){
  if(!completed)return '<p class="muted">已完成订单 · 暂无状态数据。</p>';
  const {orders,usd_minor,unknown_orders}=completed;
  return '<p>已完成订单 <strong>'+num(orders)+' 单</strong> · '+usd(usd_minor)
   +(unknown_orders?' · '+num(unknown_orders)+' 单状态待核':'')+'</p>';
 }
 async function loadRevenue(filter,force=false){
  const generation=++revenueGeneration;
  let section=$('discount-revenue');if(!section){section=document.createElement('section');section.id='discount-revenue';section.className='panel';$('metrics').after(section);}
  const fc=core.canonicalActivity(filter.activity)==='fc27-season2';if(fc){fcRevenue={status:filter.mode==='live'?'loading':'unavailable'};renderFcRevenueCard();}
  section.hidden=!seasonal()&&!fc;if(section.hidden)return;
  if(filter.mode!=='live'){section.innerHTML='<h2>活动码付款收入</h2><p>测试模式不查询或混入正式订单。请切换正式访客数据查看活动码收入。</p>';return;}
  section.innerHTML='<h2>活动码付款收入</h2><p role="status">正在读取已付款订单，行为统计可继续查看…</p>';
  const params=new URLSearchParams(Object.fromEntries(['activity','mode','from','to','game'].map(k=>[k,filter[k]||'all'])));
  if(force)params.set('refresh','1');
  try{
   const response=await fetch('api/discount-revenue?'+params,{credentials:'same-origin',signal:AbortSignal.timeout(125000)}),r=await response.json();
   if(generation!==revenueGeneration)return;
   if(!response.ok||r.status!=='available'||r.coverage?.complete!==true)throw Error(r.message||'付款订单读取未完成');
   if(fc){fcRevenue=r;renderFcRevenueCard();renderCouponPanel();}
   section.innerHTML='<h2 id="revenue-title">'+(fc?'FC三页合计用码付款':'活动码付款收入')+'</h2><p class="muted">'+(fc?'FCSCOUT10 已付款用码订单为三页合计；不归给当前单页，不与单页访客漏斗相除。':'只统计 MMOEXP 的 12 个活动专属码。')+'按上方 UTC 付款日期和游戏筛选；不按访客设备、渠道拆分，不计算访客付款转化率。</p><div class="metrics">'+[['用码付款订单',num(r.totals.paid_orders)],['付款订单金额 · USD',usd(r.totals.paid_usd_minor)],['含退款的付款订单',num(r.totals.refunded_orders)]].map(([k,v])=>'<article class="metric"><span>'+k+'</span><strong>'+v+'</strong></article>').join('')+'</div><p>后台付款显示金额：'+esc(r.paid_currencies.map(x=>x.currency+' '+x.amount).join(' · ')||'当前窗口无付款')+'</p><p class="muted">整单金额采用 Admin 付款订单美元口径；混合购物车不分摊到商品。退款保留原付款记录并另列笔数；退款金额和净收入尚未核实，不按 0 计算。更新时间：'+esc(bjt(r.generated_at))+'（北京时间），最多缓存 10 分钟。</p><div class="report-table-wrap" tabindex="0" role="region" aria-labelledby="revenue-title"><table><thead><tr>'+['游戏','活动专属码','折扣','付款订单','订单金额 · USD','含退款订单'].map(x=>'<th scope="col">'+x+'</th>').join('')+'</tr></thead><tbody>'+r.codes.map(x=>'<tr><th scope="row">'+esc(gameNames[x.game_id]||x.game_id)+'</th><td>'+esc(x.code)+'</td><td>'+num(x.off_percent)+'% OFF</td><td>'+num(x.paid_orders)+'</td><td>'+usd(x.paid_usd_minor)+'</td><td>'+num(x.refunded_orders)+'</td></tr>').join('')+'</tbody></table></div>';
   if(fc){section.querySelector('.metrics').insertAdjacentHTML('afterend',completionSummary(r.completed));section.insertAdjacentHTML('beforeend',productSalesHtml(r.product_sales));}
   if($('payment-read-state'))$('payment-read-state').textContent='活动码付款收入已接入；逐访客结账、付款回传未接入';
  }catch(error){if(generation!==revenueGeneration)return;if(fc){fcRevenue={status:'unavailable'};renderFcRevenueCard();}section.innerHTML='<h2>活动码付款收入</h2><p role="status">'+esc(error.name==='TimeoutError'?'付款订单查询超时，请更新分析重试；未完成不记为零。':error.message)+'</p>';}
 }

 let couponGeneration=0,couponUsage=null,couponPrevious=null,couponNotice='';
 const couponKey=filter=>JSON.stringify([core.canonicalActivity(filter.activity||''),filter.mode||'',filter.from||'',filter.to||'']);
 const couponCurrentFilter=()=>Object.fromEntries(new FormData($('filters')));
 function retainCoupon(filter,notice){
  const scope=$('statistics-scope').value,day=new Date(Date.now()).toISOString().slice(0,10);
  const expectedEnd=scope==='today'?day:scope==='yesterday'?new Date(Date.parse(day+'T00:00:00Z')-86400000).toISOString().slice(0,10):null;
  const scopeMatches=scope==='custom'||couponPrevious?.scope===scope;
  const prior=carnival()&&scopeMatches&&(!expectedEnd||filter.to===expectedEnd)&&couponPrevious?.key===couponKey(filter)?couponPrevious.data:null;
  couponUsage=prior;couponNotice=prior?notice:'';return !!prior;
 }
 const pctText=v=>v==null?'—':(v*100).toFixed(1)+'%';
 function renderCouponPanel(){
  let section=$('coupon-usage');
  if(!fcActivity()&&!carnival()){if(section)section.hidden=true;return;}
  if(!section){section=document.createElement('section');section.id='coupon-usage';section.className='panel';($('discount-revenue')||$('metrics')).after(section);}
  section.hidden=false;const c=couponUsage;
  if(!c||c.status==='loading'){section.innerHTML='<h2>活动券使用与转化</h2><p role="status">正在读取券使用记录，行为统计可继续查看…</p>';return;}
  if(c.status==='test')return void(section.innerHTML='<h2>活动券使用与转化</h2><p>测试模式不查询或混入正式订单。请切换正式访客数据查看活动券。</p>');
  if(c.status!=='available'){section.innerHTML='<h2>活动券使用与转化</h2><p role="status">'+esc(c.message||'活动券使用记录暂不可读；未完成不记为零。')+'</p>';return;}
  if(carnival()){
   const fields=[['累计领取','issued_total'],['累计使用','used_total'],['用券订单','used_orders'],['已付款','paid_orders'],['含退款','refunded_orders'],['付款金额 · USD','paid_usd_minor'],['确认抵扣 · USD','discount_usd_minor']];
   const table=(kind,rows,columns,label)=>'<div class="report-table-wrap" tabindex="0" role="region" aria-label="活动券使用 · '+kind+'"><table><thead><tr><th scope="col">'+kind+'</th>'+columns.map(([title])=>'<th scope="col">'+title+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr><th scope="row">'+esc(label(row))+'</th>'+columns.map(([,key])=>'<td>'+(key.endsWith('_minor')?usd(row[key]):num(row[key]))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
   const gameRows=c.games?.length?table('游戏',c.games,fields.slice(2),row=>row.game_name||(row.game_id?'游戏 #'+row.game_id:'游戏待归类')):
    '<p class="muted">'+(Array.isArray(c.games)?'所选区间没有用券订单。':'游戏明细暂不可用。')+'</p>';
   section.innerHTML='<h2>活动券使用 · 按模块</h2>'+(couponNotice?'<p role="status">'+esc(couponNotice)+'</p>':'')+table('模块',c.modules,fields,row=>core.carnivalModules[row.module])
    +'<h3>活动券使用 · 按购买游戏</h3>'+gameRows+'<p class="muted">按 Admin 订单所属游戏统计，覆盖所有活动模块。未匹配订单或无明确游戏的记录计入「游戏待归类」。</p>'
    +'<p class="muted">领取和使用累计取自券模板。窗口内按 UTC 用券日期归组，付款金额含单列的退款订单。'+(c.coverage.orders_unmatched?' '+num(c.coverage.orders_unmatched)+' 笔未匹配到订单，使用用券记录的付款状态与金额。':'')+' 更新时间 '+esc(bjt(c.generated_at))+'（北京时间）。</p>';
   return;
  }
  const t=c.totals,cp=c.coupon,rate=c.conversion,code=fcRevenue?.status==='available'?fcRevenue.totals:null;
  const cards=[['已领取券 · 累计',num(cp.issued_total)],['已使用券 · 累计',num(cp.used_total)],['领取→使用 · 累计',pctText(rate.claim_to_use)],['窗口内用券订单',num(t.used_orders)],['其中已付款',num(t.paid_orders)],['用券订单付款率',pctText(rate.paid_per_use)],['用券付款金额 · USD',usd(t.paid_usd_minor)],['券抵扣金额 · USD',usd(t.discount_usd_minor)],['用券付款买家',num(t.unique_buyers)],['含退款订单',num(t.refunded_orders)],['用券后90天复购订单',num(t.repurchase_orders)],['90天复购金额 · USD',usd(t.repurchase_usd_minor)]];
  const compare=code?'<p>优惠码（保留）：'+(code.paid_orders==null?'':num(code.paid_orders)+' 单 · ')+usd(code.paid_usd_minor)+'；优惠券：'+num(t.paid_orders)+' 单 · '+usd(t.paid_usd_minor)+'；两者合计：'+(code.paid_orders==null?'':num(code.paid_orders+t.paid_orders)+' 单 · ')+usd(code.paid_usd_minor+t.paid_usd_minor)+'。优惠码与优惠券互斥，不会同时用在一张订单上。</p>':'';
  const rows=c.daily.map(d=>'<tr><th>'+esc(d.date)+'</th><td>'+num(d.used_orders)+'</td><td>'+num(d.paid_orders)+'</td><td>'+usd(d.paid_usd_minor)+'</td></tr>').join('');
  section.innerHTML='<h2>活动券使用与转化 · FC三页合计</h2><p class="muted">三页共用一张统一券（'+esc(cp.title||'')+'，ID '+esc(cp.coupon_id)+'），不按页面拆分；与优惠码并行统计，原优惠码数据不变。发放与使用累计来自券记录，窗口内按 UTC 用券日统计，完成状态取自 Admin 当前订单。</p><div class="metrics">'+cards.map(([k,v])=>'<article class="metric"><span>'+k+'</span><strong>'+v+'</strong></article>').join('')+'</div>'+completionSummary(c.completed)+compare+(rows?'<div class="report-table-wrap"><table><thead><tr><th>日期（UTC）</th><th>用券订单</th><th>已付款</th><th>付款金额 · USD</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'<p class="muted">当前窗口没有券使用记录。</p>')+'<p class="muted">'+esc(c.note||'')+(c.coverage?.orders_unmatched?' 其中 '+num(c.coverage.orders_unmatched)+' 笔订单在订单列表里未找到，付款状态与金额按用券记录。':'')+'</p>';
 }
 async function loadCouponUsage(filter,force=false){
  const generation=++couponGeneration;
  if(!fcActivity()&&!carnival()){couponUsage=null;renderCouponPanel();return;}
  if(filter.mode!=='live'){couponUsage={status:'test'};renderCouponPanel();return;}
  if(carnival()&&(!filter.from||!filter.to||Date.now()<Date.parse(currentContext?.startsAt)||Date.parse(filter.to)+86400000<=Date.parse(currentContext?.startsAt))){
   couponUsage={status:'not_started',message:'所选区间尚未开始统计。'};renderCouponPanel();return;
  }
  if(!retainCoupon(filter,'正在更新；保留同一范围上次成功结果。'))couponUsage={status:'loading'};renderCouponPanel();
  const params=new URLSearchParams(Object.fromEntries(['activity','mode','from','to'].map(k=>[k,filter[k]||''])));
  if(force)params.set('refresh','1');
  try{
   const response=await fetch('api/coupon-usage?'+params,{credentials:'same-origin',signal:AbortSignal.timeout(125000)});if(generation!==couponGeneration)return;if(carnival()&&[401,403].includes(response.status)){couponPrevious=null;autoRefreshAllowed=false;throw Error('登录状态或访问权限未确认，请重新登录后重试。');}const r=await response.json();
   if(generation!==couponGeneration)return;
   if(!response.ok||r.status!=='available'&&r.status!=='not_started'||r.status==='available'&&r.coverage?.complete!==true){if(response.status===401||response.status===403)couponPrevious=null;throw Error(r.message||'活动券使用记录读取未完成');}
   if(carnival()&&r.status==='available'&&r.activity_id!=='mmoexp-carnival')throw Error('活动券结果与所选活动不一致');
   couponUsage=r;couponNotice='';
   if(carnival()&&r.status==='not_started')couponPrevious=null;
   if(carnival()&&r.status==='available'&&Number.isFinite(Date.parse(r.generated_at)))couponPrevious={key:couponKey(filter),scope:$('statistics-scope').value,data:r};
  }catch(error){if(generation!==couponGeneration)return;const message=error.name==='TimeoutError'?'活动券使用记录查询超时，请更新分析重试；未完成不记为零。':error.message;if(!retainCoupon(filter,'更新失败：'+message+' 保留同一范围上次成功结果。'))couponUsage={status:'unavailable',message};}
  renderCouponPanel();
 }
 let trafficState=null,trafficGeneration=0;
 async function loadTraffic(filter,force){
  const generation=++trafficGeneration;
  if(!(seasonal()||fcActivity())||!window.CampaignServer||filter.mode!=='live'){trafficState=null;showBasicTraffic(filter.mode==='test');return;}
  trafficState={status:'loading'};showBasicTraffic(false);
  const params=new URLSearchParams({activity:core.canonicalActivity(filter.activity),from:filter.from,to:filter.to});if(force)params.set('refresh','1');
  try{const response=await fetch('api/origin-traffic?'+params,{credentials:'same-origin',signal:AbortSignal.timeout(20000)}),data=await response.json();if([400,401,403].includes(response.status))autoRefreshAllowed=false;if(!response.ok)throw Error();if(generation!==trafficGeneration)return;trafficState=data;showBasicTraffic(false);}
  catch{if(generation===trafficGeneration){trafficState={status:'unavailable'};showBasicTraffic(false);}}
 }
 function showBasicTraffic(test){
  let panel=document.getElementById('basic-traffic-report');
  if(!(seasonal()||fcActivity())){if(panel)panel.hidden=true;if($('mode-notice').nextElementSibling!==$('filters'))$('mode-notice').after($('filters'));showGoogle();return;}
  if(!panel){panel=document.createElement('section');panel.id='basic-traffic-report';panel.className='panel';$('activity-summary').after(panel);}
  panel.hidden=false;if(panel.nextElementSibling!==$('filters'))panel.after($('filters'));showGoogle();
  const t=trafficState,ready=!test&&t?.status==='available'&&Number.isSafeInteger(t.pageRequests),partial=!test&&t?.status==='partial';
  const note=test?'测试模式不查询基础页面请求。':!t?'尚未查询，请点击“更新分析”。':t.status==='loading'?'正在读取187侧现有日志…':ready?'所选UTC日期的现有日志聚合已完成。':partial?'所选整期缺测；仅有部分日志覆盖，不能把已读片段当整期数据。':'现有日志暂不可读取；缺测不记为0。';
  panel.innerHTML='<h2>基础访问量 · 187侧页面请求</h2><p class="muted">'+note+'</p><div class="metrics"><article class="metric"><span>187侧活动页面请求（估算）</span><strong>'+(ready?num(t.pageRequests):test?'不统计':!t||t.status==='loading'?'—':'缺测')+'</strong><small>只计正式活动文档的成功GET，排除资源、API、HEAD及已识别机器人/自动化和标记测试；刷新重复计数。</small></article><article class="metric"><span>估算访客数 · 按IP去重</span><strong>缺测</strong><small>真实访客代理IP链尚未核实，不把出口IP当人，也不使用行为UV推算全部访客。</small></article></div>'+(t?.coverage?'<p class="muted">日志覆盖：'+esc(bjt(t.coverage.from))+' 至 '+esc(bjt(t.coverage.through))+'（北京时间）；所选日期按UTC。'+(partial?'已读范围记录 '+num(t.observedPageRequests)+' 次，整期仍缺测。':'')+'成功文档GET '+num(t.successfulRequests)+' 次，已排除 '+num(t.excludedRequests)+' 次；更新时间 '+esc(bjt(t.generatedAt))+'，最多缓存10分钟。</p>':'')+'<p class="muted">仅代表到达187的文档请求；浏览器/边缘缓存未回源会漏计，未识别预取、内部测试或代理重试可能计入。不是实际人数，不按游戏、设备或渠道拆分，不设访客去重窗口。行为统计和活动码付款销售另列。</p>'+(t?.daily?.length?'<div class="report-table-wrap"><table><thead><tr><th>UTC日期</th><th>已读日志内页面请求估算</th></tr></thead><tbody>'+t.daily.map(r=>'<tr><td>'+esc(r.date)+'</td><td>'+num(r.requests)+'</td></tr>').join('')+'</tbody></table></div>':'');
 }
 let googleSource='gsc',googleKey='',googleGeneration=0;
 function showGoogle(){
  let panel=$('google-traffic-report');
  if(!seasonal()&&!carnival()){if(panel)panel.hidden=true;googleKey='';googleGeneration++;return;}
  if(!panel){panel=document.createElement('section');panel.id='google-traffic-report';panel.className='panel';}panel.hidden=false;if($('filters').nextElementSibling!==panel)$('filters').after(panel);
  const activity=$('activity').value,from=$('from').value,to=$('to').value,mode=$('mode').value,key=[activity,from,to,mode,googleSource].join(':');
  if(key===googleKey)return;googleKey=key;googleGeneration++;
  panel.innerHTML='<h2>Google · '+(carnival()?'狂欢盛典':'万圣节')+'页面流量</h2><p class="muted">只查询正式活动页；各来源按自己的统计日，不与UTC行为窗口拼成逐访客漏斗。此区不随游戏、设备和渠道筛选，不会在页面自动刷新时重复请求Google。</p><label>数据来源 <select id="google-source"><option value="gsc">Search Console · 自然搜索</option><option value="ga4">GA4 · 页面与访问</option><option value="ads">Google Ads · 广告落地页</option></select></label> <button id="google-load" class="fs-btn fs-btn--primary" type="button">读取 Google 明细</button><div id="google-result" role="status" aria-live="polite"><p>'+esc(from)+' 至 '+esc(to)+' · 点击读取；未查询不显示为零。</p></div>';
  const labels=googleSource==='ga4'?['浏览量','活跃用户','入口会话']:googleSource==='ads'?['曝光','点击','广告费用']:['曝光','点击','CTR'];
  $('google-result').insertAdjacentHTML('afterbegin','<div class="metrics">'+labels.map(label=>'<article class="metric"><span>'+label+'</span><strong>—</strong></article>').join('')+'</div>');
  $('google-result').querySelector('p').textContent=from+' 至 '+to+' · 尚未查询，请点击“读取 Google 明细”。';
  $('google-source').value=googleSource;$('google-source').addEventListener('change',()=>{googleSource=$('google-source').value;googleKey='';showGoogle();});
  $('google-load').disabled=mode!=='live'||!window.CampaignServer;
  $('google-load').addEventListener('click',async()=>{
   const generation=++googleGeneration,button=$('google-load');button.disabled=true;$('google-result').textContent='正在读取活动页专属Google聚合数据…';
   try{const response=await fetch('api/google-traffic?'+new URLSearchParams({activity,source:googleSource,from,to,refresh:'1'}),{credentials:'same-origin',signal:AbortSignal.timeout(95000)}),value=await response.json();if(generation!==googleGeneration)return;if(!response.ok)throw Error('Google查询未完成');renderGoogle(value);}
   catch{if(generation===googleGeneration)$('google-result').textContent='Google查询未完成；未将失败或超时记为零。';}
   finally{if(generation===googleGeneration)button.disabled=false;}
  });
 }
 function renderGoogle(value){
  const reports=value.reports||{},names={page_total:'页面浏览汇总',landing_total:'作为入口的会话汇总',organic_landing_total:'自然搜索入口会话',total:'自然搜索汇总',daily:'逐日记录',query:'搜索词',country:'国家',device:'设备',channel:'来源 / 媒介',events:'已上报事件',landing:'广告日期 × 系列 × 设备'},labels={screenPageViews:'浏览量',activeUsers:'活跃用户',userEngagementDuration:'参与时长（秒）',sessions:'入口会话',organicSessions:'自然搜索入口会话',engagedSessions:'参与会话',bounceRate:'跳出率',clicks:'点击',impressions:'曝光',ctr:'CTR',position:'平均位置',eventCount:'事件次数',costMicros:'广告费用（USD）',date:'日期',query:'搜索词',country:'国家',device:'设备',deviceCategory:'设备',sessionSourceMedium:'来源 / 媒介',eventName:'事件',campaign:'广告系列'};
  labels.costMicros='广告费用（'+(value.currency||'币种未核实')+'）';
  const display=(key,v)=>v==null?'—':['ctr','bounceRate'].includes(key)?pct(v):key==='costMicros'?(v/1000000).toFixed(2):typeof v==='number'?num(v):esc(v);
  let html='<p>'+esc(value.from||$('from').value)+' 至 '+esc(value.to||$('to').value)+' · 来源时区 '+esc(value.timezone||'未提供')+' · 读取时间 '+esc(bjt(value.generatedAt))+'（北京时间）</p>';
  html+='<p>'+({available:'接口已返回活动页记录。',no_rows:'接口正常，但未返回该活动页记录；不能据此认定真实流量为零。',partial:'部分报表未完成；仅显示本次成功返回的部分。',unavailable:'来源暂不可读；未将缺测记为零。'}[value.status]||'查询状态待核对')+'</p>';
  html+='<p class="muted">'+(value.source==='ga4'?'GA4仍受访客同意、标签加载和拦截影响。页面用户与入口会话分别查询；细分用户不相加。':value.source==='gsc'?'仅Google自然网页搜索，不含广告。最终数据可能延迟，搜索词明细受隐私与Top行限制；无记录的日期不补零。':'仅MMOEXP广告账号中直接落到该活动页的记录，不代表站内入口引流，也不等同实际订单归因。')+'</p>';
  if(value.coverage)html+='<p>站点最终数据已覆盖日期：'+esc(value.coverage.availableFinalDates.join('、')||'未取得')+'；'+(value.coverage.missingDates.length?'所选区间尚缺 '+esc(value.coverage.missingDates.join('、'))+'，当前汇总不能当完整区间结果。':'所选日期最终数据均已可查询。')+'</p>';
  const totalReports=Object.entries(reports).filter(([name])=>name.endsWith('total')||name==='total'),totals=totalReports.flatMap(([name,report])=>report.rows?.[0]?Object.entries(report.rows[0].metrics).map(([key,value])=>[name==='organic_landing_total'&&key==='sessions'?'organicSessions':key,value]):[]);
  const restricted=report=>report.quality&&(report.quality.subjectToThresholding||report.quality.dataLossFromOtherRow||report.quality.samplingMetadatas?.length||report.quality.schemaRestrictionResponse?.activeMetricRestrictions?.length);
  if(value.source==='ads'&&reports.landing?.rows?.length&&!reports.landing.truncated)for(const key of ['impressions','clicks','costMicros'])totals.push([key,reports.landing.rows.reduce((sum,row)=>sum+row.metrics[key],0)]);
  if(totals.length)html+='<div class="metrics">'+totals.map(([key,v])=>'<article class="metric"><span>'+esc(labels[key]||key)+'</span><strong>'+display(key,v)+'</strong></article>').join('')+'</div>';
  if(totalReports.some(([,report])=>restricted(report)))html+='<p>Google标记汇总报表受阈值、采样或字段限制影响。</p>';
  for(const [name,report]of Object.entries(reports)){
   if(name.endsWith('total')||name==='total')continue;
   const rows=report.rows||[];html+='<details><summary>'+esc(names[name]||name)+' · '+rows.length+' 行'+(report.truncated?'（返回不完整）':'')+'</summary>';
   if(!rows.length){html+='<p>未返回记录。</p></details>';continue;}
   const dims=Object.keys(rows[0].dimensions),metrics=Object.keys(rows[0].metrics),keys=[...dims,...metrics];html+='<div class="report-table-wrap" tabindex="0" role="region" aria-label="'+esc(names[name]||name)+'"><table><thead><tr>'+keys.map(k=>'<th scope="col">'+esc(labels[k]||k)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+keys.map(k=>'<td>'+display(k,dims.includes(k)?row.dimensions[k]:row.metrics[k])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
   if(report.topRowsOnly)html+='<p class="muted">来源返回的Top明细，不用明细行和代替原生总量。</p>';
   if(restricted(report))html+='<p>Google标记该报表受阈值、采样或字段限制影响。</p>';
   html+='</details>';
  }
  for(const name of Object.keys(value.failures||{}))html+='<p>'+esc(names[name]||name)+'：本次读取失败，未补零。</p>';
  $('google-result').innerHTML=html;
 }
 function showSeasonal(data,mode){
  const c=currentContext,d=currentDiagnostics,missing=!data,t=data?.seasonalTotals||{},test=mode==='test';
  $('open-activity').href='https://www.mmoexp.com/events/seasonal/index.html';$('open-activity').textContent='打开正式活动页 ↗';$('open-activity').target='_blank';$('open-activity').rel='noopener';document.body.classList.add('operator-seasonal');$('game-filter').hidden=false;$('activity-summary').hidden=false;
  $('report-title').textContent='万圣节神秘商店';$('report-subtitle').textContent='已上线活动 · FC27、Aion2、Diablo IV、MapleStory';
  $('activity-summary').innerHTML='<h2>当前追踪活动</h2><p class="activity-link"><a href="https://www.mmoexp.com/events/seasonal/index.html" target="_blank" rel="noopener">www.mmoexp.com/events/seasonal/index.html ↗</a></p><div class="activity-status-grid"><div><strong>活动状态</strong><p>'+(!c?'发布状态待核对':!c.active?'已暂停':Date.now()>Date.parse(c.endsAt)?'已结束':'已上线')+'</p><small>'+esc(c?.releaseId||'正在读取发布版本')+'</small></div><div><strong>'+ (test?'测试验收收数':'正式访客收数')+'</strong><p>'+(missing?'查询未完成':d?.eventCount?num(d.eventCount)+' 条事件':'尚未收到事件')+'</p><small>'+(!missing?'查询服务已连通 · ':'')+'最近事件 '+esc(bjt(d?.lastEventAt))+'（北京时间）</small></div><div><strong>购物车与付款</strong><p>原生加购确认已接入</p><small id="payment-read-state">活动码付款订单独立查询；逐访客结账、付款回传未接入</small></div><div><strong>活动结束</strong><p>'+esc(c?.endsAt?new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',dateStyle:'short',timeStyle:'medium',hour12:false}).format(new Date(c.endsAt)):'等待发布信息')+'</p><small>美东时间 · 优惠码到期时间另计</small></div></div><p class="collection-note">'+(test?'当前只看标记测试事件，不计入正式经营数据。':'数据来自已同意统计且成功上报的访客。页面打开不等于同意采集；浏览器拦截与未授权访问不在覆盖内。')+'</p>';
  showBasicTraffic(test);
  const metric=(label,value,note)=>'<article class="metric"><span>'+label+'</span><strong>'+(missing?'—':num(value||0))+'</strong><small>'+note+'</small></article>';
  $('metrics').innerHTML=metric('已授权访问批次',data?.visits,'同意行为统计且成功上报的访问批次')+metric('已授权行为访客 · UV',data?.visitors,'按浏览器会话标识去重，不是全部来访人数')+metric('翻开神秘货架',t.revealed,'发生揭晓的访问批次')+metric('确认加入购物车',t.cart,'原站成功回执的访问批次');
  $('window-label').textContent='已授权行为进度';$('funnel-definition').textContent='仅统计允许后成功上报的行为；各行为按访问批次去重，不强求依次完成。';
  const stages=[['访问活动页',data?.visits],['查看商品货架',t.gameViews],['揭晓神秘优惠',t.revealed],['选择商品',t.selected],['确认加入购物车',t.cart]];
  $('funnel').innerHTML=stages.map(([label,count])=>'<div class="step"><div>'+label+'</div><div class="bar-track"><div class="bar" style="width:'+(data?.visits?Math.min(100,(count||0)/data.visits*100):0)+'%"></div></div><strong>'+(missing?'—':num(count||0))+'</strong></div>').join('')+'<p class="muted">付款订单与收入见独立活动码收入区；进入结账及逐访客付款转化尚未接入。</p>';
  $('insight').textContent=missing?'查询尚未成功，当前不显示统计值。':!data.visits?(test?'当前筛选没有测试记录。':'查询成功，但当前筛选尚无正式事件。请核对日期、游戏筛选与访客统计授权；历史测试不会补成正式数据。'):'有 '+num(t.selected||0)+' 个访问批次选择商品，'+num(t.cart||0)+' 个批次确认加购；加购待核对 '+num(t.unconfirmed||0)+' 个批次。';
  $('channels').innerHTML=data?.sources?.length?data.sources.map(x=>'<div class="channel"><div><strong>'+esc(({direct:'直接访问',organic:'自然搜索',internal:'站内入口',google_ads:'Google Ads',referral:'外部引荐'})[x.name]||x.name)+'</strong></div><div>'+num(x.visits)+' 次访问</div></div>').join(''):'<p class="empty">当前筛选尚无渠道数据</p>';
  let games=document.getElementById('game-report');if(!games){games=document.createElement('section');games.id='game-report';games.className='game-report-grid';$('metrics').after(games);}
  games.hidden=false;games.innerHTML=(c?.games||[]).filter(g=>!$('game').value||$('game').value==='all'||g.id===$('game').value).map(g=>{const r=data?.seasonalGames?.find(x=>x.gameId===g.id)||{};return '<article class="game-report-card"><h3>'+esc(g.name)+'</h3><dl>'+[['访问批次',r.visits],['揭晓优惠',r.revealed],['选择商品',r.selected],['确认加购',r.cart]].map(([k,v])=>'<dt>'+k+'</dt><dd>'+(missing?'—':num(v||0))+'</dd>').join('')+'</dl></article>';}).join('');
  const max=Math.max(1,...(data?.daily||[]).map(x=>x.visits));$('trend').innerHTML=data?.daily?.length?'<div class="trend">'+data.daily.map(x=>'<div class="day"><b>'+num(x.visits)+'</b><div class="day-bar" style="height:'+x.visits/max*100+'px"></div><span>'+esc(x.date.slice(5))+'</span><small>活动访问</small></div>').join('')+'</div>':'<p class="empty">当前筛选尚无访问趋势</p>';
  seasonalTable(data?.seasonalOffers);
 }
 function showCarnival(data){
  const c=currentContext?.activityId==='mmoexp-carnival'?currentContext:null;
  const registration=registry.find(a=>a.id==='mmoexp-carnival'),start=c?.startsAt||registration?.startAt,end=c?.endsAt||registration?.endAt;
  const started=!start||Date.now()>=Date.parse(start),outside=$('to').value&&Date.parse($('to').value)+86400000<=Date.parse(start);
  const report=started&&!outside?data?.carnival:null,steps=report?.steps;
  $('report-title').textContent='狂欢盛典 2026';
  $('report-subtitle').textContent='已授权访客行为与活动券归因';
  $('open-activity').href=c?.url||'https://www.mmoexp.com/events/Carnival.html';
  $('open-activity').textContent='打开正式活动页 ↗';
  $('open-activity').target='_blank';$('open-activity').rel='noopener';
  document.body.classList.add('operator-seasonal');
  $('activity-summary').hidden=false;
  $('activity-summary').innerHTML='<h2>活动时间 · 北京时间</h2><p>'+esc(bjt(start))+' 至 '+esc(bjt(end))+'</p>';
  for(const id of ['game-filter','game-report','discount-revenue'])if($(id))$(id).hidden=true;
  seasonalTable();showBasicTraffic(false);
  $('metrics').replaceChildren();
  $('window-label').textContent='按访问批次去重';
  $('funnel-definition').textContent='各步骤统计发生过该行为的访问批次，访客可从任意模块参与。';
  $('funnel').innerHTML=Object.entries(core.carnivalSteps).filter(([key])=>steps?.[key]!=null).map(([key,label])=>'<div class="step"><div>'+label+'</div><div class="bar-track"><div class="bar" style="width:'+(steps.visits?steps[key]/steps.visits*100:0)+'%"></div></div><strong>'+num(steps[key])+'</strong></div>').join('');
  $('insight').textContent=!started?'活动尚未开始。':outside?'所选区间早于活动开始。':!steps?'当前区间尚无可用汇总。':steps.visits===0?'当前区间尚未收到已授权访问。':'结账交接统计购物车交接事件，付款见活动券使用。';
  $('channels').innerHTML=Object.entries(core.carnivalActions).map(([module,labels])=>{
   const actions=Object.entries(labels).filter(([key])=>report?.actions?.[module]?.[key]!=null);
   return actions.length?'<h3>'+core.carnivalModules[module]+'</h3>'+actions.map(([key,label])=>'<div class="channel"><span>'+label+'</span><strong>'+num(report.actions[module][key])+'</strong></div>').join(''):'';
  }).join('')||'<p class="empty">当前区间尚无模块操作记录。</p>';
 }
 function show(data,mode){if(carnival())return showCarnival(data);if(seasonal())return showSeasonal(data,mode);showBasicTraffic(false);$('open-activity').href='products.html#page-preview';$('open-activity').textContent='预览活动页 ↗';document.body.classList.remove('operator-seasonal');$('game-filter').hidden=true;$('activity-summary').hidden=true;const gameReport=document.getElementById('game-report');if(gameReport)gameReport.hidden=true;$('report-title').textContent=fcActivity()?'FC27 周更活动（三页合计）':'活动转化分析';$('report-subtitle').textContent=fcActivity()?'Player Trio · Weekly Scout · SBC Core，共用一份活动数据':'活动行为分析';seasonalTable(data?.seasonalOffers);const sharedFc=fcActivity(),missing=mode==='local'||mode==='test'||sharedFc,unavailable=!data,report=data||core.summarize([],{template:$('template').value}),steps=report.steps,isCommerce=report.template==='commerce';$('window-label').textContent='有序 · '+(report.windowHours||24)+' 小时';$('funnel-definition').textContent=report.template==='reward'?'以中奖资格为分母，按同一赛事与奖励链路统计；未中奖不算流失。':report.template==='prediction'?'同一赛事、同一访问批次：赛事曝光 → 开始预测 → 服务端保存成功。':'同一活动访问批次按顺序完成，跨日转化按配置窗口归组。';
  const metric=(label,value,note)=>`<article class="metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`;
  $('metrics').innerHTML=metric(isCommerce?'活动访问批次':'漏斗起点批次',unavailable?'—':num(report.visits),'同一批次内事件去重')+metric(mode==='local'?'本机可识别会话':'访客数 · UV',unavailable?'—':num(report.visitors),mode==='local'?'本机仅按会话去重':'匿名浏览器 ID 去重，非跨设备实名人数')+metric(isCommerce?'付款批次转化率':'目标完成率',missing||unavailable?'—':pct(report.visits?steps.at(-1).count/report.visits:null),sharedFc?'付款按活动码独立统计，尚未关联到访客':missing?'服务端尚未接入':'最终步骤批次 ÷ 漏斗起点批次')+metric('活动商品实付 · USD',!isCommerce||missing||unavailable?'—':'$'+(report.revenueMinor/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),'独立归因订单金额；未扣退款');
  const base=steps[0].count;$('funnel').innerHTML=steps.map((s,i)=>`<div class="step"><div>${s.label}<small>${i?'上一步 '+(missing&&i>=(sharedFc?3:2)||unavailable?'待接入':pct(s.rate)):'访问入口'}</small></div><div class="bar-track"><div class="bar" style="width:${base?s.count/base*100:0}%;opacity:${1-i*.12}"></div></div><strong>${missing&&i>=(sharedFc?3:2)||unavailable?'—':num(s.count)}</strong></div>`).join('');
  const drops=steps.slice(1).map((s,i)=>({name:s.label,lost:steps[i].count-s.count})).sort((a,b)=>b.lost-a.lost);
  $('insight').textContent=unavailable?'尚无可用真实数据。请先完成下方接入清单。':missing?(sharedFc?'三页行为按活动统一去重；付款订单与商品销量见独立销售区，不把点击、加购当作销量或付款转化。':'行为埋点可核对；加购、结账与支付尚未接入，不填虚构转化。'):base?`流失最多的阶段：${drops[0].name}，减少 ${num(drops[0].lost)} 个访问批次。${mode==='demo'?'这是演示样本，不能作为运营结论。':'这是观察结果，不直接证明流失原因。'}`:'当前筛选没有数据；新登记活动不会自动生成演示销售。';
  $('channels').innerHTML=report.sources.length?report.sources.map(s=>`<div class="channel"><div><strong>${esc(({organic:'自然搜索',internal:'站内入口',direct:'直接访问',google_ads:'Google Ads',referral:'外部引荐'})[s.name]||s.name)}</strong><small>${num(s.visits)} 次访问</small></div><div>${missing?'付款待接入':pct(s.visits?s.paid/s.visits:null)}<small class="muted"> 完成率</small></div></div>`).join(''):'<p class="empty">暂无渠道数据</p>';
  const max=Math.max(1,...report.daily.map(x=>x.visits));$('trend').innerHTML=report.daily.length?'<div class="trend">'+report.daily.map(d=>`<div class="day"><b>${num(d.visits)}</b><div class="day-bar" style="height:${d.visits/max*100}px"></div><span>${esc(d.date.slice(5))}</span><small>${missing?'付款待接入':d.paid+' 完成批次'}</small></div>`).join('')+'</div>':'<p class="empty">暂无趋势数据</p>';
  $('products').innerHTML=report.products.length?report.products.slice(0,12).map(p=>`<tr><td>${esc(currentContext?.products?.[p.id]||window.FC_ACTIVITY_CONFIG.products[p.id]?.name||p.id)}</td><td>${num(p.exposures)}</td><td>${num(p.selections)}</td></tr>`).join(''):'<tr><td colspan="3">暂无商品事件</td></tr>';
  renderFcRevenueCard();
  $('intent').innerHTML=[[mode==='local'?'点击会话数':'点击访客数',report.clickers],['查看购买清单的批次',report.reviews],['选择 SBC 代做的批次',report.sbcSelections],...(report.couponClaims===undefined?[]:[['领取活动券的批次',report.couponClaims],['沿用已领券的批次',report.couponReused]]),['平均前台参与时长',report.activeSeconds==null?'—':report.activeSeconds+' 秒']].map(([label,value])=>`<div class="channel"><span>${label}</span><strong>${unavailable?'—':esc(value)}</strong></div>`).join('');
 }
 function normalizeFilters(){
  const isCarnival=carnival();
  if(seasonal()||isCarnival){for(const id of ['platform','match'])$(id).value='all';$('template').value='commerce';}
  if(isCarnival)$('game').value='all';
  const channels=$('channels').closest('section');
  channels.querySelector('h2').textContent=isCarnival?'模块操作次数':'渠道带来的转化';
  channels.querySelector('.eyebrow').hidden=isCarnival;
  channels.querySelector('.definition').hidden=isCarnival;
  $('trend').closest('section').hidden=isCarnival;
 }
 function productSalesHtml(sales){
  const available=sales?.status==='available'&&sales.coverage?.complete===true,partial=sales?.status==='partial',rows=Array.isArray(sales?.rows)?sales.rows:[];
  return '<h3>活动商品销量 · 付款订单行</h3><p>'+(available?'当前区间付款订单行已完整核对。':partial?'仅部分付款订单已取得商品行，以下为已覆盖部分，不代表完整销量。':'付款订单行暂不可用；未将缺测记为零。')+(sales?.coverage?' 已覆盖 '+num(sales.coverage.covered_paid_orders)+' / '+num(sales.coverage.eligible_paid_orders)+' 个活动付款订单。':'')+'</p>'+(sales?.rows_truncated?'<p class="muted">显示前 '+rows.length+' / 共 '+num(sales.total_products)+' 个商品，完整明细请使用自选查询；未展示的商品不代表无销量。</p>':'')+((available||partial)&&rows.length?'<div class="report-table-wrap" tabindex="0" role="region" aria-label="活动付款商品销量"><table><thead><tr>'+['商品','平台','付款订单','购买数量','含退款订单','退款订单购买数量'].map(x=>'<th scope="col">'+x+'</th>').join('')+'</tr></thead><tbody>'+rows.map(x=>'<tr><th scope="row">'+esc(x.title||x.product_id)+'</th><td>'+esc(x.platform||'未提供')+'</td><td>'+num(x.paid_orders)+'</td><td>'+esc(x.quantity)+' '+esc(x.unit)+'</td><td>'+(x.refunded_orders==null?'—':num(x.refunded_orders))+'</td><td>'+(x.refunded_quantity==null?'—':esc(x.refunded_quantity)+' '+esc(x.unit))+'</td></tr>').join('')+'</tbody></table></div>':available?'<p>完整查询：当前区间活动商品销量为 0。</p>':'')+'<p class="muted">按活动付款订单中核实的商品行统计，不使用曝光、选择或加购替代销量；整单美元金额不分摊到商品，退款单列，不冒充净销量。退款订单购买数量仅标记含退款订单的原购买数量，非实际退货或退款件数。</p>';
 }
 function renderFcSnapshot(v,behavior,revenue){
  fcRevenue=revenue?{status:'available',totals:{paid_usd_minor:revenue.paidUsdMinor,paid_orders:revenue.paidOrders}}:{status:'unavailable'};
  show(behavior?.report||null,'live');
  const traffic=v.sources?.traffic?.lastSuccess?.summary;const trafficPanel=$('basic-traffic-report');trafficPanel.innerHTML='<h2>三页基础访问量 · 页面请求估算</h2><div class="metrics"><article class="metric"><span>正式活动文档请求</span><strong>'+(traffic?num(traffic.pageRequests):'—')+'</strong></article></div><p>统计截至 '+esc(bjt(v.sources?.traffic?.lastSuccess?.at))+'（北京时间）。仅187侧成功文档GET；刷新重复计数、边缘缓存可能漏计，不代表实际人数。</p>';
  $('mode-notice').textContent='三页共用一份活动汇总 · 服务器按北京时间00:00 / 08:00 / 16:00汇总；页面每10分钟读取快照，手动更新分析读取当前区间最新来源。';
  scheduleStatus.innerHTML='<h2>活动数据更新</h2><p>统计区间：'+esc(v.window.from)+' 至 '+esc(v.window.to)+'（UTC） · 下次计划 '+esc(bjt(v.nextScheduledAt))+'（北京时间）</p>'+Object.entries({behavior:'已授权行为',revenue:'活动订单销售',traffic:'页面请求估算'}).map(([key,label])=>{const source=v.sources?.[key];return '<p>'+label+'：'+(source?.lastSuccess?'本区间已保存 · '+esc(bjt(source.lastSuccess.at)):'本区间尚无完整结果')+(source?.lastAttempt?.status&&source.lastAttempt.status!=='available'?' · 最近读取未完整完成':'')+'</p>';}).join('')+'<p class="muted">Player Trio、Weekly Scout、SBC Core 不重复相加。付款来自FCSCOUT10订单，未扣退款；行为事件不作销量。</p>';
  let section=$('discount-revenue');if(!section){section=document.createElement('section');section.id='discount-revenue';section.className='panel';$('metrics').after(section);}section.hidden=false;
  section.innerHTML='<h2>FC27三页活动订单销售</h2>'+(revenue?'<div class="metrics">'+[['已付款订单',num(revenue.paidOrders)],['订单销售额 · USD',usd(revenue.paidUsdMinor)],['含退款订单',revenue.refundedOrders==null?'—':num(revenue.refundedOrders)]].map(([label,value])=>'<article class="metric"><span>'+label+'</span><strong>'+value+'</strong></article>').join('')+'</div>'+completionSummary(revenue.completed):'<p>当前区间付款数据不可用，未记为零。</p>')+'<p class="muted">按 UTC 付款日筛选，完成状态取自 Admin 当前订单。FCSCOUT10已付款整单金额，混合购物车不分摊到商品；不作为逐访客付款转化率。最后完整读取 '+esc(bjt(v.sources?.revenue?.lastSuccess?.at))+'（北京时间）。</p>'+productSalesHtml(revenue?.product_sales);
  $('feedback').textContent='FC27三页统一快照已读取；完整零值与来源缺测分别显示。';
 }
 async function refreshScheduled(gen){
  const kind=$('statistics-scope').value;revenueGeneration++;trafficGeneration++;trafficState=null;scheduleStatus.hidden=false;scheduleStatus.textContent='正在读取服务器计划汇总…';
  couponGeneration++;
  if(retainCoupon(couponCurrentFilter(),'正在更新；保留同一范围上次成功结果。'))renderCouponPanel();
  else {couponUsage=null;couponNotice='';if($('coupon-usage'))$('coupon-usage').hidden=true;}
  if(carnival())showCarnival(null);
  try{
   const response=await fetch('api/statistics-snapshot?'+new URLSearchParams({kind,activity:$('activity').value}),{credentials:'same-origin',signal:AbortSignal.timeout(10000)});if(gen!==generation)return;if(carnival()&&[401,403].includes(response.status)){couponPrevious=null;autoRefreshAllowed=false;throw Error('登录状态或访问权限未确认，请重新登录后重试。');}const v=await response.json();
   if(gen!==generation)return;if([400,401,403].includes(response.status))autoRefreshAllowed=false;if([401,403].includes(response.status))couponPrevious=null;if(!response.ok)throw Error(v.message||'计划汇总暂不可读');
   const source=name=>v.sources?.[name]?.lastSuccess,behavior=source('behavior')?.summary,revenue=source('revenue')?.summary,traffic=source('traffic')?.summary,attempt=v.sources?.traffic?.lastAttempt;
   currentContext=v.context||null;currentDiagnostics=null;
   if(currentContext?.games)$('game').innerHTML='<option value="all">全部游戏</option>'+currentContext.games.map(g=>'<option value="'+esc(g.id)+'">'+esc(g.name)+'</option>').join('');
   $('from').value=v.window.from;$('to').value=v.window.to;
   if(carnival()){
    showCarnival(behavior?.report);
    $('mode-notice').textContent='行为仅覆盖已同意统计的访问。计划汇总于北京时间 00:00、08:00、16:00 更新。';
    scheduleStatus.textContent=v.status==='not_started'?'活动尚未开始，统计将在开始后更新。':behavior?'行为汇总截至 '+bjt(source('behavior')?.at)+'（北京时间）':'当前区间尚无完整行为汇总 · 下次计划 '+bjt(v.nextScheduledAt)+'（北京时间）';
    void loadCouponUsage({activity:v.activityId,mode:'live',from:v.window.from,to:v.window.to},false);
    return;
   }
   if(fcActivity()){renderFcSnapshot(v,behavior,revenue);void loadCouponUsage({activity:$('activity').value,mode:'live',from:v.window.from,to:v.window.to},false);return;}
   showSeasonal(behavior?{visits:behavior.visits,visitors:behavior.sessionVisitors,seasonalTotals:behavior.totals,seasonalGames:behavior.byGame}:null,'live');
   $('mode-notice').textContent='服务器计划汇总 · 北京时间00:00 / 08:00 / 16:00更新；页面刷新仅读保存结果，不重新采集。';
   const labels={traffic:'页面请求估算',behavior:'已授权行为',revenue:'活动码付款'};
   scheduleStatus.innerHTML='<h2>定时刷新状态</h2><p>下次计划：'+esc(bjt(v.nextScheduledAt))+'（北京时间） · 最近整轮成功：'+esc(bjt(v.lastSuccessfulRunAt))+'</p><p>当前区间：'+esc(v.window.start)+' 至 '+esc(v.window.endExclusive)+'（UTC，结束不含）'+(kind==='yesterday'?'；这是UTC昨日，不是北京时间昨日。':'')+'</p><p>最近运行：'+esc(({success:'全部完成',partial:'部分完成 / 存在缺测',failed:'失败',running:'正在刷新'})[v.lastAttempt?.status]||'尚未运行')+'</p>'+Object.keys(labels).map(name=>{const s=v.sources?.[name],a=s?.lastAttempt,ok=s?.lastSuccess;return '<p>'+labels[name]+'：'+esc(a?.status==='available'?'完成':a?.status==='partial'?'部分覆盖':a?.status==='blocked'?'来源暂停':a?'缺测':'尚无本区间结果')+'；本区间最后成功 '+esc(bjt(ok?.at))+(a?.reason?' · '+esc(a.reason):'')+(!ok&&s?.previousSuccessAt?'；保留的旧成功为 '+esc(bjt(s.previousSuccessAt))+'，原区间 '+esc(s.previousWindow?.from)+' 至 '+esc(s.previousWindow?.to)+'，不填入当前指标。':'')+'</p>';}).join('')+'<p class="muted">三次累计结果不相加。手动按钮只重读计划结果；查看细分、渠道、每日趋势和商品明细请选“自选区间 / 细分查询”。</p>';
   const collection=$('activity-summary').querySelector('.activity-status-grid > div:nth-child(2)');collection.querySelector('p').textContent=behavior?'已授权行为汇总已读取':'已授权行为缺测';collection.querySelector('small').textContent='最后成功 '+bjt(source('behavior')?.at)+'（北京时间）';
   for(const id of ['channels','trend'])$(id).innerHTML='<p class="muted">计划汇总仅保存轻量指标；此明细请使用自选区间查询，不以空表代表零。</p>';
   seasonalTable();$('seasonal-offer-report').innerHTML='<h2>商品与折扣明细</h2><p class="muted">计划汇总未保存逐货架明细；请使用自选区间 / 细分查询。</p>';
   const t=traffic||attempt?.summary,ready=!!traffic;
   $('basic-traffic-report').innerHTML='<h2>基础访问量 · 187侧页面请求</h2><div class="metrics"><article class="metric"><span>187侧活动页面请求（估算）</span><strong>'+(ready?num(traffic.pageRequests):'缺测')+'</strong></article><article class="metric"><span>估算访客数 · 按IP去重</span><strong>缺测</strong></article></div><p>最后成功 '+esc(bjt(source('traffic')?.at))+'（北京时间）；'+(!ready&&t?.observedPageRequests!=null?'部分日志已观察 '+num(t.observedPageRequests)+' 次，不能当整段总量。':'')+'</p>'+(t?.coverage?'<p>日志覆盖 '+esc(bjt(t.coverage.from))+' 至 '+esc(bjt(t.coverage.through))+'（北京时间）。</p>':'')+'<p class="muted">仅187侧成功HTML GET估算；刷新会重复计数，边缘缓存可能漏计。真实访客IP链未核实，不把请求或出口IP当人数。</p>';
   let section=$('discount-revenue');if(!section){section=document.createElement('section');section.id='discount-revenue';section.className='panel';$('metrics').after(section);}section.hidden=false;
   section.innerHTML='<h2>活动码付款收入</h2>'+(revenue?'<div class="metrics"><article class="metric"><span>用码付款订单</span><strong>'+num(revenue.paidOrders)+'</strong></article><article class="metric"><span>付款订单金额 · USD</span><strong>'+usd(revenue.paidUsdMinor)+'</strong></article></div><p>后台付款显示金额：'+esc(revenue.paidCurrencies.map(c=>c.currency+' '+c.amount).join(' · ')||'当前区间无付款')+'</p><div class="report-table-wrap"><table><thead><tr><th>游戏</th><th>活动码</th><th>优惠</th><th>付款订单</th><th>金额 · USD</th></tr></thead><tbody>'+revenue.codes.map(c=>'<tr><th>'+esc(gameNames[c.gameId]||c.gameId)+'</th><td>'+esc(c.code)+'</td><td>'+num(c.offPercent)+'% OFF</td><td>'+num(c.paidOrders)+'</td><td>'+usd(c.paidUsdMinor)+'</td></tr>').join('')+'</tbody></table></div>':'<p>当前区间付款数据缺测，未填零。</p>')+'<p class="muted">12个活动专属码的已付款订单美元金额；未扣退款，不是净收入或逐访客归因。最后成功 '+esc(bjt(source('revenue')?.at))+'（北京时间）。</p>';
   $('feedback').textContent='计划汇总已读取；统计日期采用UTC，运行时间显示北京时间。';
  }catch(error){if(gen!==generation)return;fcRevenue=null;show(null,'live');for(const id of ['basic-traffic-report','discount-revenue'])if($(id))$(id).innerHTML='<h2>计划数据暂不可读</h2><p>未显示旧筛选数字，也不把失败填为零。</p>';if(carnival()){if(!retainCoupon(couponCurrentFilter(),'统计区间读取失败，请更新分析；保留同一范围上次成功结果。'))couponUsage={status:'unavailable',message:'统计区间读取失败，请更新分析。'};renderCouponPanel();}scheduleStatus.textContent=error.message;$('feedback').textContent=error.message;}
 }
 async function refresh(forceRevenue=false){if(fcActivity())lastFcReadAt=Date.now();if(forceRevenue===true&&(fcActivity()||carnival()))$('statistics-scope').value='custom';normalizeFilters();const gen=++generation,mode=$('mode').value,filter=Object.fromEntries(new FormData($('filters')));couponGeneration++;if(!carnival()||couponPrevious?.key!==couponKey(filter)){couponUsage=null;couponNotice='';renderCouponPanel();}if(!seasonal())delete filter.game;if(carnival())delete filter.platform;if(!filter.activity){show(null,mode);$('feedback').textContent='暂无可查询的已上线活动。请在活动管理区查看登记状态。';return;}$('feedback').textContent='';if(filter.from>filter.to&&(!window.CampaignServer||(!seasonal()&&!carnival())||mode!=='live'||$('statistics-scope').value==='custom')){$('feedback').textContent='开始日期不能晚于结束日期。';return;}
  scheduleControl.hidden=!window.CampaignServer||!scheduledActivity();
  if(mode!=='live'||['game','device','source'].some(k=>filter[k]&&filter[k]!=='all')||filter.windowHours!=='24')$('statistics-scope').value='custom';
  if(window.CampaignServer&&scheduledActivity()&&mode==='live'&&$('statistics-scope').value!=='custom')return refreshScheduled(gen);
  scheduleStatus.hidden=true;
  if(carnival()&&currentContext?.activityId!=='mmoexp-carnival'){
   const a=registry.find(a=>a.id==='mmoexp-carnival');
   currentContext={activityId:'mmoexp-carnival',startsAt:a?.startAt,endsAt:a?.endAt};
  }
  void loadRevenue(filter,forceRevenue===true);void loadCouponUsage(filter,forceRevenue===true);void loadTraffic(filter,forceRevenue===true);
  $('mode-notice').textContent=mode==='demo'?'演示模式 · 所有人数与金额均为虚构样本，不代表真实经营结果。':mode==='local'?'本机埋点体验 · 仅显示同源浏览器的最近 1,500 条预览事件；无外传、无真实成交。':mode==='test'?'PostHog 联调数据 · 从实际项目查询 test 事件，仅用于接入验收，不代表正式经营结果。':'真实数据模式 · 仅显示 FS 服务端查询结果；未接入不会用演示数据代替。';
  if(mode==='live'||mode==='test'){show(null,mode);$('feedback').textContent='正在查询接入状态…';try{const response=await fetch('api/report?'+new URLSearchParams(filter),{signal:AbortSignal.timeout(20000),credentials:'same-origin'});const result=await response.json();if([400,401,403].includes(response.status)||result.status==='not_configured')autoRefreshAllowed=false;if(!response.ok)throw Error(result.status==='not_configured'?'PostHog 尚未配置；请先在连接页录入只读密钥。':result.message||'真实数据接口不可用，请确认服务仍运行。');if(gen!==generation)return;if(carnival()&&result.status==='not_started'){currentContext=result.context;showCarnival(null);$('feedback').textContent='';return;}if(result.status!=='available'||!result.report)throw Error(result.message||'数据暂不可用');currentContext=result.context||null;currentDiagnostics=result.diagnostics||null;if(currentContext?.games){const selected=$('game').value;$('game').innerHTML='<option value="all">全部游戏</option>'+currentContext.games.map(g=>'<option value="'+esc(g.id)+'">'+esc(g.name)+'</option>').join('');if(currentContext.games.some(g=>g.id===selected))$('game').value=selected;}show(result.report,mode);$('feedback').textContent='查询结果时间：'+bjt(result.generatedAt)+'（北京时间） · 正式查询最多缓存5分钟 · '+result.coverage;}catch(error){if(gen===generation){show(null,mode);$('feedback').textContent=error.message;}}return;}
  let events=[];try{events=mode==='demo'?window.activityDemoEvents(defaults):JSON.parse(localStorage.getItem('fc-activity-events-v1')||'[]');}catch{$('feedback').textContent='本地事件存储不可用。';}show(core.summarize(events,filter),mode);
 }
 async function save(next){next=core.validateRegistry(next);if(window.CampaignServer){const v=await CampaignServer.save({registry:next});registry=v.registry;$('registry-note').textContent='已保存到服务器 · 版本 '+v.revision+' · '+v.updatedAt;}else{localStorage.setItem(key,JSON.stringify(next));registry=next;}renderRegistry();refresh();}
 $('filters').addEventListener('submit',e=>{e.preventDefault();autoRefreshAllowed=true;normalizeFilters();const params=new URLSearchParams(new FormData($('filters')));history.replaceState(null,'',location.pathname+'?'+params);refresh(true);});$('mode').addEventListener('change',refresh);window.addEventListener('storage',e=>{if(e.key==='fc-activity-events-v1'&&$('mode').value==='local')refresh();});
 $('theme').addEventListener('click',()=>{const dark=document.documentElement.dataset.fsTheme!=='dark';document.documentElement.dataset.fsTheme=dark?'dark':'light';$('theme').textContent=dark?'切换浅色':'切换深色';});
 function edit(id){if(window.CampaignServer&&!CampaignServer.state?.canEdit){$('feedback').textContent='当前账号仅可查看';return;}editing=id||null;const a=registry.find(x=>x.id===id);$('editor-form').reset();$('activity-id').value=a?.id||'';$('activity-id').readOnly=!!id;$('activity-name').value=a?.name||'';$('activity-path').value=a?.path||'';for(const [id,value] of Object.entries({'activity-type':a?.type||'commerce','activity-status':a?.status||'draft','activity-owner':a?.owner||'','activity-version':a?.version||'1','activity-origin':a?.origin||'https://www.mmoexp.com','activity-window':a?.windowHours||24,'activity-start':(a?.startAt||'').replace(/Z$/,'').slice(0,16),'activity-end':(a?.endAt||'').replace(/Z$/,'').slice(0,16)}))$(id).value=value;$('match-rows').innerHTML='';for(const m of a?.matches||[])addMatch(m);contract();$('editor-title').textContent=id?'编辑活动':'新增活动';$('editor-error').textContent='';$('editor').showModal();}
 function contract(){const prediction=$('activity-type').value==='prediction';$('matches-editor').hidden=!prediction;$('event-contract').textContent=prediction?'参与漏斗：赛事曝光 → 开始预测 → 服务端保存成功。奖励漏斗：中奖资格 → 真实到账 → 真实核销。登录、赛果和发券状态由原站决定；不能把点击券卡当到账或核销。':'商品漏斗：访问 → 商品曝光 → 加购确认 → 真实结账 → 支付。前端只能证明行为，后端负责成交。';}
 function addMatch(m={}){const row=document.createElement('div');row.className='match-row';row.innerHTML=[['id','赛事 ID','text'],['name','赛事名称','text'],['kickoff','开赛时间 · UTC','datetime-local'],['lockAt','封盘时间 · UTC','datetime-local']].map(([key,label,type])=>`<label>${label}<input data-field="${key}" type="${type}" value="${esc((m[key]||'').replace(/Z$/,'').slice(0,type==='datetime-local'?16:80))}" ${type==='text'?'required maxlength="80"':''}></label>`).join('')+'<button type="button" class="fs-btn" data-remove-match>移除本配置行</button>';$('match-rows').append(row);}
 $('add-match').addEventListener('click',()=>addMatch());$('match-rows').addEventListener('click',e=>{if(e.target.closest('[data-remove-match]'))e.target.closest('.match-row').remove();});$('activity-type').addEventListener('change',contract);
 function activityFilters(){$('game').value='all';const a=registry.find(x=>x.id===$('activity').value);$('template').value=a?.type==='prediction'?'prediction':'commerce';const hours=String(a?.windowHours||24);if(![...$('windowHours').options].some(o=>o.value===hours))$('windowHours').add(new Option(hours+' 小时',hours));$('windowHours').value=hours;$('match').innerHTML='<option value="all">全部赛事</option>'+(a?.matches||[]).map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('');normalizeFilters();}
 $('activity').addEventListener('change',()=>{activityFilters();refresh();});
 $('template').addEventListener('change',()=>{if($('template').value==='reward')$('windowHours').value='720';});
 $('add').addEventListener('click',()=>edit());$('activities').addEventListener('click',e=>{const button=e.target.closest('[data-edit]');if(button)edit(button.dataset.edit);});$('cancel').addEventListener('click',()=>$('editor').close());
 $('editor-form').addEventListener('submit',async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{const item={id:$('activity-id').value,name:$('activity-name').value,path:$('activity-path').value,view:registry.find(x=>x.id===editing)?.view||$('activity-id').value,type:$('activity-type').value,status:$('activity-status').value,owner:$('activity-owner').value,version:$('activity-version').value,origin:$('activity-origin').value,windowHours:Number($('activity-window').value),startAt:$('activity-start').value?$('activity-start').value+'Z':'',endAt:$('activity-end').value?$('activity-end').value+'Z':'',matches:[...$('match-rows').children].map(row=>Object.fromEntries([...row.querySelectorAll('input')].map(el=>[el.dataset.field,el.value&&el.type==='datetime-local'?el.value+'Z':el.value])))};await save(editing?registry.map(a=>a.id===editing?item:a):[...registry,item]);$('editor').close();}catch(error){$('editor-error').textContent=error.message;}finally{submit.disabled=false;}});
 $('export').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(registry,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='activity-registry.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 $('import').addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>100000)throw Error('文件超过 100 KB');const next=core.validateRegistry(JSON.parse(await file.text()));await save(next);$('feedback').textContent=window.CampaignServer?'活动配置已保存服务器；网站追踪接入需开发完成。':'活动配置已导入本浏览器；尚未发布或启用追踪。';}catch(error){$('feedback').textContent='导入失败：'+error.message;}finally{e.target.value='';}});
 $('management').open=!window.CampaignServer;$('show-planned').addEventListener('change',()=>{renderRegistry();refresh();});renderRegistry();const initial=new URLSearchParams(location.search);if(window.CampaignServer){
  $('mode').value='live';
  const activeIds=registry.filter(a=>a.status==='active').map(a=>a.id);
  const preferred=['mmoexp-carnival','mmoexp-seasonal'].find(id=>activeIds.includes(id));
  if(preferred)$('activity').value=preferred;
 }
 if(initial.get('mode')==='test')$('mode').value='test';
 const initialActivity=core.canonicalActivity(initial.get('activity'));
 if([...$('activity').options].some(o=>o.value===initialActivity))$('activity').value=initialActivity;
 activityFilters();refresh();if(window.CampaignServer)setInterval(()=>{if(autoRefreshAllowed&&(!fcActivity()||Date.now()-lastFcReadAt>=600000)&&document.visibilityState==='visible'&&$('mode').value==='live'&&!$('editor').open&&(!scheduledActivity()||$('statistics-scope').value!=='custom'))refresh();},60000);
})();
