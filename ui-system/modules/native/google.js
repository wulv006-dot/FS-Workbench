export function mount(scope){
const {window,document,fetch,URL,setTimeout,setInterval,clearTimeout,clearInterval,requestAnimationFrame,cancelAnimationFrame,MutationObserver,ResizeObserver,addEventListener,matchMedia}=scope;
const globalThis=window;
/* Duplicate business displays use the maintained date-query page. Google views remain independent. */
window.MMOEXPBusiness={mount(panel){const title=document.createElement('h2'),note=document.createElement('p'),link=document.createElement('a');title.textContent='经营分析';note.textContent='经营数据已统一到全局分析，可选择项目、网站与自定义日期。';link.href='/dashboard/analytics/?mode=business';link.textContent='打开经营分析 →';panel.replaceChildren(title,note,link);},unmount(){},refresh(){}};

'use strict';
/* Server-authenticated read-only snapshots. No Google credential or mutation endpoint. */
(function(){
const TRAFFIC_RULE_VERSION='traffic-multigame-name-hints-20261017-v3';
function currentTrafficPeriod(period){return period?.rule_version===TRAFFIC_RULE_VERSION;}
function currentGamePeriod(period){return currentTrafficPeriod(period)&&period?.game_projection_version==='traffic-game-projections-20261019-v1';}
const labels={nativeCvr:'Ads原生CVR',interactions:'广告互动',sessions:'会话',activeUsers:'活跃用户',newUsers:'新用户',engagedSessions:'参与会话',engagementRate:'参与率',screenPageViews:'页面/屏幕浏览',averageSessionDuration:'平均会话时长',bounceRate:'跳出率',ecommercePurchases:'购买事件',purchaseRevenue:'GA4报告收入',clicks:'点击',impressions:'展示',ctr:'CTR（点击率）',position:'平均位置',cost:'花费 · USD',cpc:'CPC（单次点击花费）· USD',conversions:'Ads归因转化',cpa:'CPA（单次转化花费）· USD',conversionsValue:'Ads归因价值 · USD',platformRoas:'Ads平台ROAS（广告回报倍数）',share:'占比',impressionShare:'展示占比',campaignId:'Campaign ID（广告系列编号）',customerId:'Customer ID（广告账号编号）',campaignName:'广告系列',date:'数据日期'};
const explanations={
 sessions:'一次访问过程；同一个人可多次访问。默认连续30分钟没有互动后结束一次会话，实际以GA4设置为准。',
 activeUsers:'在所选期间内达到GA4活跃条件的去重用户数；同一人在不同分组出现时，分组人数不能直接相加。',
 newUsers:'GA4首次记录到访问的用户数；不是后台首次付款的新客户。',
 engagedSessions:'达到参与条件的访问次数：超过设定时长（默认10秒）、触发关键事件，或浏览至少2个页面/屏幕，满足任一即可。',
 engagementRate:'参与会话数 ÷ 全部会话数；表示有较明显互动的访问占比。',
 screenPageViews:'页面或屏幕被查看的总次数；重复查看同一页面也计数。',
 averageSessionDuration:'每次访问平均持续多少秒；不是页面保持在前台的平均互动时长。',
 bounceRate:'未达到参与条件的会话占比，等于1减参与率；不是简单的“只看一页就离开”。',
 ecommercePurchases:'GA4记录的购买事件次数；埋点、重复上报和同意设置会影响结果，不等于后台订单数。',
 purchaseRevenue:'GA4根据购买事件记录的收入；受埋点和退款记录影响，仅作参考，不替代Admin经营销售额。',
 sessionSourceMedium:'这次访问从哪里来 / 通过什么方式来；来源是网站或平台，媒介是自然搜索、付费广告、引荐等。',
 deviceCategory:'访问时使用的设备类别，如电脑、手机、平板。',
 country:'访问所在地的国家或地区，通常根据网络位置判断；不代表国籍、收货地址或购买国家。',
 landingPage:'一次访问首先打开的页面路径；不是这次访问浏览的所有页面。',
 share:'该行会话数 ÷ 同范围GA4总会话数；不是人数占比，明细合计可能与独立汇总不同。',
 query:'用户在Google搜索时输入的词；受隐私保护影响，部分搜索词不会显示。',
 page:'在Google自然搜索中获得展示或点击的网站页面。',
 clicks:'点击次数：GSC为Google自然搜索结果点击，Ads为广告点击；不是去重用户数。',
 impressions:'展示次数：GSC为自然搜索结果被展示，Ads为广告被展示。',
 ctr:'点击率 = 点击次数 ÷ 展示次数；说明看到结果或广告后，有多少比例发生点击。',
 position:'Google自然搜索中网站最高位置的平均排名；数字越小通常排名越靠前，以GSC原值为准。',
 cost:'Google Ads记录的广告花费，单位美元；不是商品采购成本。',
 cpc:'平均每次广告点击花费 = 广告花费 ÷ 点击次数；没有点击时不可计算。',
 conversions:'Google Ads按账号转化设置和归因模型分配的转化次数，可为小数；不一定是订单。',
 cpa:'每次广告归因转化的平均花费 = 广告花费 ÷ 归因转化次数；没有转化时不可计算。',
 conversionsValue:'Google Ads为转化分配的价值，单位美元；不是Admin后台实收销售额。',
 platformRoas:'广告归因价值 ÷ 广告花费；例如2倍表示每花1美元对应2美元归因价值，不代表利润。',
 impressionShare:'此意图类别展示数 ÷ 同国GSC总展示数；不是Google Ads可获展示份额。',
 campaignId:'Google Ads广告系列的唯一编号。',customerId:'Google Ads广告账号的唯一编号；不同编号分别核算。',campaignName:'Google Ads中设置的广告系列名称。',
 currency:'广告账号记录的币种；美元指标按该账号原值展示，不混算不同币种。',timezone:'该广告账号统计数据采用的时区；可能与北京时间不同。',
 date:'这行数据对应的日期；按该来源自己的时区统计。',label:'该行对应的数据来源、广告账号或意图分类。',latestDate:'来源最近返回有效数据的日期；不是页面打开时间。',
 name:'后台原始折扣码或优惠券名称；名称本身不能证明推广归属。',site:'后台记录的适用网站；此处只展示明确属于MMOEXP主站的记录。',game:'后台配置的适用游戏；未提供时显示缺失。',uses:'后台累计使用次数，不是所选Google日期内的次数。',claimed:'后台累计领取次数，不等于去重领取人数。',usedAt:'后台记录的这次用券时间；当前列表没有按Google日期区间完整筛选。',batch:'后台记录的发券批次号，用于识别同一批活动。',repeatOrders90d:'后台提供的90天复购次数原值；不按当前日期区间重新计算。',
};
const sourceNames={google:'Google',bing:'必应',duckduckgo:'DuckDuckGo搜索',yahoo:'雅虎',baidu:'百度',yandex:'Yandex搜索','(direct)':'直接访问','accounts.google.com':'Google账号网站','youtube.com':'YouTube','ea.com':'EA网站','chatgpt.com':'ChatGPT','cardpay.com':'CardPay网站','js.klarna.com':'Klarna网站','search.brave.com':'Brave搜索网站','pale.tools':'Pale Tools网站'};
const mediumNames={organic:'自然搜索',cpc:'按点击付费广告',ppc:'按点击付费广告',referral:'网站引荐',email:'电子邮件',social:'社交流量','paid-social':'付费社交广告',display:'展示广告',affiliate:'联盟推广','ai-assistant':'AI助手引荐','(none)':'无媒介标记','(not set)':'未设置','(data not available)':'数据不可用'};
const regionEnglish=new Intl.DisplayNames(['en'],{type:'region',fallback:'code'}),regionChinese=new Intl.DisplayNames(['zh-Hans'],{type:'region',fallback:'code'});
const countryCodes=new Map();
for(let a=65;a<=90;a++)for(let b=65;b<=90;b++){const code=String.fromCharCode(a,b),name=regionEnglish.of(code);if(name!==code){countryCodes.set(name.toLowerCase(),code);countryCodes.set(code.toLowerCase(),code);}}
for(const [name,code] of Object.entries({'united states of america':'US','south korea':'KR','north korea':'KP','czech republic':'CZ','russian federation':'RU','turkey':'TR','vietnam':'VN','laos':'LA','palestine':'PS','hong kong':'HK','macau':'MO','taiwan':'TW'}))countryCodes.set(name,code);
for(const [name,code] of Object.entries({"": "001", "abw": "AW", "afg": "AF", "ago": "AO", "aia": "AI", "ala": "AX", "alb": "AL", "and": "AD", "are": "AE", "arg": "AR", "arm": "AM", "asm": "AS", "atg": "AG", "aus": "AU", "aut": "AT", "aze": "AZ", "bdi": "BI", "bel": "BE", "ben": "BJ", "bes": "BQ", "bfa": "BF", "bgd": "BD", "bgr": "BG", "bhr": "BH", "bhs": "BS", "bih": "BA", "blm": "BL", "blr": "BY", "blz": "BZ", "bmu": "BM", "bol": "BO", "bra": "BR", "brb": "BB", "brn": "BN", "btn": "BT", "bwa": "BW", "caf": "CF", "can": "CA", "cck": "CC", "che": "CH", "chl": "CL", "chn": "CN", "civ": "CI", "cmr": "CM", "cod": "CD", "cog": "CG", "cok": "CK", "col": "CO", "com": "KM", "cpv": "CV", "cri": "CR", "cub": "CU", "cuw": "CW", "cxr": "CX", "cym": "KY", "cyp": "CY", "cze": "CZ", "deu": "DE", "dji": "DJ", "dma": "DM", "dnk": "DK", "dom": "DO", "dza": "DZ", "ecu": "EC", "egy": "EG", "eri": "ER", "esp": "ES", "est": "EE", "eth": "ET", "fin": "FI", "fji": "FJ", "flk": "FK", "fra": "FR", "fro": "FO", "fsm": "FM", "gab": "GA", "gbr": "GB", "geo": "GE", "ggy": "GG", "gha": "GH", "gib": "GI", "gin": "GN", "glp": "GP", "gmb": "GM", "gnb": "GW", "gnq": "GQ", "grc": "GR", "grd": "GD", "grl": "GL", "gtm": "GT", "guf": "GF", "gum": "GU", "guy": "GY", "hkg": "HK", "hnd": "HN", "hrv": "HR", "hti": "HT", "hun": "HU", "idn": "ID", "imn": "IM", "ind": "IN", "iot": "IO", "irl": "IE", "irn": "IR", "irq": "IQ", "isl": "IS", "isr": "IL", "ita": "IT", "jam": "JM", "jey": "JE", "jor": "JO", "jpn": "JP", "kaz": "KZ", "ken": "KE", "kgz": "KG", "khm": "KH", "kir": "KI", "kna": "KN", "kor": "KR", "kwt": "KW", "lao": "LA", "lbn": "LB", "lbr": "LR", "lby": "LY", "lca": "LC", "lie": "LI", "lka": "LK", "lso": "LS", "ltu": "LT", "lux": "LU", "lva": "LV", "mac": "MO", "maf": "MF", "mar": "MA", "mco": "MC", "mda": "MD", "mdg": "MG", "mdv": "MV", "mex": "MX", "mhl": "MH", "mkd": "MK", "mli": "ML", "mlt": "MT", "mmr": "MM", "mne": "ME", "mng": "MN", "mnp": "MP", "moz": "MZ", "mrt": "MR", "msr": "MS", "mtq": "MQ", "mus": "MU", "mwi": "MW", "mys": "MY", "myt": "YT", "nam": "NA", "ncl": "NC", "ner": "NE", "nfk": "NF", "nga": "NG", "nic": "NI", "niu": "NU", "nld": "NL", "nor": "NO", "npl": "NP", "nru": "NR", "nzl": "NZ", "omn": "OM", "pak": "PK", "pan": "PA", "pcn": "PN", "per": "PE", "phl": "PH", "plw": "PW", "png": "PG", "pol": "PL", "pri": "PR", "prk": "KP", "prt": "PT", "pry": "PY", "pse": "PS", "pyf": "PF", "qat": "QA", "reu": "RE", "rou": "RO", "rus": "RU", "rwa": "RW", "sau": "SA", "sdn": "SD", "sen": "SN", "sgp": "SG", "shn": "SH", "sjm": "SJ", "slb": "SB", "sle": "SL", "slv": "SV", "smr": "SM", "som": "SO", "spm": "PM", "srb": "RS", "ssd": "SS", "stp": "ST", "sur": "SR", "svk": "SK", "svn": "SI", "swe": "SE", "swz": "SZ", "sxm": "SX", "syc": "SC", "syr": "SY", "tca": "TC", "tcd": "TD", "tgo": "TG", "tha": "TH", "tjk": "TJ", "tkl": "TK", "tkm": "TM", "tls": "TL", "ton": "TO", "tto": "TT", "tun": "TN", "tur": "TR", "tuv": "TV", "twn": "TW", "tza": "TZ", "uga": "UG", "ukr": "UA", "umi": "UM", "ury": "UY", "usa": "US", "uzb": "UZ", "vat": "VA", "vct": "VC", "ven": "VE", "vgb": "VG", "vir": "VI", "vnm": "VN", "vut": "VU", "wlf": "WF", "wsm": "WS", "yem": "YE", "zaf": "ZA", "zmb": "ZM", "zwe": "ZW"}))countryCodes.set(name,code);
function translatedDimension(dim,value){
 const original=value==null||value===''?'未知':String(value),key=original.toLowerCase();
 if(['(not set)','(other)','(data not available)','unknown','未知'].includes(key))return original+'（'+({'(not set)':'未设置：来源没有提供此信息','(other)':'其他汇总项','(data not available)':'数据不可用',unknown:'未知',未知:'未知'}[key])+'）';
 if(dim==='sessionSourceMedium'){
  const parts=original.split(/\s+\/\s+/),source=parts[0],medium=parts.slice(1).join(' / ');
  if(!medium)return original+'（来源或媒介未完整提供）';
  return original+'（'+(sourceNames[source.toLowerCase()]||'来源：'+source)+' / '+(mediumNames[medium.toLowerCase()]||'自定义媒介：'+medium)+'）';
 }
 if(dim==='country'){const code=countryCodes.get(key);return original+'（'+(code?regionChinese.of(code):'国家或地区名称待确认')+'）';}
 if(dim==='deviceCategory')return original+'（'+({desktop:'电脑',mobile:'手机',tablet:'平板',smarttv:'智能电视'}[key]||'其他设备类别')+'）';
 return original;
}

const categoryNames={brand:'品牌',transaction:'交易品类',content:'内容资讯',other:'其他'};
const rates=new Set(['nativeCvr','ctr','bounceRate','engagementRate','share','impressionShare']);
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined&&text!==null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function fmt(key,value){if(value===undefined||value===null||!Number.isFinite(Number(value)))return '—';const v=Number(value);if(rates.has(key))return (v*100).toFixed(2)+'%';if(key==='platformRoas')return v.toFixed(2)+'×';if(key==='averageSessionDuration')return v.toFixed(1)+' 秒';return new Intl.NumberFormat('zh-CN',{maximumFractionDigits:key==='position'?2:key==='conversions'?3:2}).format(v);}
function help(label,text){
 const button=el('button','?','help-icon');button.type='button';button.setAttribute('aria-label',label+'：查看说明');
 const tip=el('span',text,'help-tooltip');tip.id='field-tip-'+(++scope.tipId);tip.setAttribute('role','tooltip');tip.hidden=true;button.setAttribute('aria-describedby',tip.id);
 const hide=()=>{tip.hidden=true;tip.remove();};
 const show=()=>{scope.root.querySelectorAll('.help-tooltip').forEach(n=>n.remove());scope.root.append(tip);tip.hidden=false;const r=button.getBoundingClientRect(),box=tip.getBoundingClientRect();tip.style.left=Math.max(8,Math.min(r.left,innerWidth-box.width-8))+'px';tip.style.top=(r.bottom+box.height+8<innerHeight?r.bottom+8:Math.max(8,r.top-box.height-8))+'px';};
 button.addEventListener('mouseenter',show);button.addEventListener('mouseleave',hide);button.addEventListener('focus',show);button.addEventListener('blur',hide);button.addEventListener('click',show);button.addEventListener('keydown',event=>{if(event.key==='Escape')hide();});return button;
}
function field(label,text){const name=el('span',label,'field-label');if(text)name.append(help(label,text));return name;}
function table(columns,rows){const wrap=el('div',null,'table-scroll'),t=el('table'),h=el('thead'),hr=el('tr');for(const c of columns){const th=el('th');th.scope='col';th.append(field(c.label||labels[c.key]||c.key,explanations[c.key]));hr.append(th);}h.append(hr);t.append(h);const b=el('tbody');for(const row of rows){const r=el('tr');for(const c of columns){const value=c.get?c.get(row):row[c.key];const td=el('td',c.numeric?fmt(c.key,value):value===undefined||value===null?'—':value);if(!c.numeric){td.textContent=translatedDimension(c.key,value);td.title=String(value??'');}r.append(td);}b.append(r);}if(!rows.length){const r=el('tr'),d=el('td','未返回可用明细；不按零处理。','empty');d.colSpan=columns.length;r.append(d);b.append(r);}t.append(b);wrap.append(t);wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','可横向滚动的数据表');return wrap;}
const metricCol=key=>({key,numeric:true,get:r=>r.metrics?.[key]});
function section(title,subtitle){const n=el('section',null,'report-section');n.append(el('h2',title));if(subtitle)n.append(el('p',subtitle,'section-meta'));return n;}
function changeText(change){if(!change)return '';const v=Number(change.value);return '较前周 '+(v>0?'+':'')+v.toFixed(2)+(change.kind==='percentage_points'?' 个百分点':'%');}
function cards(keys,values,changes){const grid=el('div',null,'kpi-grid');for(const key of keys){const item=el('article',null,'kpi');item.dataset.metric=key;item.append(field(labels[key],explanations[key]),el('strong',fmt(key,values?.[key])));if(changes?.[key])item.append(el('small',changeText(changes[key]),'change'));grid.append(item);}return grid;}
function bars(rows,dimension,metric,max=10){const box=el('div',null,'bar-chart');const list=rows.slice(0,max);const biggest=Math.max(...list.map(v=>Number(v.metrics?.[metric])||0),1);for(const row of list){const label=typeof dimension==='function'?dimension(row):row.dimensions?.[dimension]||row[dimension]||'未知';const item=el('div',null,'bar-row'),name=el('span',typeof dimension==='string'?translatedDimension(dimension,label):label,'bar-label');name.title=label;const track=el('div',null,'bar-track'),bar=el('i');bar.style.width=Math.max(0,(Number(row.metrics?.[metric])||0)/biggest*100)+'%';track.append(bar);item.append(name,track,el('b',fmt(metric,row.metrics?.[metric])));box.append(item);}if(!list.length)box.append(el('p','暂无可用数据。','empty'));return box;}
function line(rows,metric,period){const box=el('div',null,'line-chart');const heading=el('h3');heading.append(field(labels[metric]+' · 逐日',explanations[metric]));box.append(heading);const points=rows.filter(r=>r.dimensions?.date&&r.metrics?.[metric]!==undefined).sort((a,b)=>a.dimensions.date.localeCompare(b.dimensions.date));if(!points.length){box.append(el('p','暂无逐日数据。'));return box;}const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 620 205');svg.setAttribute('role','img');svg.setAttribute('aria-label',labels[metric]+'逐日趋势，缺失日期没有填零');const max=Math.max(...points.map(p=>Number(p.metrics[metric])),1),start=Date.parse(period.start+'T00:00:00Z');const xy=p=>[48+((Date.parse(p.dimensions.date+'T00:00:00Z')-start)/86400000)/Math.max(1,(Date.parse(period.end+'T00:00:00Z')-start)/86400000)*552,155-Number(p.metrics[metric])/max*120];let previous=null;for(const p of points){const [x,y]=xy(p);if(previous&&Date.parse(p.dimensions.date)-Date.parse(previous.dimensions.date)===86400000){const q=xy(previous),s=document.createElementNS(ns,'line');for(const [k,v] of Object.entries({x1:q[0],y1:q[1],x2:x,y2:y,stroke:'#13846d','stroke-width':3}))s.setAttribute(k,String(v));svg.append(s);}const c=document.createElementNS(ns,'circle');c.setAttribute('cx',x);c.setAttribute('cy',y);c.setAttribute('r',4);c.setAttribute('fill','#13846d');const title=document.createElementNS(ns,'title');title.textContent=p.dimensions.date+' '+fmt(metric,p.metrics[metric]);c.append(title);svg.append(c);const text=document.createElementNS(ns,'text');text.setAttribute('x',x);text.setAttribute('y',180);text.setAttribute('text-anchor','middle');text.textContent=p.dimensions.date.slice(5);svg.append(text);previous=p;}for(const [y,value] of [[35,max],[155,0]]){const text=document.createElementNS(ns,'text');text.setAttribute('x',0);text.setAttribute('y',y);text.textContent=fmt(metric,value);svg.append(text);}box.append(svg);return box;}
function statusNote(s){const c=s.coverage||{};let text='来源时区 '+s.timezone+' · 请求 '+c.requested_start+' — '+c.requested_end+' · 实际返回 '+c.returned_days+'/'+c.requested_days+' 天 · 最新返回日期 '+(c.latest_data_date||'—');if(c.query_range_complete!==undefined){text='来源时区 '+s.timezone+' · 查询范围 '+c.requested_start+' — '+c.requested_end+' · 查询/分页'+(c.query_range_complete?'完整':'尚不完整')+' · 返回有指标行 '+c.returned_days+'/'+c.requested_days+' 天 · 最近有指标日期 '+(c.latest_data_date||'—');if(c.no_metric_row_dates?.length)text+=' · 日期未返回指标行 '+c.no_metric_row_dates.join('、')+'；API按日期分段会省略所有选定指标均为零的行，未补零记录，不能当作采集失败。';}else if(c.missing_dates?.length)text+=' · 缺少 '+c.missing_dates.join('、');const q=s.status?.quality||{};if(q.subject_to_thresholding)text+=' · 受隐私阈值影响';if(q.sampling_present)text+=' · 存在采样';if(q.data_loss_from_other_row)text+=' · 高基数Other行数据损失';if(q.active_metric_restrictions?.length)text+=' · 部分指标权限受限';const n=el('p',text,'watermark');n.dataset.nativeSummary='来源时区 '+s.timezone+' · 覆盖 '+c.returned_days+'/'+c.requested_days+' 天 · 数据至 '+(c.latest_data_date||'—')+(c.query_range_complete===false?' · 查询尚不完整':'')+(q.subject_to_thresholding?' · 隐私阈值影响':'')+(q.sampling_present?' · 存在采样':'')+(q.data_loss_from_other_row?' · Other行损失':'')+(q.active_metric_restrictions?.length?' · 指标权限受限':'')+(s.status?.retained_previous?' · 请求失败，保留旧报告':'');if(s.status?.retained_previous)n.append(el('strong',' 最近请求未成功，保留上次有效报告。'));if(s.status?.collected_at)n.append(el('span',' · 采集 '+s.status.collected_at));return n;}
function coverageNote(t,query=false){let text='返回维度 '+t.returned_dimension_rows+' 行 · 当前展示 '+t.displayed_rows+' 行 · 明细'+(t.coverage_metric==='sessions'?'会话':'点击')+'覆盖 '+fmt('share',t.row_coverage);if(t.coverage_basis==='byPage_total')text+=' · 分母为同口径byPage总点击，区别于站点byProperty总量';if(query)text+=' · 搜索词隐私/Top行限制可使明细少于总量；覆盖率不代表完整性';if(t.status?.quality?.pagination_capped)text+=' · 达到本次分页上限';if(t.status?.retained_previous)text+=' · 上次有效报告';return el('p',text,'coverage');}
function dimensionDisclosure(title,columns,rows,note){
 const hasRows=Array.isArray(rows),list=hasRows?rows:[],box=el('article',null,'breakdown');box.append(el('h3',title),el('p',hasRows?'当前返回 '+list.length+' 行 · 重点展示前 '+Math.min(3,list.length)+' 行':'此维度明细尚未提供','coverage'));
 if(note)box.append(note);if(!list.length){box.append(el('p',hasRows?'当前没有可展示明细；来源限制与指标总量分别保留。':'未取得该维度，未按零处理。','coverage'));return box;}box.append(table(columns,list.slice(0,3)));const detail=el('details',null,'source-details');detail.append(el('summary','展开当前返回明细 · '+list.length+' 行'),table(columns,list));box.append(detail);return box;
}
function trendDisclosure(source,metric,period){
 const rows=(source.daily||[]).filter(r=>r.metrics?.[metric]!=null),last=[...rows].sort((a,b)=>String(a.dimensions?.date).localeCompare(String(b.dimensions?.date))).at(-1),wrap=el('article',null,'breakdown');
 wrap.append(el('h3',labels[metric]+'趋势'),el('p','返回 '+rows.length+' 个日指标点 · 最近 '+(last?.dimensions?.date||'未提供')+'：'+fmt(metric,last?.metrics?.[metric])+' · '+(changeText(source.changes?.[metric])||'无可用同范围对比'),'coverage'));
 const detail=el('details',null,'source-details');detail.append(el('summary','展开逐日趋势'),line(source.daily||[],metric,period));wrap.append(detail);return wrap;
}
function renderGA(parent,s,period){
 const block=section('GA4 · 全站行为总览','GA4原生全站范围，游戏选择不改变或重新命名这组总数。');block.append(statusNote(s),cards(['sessions','activeUsers','engagedSessions','engagementRate'],s.metrics,s.changes),trendDisclosure(s,'sessions',period));
 const extra=el('details',null,'source-details');extra.append(el('summary','补充原生指标 · 新用户、页面浏览与购买埋点'),cards(['newUsers','screenPageViews','averageSessionDuration','bounceRate','ecommercePurchases','purchaseRevenue'],s.metrics,s.changes),el('p','GA4购买事件及收入只作埋点参考，不替代Admin订单或财务销售额。','financial-note'));block.append(extra);
 for(const [name,title,dim]of [['source_medium','来源 / 媒介','sessionSourceMedium'],['device','设备','deviceCategory'],['country','国家','country'],['landing_page','落地页','landingPage']]){const t=s.breakdowns?.[name]||{};block.append(dimensionDisclosure(title,[{key:dim,label:title,get:r=>r.dimensions?.[dim]},...['sessions','activeUsers','bounceRate','share'].map(metricCol)],t.rows,coverageNote(t)));}parent.append(block);
}
function renderGSC(parent,s,period){
 const block=section('GSC · 全站自然搜索总览','来源原生全站指标；游戏内容匹配独立展示，不改写为游戏全部搜索流量。');block.append(statusNote(s),cards(['impressions','clicks','ctr','position'],s.metrics,s.changes),trendDisclosure(s,'clicks',period));
 for(const [name,title,dim]of [['query','搜索词','query'],['page','搜索页面','page'],['country','搜索国家','country']]){const t=s.breakdowns?.[name]||{};block.append(dimensionDisclosure(title,[{key:dim,label:title,get:r=>r.dimensions?.[dim]},...['clicks','impressions','ctr','position'].map(metricCol)],t.rows,coverageNote(t,true)));}
 const markets=el('details',null,'source-details'),available=(s.markets||[]).filter(m=>m.available);markets.append(el('summary','市场 × 搜索意图 · '+available.length+'/'+(s.markets||[]).length+' 个市场可用'));
 for(const market of s.markets||[]){const box=el('article',null,'breakdown');box.append(el('h3',market.label));if(!market.available)box.append(el('p','当前未返回该市场记录，未按零解释。','coverage'));else{box.append(el('p','查询点击覆盖 '+fmt('share',market.query_row_coverage)+'；受隐私和Top限制。','coverage'));box.append(table([{key:'label',label:'意图类别'},...['impressions','clicks','impressionShare','ctr','position'].map(metricCol)],market.categories.map(v=>({label:categoryNames[v.category],metrics:v.metrics}))),dimensionDisclosure('搜索词',[{key:'query',label:'搜索词',get:r=>r.dimensions.query},...['clicks','impressions','ctr','position'].map(metricCol)],market.top_queries));}markets.append(box);}
 const rule=el('details');rule.append(el('summary','查看分类规则 '+(period.query_rules?.version||'未提供')),el('pre',JSON.stringify(period.query_rules||{},null,2)));markets.append(rule);block.append(markets);parent.append(block);
}
function renderAds(parent,accounts,brand,period){
 const block=section('Google Ads · '+(brand==='rsorder'?'RSOrder':'MMOEXP')+'全局投放','各账号原生花费与归因指标独立，广告组不再次加入系列或账号总额。');
 block.append(table([{key:'label',label:'账号'},{key:'customerId'},...['cost','clicks','conversions','conversionsValue','platformRoas'].map(metricCol)],accounts));
 for(const a of accounts){const box=el('article',null,'breakdown');box.dataset.customer=a.customerId;box.append(el('h3',a.label),cards(['cost','clicks','conversions','platformRoas'],a.metrics,a.changes));const audit=el('details',null,'source-details');audit.append(el('summary','账号来源与逐日数据 · '+(a.daily||[]).length+' 行'),statusNote(a),el('p',(a.currency||'币种未提供')+' · '+(a.timezone||'时区未提供'),'coverage'),table([{key:'date',get:r=>r.dimensions.date},...['impressions','clicks','conversions','conversionsValue'].map(metricCol),{key:'cost',numeric:true,get:r=>Number(r.metrics.costMicros)/1000000}],a.daily||[]));box.append(audit);block.append(box);}
 const campaigns=accounts.flatMap(a=>a.calculation_campaigns||a.campaigns||[]).sort((a,b)=>Number(b.metrics.cost)-Number(a.metrics.cost));block.append(dimensionDisclosure('广告系列',[{key:'campaignName'},{key:'customerId'},{key:'campaignId'},...['cost','clicks','conversions','platformRoas'].map(metricCol)],campaigns,el('p',period.start+' — '+period.end+' · '+(currentTrafficPeriod(period)&&accounts.length>0&&accounts.every(a=>a.campaign_calculation_complete===true)?'计算使用来源完整返回集合，展示前3行不限制统计。':'当前仅已返回系列；旧缓存或不完整集合不能证明全量，需按当前规则核实。')+'币种/时区按账号。','coverage')));
 for(const a of accounts){block.append(el('p',a.customerId+' · 系列返回 '+a.campaign_count+' 行 · 花费覆盖 '+fmt('share',a.campaign_row_cost_coverage)+(a.campaign_calculation_complete?' · 本次查询完整':' · 完整性未核实'),'coverage'));block.append(dimensionDisclosure(a.label+'广告组',[{key:'campaignName'},{key:'adGroupName',label:'广告组'},{key:'adGroupStatus',label:'状态'},...['cost','clicks','conversions','platformRoas'].map(metricCol)],a.ad_groups?.rows||[],el('p',(a.ad_groups?.calculation_complete?'本次广告组查询完整。':'广告组尚未完整取得，不以缺失代表零投放。')+'PMax不适用ad_group；未混入asset_group。','coverage')));}parent.append(block);
}

function renderBusinessLinks(parent,value){
 const block=section('经营关联 · MMOEXP主站','Admin会员统计、折扣码与优惠券；与Google流量分别统计，原始日期与范围单独列明。');
 block.dataset.businessLinks='true';parent.querySelector('[data-business-links]')?.remove();
 if(!value||value.status==='unavailable'){block.append(el('p','经营关联尚未读取，请在上方选择日期并应用区间。','coverage'));parent.append(block);return;}
 const member=value.membership;block.append(el('h3','会员统计'));
 if(member?.status==='available'){
  block.append(el('p',member.start+' — '+member.end+' · '+member.site+' · 注册与支付按同一期间统计 · Asia/Shanghai','coverage'));
  const grid=el('div',null,'kpi-grid');for(const m of member.metrics){const card=el('article',null,'kpi');card.dataset.metric=m.field;card.append(field(m.label+(m.unit==='USD'?' · USD':''),m.explanation),el('strong',fmt(m.field,m.value)));grid.append(card);}block.append(grid);
 }else block.append(el('p','会员统计本次未取得，未填零。','coverage'));
 for(const [key,title] of [['discount','最近折扣码配置'],['coupon','最近优惠券配置'],['usage','最近用券记录']]){
  const part=value[key];
  if(!part||part.status==='unavailable'){block.append(el('h3',title),el('p','本次未取得，未填零。','coverage'));continue;}
  const note=el('p',part.basis+' · 返回主站 '+part.returnedMainSiteRows+' 条 / 本页 '+part.returnedRows+' 条；后台全部站点总项数 '+fmt('',part.totalAllSites),'coverage');
  const columns=[{key:'name',label:key==='discount'?'折扣码':'优惠券名称'},{key:'site',label:'适用站点'}];
  if(key==='usage')columns.push({key:'usedAt',label:'使用时间'},{key:'batch',label:'活动批次'},{key:'repeatOrders90d',label:'后台90天复购次数',numeric:true});
  else {columns.push({key:'game',label:'适用游戏'},{key:'uses',label:'累计使用次数',numeric:true});if(key==='coupon')columns.push({key:'claimed',label:'累计领取次数',numeric:true});}
  block.append(dimensionDisclosure(title,columns,part.rows,note));
 }
 block.append(el('p','当前未接入创作者名单、佣金或GA4用户与订单的逐人关联，不能据折扣码名称推断KOL归属或计算跨源转化率。','coverage'));parent.append(block);
}
async function loadBusinessLinks(parent,period,value){
 const key=period.start+'_'+period.end;scope.businessLinksCache??=new Map();
 const cached=scope.businessLinksCache.get(key);
 if(value?.membership?.start===period.start&&value.membership.end===period.end){renderBusinessLinks(parent,value);return;}
 if(cached&&Date.now()-cached.at<300000){renderBusinessLinks(parent,cached.value);return;}
 renderBusinessLinks(parent,null);
 try{
  const url='/dashboard/marketing/business-links.json?'+new URLSearchParams({start:period.start,end:period.end});
  for(let n=0;n<20;n++){
   const r=await fetch(url,{cache:'no-store',credentials:'same-origin'});
   if(r.status===202||r.status===429){await new Promise(resolve=>setTimeout(resolve,5000));continue;}
   if(!r.ok)throw Error('links_unavailable');const links=await r.json();
   if(links.start!==period.start||links.end!==period.end)throw Error('links_range_mismatch');
   scope.businessLinksCache.set(key,{at:Date.now(),value:links});if(parent.isConnected)renderBusinessLinks(parent,links);return;
  }
 }catch{}
 if(parent.isConnected)renderBusinessLinks(parent,{status:'unavailable'});
}

function selectedAccounts(period,game='FC27'){
 return period.adsAccounts.filter(a=>a.brand==='mmoexp').map(a=>{
  const all=a.calculation_campaigns||a.campaigns||[],rows=all.filter(r=>(r.campaign_scope==='project'&&r.game_target===game||game==='D4'&&r.campaign_scope==='game_name_candidate'&&r.game_target===game)),global=all.filter(r=>r.campaign_scope==='global_brand');
  const complete=(game==='FC27'||all.some(r=>r.game_target===game)||(period.game_profiles||[]).some(p=>(typeof p==='string'?p:p.code)===game))&&a.campaign_calculation_complete===true&&a.campaign_count===all.length&&a.metrics?.cost!==null&&a.metrics?.cost!==undefined&&all.every(r=>r.metrics?.cost!==null&&r.metrics?.cost!==undefined)&&Math.abs(all.reduce((sum,r)=>sum+Number(r.metrics.cost),0)-Number(a.metrics.cost))<0.00000001;
  const metrics={};for(const key of ['cost','clicks','impressions','conversions','conversionsValue','interactions'])metrics[key]=rows.length&&rows.every(r=>r.metrics?.[key]!==null&&r.metrics?.[key]!==undefined)?rows.reduce((sum,r)=>sum+Number(r.metrics[key]),0):!rows.length&&complete?0:null;
  metrics.platformRoas=metrics.cost>0&&metrics.conversionsValue!==null?metrics.conversionsValue/metrics.cost:null;metrics.nativeCvr=rows.length===1?rows[0].metrics.nativeCvr:null;
  return {...a,metrics,campaigns:rows,calculation_campaigns:rows,global_brand:global,unverified_brand:all.filter(r=>r.campaign_scope==='brand_scope_unverified'&&r.game_candidate===game),selection_complete:complete};
 });
}
function renderGameAds(parent,period,game){
 const selectedGame=(scope.esProfiles||[]).find(p=>p.code===game)?.label||{FC27:'FC27',D4:'Diablo IV',AION2:'Aion2'}[game]||game;
 const content=section(game==='FC27'?'FC27 / Coins关键词线索':selectedGame+' · 搜索与访问范围',game==='FC27'?'可能包含泛Coins词；按已确认名称规则筛选，不代表纯FC访问或订单归因。GA4/GSC总盘仍为全站背景。':'该游戏的GA4/GSC过滤指标尚未提供；全站背景见下方展开区。');if(game==='FC27')for(const [key,title]of [['query','FC27 / Coins搜索词'],['page','FC27 / Coins搜索页面']]){const t=period.sources?.gsc?.breakdowns?.[key]?.fc27_content;const available=Array.isArray(t?.rows),status=t?.status?.status;const note=!t?'该游戏内容维度尚未提供。':!available?(status==='not_collected'?'该维度本次未取得，未按空记录或零解释。':'旧缓存未提供匹配明细；可通过原区间更新入口读取，未按空记录解释。'):(status==='failed'||status==='empty'?'来源本次读取失败，以下为上次成功返回的匹配记录。':'')+'当前返回匹配 '+t.returned_matching_rows+' 行 · 展示已返回匹配中的 Top20（'+t.rows.length+' 行）'+(t.display_truncated?' · 其余 '+t.omitted_rows+' 行未展示':'')+'；汇总使用全部已返回匹配，仍受隐私及来源Top范围限制。';content.append(cards(['clicks','impressions'],t?.metrics),dimensionDisclosure(title,[{key,label:key==='query'?'搜索词':'页面',get:r=>r.dimensions[key]},...['clicks','impressions','ctr','position'].map(metricCol)],t?.rows,el('p',note,'coverage')));}else content.append(el('p','该游戏的GA4/GSC过滤指标尚未提供；全站背景见下方展开区。','coverage'));parent.append(content);
 const accounts=selectedAccounts(period,game),block=section('Google Ads · '+(game==='D4'?'D4名称线索':selectedGame+'专属投放'),game==='D4'?'仅按系列名称前缀筛选，不代表已核实的游戏归属；待核品牌单列，不计入名称小计。':'按已确认投放归属计算；页面Top展示不限制计算全量。全局品牌费用与转化价值单列。');
 for(const account of accounts){block.append(el('h3',account.label),cards(['cost','interactions','conversions','nativeCvr','platformRoas'],account.metrics),el('p',account.selection_complete?'本期计算系列完整；Ads指标按平台归因。':'仅已返回系列小计，旧Top数据不能证明'+selectedGame+'全量或零投放。','coverage'),dimensionDisclosure(selectedGame+'投放系列',[{key:'campaignName'},...['cost','interactions','conversions','nativeCvr','platformRoas'].map(metricCol)],account.campaigns));
  if(game==='D4')block.append(el('h3','D4品牌归属待核'),el('p','仅名称含D4线索；未并入上方名称小计，也不向游戏分摊。','coverage'),dimensionDisclosure('D4待核品牌系列',[{key:'campaignName'},metricCol('cost')],account.unverified_brand));
  block.append(el('h3','主站全局品牌投放'),el('p','google-FC27-PMAX-Coins-US费用保留全局；关联FC成交需以Admin实际游戏字段读取，无分摊方法时不生成FC分摊ROAS。','coverage'),dimensionDisclosure('全局品牌系列',[{key:'campaignName'},...['cost','interactions','conversions','nativeCvr','platformRoas'].map(metricCol)],account.global_brand));
  for(const [title,rows]of [[selectedGame+'广告组',(account.ad_groups?.rows||[]).filter(r=>(r.campaign_scope==='project'&&r.game_target===game||game==='D4'&&r.campaign_scope==='game_name_candidate'&&r.game_target===game))],...(game==='D4'?[['D4品牌归属待核广告组',(account.ad_groups?.rows||[]).filter(r=>r.campaign_scope==='brand_scope_unverified'&&r.game_candidate==='D4')]]:[]),['全局品牌广告组',(account.ad_groups?.rows||[]).filter(r=>r.campaign_scope==='global_brand')]]){const detail=el('details',null,'source-details');detail.append(el('summary',title+' · '+rows.length+' 行'),el('p',(account.ad_groups?.calculation_complete?'本期返回完整查询范围。':'广告组缺失、部分或读取失败，不能按零投放解释。')+'仅作只读细分，不加入系列/账号总额。PMax不适用ad_group，未混入asset_group。','coverage'),table([{key:'campaignName'},{key:'adGroupName',label:'广告组'},{key:'adGroupId',label:'Ad Group ID'},{key:'adGroupStatus',label:'状态'},...['cost','clicks','conversions','nativeCvr','platformRoas'].map(metricCol)],rows));block.append(detail);}
 }parent.append(block);
}
function nativeFields(value,period){
 const valid=v=>(typeof v==='number'||typeof v==='string'&&v.trim()!=='')&&Number.isFinite(Number(v));
 const selected={};for(const system of ['order.p2pah.cn','admin.p2pah.cn'])for(const row of Object.values(value.profile||{})){
  if(!row||row.system!==system||row.status!=='available')continue;const source=value.sources?.[system.startsWith('admin')?'Admin':'Order'];if((row.stale??source?.stale)!==false)continue;const end=new Date(period.end+'T12:00:00Z');end.setUTCDate(end.getUTCDate()+1);if(row.period?.start!==period.start+' 00:00'||row.period?.end!==end.toISOString().slice(0,10)+' 00:00')continue;
  for(const [key,metric] of Object.entries(row.metrics||{}))if(metric?.status==='available'&&valid(metric.value))selected[key]=metric;
  for(const key of ['orders','revenueUsd'])if(valid(row[key])&&Number(row[key])>=0&&(key!=='orders'||Number.isSafeInteger(Number(row[key]))))selected[key]={value:row[key],source:system,scope:'后台原统计范围'};
  if(system==='admin.p2pah.cn'){const channels=row.dimensions?.channels||[],main=channels.filter(r=>(r.code||r.name)==='www.mmoexp.com');if(main.length===1)for(const key of ['orders','revenueUsd']){const v=main[0][key];if(valid(v)&&Number(v)>=0&&(key!=='orders'||Number.isSafeInteger(Number(v))))selected[key]={value:v,source:system,scope:'MMOEXP主站（Admin渠道www.mmoexp.com）'};}else if(!channels.length&&['orders','revenueUsd'].every(key=>row.metrics?.[key]?.value===0)){for(const key of ['orders','revenueUsd'])selected[key]={value:0,source:system,scope:'MMOEXP主站（Admin全零）'};}}
 }return selected;
}
async function businessResult(parent,period){
 const block=section('经营结果 · FC27','Admin原生订单统计优先，Order仅补缺；与GA4、GSC、Ads分源核对。');parent.prepend(block);const note=el('p','正在读取所选期间经营结果…','coverage');note.setAttribute('role','status');block.append(note);
 const query=new URLSearchParams({mode:'summary',profile:'FC27',start:period.start,end:period.end,grain:'day'});
 try{for(let n=0;n<24&&block.isConnected;n++){
  const response=await fetch('/dashboard/fs-home/range.json?'+query,{credentials:'same-origin',cache:'no-store'});if(!response.ok&&response.status!==202)throw Error('business_unavailable');const value=await response.json();
  if(!block.isConnected)return;
  if(['pending','running','reading'].includes(value.status)||value.status==='partial'&&!value.profile){note.textContent='经营数据准备中，已到达的营销数据仍可查看。';await new Promise(resolve=>setTimeout(resolve,3000));continue;}
  if(value.scopeContractId!=='admin-main-order-labelled-supplement-v1')throw Error('business_contract');
  const values=nativeFields(value,period),m={orders:values.orders?.value??null,revenueUsd:values.revenueUsd?.value??null};const rate=values.profitMarginPct?.value??null;
  m.averageOrderUsd=m.orders>0&&m.revenueUsd!==null?m.revenueUsd/m.orders:null;m.estimatedProfitUsd=m.revenueUsd!==null&&rate!==null?m.revenueUsd*rate/100:null;
  Object.assign(labels,{orders:'订单数',revenueUsd:'销售额 · USD',averageOrderUsd:'客单价 · USD',estimatedProfitUsd:'参考估算利润 · USD'});
  note.textContent=period.start+' — '+period.end+' · 参考利润率 '+(rate===null?'未提供':rate+'%')+'；估算非财务结算。金额范围：'+(values.revenueUsd?.scope||'来源原统计范围')+'；未明确主站时不声称已排除分销。';block.append(cards(['orders','revenueUsd','averageOrderUsd','estimatedProfitUsd'],m));return;
 }note.textContent='本期经营结果尚未就绪；未将缺失填0。';}catch{if(block.isConnected)note.textContent='本期经营结果不可用，营销数据保留；请在经营分析中核对来源。';}
}
function renderNativeOverview(parent,period,brand){
 const accounts=period.adsAccounts.filter(a=>a.brand===brand),allUSD=accounts.length>0&&accounts.every(a=>a.currency==='USD'),sum=key=>allUSD&&accounts.every(a=>a.metrics?.[key]!=null)?accounts.reduce((n,a)=>n+Number(a.metrics[key]),0):null;
 Object.assign(labels,{macroSessions:'GA4全站会话',macroUsers:'GA4全站活跃用户',macroSearchClicks:'GSC全站点击',macroSearchImpressions:'GSC全站展示',macroAdCost:'Ads账号花费 · USD',macroAdClicks:'Ads账号点击',macroConversions:'Ads归因转化',macroAdValue:'Ads归因价值 · USD'});
 const block=section('全局宏观 · 分来源原生总览','所选窗口按来源实际日期、时区与定义核对；游戏筛选只影响下方专属投放和订单结构。');block.classList.add('traffic-overview');for(const [name,source]of [['GA4',period.sources?.ga4],['GSC',period.sources?.gsc]]){const coverage=source?.coverage||{};block.append(el('p',name+' · '+(source?.metrics?(source.status?.retained_previous?'上次成功快照':'当前返回'):'未取得可用指标')+' · 来源时区 '+(source?.timezone||'未提供')+' · 最近有效日期 '+(coverage.latest_data_date||'未提供')+' · 返回日期 '+(coverage.returned_days??'未提供')+'/'+(coverage.requested_days??'未提供'),'coverage'));}block.append(cards(['macroSessions','macroUsers','macroSearchClicks','macroSearchImpressions','macroAdCost','macroAdClicks','macroConversions','macroAdValue'],{macroSessions:period.sources?.ga4?.metrics?.sessions,macroUsers:period.sources?.ga4?.metrics?.activeUsers,macroSearchClicks:period.sources?.gsc?.metrics?.clicks,macroSearchImpressions:period.sources?.gsc?.metrics?.impressions,macroAdCost:sum('cost'),macroAdClicks:sum('clicks'),macroConversions:sum('conversions'),macroAdValue:sum('conversionsValue')}));
 block.append(el('p','GA4会话 '+(changeText(period.sources?.ga4?.changes?.sessions)||'同范围对比未提供')+' · GSC点击 '+(changeText(period.sources?.gsc?.changes?.clicks)||'同范围对比未提供')+' · Ads '+accounts.length+' 个账号原生指标；不同币种未合计。','coverage'));
 const grouped=new Map();for(const a of accounts)for(const row of a.calculation_campaigns||a.campaigns||[]){const key=!currentTrafficPeriod(period)?'旧版缓存待更新':row.campaign_scope==='global_brand'?'全局品牌':row.campaign_scope==='brand_scope_unverified'?'品牌归属待核':row.campaign_scope==='game_name_candidate'?(row.game_candidate||'未知')+'名称线索':row.game_target||'未匹配投放';let bucket=grouped.get(key);if(!bucket){bucket={game:key,campaigns:0,metrics:{cost:0}};grouped.set(key,bucket);}bucket.campaigns++;bucket.metrics.cost=allUSD&&bucket.metrics.cost!==null&&row.metrics?.cost!=null?bucket.metrics.cost+Number(row.metrics.cost):null;}
 block.append(dimensionDisclosure('游戏投放结构摘要',[{key:'game',label:'投放归属 / 名称线索'},{key:'campaigns',label:'系列数',numeric:true},metricCol('cost')],[...grouped.values()].sort((a,b)=>(b.metrics.cost||0)-(a.metrics.cost||0)),el('p','按已返回广告归属汇总；不从广告名推定订单成交游戏，未匹配和全局品牌保留。','coverage')));parent.append(block);
}

function renderESStructure(parent,period){
 const generation=(scope.esGeneration||0)+1;scope.esGeneration=generation;scope.esAbort?.abort();clearTimeout(scope.esTimer);
 const profile=scope.trafficProject==='all'?'ALL':scope.trafficProject,global=profile==='ALL',block=section('ES订单结构 · '+(global?'全部游戏':((scope.esProfiles||[]).find(p=>p.code===profile)?.label||{FC27:'FC27',D4:'Diablo IV',AION2:'Aion2'}[profile]||profile)),'按Admin导出游戏字段聚合；站点、排分销和时区未核实。只有点击读取才请求该窗口，结构筛选不改变经营主盘。');block.id='es-order-structure';parent.append(block);
 const controls=el('div',null,'toolbar'),group=el('select'),status=el('select');group.setAttribute('aria-label','订单结构维度');status.setAttribute('aria-label','订单原状态');
 const dimensions=[...(global?[['game','游戏汇总']]:[]),['source_game','来源 × 游戏'],['product','产品类型'],['country','国家'],['payment','支付方式'],['new_customer','新客户标志订单'],['status','订单原状态']];
 for(const [value,label]of dimensions){const o=el('option',label);o.value=value;group.append(o);}group.value=dimensions.some(([v])=>v===scope.esGroup)?scope.esGroup:global?'game':'source_game';
 const all=el('option','全部原状态');all.value='all';status.append(all);status.value='all';
 for(const [label,select]of [['结构维度',group],['包含状态',status]]){const wrap=el('label',null,'scope-select');wrap.append(el('span',label),select);controls.append(wrap);}
 const button=el('button','读取所选窗口订单结构','fs-btn'),body=el('div');button.type='button';body.setAttribute('aria-live','polite');body.append(el('p','尚未读取此窗口的ES结构。可先查看上方流量总览，再按需要读取。','coverage'));controls.append(button);block.append(controls,body);
 let controller=null,deadline=0;const current=()=>generation===scope.esGeneration&&block.isConnected&&!scope.signal.aborted;
 const query=()=>({mode:'hermes',structure:'es',profile,start:period.start,end:period.end,group_by:group.value,...(status.value==='all'?{}:{status:status.value})});
 const cacheKey=()=>JSON.stringify(query());scope.esCache??=new Map();
 function show(data){
  body.replaceChildren(el('p',period.start+' — '+period.end+' · '+({available:'当前导出结构可用',partial:'部分可用，缺失不补零',pending:'正在准备',unavailable:'暂不可用'}[data.status]||'状态未识别'),'coverage'));
  const quality=data.quality||{};if(quality.retained_previous)body.append(el('p',quality.refresh_pending?'上次成功快照，刷新中。':'上次成功快照，刷新失败；保留原版本，可主动重试。','coverage'));
  if(!['available','partial'].includes(data.status)){body.append(el('p',data.status==='pending'?'原请求正在准备，按原查询检查，不重复提交导出。':'此窗口没有可用结构；未将缺失填零。','coverage'));return;}
  const t=data.structure_totals||{};Object.assign(labels,{esRecords:'导出记录',esOrders:'文件集合去重订单',esAmount:'订单金额 · USD',esPriced:'有价订单'});body.append(cards(['esRecords','esOrders','esAmount','esPriced'],{esRecords:t.records,esOrders:t.orders,esAmount:t.order_amount_usd,esPriced:t.priced_orders}));
  body.append(el('p','订单金额为导出结构金额，不是财务净营收或Admin主盘占比。'+(group.value==='new_customer'?'新客户标志按订单展示，不是去重人数或复购率。':''),'coverage'));
  const states=Object.keys(quality.status_composition||{});if(status.value==='all'){status.replaceChildren();for(const [value,label]of [['all','全部原状态'],...states.filter(v=>v!=='all').map(v=>[v,v])]){const o=el('option',label);o.value=value;status.append(o);}status.value='all';}
  body.append(dimensionDisclosure(global&&group.value==='game'?'导出游戏结构':'导出分组',[{key:'label',label:'分组'},{key:'records',label:'记录',numeric:true},{key:'orders',label:'去重订单',numeric:true},{key:'order_amount_usd',label:'订单金额 USD',numeric:true}],data.groups||[],el('p','全量已读集合先计算；当前返回 '+(data.groups||[]).length+' 个分组，其他/未知按来源保留。','coverage')));
  const audit=el('details',null,'source-details'),version=el('p','读取 '+(data.captured_at||'未提供')+' · 版本 ');for(const chunk of String(data.source_version||'未提供').match(/.{1,16}/g)||[])version.append(document.createTextNode(chunk),el('wbr'));audit.append(el('summary','来源、完整性与缺失维度'),version,el('p','声明文件 '+fmt('records',quality.declared_files)+' / 读取 '+fmt('records',quality.read_files)+' · 文件集合'+(quality.file_set_complete?'齐读':'尚未证实齐读')+' · 上游全盘完整性 '+(quality.upstream_completeness==='unknown'?'未核实':'见源合同'),'coverage'));
  const missing={site:'站点',distribution_group:'分销组',platform:'平台',cost:'成本',profit:'利润',customer_identity:'客户身份'};if(data.missing_dimensions?.length)audit.append(el('p','缺失：'+[...new Set(data.missing_dimensions.map(k=>missing[k]||'未提供维度'))].join('、'),'coverage'));body.append(audit);
  if(Array.isArray(data.available_profiles)){scope.esProfiles=data.available_profiles;const project=document.querySelector('[aria-label="流量项目"]');if(project)for(const item of data.available_profiles){const code=typeof item==='string'?item:item.code,label=typeof item==='string'?item:item.label;if(!/^[A-Z0-9_]{1,24}$/.test(code||'')||code==='ALL'||[...project.options].some(o=>o.value===code))continue;const o=el('option',label||code);o.value=code;project.append(o);}}
 }
 async function read(poll=false){
  if(!current())return;if(poll&&Date.now()>=deadline){button.disabled=false;button.textContent='重新读取结构';body.setAttribute('aria-busy','false');body.append(el('p','已等待2分钟，自动检查暂停；可主动重试。','coverage'));return;}
  if(!poll)deadline=Date.now()+120000;controller?.abort();controller=new AbortController();scope.esAbort=controller;const own=controller,key=cacheKey(),q=query();let waiting=false;button.disabled=true;button.textContent='正在读取…';body.setAttribute('aria-busy','true');
  if(!poll&&!scope.esCache.has(key))body.replaceChildren(el('p','正在读取所选窗口…','coverage'));
  try{const response=await fetch('/dashboard/fs-home/advisor.json?'+new URLSearchParams(q),{credentials:'same-origin',cache:'no-store',signal:AbortSignal.any([own.signal,scope.signal,AbortSignal.timeout(30000)])});if(!current()||own!==controller||own.signal.aborted)return;if(!response.ok&&response.status!==202)throw Error(response.status===422?'该游戏或窗口结构暂不支持，请调整日期或查看来源能力。':'结构读取失败，请稍后重试。');const data=await response.json();if(!current()||own!==controller||own.signal.aborted)return;if(data.schemaVersion!==1||data.kind!=='es_order_structure'||data.profile!==q.profile||data.period?.start!==q.start||data.period?.end!==q.end)throw Error('返回区间或结构版本不一致。');scope.esCache.set(key,data);show(data);waiting=data.status==='pending'||data.quality?.refresh_pending===true;if(waiting)scope.esTimer=setTimeout(()=>read(true),Math.min(5000,Math.max(1,deadline-Date.now())));
  }catch(error){if(current()&&own===controller&&!own.signal.aborted)body.replaceChildren(el('p',error.name==='TimeoutError'?'读取超时，可主动重试。':String(error.message).startsWith('protected_read_failed')?'结构读取失败，请稍后重试。':error.message,'failure'));}finally{if(current()&&own===controller){button.disabled=waiting;button.textContent=waiting?'正在准备结构…':'重新读取结构';body.setAttribute('aria-busy',String(waiting));}}
 }
 const reset=()=>{controller?.abort();clearTimeout(scope.esTimer);scope.esGroup=group.value;body.replaceChildren(el('p','筛选已改变，点击读取更新结构。','coverage'));button.textContent='读取所选窗口订单结构';button.disabled=false;};group.addEventListener('change',reset);status.addEventListener('change',reset);button.addEventListener('click',()=>read());
 if(scope.esCache.has(cacheKey()))show(scope.esCache.get(cacheKey()));
}
scope.signal.addEventListener('abort',()=>{scope.esAbort?.abort();clearTimeout(scope.esTimer);},{once:true});

function renderReportLinks(parent,period){
 const block=section('运营报告','查看日报、周报或按自定义区间进入报告工作区；本页不生成即时分析。'),links=el('div',null,'toolbar');
 for(const [kind,label]of [['daily','日报'],['weekly','周报'],['investigation','自定义报告']]){const a=el('a',label,'fs-btn');a.href='/dashboard/fs-home/brain/index.html?report_kind='+kind+'&start='+period.start+'&end='+period.end;links.append(a);}block.append(links);parent.append(block);
}

function rangeControls(toolbar,container,model,periods,selector){
 scope.rangeGeneration??=0;
 const controls=el('form',null,'traffic-range');controls.setAttribute('aria-label','流量分析自定义区间');
 const start=el('input'),end=el('input');start.type=end.type='date';start.required=end.required=true;start.setAttribute('aria-label','流量开始日期');end.setAttribute('aria-label','流量结束日期');
 const current=periods.find(p=>p.id===selector.value)||periods[0];start.value=current?.start||'';end.value=current?.end||'';
 const apply=el('button','应用区间');apply.type='submit';const note=el('p','可自定义起止日期；Google各来源按自己的时区与实际覆盖返回，关联会员按北京时间统计。','coverage');note.setAttribute('role','status');
 const shortcuts=el('div',null,'toolbar traffic-shortcuts');for(const [label,days] of [['今日',0],['昨日',1],['近7天',7],['近14天',14],['近30天',30],['上月',-1],['本月截至昨日',-2]]){const button=el('button',label,'fs-btn');button.type='button';button.addEventListener('click',()=>{const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());const hi=new Date(today+'T12:00:00Z');if(days!==0)hi.setUTCDate(hi.getUTCDate()-1);const lo=new Date(hi);if(days>0)lo.setUTCDate(lo.getUTCDate()-days+1);if(days===-1){hi.setTime(new Date(today+'T12:00:00Z'));hi.setUTCDate(0);lo.setTime(hi);lo.setUTCDate(1);}if(days===-2){lo.setTime(new Date(today+'T12:00:00Z'));lo.setUTCDate(1);}start.value=lo.toISOString().slice(0,10);end.value=hi.toISOString().slice(0,10);controls.requestSubmit();});shortcuts.append(button);}toolbar.after(shortcuts);
 controls.append(el('span','自定义日期'),start,el('span','至'),end,apply);toolbar.after(controls,note);
 controls.addEventListener('submit',async event=>{
  event.preventDefault();if(!start.value||!end.value||start.value>end.value){note.textContent='起始日期不能晚于结束日期。';return;}
  const lo=start.value,hi=end.value,generation=++scope.rangeGeneration;scope.rangePending=true;container.setAttribute('aria-busy','true');apply.disabled=true;note.textContent=(!currentTrafficPeriod(current)?'旧版细分缓存尚未按当前规则核实全量；':'')+'正在查询 '+lo+' — '+hi+'；来源读取期间保留原视图。';
  try{
   const url='/dashboard/marketing/range.json?'+new URLSearchParams({start:lo,end:hi});let result;
   for(let attempt=0;attempt<130;attempt++){
    if(generation!==scope.rangeGeneration||start.value!==lo||end.value!==hi||!container.isConnected)return;
    const response=await fetch(url,{cache:'no-store',credentials:'same-origin'});if(generation!==scope.rangeGeneration||!container.isConnected)return;if(response.status===202||response.status===429){await new Promise(resolve=>setTimeout(resolve,5000));continue;}
    if(!response.ok)throw Error(response.status===429?'已有区间查询正在运行，请稍后再试。':'区间查询未成功，请检查日期或重新登录后再试。');
    result=await response.json();break;
   }
   if(!result||!['available','partial','stale'].includes(result.status)||result.start!==lo||result.end!==hi||!currentTrafficPeriod(result.period))throw Error('这次区间未取得可用数据，已保留原视图。');
   if(generation!==scope.rangeGeneration||start.value!==lo||end.value!==hi)return;
   if(!container.isConnected||scope.root!==container.getRootNode()&&!scope.root.contains(container))return;
   const next=structuredClone(model),p=result.period;p.id='custom_'+lo+'_'+hi;p.isCustomRange=true;
   next.details.periods=[p,...next.details.periods.filter(x=>!x.isCustomRange&&!(x.start===lo&&x.end===hi))];next.businessLinks=result.businessLinks;scope.customRange={period:p,businessLinks:result.businessLinks};container.dataset.period=p.id;render(container,next);
   container.querySelector('.traffic-range + .coverage').textContent=(result.status==='stale'?'本次更新失败，保留原日期结果 ':'已查询 ')+lo+' — '+hi+'；各来源覆盖及失败项见对应卡片。';
  }catch(error){if(container.isConnected&&generation===scope.rangeGeneration)note.textContent=error.message;}finally{if(generation===scope.rangeGeneration){scope.rangePending=false;container.setAttribute('aria-busy','false');apply.disabled=false;}}
 });
 return function ensureCurrentPeriod(period){
  if(scope.restoreRangeWanted||currentGamePeriod(period)||!period?.start||!period?.end)return;
  scope.rangeUpgradeTried??=new Set();const key=period.start+'_'+period.end;
  if(scope.rangeUpgradeTried.has(key)){note.textContent='当前旧版细分缓存尚未升级成功；可点击应用区间重试，不按全量解释。';return;}
  note.textContent='当前为旧版细分缓存，尚未按当前规则核实全量；正在读取同期间准确数据。';
  setTimeout(()=>{
   if(!controls.isConnected||!container.isConnected||scope.model!==model||container.dataset.period!==period.id||container.dataset.brand==='business'||scope.rangePending||scope.rangeUpgradeTried.has(key))return;
   scope.rangeUpgradeTried.add(key);start.value=period.start;end.value=period.end;controls.requestSubmit();
  },0);
 };
}

const gameLabels=scope.gameLabels={all:'全部游戏',FC27:'FC27',FC26:'FC26',D4:'Diablo IV',AION2:'Aion2',RS:'RuneScape',MADDEN:'Madden',POE2:'POE2',ARC:'ARC Raiders',WOW_FOREVER:'WoW Forever',MSCW:'MapleStory Classic World',MONOPOLY_GO:'Monopoly Go',NBA2K:'NBA2K',MLB:'MLB',GLOBAL:'全局品牌 / 通用',UNKNOWN:'未映射 / 待核'};
function sumAdsRows(rows){
 if(!rows.length)return null;
 const m={};for(const key of ['cost','clicks','impressions','conversions','conversionsValue'])m[key]=rows.every(r=>r.metrics?.[key]!=null)?rows.reduce((n,r)=>n+Number(r.metrics[key]),0):null;
 m.cpa=m.cost!=null&&m.conversions>0?m.cost/m.conversions:null;m.platformRoas=m.conversionsValue!=null&&m.cost>0?m.conversionsValue/m.cost:null;return m;
}
function gameProjection(source,accounts){
 if(source!=='ads')return scope.activePeriod.sources?.[source]?.games;
 const groups=new Map();for(const a of accounts)for(const c of a.calculation_campaigns||a.campaigns||[]){const game=c.game_mapping?.game||'UNKNOWN';if(!groups.has(game))groups.set(game,[]);groups.get(game).push(c);}
 return {status:accounts.length&&accounts.every(a=>a.campaign_calculation_complete)?'available':'partial',rows:[...groups].map(([game,items])=>({game,label:gameLabels[game]||game,metrics:sumAdsRows(items),row_count:items.length,basis:['广告系列映射']})).sort((a,b)=>(b.metrics?.cost||0)-(a.metrics?.cost||0))};
}
function fullDetail(title,columns,rows,note){const box=el('article',null,'breakdown');box.append(el('h3',title));if(note)box.append(el('p',note,'coverage'));box.append(table(columns,rows||[]));return box;}
function renderSourceBody(panel,p,site,source){
 const game=scope.trafficProject||'all',accounts=(p.adsAccounts||[]).filter(a=>site==='all'||a.brand===site);
 const s=p.sources?.[source];scope.activePeriod=p;
 const note=section('数据范围',p.start+' — '+p.end+' · '+(source==='ads'?'广告账号范围':'来源原生统计窗口'));
 note.append(el('p',source==='ads'?'广告归因不等于Admin实收；平台ROAS与订单规则归因回报分开。':'GA4按访问行为、GSC按自然搜索统计；不与订单拼成逐人转化漏斗。','coverage'));panel.append(note);
 if(site==='all'&&source!=='ads')note.append(el('p','当前仅MMOEXP已验证接通此来源；这里不代表全部卫星站合计。','coverage'));
 if(source!=='ads'&&site==='rsorder'){panel.append(section('该站点尚未接通 '+source.toUpperCase(),'RSOrder暂无此来源数据，不使用MMOEXP数据替代，也不填0。'));return;}
 if(source!=='ads'&&!s){panel.append(section('来源数据尚未提供','保留缺口，未按0解释。'));return;}
 const overview=section(source==='ads'?'Ads · 全局投放':source==='ga4'?'GA4 · 全局访问与行为':'GSC · 全局自然搜索','全局指标不随右侧游戏选择改名；游戏表现见下方。');
 if(source==='ads'){
  const currencies=new Set(accounts.map(a=>a.currency));const m=currencies.size===1&&currencies.has('USD')?sumAdsRows(accounts):null;
  overview.append(cards(['cost','clicks','conversions','cpa','platformRoas'],m));for(const a of accounts)overview.append(el('p',a.label+' · '+a.customerId+' · '+a.currency+' · '+a.timezone,'coverage'),statusNote(a));
 }else {overview.append(cards(source==='ga4'?['sessions','activeUsers','newUsers','engagementRate']:['clicks','impressions','ctr','position'],s.metrics,s.changes),statusNote(s),line(s.daily||[],source==='ga4'?'sessions':'clicks',p));}
 panel.append(overview);
 const projection=gameProjection(source,accounts),rows=projection?.rows||[],grid=el('div',null,'traffic-dual');
 const keys=source==='ads'?['cost','conversions','cpa','platformRoas']:source==='ga4'?['sessions']:['clicks','impressions','ctr','position'];
 const left=fullDetail('各游戏表现',[{key:'label',label:'游戏'},...keys.map(metricCol),{key:'basis',label:'口径 / 线索',get:r=>(r.basis||[]).map(v=>({explicit_game_path:'游戏目录',news_slug_hint:'资讯标题线索（待核）',site_home:'站点首页',unmapped_page:'页面待映射'}[v]||v)).join(' · ')}],rows,'点击游戏查看右侧细分。'+(projection?'当前状态 '+projection.status+'；按已返回落地页/搜索页面或广告系列归类，缺失和跨游戏另列。':'游戏数据合同尚未接通，不能从Top榜推算完整游戏总量。'));
 left.querySelectorAll('tbody tr').forEach((tr,i)=>{if(!rows[i])return;const cell=tr.firstElementChild;cell.replaceChildren();const button=el('button',rows[i].label,'fs-btn');button.type='button';button.setAttribute('aria-pressed',String(game===rows[i].game));button.onclick=()=>{scope.trafficProject=rows[i].game;render(document.getElementById('marketing'),scope.model);};cell.append(button);});
 grid.append(left);const right=el('article',null,'breakdown');right.append(el('h3',(gameLabels[game]||game)+' · 深入查看'));
 if(game==='all')right.append(el('p','选择左侧游戏，查看它的国家、渠道或广告系列。','coverage'));
 else if(source==='ads'){
  const selected=accounts.flatMap(a=>a.calculation_campaigns||a.campaigns||[]).filter(c=>(c.game_mapping?.game||'UNKNOWN')===game);
  const countryGroups=new Map();for(const a of accounts)for(const r of a.countries?.rows||[]){if((r.game_mapping?.game||'UNKNOWN')!==game)continue;const key=r.country||('criterion:'+r.countryCriterionId);if(!countryGroups.has(key))countryGroups.set(key,[]);countryGroups.get(key).push(r);}
  const countries=[...countryGroups].map(([country,items])=>({country,metrics:sumAdsRows(items)})).sort((a,b)=>(b.metrics.cost||0)-(a.metrics.cost||0));
  right.append(fullDetail('实际用户国家',[{key:'country',label:'国家'},...keys.map(metricCol)],countries,'Google Ads user_location_view；未知国家保留来源ID。'+accounts.map(a=>a.label+' '+(a.countries?.status?.status||'未接通')).join(' · ')),fullDetail('广告系列',[{key:'campaignName',label:'广告系列'},...keys.map(metricCol)],selected,'系列国家后缀不作为实际国家；全局品牌费用不分摊。'));
 }else{
  const countries=s.game_countries;right.append(fullDetail('国家',[{key:'dimension',label:'国家'},...keys.map(metricCol)],(countries?.rows||[]).filter(r=>r.game===game),countries?'联合查询状态 '+countries.status:'游戏×国家尚未接通，不能拼接全站国家表。'));
  if(source==='ga4'){const channels=s.game_channels;right.append(fullDetail('来源 / 媒介',[{key:'dimension',label:'来源 / 媒介'},metricCol('sessions')],(channels?.rows||[]).filter(r=>r.game===game),channels?'联合查询状态 '+channels.status:'游戏×渠道尚未接通。'));}
 }
 grid.append(right);panel.append(grid);
 const details=section(game==='all'?'全局维度明细':'全局维度参考 · 非所选游戏专属','原始来源、范围与完整性单独保留。');
 if(source==='ads')renderAds(details,accounts,site,p);
 else {const specs=source==='ga4'?[['country','国家','country'],['source_medium','来源 / 媒介','sessionSourceMedium'],['landing_page','落地页','landingPage'],['device','设备','deviceCategory']]:[['country','国家','country'],['query','搜索词','query'],['page','搜索页面','page']];
  for(const [key,title,dim]of specs){const t=s.breakdowns?.[key]||{};details.append(fullDetail(title,[{key:dim,label:title,get:r=>r.dimensions?.[dim]},...(source==='ga4'?['sessions','activeUsers','bounceRate']:['clicks','impressions','ctr','position']).map(metricCol)],t.rows,'返回 '+(t.returned_dimension_rows??'未知')+' 行；本页展示 '+(t.rows?.length??0)+' 行，展示范围不等于来源完整总量。'));}
 }
 if(game==='all')panel.append(details);else{const d=el('details',null,'source-details');d.append(el('summary','展开全局维度参考（不属于当前游戏）'),details);panel.append(d);}
 const related=el('details',null,'source-details');related.append(el('summary','经营关联 · 订单结构与新客优惠（按需）'));
 if(site!=='rsorder'){
  if(['all','FC27','D4','AION2'].includes(game))renderESStructure(related,p);else related.append(el('p','当前游戏的订单结构映射尚未核实；不拿全站订单代替。','coverage'));
  const membership=el('div'),read=el('button','读取同期间会员与优惠情况','fs-btn');read.type='button';read.onclick=()=>loadBusinessLinks(membership,p,scope.model.businessLinks);related.append(read,membership);
 }else related.append(el('p','此经营关联仅验证MMOEXP主站，未用它代替RSOrder。','coverage'));
 panel.append(related);
 const action=section('经营解读与行动','查看已生成报告，或进入Hermes按所选日期研究；切标签不会触发模型重跑。');renderReportLinks(action,p);const business=el('a','查看经营分析 →','fs-btn');business.href='/dashboard/analytics/?mode=business';action.append(business);panel.append(action);
}
function render(container,model){
 scope.tipId??=0;scope.trafficProject??='all';scope.source=['ga4','gsc','ads'].includes(scope.source)?scope.source:'ga4';scope.model=model;const saved=container.dataset.period;
 container.replaceChildren();container.classList.add('traffic-source-first');
 if(model.schemaVersion!==1||model.isMock!==false){container.append(el('p','未取得已验证真实快照。','failure'));return;}
 const site=['mmoexp','rsorder','all'].includes(container.dataset.brand)?container.dataset.brand:'mmoexp';container.dataset.brand=site;
 const periods=model.details?.periods||[],selector={value:periods.some(p=>p.id===saved)?saved:periods[0]?.id};container.dataset.period=selector.value||'';
 const toolbar=el('div',null,'toolbar'),tabs=el('div',null,'brand-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','流量数据来源');
 for(const [key,name]of [['ga4','GA4 · 访问与行为'],['gsc','GSC · 自然搜索'],['ads','Ads · 广告经营']]){const b=el('button',name);b.type='button';b.id='source-tab-'+key;b.dataset.source=key;b.setAttribute('role','tab');b.setAttribute('aria-selected',String(scope.source===key));b.setAttribute('aria-controls','brand-panel');b.tabIndex=scope.source===key?0:-1;b.onclick=()=>{scope.source=key;render(container,scope.model);};tabs.append(b);}
 tabs.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const bs=[...tabs.children],i=bs.indexOf(document.activeElement),n=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;bs[n].click();container.querySelector('#'+bs[n].id)?.focus();};toolbar.append(tabs);
 const sites=el('select');sites.setAttribute('aria-label','流量站点');for(const [v,label]of [['mmoexp','MMOEXP'],['rsorder','RSOrder业务账号'],['all','全部已接入范围']]){const o=el('option',label);o.value=v;sites.append(o);}sites.value=site;sites.onchange=()=>{container.dataset.brand=sites.value;scope.trafficProject='all';render(container,scope.model);};toolbar.append(sites);container.append(toolbar);
 const ensure=rangeControls(toolbar,container,model,periods,selector),p=periods.find(x=>x.id===selector.value);
 const project=el('select');project.setAttribute('aria-label','流量项目');for(const [key,label]of Object.entries(gameLabels)){const o=el('option',label);o.value=key;project.append(o);}project.value=scope.trafficProject;project.onchange=()=>{scope.trafficProject=project.value;render(container,scope.model);};toolbar.append(project);
 const panel=el('div');panel.id='brand-panel';panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','source-tab-'+scope.source);container.append(panel);
 scope.esGeneration=(scope.esGeneration||0)+1;scope.esAbort?.abort();clearTimeout(scope.esTimer);
 if(p){ensure(p);renderSourceBody(panel,p,site,scope.source);}else panel.append(el('p','所选区间尚未取得数据，未填0。','coverage'));
 const audit=el('details',null,'source-details');audit.append(el('summary','数据更新与口径'),el('p','快照生成 '+(model.data_generated_at||'未知')+'；来源时区、数据截至和覆盖分别列示。Admin主源，Order仅补缺；参考利润保持估算。','snapshot-time'));container.append(audit);workspaceSync();
}

async function load(container){if(scope.rangePending)return;const generation=scope.rangeGeneration||0;try{const response=await fetch('/dashboard/marketing/data.json',{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw Error('DATA_NOT_AVAILABLE');scope.checkedAt=new Date().toISOString();const fresh=await response.json();if(scope.rangePending||generation!==(scope.rangeGeneration||0))return;if(scope.customRange){fresh.details.periods=[scope.customRange.period,...fresh.details.periods];fresh.businessLinks=scope.customRange.businessLinks;}render(container,fresh);}catch{const old=container.querySelector('.refresh-error');if(old)old.remove();container.prepend(el('p','本次更新未成功；若有已显示数据则保留，重新登录后再刷新。','refresh-error failure'));}}
window.MMOEXPMarketing={render,load};const target=document.getElementById('marketing');if(target){load(target);setInterval(()=>{if(!document.hidden)load(target);},300000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load(target);});}
})();
let workspaceQueued=false;
function workspaceState(){const target=document.getElementById('marketing');scope.businessProfile=target.querySelector('[aria-label="经营项目"]')?.value||scope.businessProfile||scope.seed?.g_business_profile||'MMOEXP';return {g_brand:target.dataset.brand||'mmoexp',g_period:target.dataset.period||'',g_source:scope.source||'all',g_project:scope.trafficProject||'all',g_business_profile:scope.businessProfile,details:target.querySelector('.snapshot-time')?.textContent,generatedAt:scope.model?.data_generated_at,checkedAt:scope.checkedAt,phase:target.querySelector('.refresh-error')?'error':target.querySelector('.brand-tabs')?'available':'loading'};}
function workspaceApply(s){
 const target=document.getElementById('marketing');if(!scope.model)return false;
 scope.trafficProject=Object.hasOwn(scope.gameLabels||{},s.g_project)?s.g_project:'all';
 scope.source=['ga4','gsc','ads'].includes(s.g_source)?s.g_source:'ga4';
 target.dataset.brand=['mmoexp','rsorder','all'].includes(s.g_brand)?s.g_brand:'mmoexp';
 const found=scope.model.details?.periods.some(p=>p.id===s.g_period),match=/^custom_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$/.exec(s.g_period||'');
 if(found)target.dataset.period=s.g_period;
 scope.restoreRangeWanted=!found&&match?match:null;
 window.MMOEXPMarketing.render(target,scope.model);
 if(scope.restoreRangeWanted){const wanted=scope.restoreRangeWanted,form=target.querySelector('.traffic-range');form.querySelector('[aria-label="流量开始日期"]').value=wanted[1];form.querySelector('[aria-label="流量结束日期"]').value=wanted[2];setTimeout(()=>{if(form.isConnected&&scope.restoreRangeWanted===wanted){scope.restoreRangeWanted=null;form.requestSubmit();}},0);}
 return true;
}
function workspaceSync(){if(workspaceQueued)return;workspaceQueued=true;requestAnimationFrame(()=>{workspaceQueued=false;if(scope.root.isConnected!==false)scope.changed(workspaceState());});}
return {state:workspaceState,apply:workspaceApply,update:()=>window.MMOEXPMarketing.load(document.getElementById("marketing"))};
}

