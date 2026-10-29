// Extend the original history-five VM DOM fixture with actual api/showJob handlers.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../source/app.js'),'utf8');
const helper=source.slice(source.indexOf('  function node('),source.indexOf('  function clearPlan('));
const api=source.slice(source.indexOf('  async function api('),source.indexOf('  async function status()'));
const jobs=source.slice(source.indexOf('  async function loadJobs()'),source.indexOf('  async function loadTagCatalog('));
assert.ok(helper&&api&&jobs,'actual candidate handlers must be present');
class Element{
  constructor(tag){Object.assign(this,{tag,textContent:'',className:'',children:[],hidden:false,disabled:false,attrs:{},open:false});}
  append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
  replaceChildren(...children){for(const child of this.children)child.parent=null;this.children=[];this.textContent='';this.append(...children);}
  setAttribute(key,value){this.attrs[key]=String(value);}
  click(){if(!this.disabled)return this.onclick?.();}
}
function all(root){return [root,...root.children.flatMap(all)];}
function fixture({role='admin',auth=true,can_resume=true}={}){
  const roots={jobResult:new Element('div'),jobsList:new Element('div')},requests=[];
  const id='2b24ac5661fb404e8bef25f2e6c791f5';
  let job={id,created_at:'original-created',updated_at:'now',status:'needs_reconcile',step:'unknown',can_resume,items:[],events:[]};
  let resolvePost,rejectPost,recoveries=0;
  const deferred=new Promise((resolve,reject)=>{resolvePost=resolve;rejectPost=reject;});
  const response=(status,data)=>({ok:status>=200&&status<300,status,json:async()=>data});
  const context={state:{role,auth,csrf:'csrf-fixture'},prefix:'/tools/fc27-players',
    $:id=>{assert.ok(roots[id],id);return roots[id];},document:{createElement:tag=>new Element(tag)},
    fetch:async(url,options)=>{
      requests.push({url,options});
      if(options.method==='POST')return deferred;
      if(url.endsWith('/api/jobs/'+id))return response(200,{...job});
      if(url.endsWith('/api/jobs'))return response(200,{items:[{...job}]});
      assert.fail('Unexpected request '+url);
    },recoverSession:async()=>{recoveries++;assert.fail('Resume must never automatically replay a POST');},
    table:(root,heads,rows)=>root.append(Object.assign(new Element('table'),{heads,rows})),
    msg:()=>assert.fail('unexpected list error'),Math,encodeURIComponent};
  vm.createContext(context);vm.runInContext(helper+api+jobs,context);
  return {context,roots,requests,id,response,resolvePost,rejectPost,setJob:value=>{job={...job,...value};},recoveries:()=>recoveries,
    show:()=>vm.runInContext('showJob('+JSON.stringify(id)+')',context),
    buttons:()=>all(roots.jobResult).filter(node=>node.tag==='button'&&node.textContent==='继续原任务')};
}
(async()=>{
  let scenarios=0;
  for(const can_resume of [false,true])for(const role of ['admin','readonly'])for(const auth of [false,true]){
    const f=fixture({can_resume,role,auth});await f.show();
    assert.equal(f.buttons().length,Number(can_resume&&role==='admin'&&auth));
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,0);
    scenarios++;
  }
  {
    const f=fixture();await f.show();const resume=f.buttons()[0],pending=resume.click();
    assert.equal(resume.disabled,true,'disable synchronously before first await');
    await resume.click();
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,1,'native disabled button prevents double click');
    const post=f.requests.find(request=>request.options.method==='POST');
    assert.equal(post.url,'/tools/fc27-players/api/jobs/'+f.id+'/resume');
    assert.deepEqual(JSON.parse(post.options.body),{confirmed:true});
    assert.equal(post.options.headers['X-CSRF-Token'],'csrf-fixture');
    assert.equal(post.options.credentials,'same-origin');
    const message=all(f.roots.jobResult).find(node=>node.attrs['aria-live']==='polite');
    assert.equal(message.attrs.role,'status');assert.match(message.textContent,/正在接续原任务/);
    f.setJob({status:'queued',can_resume:false});f.resolvePost(f.response(202,{execution_id:f.id,status:'queued'}));await pending;
    assert.equal(f.buttons().length,0);assert.equal(f.recoveries(),0);
    assert.ok(f.requests.every(request=>request.url.includes('/api/jobs')),'resume never creates a plan or new execution ID');
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,1);
    scenarios++;
  }
  for(const failure of ['http403','network']){
    const f=fixture();await f.show();const resume=f.buttons()[0],pending=resume.click();
    if(failure==='http403')f.resolvePost(f.response(403,{error:'BROWSER_SESSION_REQUIRED'}));
    else f.rejectPost(new Error('connection lost'));
    await pending;
    const message=all(f.roots.jobResult).find(node=>node.attrs['aria-live']==='polite');
    assert.equal(message.attrs.role,'status');assert.match(message.textContent,/未能接续/);
    assert.match(message.textContent,/原任务状态/);assert.equal(resume.disabled,false);
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,1);
    assert.equal(f.recoveries(),0,'failed write is never automatically recovered and resent');
    scenarios++;
  }
  {
    const f=fixture();await f.show();const pending=f.buttons()[0].click();
    await f.show();
    assert.ok(!f.buttons().length||f.buttons()[0].disabled,'viewing original result again must not create a second enabled resume button while POST pending');
    if(f.buttons().length)await f.buttons()[0].click();
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,1,'re-render does not bypass per-execution pending guard');
    f.rejectPost(new Error('connection lost after re-render'));await pending;
    const message=all(f.roots.jobResult).find(node=>node.attrs['aria-live']==='polite'&&/未能接续/.test(node.textContent));
    assert.ok(message,'error remains visible in current live DOM after result re-render');
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,1);scenarios++;
  }
  {
    // Retain the established history-five behavior using the actual candidate loadJobs.
    const f=fixture();await vm.runInContext('loadJobs()',f.context);
    const rows=f.roots.jobsList.children.filter(child=>child.className==='job-row');
    assert.equal(rows.length,1);assert.equal(rows[0].children[0].textContent,'original-created');
    await rows[0].children[3].click();assert.equal(f.buttons().length,1);
    assert.equal(f.requests.filter(request=>request.options.method==='POST').length,0);scenarios++;
  }
  console.log('resume DOM: '+scenarios+' scenarios passed; real candidate api/showJob/loadJobs; no network; no new ID or duplicate POST');
})().catch(error=>{console.error(error);process.exitCode=1;});
