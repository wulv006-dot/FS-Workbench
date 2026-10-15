'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'ui','brain.js'),'utf8');
const start=source.indexOf('  function detail(job) {'),end=source.indexOf('  async function select(id)',start);
assert(start>=0&&end>start,'actual detail function must be present');
new vm.Script(source);
let assertions=0;
function check(value,message){assert(value,message);assertions++;}
function fixture(result,state='COMPLETED',mode='investigation'){
  const elements=new Map(),requests=[],selected='synthetic';
  function element(tag='div',text=null){return {tag,textContent:text,children:[],replaceChildren(){this.children=[];},append(child){this.children.push(child);}};}
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const context={selected,completedResults:new Map(),$,
    labels:{COMPLETED:'已成稿',RUNNING:'调查中',REPORT_PENDING:'正在保存报告',FAILED:'失败'},
    node:(tag,text,parent,cls)=>{const value=element(tag,text);value.className=cls;if(parent)parent.append(value);return value;},
    kindOf:job=>job.body.mode==='pricing'?'pricing':'weekly',
    report:(job,kind,download)=>{requests.push({id:job.id,kind,download});return Promise.resolve();},message:()=>{}};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  const job={id:selected,state,owner:'synthetic',body:{start:'2026-01-05',end:'2026-01-11',question:'合成问题',mode},result};
  return {context,job,elements,requests,render:()=>context.detail(job),buttons:()=>($('report-detail').children.filter(child=>child.tag==='button'))};
}
const valid={report_contract:'fs-report-v2',report_format:'structured_v2_recovered',analysis_completed:true,summary:'合成结构化报告',actions:[{target:'合成对象',action:'只读核对',condition:'原条件',review_at:'建议复查',success_check:'核对来源'}]};
for(const format of ['structured_v2','structured_v2_recovered']){
  const f=fixture({...valid,report_format:format}),before=JSON.stringify(f.job);
  f.render();check(f.buttons().length===4,format+' exposes both open/download pairs');
  check(JSON.stringify(f.job)===before,'render must not mutate immutable result');
  for(const button of f.buttons())button.onclick();
  check(JSON.stringify(f.requests)===JSON.stringify([{id:'synthetic',kind:'boss',download:false},{id:'synthetic',kind:'boss',download:true},{id:'synthetic',kind:'html',download:false},{id:'synthetic',kind:'html',download:true}]),'buttons use existing artifact endpoints only');
  check(f.elements.get('decision-list').children.some(row=>row.className==='decision'),'structured actions remain visible');
}
for(const state of ['RUNNING','REPORT_PENDING','FAILED','CANCELLED','NEEDS_RECONCILE']){
  const f=fixture(valid,state);f.render();check(f.buttons().length===0,state+' cannot expose report buttons');
}
for(const result of [undefined,null,{}, {...valid,report_contract:'unknown'}, {...valid,report_format:'markdown'}, {...valid,analysis_completed:false}, {...valid,summary:''}, {...valid,summary:'   '}, {...valid,summary:42}, {...valid,actions:null}]){
  const f=fixture(result);f.render();check(f.buttons().length===0,'missing or invalid structured result cannot expose report buttons');
}
const legacy=fixture({model_generated:true,summary:'旧版成稿',actions:[]});legacy.render();check(legacy.buttons().length===4,'legacy model flag remains compatible');
const cached=fixture(undefined);cached.context.completedResults.set('synthetic',valid);cached.render();check(cached.buttons().length===4,'cached result.json supplies the structured result');check(cached.job.result===undefined,'cache merge does not mutate job');
const pricing=fixture(valid,'COMPLETED','pricing');pricing.render();check(pricing.buttons()[0].textContent==='打开竞品与定价报告','pricing button label remains separate');
console.log(`report buttons: ${assertions} assertions passed; no DOM browser, network or model calls`);
