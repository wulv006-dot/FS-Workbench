'use strict';
// Execute the production script and actual event handlers with a small DOM/fetch host.
// Layout/visual evidence is covered separately by the Playwright check.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto, createHash} = require('node:crypto');
const A = 'a'.repeat(32), B = 'b'.repeat(32);
const source = fs.readFileSync(path.join(__dirname, 'conversation.js'), 'utf8');
const markup = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const hash = x => createHash('sha256').update(x).digest('hex');
const reply = (value, status=200) => ({ok: status < 400, status, json: async () => structuredClone(value)});
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this._text=''; this.value=''; this.disabled=false; this.files=[]; this.attributes={}; }
  set textContent(x) { this._text=String(x); this.children=[]; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  append(x) { this.children.push(x); }
  replaceChildren(...xs) { this.children=xs; this._text=''; }
  setAttribute(k,v) { this.attributes[k]=v; }
  querySelector(tag) { return this.children.find(x => x.tagName===tag); }
  focus() { this.focused=true; }
  click() { if (!this.disabled) { if (this.type==='checkbox') { this.checked=!this.checked; return this.onchange?.({target:this}); } return this.onclick?.({preventDefault(){}}); } }
  requestSubmit() { return this.onsubmit?.({preventDefault(){}}); }
}
function descendants(root) { return root.children.flatMap(x => [x,...descendants(x)]); }
function backend() {
  return {files: {[A]:[],[B]:[]}, turns:{[A]:[],[B]:[]}, calls:[], uploads:[], denied:false, mode:'ok', lookup404:false, delayed:null};
}
async function boot(state=backend(), storage=new Map()) {
  const nodes = Object.fromEntries([...markup.matchAll(/id="([^"]+)"/g)].map(m => [m[1],new Element()]));
  const timers=new Map(); let tid=0;
  const fetch = async (url, init={}) => {
    const u=new URL(url,'http://localhost'), parts=u.pathname.split('/').filter(Boolean).slice(3);
    const method=init.method || 'GET'; state.calls.push({url,method,body:init.body});
    if (state.denied) return reply({error:'forbidden'},403);
    if (!parts.length) return method==='POST' ? reply({conversation_id:A},201) : reply({items:[A,B].map((conversation_id,i)=>({conversation_id,title:'Chat '+i}))});
    const [cid,kind,id]=parts;
    if (!kind) return reply({conversation_id:cid, title:'Chat '+(cid===A?0:1), turns:state.turns[cid], last_seq:0});
    if (kind==='files' && method==='GET') {
      if (u.searchParams.has('request_id')) {
        const fid=hash(cid+':'+u.searchParams.get('request_id')).slice(0,32);
        return state.lookup404 ? reply({},404) : (state.files[cid].find(f=>f.file_id===fid) ? reply(state.files[cid].find(f=>f.file_id===fid)) : reply({},404));
      }
      return reply({items:state.files[cid]});
    }
    if (kind==='files' && method==='POST') {
      const bytes=Buffer.from(await init.body.arrayBuffer());
      state.uploads.push({cid,id:init.headers['X-FS-Request-ID'],bytes,headers:init.headers});
      if (state.mode==='fail') return reply({},422);
      const file_id=hash(cid+':'+init.headers['X-FS-Request-ID']).slice(0,32);
      const item={file_id,filename:decodeURIComponent(init.headers['X-FS-Filename']),sha256:hash(bytes),size:bytes.length,
        version:1,parent_id:null,status:'available',mime:'text/csv',expires_at:2000000000};
      if (!state.files[cid].some(f=>f.file_id===file_id)) state.files[cid].push(item);
      if (state.mode==='unknown') throw Error('lost upload response');
      if (state.mode==='delay') await new Promise(resolve=>{state.delayed=resolve;});
      return reply(item,201);
    }
    if (kind==='turns') {
      const body=JSON.parse(init.body); state.submitted=body;
      if (state.turnUnknown) throw Error('lost turn response');
      const turn={turn_id:'c'.repeat(32),client_request_id:body.client_request_id,text:body.text,state:'completed',
        file_bindings:{inputs:body.file_ids||[],generated:[]},files:{inputs:state.files[cid].filter(f=>(body.file_ids||[]).includes(f.file_id)),generated:[]},
        reply:'model said /arbitrary/file_id',artifacts:[]};
      state.turns[cid].push(turn); return reply({turn_id:turn.turn_id,state:'completed'},202);
    }
    if (kind==='runs') { state.steered=JSON.parse(init.body); return reply({state:'accepted'},202); }
    if (kind==='materials') {
      state.materialJobs ||= {};
      if (method==='POST' && !id) {
        const body=JSON.parse(init.body);state.materialSubmitted=body;
        state.materialJobs[cid+body.client_request_id]={request_id:body.client_request_id,status:'running',files:[]};
        if (state.materialUnknown) throw Error('lost material acceptance');
        if (state.materialDelay) await new Promise(resolve=>{state.materialRelease=resolve;});
        return reply(state.materialJobs[cid+body.client_request_id],202);
      }
      const job=state.materialJobs[cid+id];
      if (!job) return reply({},404);
      if (parts[3]==='result') return reply({request_id:id,status:'completed',text:'<script>never execute</script>\nanswer /arbitrary/file',truncated:false});
      if (method==='POST') job.status='cancelled';
      return reply(job);
    }
    throw Error('unexpected '+url);
  };
  const context={document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag)},fetch,
    sessionStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    EventSource:class {close(){}}, URL, crypto:webcrypto, Uint8Array, AbortSignal,
    location:{href:'http://localhost/?conversation='+A},history:{replaceState(){}},
    setTimeout:(fn,ms)=>{const id=++tid; if(ms<=350) timers.set(id,fn); return id;},clearTimeout:id=>timers.delete(id),console};
  vm.runInNewContext(source,context,{filename:'conversation.js'});
  async function flush() { for(let i=0;i<12;i++) await new Promise(r=>setImmediate(r)); for(const [id,fn] of [...timers]) {timers.delete(id);fn();} }
  await flush();
  const find=(root,text)=>descendants(nodes[root]).find(x=>x.textContent===text && ['button','a'].includes(x.tagName));
  const checks=()=>descendants(nodes['file-choices']).filter(x=>x.type==='checkbox');
  async function choose(content='a,b\n1,2',name='a.csv') { nodes['file-input'].files=[new File([content],name)]; await nodes['file-input'].onchange(); await flush(); }
  return {nodes,state,storage,flush,choose,find,checks,async send(text='analyze') {nodes['message-input'].value=text;await nodes.composer.requestSubmit();await flush();}};
}
async function run() {
  let ui=await boot();
  await ui.send('plain text'); assert(!('file_ids' in ui.state.submitted));
  ui=await boot(); await ui.choose(); assert.equal(ui.state.uploads.length,1);
  assert.equal(ui.nodes['conversation-title'].title,'Chat 0');
  assert.match(ui.nodes['file-choices'].textContent,/可用/); assert.equal(ui.checks()[0].checked,false);
  ui.nodes.attachments.open=true;
  ui.checks()[0].click(); await ui.send(); assert.equal(ui.state.submitted.file_ids.length,1);
  assert.equal(ui.nodes.attachments.open,false);
  assert.equal(descendants(ui.nodes.messages).filter(x=>x.tagName==='a'&&x.textContent==='下载文件').length,1);
  assert(!descendants(ui.nodes.messages).some(x=>x.href?.includes('arbitrary')));

  // Unknown commit is recovered after refresh with the exact original request and hash.
  ui=await boot(); ui.state.mode='unknown'; await ui.choose(); const originalId=ui.state.uploads[0].id;
  assert.match(ui.nodes['upload-list'].textContent,/待核对/);
  ui=await boot(ui.state,ui.storage); assert(ui.checks()[0].disabled);
  ui.find('upload-list','核对原上传').click(); await ui.flush();
  assert.match(ui.nodes['file-choices'].textContent,/可用/); assert.equal(ui.state.uploads.length,1);
  ui.state.mode='ok';

  // Missing result never makes a new request ID, and changed bytes are rejected.
  ui=await boot(); ui.state.mode='unknown'; await ui.choose(); ui.state.lookup404=true;
  ui.find('upload-list','核对原上传').click(); await ui.flush();
  const before=ui.state.uploads.length; await ui.choose('a,b\n9,8'); assert.equal(ui.state.uploads.length,before);
  ui.state.mode='ok'; ui.state.lookup404=false; await ui.choose();
  assert.equal(ui.state.uploads[1].id,ui.state.uploads[0].id); assert.equal(ui.state.files[A].length,1);

  ui=await boot(); ui.state.mode='fail'; await ui.choose(); assert.match(ui.nodes['upload-list'].textContent,/上传失败/);
  ui.state.mode='ok'; await ui.find('upload-list','重试原文件').click(); await ui.flush();
  assert.equal(ui.state.uploads[1].id,ui.state.uploads[0].id);

  ui=await boot(); await ui.choose('a','bad.exe');
  ui.nodes['file-input'].files=[{name:'too.csv',size:10*1024*1024+1}];
  await ui.nodes['file-input'].onchange(); await ui.flush(); assert.equal(ui.state.uploads.length,0);
  ui=await boot();
  for(let i=0;i<11;i++) ui.state.files[A].push({file_id:hash(String(i)).slice(0,32),filename:i+'.csv',version:1,status:'available'});
  ui=await boot(ui.state,ui.storage);
  for(let i=0;i<10;i++) ui.checks()[i].click();
  assert(ui.checks()[10].disabled); assert.match(ui.nodes['attachment-summary'].textContent,/10 \/ 10/);

  ui=await boot(); await ui.choose(); ui.checks()[0].click(); ui.state.files[A][0].status='expired';
  await ui.send(); assert.equal(ui.state.submitted,undefined); assert(ui.nodes['send-message'].disabled);
  ui.checks()[0].click(); await ui.send('without expired file'); assert(!('file_ids' in ui.state.submitted));

  // A late upload for A must never select or add files to B.
  ui=await boot(); ui.state.mode='delay'; const uploading=ui.choose();
  while(!ui.state.delayed) await new Promise(r=>setImmediate(r));
  await ui.find('conversation-list','Chat 1').click(); await ui.flush();
  ui.state.delayed(); await uploading; await ui.flush();
  assert.equal(ui.checks().length,0); assert.match(ui.nodes['attachment-summary'].textContent,/0 \/ 10/);

  // Pending turn identity and attachment set survive refresh unchanged.
  ui=await boot(); await ui.choose(); ui.checks()[0].click(); ui.state.turnUnknown=true; ui.nodes.attachments.open=true;
  await ui.send('pending'); const pending={...ui.state.submitted};
  assert.equal(ui.nodes.attachments.open,true);
  ui=await boot(ui.state,ui.storage); ui.state.turnUnknown=false; await ui.send();
  assert.equal(ui.state.submitted.client_request_id,pending.client_request_id);
  assert.deepEqual(ui.state.submitted.file_ids,pending.file_ids);

  // Server metadata alone creates derived cards and explicit follow-up selection.
  ui=await boot(); await ui.choose(); const derived={...ui.state.files[A][0],file_id:'d'.repeat(32),version:2,filename:'result.xlsx'};
  ui.state.files[A].push(derived); ui.state.turns[A]=[{turn_id:'c'.repeat(32),state:'completed',text:'done',reply:'done',files:{inputs:[],generated:[derived]}}];
  ui=await boot(ui.state,ui.storage); ui.find('messages','用于下一轮追问').click(); await ui.flush();
  assert(ui.checks().find(c=>c.checked)); await ui.send('revise'); assert.deepEqual(ui.state.submitted.file_ids,[derived.file_id]);
  assert(ui.nodes['message-input'].focused);
  ui.state.files[A].forEach(f=>f.status='expired');
  ui.state.turns[A].forEach(t=>Object.values(t.files||{}).flat().forEach(f=>f.status='expired'));
  ui=await boot(ui.state,ui.storage);
  assert(!descendants(ui.nodes.messages).some(x=>x.textContent==='下载文件'&&x.tagName==='a'));
  assert(ui.checks().every(c=>c.disabled));
  ui.state.denied=true; ui=await boot(ui.state,ui.storage); assert(ui.nodes['file-input'].disabled); assert.equal(ui.checks().length,0);

  // Steer never submits selected attachments again; keyboard retains original submit path.
  ui=await boot(); await ui.choose(); ui.checks()[0].click();
  ui.state.turns[A]=[{turn_id:'c'.repeat(32),state:'running',run_id:'run_'+'e'.repeat(32),text:'running',
    progress:{type:'tool.started',tool:'mcp__fcro__fc_read_conversation_file'}}];
  ui=await boot(ui.state,ui.storage); assert(ui.nodes['file-input'].disabled);
  assert.match(ui.nodes.messages.textContent,/读取附件 · 正在处理/);
  assert(!ui.nodes.messages.textContent.includes('mcp__fcro__'));
  ui.nodes['message-input'].value='steer'; await ui.nodes['message-input'].onkeydown({key:'Enter',ctrlKey:true,preventDefault(){}}); await ui.flush();
  assert.equal(ui.state.steered.text,'steer'); assert(!('file_ids' in ui.state.steered));
  const css=fs.readFileSync(path.join(__dirname,'conversation.css'),'utf8');
  assert(css.includes(':focus-visible')); assert(css.includes('var(--fs-surface)')); assert(markup.includes('aria-describedby="file-help"'));
  // New material actions execute real UI handlers; lost acceptance reconciles by
  // original GET and never silently posts another task or binds a human turn.
  ui=await boot();await ui.choose();ui.checks()[0].click();
  ui.nodes['material-mode'].value='read';ui.nodes['message-input'].value='Read this selected file';
  ui.state.materialUnknown=true;await ui.nodes['run-material'].click();await ui.flush();
  const original=ui.state.materialSubmitted;
  assert.equal(original.file_ids.length,1);assert.equal(original.operation.mode,'read');
  assert(!ui.state.submitted);assert.match(ui.nodes['material-jobs'].textContent,/结果待核对/);
  const postCount=()=>ui.state.calls.filter(v=>v.url.endsWith('/materials')&&v.method==='POST').length;
  await ui.nodes['run-material'].click();await ui.flush();assert.equal(postCount(),1);
  await ui.find('material-jobs','核对原任务').click();await ui.flush();
  assert.match(ui.nodes['material-jobs'].textContent,/执行中/);assert.equal(postCount(),1);
  await ui.find('material-jobs','停止短任务').click();await ui.flush();
  assert.match(ui.nodes['material-jobs'].textContent,/已取消/);
  assert.equal(ui.state.materialSubmitted.client_request_id,original.client_request_id);
  ui=await boot();await ui.choose();ui.checks()[0].click();
  ui.nodes['material-mode'].value='revise';ui.nodes['material-sheet'].value='1';ui.nodes['material-row'].value='2';
  ui.nodes['material-column'].value='2';ui.nodes['material-value'].value='30';ui.nodes['material-value-type'].value='number';
  ui.nodes['material-format'].value='xlsx';ui.nodes['message-input'].value='Change selected cell';
  await ui.nodes['run-material'].click();await ui.flush();
  assert.deepEqual(ui.state.materialSubmitted.operation.edits,[{sheet:0,row:1,column:1,value:30}]);
  assert.equal(ui.state.materialSubmitted.operation.format,'xlsx');
  ui=await boot();await ui.choose();ui.checks()[0].click();
  ui.nodes['material-mode'].value='read';ui.nodes['material-bounded'].checked=true;
  ui.nodes['material-read-sheet'].value='2';ui.nodes['material-read-offset'].value='201';ui.nodes['material-read-limit'].value='100';
  ui.nodes['message-input'].value='Read this explicit range';
  await ui.nodes['run-material'].click();await ui.flush();
  assert.deepEqual(ui.state.materialSubmitted.read_scope,{file_id:ui.state.files[A][0].file_id,sheet:1,offset:200,limit:100});
  const retained=ui.find('material-jobs','核对原任务');
  await retained.click();await ui.flush();
  const unchanged=ui.find('material-jobs','核对原任务');
  await unchanged.click();await ui.flush();
  assert.equal(ui.find('material-jobs','核对原任务'),unchanged,'unchanged polls preserve the focused DOM control');
  const materialId=ui.state.materialSubmitted.client_request_id;
  ui.state.materialJobs[A+materialId].status='completed';ui.state.materialJobs[A+materialId].run_id='run_'+'a'.repeat(32);
  await ui.find('material-jobs','核对原任务').click();await ui.flush();
  await ui.find('material-jobs','查看回答').click();await ui.flush();
  assert.match(ui.nodes['material-jobs'].textContent,/<script>never execute<\/script>/);
  assert(!descendants(ui.nodes['material-jobs']).some(x=>['script','iframe','a'].includes(x.tagName)));
  assert(![...ui.storage.values()].some(value=>value.includes('never execute')),'model answer stays outside stored goal/request data');
  console.log('PASS materials UI: executed DOM/fetch upload, recovery, hash, race, turn, follow-up, revocation, steer and keyboard scenarios');
}
module.exports={run};
if(require.main===module) run().catch(e=>{console.error(e);process.exitCode=1;});
