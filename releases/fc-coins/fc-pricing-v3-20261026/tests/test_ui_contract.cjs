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
elements['v3-mode'].value = 'daily';
const document = { getElementById: id => elements[id], createElement: () => new Element(), activeElement: null, hidden: false };
const store = new Map();
const sessionStorage = { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) };
const plan = { plan_id: 'plan-1', mode: 'daily', state: 'SUSPENDED' };
const state = { plans: [plan], active_plans: [plan], plan, generation: 'g', captured_at: '2026-10-26T13:00:00+08:00', snapshot_id: 'snapshot-1',
  strategies: { daily: { status: 'READY', selected: { action: { base_prices: { console: '8.51', pc: '8.59' } }, score: { absolute_forecast_available: false } } }, acquisition: { status: 'DATA_PENDING' } },
  operations: [{ operation_id: 'op-1', status: 'COMPLETED', created_at: '2026-10-26T13:05:00+08:00', bundle: { mode: 'daily', review_approved: false, decision_source: 'v3_explicit_deterministic_feasible_assignment' } }],
  target: { mtd_lower_bound: '666454.13', mtd_upper_bound: '666464.47', through_date: '2026-10-25', today: { status: 'unavailable' } }, region_rules: [], regional_controls: [], incidents: [] };
let canWrite = true, intervalBody;
const automation = { revision: 3, can_manage_v3: true, v3: { schedule: { cycle_interval_minutes: 120, active_plan_state: 'SUSPENDED', next_cycle_at: null,
  last_cycle_at: '2026-10-26T13:00:00+08:00', last_source_checked_at: null, last_execution_stage: 'COMPLETED' } } };
const monitor = { storefront: { rows: { PS: { package_usd: 8.51, checked_at: '2026-10-26T13:07:00+08:00' },
  XBOX: { package_usd: 8.51 }, PC: { package_usd: 8.59 } } }, publication: { status: 'matched' } };
let marketError=false;
const market={snapshot_id:'snapshot-1',global_offers:{PS:{Lootbar:{usd_price:'9.18',base_k:'100',bonus_k:'5',checked_at:new Date().toISOString()}}},reference:{offers:[{platform:'PS',gross_usd:'8.14',purchase_k:'100',bonus_k:'0',status:'valid',captured_at:'2000-01-01T00:00:00Z'}]},arab:[]};
market.saudi_missing_price_policy='follow_global';
market.price_basis={rows:{PS:{cost_usd_per_1k:'.04',cost_cny_per_1k:'.28',package_cost_usd:'4.2',delivered_k:'105',regular_floor_usd:'5.30',average_floor_usd:'5.80',cost_checked_at:'2026-10-27T00:00:00Z'}}};
Object.assign(market.reference.offers[0],{bonus_k:'5',gift_equivalence_assumed:true});
const fetch = async (url, options = {}) => ({ ok: true, json: async () => url.endsWith('/pricing/v3/interval') ? (intervalBody = JSON.parse(options.body), { revision: 4 })
  : url.endsWith('/pricing/v3/market') ? (marketError?Promise.reject(Error('fixture unavailable')):market)
  : url.endsWith('/pricing/collect') ? {job_id:'collect-test'} : url.endsWith('/jobs/collect-test') ? {status:'ready',result:{status:'INFEASIBLE'}}
  : url.endsWith('/pricing/v3/state') ? state : url.endsWith('/automation') ? { ...automation, can_manage_v3: canWrite }
  : url.endsWith('/monitor') ? monitor : url.endsWith('/player-sync') ? { enabled: true, revision: 1 } : {} });
vm.runInNewContext(script, { document, fetch, sessionStorage, crypto: { randomUUID: () => 'new-id' }, AbortSignal: { timeout: () => null },
  setInterval: () => {}, Intl, Date, console });
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
(async () => {
  await tick();
  assert.match(elements['v3-current-plan'].textContent, /已暂停/);
  assert.match(elements['v3-next-cycle'].textContent, /已暂停，无下一自然写价轮/);
  assert.match(elements['v3-review-source'].textContent, /历史原操作.*未获模型审核.*当前规则无需逐轮审核/);
  assert.equal(elements['v3-price-pc'].textContent, '$8.59');
  assert.match(elements['v3-source-time'].textContent, /待核/);
  assert.equal(elements['v3-strategies'].children.length, 1, 'only selected strategy is shown');
  assert.equal(elements['v3-interval-minutes'].value, 120);
  assert(html.indexOf('id="v3-market-title"')<html.indexOf('id="plan-title"'),'competitor module precedes strategy');
  assert.equal(elements['v3-market-cards'].children.length,3);
  const marketText=JSON.stringify(elements['v3-market-cards'].children);
  assert.match(marketText,/\$8.74 \/ 100K 实际交付/,'normalize with all 105K delivered');
  assert.match(marketText,/ItemD2R/,'saved sprint reference remains visible under daily strategy');
  assert.match(marketText,/已过 15 分钟/);
  assert.match(marketText,/暂无报价/);
  assert.match(marketText,/赠品等值 5K（估算）/);
  assert.match(marketText,/\$7.75 \/ 100K 金币等值/);
  assert.match(marketText,/缺价 · 跟随全球/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/采购成本.*0.0400/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/未优惠红线.*5.30/);
  assert.match(JSON.stringify(elements['v3-price-basis-ps'].children),/七日平均红线.*5.80/);
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
  assert.deepEqual(intervalBody, { interval_minutes: 180, expected_revision: 3 });
  state.operations[0].bundle.decision_source = 'v3_inherited_reviewed_business_strategy';
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent, /沿用先前已审经营策略/);
  state.operations[0].bundle.decision_source = 'v3_model_reviewed_this_cycle';
  state.operations[0].bundle.review_approved = true;
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent, /本轮 Hermes 实际选择/);
  elements['v3-mode'].value = 'acquisition'; elements['v3-mode'].events.change();
  assert.equal(elements['v3-strategies'].children.length, 1);
  state.operations[0].bundle.review_contract='program_pricing_with_daily_hermes_review_v3';
  state.operations[0].bundle.review_approved=false;
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent,/当前规则：程序逐轮定价，Hermes 每日效果复盘/);
  state.operations[0].bundle.maintenance_purpose='retire_uk_discount_v1';
  await elements['v3-refresh'].events.click();
  assert.match(elements['v3-review-source'].textContent,/用户授权英国临时折扣退出/);
  assert.doesNotMatch(elements['v3-review-source'].textContent,/待核/);
  assert.equal(elements['v3-target-section'].hidden, true);
  elements['v3-mode'].value = 'revenue_sprint'; elements['v3-mode'].events.change();
  assert.equal(elements['v3-target-section'].hidden, false);
  canWrite = false; await elements['v3-refresh'].events.click();
  assert.equal(elements['v3-execute'].disabled, true);
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
  console.log('UI contract and state smoke passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
