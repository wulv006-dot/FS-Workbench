'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'strategy.js'),'utf8');new vm.Script(source);
let assertions=0;const check=(v,m)=>{assert.ok(v,m);assertions++;};
class Element{
  constructor(tag='div'){this.tag=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.handlers={};}
  append(...values){this.children.push(...values);}replaceChildren(...values){this.children=[...values];}
  addEventListener(name,handler){this.handlers[name]=handler;}get options(){return this.children.filter(c=>c.tag==='option');}
}
const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={getElementById:element,createElement:tag=>new Element(tag)};
const lesson='<img src=x onerror=alert(1)> test method';
const learning={sha256:'a'.repeat(64),experiences:[],events:[],candidates:[{id:'b'.repeat(64),content_hash:'c'.repeat(64),risk:'L1',event:'d'.repeat(64),expires_at:'2026-11-20T00:00:00+08:00',content:JSON.stringify({lesson,applies_to:'合成测试',counterexample:'有条件',evidence_refs:['ev_test']})}],publication_events:[],paused:false};
const workspace={enabled:true,capabilities:{status:'available',baseline_policy:{revision:38}},drafts:[],simulations:[],method_candidates:[],action_history:[]};
let failure=null,teachState='queued';const requests=[];
const context={document,console,Map,Set,AbortSignal,FormData:class{constructor(form){this.form=form;}get(k){return this.form.formValues[k];}},fetch:async(url,options)=>{
  const body=JSON.parse(options.body);requests.push({url,options,body});if(failure)throw failure;
  const value=body.kind==='hermes_learning'?learning:workspace;
  if(body.action==='enqueue')return {ok:true,json:async()=>({id:'f'.repeat(64),state:teachState})};
  if(body.action==='review_model')return {ok:true,json:async()=>({id:body.event,state:'running'})};
  if(body.action==='publish')return {ok:false,json:async()=>({error:'publication_conflict'})};
  return {ok:true,json:async()=>value};
}};
vm.createContext(context);vm.runInContext(source,context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
const tags=node=>[node.tag,...node.children.flatMap(tags)];
(async()=>{
  await flush();check(requests.length===2,'initial view reads only two existing entry lists');
  check(requests.every(r=>r.body.action==='list'&&r.url==='/dashboard/fs-home/advisor.json'&&r.options.credentials==='same-origin'&&r.options.redirect==='error'),'same-origin existing endpoint only');
  check(text(element('strategy-records')).includes('尚无本范围策略草案'),'honest empty draft state');
  check(text(element('strategy-actions')).includes('不代表从未做过运营'),'empty ledger does not invent history');
  check(text(element('learning-records')).includes(lesson),'untrusted text is preserved visibly');
  check(!tags(element('learning-records')).includes('img'),'untrusted candidate does not become markup');
  check(element('strategy-review-submit').disabled,'no fake review selection when empty');
  check(!element('learning-submit').disabled,'an available candidate can be reviewed');
  check(element('learning-reflect-submit').disabled,'teaching requires a real owned completed report source');
  element('learning-version').value='b'.repeat(64);element('learning-reason').value='合成审核理由，非生产批准。';const form=element('learning-publish');form.formValues={action:'publish'};
  const pending=form.handlers.submit({preventDefault(){},target:form});check(element('learning-submit').disabled,'valid submission prevents duplicate posts');await pending;
  check(element('learning-action-status').textContent.includes('版本已变化'),'CAS conflict is visible');
  check(!element('learning-action-status').textContent.includes('操作已记录'),'conflict is not translated into success');
  const submitted=requests.at(-1).body;check(submitted.expected_manifest===learning.sha256&&!('owner' in submitted)&&!('actor' in submitted),'knowledge operation binds exact manifest without browser identity fields');
  const before=requests.length;failure=Error('transport');await form.handlers.submit({preventDefault(){},target:form});await flush();
  check(requests.length===before+1,'uncertain knowledge operation is never auto-retried');
  check(element('learning-action-status').textContent.includes('核对原状态'),'unknown write directs original-state readback');
  check(!source.includes('innerHTML'),'new views do not insert source markup');
  failure=null;learning.events=[{id:'f'.repeat(64),source:'a'.repeat(32),state:'queued'}];await element('learning-refresh').handlers.click();
  element('learning-source').value='a'.repeat(32);element('learning-feedback').value='请独立核查推断缺口并归纳方法，不照抄答案。';
  const teach=element('learning-reflect'),startTeach=requests.length;await teach.handlers.submit({preventDefault(){},target:teach});
  check(requests.slice(startTeach).filter(r=>r.body.action==='review_model').length===1,'explicit teaching starts exactly one bounded model review');
  check(requests.slice(startTeach).every(r=>r.body.action!=='publish'),'teaching never auto-publishes the model candidate');
  check(element('learning-reflect-status').textContent.includes('迁移能力尚未验证'),'receipt does not claim the model learned');
  teachState='completed';const repeated=requests.length;await teach.handlers.submit({preventDefault(){},target:teach});
  check(!requests.slice(repeated).some(r=>r.body.action==='review_model'),'completed original teaching event is not replayed');
  failure=null;workspace.drafts=[{id:'d'.repeat(64),content_hash:'e'.repeat(64),content:{question:'合成模拟',hypothesis:'不预测需求',review_plan:'核实回执'}}];
  const rows=['PS','XBOX','PC'].map(platform=>({platform,target_page_usd:'10.00',gross_margin_pct:'20.00'}));
  workspace.simulations=[{proposal:'d'.repeat(64),content:{id:'sim_test',candidate:{rows},baseline:{rows},precheck:[{status:'block',reason:'execution unavailable'}],comparisons:[],limitations:['fictional test']}}];
  await element('strategy-refresh').handlers.click();
  check(text(element('strategy-records')).includes('已模拟 · 未申请执行 · 未执行'),'simulation never appears as executed');
  check(tags(element('strategy-records')).filter(t=>t==='tr').length===4,'full PS/XBOX/PC table plus heading');
  check(text(element('strategy-records')).includes('未获执行授权'),'execution boundary remains visible with prices');
  const html=fs.readFileSync(path.join(__dirname,'../source/brain.html'),'utf8');
  for(const id of ['strategy-review-form','learning-publish'])check(html.includes(`id="${id}" action="/dashboard/fs-home/advisor.json" method="post"`),'semantic same-origin form '+id);
  check(html.includes('aria-live="polite"')&&html.includes('aria-describedby="learning-help"'),'dynamic errors and visible field help');
  check(html.includes('学习')&&html.includes('未见过的问题')&&html.includes('learning-reflect-help'),'learning criteria and feedback instructions are visible');
  check(html.includes('fs-tokens.css')&&html.includes('fs-ui.css')&&!html.includes('<style'),'existing shared design system without a private stylesheet');
  console.log(`strategy UI: ${assertions} assertions passed; synthetic DOM/API, no model or production writes`);
})().catch(error=>{console.error(error);process.exitCode=1;});
