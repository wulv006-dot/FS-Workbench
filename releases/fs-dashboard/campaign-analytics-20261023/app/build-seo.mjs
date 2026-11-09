import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),model=require('./activity-content.js'),core=require('./activity-core.js');
const root=path.dirname(fileURLToPath(import.meta.url)),read=name=>fs.readFileSync(path.join(root,name),'utf8');
export function loadConfig(){return JSON.parse(read('catalog.js').replace(/^window\.FC_ACTIVITY_CONFIG\s*=\s*/, '').replace(/;\s*$/, ''));}
const e=model.escape;
function attribute(html,id,name,value){
 const re=new RegExp('<[a-z][^>]*\\bid="'+id+'"[^>]*>','i');assert(re.test(html),'Missing template element '+id);
 return html.replace(re,open=>{const cleaned=open.replace(new RegExp('\\s'+name+'(?:="[^"]*"|=\'[^\']*\')?(?=\\s|>)','g'),'');return cleaned.slice(0,-1)+(value===null?'':value===true?' '+name:' '+name+'="'+e(value)+'"')+'>';});
}
function fill(html,id,value){
 const re=new RegExp('(<([a-z][a-z0-9]*)\\b[^>]*\\bid="'+id+'"[^>]*>)[\\s\\S]*?(</\\2>)','i');assert(re.test(html),'Missing template content '+id);
 return html.replace(re,(_,open,tag,close)=>open+value+close);
}
export function seoHead(info,indexable=false){
 return `<title>${e(info.title)}</title>
<meta name="description" content="${e(info.description)}">
<meta name="robots" content="${indexable?'index,follow,max-image-preview:large':'noindex,follow'}">
<link rel="canonical" href="${e(info.canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="MMOEXP">
<meta property="og:title" content="${e(info.title)}">
<meta property="og:description" content="${e(info.description)}">
<meta property="og:url" content="${e(info.canonical)}">
<meta property="og:image" content="${e(info.image)}">
<meta property="og:image:alt" content="${e(info.name)}">
<meta property="og:locale" content="${info.lang==='zh'?'zh_CN':'en_US'}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${e(info.title)}">
<meta name="twitter:description" content="${e(info.description)}">
<meta name="twitter:image" content="${e(info.image)}">
<script id="fc-seo-jsonld" type="application/ld+json">${model.json(info.schema)}</script>`;
}
export function renderPage(config,view,lang='en',{hub=false}={}){
 config=model.publicConfig(config);lang='en';
 const content=model.create(config,config.mode==='live'),info=content.page(view,lang),{words,heroes}=content,h=heroes[view],zh=lang==='zh',t=(cn,en)=>zh?cn:en;
 let html=read('page-template.html');
 html=html.replace(/(<([a-z][a-z0-9]*)\b[^>]*\bdata-i18n="([^"]+)"[^>]*>)[\s\S]*?(<\/\2>)/gi,(all,open,tag,key,close)=>words[key]?open+e(words[key][zh?0:1])+close:all);
 html=html.replace(/<html lang="[^"]*">/,'<html lang="'+(zh?'zh-CN':'en')+'">');
 html=html.replace(/<head>[\s\S]*?<\/head>/,'<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'+seoHead(info)+'\n<link rel="stylesheet" href="activity.css">\n</head>');
 html=attribute(html,'fc-activity','data-view',view);html=attribute(html,'fc-activity','data-default-view',view);html=attribute(html,'fc-activity','data-default-language',lang);

 const nav=config.pageOrder.map(key=>{const label=content.page(key,lang).name,current=key===view;return hub?`<button type="button" data-view="${key}" aria-pressed="${current}">${e(label)}</button>`:`<a data-view="${key}" href="${e(content.page(key,lang).canonical)}"${current?' aria-current="page"':''}>${e(label)}</a>`;}).join('');
 html=html.replace(/(<div class="fca-container fca-view-nav-inner">)[\s\S]*?(<\/div>)/,(_,open,close)=>open+nav+close);
 html=fill(html,'hero-kicker',e(h.kicker));html=fill(html,'hero-title','<span>'+e(h.title[zh?0:2])+'</span><strong>'+e(h.title[zh?1:3])+'</strong>');
 html=fill(html,'hero-body',e(t(...h.body)));html=fill(html,'hero-cta',e(t(...h.cta)));html=fill(html,'view-heading',e(t(...h.heading)));html=fill(html,'view-intro',e(t(...h.intro)));
 html=fill(html,'activity-offer',e(content.promotionText(lang)));html=attribute(html,'activity-offer','hidden',content.promotionText(lang)?null:true);
 const hero=view==='trio'?config.trio.hero:'assets/'+h.image+'-hero.webp',mobile=view==='trio'?config.trio.heroMobile:'assets/'+h.image+'-hero-mobile.webp';
 html=attribute(html,'hero-image','src',hero);html=html.replace(/(<picture class="fca-hero-art">)/,`$1<source media="(max-width: 700px)" srcset="${e(mobile||hero)}">`);
 const sbc=view==='sbc';for(const id of ['sbc-controls','sbc-lineup','sbc-options'])html=attribute(html,id,'hidden',sbc?null:true);html=attribute(html,'product-grid','hidden',sbc?true:null);
 const p=key=>config.products[key],money=amount=>new Intl.NumberFormat(zh?'zh-CN':'en-US',{style:'currency',currency:'USD'}).format(amount/100),amount=key=>core.activityPrice(core.line(p(key),'ps').amount,config),priced=config.activityPricing?.enabled===true,price=key=>priced?money(amount(key).amount):config.activityPricing?.strategy==='native_discount_code'?'Price confirmed at checkout':config.mode==='live'?t('现价确认中','Checking current price'):money(amount(key).amount);
 const pricing=key=>({price:price(key),originalPrice:priced&&amount(key).discountAmount?money(amount(key).baseAmount):'','discountPercent':config.activityPricing?.discountPercent});
 const card=(key,opts={})=>content.card(p(key),{lang,...pricing(key),...opts});
 html=fill(html,'core-select',config.sbc.ids.map(key=>`<option value="${e(key)}"${key===config.sbc.defaultId?' selected':''}>${e(p(key).title)}</option>`).join(''));
 html=fill(html,'core-mode-help',e(t('核心不加入购买清单，也不计入金额。你只购买两位搭档。','Your owned core is excluded from the purchase and total. You buy the two companions only.')));
 const route=config.sbc.routes[config.sbc.defaultId],pool=[...new Set([...route.picks,...route.alternatives])];
 html=fill(html,'sbc-lineup',sbc?card(config.sbc.defaultId,{label:t('你的 SBC 核心','YOUR SBC CORE'),fixed:true,owned:true})+route.picks.map((key,i)=>card(key,{label:t('搭档 '+(i+1),'COMPANION '+(i+1)),fixed:true,picked:true})).join(''):'');
 html=fill(html,'sbc-options',sbc?route.picks.map((key,i)=>`<div class="fca-companion-picker"><label for="companion-${i}">${e(t('搭档 '+(i+1)+' · '+route.label.zh,'Companion '+(i+1)+' · '+route.label.en))}</label><select id="companion-${i}" name="companion${i+1}" data-companion-slot="${i}">${pool.map(id=>`<option value="${e(id)}"${id===key?' selected':''}${id===route.picks[1-i]?' disabled':''}>${e(p(id).title)}</option>`).join('')}</select></div>`).join('')+`<p class="fca-inline-note fca-pairing-note">${e(t('这是搭配灵感，不承诺满化学。请核对游戏内位置、联赛与现有阵容。','Pairing ideas do not guarantee full chemistry. Check in-game positions, leagues and your existing lineup.'))}</p>`:'');
 html=fill(html,'product-grid',sbc?'':info.ids.map((key,i)=>card(key,{label:view==='trio'?config.trio.roles[i][lang]:config.weekly.edition[lang],fixed:view==='trio',picked:view==='trio'||i===0})).join(''));
 html=fill(html,'bundle-heading',e(t('也可以选商店现有阵容包。','Or start with an existing player bundle.')));html=fill(html,'bundle-grid',config.bundles.ids.map(key=>content.bundle(p(key),{lang,...pricing(key)})).join(''));
 const selected=sbc?route.picks:view==='trio'?config.trio.ids:[config.weekly.ids[0]],total=priced?money(selected.reduce((n,key)=>n+amount(key).amount,0)):config.activityPricing?.strategy==='native_discount_code'?'Confirmed at checkout':config.mode==='live'?t('点击核对现价','Check current total'):money(selected.reduce((n,key)=>n+amount(key).amount,0));
 html=fill(html,'summary-count',String(selected.length));html=fill(html,'summary-total',e(total));html=fill(html,'mobile-summary-total',e(selected.length+' '+t('项','items')+' · '+total));html=fill(html,'mobile-review',e(t('核对方案','Review lineup')));
 const date=new Intl.DateTimeFormat(zh?'zh-CN':'en-GB',{year:'numeric',month:'short',day:'numeric',timeZone:'Asia/Shanghai'}).format(new Date(config.capturedAt));
 html=fill(html,'summary-note',e(t('精确商品分别列出，已有核心不重复购买；当前展示为 '+date+' 公开价格快照。','Exact items are listed separately. Owned cores are excluded. Public price snapshot: '+date+'.')));
 if(priced){
  // Static value is the PlayStation snapshot; the page re-reads the current price for the chosen platform.
  html=fill(html,'summary-note','Choose your platform to read the current store price. The original cart applies the activity code; coupons and member points cannot be combined.');
 }else if(config.activityPricing?.strategy==='native_discount_code'){
  html=fill(html,'summary-note','Select the exact items and platform. Campaign offer not configured. Any code must be accepted by the main-site checkout before payment; coupons and member points cannot be combined.');
  html=fill(html,'summary-savings','');
 }
 // Static HTML never submits: the page enables it only after a native review.
 html=attribute(html,'submit-selection','disabled',true);
 html=fill(html,'activity-breadcrumb','<ol>'+info.breadcrumbs.map((x,i)=>'<li>'+(i<2?'<a href="'+e(x.url)+'">'+e(x.name)+'</a>':'<span aria-current="page">'+e(x.name)+'</span>')+'</li>').join('')+'</ol>');
 html=fill(html,'activity-guide',info.guide);
 if(!zh)html=html.replace('请启用 JavaScript 体验活动，或直接前往商店选购。','Enable JavaScript to build your lineup, or browse the original shop.');
 const fragment=html.match(/<main\b[\s\S]*?<\/main>/)[0];
 const local=html.replace(/(<a\b[^>]*\bdata-view="[^"]+"[^>]*\bhref=")([^"]+)(")/g,(_,open,url,close)=>open+path.posix.basename(new URL(url).pathname)+close);
 return {info,html:local.replace('<script defer src="host-adapter.js"></script>','<script defer src="host-adapter.js"></script>\n    <script defer src="standalone-adapter.js"></script>'),fragment,head:seoHead(info,true),validation:'<!DOCTYPE html><html lang="en"><head>'+seoHead(info,true)+'</head><body>'+fragment.replace(/<script defer[^>]*><\/script>/g,'')+'</body></html>'};
}
export function buildOutputs(config){
 assert(new URL(config.seo.origin).origin==='https://www.mmoexp.com','Unexpected site origin');
 assert(/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(config.seo.assetPath));assert(!Number.isNaN(Date.parse(config.capturedAt)),'Invalid catalog timestamp');
 assert.deepEqual([...config.pageOrder].sort(),['sbc','trio','weekly']);
 if(config.activityPricing?.enabled)core.activityPrice(100,config);
 assert(['en','zh'].includes(config.defaultLanguage));assert(new Set(config.trio.ids).size===3,'Trio must contain three distinct cards');
 assert(config.trio.ids.length===3&&config.trio.ids.every(id=>config.products[id]?.kind==='player'),'Trio must contain three existing player cards');
 const analyticsSandbox={window:{}};vm.runInNewContext(read('analytics-config.js'),analyticsSandbox);
 const registry=analyticsSandbox.window.FC_ANALYTICS_CONFIG.registry.map(a=>({...a,path:config.seo.pages[a.view]?.path||a.path}));
 const outputs={'catalog.json':JSON.stringify(config,null,2)+'\n','analytics/activity-registry.json':JSON.stringify(registry,null,2)+'\n'};
 const paths=new Set();for(const view of ['weekly','trio','sbc']){
  const route=config.seo.pages[view].path,file={weekly:'Weekly-Scout.html',sbc:'Sbc-Companions.html',trio:'Player-Trio.html'}[view];assert(route===config.seo.assetPath+file,'Invalid page route');assert(!paths.has(route));paths.add(route);
  const result=renderPage(config,view);
  outputs[path.posix.basename(route)]=result.html;outputs['activity-fragment-'+view+'.html']=result.fragment;outputs['seo-head-'+view+'.html']=result.head;outputs['structured-data-'+view+'.json']=model.json(result.info.schema)+'\n';outputs['validation/'+view+'.html']=result.validation;
 }
 outputs['index.html']=renderPage(config,config.defaultView,config.defaultLanguage,{hub:true}).html;
 outputs['sitemap.xml']='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+[...paths].map(route=>'<url><loc>'+e(new URL(route,config.seo.origin).href)+'</loc><lastmod>'+new Date(config.capturedAt).toISOString()+'</lastmod></url>').join('')+'</urlset>\n';
 const keys=[...new Set([...config.weekly.ids,...config.trio.ids,...config.sbc.ids,...Object.values(config.sbc.routes).flatMap(route=>[...route.picks,...route.alternatives]),...config.bundles.ids])];
 outputs['promotion-policy.json']=model.json({activityId:'fc27-season2',status:'requires_backend_and_approved_cost_validation',...config.activityPricing,respectExistingMutualExclusion:true,eligible:keys.flatMap(key=>Object.values(config.products[key].platforms).map(p=>({id:p.id,aid:p.aid,quantity:p.quantity}))),sourceProof:config.activityPricing?.strategy==='native_discount_code'?'native_order_discount_code_and_effective_payment':'server_persisted_cart_line_promotion_context',rounding:'existing_display_currency_scale_half_up_per_line',profitPolicy:'approved_policy_for_each_eligible_item_category_no_inherited_Coins_floor'})+'\n';
 return outputs;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const outputs=buildOutputs(loadConfig()),check=process.argv.includes('--check');
 for(const [name,data] of Object.entries(outputs)){const file=path.join(root,name);if(check)assert(fs.existsSync(file)&&fs.readFileSync(file,'utf8')===data,'Stale generated file: '+name);else{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,data);}}
 console.log(JSON.stringify({status:check?'generated_files_current':'generated',files:Object.keys(outputs).length,pages:3}));
}
