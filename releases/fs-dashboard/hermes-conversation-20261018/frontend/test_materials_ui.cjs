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
  async function choose(content='a,b\n1,2',name='a.csv') { nodes['file-input'].files=[new File([content],name)]; await nodes['file-input'].onchange(); await flush(); }
  return {nodes,state,storage,flush,choose,find,async send(text='analyze') {nodes['message-input'].value=text;await nodes.composer.requestSubmit();await flush();}};
}
async function run() {
  // The five-file candidate is an ordinary chat UI; legacy material data stays untouched.
  assert(!markup.includes('id="run-material"'));
  assert(!markup.includes('id="material-jobs"'));
  assert(!markup.includes('accept=".csv,.xlsx"'));
  assert(!/<textarea\b[^>]*\bid="message-input"[^>]*\bmaxlength=/i.test(markup));
  const longText = '长消息合成核验'.repeat(1001);
  let longUI = await boot();
  await longUI.send(longText);
  assert.equal(longUI.state.submitted.text, longText);
  longUI.state.turns[A] = [{turn_id:'c'.repeat(32),state:'running',run_id:'run_'+'e'.repeat(32),text:'生成中'}];
  longUI = await boot(longUI.state, longUI.storage);
  await longUI.send(longText);
  assert.equal(longUI.state.steered.text, longText);
  let ui=await boot();
  await ui.choose('original raw bytes','说明.pdf');
  assert.equal(ui.state.uploads.length,1);
  assert.equal(ui.state.uploads[0].bytes.toString(),'original raw bytes');
  assert(!ui.nodes['send-message'].disabled);
  await ui.send('请结合这份附件回答');
  assert.deepEqual(ui.state.submitted.file_ids,[ui.state.files[A][0].file_id]);
  assert.equal(ui.state.submitted.text,'请结合这份附件回答');
  assert.equal(ui.nodes['file-choices'].children.length,0);
  assert.equal(ui.nodes['message-input'].value,'');
  assert(!ui.state.calls.some(c=>c.url.includes('/materials')));
  assert(!descendants(ui.nodes.messages).some(x=>x.href?.includes('arbitrary')));

  ui=await boot(); await ui.choose();
  ui.find('file-choices','移除附件').click(); await ui.send('只发文字');
  assert(!('file_ids' in ui.state.submitted));

  ui=await boot(); ui.state.mode='unknown'; await ui.choose();
  const uploadId=ui.state.uploads[0].id;
  assert(ui.nodes['send-message'].disabled,'unconfirmed uploads cannot silently be omitted');
  ui=await boot(ui.state,ui.storage);
  await ui.find('upload-list','核对原上传').click();await ui.flush();
  await ui.send();assert.equal(ui.state.uploads.length,1);
  assert.equal(ui.state.uploads[0].id,uploadId);assert.equal(ui.state.submitted.file_ids.length,1);

  ui=await boot();ui.state.mode='unknown';ui.state.lookup404=true;await ui.choose();
  const original=ui.state.uploads[0].id;
  await ui.choose('different bytes');assert.equal(ui.state.uploads.length,1);
  ui.state.mode='ok';ui.state.lookup404=false;await ui.choose();
  assert.equal(ui.state.uploads[1].id,original);

  ui=await boot();ui.state.mode='fail';await ui.choose();
  assert.match(ui.nodes['upload-list'].textContent,/上传失败/);
  ui.state.mode='ok';await ui.find('upload-list','重试原文件').click();await ui.flush();
  assert.equal(ui.state.uploads[1].id,ui.state.uploads[0].id);

  ui=await boot();ui.state.mode='delay';const uploading=ui.choose();
  while(!ui.state.delayed) await new Promise(r=>setImmediate(r));
  await ui.find('conversation-list','Chat 1').click();await ui.flush();
  ui.state.delayed();await uploading;await ui.flush();
  assert.equal(ui.nodes['file-choices'].children.length,0,'late A upload cannot select into B');

  ui=await boot();await ui.choose();ui.state.turnUnknown=true;await ui.send('待核对的原消息');
  const pending={...ui.state.submitted};
  assert.equal(ui.nodes['message-input'].value,pending.text);
  ui=await boot(ui.state,ui.storage);ui.state.turnUnknown=false;await ui.send();
  assert.equal(ui.state.submitted.client_request_id,pending.client_request_id);
  assert.deepEqual(ui.state.submitted.file_ids,pending.file_ids);

  ui=await boot();await ui.choose();
  ui.state.files[A][0].status='expired';ui=await boot(ui.state,ui.storage);
  await ui.send('失效文件不静默忽略');assert.equal(ui.state.submitted,undefined);
  ui.find('file-choices','移除附件').click();await ui.send('只发文字');assert(!('file_ids' in ui.state.submitted));

  ui=await boot();await ui.choose();
  ui.state.turns[A]=[{turn_id:'c'.repeat(32),state:'running',run_id:'run_'+'e'.repeat(32),text:'其他客户端刚启动'}];
  ui=await boot(ui.state,ui.storage);await ui.send('不能静默丢掉待发送附件');
  assert.equal(ui.state.steered,undefined);assert(ui.nodes['send-message'].disabled);

  const derived={file_id:'d'.repeat(32),filename:'核对结果.xlsx',mime:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',status:'available',version:2};
  ui=await boot();ui.state.files[A].push(derived);
  ui.state.turns[A]=[{turn_id:'c'.repeat(32),state:'completed',text:'原消息',reply:'完整回答\n<script>不执行</script>\n[脚本](javascript:alert(1))\n[正常文档](https://example.org/help)',files:{inputs:[],generated:[derived]},artifacts:[{artifact_id:'f'.repeat(32),filename:'结果.html',mime:'text/html'}]}];
  const legacy=JSON.stringify([{body:{client_request_id:'sealed'},status:'unknown'}]);
  ui.storage.set('fs_material_jobs_'+A,legacy);
  ui=await boot(ui.state,ui.storage);
  assert(ui.nodes.messages.textContent.includes('<script>不执行</script>'));
  assert(!descendants(ui.nodes.messages).some(x=>['script','iframe','input'].includes(x.tagName)));
  assert(!ui.nodes.messages.textContent.includes('用于下一轮'));
  assert(!descendants(ui.nodes.messages).some(x=>x.href?.startsWith('javascript:')));
  assert(descendants(ui.nodes.messages).some(x=>x.href==='https://example.org/help'));
  assert.equal(ui.storage.get('fs_material_jobs_'+A),legacy);
  await ui.send('继续说明上一个版本');assert(!('file_ids' in ui.state.submitted),'history must not blindly rebind every file');
  assert(!ui.state.calls.some(c=>c.url.includes('sealed')));

  ui=await boot();ui.state.turns[A]=[{turn_id:'c'.repeat(32),state:'running',run_id:'run_'+'e'.repeat(32),text:'生成中',reply:'',progress:{type:'tool.started',tool:'mcp__fcro__fc_read_conversation_file'}}];
  ui=await boot(ui.state,ui.storage);assert(ui.nodes['file-input'].disabled);
  assert.match(ui.nodes.messages.textContent,/读取附件/);
  ui.nodes['message-input'].value='补充文字';
  await ui.nodes['message-input'].onkeydown({key:'Enter',shiftKey:false,isComposing:false,preventDefault(){}});await ui.flush();
  assert.equal(ui.state.steered.text,'补充文字');assert(!('file_ids' in ui.state.steered));
  const count=ui.state.calls.length;
  await ui.nodes['message-input'].onkeydown({key:'Enter',shiftKey:true,preventDefault(){throw Error('must retain newline')}});
  assert.equal(ui.state.calls.length,count);
  await ui.nodes['message-input'].onkeydown({key:'Enter',isComposing:true,preventDefault(){throw Error('IME must not send')}});
  ui.state.denied=true;ui=await boot(ui.state,ui.storage);assert(ui.nodes['file-input'].disabled);
  assert(!descendants(ui.nodes.messages).some(x=>x.tagName==='a'&&x.textContent==='下载文件'));
  console.log('PASS native chat UI: raw upload/chips/remove/recovery/unknown/race/turn/files/history/steer/IME/denial; zero materials requests');
}

module.exports={run};
if(require.main===module) run().catch(e=>{console.error(e);process.exitCode=1;});
