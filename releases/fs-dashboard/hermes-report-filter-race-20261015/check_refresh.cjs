'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/candidate/brain.js','utf8'),elements=new Map(),pending=[];let checks=0;
function element(tag='div'){return {tagName:tag,children:[],textContent:'',className:'',classList:{add(){},remove(){},toggle(){}},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];},remove(){},scrollIntoView(){}};}
const document={hidden:false,body:element(),getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},querySelector(){return element();},createElement:element};
const context={document,location:{search:''},URLSearchParams,AbortSignal,Date,Map,Set,Blob,URL,crypto:{randomUUID:()=> 'fixture'},setTimeout:()=>1,clearTimeout(){},fetch:(url,options)=>new Promise(resolve=>pending.push({url,resolve:value=>resolve({ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>value})}))};
const marker=source.indexOf("  $('report-kind').value=reportKind;");assert.ok(marker>0);
vm.createContext(context);vm.runInContext(source.slice(0,marker)+"globalThis.probe={refresh,select,scope:value=>poolScope=value,selectedJob:()=>selectedJob,selected:()=>selected};})();",context);
const flush=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
const check=(v,m)=>{assert.ok(v,m);checks++;};
(async()=>{
 const first=context.probe.refresh();check(pending.length===1,'first request starts');
 context.probe.scope('mine');await context.probe.refresh();context.probe.scope('trash');await context.probe.refresh();
 check(pending.length===1,'busy filter changes coalesce');
 pending[0].resolve({items:[],can_generate:true,pool_scope:'shared'});await first;await flush();
 check(pending.length===2&&pending[1].url.includes('scope=trash'),'latest filter immediately refetched');
 check(elements.get('notice')?.textContent!=='共享池：显示有权访问的夜间与人工报告。 报告结论与建议不代表已执行。','stale list response discarded');
 pending[1].resolve({items:[],can_generate:true,pool_scope:'trash'});await flush();check(elements.get('notice').textContent.includes('回收站'),'latest filter applied');
 const a=context.probe.select('a'.repeat(32)),b=context.probe.select('b'.repeat(32));
 pending[3].resolve({id:'b'.repeat(32),owner:'wulv',state:'FAILED',body:{start:'2026-10-05',end:'2026-10-11',question:'new selected fixture'},result:null,can_followup:false});await flush();
 check(pending[4].url.includes('thread=1'),'new selection loads its own conversation');pending[4].resolve({items:[]});await b;
 pending[2].resolve({id:'a'.repeat(32),owner:'DY',state:'FAILED',body:{start:'2026-10-05',end:'2026-10-11',question:'old selected fixture'},result:null});await a;
 check(context.probe.selectedJob().id==='b'.repeat(32),'late older selection cannot replace current followup parent');
 check(context.probe.selected()==='b'.repeat(32),'selected identity remains newest');
 check(!pending.some(r=>r.url.includes('artifact=')),'failed fixtures cannot read report artifacts');
 console.log(JSON.stringify({result:'PASS',checks,modelCalls:0,productionWrites:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
