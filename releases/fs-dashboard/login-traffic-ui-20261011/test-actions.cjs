'use strict';
// Exercise the shipped handlers with an in-memory DOM and HTTP responses.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.events={}; this.dataset={}; this.textContent=''; this.value=''; }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children=items; }
  addEventListener(name, handler) { this.events[name]=handler; }
  querySelector() { return this.button || (this.button=new Element('button')); }
  querySelectorAll() { return this.children; }
  getClientRects() { return [1]; }
  scrollIntoView() {}
  reset() { this.resetCalled=true; }
}
const ids=Object.fromEntries(['home','open-register','back-login','login-panel','register-panel','message','guest','native-box','account','admin','logout','state','request','apply','approved','register','login','native-login','theme','requests','more','selection','select-all','bulk-approve','bulk-reject','bulk-revoke','bulk-reason','results','refresh','audit-button','audit'].map(id=>[id,new Element()]));
for (const id of ['register','login','native-login','apply']) {
  const button=new Element('button'), alert=new Element('p');
  ids[id].querySelector=selector=>selector==='button'?button:alert;
  ids[id].fields={username:'fixture',password:'wrong-fixture-password'};
}
let calls=[], failures={}, checks=0, confirmResult=true;
function check(value, description) { assert.ok(value,description); checks++; }
const context=vm.createContext({
  document:{body:{dataset:{}},getElementById:id=>ids[id],createElement:tag=>new Element(tag),documentElement:{dataset:{theme:'light'}}},
  FormData:class { constructor(form){this.form=form;} [Symbol.iterator](){return Object.entries(this.form.fields)[Symbol.iterator]();} },
  confirm:()=>confirmResult, prompt:()=> '人工核实测试',
  fetch:async (url, options)=> {
    if(url.endsWith('bootstrap')) return {ok:true,status:200,json:async()=>({csrf:'fixture-csrf',account:{role:'guest'}})};
    if(url.includes('requests?')) return {ok:true,status:200,json:async()=>({items:[]})};
    const body=JSON.parse(options.body); calls.push({url,body,headers:options.headers});
    const status=url.endsWith('login')?401:(failures[body.request_id]??200);
    if(status===0) throw new Error('transport lost');
    return {ok:status===200,status,json:async()=>({error:status===401?'invalid credentials':'申请已变化'})};
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'auth-web/app.js'),'utf8'),context);
const invoke=code=>vm.runInContext(code,context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  const items=[1,2,3].map(i=>({id:String(i),name:'fixture_'+i,status:'pending',version:i}));
  context.fixtureItems=items;
  await invoke('decideRows(fixtureItems,"approve","人工核实测试")');
  check(calls.length===3,'all selected accounts called exactly once');
  check(calls.every(c=>c.url.endsWith('decision')&&c.body.action==='approve'&&c.body.version===Number(c.body.request_id)&&c.headers['X-CSRF-Token']==='fixture-csrf'),'existing CAS/CSRF contract retained');
  check(ids.results.children.length===3,'individual outcomes persist');
  calls=[]; failures={'2':409};
  await invoke('decideRows(fixtureItems,"reject","人工核实测试")');
  check(calls.length===3&&ids.message.textContent.includes('失败 1'),'CAS conflict cannot become all-success');
  for (const status of [0,503,403,429]) {
    calls=[]; failures={'2':status};
    await invoke('decideRows(fixtureItems,"revoke","人工核实测试")');
    check(calls.length===2,'uncertain or unauthorized response stops subsequent writes');
    check(calls.every(c=>c.url.endsWith('revoke')&&!('action' in c.body)),'revoke payload retained');
  }
  calls=[]; failures={}; confirmResult=false;
  await invoke('decideRows(fixtureItems,"approve","人工核实测试")');
  check(!calls.length,'cancel performs no write');
  confirmResult=true;
  await invoke('decideRows(fixtureItems,"approve"," ")');
  check(!calls.length,'blank reason performs no write');
  for (const id of ['login']) {
    await ids[id].events.submit({preventDefault(){},currentTarget:ids[id]});
    check(ids[id].querySelector('[role=alert]').textContent==='账号或密码错误，请检查后重试。','credential error is inline and Chinese');
    check(!ids[id].querySelector('button').disabled&&!ids[id].resetCalled,'failure preserves inputs and restores button');
  }
  console.log(JSON.stringify({passed:true,checks,scope:'actual front-end action handlers; synthetic DOM/HTTP; no real accounts'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
