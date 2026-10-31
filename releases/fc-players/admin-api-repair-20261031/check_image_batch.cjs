const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync(process.argv[2]||path.join(__dirname,'source/images.js'),'utf8');
class Element{constructor(){this.children=[];this.disabled=false;this.checked=false;this.hidden=false;this.style={};}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
async function run(mode){
  const roots={},calls=[],staged=[],listeners={};let refreshed=0,renewed=false;
  const $=id=>roots[id]??=new Element();
  const ctx={csrf:'csrf1',owner:'operator',role:'admin',auth:true,snapshot:'old',imageWrite:true};
  const emit=()=>listeners['fc27players:context']({detail:{...ctx}});
  const files=['1001.png','1002.png','1003.png'].map(name=>({name,size:8,arrayBuffer:async()=>new Uint8Array(8).buffer}));
  const batch={batch_id:'batch',items:files.map((file,i)=>({name:file.name,futbin_id:String(1001+i),model_id:i+1,status:'matched'}))};
  const response=(status,data)=>({ok:status===200,status,json:async()=>data});
  const sandbox={crypto,URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>{}},
    location:{pathname:'/tools/fc27-players/models.html'},document:{getElementById:$,createElement:()=>new Element(),addEventListener:(name,fn)=>listeners[name]=fn},
    window:{fc27PlayersRefreshModels:async()=>{refreshed++;ctx.snapshot='fresh';emit();},fc27PlayersRecoverSession:async()=>{ctx.csrf='csrf2';emit();}},
    fetch:async(url,options)=>{
      calls.push({url,options});
      if(url.endsWith('/api/image-batches'))return response(200,batch);
      if(url.includes('/files/')){
        if(!renewed&&mode==='csrf'){renewed=true;return response(403,{error:'BROWSER_SESSION_REQUIRED'});}
        if(mode==='snapshot'&&!renewed){renewed=true;ctx.snapshot='another';emit();}
        if(mode==='unknown')throw new Error('response lost');
        staged.push(url.split('/').at(-1));return response(200,{staged:true});
      }
      if(url.endsWith('/api/plans/model-images'))return response(200,{plan_id:'plan',plan_digest:'digest',items:batch.items,blockers:[],expires_at:'2030-01-01'});
      assert.fail('unexpected request '+url);
    }};
  vm.runInNewContext(source,sandbox);emit();$('imageFolder').files=files;$('imageFolder').onchange();await $('imagePrepare').onclick();
  if(process.argv[2]){assert.equal(staged.length,1);assert.match($('imageMessage').textContent,/变化/);return;}
  assert.equal(refreshed,1,'full snapshot must refresh before matching');
  if(mode==='snapshot'){assert.equal(staged.length,1);assert.equal(calls.filter(x=>x.url.endsWith('/api/plans/model-images')).length,0);return;}
  if(mode==='unknown'){assert.equal(calls.filter(x=>x.url.includes('/files/')).length,1);assert.equal(calls.filter(x=>x.url.endsWith('/api/plans/model-images')).length,0);return;}
  assert.deepEqual(staged,files.map(x=>x.name));assert.equal(calls.filter(x=>x.url.endsWith('/api/plans/model-images')).length,1);
  assert.equal($('imageConfirm').disabled,true,'matching never confirms writes');$('imageScopeChecked').checked=true;$('imageScopeChecked').onchange();assert.equal($('imageConfirm').disabled,false);
  assert.equal(calls.filter(x=>x.url.endsWith('/confirm')).length,0);
}
(async()=>{for(const mode of (process.argv[2]?['csrf']:['normal','csrf','snapshot','unknown']))await run(mode);console.log(process.argv[2]?'baseline reproduced: session renewal leaves only first image staged':'image batch: all three staged, renewal preserves batch, stale snapshot aborts, unknown upload not retried; manual confirmation retained');})().catch(e=>{console.error(e);process.exitCode=1;});
