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
assert(html.indexOf('id="v3-result"')<html.indexOf('id="v3-panel"'),'action result is visible beside the top controls');
assert.match(html,/fc-pricing-v3\.js\?v=20261030-console-control/);
assert.match(script,/双20只按购买100K、赠送5K这一档核算/);
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
const document = { getElementById: id => elements[id], createElement: () => new Element(), activeElement: null, hidden: false };
const store = new Map();
const sessionStorage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) };
const plan = { plan_id: 'plan-1', mode: 'daily', state: 'SUSPENDED' };
const state = { plans: [plan], active_plans: [plan], plan, generation: 'g', captured_at: '2026-10-26T13:00:00+08:00', snapshot_id: 'snapshot-1',
  price_control:{revision:0,manual_enabled:false,manual_prices:{console:null,pc:null},uplift_enabled:false,uplift_pct:'0'},
  strategies: { daily: { status: 'READY', selected: { action: { base_prices: { console: '8.51', pc: '8.59' } }, score: { absolute_forecast_available: false } } }, revenue_sprint: { status: 'DATA_PENDING' } },
  operations: [{ operation_id: 'op-1', status: 'COMPLETED', created_at: '2026-10-26T13:05:00+08:00', bundle: { mode: 'daily', review_approved: false, decision_source: 'v3_explicit_deterministic_feasible_assignment' } }],
  target: { mtd_lower_bound: '666454.13', mtd_upper_bound: '666464.47', through_date: '2026-10-25', today: { status: 'unavailable' } }, region_rules: [], regional_controls: [], incidents: [] };
let canWrite = true, intervalBody;
const automation = { revision: 3, can_manage_v3: true, system_enabled:true,mode:'auto',platforms:['PS','XBOX','PC'],minimum_gross_margin_pct:'20', v3: { schedule: { cycle_interval_minutes: 120, active_plan_state: 'SUSPENDED', next_cycle_at: null,
  last_cycle_at: '2026-10-26T13:00:00+08:00', last_source_checked_at: null, last_execution_stage: 'COMPLETED' } } };
const monitor = { storefront: { rows: { PS: { package_usd: 8.51, checked_at: '2026-10-26T13:07:00+08:00' },
  XBOX: { package_usd: 8.51 }, PC: { package_usd: 8.59 } } }, publication: { status: 'matched' } };
let marketError=false;
const market={snapshot_id:'snapshot-1',global_offers:{PS:{Lootbar:{usd_price:'9.18',base_k:'100',bonus_k:'5',checked_at:new Date().toISOString()}}},reference:{offers:[{platform:'PS',gross_usd:'8.14',purchase_k:'100',bonus_k:'0',status:'valid',captured_at:'2000-01-01T00:00:00Z'}]},arab:[]};
market.saudi_missing_price_policy='follow_global';
market.price_basis={historical_retained_ratio:'.9',rows:{PS:{cost_usd_per_1k:'.04',cost_cny_per_1k:'.28',package_cost_usd:'4.2',delivered_k:'105',regular_floor_usd:'5.30',average_floor_usd:'5.80',current_regular_margin_pct:'40',current_average_margin_pct:'30',cost_checked_at:'2026-10-27T00:00:00Z'}}};

const normalFetch = async (url, options = {}) => ({ ok: true, json: async () => url.endsWith('/pricing/v3/interval') ? (intervalBody = JSON.parse(options.body), { revision: 4 })
  : url.endsWith('/pricing/v3/preview') ? {results:{smart:{status:'READY',selected:{action:{base_prices:{console:'10',pc:'11'}}}}}}
  : url.endsWith('/pricing/v3/market') ? (marketError?Promise.reject(Error('fixture unavailable')):market)
  : url.endsWith('/pricing/collect') ? {job_id:'collect-test'} : url.endsWith('/jobs/collect-test') ? {status:'ready',result:{status:'INFEASIBLE'}}
  : url.endsWith('/pricing/v3/state') ? state : url.endsWith('/automation') ? (options.body?(intervalBody=JSON.parse(options.body),{revision:4}):{ ...automation, can_manage_v3: canWrite })
  : url.endsWith('/monitor') ? monitor : url.endsWith('/player-sync') ? { enabled: true, revision: 1 } : {} });
