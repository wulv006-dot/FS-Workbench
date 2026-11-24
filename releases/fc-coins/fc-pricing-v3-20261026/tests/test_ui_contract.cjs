const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname,'../source');
const html = fs.readFileSync(path.join(folder, 'fc27-coins.html'), 'utf8');
const script = fs.readFileSync(path.join(folder, 'fc-pricing-v3.js'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, 'HTML IDs must be unique');
for (const [, id] of script.matchAll(/\$\('([^']+)'\)/g)) assert(ids.includes(id), `missing #${id}`);
assert(!html.includes('/dashboard/fc27-quote-cloud.js'));
assert(!html.includes('/dashboard/fc27-reference-observer.js'));
assert(html.includes('/dashboard/fc27-local-client.js'));
assert(!html.includes('ELD 独立'));
assert(!/value="(?:acquisition|backlog|flash_sale)"/.test(html));
const hero=html.match(/<header class="hero">[\s\S]*?<\/header>/)[0];
assert.match(hero,/FC 自动改价总控制台/);
const mainConsole=html.slice(html.indexOf('class="panel console-panel"'),html.indexOf('aria-labelledby="current-title"'));
for(const id of ['v3-system-enabled','v3-auto-enabled','v3-manual-enabled','v3-uplift-enabled','v3-execute-now','collect','v3-refresh'])assert(mainConsole.includes(`id="${id}"`),`#${id} belongs to the unified console`);
assert.match(mainConsole,/id="v3-execute-now"[^>]*>立即执行一轮改价/);
assert.match(mainConsole,/id="collect"[^>]*>立即采集/);
assert.match(mainConsole,/立即采集只查价/);
assert.match(mainConsole,/id="v3-curve-collect"[^>]*>采集并预览新定价/);
assert.match(mainConsole,/id="v3-curve-status" role="status"/);
assert.match(mainConsole,/<details id="v3-curve-details"><summary>本轮调整详情<\/summary>/);
assert.equal((html.match(/class="price-strip"/g)||[]).length,1);
for (const platform of ['ps','xbox','pc']) assert(ids.includes('v3-price-large-'+platform));
assert.match(mainConsole,/id="v3-curve-activate"[^>]*disabled>启用新定价/);
assert(html.indexOf('id="v3-result"')<html.indexOf('id="v3-panel"'),'action result is visible beside the top controls');
assert.match(html,/fc-pricing-v3\.js\?v=20261124-observer-status/);
assert.equal((html.match(/<article data-platform=/g)||[]).length,3);
assert.match(html,/竞品普通档报价/);
assert.match(html,/相同购买量的普通档售价.*额外加赠档不参与比较/);
assert.match(script,/双20只按购买100K、实交100K这一档核算/);
assert.match(script,/sprint_policy_version='sprint_5_10_lower_quote_floor20_v3'/,'preserve the live lower-anchor business parameter');
assert.match(script,/D-9至D-2八个完整日真实优惠金额结构/,'preserve the live eight-day financial wording');

class Element {
  constructor() { this.value = ''; this.textContent = ''; this.children = []; this.events = {}; this.hidden = false; this.disabled = false; this.dataset = {}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  querySelectorAll() { return []; }
  querySelector() { return new Element(); }
  replaceChildren(...items) { this.children = items; }
  append(...items) { this.children.push(...items); }
  setAttribute() {}
  removeAttribute() {}
  focus() {}
}
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
const marketTag = new Element();
marketTag.textContent='Lootbar 无券 · ItemD2R · Saudi Arabia 普通发货';
elements['v3-market-title'].parentElement={querySelector:selector=>selector==='.tag'?marketTag:null};
elements['v3-mode'].value = 'daily';
const pageEvents={},documentEvents={};
const window={addEventListener:(name,fn)=>{pageEvents[name]=fn;}};
const document = { getElementById: id => elements[id], createElement: () => new Element(), activeElement: null, hidden: false,
  addEventListener:(name,fn)=>{documentEvents[name]=fn;} };
const store = new Map();
const sessionStorage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) };
const plan = { plan_id: 'plan-1', mode: 'daily', state: 'SUSPENDED', revision:3, resources:['base:PS','base:XBOX','base:PC'] };
const state = { plans: [plan], active_plans: [plan], plan, generation: 'g', captured_at: '2026-10-26T13:00:00+08:00', snapshot_id: 'snapshot-1',
  price_control:{revision:0,manual_enabled:false,manual_prices:{PS:null,XBOX:null,PC:null},uplift_enabled:false,uplift_pct:'0'},
  strategies: { daily: { status: 'READY', selected: { action: { base_prices: { PS: '8.51', XBOX:'8.45', PC: '8.59' } }, score: { absolute_forecast_available: false } } }, revenue_sprint: { status: 'DATA_PENDING' } },
  operations: [{ operation_id: 'op-1', status: 'COMPLETED', created_at: '2026-10-26T13:05:00+08:00', bundle: { mode: 'daily', review_approved: false, decision_source: 'v3_explicit_deterministic_feasible_assignment' } }],
  target: { mtd_lower_bound: '666454.13', mtd_upper_bound: '666464.47', through_date: '2026-10-25', today: { status: 'unavailable' } }, region_rules: [], regional_controls: [], incidents: [] };
let canWrite = true, intervalBody;const refreshIntervals=[];
const automation = { revision: 3, can_manage_v3: true, system_enabled:true,mode:'auto',platforms:['PS','XBOX','PC'],minimum_gross_margin_pct:'20', v3: { schedule: { cycle_interval_minutes: 120, active_plan_state: 'SUSPENDED', next_cycle_at: null,
  last_cycle_at: '2026-10-26T13:00:00+08:00', last_source_checked_at: null, last_execution_stage: 'COMPLETED' } } };
const monitor = { storefront: { rows: { PS: { package_usd: 8.51, checked_at: '2026-10-26T13:07:00+08:00' },
  XBOX: { package_usd: 8.51 }, PC: { package_usd: 8.59 } } }, publication: { status: 'matched' } };
let marketError=false,curveMarket;
const market={snapshot_id:'snapshot-1',global_offers:{PS:{Lootbar:{usd_price:'9.18',base_k:'100',bonus_k:'5',checked_at:new Date().toISOString()}}},reference:{offers:[{platform:'PS',gross_usd:'8.14',purchase_k:'100',bonus_k:'0',status:'valid',captured_at:'2000-01-01T00:00:00Z'}]},arab:[]};
market.saudi_missing_price_policy='follow_global';
market.price_basis={rows:{PS:{historical_retained_ratio:'.9',cost_usd_per_1k:'.04',cost_cny_per_1k:'.28',package_cost_usd:'4.2',delivered_k:'105',regular_floor_usd:'5.30',average_floor_usd:'5.80',current_regular_margin_pct:'40',current_average_margin_pct:'30',cost_checked_at:'2026-10-27T00:00:00Z'}}};

const normalFetch = async (url, options = {}) => ({ ok: true, json: async () => url.endsWith('/pricing/v3/interval') ? (intervalBody = JSON.parse(options.body), { revision: 4 })
  : url.endsWith('/pricing/v3/preview') ? {results:{smart:{status:'READY',selected:{action:{base_prices:{PS:'10',XBOX:'10.5',PC:'11'}}}}}}
  : url.endsWith('/pricing/v3/market') ? (marketError?Promise.reject(Error('fixture unavailable')):curveMarket||market)
  : url.endsWith('/pricing/collect') ? {job_id:'collect-test'} : url.endsWith('/jobs/collect-test') ? {status:'ready',result:{status:'INFEASIBLE'}}
  : url.endsWith('/pricing/v3/state') ? state : url.endsWith('/automation') ? (options.body?(intervalBody=JSON.parse(options.body),{revision:4}):{ ...automation, can_manage_v3: canWrite })
  : url.endsWith('/monitor') ? monitor : url.endsWith('/player-sync') ? { enabled: true, revision: 1 } : {} });
const weeklyBodies=[];
const executeBodies=[];
const priceBodies=[];let priceFailure=false;
const collectBodies=[],curvePreviews=[];
let curveJob,curveSubmitLost=false,curveQueueBusy=false,curveBadPlatform='',scheduledCurve;
let stateReads=0,stateReadGate;
const progressTimers=new Map();let timerId=1;
const tickProgress=()=>{const [id,fn]=progressTimers.entries().next().value;progressTimers.delete(id);return fn();};
let curveProven=false,curveActivationResponse='',activationBodies=[];
const previousCurveId='34454366-c016-46ae-89f6-ddccb64f377a';
const curveCapturedAt=new Date().toISOString();
const readonlyMarketId='0d0d4870-f3dd-4f23-bae6-bf9892e48e03';
let readonlyJob=null,readonlyMarket=null,readonlyReads=[];
let executeGate=null,releaseExecution=null,executeFailure=false,executeReplyMissing=false,executeReject=null,executeStatus='done',idSequence=0;
const fetch=async (url,options={})=>{
  if(url.includes('/weekly-ladder/')){weeklyBodies.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({status:'CONFIRMED'})};}
  if(url.endsWith('/pricing/v3/state')){stateReads++;if(stateReadGate)await stateReadGate;}
  if(url.endsWith('/pricing/collect')){
    const body=JSON.parse(options.body);collectBodies.push(body);
    if(body.write_protocol){
      if(curveQueueBusy)return {ok:false,status:503,json:async()=>({error:'queue_mutation_busy',retryable:true,accepted:false})};
      curveJob={job_id:body.client_event_id,kind:'collect',request:{write_protocol:body.write_protocol},status:'running'};
      if(curveSubmitLost)throw Error('fixture collect receipt lost');
      return {ok:true,json:async()=>({job_id:body.client_event_id})};
    }
    if(readonlyJob)return {ok:true,json:async()=>({job_id:readonlyMarketId})};
  }
  if(url.endsWith('/jobs/'+readonlyMarketId))return {ok:true,json:async()=>readonlyJob};
  if(url.includes('/pricing/v3/market/')){
    readonlyReads.push({url,method:options.method});
    return readonlyMarket?{ok:true,json:async()=>readonlyMarket}:{ok:false,status:503,json:async()=>({error:'state_unavailable'})};
  }
  if(url.includes('/jobs/new-id-')){
    if(!curveJob)return {ok:false,status:404,json:async()=>({error:'not_found'})};
    return {ok:true,json:async()=>curveJob};
  }
  if(url.endsWith('/jobs/'+previousCurveId))return {ok:true,json:async()=>({job_id:previousCurveId,
    kind:'collect',request:{write_protocol:'fc27_curve_v6'},status:'ready',result:{run_id:previousCurveId}})};
  if(url.endsWith('/jobs/00000000-0000-0000-0000-000000000000'))return {ok:false,status:404,json:async()=>({error:'not_found'})};
  if(url.endsWith('/plans/plan-1/activate-curve')){
    const body=JSON.parse(options.body);activationBodies.push(body);
    if(curveActivationResponse==='lost-before')throw Error('fixture request lost before acceptance');
    plan.revision=body.expected_revision+1;
    plan.write_protocol='fc27_curve_v6';
    plan.curve_activation_snapshot_id=body.snapshot_id;
    if(curveActivationResponse==='lost-after')throw Error('fixture receipt lost after acceptance');
    return {ok:true,json:async()=>plan};
  }
  if(url.endsWith('/pricing/v3/preview')&&JSON.parse(options.body).write_protocol){
    const body=JSON.parse(options.body);curvePreviews.push(body);
    return {ok:true,json:async()=>({write_protocol:body.write_protocol,platform:body.platform,
      snapshot_id:curveBadPlatform===body.platform?'wrong-run':body.snapshot_id, snapshot_captured_at:curveCapturedAt,
      execution_authorized:false,write_performed:false,
      current_catalogue:{quote_100k:{regular_usd:'8.50'},tiers:[{purchase_k:'1000',native_price_usd:'81.60',promised_bonus_k:'30'}]},decision:{candidates:[{
        labels:[curveProven?'CURRENT':'A'],quote:body.segment==='small'?{purchase_k:'100',regular_usd:'8.40'}:{purchase_k:'1000',regular_usd:'79.25'},financial_proof:{status:curveProven?'PROVEN':'PROOF_INCOMPLETE',
          average_discount:{contract:'fc_v6_d8_d2_amount_weighted_discount_v1',retained_ratio:'0.935',
            eligible_orders:200,matched_orders:200},minimum_safe_procurement_margin:'0.215'}}]}})};
  }
  if(url.endsWith('/pricing/v3/price-control')){
    const body=JSON.parse(options.body);priceBodies.push(body);
    if(priceFailure)throw Error('fixture price save result unknown');
    state.price_control={...body,revision:state.price_control.revision+1};
    return {ok:true,json:async()=>({settings:state.price_control,write_performed:false})};
  }
  if(url.endsWith('/pricing/v3/execute')){
    const body=JSON.parse(options.body);executeBodies.push(body);
    if(executeGate)await executeGate;
    if(executeFailure)throw Error('fixture network result unknown');
    if(executeReject)return {ok:false,status:executeReject.status,json:async()=>({error:executeReject.error})};
    return {ok:true,json:async()=>executeReplyMissing?{status:'queued'}:({status:executeStatus,job_key:'manual:'+body.request_key})};
  }
  return normalFetch(url,options);
};
vm.runInNewContext(script, { document, window, fetch, sessionStorage, crypto: { randomUUID: () => 'new-id-'+(++idSequence) }, AbortSignal: { timeout: () => null },
  setInterval: (fn,ms) => {refreshIntervals.push(ms);}, setTimeout: (fn,ms)=>{if(ms===10000){scheduledCurve=fn;return 1;}assert.equal(ms,7000);progressTimers.set(++timerId,fn);return timerId;}, clearTimeout:id=>{progressTimers.delete(id);}, Intl, Date, console });
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
(async () => {
  await tick();
  assert.deepEqual(refreshIntervals,[300000],'background status refresh every five minutes; manual refresh stays immediate');
  state.active_plans.push({mode:'revenue_sprint',resources:['base:PS','base:XBOX','base:PC'],parameters:{preferred_undercut_pct:'5'}});
  elements['v3-mode'].value='smart';elements['v3-mode'].events.change();
  await elements['v3-preview'].events.click();
  assert.match(elements['v3-preview-output'].textContent,/默认7\.5%.*情景/);
  assert.match(elements['v3-preview-output'].textContent,/未使用当前5%.*6小时.*分配/);
  assert.match(elements['v3-preview-output'].textContent,/不是本计划报价.*不作为切换或审批依据/);
  state.active_plans.pop();
  elements['v3-mode'].value='daily';elements['v3-mode'].events.change();
  assert.match(elements['v3-current-plan'].textContent, /已暂停/);
  assert.match(elements['v3-next-cycle'].textContent, /已暂停，无下一自然写价轮/);
  assert.match(elements['v3-review-source'].textContent, /历史原操作.*未获模型审核.*当前规则无需逐轮审核/);
  assert.equal(elements['v3-price-pc'].textContent, '$8.59');
  assert.equal(elements['v3-execute-now'].disabled,true,'top execute requires an active plan');
  state.operations[0].order_close={reason:'order_write_confirmed_admin_price_matched'};
  monitor.publication.status='mismatch';await elements['v3-refresh'].events.click();
  assert.match(elements['v3-stage'].textContent,/^Order与Admin已确认/);
  assert.match(elements['v3-review-source'].textContent,/最近原操作 op-1：Order与Admin已确认.*公开网页核验单独列示/);
  assert.match(elements['v3-public-status'].textContent,/mismatch/,'separate public mismatch remains visible');
  delete state.operations[0].order_close;monitor.publication.status='matched';await elements['v3-refresh'].events.click();
  assert.match(elements['v3-stage'].textContent,/公开核验完成/,'legacy public-confirmed completion label is preserved');
  assert.match(elements['v3-source-time'].textContent, /待核/);
  assert.equal(elements['v3-strategies'].children.length, 1, 'only selected strategy is shown');
  elements['v3-mode'].value='revenue_sprint';
  state.strategies.revenue_sprint={status:'READY',selected:{decision_type:'floor_fallback',action:{base_prices:{PS:'7.15',XBOX:'7.25',PC:'8.31'}},score:{absolute_forecast_available:false}}};
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/双20可写，未达到竞争目标/);
  elements['v3-mode'].value='daily';
  await elements['v3-refresh'].events.click();
  state.strategies.daily.selected.daily_pricing={XBOX:{driver_platform:'XBOX',target_public_usd:'8.55',selected_base_total:'8.55',item_target_met:true,platforms:{PS:{actual_unit_100k:'8.142857',reference_source:'Lootbar',difference_pct:'-10'},XBOX:{actual_unit_100k:'8.142857',reference_source:'ItemD2R',difference_pct:'.035'}}}};
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/Xbox按ItemD2R XBOX当轮实际交付价定价/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/达到Item目标（按公开分币舍入）/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/PS.*本平台参考 Lootbar.*价差 -10.00%/);
  state.strategies.daily.selected.daily_pricing.XBOX.item_target_met=false;
  state.strategies.daily.selected.daily_pricing.XBOX.selected_base_total='11.67';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/财务底价抬高，未达到Item目标/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/双20可写，未达到ItemD2R目标/);
  state.strategies.daily.selected.daily_pricing.XBOX.unmet_reason='public_cent_not_reachable';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/舍入导致目标未命中，未达到Item目标/);
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/财务底价抬高/);
  delete state.strategies.daily.selected.daily_pricing;await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-interval-minutes'].value, 120);
  assert(html.indexOf('id="plan-title"')<html.indexOf('id="current-title"'),'unified controls precede price monitoring');
  assert(html.indexOf('id="current-title"')<html.indexOf('id="v3-market-title"'),'current prices precede competitor details');
  assert.equal(elements['v3-market-cards'].children.length,3);
  const marketText=JSON.stringify(elements['v3-market-cards'].children);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/历史七日平均优惠10\.0% 红线/);
  market.price_basis.history_window_contract='d9_d2_eight_closed_days_v1';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/D-9至D-2八日平均优惠10\.0% 红线/);
  const originalRows=market.price_basis.rows;
  market.price_basis.rows=Object.fromEntries(['PS','XBOX','PC'].map(p=>[p,{...originalRows.PS,average_floor_usd:'9.16'}]));
  for(const [retained,expected] of [['.9134','8.6%'],['.914','8.6%'],['1','0.0%'],[null,'待核'],['','待核'],['bad','待核']]){
    for(const row of Object.values(market.price_basis.rows))row.historical_retained_ratio=retained;
    await elements['v3-refresh'].events.click();
    for(const platform of ['ps','xbox','pc'])assert.equal(elements['v3-price-basis-'+platform].children[3].textContent.split(' · ')[0],`D-9至D-2八日平均优惠${expected} 红线 $9.16`);
  }
  market.price_basis.rows=originalRows;
  const distinct={PS:['.9181192335961722','8.1%'],XBOX:['.9244583833739689','7.5%'],PC:['.9105486557247720','8.9%']};
  market.price_basis.rows=Object.fromEntries(Object.entries(distinct).map(([p,[retained]])=>[p,{...originalRows.PS,historical_retained_ratio:retained}]));
  await elements['v3-refresh'].events.click();
  for(const [p,[,pct]] of Object.entries(distinct))assert.match(elements['v3-price-basis-'+p.toLowerCase()].children[3].textContent,new RegExp('八日平均优惠'+pct.replace('.','\\.')));
  market.price_basis.rows=originalRows;
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-proof-notes'].textContent,/八个完整日/);
  state.operations[0].bundle.financial_contract_version='fc27_dual20_v1';
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-proof-notes'].textContent,/旧口径历史证明/);
  state.operations[0].bundle.financial_proof={pricing_scope:'100k_package_only'};
  market.price_basis.pricing_scope='100k_package_only';
  await elements['v3-refresh'].events.click();
  assert.doesNotMatch(elements['v3-proof-notes'].textContent,/旧口径历史证明/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/双20只按购买100K/);
  delete state.operations[0].bundle.financial_proof;
  delete market.price_basis.pricing_scope;
  delete state.operations[0].bundle.financial_contract_version;
  delete market.price_basis.history_window_contract;
  await elements['v3-refresh'].events.click();

  assert.match(marketText,/\$8.74 \/ 100K 实际交付/,'normalize with all 105K delivered');
  assert.match(marketText,/ItemD2R/,'saved sprint reference remains visible under daily strategy');
  assert.match(marketText,/已过 15 分钟/);
  assert.match(marketText,/暂无报价/);
  assert.doesNotMatch(marketText,/赠品等值|礼包估算/);
  assert.match(marketText,/\$8.14 \/ 100K 实际交付/);
  assert.match(marketText,/缺价 · 跟随全球/);
  const savedOffers=market.global_offers,savedReference=market.reference;
  market.global_offers={};market.reference={status:'unavailable',offers:[],reason:'itemd2r_cloudflare_403',http_status:403,blocked_by:'cloudflare'};
  market.competitor_diagnostics=['Lootbar:TimeoutExpired'];await elements['v3-refresh'].events.click();
  const missingText=JSON.stringify(elements['v3-market-cards'].children);
  assert.match(missingText,/Cloudflare 403 · 缺价/);
  assert.match(missingText,/TimeoutExpired/);
  assert.match(missingText,/30%/);
  assert.match(missingText,/双20最低/);
  assert.doesNotMatch(missingText,/\$8\.14/,'old saved Item price must not fill current unavailable source');
  market.global_offers=savedOffers;market.reference=savedReference;delete market.competitor_diagnostics;
  await elements['v3-refresh'].events.click();
  market.reference={status:'partial',offers:savedReference.offers,reason:'itemd2r_partial_platform_coverage',missing:[{platform:'PC',source:'ItemD2R',reason:'itemd2r_price_invalid:PC'}]};
  await elements['v3-refresh'].events.click();
  const partialCards=elements['v3-market-cards'].children;
  assert.match(JSON.stringify(partialCards[0]),/\$8\.14 \/ 100K 实际交付/);
  assert.doesNotMatch(JSON.stringify(partialCards[0]),/itemd2r_price_invalid:PC/);
  assert.match(JSON.stringify(partialCards[2]),/itemd2r_price_invalid:PC/);
  assert.doesNotMatch(JSON.stringify(partialCards[2]),/itemd2r_partial_platform_coverage/,'platform-specific reason takes precedence');
  market.reference=savedReference;await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/采购成本.*0.0400/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/未优惠红线.*5.30.*当前50.6%/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/七日平均优惠10\.0% 红线.*5.80.*当前45.2%/);
  monitor.storefront.rows.PS.package_usd='7.00';await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/未优惠红线.*当前40.0%/,'current margin must follow the public readback, not the pre-write snapshot price');
  assert(!html.includes('<pre id="v3-daily-result"'),'prose must not inherit the shared code-block no-wrap style');
  marketError=true;await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-market-cards'].children.length,0);
  assert.match(elements['v3-market-status'].textContent,/暂无法读取/);
  marketError=false;market.snapshot_id='different-snapshot';await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-market-cards'].children.length,0);
  assert.match(elements['v3-market-status'].textContent,/不一致/);
  market.snapshot_id=state.snapshot_id;await elements['v3-refresh'].events.click();
  elements['v3-interval-minutes'].value = '180';
  await elements['v3-interval-form'].events.submit({ preventDefault() {} }); await tick();
  assert.deepEqual(intervalBody, {settings:{system_enabled:true,mode:'auto',interval_minutes:180,platforms:['PS','XBOX','PC'],minimum_gross_margin_pct:'20'},expected_revision:3});
  state.operations[0].bundle.decision_source = 'v3_inherited_reviewed_business_strategy';
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent, /沿用先前已审经营策略/);
  state.operations[0].bundle.decision_source = 'v3_model_reviewed_this_cycle';
  state.operations[0].bundle.review_approved = true;
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent, /本轮 Hermes 实际选择/);
  elements['v3-mode'].value = 'revenue_sprint'; elements['v3-mode'].events.change();
  assert.equal(elements['v3-strategies'].children.length, 1);
  state.operations[0].bundle.review_contract='program_pricing_with_daily_hermes_review_v3';
  state.operations[0].bundle.review_approved=false;
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent,/当前规则：程序逐轮定价，Hermes 每日效果复盘/);
  state.operations[0].bundle.maintenance_purpose='retire_uk_discount_v1';
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent,/用户授权英国临时折扣退出/);
  assert.doesNotMatch(elements['v3-review-source'].textContent,/待核/);
  assert.equal(elements['v3-end'].required,false);
  assert.match(elements['v3-end-help'].textContent,/留空持续运行/);
  elements['v3-mode'].value = 'revenue_sprint'; elements['v3-mode'].events.change();
  assert.equal(elements['v3-target-section'].hidden, false);
  canWrite = false; await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-execute'].disabled, true);
  assert.equal(elements['v3-execute-now'].disabled,true,'top execute follows writer permission');
  assert.equal(elements['collect'].disabled, true);
  assert.equal(elements['v3-curve-collect'].disabled,true);
  assert.match(elements['v3-state'].textContent, /仅可查看/);
  state.snapshot_id='fresh-infeasible-snapshot';
  state.strategies.revenue_sprint={status:'INFEASIBLE',candidates:[],selected:null,failures:Array.from({length:200},(_,i)=>({code:['NO_SAFE_COMMIT_PATH','pricing_required_market_missing:ArabUT:PC','pricing_regional_competitive_band'][i%3],scope:'candidate:'+i}))};
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-decision-basis'].textContent,/fresh-infeasible-snapshot/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/本次未写价/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/没有可证的当前写入顺序/);
  assert.equal((JSON.stringify(elements['v3-strategies'].children).match(/没有可证的当前写入顺序/g)||[]).length,1,'summarize each rejection reason once while keeping per-candidate evidence');
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/已有可行方案/);
  canWrite=true;await elements['v3-refresh'].events.click();await elements.collect.events.click();
  assert.match(elements['v3-result'].textContent,/采集已完成；当前策略无可执行报价，未写价/);
  assert.equal(sessionStorage.getItem('fc-v3-collect-job'),null);
  assert.deepEqual(Object.keys(collectBodies[0]),['client_event_id'],'original collect stays on the scalar protocol');
  curveSubmitLost=true;
  await elements['v3-curve-collect'].events.click();
  const originalCurve=curveJob.job_id;
  assert.equal(sessionStorage.getItem('fc-v3-curve-collect-job'),originalCurve);
  assert.match(elements['v3-curve-status'].textContent,/正在采集三平台/);
  assert.equal(elements['v3-market-activity'].dataset.state,'pending');
  assert.match(elements['v3-market-activity'].textContent,/最近保存的快照/);
  assert.equal(elements['v3-curve-collect'].disabled,true);
  curveJob={...curveJob,status:'ready',result:{run_id:originalCurve,quote_status:'proof_incomplete'}};
  curveBadPlatform='PC';
  await scheduledCurve();
  assert.equal(collectBodies.length,2,'an unknown POST with an original job never submits again');
  assert.deepEqual(curvePreviews.filter(row=>!row.segment).map(row=>row.platform),['PS','XBOX','PC']);
  assert.deepEqual(curvePreviews.filter(row=>row.segment==='small').map(row=>row.platform),['PS','XBOX']);
  assert(curvePreviews.every(row=>row.snapshot_id===originalCurve&&row.write_protocol==='fc27_curve_v6'));
  assert.match(JSON.stringify(elements['v3-curve-results'].children[0]),/\$79\.25.*证据待补.*\$2\.35/);
  assert.match(JSON.stringify(elements['v3-curve-results'].children[0]),/\$8\.40.*证据待补.*\$0\.10/);
  assert.equal(elements['v3-price-ps'].textContent,'$7.00');
  assert.match(JSON.stringify(elements['v3-curve-results'].children[0]),/核算依据.*D-8 至 D-2 平均优惠 6\.50%.*200\/200.*21\.50%/);
  const candidateCard=elements['v3-curve-results'].children[0];
  assert.match(JSON.stringify(candidateCard),/预览/);
  assert.doesNotMatch(JSON.stringify(candidateCard),/后台现价/);
  assert.equal(candidateCard.children.filter(row=>row.className==='candidate-basis').length,1);
  assert.doesNotMatch(JSON.stringify(elements['v3-curve-results'].children[2]),/79\.25/);
  assert.equal(elements['v3-curve-collect'].textContent,'重读原预览');
  curveBadPlatform='';
  await elements['v3-curve-collect'].events.click();
  assert.match(elements['v3-curve-status'].textContent,/三平台预览已读回.*本次未改价/);
  assert.equal(sessionStorage.getItem('fc-v3-curve-collect-job'),null);
  assert.equal(elements['v3-curve-activate'].disabled,true,'incomplete proof cannot switch the plan');
  assert.equal(collectBodies.length,2);
  curveQueueBusy=true;curveJob=null;
  await elements['v3-curve-collect'].events.click();
  assert.equal(collectBodies.length,3,'a busy queue response only checks the original job');
  assert.match(elements['v3-curve-status'].textContent,/采集队列暂忙，本次未入队.*可用原编号续办/);
  assert.equal(sessionStorage.getItem('fc-v3-curve-collect-job'),collectBodies[2].client_event_id);
  assert.equal(elements['v3-curve-collect'].textContent,'续办原采集');
  curveQueueBusy=false;curveSubmitLost=false;
  await elements['v3-curve-collect'].events.click();
  assert.equal(collectBodies[2].client_event_id,collectBodies[3].client_event_id,'confirmed absent retries use the same event ID');
  curveJob={...curveJob,status:'failed',error_detail:'fixture no quote'};
  await scheduledCurve();
  assert.match(elements['v3-curve-status'].textContent,/未能生成预览/);
  plan.state='ACTIVE';await elements['v3-refresh'].events.click();
  curveProven=true;
  const collectsBeforeRead=collectBodies.length;
  elements['v3-curve-read-id'].value='00000000-0000-0000-0000-000000000000';
  await elements['v3-curve-read'].events.click();
  assert.match(elements['v3-curve-status'].textContent,/未找到原采集.*请核对编号/);
  assert.equal(elements['v3-curve-collect'].textContent,'采集并预览新定价');
  const activationSnapshot=previousCurveId;
  elements['v3-curve-read-id'].value=activationSnapshot;
  await elements['v3-curve-read'].events.click();
  assert.equal(collectBodies.length,collectsBeforeRead,'reading the prior job after reload never starts a new collector');
  assert.equal(elements['v3-curve-activate'].disabled,false);
  curveActivationResponse='lost-before';
  await elements['v3-curve-activate'].events.click();
  assert.equal(activationBodies.length,1,'unknown result only reads state automatically');
  assert.equal(elements['v3-curve-activate'].textContent,'续办原启用');
  curveActivationResponse='lost-after';
  await elements['v3-curve-activate'].events.click();
  assert.deepEqual(activationBodies,[{expected_revision:3,snapshot_id:activationSnapshot},{expected_revision:3,snapshot_id:activationSnapshot}]);
  assert.match(elements['v3-curve-activation-status'].textContent,/新定价已启用.*版本 4/);
  assert.equal(elements['v3-curve-activate'].disabled,true);
  assert.equal(sessionStorage.getItem('fc-v3-curve-activation'),null);
  assert.match(marketTag.textContent,/Lootbar.*U7Buy.*Arab-UT.*100K/);
  assert.match(elements['v3-market-status'].textContent,/等待当前新定价/);
  assert.doesNotMatch(elements['v3-price-basis-ps'].textContent,/双红线|双20/);
  assert.match(elements['v3-decision-basis'].textContent,/等待当前 V6/);
  assert.doesNotMatch(elements['v3-state'].textContent,/2026-10-26/,'V6 must hide a legacy snapshot during independent deployment');
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/双20|本轮最终候选/);
  const oldSnapshotId=state.snapshot_id,oldSnapshotTime=state.captured_at;
  state.write_protocol='fc27_curve_v6';
  state.snapshot_id='curve-market-run';
  state.captured_at=curveCapturedAt;
  state.source_checked_at=curveCapturedAt;
  state.curve_decision={status:'READY',rows:[
    {platform:'PS',status:'READY',selection:{segment:'large',label:'C'}},
    {platform:'XBOX',status:'KEEP'},
    {platform:'PC',status:'PROOF_INCOMPLETE',gaps:['ordinary_cost_unavailable']}
  ]};
  curveMarket={write_protocol:'fc27_curve_v6',snapshot_id:'curve-market-run',captured_at:curveCapturedAt,
    price_basis:{rows:{PS:{average_discount:{retained_ratio:'.91'},minimum_safe_procurement_margin:'.182'}}},
    catalogue_samples:{PS:{observed_at:curveCapturedAt,tiers:[{purchase_k:'100',native_price_usd:'8.51',promised_bonus_k:'0'},{purchase_k:'1000',native_price_usd:'81.60',promised_bonus_k:'30'}]}},
    competitor_offers:[
      {source:'Lootbar',platform:'PS',purchase_k:100,bonus_k:'5',currency:'USD',regular_price:'8.75',comparable:true,captured_at:curveCapturedAt},
      {source:'U7Buy',platform:'PS',purchase_k:'1000',bonus_k:'30',currency:'USD',regular_price:'85',comparable:true},
      {source:'U7Buy',platform:'PS',purchase_k:'100',bonus_k:'0',currency:'USD',regular_price:'9.10',comparable:true,captured_at:'2000-01-01T00:00:00Z'},
      {source:'ArabUT',platform:'XBOX',purchase_k:'1000',bonus_k:'30',currency:'USD',regular_price:'80',comparable:true},
      {source:'ArabUT',platform:'PC',purchase_k:'100.000',bonus_k:'0',currency:'SAR',regular_price:'35',comparable:true}
    ]};
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-market-status'].textContent,/新定价采集快照/);
  assert.equal(elements['v3-market-snapshot'].textContent,'curve-market-run');
  assert.match(elements['v3-decision-basis'].textContent,/curve-market-run.*V6/);
  const curveDecisionText=JSON.stringify(elements['v3-strategies'].children);
  assert.match(curveDecisionText,/PS.*已有可行方案.*大额段.*C.*Xbox.*保持现价.*PC.*核算待补/);
  assert.doesNotMatch(curveDecisionText,/双20|已写价|本轮最终候选|op-1/);
  assert.equal(elements['v3-legacy-proof-table'].hidden,true);
  assert.match(elements['version'].textContent,/V6.*curve-market-run/);
  assert.match(elements['v3-stage'].textContent,/已有可行方案/);
  assert.notEqual(elements['v3-source-time'].textContent,'当前计划来源待核');
  const savedOperations=state.operations;
  state.operations=[{operation_id:'original-current-curve',plan_id:plan.plan_id,status:'COMPLETED',
    bundle:{write_protocol:'fc27_curve_v6',snapshot_id:'curve-market-run'},
    readback:{write_protocol:'fc27_curve_v6',execution_id:'original-current-curve',status:'CONFIRMED'}},...savedOperations];
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/本轮原操作.*Admin 主站价表已核对.*original-current-curve/);
  assert.match(elements['v3-stage'].textContent,/Admin 主站价表已核对/);
  state.operations=savedOperations;
  assert.equal(elements['v3-price-large-ps'].textContent,'$81.60');
  assert.match(elements['v3-price-delivery-ps'].textContent,/赠 30K · 实交 1030K/);
  assert.equal(elements['v3-price-large-xbox'].textContent,'现价待核');
  assert.equal(elements['v3-price-xbox'].textContent,'现价待核','V6 current price does not fall back to a public quote');
  const [psMarket,xboxMarket,pcMarket]=elements['v3-market-cards'].children;
  assert.match(JSON.stringify(psMarket),/Lootbar.*\$8\.75.*购买 100K.*赠 5K.*U7Buy.*\$9\.10.*购买 100K/);
  assert.match(JSON.stringify(xboxMarket),/Arab-UT.*该快照未取得 100K 报价/);
  assert.match(JSON.stringify(pcMarket),/Arab-UT.*SAR 35.*采价时间待核.*报价详情.*购买 100K/);
  assert.match(JSON.stringify(psMarket),/Lootbar.*已采 · 15 分钟内.*U7Buy.*历史报价 · 已过 15 分钟/);
  assert.doesNotMatch(JSON.stringify([psMarket,xboxMarket,pcMarket]),/1000K|\$85\.00|\$80\.00/);
  assert.equal(elements['v3-price-ps'].textContent,'$8.51');
  assert.match(elements['v3-price-source-ps'].textContent,/后台采样/);
  assert.equal(elements['v3-price-change-ps'].hidden,true);
  const historicalMarket=curveMarket;
  curveMarket={...historicalMarket,competitor_policy:'v6_pricing_packages_observers_separate_v2',
    competitor_coverage:{optional_sources:['Lootbar','U7Buy']},
    monitoring:{IGGM:[{platform:'PS',purchase_k:'100',regular_price:'10',captured_at:curveCapturedAt}],U4GM:[]},
    monitoring_status:{IGGM:'partial',U4GM:'pending'}};
  await elements['v3-refresh'].events.click();
  const monitorCards=JSON.stringify(elements['v3-market-cards'].children[0]);
  assert.match(monitorCards,/IGGM · 监控.*我方同档价差 -14.9%.*U4GM · 监控.*本轮尚无监控结果/);
  assert.doesNotMatch(monitorCards,/Arab-UT/);
  curveMarket={...curveMarket,monitoring_status:{IGGM:'partial',U4GM:'missing'},
    monitoring:{...curveMarket.monitoring,IGGM:[...curveMarket.monitoring.IGGM,
      {platform:'PS',purchase_k:'1000',regular_price:'90',captured_at:curveCapturedAt,collection_node:'local'}]},
    monitoring_attempts:{IGGM:[{node:'local',errors:[],response_received:true,requested:[['PS','1000'],['PC','1000']]}],
      U4GM:[{node:'187',errors:['source_blocked'],response_received:false}]}};
  await elements['v3-refresh'].events.click();
  const diagnosedCards=JSON.stringify(elements['v3-market-cards'].children[0]);
  assert.match(diagnosedCards,/IGGM · 监控.*1000K .*Windows 本机采集.*U4GM · 监控.*187 的来源账本已阻断本站，采集停派，本轮未派给本机/);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[2]),/IGGM · 监控.*Windows 本机已回传，仍有普通档缺价/);
  curveMarket=historicalMarket;
  await elements['v3-refresh'].events.click();
  const decisionBeforeReadonly=elements['v3-decision-basis'].textContent;
  const sourceBeforeReadonly=elements['v3-source-time'].textContent;
  readonlyJob={job_id:readonlyMarketId,kind:'collect',status:'running'};
  readonlyMarket={write_protocol:'fc27_curve_v6',snapshot_id:readonlyMarketId,basis:'readonly_collection',
    execution_authorized:false,write_performed:false,captured_at:curveCapturedAt,
    competitor_offers:[{source:'ArabUT',platform:'PS',purchase_k:'100',bonus_k:'0',currency:'USD',
      regular_price:'8.80',comparable:true,captured_at:curveCapturedAt}]};
  await elements.collect.events.click();
  assert.match(elements['v3-result'].textContent,/只读采集已登记/);
  assert.equal(elements['v3-market-snapshot'].textContent,'curve-market-run');
  readonlyJob={...readonlyJob,status:'ready',result:{run_id:readonlyMarketId,quote_status:'curve_candidate_proven'}};
  await scheduledCurve();
  assert.match(elements['v3-result'].textContent,/采集已完成.*本次未改价/);
  assert.doesNotMatch(elements['v3-result'].textContent,/待核（ready）/);
  assert.match(elements['v3-market-status'].textContent,/只读采集快照.*本次未改价/);
  assert.equal(elements['v3-market-snapshot'].textContent,readonlyMarketId);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[0]),/Arab-UT.*\$8\.80/);
  assert.equal(elements['v3-decision-basis'].textContent,decisionBeforeReadonly);
  assert.equal(elements['v3-source-time'].textContent,sourceBeforeReadonly);
  assert.equal(elements['v3-price-ps'].textContent,'$8.51');
  assert.equal(readonlyReads.length,1);
  assert.equal(readonlyReads[0].method,undefined,'read the saved collection over GET');
  await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-market-snapshot'].textContent,readonlyMarketId,'status refresh retains the newer collection');
  const originalMarketTime=curveMarket.captured_at;
  curveMarket.captured_at='2099-01-01T00:00:00Z';
  await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-market-snapshot'].textContent,'curve-market-run','newer plan evidence replaces old collection');
  curveMarket.captured_at=originalMarketTime;
  readonlyJob=null;readonlyMarket=null;
  state.snapshot_id=oldSnapshotId;state.captured_at=oldSnapshotTime;
  delete state.write_protocol;delete state.curve_decision;delete state.source_checked_at;
  const sampled=curveMarket.catalogue_samples.PS;
  const operationsBefore=state.operations;
  state.catalogue_readbacks={PS:{...sampled,basis:'confirmed_readback'}};
  state.operations=[{operation_id:'original-confirmed',status:'COMPLETED',readback:{
    write_protocol:'fc27_curve_v6',execution_id:'original-confirmed',status:'CONFIRMED',curve_results:{
      PS:{operation_id:'original-confirmed',propagation:{status:'confirmed',confirmed_at:curveCapturedAt},
        recipients_before:{'266':{more:{gold:[100,1000],price:[8.16,82.15]}}}}
    }
  }}];
  await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-price-change-ps'].textContent,'最近确认 +$0.35');
  assert.equal(elements['v3-price-change-ps'].dataset.trend,'up');
  assert.equal(elements['v3-price-change-large-ps'].textContent,'最近确认 −$0.55');
  assert.equal(elements['v3-price-change-large-ps'].dataset.trend,'down');
  assert.match(elements['v3-price-source-ps'].textContent,/后台已确认/);
  assert.match(elements['v3-review-source'].textContent,/Admin 主站完整价表已确认.*公开网页核验单独列示/);
  assert.match(elements['v3-public-status'].textContent,/公开网页独立核验/);
  curveMarket.catalogue_samples.PS={...sampled,observed_at:'2099-01-01T00:00:00Z',basis:'admin_sample'};
  await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-price-change-ps'].hidden,true,'older confirmed change never labels a newer sample');
  assert.match(elements['v3-price-source-ps'].textContent,/后台采样/);
  state.operations=operationsBefore;
  delete state.catalogue_readbacks;
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/9\.00%.*18\.20%/);
  curveMarket=undefined;
  assert.equal(executeBodies.length,0);
  delete plan.write_protocol;delete plan.curve_activation_snapshot_id;
  plan.state='ACTIVE';await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-execute-now'].disabled,false);
  executeGate=new Promise(resolve=>{releaseExecution=resolve;});
  const firstExecute=elements['v3-execute-now'].events.click();
  assert.equal(elements['v3-execute-now'].disabled,true);
  assert.equal(elements['v3-execute'].disabled,true,'both execution buttons share busy state');
  assert.equal(elements.collect.disabled,true,'collection cannot double-submit during an action');
  await elements['v3-execute'].events.click();
  assert.equal(executeBodies.length,1,'rapid clicks across both buttons produce one request');
  releaseExecution();await firstExecute;executeGate=null;
  assert.match(elements['v3-result'].textContent,/改价任务已登记/);
  assert.match(elements['v3-execution-job'].textContent,/^manual:/);
  assert.match(elements['v3-execution-progress'].textContent,/本轮已结束.*操作回执/);
  assert.equal(elements['v3-execute-now'].disabled,false);
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),null,'confirmed acknowledgement ends this request intent');
  await elements['v3-execute'].events.click();
  assert.equal(executeBodies[1].plan_id,'plan-1');
  assert.notEqual(executeBodies[0].request_key,executeBodies[1].request_key,'a later action uses a new key even with the same snapshot');
  executeFailure=true;await elements['v3-execute-now'].events.click();
  const unknownKey=executeBodies[2].request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),unknownKey);
  assert.match(elements['v3-result'].textContent,/尚未确认.*更新统一状态.*沿用该请求编号/);
  executeFailure=false;await elements['v3-execute'].events.click();
  assert.equal(executeBodies[3].request_key,unknownKey,'unknown results reuse the original key');
  await elements['v3-execute-now'].events.click();
  assert.notEqual(executeBodies[4].request_key,unknownKey,'the next confirmed intent is unique');
  executeReplyMissing=true;await elements['v3-execute-now'].events.click();
  const missingReceiptKey=executeBodies.at(-1).request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),missingReceiptKey);
  assert.match(elements['v3-error'].textContent,/回执缺少编号/);
  executeReplyMissing=false;await elements['v3-execute-now'].events.click();
  assert.equal(executeBodies.at(-1).request_key,missingReceiptKey,'missing receipt identities also reuse the same intent');
  executeReject={status:400,error:'pricing_plan_required'};await elements['v3-execute-now'].events.click();
  const rejectedKey=executeBodies.at(-1).request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),null,'an explicit pre-enqueue refusal ends this unused request key');
  assert.match(elements['v3-result'].textContent,/被拒绝.*当前没有可执行.*未登记新任务/);
  assert.doesNotMatch(elements['v3-result'].textContent,/尚未确认/);
  executeReject=null;await elements['v3-execute-now'].events.click();
  assert.notEqual(executeBodies.at(-1).request_key,rejectedKey);
  executeReject={status:503,error:'queue_unavailable'};await elements['v3-execute-now'].events.click();
  const serverUnknownKey=executeBodies.at(-1).request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),serverUnknownKey,'a server failure does not prove the write was rejected');
  executeReject={status:400,error:'pricing_execute_payload_conflict'};await elements['v3-execute-now'].events.click();
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),serverUnknownKey,'a conflict identifies an existing original request');
  executeReject=null;
  await elements['v3-execute-now'].events.click();
  executeFailure=true;await elements['v3-execute-now'].events.click();
  const unauthorizedUnknownKey=executeBodies.at(-1).request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-unknown-plan-1'),unauthorizedUnknownKey);
  executeFailure=false;executeReject={status:403,error:'writer_required'};
  await elements['v3-execute'].events.click();
  assert.equal(executeBodies.at(-1).request_key,unauthorizedUnknownKey);
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),unauthorizedUnknownKey,'a later 403 cannot erase an earlier unknown write');
  assert.match(elements['v3-result'].textContent,/尚未确认/);
  assert.doesNotMatch(elements['v3-result'].textContent,/未登记新任务/);
  executeReject=null;await elements['v3-execute-now'].events.click();
  assert.equal(executeBodies.at(-1).request_key,unauthorizedUnknownKey,'permission recovery reconciles the same request');
  assert.equal(sessionStorage.getItem('fc-v3-execute-unknown-plan-1'),null);
  await elements['v3-execute-now'].events.click();
  assert.notEqual(executeBodies.at(-1).request_key,unauthorizedUnknownKey);
  executeStatus='confirmation_pending';await elements['v3-execute-now'].events.click();
  const pendingStatusKey=executeBodies.at(-1).request_key;
  assert.equal(sessionStorage.getItem('fc-v3-execute-plan-1'),pendingStatusKey,'a job key with unknown state is not a confirmed receipt');
  executeStatus='done';await elements['v3-execute-now'].events.click();
  assert.equal(executeBodies.at(-1).request_key,pendingStatusKey);
  executeStatus='queued';
  await elements['v3-execute-now'].events.click();
  const currentJob=elements['v3-execution-job'].textContent;
  assert.match(elements['v3-execution-progress'].textContent,/已排队，等待采价/);
  assert.equal(elements['v3-execute-now'].disabled,true);
  assert.equal(progressTimers.size,1);
  state.manual_execution={job_key:'manual:older-job',plan_id:'plan-1',status:'done',phase:'completed'};
  await tickProgress();
  assert.match(elements['v3-execution-progress'].textContent,/已排队/);
  assert.equal(progressTimers.size,1);
  state.manual_execution={job_key:currentJob,plan_id:'plan-1',status:'running',phase:'collecting'};
  const readsBefore=stateReads;
  let finishStateRead;
  stateReadGate=new Promise(resolve=>{finishStateRead=resolve;});
  const progressRead=tickProgress();
  const normalRefresh=elements['v3-refresh'].events.click();
  assert.equal(stateReads,readsBefore+1,'the full refresh waits for the in-flight state read');
  stateReadGate=null;finishStateRead();await progressRead;await normalRefresh;
  assert.match(elements['v3-execution-progress'].textContent,/正在采价/);
  assert.equal(progressTimers.size,1);
  document.hidden=true;documentEvents.visibilitychange();assert.equal(progressTimers.size,0);
  document.hidden=false;documentEvents.visibilitychange();assert.equal(progressTimers.size,1);
  pageEvents.pagehide();assert.equal(progressTimers.size,0);
  pageEvents.pageshow();assert.equal(progressTimers.size,1);
  state.manual_execution={...state.manual_execution,status:'done',phase:'original_operation_reconciliation_pending'};
  await tickProgress();
  assert.match(elements['v3-execution-progress'].textContent,/等待原操作对账，尚未开始新采价/);
  assert.equal(progressTimers.size,0,'terminal receipt stops the short polling');
  assert.equal(elements['v3-execute-now'].disabled,false);
  elements['v3-uplift-enabled'].checked=true;elements['v3-uplift-pct'].value='10';
  elements['v3-price-control-form'].events.input();
  assert.match(elements['v3-price-control-draft'].textContent,/未保存/);
  priceFailure=true;elements['v3-price-control-form'].events.submit({preventDefault(){}});await tick();
  const pendingPrice=priceBodies.at(-1);
  assert.match(elements['v3-price-control-result'].textContent,/尚未确认/);
  assert.equal(elements['v3-uplift-pct'].disabled,true,'unknown save freezes the original payload');
  priceFailure=false;elements['v3-price-control-form'].events.submit({preventDefault(){}});await tick();
  assert.deepEqual(priceBodies.at(-1),pendingPrice,'price settings retry the original ID and payload');
  assert.equal(sessionStorage.getItem('fc-v3-price-control-pending'),null);
  assert.match(elements['v3-effective-control'].textContent,/临时上浮 10%/);
  assert.match(elements['v3-price-control-result'].textContent,/保存没有立即写价/);
  plan.mode='smart';plan.smart_strategy_version='smart-three-platform-v3';
  market.snapshot_id=state.snapshot_id;
  plan.parameters={competitor_policy:'lootbar_primary_arabut_secondary_v1',region_pricing:'global'};
  state.strategies.smart={status:'READY',smart_assignment:{strategy_version:'smart-three-platform-v3',label:'MIXED',block:0,
    group_labels:{PS:'B',XBOX:'A',PC:'C'},group_pair_ids:{console:'0:1',pc:'0:2'},no_space_by_group:{PS:true,XBOX:false,PC:false},
    merged_with_A_by_group:{console:true,pc:false},policy:{group_results:{PS:{winner:'B'},XBOX:{},PC:{winner:'C'}}}},
    selected:{action:{base_prices:{PS:'8.51',XBOX:'8.45',PC:'8.59'}},score:{absolute_forecast_available:false}}};
  market.arab=[{platform:'PC',region_id:21,source_region_id:21,reference_scope:'global',delivery:'standard',
    total_usd:'9.47',purchase_k:'100',bonus_k:'0',captured_at:new Date().toISOString(),selection_verified:true}];
  elements['v3-mode'].value='smart';elements['v3-mode'].events.change();await elements['v3-refresh'].events.click();
  const smartText=JSON.stringify(elements['v3-strategies'].children);
  assert.match(smartText,/PS.*B.*XBOX.*A.*PC.*C/);
  assert.match(smartText,/PS.*候选.*合并/);
  assert.match(smartText,/PS.*B.*领先.*PC.*C.*领先/);
  assert.match(elements['v3-mode-purpose'].textContent,/降3%.*涨3%/);
  assert.doesNotMatch(elements['v3-mode-purpose'].textContent,/上调6%/);
  assert.match(elements['v3-proof-notes'].textContent,/Lootbar.*主.*Arab.*次.*ItemD2R.*辅助/);
  assert.match(elements['v3-proof-notes'].textContent,/全球.*系数1/);
  assert.match(marketTag.textContent,/Lootbar.*主锚.*Arab.*次锚.*ItemD2R.*辅助/);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[2]),/PC.*独立.*标准/);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[2]),/\$9\.47/);
  plan.mode='daily';state.strategies.daily.selected.daily_pricing={PC:{driver_source:'ArabUT',driver_platform:'PC',
    target_public_usd:'9.94',selected_base_total:'9.94',item_target_met:true,platforms:{}}};
  elements['v3-mode'].value='daily';await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/PC按ArabUT PC当轮实际交付价定价/);
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/ItemD2R/);
  plan.mode='smart';delete plan.smart_strategy_version;delete plan.parameters;
  elements['v3-mode'].value='smart';elements['v3-mode'].events.change();
  assert.match(elements['v3-mode-purpose'].textContent,/历史智能策略.*B上调3%.*C上调6%/);
  await elements['v3-refresh'].events.click();
  assert.equal(marketTag.textContent,'Lootbar 无券 · ItemD2R · Saudi Arabia 普通发货','legacy plans keep the original market heading');
  plan.smart_strategy_version='market-anchor-v1';plan.write_protocol='fc27_curve_v6';plan.state='ACTIVE';
  state.weekly_ladder={control:{automatic:false,eligible_after:'2099-01-01T00:00:00+08:00'},proposals:[{
    proposal_id:'proposal-1',platform:'PS',band:'small',week_start:'2026-11-23',status:'PROPOSED',
    rule:'raise_position',before_p:'.08',after_p:'.09',expires_at:'2099-01-01T00:00:00+08:00',
    prior:{small:{orders:100,procurement_gross_cny:'1200'}},current:{small:{orders:110,procurement_gross_cny:'1250'}}}]};
  await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-weekly-panel'].hidden,false);
  assert.match(JSON.stringify(elements['v3-weekly-proposals'].children),/8%.*9%/);
  assert.equal(elements['v3-weekly-auto'].disabled,true,'four weeks do not enable themselves');
  canWrite=false;await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-weekly-proposals'].children[0].children.at(-1).children[0].disabled,true);
  canWrite=true;await elements['v3-refresh'].events.click();
  await elements['v3-weekly-proposals'].children[0].children.at(-1).children[0].events.click();
  assert.equal(weeklyBodies.at(-1).url,'/api/fc27/cloud/pricing/v3/weekly-ladder/proposal-1/confirm');
  assert.deepEqual(weeklyBodies.at(-1).body,{expected_revision:plan.revision});
  state.weekly_ladder.proposals[0].expires_at='2000-01-01T00:00:00Z';await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-weekly-proposals'].children[0].children.at(-1).children[0].disabled,true);
  state.weekly_ladder.control.eligible_after='2000-01-01T00:00:00Z';await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-weekly-auto'].disabled,false);
  await elements['v3-weekly-auto'].events.click();
  assert.deepEqual(weeklyBodies.at(-1).body,{enabled:true,expected_revision:plan.revision});
  console.log('UI contract and state smoke passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
