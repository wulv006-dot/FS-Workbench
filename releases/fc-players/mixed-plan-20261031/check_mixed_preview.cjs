const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'source/app.js'),'utf8');
class Element{constructor(){this.children=[];this.textContent='';this.checked=false;}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}}
const elements={};const $=id=>elements[id]??=new Element();
const node=(tag,text,cls)=>Object.assign(new Element(),{tag,textContent:text,className:cls});
const ids=Array.from({length:34},(_,i)=>String(i+1)),upload=ids.slice(0,8),existing=ids.slice(8);
const state={collection:'frozen-collection',role:'admin',auth:true,write:true,selected:{upload:new Set(upload),tags:new Set(ids),recommend:new Set()}};
const plan={plan_id:'readonly-plan',plan_digest:'digest',scope_ids:ids,upload_futbin_ids:upload,tag_futbin_ids:ids,recommend_futbin_ids:[],selected_tag_ids:[12307,12421],existing_model_map:Object.fromEntries(existing.map(id=>[id,100+Number(id)])),
  blockers:['UNRESOLVED_IMPORT'],active_conflicts:upload.map(futbin_id=>({futbin_id,execution_id:'original-unknown'})),expires_at:new Date(Date.now()+60000).toISOString()};
const requests=[];let previewRows;
const context={state,page:'new',$,node,button:(text,onclick)=>Object.assign(new Element(),{textContent:text,onclick}),Date,parseTags:()=>[12307,12421],ratingThreshold:()=>85,
 msg:(id,value)=>$(id).textContent=value,clearPlan:()=>assert.fail('preview should not fail'),
 table:(root,headers,rows)=>previewRows=rows,api:async(route,method,body)=>{requests.push({route,method,body});return plan;}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  function previewBase('),source.indexOf('  function table('))+source.slice(source.indexOf('  function updateConfirm()'),source.indexOf('  async function confirmPlan()'))+source.slice(source.indexOf('  async function prepareNew()'),source.indexOf('  function modelCriteria()')),context);
(async()=>{
 await vm.runInContext('prepareNew()',context);
 assert.equal(requests.length,1);assert.equal(requests[0].route,'/api/plans/new-cards');assert.deepEqual([...requests[0].body.upload_futbin_ids],upload);assert.deepEqual([...requests[0].body.tag_futbin_ids],ids);
 assert.equal(previewRows.length,34);assert.equal($('confirm').disabled,true);$('scopeChecked').checked=true;vm.runInContext('updateConfirm()',context);assert.equal($('confirm').disabled,true);
 const text=$('planPreview').children.map(x=>x.textContent||'').join('\n');assert.match(text,/需先核对 8 人/);assert.match(text,/original-unknown/);assert.match(text,/请勿重复上新/);assert.doesNotMatch(text,/NEW_CARD_SCOPE_REQUIRED/);
 plan.blockers=[];plan.active_conflicts=[];await vm.runInContext('prepareNew()',context);$('scopeChecked').checked=true;vm.runInContext('updateConfirm()',context);assert.equal($('confirm').disabled,false);
 assert.ok(requests.every(x=>!x.route.endsWith('/confirm')));console.log('mixed preview: 8 uploads / 34 tags preserved; eight original conflicts explained and blocked; valid mixed plan remains manually confirmable');
})().catch(e=>{console.error(e);process.exitCode=1;});