const executeBodies=[];
const priceBodies=[];let priceFailure=false;
let executeGate=null,releaseExecution=null,executeFailure=false,executeReplyMissing=false,executeReject=null,executeStatus='queued',idSequence=0;
const fetch=async (url,options={})=>{
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
vm.runInNewContext(script, { document, fetch, sessionStorage, crypto: { randomUUID: () => 'new-id-'+(++idSequence) }, AbortSignal: { timeout: () => null },
  setInterval: () => {}, Intl, Date, console });
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
(async () => {
  await tick();
  state.active_plans.push({mode:'revenue_sprint',resources:['base:console','base:pc'],parameters:{preferred_undercut_pct:'5'}});
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
  assert.match(elements['v3-review-source'].textContent,/最近原操作 op-1：Order与Admin已确认.*公开读回状态单独列示/);
  assert.match(elements['v3-public-status'].textContent,/mismatch/,'separate public mismatch remains visible');
  delete state.operations[0].order_close;monitor.publication.status='matched';await elements['v3-refresh'].events.click();
  assert.match(elements['v3-stage'].textContent,/公开核验完成/,'legacy public-confirmed completion label is preserved');
  assert.match(elements['v3-source-time'].textContent, /待核/);
  assert.equal(elements['v3-strategies'].children.length, 1, 'only selected strategy is shown');
  elements['v3-mode'].value='revenue_sprint';
  state.strategies.revenue_sprint={status:'READY',selected:{decision_type:'floor_fallback',action:{base_prices:{console:'7.15',pc:'8.31'}},score:{absolute_forecast_available:false}}};
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/双20可写，未达到竞争目标/);
  elements['v3-mode'].value='daily';
  await elements['v3-refresh'].events.click();
  state.strategies.daily.selected.daily_pricing={console:{driver_platform:'XBOX',target_public_usd:'8.55',selected_base_total:'8.55',item_target_met:true,platforms:{PS:{actual_unit_100k:'8.142857',reference_source:'Lootbar',difference_pct:'-10'},XBOX:{actual_unit_100k:'8.142857',reference_source:'ItemD2R',difference_pct:'.035'}}}};
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/Console共价按ItemD2R XBOX当轮实际交付价定价/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/达到Item目标（按公开分币舍入）/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/PS.*本平台参考 Lootbar.*价差 -10.00%/);
  state.strategies.daily.selected.daily_pricing.console.item_target_met=false;
  state.strategies.daily.selected.daily_pricing.console.selected_base_total='11.67';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/财务底价抬高，未达到Item目标/);
  assert.match(JSON.stringify(elements['v3-strategies'].children),/双20可写，未达到ItemD2R目标/);
  state.strategies.daily.selected.daily_pricing.console.unmet_reason='public_cent_not_reachable';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/舍入导致目标未命中，未达到Item目标/);
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/财务底价抬高/);
  delete state.strategies.daily.selected.daily_pricing;await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-interval-minutes'].value, 120);
  assert(html.indexOf('id="plan-title"')<html.indexOf('id="current-title"'),'unified controls precede price monitoring');
  assert(html.indexOf('id="current-title"')<html.indexOf('id="v3-market-title"'),'current prices precede competitor details');
  assert.equal(elements['v3-market-cards'].children.length,3);
  const marketText=JSON.stringify(elements['v3-market-cards'].children);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/历史七日平均红线/);
  market.price_basis.history_window_contract='d9_d2_eight_closed_days_v1';
  await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/D-9至D-2八日平均红线/);
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
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/七日平均红线.*5.80.*当前45.2%/);
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
  assert.match(elements['v3-result'].textContent,/改价任务已登记.*manual:/);
  assert.match(elements['v3-result'].textContent,/实际结果以执行状态和读回为准/);
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
  executeStatus='queued';await elements['v3-execute-now'].events.click();
  assert.equal(executeBodies.at(-1).request_key,pendingStatusKey);
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
  plan.mode='smart';plan.smart_strategy_version='smart-bidirectional-v2';
  market.snapshot_id=state.snapshot_id;
  plan.parameters={competitor_policy:'lootbar_primary_arabut_secondary_v1',region_pricing:'global'};
  state.strategies.smart={status:'READY',smart_assignment:{strategy_version:'smart-bidirectional-v2',label:'MIXED',block:0,
    group_labels:{console:'B',pc:'C'},group_pair_ids:{console:'0:1',pc:'0:2'},no_space_by_group:{console:true,pc:false},
    merged_with_A_by_group:{console:true,pc:false},policy:{group_results:{console:{winner:'B'},pc:{winner:'C'}}}},
    selected:{action:{base_prices:{console:'8.51',pc:'8.59'}},score:{absolute_forecast_available:false}}};
  market.arab=[{platform:'PC',region_id:21,source_region_id:21,reference_scope:'global',delivery:'standard',
    total_usd:'9.47',purchase_k:'100',bonus_k:'0',captured_at:new Date().toISOString(),selection_verified:true}];
  elements['v3-mode'].value='smart';elements['v3-mode'].events.change();await elements['v3-refresh'].events.click();
  const smartText=JSON.stringify(elements['v3-strategies'].children);
  assert.match(smartText,/Console.*B.*PC.*C/);
  assert.match(smartText,/Console.*候选.*合并/);
  assert.match(smartText,/Console.*B.*领先.*PC.*C.*领先/);
  assert.match(elements['v3-mode-purpose'].textContent,/降3%.*涨3%/);
  assert.doesNotMatch(elements['v3-mode-purpose'].textContent,/上调6%/);
  assert.match(elements['v3-proof-notes'].textContent,/Lootbar.*主.*Arab.*次.*ItemD2R.*辅助/);
  assert.match(elements['v3-proof-notes'].textContent,/全球.*系数1/);
  assert.match(marketTag.textContent,/Lootbar.*主锚.*Arab.*次锚.*ItemD2R.*辅助/);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[2]),/PC.*独立.*标准/);
  assert.match(JSON.stringify(elements['v3-market-cards'].children[2]),/\$9\.47/);
  plan.mode='daily';state.strategies.daily.selected.daily_pricing={pc:{driver_source:'ArabUT',driver_platform:'PC',
    target_public_usd:'9.94',selected_base_total:'9.94',item_target_met:true,platforms:{}}};
  elements['v3-mode'].value='daily';await elements['v3-refresh'].events.click();
  assert.match(JSON.stringify(elements['v3-strategies'].children),/PC按ArabUT PC当轮实际交付价定价/);
  assert.doesNotMatch(JSON.stringify(elements['v3-strategies'].children),/ItemD2R/);
  plan.mode='smart';delete plan.smart_strategy_version;delete plan.parameters;
  elements['v3-mode'].value='smart';elements['v3-mode'].events.change();
  assert.match(elements['v3-mode-purpose'].textContent,/上调3%.*上调6%/,'legacy plans retain their actual policy');
  await elements['v3-refresh'].events.click();
  assert.equal(marketTag.textContent,'Lootbar 无券 · ItemD2R · Saudi Arabia 普通发货','legacy plans keep the original market heading');
  console.log('UI contract and state smoke passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
