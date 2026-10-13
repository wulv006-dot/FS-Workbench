const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = path.join(__dirname, '../source/game-monitor');
const html = fs.readFileSync(path.join(base, 'index.html'), 'utf8');
const source = fs.readFileSync(path.join(base, 'fs-integration.js'), 'utf8');
for (const script of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script[1]);
new vm.Script(source);
for (const asset of new Set(html.match(/assets\/[a-zA-Z0-9_/., -]+\.(?:jpg|jpeg|png|webp|svg|gif)/g))) {
  assert.ok(fs.existsSync(path.join(base, asset)), asset);
}
assert.ok(!html.includes('定时脚本自动更新'));
assert.ok(!html.includes('/*__RG_JS_START__*/'));
for (const falseClaim of ['每周一采集', '每周一 10:00 自动采集', '已提交采集请求', '采集请求已提交', '>⟳ 采集信息<', '最近采集 ']) assert.ok(!html.includes(falseClaim), falseClaim);
let snapshotClick, snapshotNotice = '';
const snapshotButton = {disabled:false,addEventListener:(type,fn)=>snapshotClick=fn};
const bindSnapshot = html.slice(html.indexOf('function bindFC(){'), html.indexOf('function renderFCtoast(msg){'));
vm.runInNewContext(bindSnapshot + '\nbindFC();', {document:{getElementById:id=>id === 'fcCollectBtn' ? snapshotButton : null},renderFCtoast:text=>snapshotNotice=text});
snapshotClick(); snapshotClick();
assert.ok(snapshotNotice.includes('历史模式仅展示原包资料'));
assert.equal(snapshotButton.disabled,false,'snapshot information remains reusable');
const day = {textContent:''}, hour = {textContent:''};
const countdown = {dataset:{target:'2026-10-15T03:00:00Z'},querySelector:selector=>selector === '.d' ? day : hour};
const nav = {dataset:{target:'sec-radar'},querySelector:()=>null};
const tickCountdown = html.slice(html.indexOf('function tickCd(){'),html.indexOf('function tickClock(){'));
vm.runInNewContext(tickCountdown + '\ntickCd();', {
  document:{querySelectorAll:selector=>selector === '[data-target]' ? [nav,countdown] : selector === '.modal-cd-big[data-target]' ? [countdown] : []},
  Date:class extends Date { static now(){return new Date('2026-10-13T00:00:00Z').getTime();} },
  MS_DAY:86400000,pad:value=>String(value).padStart(2,'0')
});
assert.equal(day.textContent,2,'modal countdown still updates despite navigation data-target attributes');
assert.equal(hour.textContent,'03');

