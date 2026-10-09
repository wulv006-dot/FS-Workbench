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
 date:'这行数据对应的日期；按该来源自己的时区统计。',label:'该行对应的数据来源、广告账号或意图分类。',latestDate:'来源最近返回有效数据的日期；不是页面打开时间。',
 name:'后台原始折扣码或优惠券名称；名称本身不能证明推广归属。',site:'后台记录的适用网站；此处只展示明确属于MMOEXP主站的记录。',game:'后台配置的适用游戏；未提供时显示缺失。',uses:'后台累计使用次数，不是所选Google日期内的次数。',claimed:'后台累计领取次数，不等于去重领取人数。',usedAt:'后台记录的这次用券时间；当前列表没有按Google日期区间完整筛选。',batch:'后台记录的发券批次号，用于识别同一批活动。',repeatOrders90d:'后台提供的90天复购次数原值；不按当前日期区间重新计算。',
};
const sourceNames={google:'Google',bing:'必应',duckduckgo:'DuckDuckGo搜索',yahoo:'雅虎',baidu:'百度',yandex:'Yandex搜索','(direct)':'直接访问','accounts.google.com':'Google账号网站','youtube.com':'YouTube','ea.com':'EA网站','chatgpt.com':'ChatGPT','cardpay.com':'CardPay网站','js.klarna.com':'Klarna网站','search.brave.com':'Brave搜索网站','pale.tools':'Pale Tools网站'};
const mediumNames={organic:'自然搜索',cpc:'按点击付费广告',ppc:'按点击付费广告',referral:'网站引荐',email:'电子邮件',social:'社交流量','paid-social':'付费社交广告',display:'展示广告',affiliate:'联盟推广','ai-assistant':'AI助手引荐','(none)':'无媒介标记','(not set)':'未设置','(data not available)':'数据不可用'};
const regionEnglish=new Intl.DisplayNames(['en'],{type:'region',fallback:'code'}),regionChinese=new Intl.DisplayNames(['zh-Hans'],{type:'region',fallback:'code'});
const countryCodes=new Map();
for(let a=65;a<=90;a++)for(let b=65;b<=90;b++){const code=String.fromCharCode(a,b),name=regionEnglish.of(code);if(name!==code){countryCodes.set(name.toLowerCase(),code);countryCodes.set(code.toLowerCase(),code);}}
for(const [name,code] of Object.entries({'united states of america':'US','south korea':'KR','north korea':'KP','czech republic':'CZ','russian federation':'RU','turkey':'TR','vietnam':'VN','laos':'LA','palestine':'PS','hong kong':'HK','macau':'MO','taiwan':'TW'}))countryCodes.set(name,code);
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
