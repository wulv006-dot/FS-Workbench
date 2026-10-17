'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/candidate/brain.js','utf8');
const elements=new Map(),calls=[],opened=[];let failBoss=false,checks=0;
function element(tag='div'){return {tagName:tag,children:[],textContent:'',className:'',classList:{add(){},remove(){},toggle(){}},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];},remove(){},click(){opened.push({download:this.download,target:this.target});},scrollIntoView(){}};}
const document={hidden:true,body:element(),getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element};
const context={document,location:{search:''},URLSearchParams,AbortSignal,Date,Map,Set,Blob,crypto:{randomUUID:()=> 'test'},URL:{createObjectURL:()=> 'blob:report',revokeObjectURL(){}},setTimeout:()=>1,clearTimeout(){},fetch:async(url,options)=>{calls.push({url,options});const kind=new URL(url,'https://fs.test').searchParams.get('artifact');return {ok:!(failBoss&&kind==='boss'),status:failBoss&&kind==='boss'?404:200,headers:{get:()=> 'application/json'},json:async()=>({content:'<html>stored report</html>',mime:'text/html',filename:kind==='boss'?'presentation.html':'research.html'})};}};
vm.createContext(context);
const end=source.indexOf("  $('report-kind').value=reportKind;");assert.ok(end>0);
vm.runInContext(source.slice(0,end)+"globalThis.showReport=job=>{selected=job.id;detail(job);};})();",context);
const job={id:'a'.repeat(32),state:'COMPLETED',body:{start:'2026-10-13',end:'2026-10-14',question:'existing report'},result:{model_generated:true,summary:'已有报告',actions:[]}};
const buttons=()=>elements.get('report-detail').children.filter(n=>n.tagName==='button');
const check=(value,message)=>{assert.ok(value,message);checks++;};
(async()=>{
 context.showReport(job);
 assert.deepEqual(buttons().map(b=>b.textContent),['打开汇报','下载汇报','打开研究详情','下载研究详情']);checks++;
 assert.deepEqual(buttons().map(b=>b.className),['primary','primary','quiet','quiet']);checks++;
 for(const b of buttons())await b.onclick();
 assert.deepEqual(calls.map(c=>new URL(c.url,'https://fs.test').searchParams.get('artifact')),['boss','boss','html','html']);checks++;
 assert.deepEqual(opened,[{download:undefined,target:'_blank'},{download:'presentation.html',target:undefined},{download:undefined,target:'_blank'},{download:'research.html',target:undefined}]);checks++;
 check(calls.every(c=>c.options.method==='GET'),'buttons only read existing artifacts');
 failBoss=true;await buttons()[0].onclick();check(elements.get('notice').textContent.includes('汇报暂未就绪'),'presentation failure remains visible');check(buttons().length===4,'research fallback remains available');
 context.showReport({...job,state:'RUNNING'});check(buttons().length===0,'unfinished job exposes no report buttons');
 console.log(JSON.stringify({checks,result:'PASS',modelCalls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