class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.value = ''; this.textContent = ''; this.disabled = false; this.listeners = {}; this.attrs = {}; }
  append(...items) { this.children.push(...items); for (const item of items) item.parent = this; if (this.tag === 'select' && this.value === '' && items[0]) this.value = items[0].value; }
  replaceChildren(...items) { this.children = []; this.value = ''; this.append(...items); }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  remove() { this.parent.children = this.parent.children.filter(item => item !== this); }
}
const flush = () => new Promise(resolve => setImmediate(resolve));
async function fixture(role = 'admin', eventDate = '2026-10-13', mode = 'direct', storage = new Map()) {
  const ids = Object.fromEntries(['fsGame','fsEvent','fsInsightButton','fsInsightStatus','fsInsightText','fsInsightReceipt','fsSessionStatus'].map(id => [id, new Element(id === 'fsGame' || id === 'fsEvent' ? 'select' : 'div')]));
  const body = new Element('body'); Object.values(ids).forEach(el => body.append(el));
  const document = {body, hidden: false, getElementById: id => ids[id], createElement: tag => new Element(tag), addEventListener() {}};
  let denied = false, transportFails = false, user = 'test', pollFailure = mode === 'poll_failure';
  const requests = [], listeners = {}, intervals = [], polls = [], postedHeaders = [];
  const headers = entries => ({get: key => entries[key] || ''});
  const success = {status:'succeeded',text:'<script>untrusted</script>',model:'fixture',receipt:'receipt-test',tokens:3};
  const response = value => ({status:200,ok:true,headers:headers({'content-type':'application/json'}),json:async()=>value});
  const fetch = async (url, options) => {
    if (url === '/__auth/verify') return {status: denied ? 401 : 200, ok: !denied, headers: headers({'X-Auth-Groups':'dashboard','X-Auth-Role':role,'X-Auth-User':user})};
    if (url.startsWith('/dashboard/fs-home/advisor.json?id=')) {
      polls.push(url);
      assert.equal(options.method, undefined, 'poll uses GET');
      if (pollFailure) { pollFailure = false; throw Error('transport_failed'); }
      if (mode === 'identity_changed') user = 'other-admin';
      if (mode === 'poll_timeout' || (mode === 'pending' && polls.length === 1)) return response({job:{state:'running'}});
      if (mode === 'source_denied') return response({job:{state:'failed',error:'source_permission_denied'}});
      if (mode === 'model_failure') return response({job:{state:'completed',result:{status:'configuration_missing',text:''}}});
      if (mode === 'not_found') return {status:404,ok:false,headers:headers({})};
      return response({job:{state:'completed',result:success}});
    }
    requests.push(JSON.parse(options.body));
    assert.ok([...storage.values()].some(value=>JSON.parse(value).request_id === 'test-request-id'),'request intent must be durable before POST');
    postedHeaders.push(options.headers);
    if (transportFails) throw Error('timeout');
    if (mode === 'daily_limit') return {...response({reason:'daily_model_limit'}),status:429,ok:false};
    if (mode === 'safe_failure') return response({status:'failed',reason:'configuration_missing',stack:'MUST NOT SHOW'});
    return response(mode === 'direct' ? success : {status:'pending',job_id:'job-test',retryAfter:3});
  };
  const window = {GAME_TIMELINE_DATA:{games:[{name_en:'Game',owner:'NEVER SEND',sales:999,events:[{title:'Event',date:eventDate,source:'https://example.com/event?private=remove#fragment',secret:'NEVER SEND'},{title:'Other event',date:eventDate,source:'https://example.com/other'}]}]},addEventListener:(event,fn)=>listeners[event]=fn};
  const sessionStorage = {getItem:key=>storage.get(key)||null,setItem:(key,value)=>{if(mode==='storage_failure')throw Error('quota');storage.set(key,value);},removeItem:key=>storage.delete(key)};
  vm.runInNewContext(source,{window, document, sessionStorage, fetch, AbortController, AbortSignal, URL, Date, crypto:{randomUUID:()=> 'test-request-id'},setTimeout:(fn,ms)=>setTimeout(fn,ms === 180000 && mode === 'poll_timeout' ? 20 : ms < 10000 ? 0 : ms),clearTimeout,setInterval:fn=>intervals.push(fn),clearInterval});
  await flush();
  return {ids, body, requests, listeners, intervals, polls, postedHeaders, storage, deny:()=>denied=true, fail:()=>transportFails=true};
}
(async () => {
  const f = await fixture();
  assert.equal(f.ids.fsInsightButton.disabled, false);
  await f.ids.fsInsightButton.listeners.click();
  assert.deepEqual(f.requests, [{scope:'game-monitor',request_id:'test-request-id',context:{events:[{game:'Game',title:'Event',date:'2026-10-13',source_url:'https://example.com/event'}]}}]);
  assert.equal(f.ids.fsInsightText.textContent,'<script>untrusted</script>');
  assert.equal(f.ids.fsInsightText.children.length,0,'model text must not create HTML');
  await f.intervals[0]();
  assert.equal(f.ids.fsInsightText.textContent,'<script>untrusted</script>','session polling must retain valid results');
  f.deny(); await f.listeners.focus();
  assert.equal(f.ids.fsInsightText.textContent,'');
  assert.equal(f.body.children.length,1,'denied sessions discard page content');

  const invalid = await fixture('admin','2026-02-30');
  assert.equal(invalid.ids.fsInsightButton.disabled,true);
  await invalid.ids.fsInsightButton.listeners.click(); assert.equal(invalid.requests.length,0);
  const member = await fixture('member');
  assert.equal(member.ids.fsInsightButton.disabled,true);
  await member.ids.fsInsightButton.listeners.click(); assert.equal(member.requests.length,0);
  const timeout = await fixture(); timeout.fail();
  await timeout.ids.fsInsightButton.listeners.click(); await flush();
  assert.equal(timeout.requests.length,1,'failed POST never automatically retries');
  assert.ok(timeout.ids.fsInsightStatus.textContent.includes('未自动重试'));
  assert.ok(timeout.ids.fsInsightReceipt.textContent.includes('test-request-id'));
  assert.equal(timeout.ids.fsInsightButton.disabled,true,'unknown POST without job must block repeat');
  await timeout.ids.fsInsightButton.listeners.click();
  assert.equal(timeout.requests.length,1);
  timeout.ids.fsEvent.value='1'; timeout.ids.fsEvent.listeners.change();
  assert.equal(timeout.ids.fsInsightButton.disabled,false);
  timeout.ids.fsEvent.value='0'; timeout.ids.fsEvent.listeners.change();
  assert.equal(timeout.ids.fsInsightButton.disabled,true,'selection changes preserve unresolved request');
  const refreshedUnknown = await fixture('admin','2026-10-13','direct',timeout.storage);
  assert.equal(refreshedUnknown.ids.fsInsightButton.disabled,true);
  await refreshedUnknown.ids.fsInsightButton.listeners.click();
  assert.equal(refreshedUnknown.requests.length,0,'refresh cannot repeat unknown POST');
  assert.ok(refreshedUnknown.ids.fsInsightReceipt.textContent.includes('test-request-id'));
  const pending = await fixture('admin','2026-10-13','pending');
  await pending.ids.fsInsightButton.listeners.click();
  assert.equal(pending.requests.length,1);
  assert.equal(pending.postedHeaders[0]['X-FS-Advisor-Action'],'submit');
  assert.equal(pending.postedHeaders[0]['Sec-Fetch-Site'],undefined);
  assert.deepEqual(pending.polls,['/dashboard/fs-home/advisor.json?id=job-test','/dashboard/fs-home/advisor.json?id=job-test']);
  assert.ok(pending.ids.fsInsightReceipt.textContent.includes('job-test'));
  assert.equal(pending.ids.fsInsightText.textContent,successText());
  const resume = await fixture('admin','2026-10-13','poll_failure');
  await resume.ids.fsInsightButton.listeners.click();
  assert.ok(resume.ids.fsInsightStatus.textContent.includes('仍可凭编号查询，不自动重提'));
  assert.equal(resume.ids.fsInsightButton.textContent,'查询已有解读任务');
  resume.ids.fsEvent.value='1'; resume.ids.fsEvent.listeners.change();
  resume.ids.fsEvent.value='0'; resume.ids.fsEvent.listeners.change();
  assert.equal(resume.ids.fsInsightButton.textContent,'查询已有解读任务','selection changes retain known job');
  const refreshedKnown = await fixture('admin','2026-10-13','direct',new Map(resume.storage));
  await refreshedKnown.ids.fsInsightButton.listeners.click();
  assert.equal(refreshedKnown.requests.length,0,'refresh with job uses only GET');
  assert.equal(refreshedKnown.polls.length,1);
  await resume.ids.fsInsightButton.listeners.click();
  assert.equal(resume.requests.length,1,'manual job query never re-POSTs');
  assert.equal(resume.polls.length,2);
  assert.equal(resume.ids.fsInsightText.textContent,successText());
  const pollingTimeout = await fixture('admin','2026-10-13','poll_timeout');
  await pollingTimeout.ids.fsInsightButton.listeners.click();
  assert.equal(pollingTimeout.requests.length,1);
  assert.ok(pollingTimeout.ids.fsInsightStatus.textContent.includes('仍可凭编号查询，不自动重提'));
  assert.ok(pollingTimeout.ids.fsInsightReceipt.textContent.includes('job-test'));
  const changed = await fixture('admin','2026-10-13','identity_changed');
  await changed.ids.fsInsightButton.listeners.click();
  assert.equal(changed.ids.fsInsightText.textContent,'','other identity cannot display result');
  const safe = await fixture('admin','2026-10-13','safe_failure');
  await safe.ids.fsInsightButton.listeners.click();
  assert.equal(safe.ids.fsInsightStatus.textContent,'服务器尚未配置模型。');
  assert.equal(safe.ids.fsInsightText.textContent,'');
  assert.ok(!safe.ids.fsInsightReceipt.textContent.includes('模型：'));
  const sourceDenied = await fixture('admin','2026-10-13','source_denied');
  await sourceDenied.ids.fsInsightButton.listeners.click();
  assert.equal(sourceDenied.ids.fsInsightStatus.textContent,'当前账号无权读取该任务来源。');
  const modelFailure = await fixture('admin','2026-10-13','model_failure');
  await modelFailure.ids.fsInsightButton.listeners.click();
  assert.equal(modelFailure.ids.fsInsightStatus.textContent,'服务器尚未配置模型。');
  assert.ok(!modelFailure.ids.fsInsightReceipt.textContent.includes('模型：'));
  const missing = await fixture('admin','2026-10-13','not_found');
  await missing.ids.fsInsightButton.listeners.click();
  assert.equal(missing.ids.fsInsightStatus.textContent,'该任务不存在或不属于当前账号，请核对任务编号。');
  const storageFailure = await fixture('admin','2026-10-13','storage_failure');
  await storageFailure.ids.fsInsightButton.listeners.click();
  assert.equal(storageFailure.requests.length,0,'failed intent storage prevents POST');
  const dailyLimit = await fixture('admin','2026-10-13','daily_limit');
  await dailyLimit.ids.fsInsightButton.listeners.click();
  assert.ok(dailyLimit.ids.fsInsightStatus.textContent.includes('今日模型调用额度已用完'));
  assert.equal(dailyLimit.storage.size,0,'explicit rejection ends intent record');
  console.log('PASS game monitor: inline syntax, 97 assets, minimal payload, safe text, auth, async GET polling/resume, identity isolation, safe failures, no re-POST');
})().catch(error => {console.error(error); process.exitCode = 1;});
function successText() { return '<script>untrusted</script>'; }
