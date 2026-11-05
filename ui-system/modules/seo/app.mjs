import {SnapshotClient, value, latestRow, chartSegments} from './model.mjs';
const client = new SnapshotClient(), select = document.querySelector('#scope'), panel = document.querySelector('#panel'), status = document.querySelector('#status');
const names = {FC27:'FC27', D4:'Diablo 4', AION2:'Aion2', WOW_FOREVER:'WowForever'};
const views = {overview:['经营全景','history'], timeline:['游戏日程',null], sources:['数据来源','sources'], rankings:['关键词/竞品','rankings'], pages:['页面健康','pages'], orders:['自然搜索成交','history'], ai:['行动与AI分析',null], history:['每日明细','history']};
const primary = ['overview','timeline','sources'];
const labels = {available:'可用', provisional:'初步值', pending:'等待来源', no_rows:'暂无记录', failed:'采集失败', stale:'上次有效值', missing:'缺少来源', found:'已找到', not_found:'未找到'};
const columns = {rankings:[['source_date','来源日期'],['keyword','关键词'],['rank','自然名次'],['status','状态'],['observed_at','观察时间']], pages:[['source_date','来源日期'],['url','页面'],['status_code','HTTP状态'],['title','标题'],['observed_at','观察时间']], sources:[['source_date','源日期'],['source','来源'],['status','状态'],['source_timezone','源时区'],['collected_at','最近读取'],['error','原因']]};
let active = 'overview', epoch = 0;
const text = (tag, content, className) => {const e=document.createElement(tag); if(content!=null)e.textContent=content; if(className)e.className=className; return e;};
const badge = (content, tone='neutral') => text('span',content,'badge '+tone);
function button(content, action, className='quiet-button') {const b=text('button',content,className); b.type='button'; b.onclick=action; return b;}
function openView(view) {active=view; render();}
const viewButton = (view, label=views[view][0]) => button(label,()=>openView(view));
function sectionHeading(title, note, view) {
  const h=text('div',null,'section-heading'), group=text('div'); group.append(text('h2',title)); if(note)group.append(text('p',note,'muted'));
  h.append(group); if(view)h.append(viewButton(view)); return h;
}
function table(headers, rows, caption) {
  const region=text('div',null,'table-wrapper'); region.tabIndex=0; region.setAttribute('role','region'); region.setAttribute('aria-label',caption);
  const t=text('table'), head=text('thead'), tr=text('tr'), body=text('tbody'); t.append(text('caption',caption));
  headers.forEach(h=>{const th=text('th',h);th.scope='col';tr.append(th);});head.append(tr);t.append(head,body);
  rows.forEach(row=>{const tr=text('tr');row.forEach((v,i)=>{const cell=text(i?'td':'th',v??'—');if(!i)cell.scope='row';tr.append(cell);});body.append(tr);});
  region.append(t);return region;
}
function historyTable(rows) {
  return table(['来源日期','GSC点击','GSC展示','GSC CTR','自然会话','购买次数','Admin客单价（$）','预估成交额（$）'],rows.map(r=>[r.source_date,value(r.metrics.gsc?.clicks),value(r.metrics.gsc?.impressions),value(r.metrics.gsc?.ctr,true),value(r.metrics.ga4?.sessions),value(r.metrics.ga4?.purchase_events),value(r.metrics.admin?.admin_customer_price_usd),value(r.estimate?.revenue_usd)]),'每日搜索与成交，各来源按实际统计时区');
}
function details(title, child) {const box=text('details',null,'data-disclosure');box.append(text('summary',title),child);return box;}
function keyValues(items, className='metric-pair') {
  const dl=text('dl',null,className);items.forEach(([label,val])=>{const group=text('div');group.append(text('dt',label),text('dd',val));dl.append(group);});return dl;
}
function empty(title, message, view) {const e=text('div',null,'empty');e.append(text('h3',title),text('p',message,'muted'));if(view)e.append(viewButton(view));return e;}
function chart(rows, extract, title, tone='demand') {
  const segments=chartSegments(rows,extract), figure=text('figure',null,'trend-chart '+tone);
  if(!segments.length){figure.append(text('p','暂无可绘制的真实历史。','chart-empty'));return figure;}
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 480 142');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('role','img');svg.setAttribute('aria-label',title+'，缺失日期留空。完整数值见每日明细。');
  const titleNode=document.createElementNS(svg.namespaceURI,'title');titleNode.textContent=title;svg.append(titleNode);
  const max=Math.max(...segments.flat().map(p=>p.value),1),x=i=>12+i*456/Math.max(1,rows.length-1),y=v=>126-v*110/max;
  for(const height of [16,71,126]){const line=document.createElementNS(svg.namespaceURI,'line');for(const [k,v] of Object.entries({x1:12,x2:468,y1:height,y2:height}))line.setAttribute(k,v);line.setAttribute('class','chart-grid');svg.append(line);}
  segments.forEach(points=>{
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',points.map((p,i)=>(i?'L':'M')+x(p.index).toFixed(2)+' '+y(p.value).toFixed(2)).join(' '));path.setAttribute('class','chart-line');svg.append(path);
    points.forEach(p=>{const dot=document.createElementNS(svg.namespaceURI,'circle');dot.setAttribute('cx',x(p.index));dot.setAttribute('cy',y(p.value));dot.setAttribute('r','3');dot.setAttribute('class','chart-point');const hint=document.createElementNS(svg.namespaceURI,'title');hint.textContent=rows[p.index].source_date+'：'+value(p.value);dot.append(hint);svg.append(dot);});
  });
  figure.append(svg);const axis=text('figcaption',null,'chart-axis');[0,Math.floor((rows.length-1)/2),rows.length-1].forEach(i=>axis.append(text('span',rows[i].source_date.slice(5))));figure.append(axis);return figure;
}
function card(title, source, tone) {
  const c=text('article',null,'journey-card '+tone),header=text('div',null,'card-heading');header.append(text('h3',title),badge(source));c.append(header);return c;
}
function cardValue(root, amount, caption) {const group=text('div',null,'primary-metric');group.append(text('strong',amount),text('span',caption));root.append(group);}
function coverageStrip(history) {
  const strip=document.querySelector('#source-strip');strip.replaceChildren();
  for(const [key,label] of [['gsc','GSC'],['ga4','GA4'],['admin','Admin']]){
    const count=history.filter(r=>r.metrics[key]!=null).length;
    const latest=latestRow(history,key),state=latest?.source_status?.[key]?.status;
    strip.append(button(label+' '+count+'/30日'+(state?' / '+(labels[state]??state):''),()=>openView('sources'),'source-chip'));
  }
  strip.append(text('span','独立排名与页面检测按实际配置展示','muted'));
}
function loading() {const e=text('div',null,'journey-grid loading-grid');for(let i=0;i<3;i++){const c=text('div',null,'skeleton-card');c.setAttribute('aria-hidden','true');c.append(text('div'),text('div'),text('div'));e.append(c);}const msg=text('span','正在读取已发布快照…','sr-only');e.append(msg);return e;}
function selectedURL() {
  const url=new URL(location.href);if(client.id)url.searchParams.set('snapshot_id',client.id);else url.searchParams.delete('snapshot_id');url.searchParams.set('game',select.value);url.searchParams.set('tab',active);history.replaceState(null,'',url);
  const download=document.querySelector('#export');if(client.id){download.href=client.exportURL(select.value);download.download=`${client.id}-${select.value}.csv`;download.setAttribute('aria-disabled','false');}else{download.removeAttribute('href');download.setAttribute('aria-disabled','true');}
  const selected=primary.includes(active)?active:'overview';document.querySelectorAll('[role=tab]').forEach(b=>{const on=b.dataset.view===selected;b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1;});panel.setAttribute('aria-labelledby','tab-'+selected);
}
function overview(history, scope, request) {
  coverageStrip(history);panel.append(sectionHeading('全链路概览',null,'history'));
  const grid=text('div',null,'journey-grid'),latest=history.at(-1),gsc=latestRow(history,'gsc');
  const demand=card('上游 · 需求走势','GSC展示','demand');cardValue(demand,value(gsc?.metrics.gsc.impressions),'搜索展示');
  demand.append(text('p',gsc?'最近源日 '+gsc.source_date+' · 太平洋时间':'暂无有效GSC源日','source-caption'),chart(history,r=>r.metrics.gsc?.impressions,'近30日GSC搜索展示','demand'),text('p','用搜索展示观察需求；社区热度与Google Trends尚未接入。','card-note'));
  const search=card('中游 · 搜索表现','GSC','search');cardValue(search,value(gsc?.metrics.gsc.clicks),'自然搜索点击');
  search.append(keyValues([['点击率',value(gsc?.metrics.gsc.ctr,true)],['GSC平均位置',value(gsc?.metrics.gsc.position)]]),chart(history,r=>r.metrics.gsc?.clicks,'近30日GSC搜索点击','search'),text('p','GSC平均位置不作为固定条件的Google排名。','card-note'));
  const sales=card('下游 · 成交预估','GA4 + Admin','sales');cardValue(sales,latest?.estimate?.revenue_usd==null?'—':'$'+value(latest.estimate.revenue_usd),'预估SEO成交额');
    sales.append(text('p','业务统计日 '+(latest?.source_date??client.meta.report_date)+' · 北京时间','source-caption'),keyValues([['自然会话',value(latest?.metrics.ga4?.sessions)],['购买次数',value(latest?.metrics.ga4?.purchase_events)],['Admin客单价',latest?.metrics.admin?.admin_customer_price_usd==null?'—':'$'+value(latest.metrics.admin.admin_customer_price_usd)]],'sales-metrics'),viewButton('orders','查看成交预估明细'),text('p','购买次数 × Admin现成客单价；金额为预估，无法逐单归因。','card-note warn'));
  grid.append(demand,search,sales);panel.append(grid);
  const matrix=text('section',null,'dashboard-section');matrix.append(sectionHeading('国家竞争矩阵','按国家、语言、设备与关键词分别观察真实竞争位置。','rankings'));panel.append(matrix);
  if(client.meta.sources?.serp==='not_configured')renderMarkets(matrix,scope);else loadOptional('markets',scope,request,matrix,result=>renderMarkets(matrix,scope,result.rows,result.source_state));
  const action=text('section',null,'dashboard-section');action.append(sectionHeading('行动与分析中心','基础规则独立运行，AI按游戏单独启用。','ai'));
  const actions=text('div',null,'action-grid'),rules=text('article',null,'action-card'),ai=text('article',null,'action-card');
  rules.append(text('h3','基础规则提醒'),text('p','正在读取此快照的规则结果…','muted pending'));ai.append(text('h3','可选AI增强'),text('p','正在读取独立控制配置…','muted'));actions.append(rules,ai);action.append(actions);panel.append(action);
  loadOptional('rules',scope,request,rules,result=>{rules.replaceChildren(text('h3','基础规则提醒'),badge('程序计算'));if(!result.rows.length)rules.append(text('p','当前快照没有触发基础提醒。','muted'));result.rows.forEach(r=>{rules.append(text('p',r.message));if(r.evidence_start)rules.append(text('p',r.evidence_start+' 至 '+r.evidence_end,'muted'));});rules.append(viewButton('pages','查看页面健康'));});
  client.get('ai-policy').then(policy=>{
    if(request!==epoch||!ai.isConnected)return;
    const allowed=policy.ai_enabled&&policy.projects[scope]?.ai_enabled;
    ai.replaceChildren(text('h3','可选AI增强'),badge(policy.runtime_status==='not_configured'?'尚未配置':allowed?'已允许':'已关闭'));
    ai.append(text('p',policy.runtime_status==='not_configured'?'Hermes增强尚未接入。开关可独立保存，基础数据照常展示。':allowed?'等待下一夜间分析，白天恢复不自动补跑。':'本游戏不发起新AI分析，基础规则、历史与取数照常运行。','muted'),viewButton('ai','查看AI设置'));
  }).catch(()=>{if(request===epoch&&ai.isConnected)ai.replaceChildren(text('h3','可选AI增强'),text('p','AI设置暂不可用，基础数据可继续查看。','muted'),viewButton('ai','查看AI设置'));});
  panel.append(details('展开每日数据，核对趋势与预估数值',historyTable(history)));
}
function renderMarkets(root, scope, rows=[], sourceState={}) {
  if(['partial','failed','stale'].includes(sourceState.status))root.append(text('p','最近采样 '+sourceState.source_date+'：'+(labels[sourceState.status]??'部分完成')+'；下方保留实际观察时间，失败不视为掉榜。','matrix-notice'));
  if(rows.length){
    const groups=new Map();for(const row of rows){const key=JSON.stringify([row.country,row.language,row.device,row.location??'']);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
    for(const group of groups.values()){
      const first=group[0],box=text('article',null,'market-card'),order=['MMOEXP','IGGM','U4GM','U7BUY','LootBar','G2G','Eldorado'],brands=[...new Set(group.map(r=>r.brand))].sort((a,b)=>(order.indexOf(a)<0?99:order.indexOf(a))-(order.indexOf(b)<0?99:order.indexOf(b))||a.localeCompare(b)),queries=new Map();
      box.append(text('h3',[first.country,first.language,first.device,first.location].filter(Boolean).join(' / ')),text('p','Google自然结果 · Bright Data · 固定快照','muted'));
      for(const row of group){const key=JSON.stringify([row.keyword,row.source_date,row.depth]);if(!queries.has(key))queries.set(key,[]);queries.get(key).push(row);}
      const cells=[...queries.values()].map(samples=>{const r=samples[0];return [r.keyword,...brands.map(brand=>{const cell=samples.find(x=>x.brand===brand);return !cell?'待采样':cell.status==='found'?'#'+cell.rank:cell.status==='not_found'?'前'+cell.depth+'未找到':cell.status==='insufficient_depth'?'深度不足 '+cell.effective_depth+'/'+cell.depth:'采集失败';}),r.observed_at??r.source_date];});
      box.append(table(['关键词',...brands,'观察时间'],cells,'已发布国家竞争样本'));root.append(box);
    }return;
  }
  root.append(text('p','独立SERP尚无已发布样本。按已确认的八国范围等待配置与首次夜间采样；未采集前不展示名次或涨跌。','matrix-notice'));
  const grid=text('div',null,'market-grid');
  for(const [code,name] of [['US','美国'],['GB','英国'],['DE','德国'],['FR','法国'],['ES','西班牙'],['PT','葡萄牙'],['NL','荷兰'],['BR','巴西']]){
    const c=text('article',null,'market-card'),header=text('div',null,'market-heading'),title=text('div',null,'market-title');title.append(text('span',code,'country-code'),text('h3',name+' / '+names[scope]));header.append(title,badge('等待采样'));c.append(header);
    const rank=text('div',null,'market-placeholder');rank.append(text('strong','—'),text('p','等待首批固定条件Google排名','muted'));c.append(rank);
    c.append(text('p','MMOEXP / IGGM / U4GM / U7BUY / LootBar / G2G / Eldorado','brand-list'));grid.append(c);
  }
  root.append(grid);
}
function loadOptional(kind,scope,request,root,done) {
  const load=async()=>{let result=await client.load(kind,scope);if(['markets','calendar'].includes(kind))while(result.next_cursor!=null&&request===epoch){const next=await client.load(kind,scope,result.next_cursor);result={...next,rows:[...result.rows,...next.rows]};}return result;};
  load().then(result=>{if(request===epoch&&root.isConnected)done(result);}).catch(error=>{if(request===epoch&&root.isConnected){root.querySelector('.pending')?.remove();root.append(text('p',(kind==='markets'?'国家竞争':kind==='calendar'?'游戏日程':views[kind]?.[0]??'基础提醒')+'暂不可用：'+error.message,'error'));}});
}
function detailCells(kind,row) {return columns[kind].map(([key])=>key==='status'?(labels[row.status]??row.status):row[key]??row.metrics?.[key]);}
function timeline(scope,request) {
  panel.append(sectionHeading(names[scope]+' 游戏日程','官方来源优先，事件按真实观察时间记录。'));
  if(client.meta.sources?.calendar!=='configured')panel.append(empty('游戏日程来源尚未接入','当前没有可展示的已核验游戏事件。demo中的赛季、版本和运营日程不作为真实公告。','sources'));
  else {
    const events=text('div',null,'calendar-events');events.append(text('p','正在读取此快照的日程…','pending'));panel.append(events);
    loadOptional('calendar',scope,request,events,result=>{events.replaceChildren(text('p','复用已发布资料。公告发布日期不代替事件日期；原来源读取时间单独保留。','muted'));if(!result.rows.length)events.append(empty('本游戏暂无已发布日程','缺少范围、来源或日期的项目保留缺口，不生成预测。','sources'));
      for(const row of [...result.rows].sort((a,b)=>(a.event_date??'9999').localeCompare(b.event_date??'9999'))){const card=text('article',null,'source-card');card.append(text('h3',row.title),badge(row.verification==='user_provided'?'用户提供、未独立核验':row.source_status==='stale'?'来源已过期':'已有来源记录'),text('p',row.event_date?(row.event_date+(row.event_end_date?' → '+row.event_end_date:'')):'事件日期待核'));if(row.summary)card.append(text('p',row.summary));card.append(text('p','原来源读取 '+(row.upstream_observed_at??(row.upstream_source_date?row.upstream_source_date+'（时刻未记录）':'时刻未记录'))+' · 纳入观察 '+row.source_date,'muted'));if(row.published_at)card.append(text('p','公告发布 '+row.published_at,'muted'));if(row.source_url){const link=text('a','查看来源公告','quiet-button');link.href=row.source_url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}if(row.evidence)card.append(details('来源证据',text('p',row.evidence)));events.append(card);}
    });
  }
  const schedule=text('div',null,'schedule-note');schedule.append(text('h3','看板日更安排'),keyValues([['批次启动','每日03:20（北京时间）'],['基础发布','有效即发布，最晚06:30'],['白天读取','固定已发布快照']],'schedule-grid'));panel.append(schedule);
}
async function sources(scope,request) {
  const history=await client.load('history',scope);if(request!==epoch)return;panel.replaceChildren();coverageStrip(history.rows);
  panel.append(sectionHeading('数据来源与覆盖','30天展示窗口，迟到与缺失保留实际状态。'));
  const grid=text('div',null,'source-grid');
  for(const [key,label] of [['gsc','Google Search Console'],['ga4','Google Analytics 4'],['admin','Admin原生汇总']]){
    const row=latestRow(history.rows,key),c=text('article',null,'source-card');c.append(text('h3',label),badge(row?(labels[row.source_status?.[key]?.status]??'已有数据'):'缺少数据'));
    c.append(keyValues([['可用覆盖',history.rows.filter(r=>r.metrics[key]!=null).length+'/30日'],['最近源日',row?.source_date??'—'],['来源时区',row?.source_status?.[key]?.source_timezone??'—']]));grid.append(c);
  }
  panel.append(grid);
  const note=text('div',null,'source-boundary');note.append(text('h3','可选来源与费用'),text('p','独立SERP：'+(client.meta.sources?.serp==='configured'?'已配置':'未配置')+'；页面检测：'+(client.meta.sources?.pages==='configured'?'已配置':'未配置')+'。游戏日程：'+(client.meta.sources?.calendar==='configured'?'已配置，按快照内实际材料展示':'未配置')+'。社区热度与Google Trends尚未接入。','muted'),text('p','AI费用账本未接入，暂无可核验的SEO模型费用。','muted'),viewButton('ai','查看独立AI开关'));panel.append(note);
  const result=await client.load('sources',scope);if(request!==epoch)return;
  const metadata=keyValues([['snapshot_id',client.id],['facts_hash',client.meta.facts_hash],['发布日期',client.meta.publication_date],['业务目标日',client.meta.report_date]],'snapshot-metadata');
  const ledger=text('div');ledger.append(metadata,table(columns.sources.map(c=>c[1]),result.rows.map(r=>detailCells('sources',r)),'数据来源与覆盖状态'));panel.append(details('查看快照校验与逐日来源明细',ledger));
  appendNext(result,'sources',scope,request,ledger);
}
function appendNext(data,kind,scope,request,root=panel) {
  if(data.next_cursor==null)return;const next=button('继续读取此版本',async()=>{
    next.disabled=true;try{const result=await client.load(kind,scope,data.next_cursor);if(request!==epoch)return;const body=root.querySelector('tbody');table([],result.rows.map(r=>detailCells(kind,r)),'续页').querySelectorAll('tbody tr').forEach(tr=>body.append(tr));next.remove();appendNext(result,kind,scope,request,root);}catch(error){next.disabled=false;status.textContent=error.message;}
  });root.append(next);
}
async function render() {
  const request=++epoch,scope=select.value;selectedURL();panel.replaceChildren(loading());panel.setAttribute('aria-busy','true');
  document.querySelector('#detail-nav').replaceChildren();if(!primary.includes(active))document.querySelector('#detail-nav').append(viewButton('overview','返回经营全景'),text('span',views[active][0],'muted'));
  try{
    if(active==='ai'){
      panel.replaceChildren(sectionHeading('行动与AI分析','开关实时生效，数据仍绑定同一已发布快照。'));
      const rules=text('div',null,'action-card');panel.append(rules);if(client.id)loadOptional('rules',scope,request,rules,result=>{rules.replaceChildren(text('h3','基础规则提醒'));result.rows.forEach(r=>rules.append(text('p',r.message)));if(!result.rows.length)rules.append(text('p','当前快照没有触发基础提醒。','muted'));});else rules.append(text('p','基础提醒等待首个夜间批次。','muted'));
      const box=text('div',null,'ai-settings');panel.append(box);import('./ai.mjs').then(m=>{if(request===epoch)m.mount(box,client);}).catch(()=>{if(request===epoch)box.append(text('p','AI组件暂不可用，基础数据可继续查看。','error'));});return;
    }
    if(!client.id){panel.replaceChildren(empty('等待首个夜间批次发布','没有可展示的已发布事实。'));return;}
    if(active==='timeline'){panel.replaceChildren();timeline(scope,request);return;}
    if(active==='sources'){await sources(scope,request);return;}
    const kind=views[active][1],data=await client.load(kind,scope);if(request!==epoch)return;panel.replaceChildren();
    if(active==='overview')overview(data.rows,scope,request);
    else if(active==='history'){panel.append(sectionHeading(names[scope]+' 每日数据','缺失留空，金额与指标来自此快照。'),historyTable(data.rows));}
    else if(active==='orders'){
      panel.append(sectionHeading('自然搜索成交预估','直接使用同日、同游戏MMOEXP主站Admin客单价。'));
      panel.append(text('p','GA4自然搜索购买事件次数 × Admin原生customer_price。交易标识为空，不能关联具体订单或用户；后台该字段口径为付费客户均额，GA4为初步值。','method-note'));
      panel.append(chart(data.rows,r=>r.estimate?.revenue_usd,'近30日预估SEO成交额','sales'));
      panel.append(table(['来源日期','购买事件次数','Admin客单价（$）','预估成交额（$）','状态'],data.rows.map(r=>[r.source_date,value(r.metrics.ga4?.purchase_events),value(r.metrics.admin?.admin_customer_price_usd),value(r.estimate?.revenue_usd),r.estimate?.status==='estimated'?'预估':'缺少来源']),'按日预估，缺失不补零'));
    }else{
      panel.append(sectionHeading(views[active][0],'真实观察样本，按其源日期与观察时间展示。'));
      if(!data.rows.length)panel.append(empty('暂无已发布样本',client.meta.sources?.[active==='rankings'?'serp':active]==='not_configured'?'该数据源尚未接入。其他基础数据可正常查看。':'等待后续夜间采集，失败不按排名下跌处理。','sources'));
      else panel.append(table(columns[active].map(c=>c[1]),data.rows.map(r=>detailCells(active,r)),views[active][0]));
      appendNext(data,kind,scope,request);
    }
  }catch(error){if(request===epoch)panel.replaceChildren(text('p',error.message,'error'),button('重试读取此快照',render));}
  finally{if(request===epoch)panel.setAttribute('aria-busy','false');}
}
for(const key of primary){const b=button(views[key][0],()=>openView(key));b.id='tab-'+key;b.dataset.view=key;b.setAttribute('role','tab');b.setAttribute('aria-controls','panel');document.querySelector('#tabs').append(b);}
document.querySelector('#tabs').addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const current=primary.includes(active)?active:'overview',i=primary.indexOf(current),key=primary[event.key==='Home'?0:event.key==='End'?primary.length-1:(i+(event.key==='ArrowRight'?1:primary.length-1))%primary.length];document.querySelector('#tab-'+key).focus();openView(key);
});
select.addEventListener('change',()=>{document.querySelector('#source-strip').replaceChildren(text('span',names[select.value]+'：来源覆盖见数据来源','muted'));render();});
document.querySelector('#ai-settings-entry').onclick=()=>openView('ai');
(async()=>{
  try{
    const initialEpoch=epoch,params=new URLSearchParams(location.search),meta=await client.init(params.get('snapshot_id'));Array.from(select.options).forEach(o=>{o.disabled=!meta.games.includes(o.value);});select.value=meta.games.includes(params.get('game'))?params.get('game'):meta.games[0];select.disabled=false;
    if(epoch===initialEpoch)active=Object.hasOwn(views,params.get('tab'))?params.get('tab'):'overview';document.querySelector('#version').textContent='发布 '+meta.publication_date+' / 业务目标 '+meta.report_date+' / '+meta.snapshot_id;document.querySelector('#business-day').textContent='业务目标日 '+meta.report_date;
    status.textContent=meta.data_status==='partial'?'已发布固定快照，部分来源延迟或未接入':'已发布固定快照';await render();
  }catch(error){document.querySelector('#version').textContent='暂未读取数据版本';status.textContent=error.message;if(active!=='ai'){panel.replaceChildren(empty('暂无可读取的已发布数据','每日03:20启动独立批次，基础有效即发布。'));panel.setAttribute('aria-busy','false');}}
})();
