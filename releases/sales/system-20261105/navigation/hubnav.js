/* Shared navigation only. Every business page keeps its existing server permission gate.
   2026-10-19（三修 · 根治切页闪屏）：
   1) 导航样式全部内联（自带局部色板），不再外链 4 个 CSS —— 导航 DOM 与样式同帧生效，
      消除「先裸样式/无侧栏 → 再变成侧栏」的布局跳变；
   2) 导航清单编译进脚本（BUILTIN），冷启动零网络依赖即可同步渲染完整导航，
      不再出现「正在确认访问范围」占位；清单在后台静默更新；
   3) 身份有缓存就补账号区，无缓存后台拉取，不阻塞导航；
   4) 弹窗只用于「无权限 / 未登录」这类异常，不再做日常过渡态。 */
(function(){
 'use strict';

const menuEpochSlot='fs-menu-access-epoch';
const ID_CACHE='fs-nav-identity', REG_CACHE='fs-nav-registry-sales-20261105-v1';
const ID_TTL=30000, REG_TTL=300000;
const NAV_W=236;

/* 2026-10-20：/__auth/access/（账号与权限控制台）也并入这条全站导航。
   它不靠 nginx 注入，而是页面自己确认「已登录 + 是管理员」后再加载本脚本，
   所以未登录的登录落点不会露出整条导航。其余 /__auth/* 仍是独立门面。 */
const IAM_PAGE=location.pathname.startsWith('/__auth/access');
if(window.parent!==window||document.getElementById('hubNav')||(location.pathname.startsWith('/__auth/')&&!IAM_PAGE)||location.pathname.startsWith('/fc27/'))return;
if(!document.body)return;

const uiRoot='/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/';
const styledModule=!document.body.hasAttribute('data-management-v2')&&(location.pathname.startsWith('/dashboard/')||location.pathname.startsWith('/tools/fc27-gallery/')||location.pathname.startsWith('/tools/fc27-players/'));

/* ---------- 1. 内联导航样式（局部作用域，不污染页面色板） ---------- */
const NAV_CSS=[
 '#hubNav{--n-surface:#fff;--n-surface2:#f7f9fb;--n-text:#1b2632;--n-muted:#596980;--n-line:#dce3eb;--n-line-soft:#e8edf3;--n-brand:#1f6f73;--n-brand-soft:#e3f0ef;--n-focus:#147a80;--n-font:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}',
 'html[data-fs-theme="dark"] #hubNav,#hubNav[data-theme="dark"]{--n-surface:#121d31;--n-surface2:#182641;--n-text:#e8eef6;--n-muted:#b6c4d7;--n-line:#35465f;--n-line-soft:#293a51;--n-brand:#4db8b0;--n-brand-soft:#183a40;--n-focus:#7fd0c9}',
 'body.fs-unified-navigation{margin-left:'+NAV_W+'px!important}',
 'body.fs-unified-navigation #sidebar,body.fs-unified-navigation .global-nav,body.fs-unified-navigation #menu{display:none!important}',
 'body.fs-unified-navigation .shell{margin-left:0!important}body.fs-unified-navigation .platform-header{padding-inline:24px}',
 'body.fs-unified-navigation .topbar{left:'+NAV_W+'px}',
 '#hubNav{display:block;position:fixed;inset:0 auto 0 0;width:'+NAV_W+'px;overflow-y:auto;z-index:80;background:var(--n-surface);color:var(--n-text);border-right:1px solid var(--n-line);font:13px/1.55 var(--n-font);padding:22px 14px;text-align:left;margin:0}',
 '#hubNav,#hubNav *{box-sizing:border-box}#hubNav a{display:block;color:inherit;text-decoration:none;border-radius:9px;padding:9px 11px;cursor:pointer}',
 '#hubNav a:hover,#hubNav a[aria-current]{background:var(--n-brand-soft);color:var(--n-brand)}',
 '#hubNav a:focus-visible,#hubNav select:focus-visible,#hubNavToggle:focus-visible{outline:3px solid var(--n-focus);outline-offset:2px}',
 '#hubNav .hn-brand{font-size:18px;font-weight:700;padding:8px 11px 24px;letter-spacing:.02em}#hubNav .hn-home{font-weight:600}',
 '#hubNav .hn-group{padding-top:5px;margin-top:5px}#hubNav .hn-heading{font-weight:600;display:flex;gap:11px;align-items:center}',
 '#hubNav .hn-icon{font-size:17px;width:21px;text-align:center;color:var(--n-brand)}',
 '#hubNav .hn-tool{font-size:12px;margin-left:14px;padding:7px 12px;border-left:1px solid var(--n-line);border-radius:0 8px 8px 0}',
 '#hubNav .hn-account{border-top:1px solid var(--n-line);margin-top:22px;padding-top:15px;font-size:12px}',
 '#hubNav .hn-status{font-size:12px;color:var(--n-muted);padding:4px 11px}',
 '#hubNav .hn-theme{display:grid;gap:7px;padding:12px 11px 4px;color:var(--n-muted);font-size:12px}',
 '#hubNav .hn-theme select{width:100%;padding:7px 9px;border:1px solid var(--n-line);border-radius:9px;background:var(--n-surface2);color:var(--n-text)}',
 'body.fs-unified-navigation #hubNavToggle,body.fs-unified-navigation #hubNavScrim{display:none}',
 '@media(max-width:899px){body.fs-unified-navigation{margin-left:0!important;padding-top:50px!important}#hubNav{transform:translateX(-100%);width:min(270px,85vw);padding-top:52px}#hubNav.open{transform:none}body.fs-unified-navigation .topbar{left:0}body.fs-unified-navigation #hubNavToggle{display:block;position:fixed;top:8px;left:12px;z-index:81;border:1px solid var(--n-line);border-radius:9px;background:var(--n-surface);color:var(--n-text);padding:7px 12px;font:13px var(--n-font)}body.fs-unified-navigation #hubNavScrim:not([hidden]){display:block;position:fixed;inset:0;z-index:79;background:#07172b66;border:0;width:100%;height:100%}}',
 '@media print{#hubNav,#hubNavToggle,#hubNavScrim{display:none!important}body.fs-unified-navigation{margin-left:0!important}}',
 '#hubNavGate{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;z-index:200;background:rgba(7,23,43,.16);backdrop-filter:blur(2px)}',
 '#hubNavGate .card{min-width:260px;max-width:86vw;background:#fff;color:#1b2632;border:1px solid #dce3eb;border-radius:14px;padding:22px 24px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.18)}',
 '#hubNavGate .card p{margin:12px 0 0;font:14px/1.55 system-ui}#hubNavGate .card strong{font-size:15px}',
 '#hubNavGate a.btn{display:inline-block;margin-top:14px;padding:9px 16px;border-radius:9px;background:#1f6f73;color:#fff;text-decoration:none;font:14px system-ui}',
 '#hubNavGate.fade{opacity:0;transition:opacity .25s ease}'
].join('\n');
const navStyle=document.createElement('style');navStyle.id='hubNavInlineStyle';navStyle.textContent=NAV_CSS;document.head.append(navStyle);

/* 页面内容色板仍按原逻辑外链（与导航无关，不阻塞导航渲染） */
for(const name of (styledModule?['fs-tokens.css','fs-ui.css','legacy.css']:['fs-tokens.css'])){const css=document.createElement('link');css.rel='stylesheet';css.href=uiRoot+name;document.head.append(css);}
if(location.pathname.startsWith('/dashboard/tasks/')){const local=document.querySelector('#nav'),main=document.querySelector('main');if(local&&main){local.classList.add('fs-module-nav');local.setAttribute('aria-label','任务视图');main.prepend(local);}}
const moduleStyle=document.createElement('style');moduleStyle.textContent='.fs-ui-page #nav.fs-module-nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px;padding:10px;background:var(--fs-surface,#fff);border:1px solid var(--fs-line,#dce3eb);border-radius:12px}.fs-ui-page #nav.fs-module-nav button{width:auto;color:var(--fs-muted,#596980);background:var(--fs-surface-2,#f7f9fb)}.fs-ui-page #nav.fs-module-nav button.active{color:var(--fs-brand,#1f6f73);background:var(--fs-brand-soft,#e3f0ef)}';document.head.append(moduleStyle);
if(location.pathname.startsWith('/dashboard/game-monitor/')){document.body.dataset.fsModule='monitor';const topStyle=document.createElement('style');topStyle.textContent='.fs-ui-page[data-fs-module=monitor] .topbar{background:var(--fs-surface,#fff);color:var(--fs-text,#1b2632);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=monitor] .topbar *{color:inherit}';document.head.append(topStyle);}
if(['/dashboard/fc27-coins.html','/dashboard/madden27-coins.html'].includes(location.pathname)||location.pathname.startsWith('/tools/fc27-gallery/')){document.body.dataset.fsModule='pricing';const priceStyle=document.createElement('style');priceStyle.textContent='.fs-ui-page[data-fs-module=pricing] .panel>.head,.fs-ui-page[data-fs-module=pricing] .panel>h2{background:var(--fs-surface-2,#f7f9fb);color:var(--fs-text,#1b2632);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=pricing] .controls label,.fs-ui-page[data-fs-module=pricing] .automation-grid>label,.fs-ui-page[data-fs-module=pricing] .switch-card,.fs-ui-page[data-fs-module=pricing] .switch{background:var(--fs-surface-2,#f7f9fb);color:var(--fs-text,#1b2632);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=pricing] .switch-card:has(input:checked){background:var(--fs-ok-soft,#e2f3ec);border-color:var(--fs-ok,#1f7d61)}.fs-ui-page[data-fs-module=pricing] input:not([type=checkbox]),.fs-ui-page[data-fs-module=pricing] select{background:var(--fs-surface,#fff);color:var(--fs-text,#1b2632);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=pricing] .notice{background:var(--fs-surface-2,#f7f9fb);color:var(--fs-text,#1b2632);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=pricing] .notice.success{background:var(--fs-ok-soft,#e2f3ec);color:var(--fs-ok,#1f7d61)}.fs-ui-page[data-fs-module=pricing] .notice.error{background:var(--fs-danger-soft,#fbeae5);color:var(--fs-danger,#a8412c)}.fs-ui-page[data-fs-module=pricing] button{background:var(--fs-brand,#1f6f73);color:var(--fs-brand-on,#fff);border-color:var(--fs-brand,#1f6f73)}.fs-ui-page[data-fs-module=pricing] button.secondary{background:var(--fs-surface,#fff);color:var(--fs-brand,#1f6f73);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=pricing] button.danger{background:var(--fs-danger,#a8412c);color:var(--fs-danger-on,#fff)}';document.head.append(priceStyle);}
const themeScript=document.createElement('script');themeScript.src=uiRoot+'fs-theme.js';document.head.append(themeScript);
if(styledModule)document.body.classList.add('fs-ui-page');document.documentElement.dataset.fsUiVersion='20261019-v3';
if(location.pathname.startsWith('/dashboard/management/')){document.body.dataset.fsModule='management';const polish=document.createElement('style');polish.textContent='.fs-ui-page[data-fs-module=management] .gc{background:var(--fs-surface,#fff);border-color:var(--fs-line,#dce3eb)}.fs-ui-page[data-fs-module=management] .topbar a[href*=sandbox]{background:var(--fs-warn,#825a13);color:var(--fs-warn-on,#fff)}';document.head.append(polish);}

/* ---------- 2. 导航清单内置快照（零网络依赖） ---------- */
const BUILTIN={"schemaVersion":1,"releaseReady":false,"scopeContract":"Existing global portal sessions/current membership only; FC login/register/roles/fallback retired; writes remain existing admins","sections":[{"id":"analytics","title":"数据分析","icon":"▥","intro":"数据看板、运营报告、经营管理与游戏监控。","ids":["unified-business","channel-effects","user-analytics","data-analysis-tools","weekly","management","game-monitor","seo"],"path":"/dashboard/modules/analytics/"},{"id":"brain","title":"Hermes 智体","icon":"◈","intro":"决策报告、持续对话与客单追踪。","ids":["brain","hermes-conversation","customer-tracking"],"path":"/dashboard/modules/hermes/"},{"id":"activities","title":"主站活动区","icon":"◫","intro":"活动转化分析、活动配置与商品编辑预览。","ids":["campaign-analytics","campaign-products"],"path":"/dashboard/analytics/campaigns/analytics/"},{"id":"sports","title":"球类工作区","icon":"◉","intro":"按 FC、MLB、NBA2K、Madden 进入业务工具。","ids":["coins","fc27-bundles","fc27-sbc","ops","players","gallery","odds","mlb","nba","madden","fc27-evolutions"],"path":"/dashboard/modules/sports/"},{"id":"arpg","title":"RPG 工作区","icon":"♜","intro":"D4、PoE2、Aion2 改价与 G2G 自动改价。","ids":["d4","g2g"],"path":"/dashboard/modules/arpg/"},{"id":"sales","title":"销售部系统","icon":"▥","intro":"销售订单、推广人、折扣码与区服分析。","ids":["sales"],"path":"/sales/"},{"id":"marketing","title":"营销系统","icon":"◧","intro":"站内营销配置（新闻详情广告）与邮件营销配置。","ids":["marketing"],"path":"/dashboard/modules/marketing/"},{"id":"bots","title":"机器人管理","icon":"⚙","intro":"GuardBot 防冒充、Shugo-bot 迎新与资讯的统一控制台。","ids":["bot-console"],"path":"/dashboard/modules/bots/"},{"id":"collaboration","title":"协作工具","icon":"▦","intro":"项目任务、团队手册与共享工具。","ids":["tasks","docs","sites","deploy"],"path":"/dashboard/modules/collaboration/"}],"tools":[{"id":"campaign-analytics","label":"活动转化分析","path":"/dashboard/analytics/campaigns/analytics/","icon":"◫","short":"活动漏斗、赛事追踪与商品草稿","ownerId":null,"requiredGroup":"dashboard","section":"activities"},{"id":"user-analytics","label":"用户分析","path":"/dashboard/users/","icon":"◎","short":"购买客户、复购与生命周期；覆盖范围按实际数据展示","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__auth_verify"},{"id":"fc27-sbc","label":"FC27 SBC 上架工具","path":"/dashboard/fc27-sbc/","icon":"▣","short":"SBC / Packs 上架、改价与下架 · 仅管理员操作","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC","serverGuard":"/__auth_verify"},{"id":"channel-effects","label":"渠道效果看板","path":"/dashboard/channel-effects/","icon":"▥","short":"优惠码、优惠券与渠道经营效果 · 按需查询","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"data-analysis-tools","label":"数据分析工具","path":"/dashboard/data-tools/","icon":"▤","short":"独立查询与归档数据","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"unified-business","label":"数据看板","path":"/dashboard/analytics/?mode=business","icon":"▥","short":"经营表现与流量分析，按所选日期查看","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"tasks","label":"项目工作任务台","path":"/dashboard/tasks/","icon":"☑","short":"任务下发、接手确认、自检放行","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"coins","label":"FC27 金币控制台","path":"/dashboard/fc27-coins.html","icon":"◎","short":"竞品、报价与自动化","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"ops","label":"FC27 运营看板","path":"/s/wulv/fc27-ops/","icon":"▥","short":"运营统计与分析 · 独立门禁","ownerId":null,"serverGuard":"/__fc27_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"players","label":"FC27 球员维护","path":"/tools/fc27-players/","icon":"▣","short":"同步、校验与维护 · 独立门禁","ownerId":null,"serverGuard":"/__fc27_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"gallery","label":"FC27 收藏馆调价","path":"/tools/fc27-gallery/","icon":"▧","short":"收藏馆代币与等级服务定价、执行状态","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"mlb","label":"MLB 新卡工作台","path":"/mlb/","icon":"◇","short":"新卡上架业务工具","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"MLB"},{"id":"nba","label":"NBA2K 自动改价台","path":"/nba2k27/","icon":"◉","short":"报价与现行浏览器自动化控制","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"NBA2K"},{"id":"d4","label":"RPG 游戏改价系统","path":"/d4/","icon":"♜","short":"D4 / PoE2 / Aion2 共用控制台，进入后选择游戏","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"arpg","requiredGroup":"dashboard"},{"id":"docs","label":"部门手册","path":"/docs/","icon":"▤","short":"现有团队文档入口","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"sites","label":"团队工具目录","path":"/s/","icon":"▦","short":"现有共享业务站点","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"deploy","label":"现有部署工作台","path":"/deploy/","icon":"↥","short":"现有发布入口 · deploy组","ownerId":null,"requiredGroup":"deploy","serverGuard":"/__auth_verify_deploy","scope":"global-portal","section":"collaboration"},{"id":"weekly","label":"运营报告","path":"/dashboard/fs-home/brain/index.html?report_kind=weekly#reports","icon":"▤","short":"Hermes 日报、周报、月报与报告历史","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"madden","label":"Madden 金币看板","path":"/dashboard/madden27-coins.html","icon":"◎","short":"既有金币看板","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"Madden"},{"id":"odds","label":"FC26 库存与交付（历史工具）","path":"/s/wulv/fc-odds/","icon":"◈","short":"历史业务工具，仅按现有用途使用","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"game-monitor","label":"游戏监控台","short":"全球新游上线 · 版本赛季 · 开服节点一屏追踪","icon":"◉","path":"/dashboard/game-monitor/","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"management","label":"经营管理台","short":"三组进度 · 健康度责任到人 · 目标沙盘与经营决策","icon":"▦","path":"/dashboard/management/","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"brain","label":"智体决策报告","short":"任务、经营判断与日报周报月报","icon":"◈","path":"/dashboard/fs-home/brain/index.html","section":"brain","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"fc27-bundles","label":"FC27 捆绑包改价","path":"/dashboard/modules/sports/bundles/","icon":"↗","short":"捆绑包配置、定价预览与现有后台改价功能","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC"},{"id":"g2g","label":"G2G 自动改价","path":"/g2g/","icon":"↗","short":"AION2 Kinah · 使用原 G2G 控制台与原改价护栏","section":"arpg","scope":"global-portal","requiredGroup":"dashboard"},{"id":"sales","label":"销售部系统","path":"/sales/","icon":"▥","short":"Aion2 销售数据看板 · 渠道、销量与趋势","section":"sales","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__auth_verify"},{"id":"bot-console","label":"Discord 机器人控制台","path":"/bots/","icon":"↗","short":"GuardBot 防冒充、Shugo-bot 迎新与资讯；按原权限管理","section":"bots","scope":"global-portal","requiredGroup":"dashboard"},{"id":"hermes-conversation","section":"brain","scope":"global-portal","requiredGroup":"dashboard","icon":"◈","label":"持续对话","path":"/dashboard/fs-home/hermes/conversation/","short":"延续上下文，讨论问题与调查结果"},{"id":"customer-tracking","section":"brain","scope":"global-portal","requiredGroup":"dashboard","icon":"◈","label":"智体客单追踪","path":"/dashboard/fs-home/hermes/customer-tracking/","short":"按日期区间筛选候选，查看持续观察与维护建议"},{"id":"fc27-evolutions","label":"FC27 进化商品改价","path":"/dashboard/fc27-evolutions/","icon":"↗","short":"Evolutions 模型金币数、平台B2C与单品设置","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC","serverGuard":"/__auth_verify"},{"id":"campaign-products","label":"商品编辑与预览","path":"/dashboard/analytics/campaigns/analytics/products.html","icon":"▣","short":"维护活动商品组合、保存服务器草稿并预览","requiredGroup":"dashboard","section":"activities"},{"id":"marketing","label":"营销系统","path":"/dashboard/modules/marketing/","icon":"◧","short":"新闻详情广告配置 · 商店入口 / 广告图 · 需本机执行服务在运行","ownerId":null,"section":"marketing","scope":"global-portal","requiredGroup":"dashboard"},{"id":"seo","label":"SEO监控台","path":"/dashboard/analytics/seo/","icon":"▥","short":"四游戏昨日固定数据与成交预估","scope":"global-portal","section":"analytics","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"}],"analyticsContract":{"status":"BLOCKED_SECURITY_REVIEW_REAL_ROLE_ACCEPTANCE","legacyBusiness":"/dashboard/index.html","legacyGoogle":"/dashboard/marketing/","unifiedPath":"/dashboard/analytics/?mode=business","googlePath":"/dashboard/analytics/?mode=google","retiredDisplayEntries":["/dashboard/index.html","/dashboard/marketing/"],"sharedDataServicesRetained":true}};

function showGate(html){let g=document.getElementById('hubNavGate');if(!g){g=document.createElement('div');g.id='hubNavGate';document.body.append(g);}g.classList.remove('fade');g.innerHTML='<div class="card">'+html+'</div>';}
function closeGate(){const g=document.getElementById('hubNavGate');if(!g)return;g.classList.add('fade');setTimeout(()=>{try{g.remove()}catch{}},280);}

function readJSON(key){try{return JSON.parse(sessionStorage.getItem(key));}catch{return null;}}
function writeJSON(key,v){try{sessionStorage.setItem(key,JSON.stringify(v));}catch{}}

let currentUser=null,registry=null,stopped=false;
function cachedIdentity(){const c=readJSON(ID_CACHE);return (c&&c.user&&c.user.name)?c.user:null;}
function cachedRegistryData(){const c=readJSON(REG_CACHE);return (c&&c.reg&&Array.isArray(c.reg.sections))?c.reg:null;}
async function fetchIdentity(){const r=await fetch('/__auth/verify',{credentials:'same-origin',cache:'no-store',redirect:'manual',signal:AbortSignal.timeout(10000)});if(r.status!==200||r.redirected){throw Error('identity_unavailable');}const user={name:r.headers.get('X-Auth-User'),role:r.headers.get('X-Auth-Role'),groups:(r.headers.get('X-Auth-Groups')||'').split(',').map(x=>x.trim()).filter(Boolean)};writeJSON(ID_CACHE,{ts:Date.now(),user});return user;}
async function fetchRegistryData(){const r=await fetch('/dashboard/fs-home/navigation.json',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:AbortSignal.timeout(10000)});if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('registry_unavailable');const reg=await r.json();if(reg.schemaVersion!==1||!Array.isArray(reg.sections)||!Array.isArray(reg.tools))throw Error('registry_invalid');writeJSON(REG_CACHE,{ts:Date.now(),reg});return reg;}
function makeTools(reg){return reg.tools.filter(t=>safe(t.path)).map(t=>({...t,available:true}));}

const nav=document.createElement('nav');nav.id='hubNav';nav.setAttribute('aria-label','FS 统一导航');
const tree=document.createElement('div');
const toggle=document.createElement('button');toggle.id='hubNavToggle';toggle.type='button';toggle.textContent='☰ 导航';toggle.setAttribute('aria-controls','hubNav');toggle.setAttribute('aria-expanded','false');
const scrim=document.createElement('button');scrim.id='hubNavScrim';scrim.type='button';scrim.hidden=true;scrim.setAttribute('aria-label','关闭导航');
function close(){nav.classList.remove('open');nav.inert=innerWidth<900;scrim.hidden=true;toggle.setAttribute('aria-expanded','false');}
nav.inert=innerWidth<900;
toggle.onclick=()=>{const open=nav.classList.toggle('open');nav.inert=!open;scrim.hidden=!open;toggle.setAttribute('aria-expanded',String(open));if(open)nav.querySelector('a')?.focus();};scrim.onclick=()=>{close();toggle.focus();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&nav.classList.contains('open')){close();toggle.focus();}});
addEventListener('resize',()=>{if(innerWidth>=900)close();else nav.inert=!nav.classList.contains('open');});
function element(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function safe(path){return typeof path==='string'&&/^\/(?!\/)[a-zA-Z0-9_./-]+(?:\?(?:mode=(?:business|google)|report_kind=(?:daily|weekly|monthly)(?:#reports)?))?$/.test(path)&&!path.split('?')[0].split('/').includes('..');}
function link(label,path,cls){const a=element('a',label,cls);a.href=path;a.onclick=close;return a;}
nav.append(link('FS · MMOEXP','/dashboard/','hn-brand'),tree);

// Homepage shortcut cards share the native card structure and existing permission probes.
let homeCardsObserver=null;
function clearHomeCards(){homeCardsObserver?.disconnect();homeCardsObserver=null;document.querySelectorAll('[data-fs-home-shortcut]').forEach(e=>e.remove());}
function mountHomeCards(user,tools){
 clearHomeCards();
 if(!['/dashboard/','/dashboard/fs-home/index.html'].includes(location.pathname))return;
 const grid=document.getElementById('workspaces');if(!grid)return;
 function place(){
  if(stopped||currentUser?.name!==user.name)return;
  let after=grid.querySelector('.workspace-card.marketing')||grid.querySelector('.workspace-card.arpg');if(!after)return;
  for(const id of ['management','game-monitor']){
   const tool=tools.find(t=>t.id===id);if(!tool?.available)continue;
   let card=grid.querySelector('[data-fs-home-shortcut="'+id+'"]');
   if(!card){card=element('article',null,'workspace-card '+id);card.dataset.fsHomeShortcut=id;const a=link('',tool.path,'workspace-main');
    a.append(element('span',id==='management'?'◎':'◷','workspace-icon'),element('h3',id==='management'?'经营管理台':'游戏监控台'),element('p',id==='management'?'三组进度 · 健康度责任到人 · 目标沙盘与经营决策':'全球新游上线 · 版本赛季 · 开服节点一屏追踪'),element('span','进入工作区 →','entry'));card.append(a);}
   if(after.nextElementSibling!==card)after.after(card);after=card;
  }
 }
 place();homeCardsObserver=new MutationObserver(place);homeCardsObserver.observe(grid,{childList:true});
}

function matches(path){const url=new URL(path,location.origin),current=new URL(location.href);if(Array.from(url.searchParams).some(([key,value])=>current.searchParams.get(key)!==value))return false;return current.pathname===url.pathname||(url.pathname.endsWith('/')&&current.pathname.startsWith(url.pathname));}

/* 同步渲染：无 await、无网络、无占位文案 */
function render(user,tools,reg){
 const data=reg||registry||BUILTIN;if(!data)return;
 const homeLink=link('首页','/dashboard/','hn-home');if(['/dashboard/','/dashboard/fs-home/index.html'].includes(location.pathname))homeLink.setAttribute('aria-current','page');
 const frag=document.createDocumentFragment();frag.append(homeLink);
 for(const section of data.sections.filter(s=>!['game-monitor','management'].includes(s.id))){
  if(!safe(section.path))continue;
  const rows=(section.ids||[]).map(id=>tools.find(t=>t.id===id)).filter(Boolean);const currentRow=rows.filter(t=>matches(t.path)).sort((a,b)=>b.path.length-a.path.length)[0];
  const group=element('section',null,'hn-group'),heading=link(section.title,section.path,'hn-heading');
  if(matches(section.path)||rows.some(t=>matches(t.path)))heading.setAttribute('aria-current','true');
  heading.replaceChildren(element('span',section.icon||'◈','hn-icon'),element('span',section.title));
  group.append(heading);
  if(section.id==='analytics'||section.id==='brain'||section.id==='activities')for(const t of rows){const a=link(t.label,t.path,'hn-tool');if(currentRow===t)a.setAttribute('aria-current','page');group.append(a);}
  frag.append(group);
 }
 if(user&&user.name){const account=element('div',null,'hn-account');account.append(link(user.name,'/__auth/status'));if(user.role==='admin')account.append(link('账号与权限管理','/__auth/access/'));frag.append(account);}
 const themeLabel=element('label','显示主题','hn-theme'),selector=element('select');selector.dataset.fsThemeControl='';selector.setAttribute('aria-label','全站显示主题');
 for(const [v,t] of [['light','浅色'],['dark','深色'],['system','跟随系统']]){const o=element('option',t);o.value=v;selector.append(o);}
 let remembered='light';try{remembered=localStorage.getItem('fs-navigation-theme')||remembered;}catch{}selector.value=window.FSTheme?.get()||remembered;selector.onchange=()=>window.FSTheme?.set(selector.value);themeLabel.append(selector);frag.append(themeLabel);
 tree.replaceChildren(frag);document.dispatchEvent(new CustomEvent('fs-nav-account-ready',{detail:{account:tree.querySelector('.hn-account')}}));
 if(!document.getElementById('hubNav')){document.body.prepend(nav,toggle,scrim);document.body.classList.add('fs-unified-navigation');}
 if(user&&user.name)mountHomeCards(user,tools);
}
function denied(){
 clearHomeCards();currentUser=null;
 const next=encodeURIComponent(location.pathname+location.search);
 showGate('<p><strong>登录或访问范围未确认</strong></p><p>业务入口已清除，请重新登录后重试。</p><a class="btn" href="/__auth/login?next='+next+'">重新登录</a>');
}

/* 首帧：立刻渲染（缓存优先 → 内置快照兜底），完全不等待网络 */
(function firstPaint(){
 const cu=cachedIdentity(),cr=cachedRegistryData();
 registry=cr||BUILTIN;
 currentUser=cu;
 render(cu,makeTools(registry));
})();

/* 后台静默校准：身份 + 清单，不打断、不遮挡 */
async function refresh(){
 if(stopped)return;
 const prev=currentUser;
 try{
  const c=readJSON(ID_CACHE);
  const user=(c&&c.user&&c.user.name&&Date.now()-c.ts<ID_TTL)?c.user:await fetchIdentity();
  if(stopped)return;
  // 控制台的准入由服务端按 admin/manage 判，不要求 dashboard 组；
  // 这里再按组拦一次，会让「有授权但不在 dashboard 组」的管理员被整屏遮住。
  if(!user.name||(!IAM_PAGE&&!user.groups.includes('dashboard'))){if(!prev){denied();}return;}
  const rc=readJSON(REG_CACHE);
  const reg=(rc&&rc.reg&&Date.now()-rc.ts<REG_TTL)?null:await fetchRegistryData().catch(()=>null);
  const changedUser=!prev||user.name!==prev.name||user.role!==prev.role||JSON.stringify(user.groups)!==JSON.stringify(prev.groups);
  const changedReg=!!reg&&JSON.stringify(reg)!==JSON.stringify(registry);
  if(stopped)return;
  if(changedUser||changedReg){currentUser=user;if(reg)registry=reg;render(user,makeTools(registry));}
  else currentUser=user;
 }catch{/* 网络波动：保留已渲染导航 */}
}
refresh();
function watch(){return setInterval(async()=>{if(document.hidden||!currentUser)return;try{const user=await fetchIdentity();if(!user.name||(!IAM_PAGE&&!user.groups.includes('dashboard'))){denied();return;}if(user.name!==currentUser.name||user.role!==currentUser.role||JSON.stringify(user.groups)!==JSON.stringify(currentUser.groups)){currentUser=user;render(user,makeTools(registry));}}catch{/* 保留现状 */}},60000);}
let timer=watch();
addEventListener('pagehide',()=>{stopped=true;clearInterval(timer);homeCardsObserver?.disconnect();});
addEventListener('pageshow',e=>{if(e.persisted){stopped=false;clearInterval(timer);timer=watch();refresh();}});
})();

(function(){if(document.getElementById('fsNavExperienceStyle'))return;const s=document.createElement('style');s.id='fsNavExperienceStyle';s.textContent="/* Shared navigation experience. Business content keeps its own layout. */\n@view-transition{navigation:auto}\nhtml{scrollbar-gutter:stable}\nhtml[data-fs-nav-ready] #hubNav{view-transition-name:fs-navigation}\n::view-transition-group(fs-navigation){animation-duration:180ms}\n::view-transition-old(root){animation:fs-page-out 140ms ease both}\n::view-transition-new(root){animation:fs-page-in 220ms cubic-bezier(.2,.7,.2,1) both}\n@keyframes fs-page-out{to{opacity:0}}\n@keyframes fs-page-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}\nhtml[data-fs-nav-ready]{--fs-nav-width:248px}\nbody.fs-unified-navigation{margin-left:var(--fs-nav-width,248px)!important}\nbody.fs-unified-navigation .topbar{left:var(--fs-nav-width,248px)}\n#hubNav.fs-nav-v4{--n-surface:#fff;--n-surface2:#f3f7f7;--n-text:#21383d;--n-muted:#62787d;--n-line:#e0e9e9;--n-brand:#176b70;--n-brand-soft:#e7f3f1;--n-focus:#137a82;box-sizing:border-box;position:fixed;inset:0 auto 0 0;width:var(--fs-nav-width,248px);display:flex!important;flex-direction:column;gap:8px;padding:18px 12px 12px;overflow:hidden;background:var(--n-surface);border-right:1px solid var(--n-line);color:var(--n-text);z-index:80;font:13px/1.5 system-ui,'Microsoft YaHei',sans-serif;box-shadow:3px 0 20px #17383b05}\nhtml[data-fs-theme=dark] #hubNav.fs-nav-v4{--n-surface:#112327;--n-surface2:#183035;--n-text:#e1eeee;--n-muted:#a1b8bc;--n-line:#2b4449;--n-brand:#8cdbce;--n-brand-soft:#203e40;--n-focus:#8cdbce}\n#hubNav.fs-nav-v4 *{box-sizing:border-box}\n#hubNav.fs-nav-v4 button,#hubNav.fs-nav-v4 input{font:inherit}\n#hubNav.fs-nav-v4 button{cursor:pointer}\n#hubNav.fs-nav-v4 a{color:inherit;text-decoration:none}\n#hubNav.fs-nav-v4 .hn-brand{display:flex;align-items:center;gap:10px;flex-shrink:0;font-size:16px;letter-spacing:-.3px;font-weight:750;padding:5px 8px 14px}\n#hubNav.fs-nav-v4 .hn-brand::before{content:'F';display:grid;place-items:center;width:30px;height:30px;flex:0 0 30px;border-radius:10px 10px 10px 3px;color:#fff;background:#176b70;font-size:19px}\n#hubNav.fs-nav-v4 .hn-search-box{position:relative;flex-shrink:0}\n#hubNav.fs-nav-v4 .hn-search{width:100%;height:36px;border:1px solid var(--n-line);border-radius:9px;background:var(--n-surface2);color:var(--n-text);padding:7px 48px 7px 11px;outline:none}\n#hubNav.fs-nav-v4 .hn-search-box kbd{position:absolute;right:9px;top:10px;font:10px system-ui;color:var(--n-muted);pointer-events:none}\n#hubNav.fs-nav-v4 .hn-tree{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--n-line) transparent;padding:2px 0 12px}\n#hubNav.fs-nav-v4 .hn-home{display:block;padding:10px 12px;margin-bottom:10px;border-radius:9px;font-weight:650}\n#hubNav.fs-nav-v4 .hn-group{margin:3px 0;padding:0;border:0}\n#hubNav.fs-nav-v4 .hn-row{display:flex;align-items:center;gap:2px;border-radius:9px}\n#hubNav.fs-nav-v4 .hn-heading{display:flex;align-items:center;gap:10px;flex:1;min-width:0;margin:0;padding:10px;border:0;background:none;font-weight:600;font-size:13px;border-radius:9px}\n#hubNav.fs-nav-v4 .hn-icon{font-size:17px;flex:0 0 22px;width:22px;text-align:center;color:var(--n-brand)}\n#hubNav.fs-nav-v4 .hn-expander{width:28px;height:30px;padding:0;border:0;border-radius:7px;color:var(--n-muted);background:transparent;flex-shrink:0;box-shadow:none}\n#hubNav.fs-nav-v4 .hn-expander span{display:inline-block;transition:transform 180ms ease}\n#hubNav.fs-nav-v4 .hn-expander[aria-expanded=true] span{transform:rotate(90deg)}\n#hubNav.fs-nav-v4 .hn-children{display:grid;grid-template-rows:0fr;transition:grid-template-rows 200ms cubic-bezier(.2,.7,.2,1);visibility:hidden}\n#hubNav.fs-nav-v4 .hn-group[data-open=true] .hn-children{grid-template-rows:1fr;visibility:visible}\n#hubNav.fs-nav-v4 .hn-children-inner{min-height:0;overflow:hidden}\n#hubNav.fs-nav-v4 .hn-tool{display:block;margin:2px 5px 2px 21px;padding:8px 10px 8px 20px;border:0;border-left:1px solid var(--n-line);border-radius:0 7px 7px 0;font-size:12px;color:var(--n-muted);line-height:1.5}\n#hubNav.fs-nav-v4 a:hover,#hubNav.fs-nav-v4 button:hover{background:var(--n-surface2);color:var(--n-brand)}\n#hubNav.fs-nav-v4 a[aria-current=page]{background:var(--n-brand-soft);color:var(--n-brand);font-weight:700;box-shadow:inset 3px 0 var(--n-brand)}\n#hubNav.fs-nav-v4 .hn-heading[aria-current=true]{color:var(--n-brand);background:none}\n#hubNav.fs-nav-v4 :is(a,button,input,select):focus-visible{outline:2px solid var(--n-focus);outline-offset:-2px}\n#hubNav.fs-nav-v4 .hn-footer{border-top:1px solid var(--n-line);padding-top:9px;flex-shrink:0;display:flex;align-items:center;gap:5px}\n#hubNav.fs-nav-v4 .hn-account{border:0;margin:0;padding:0;flex:1;font-size:11px;min-height:35px}\n#hubNav.fs-nav-v4 .hn-account a{display:block;padding:3px 8px;border-radius:6px}\n#hubNav.fs-nav-v4 .hn-collapse{height:32px;width:32px;flex:0 0 32px;background:var(--n-surface2);color:var(--n-muted);border:1px solid var(--n-line);border-radius:8px}\n#hubNav.fs-nav-v4 .hn-theme{margin:0;padding:7px 8px;display:flex;align-items:center;gap:6px;font-size:11px;color:var(--n-muted)}\n#hubNav.fs-nav-v4 .hn-theme select{min-width:0;flex:1;padding:4px;background:var(--n-surface2);border:1px solid var(--n-line);border-radius:6px;color:var(--n-text);font:inherit}\n#hubNav.fs-nav-v4 .hn-empty{font-size:12px;color:var(--n-muted);padding:12px;line-height:1.8}\n#hubNav.fs-nav-v4 [hidden]{display:none!important}\n#hubNav.fs-nav-v4 .hn-status{display:none}\nbody.fs-unified-navigation #content-panel:empty{min-height:420px;border-radius:14px;background:linear-gradient(var(--fs-surface,#fff),var(--fs-surface,#fff)) 0 100px/100% 130px no-repeat}\nbody.fs-unified-navigation main{min-width:0}\nhtml[data-fs-nav-page=campaign] body.fs-unified-navigation main{margin-left:0!important}\n@media(min-width:900px){html[data-fs-nav-compact=true]{--fs-nav-width:72px}html[data-fs-nav-compact=true] #hubNav.fs-nav-v4{padding-inline:10px}html[data-fs-nav-compact=true] #hubNav .hn-brand{font-size:0;padding-inline:9px}html[data-fs-nav-compact=true] #hubNav :is(.hn-heading>span:not(.hn-icon),.hn-expander,.hn-children,.hn-search-box,.hn-theme,.hn-account){display:none!important}html[data-fs-nav-compact=true] #hubNav .hn-home{font-size:0;text-align:center;padding:10px 0}html[data-fs-nav-compact=true] #hubNav .hn-home::before{content:'⌂';font-size:24px}html[data-fs-nav-compact=true] #hubNav .hn-heading{justify-content:center;padding:12px 0}html[data-fs-nav-compact=true] #hubNav .hn-footer{justify-content:center}}\n@media(max-width:899px){body.fs-unified-navigation{margin-left:0!important;padding-top:50px!important}body.fs-unified-navigation .topbar{left:0}#hubNav.fs-nav-v4{width:min(288px,86vw);padding-top:55px;transform:translateX(-100%);transition:transform 200ms ease}#hubNav.fs-nav-v4.open{transform:none}#hubNav.fs-nav-v4 .hn-collapse{display:none}body.fs-unified-navigation #hubNavToggle{display:block!important;position:fixed;top:9px;left:12px;z-index:81;border:1px solid #b9cccd;border-radius:8px;background:var(--fs-surface,#fff);color:var(--fs-text,#21383d);padding:7px 12px}body.fs-unified-navigation #hubNavScrim:not([hidden]){display:block!important;position:fixed;inset:0;z-index:79;background:#071e2866;border:0;width:100%;height:100%}}\n@media(prefers-reduced-motion:reduce){@view-transition{navigation:none}::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation:none!important}#hubNav.fs-nav-v4 *{transition:none!important}}\n@media print{#hubNav.fs-nav-v4,#hubNavToggle,#hubNavScrim{display:none!important}body.fs-unified-navigation{margin-left:0!important}}\n";document.head.append(s);})();
/* Progressive enhancement shared by static and dynamic navigation. No business APIs. */
(function start(){
 'use strict';
 if(window.parent!==window||window.__fsNavExperience)return;
 const nav=document.getElementById('hubNav');if(!nav){document.addEventListener('DOMContentLoaded',start,{once:true});return;}
 window.__fsNavExperience=true;
 const registry={"schemaVersion":1,"releaseReady":false,"scopeContract":"Existing global portal sessions/current membership only; FC login/register/roles/fallback retired; writes remain existing admins","sections":[{"id":"analytics","title":"数据分析","icon":"▥","intro":"数据看板、运营报告、经营管理与游戏监控。","ids":["unified-business","channel-effects","user-analytics","data-analysis-tools","weekly","management","game-monitor","seo"],"path":"/dashboard/modules/analytics/"},{"id":"brain","title":"Hermes 智体","icon":"◈","intro":"决策报告、持续对话与客单追踪。","ids":["brain","hermes-conversation","customer-tracking"],"path":"/dashboard/modules/hermes/"},{"id":"activities","title":"主站活动区","icon":"◫","intro":"活动转化分析、活动配置与商品编辑预览。","ids":["campaign-analytics","campaign-products"],"path":"/dashboard/analytics/campaigns/analytics/"},{"id":"sports","title":"球类工作区","icon":"◉","intro":"按 FC、MLB、NBA2K、Madden 进入业务工具。","ids":["coins","fc27-bundles","fc27-sbc","ops","players","gallery","odds","mlb","nba","madden","fc27-evolutions"],"path":"/dashboard/modules/sports/"},{"id":"arpg","title":"RPG 工作区","icon":"♜","intro":"D4、PoE2、Aion2 改价与 G2G 自动改价。","ids":["d4","g2g"],"path":"/dashboard/modules/arpg/"},{"id":"sales","title":"销售部系统","icon":"▥","intro":"销售订单、推广人、折扣码与区服分析。","ids":["sales"],"path":"/sales/"},{"id":"marketing","title":"营销系统","icon":"◧","intro":"站内营销配置（新闻详情广告）与邮件营销配置。","ids":["marketing"],"path":"/dashboard/modules/marketing/"},{"id":"bots","title":"机器人管理","icon":"⚙","intro":"GuardBot 防冒充、Shugo-bot 迎新与资讯的统一控制台。","ids":["bot-console"],"path":"/dashboard/modules/bots/"},{"id":"collaboration","title":"协作工具","icon":"▦","intro":"项目任务、团队手册与共享工具。","ids":["tasks","docs","sites","deploy"],"path":"/dashboard/modules/collaboration/"}],"tools":[{"id":"campaign-analytics","label":"活动转化分析","path":"/dashboard/analytics/campaigns/analytics/","icon":"◫","short":"活动漏斗、赛事追踪与商品草稿","ownerId":null,"requiredGroup":"dashboard","section":"activities"},{"id":"user-analytics","label":"用户分析","path":"/dashboard/users/","icon":"◎","short":"购买客户、复购与生命周期；覆盖范围按实际数据展示","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__auth_verify"},{"id":"fc27-sbc","label":"FC27 SBC 上架工具","path":"/dashboard/fc27-sbc/","icon":"▣","short":"SBC / Packs 上架、改价与下架 · 仅管理员操作","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC","serverGuard":"/__auth_verify"},{"id":"channel-effects","label":"渠道效果看板","path":"/dashboard/channel-effects/","icon":"▥","short":"优惠码、优惠券与渠道经营效果 · 按需查询","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"data-analysis-tools","label":"数据分析工具","path":"/dashboard/data-tools/","icon":"▤","short":"独立查询与归档数据","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"unified-business","label":"数据看板","path":"/dashboard/analytics/?mode=business","icon":"▥","short":"经营表现与流量分析，按所选日期查看","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"tasks","label":"项目工作任务台","path":"/dashboard/tasks/","icon":"☑","short":"任务下发、接手确认、自检放行","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"coins","label":"FC27 金币控制台","path":"/dashboard/fc27-coins.html","icon":"◎","short":"竞品、报价与自动化","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"ops","label":"FC27 运营看板","path":"/s/wulv/fc27-ops/","icon":"▥","short":"运营统计与分析 · 独立门禁","ownerId":null,"serverGuard":"/__fc27_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"players","label":"FC27 球员维护","path":"/tools/fc27-players/","icon":"▣","short":"同步、校验与维护 · 独立门禁","ownerId":null,"serverGuard":"/__fc27_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"gallery","label":"FC27 收藏馆调价","path":"/tools/fc27-gallery/","icon":"▧","short":"收藏馆代币与等级服务定价、执行状态","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"mlb","label":"MLB 新卡工作台","path":"/mlb/","icon":"◇","short":"新卡上架业务工具","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"MLB"},{"id":"nba","label":"NBA2K 自动改价台","path":"/nba2k27/","icon":"◉","short":"报价与现行浏览器自动化控制","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"NBA2K"},{"id":"d4","label":"RPG 游戏改价系统","path":"/d4/","icon":"♜","short":"D4 / PoE2 / Aion2 共用控制台，进入后选择游戏","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"arpg","requiredGroup":"dashboard"},{"id":"docs","label":"部门手册","path":"/docs/","icon":"▤","short":"现有团队文档入口","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"sites","label":"团队工具目录","path":"/s/","icon":"▦","short":"现有共享业务站点","ownerId":null,"serverGuard":"/__auth_verify","scope":"global-portal","section":"collaboration","requiredGroup":"dashboard"},{"id":"deploy","label":"现有部署工作台","path":"/deploy/","icon":"↥","short":"现有发布入口 · deploy组","ownerId":null,"requiredGroup":"deploy","serverGuard":"/__auth_verify_deploy","scope":"global-portal","section":"collaboration"},{"id":"weekly","label":"运营报告","path":"/dashboard/fs-home/brain/index.html?report_kind=weekly#reports","icon":"▤","short":"Hermes 日报、周报、月报与报告历史","scope":"global-portal","section":"analytics","requiredGroup":"dashboard"},{"id":"madden","label":"Madden 金币看板","path":"/dashboard/madden27-coins.html","icon":"◎","short":"既有金币看板","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"Madden"},{"id":"odds","label":"FC26 库存与交付（历史工具）","path":"/s/wulv/fc-odds/","icon":"◈","short":"历史业务工具，仅按现有用途使用","scope":"global-portal","section":"sports","requiredGroup":"dashboard","category":"FC"},{"id":"game-monitor","label":"游戏监控台","short":"全球新游上线 · 版本赛季 · 开服节点一屏追踪","icon":"◉","path":"/dashboard/game-monitor/","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"management","label":"经营管理台","short":"三组进度 · 健康度责任到人 · 目标沙盘与经营决策","icon":"▦","path":"/dashboard/management/","section":"analytics","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"brain","label":"智体决策报告","short":"任务、经营判断与日报周报月报","icon":"◈","path":"/dashboard/fs-home/brain/index.html","section":"brain","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"},{"id":"fc27-bundles","label":"FC27 捆绑包改价","path":"/dashboard/modules/sports/bundles/","icon":"↗","short":"捆绑包配置、定价预览与现有后台改价功能","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC"},{"id":"g2g","label":"G2G 自动改价","path":"/g2g/","icon":"↗","short":"AION2 Kinah · 使用原 G2G 控制台与原改价护栏","section":"arpg","scope":"global-portal","requiredGroup":"dashboard"},{"id":"sales","label":"销售部系统","path":"/sales/","icon":"▥","short":"Aion2 销售数据看板 · 渠道、销量与趋势","section":"sales","scope":"global-portal","requiredGroup":"dashboard","serverGuard":"/__auth_verify"},{"id":"bot-console","label":"Discord 机器人控制台","path":"/bots/","icon":"↗","short":"GuardBot 防冒充、Shugo-bot 迎新与资讯；按原权限管理","section":"bots","scope":"global-portal","requiredGroup":"dashboard"},{"id":"hermes-conversation","section":"brain","scope":"global-portal","requiredGroup":"dashboard","icon":"◈","label":"持续对话","path":"/dashboard/fs-home/hermes/conversation/","short":"延续上下文，讨论问题与调查结果"},{"id":"customer-tracking","section":"brain","scope":"global-portal","requiredGroup":"dashboard","icon":"◈","label":"智体客单追踪","path":"/dashboard/fs-home/hermes/customer-tracking/","short":"按日期区间筛选候选，查看持续观察与维护建议"},{"id":"fc27-evolutions","label":"FC27 进化商品改价","path":"/dashboard/fc27-evolutions/","icon":"↗","short":"Evolutions 模型金币数、平台B2C与单品设置","section":"sports","scope":"global-portal","requiredGroup":"dashboard","category":"FC","serverGuard":"/__auth_verify"},{"id":"campaign-products","label":"商品编辑与预览","path":"/dashboard/analytics/campaigns/analytics/products.html","icon":"▣","short":"维护活动商品组合、保存服务器草稿并预览","requiredGroup":"dashboard","section":"activities"},{"id":"marketing","label":"营销系统","path":"/dashboard/modules/marketing/","icon":"◧","short":"新闻详情广告配置 · 商店入口 / 广告图 · 需本机执行服务在运行","ownerId":null,"section":"marketing","scope":"global-portal","requiredGroup":"dashboard"},{"id":"seo","label":"SEO监控台","path":"/dashboard/analytics/seo/","icon":"▥","short":"四游戏昨日固定数据与成交预估","scope":"global-portal","section":"analytics","requiredGroup":"dashboard","serverGuard":"/__nav_formal_native_session"}],"analyticsContract":{"status":"BLOCKED_SECURITY_REVIEW_REAL_ROLE_ACCEPTANCE","legacyBusiness":"/dashboard/index.html","legacyGoogle":"/dashboard/marketing/","unifiedPath":"/dashboard/analytics/?mode=business","googlePath":"/dashboard/analytics/?mode=google","retiredDisplayEntries":["/dashboard/index.html","/dashboard/marketing/"],"sharedDataServicesRetained":true}};
 const root=document.documentElement,KEY='fs-nav-experience-v4';
 let saved={};try{saved=JSON.parse(sessionStorage.getItem(KEY)||'{}')||{};}catch{}
 const persist=()=>{try{sessionStorage.setItem(KEY,JSON.stringify(saved));}catch{}};
 root.dataset.fsNavReady='20261103';root.dataset.fsNavCompact=String(saved.compact===true);
 if(location.pathname.startsWith('/dashboard/analytics/campaigns/analytics/'))root.dataset.fsNavPage='campaign';
 nav.classList.add('fs-nav-v4');
 function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;}
 function valid(path){return typeof path==='string'&&path.startsWith('/')&&!path.startsWith('//')&&!path.includes('..');}
 function matches(path){const u=new URL(path,location.origin),c=new URL(location.href);return c.pathname===u.pathname&&[...u.searchParams].every(([k,v])=>c.searchParams.get(k)===v);}
 let query='',building=false,scheduled=false,tree,search;
 function setOpen(group,open){group.dataset.open=String(open);const button=group.querySelector('.hn-expander'),panel=group.querySelector('.hn-children');button?.setAttribute('aria-expanded',String(open));if(panel)panel.inert=!open;}
 function filter(){
  const q=query.trim().toLowerCase();let count=0;
  nav.querySelectorAll('.hn-group').forEach(g=>{
   const title=g.querySelector('.hn-heading').textContent.toLowerCase();let hits=0;
   g.querySelectorAll('.hn-tool').forEach(a=>{a.hidden=!!q&&!title.includes(q)&&!a.textContent.toLowerCase().includes(q);if(!a.hidden)hits++;});
   g.hidden=!!q&&!hits;count+=g.hidden?0:1;
   setOpen(g,q?hits>0:g.dataset.key===saved.open);
  });
  const empty=nav.querySelector('.hn-empty');if(empty)empty.hidden=count>0;
 }
 function build(){
  if(building)return;building=true;
  try{
   // Keep current server-provided account/permission links and theme control.
   const account=nav.querySelector('.hn-account'),theme=nav.querySelector('.hn-theme');
   const brand=nav.querySelector('.hn-brand')||el('a','hn-brand','FS · MMOEXP');brand.href='/dashboard/';
   const links=new Map([...nav.querySelectorAll('a[href]')].map(a=>[a.getAttribute('href'),a]));
   const fragment=document.createDocumentFragment();fragment.append(brand);
   const box=el('div','hn-search-box');search=el('input','hn-search');search.type='search';search.placeholder='搜索工作区或工具';search.setAttribute('aria-label','搜索导航');search.value=query;
   search.addEventListener('input',()=>{query=search.value;filter();});
   search.addEventListener('keydown',e=>{if(e.key==='Escape'){query='';search.value='';filter();e.stopPropagation();}if(e.key==='ArrowDown'){e.preventDefault();nav.querySelector('.hn-group:not([hidden]) .hn-tool:not([hidden])')?.focus();}});
   box.append(search,el('kbd','', 'Ctrl K'));fragment.append(box);
   tree=el('div','hn-tree');const home=el('a','hn-home','首页');home.href='/dashboard/';home.title='首页';if(matches('/dashboard/'))home.setAttribute('aria-current','page');tree.append(home);
   const all=registry.sections.filter(s=>valid(s.path));
   const active=all.find(s=>matches(s.path))||all.find(s=>s.ids.some(id=>{const t=registry.tools.find(t=>t.id===id);return t&&matches(t.path);}));
   if(saved.path!==location.pathname+location.search){saved.open=active?.id||saved.open||null;saved.path=location.pathname+location.search;persist();}
   for(const section of all){
    const group=el('section','hn-group');group.dataset.key=section.id;
    const row=el('div','hn-row'),heading=el('a','hn-heading');heading.href=section.path;heading.title=section.title;heading.append(el('span','hn-icon',section.icon||'◈'),el('span','',section.title));
    if(active?.id===section.id)heading.setAttribute('aria-current','true');
    const expander=el('button','hn-expander');expander.type='button';expander.setAttribute('aria-label','展开或收起'+section.title);expander.setAttribute('aria-controls','hn-children-'+section.id);expander.append(el('span','','›'));
    expander.onclick=()=>{saved.open=group.dataset.open==='true'?null:section.id;query='';search.value='';persist();filter();};
    row.append(heading,expander);group.append(row);
    const children=el('div','hn-children');children.id='hn-children-'+section.id;const inner=el('div','hn-children-inner');
    const direct=registry.tools.find(t=>section.ids.includes(t.id)&&t.path===section.path);
    const overview=el('a','hn-tool',direct?.label||'工作区概览');overview.href=section.path;if(matches(section.path))overview.setAttribute('aria-current','page');inner.append(overview);
    for(const id of section.ids||[]){const t=registry.tools.find(t=>t.id===id);if(!t||!valid(t.path)||t.path===section.path||t.requiredGroup==='deploy'&&!links.has(t.path))continue;
     const a=el('a','hn-tool',t.label);a.href=t.path;a.title=t.label;if(matches(t.path))a.setAttribute('aria-current','page');
     const old=links.get(t.path);if(old?.getAttribute('aria-disabled')==='true'){a.removeAttribute('href');a.setAttribute('aria-disabled','true');}
     if(t.requiredGroup==='deploy'){a.dataset.requiresGroup='deploy';/* Existing server gate remains authoritative. */}
     inner.append(a);
    }
    children.append(inner);group.append(children);tree.append(group);
   }
   const empty=el('p','hn-empty','没有匹配的入口，试试游戏名称或功能名称。');empty.hidden=true;tree.append(empty);fragment.append(tree);
   if(theme)fragment.append(theme);
   const footer=el('div','hn-footer');if(account)footer.append(account);
   const collapse=el('button','hn-collapse',saved.compact?'»':'«');collapse.type='button';collapse.title=saved.compact?'展开侧栏':'收起侧栏';collapse.setAttribute('aria-label',collapse.title);collapse.setAttribute('aria-expanded',String(!saved.compact));
   collapse.onclick=()=>{saved.compact=!saved.compact;persist();root.dataset.fsNavCompact=String(saved.compact);collapse.textContent=saved.compact?'»':'«';collapse.title=saved.compact?'展开侧栏':'收起侧栏';collapse.setAttribute('aria-label',collapse.title);collapse.setAttribute('aria-expanded',String(!saved.compact));};
   footer.append(collapse);fragment.append(footer);nav.replaceChildren(fragment);filter();
  }finally{building=false;}
 }
 build();
 const grid=document.getElementById('workspaces');let cardsObserver=null;
 if(grid&&location.pathname==='/dashboard/'){
  const syncCards=()=>{for(const section of registry.sections){
   let card=grid.querySelector('.workspace-card.'+section.id);
   if(!card){card=el('article','workspace-card '+section.id);const a=el('a','workspace-main');a.href=section.path;a.append(el('span','workspace-icon',section.icon),el('h3','',section.title),el('p','',section.intro),el('span','entry','进入工作区 →'));card.append(a);grid.append(card);}
   const a=card.querySelector('.workspace-main');if(a&&a.getAttribute('href')!==section.path)a.href=section.path;
  }
   const rpgCard=grid.querySelector('.workspace-card.arpg'),salesCard=grid.querySelector('.workspace-card.sales'),marketingCard=grid.querySelector('.workspace-card.marketing');
   if(rpgCard&&salesCard&&rpgCard.nextElementSibling!==salesCard)rpgCard.after(salesCard);
   if(salesCard&&marketingCard&&salesCard.nextElementSibling!==marketingCard)salesCard.after(marketingCard);
  };
  syncCards();cardsObserver=new MutationObserver(syncCards);cardsObserver.observe(grid,{childList:true});
 }
 document.addEventListener('fs-nav-account-ready',e=>{const incoming=e.detail?.account;if(!incoming)return;const footer=nav.querySelector('.hn-footer');if(!footer)return;footer.querySelector('.hn-account')?.remove();footer.prepend(incoming);});
 // A delayed identity/registry update can replace legacy tree contents once.
 // Old cached shell scripts may still rewrite a group after this bundle runs.
 // Repair only a broken structure; account updates and our own animations do not rebuild it.
 function intact(){return nav.querySelectorAll('.hn-tree > .hn-group').length===registry.sections.filter(s=>valid(s.path)).length && !nav.querySelector('.hn-group .hn-group') && [...nav.querySelectorAll('.hn-tree > .hn-group')].every(g=>g.querySelector(':scope > .hn-row > .hn-expander'));}
 const observer=new MutationObserver(()=>{if(!intact()&&!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;build();});}});
 observer.observe(nav,{childList:true,subtree:true});
 const toggle=document.getElementById('hubNavToggle'),scrim=document.getElementById('hubNavScrim');
 function mobile(open){nav.classList.toggle('open',open);nav.inert=innerWidth<900&&!open;if(scrim)scrim.hidden=!open;toggle?.setAttribute('aria-expanded',String(open));if(open)search.focus();}
 if(toggle)toggle.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();mobile(!nav.classList.contains('open'));},true);
 if(scrim)scrim.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();mobile(false);toggle?.focus();},true);
 mobile(false);
 addEventListener('resize',()=>{if(innerWidth>=900)mobile(false);else nav.inert=!nav.classList.contains('open');});
 document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();saved.compact=false;persist();root.dataset.fsNavCompact='false';const b=nav.querySelector('.hn-collapse');if(b){b.textContent='«';b.title='收起侧栏';b.setAttribute('aria-label','收起侧栏');b.setAttribute('aria-expanded','true');}if(innerWidth<900)mobile(true);search.focus();}
  if(e.key==='Escape'&&nav.classList.contains('open')){mobile(false);toggle?.focus();}
  if(e.key==='Tab'&&innerWidth<900&&nav.classList.contains('open')){const list=[...nav.querySelectorAll('a[href],button,input,select')].filter(n=>n.getClientRects().length&&!n.closest('[inert]'));const first=list[0],last=list.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
 });
 nav.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&e.button===0){saved.scroll=tree.scrollTop;persist();}});
 addEventListener('pagehide',()=>{observer.disconnect();cardsObserver?.disconnect();});
 addEventListener('pageshow',e=>{if(e.persisted){observer.observe(nav,{childList:true,subtree:true});if(!intact())build();if(cardsObserver)cardsObserver.observe(grid,{childList:true});mobile(false);}});
})();
