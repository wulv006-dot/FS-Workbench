'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'source','brain.js'),'utf8');
new vm.Script(source);
let count=0;function check(value,message){assert(value,message);count++;}
const elements=new Map(),requests=[],clicks=[],blobs=new Map(),answers=new Map();
class Element{
  constructor(tag='div'){this.tag=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.checked=true;this.dataset={};this.classList={add(){},remove(){},toggle(){}};}
  append(value){this.children.push(value);}replaceChildren(){this.children=[];}remove(){}focus(){}scrollIntoView(){}click(){clicks.push(this);if(this.onclick)return this.onclick();}
}
const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={hidden:true,getElementById:element,createElement:tag=>new Element(tag),querySelectorAll:()=>[],querySelector:()=>new Element(),addEventListener(){},body:new Element('body')};
const urlAPI=class extends URL{};urlAPI.createObjectURL=blob=>{const url='blob:synthetic/'+blobs.size;blobs.set(url,blob);return url;};urlAPI.revokeObjectURL=()=>{};
const box={document,location:{search:''},URL:urlAPI,URLSearchParams,Blob,AbortSignal,Date,Map,Set,console,
  setTimeout:()=>1,clearTimeout(){},crypto:{randomUUID:()=> 'synthetic'},confirm:()=>true,
  fetch:async(url,options)=>{requests.push({url,options});if(!answers.has(url))throw Error('unexpected synthetic request '+url);return {ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>answers.get(url)};}};
vm.createContext(box);
const exposed=source.replace(/\}\)\(\);\s*$/,"globalThis.ui={kindOf,list,detail,report,conversation,select,refresh,items:()=>items,setSelected:id=>selected=id,setJob:job=>selectedJob=job,setPool:value=>poolScope=value};})();");
check(exposed!==source,'test hooks must attach only to the test copy');vm.runInContext(exposed,box);
const ui=box.ui,API='/dashboard/fs-home/advisor.json';
const imported={id:'import-'+'a'.repeat(32),state:'IMPORTED',owner:'wulv',body:{start:'2026-10-01',end:'2026-10-14',question:'合成导入月中复盘',mode:'investigation',report_kind:'monthly'},imported:{author:'Synthetic Author',version:'v1-test',imported_at:'2026-10-15T12:00:00Z',html_sha256:'b'.repeat(64),markdown_sha256:'c'.repeat(64)},can_followup:false,can_delete:false,model_usage:{calls:0,total_tokens:0}};
const generated={id:'d'.repeat(32),state:'COMPLETED',owner:'wulv',body:{start:'2026-10-14',end:'2026-10-14',question:'原任务',mode:'daily'},model_usage:{calls:2,total_tokens:123},result:{model_generated:true,summary:'既有模型成稿',actions:[]}};
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
async function main(){
  check(ui.kindOf(imported)==='monthly','explicit monthly wins over a partial-month date range');
  check(ui.kindOf({...imported,body:{...imported.body,mode:'pricing'}})==='monthly','report_kind takes first priority');
  check(ui.kindOf(generated)==='daily','ordinary date inference remains unchanged');
  const original=JSON.stringify([imported,generated]);
  answers.set(API+'?mode=hermes&scope=shared',{items:[generated],imported_items:[imported],can_generate:true,next_before:null});
  document.hidden=false;await ui.refresh();document.hidden=true;
  check(ui.items().map(item=>item.id).join(',')===imported.id+','+generated.id,'imports precede ordinary items');
  check(element('completed').textContent===1,'imports do not change completed model task count');
  const listed=text(element('tasks'));for(const value of ['导入成品','Synthetic Author','v1-test','2026-10-01','2026-10-14'])check(listed.includes(value),'list shows '+value);
  ui.setPool('trash');ui.list();check(!text(element('tasks')).includes('导入成品'),'read-only imports never show restore controls');ui.setPool('shared');
  ui.setSelected(imported.id);ui.detail(imported);
  const detail=text(element('report-detail'));for(const value of ['导入成品','Synthetic Author','v1-test','2026-10-01','2026-10-14'])check(detail.includes(value),'detail shows '+value);
  const buttons=element('report-detail').children.filter(node=>node.tag==='button');
  check(buttons.map(button=>button.textContent).join('|')==='打开导入成品|下载 HTML|下载 Markdown','import controls expose original files only');
  check(!detail.includes('模型调用 0 次')&&!detail.includes('删除报告')&&!detail.includes('查看上一版本'),'imports do not impersonate model runs or parent tasks');
  const before=requests.length;await ui.conversation({...imported,can_followup:true});
  check(requests.length===before,'import conversation performs no thread request');check(element('chat-send').disabled,'import conversation cannot be submitted');
  check(text(element('chat-messages')).includes('暂无模型对话'),'import conversation has a clear empty state');
  ui.setJob({...imported,can_followup:true});await element('chat-form').onsubmit({preventDefault(){}});check(requests.length===before,'an import cannot become parent_report even if a capability flag is wrong');
  answers.set(API+'?mode=hermes&id='+imported.id,imported);await ui.select(imported.id);
  check(requests.length===before+1,'select import performs only the item GET, never result.json or thread GET');
  ui.setSelected(generated.id);ui.detail(generated);check(element('report-detail').children.filter(node=>node.tag==='button').length===4,'ordinary model report retains its four controls');
  const structured={...generated,result:{report_contract:'fs-report-v2',report_format:'structured_v2_recovered',analysis_completed:true,summary:'规范成稿',actions:[]}};
  ui.detail(structured);check(element('report-detail').children.filter(node=>node.tag==='button').length===4,'structured model report remains compatible');
  const html='<!doctype html><html><body><script>window.fixture=1</script>"</iframe><script>bad()</script></body></html>',md='# 原始 Markdown\n\n中文、引号 " 与 <tag> 保持。\n';
  answers.set(API+'?mode=hermes&id='+imported.id+'&artifact=html',{content:html,mime:'text/html;charset=utf-8',filename:'original.html'});
  answers.set(API+'?mode=hermes&id='+imported.id+'&artifact=md',{content:md,mime:'text/markdown;charset=utf-8',filename:'original.md'});
  await ui.report(imported,'html',false);const wrapper=await blobs.get(clicks.at(-1).href).text();
  check(wrapper.includes('sandbox="allow-scripts allow-downloads allow-modals"'),'sandbox preserves inline interactions, downloads and print');
  check(!wrapper.includes('allow-same-origin')&&!wrapper.includes('allow-top-navigation'),'sandbox never grants FS origin or top navigation');
  check(wrapper.includes("connect-src 'none'")&&wrapper.includes("form-action 'none'"),'wrapper blocks network and form writes');
  check(wrapper.includes('&lt;script&gt;')&&!wrapper.includes('<script>bad()'),'srcdoc content is attribute-escaped, not injected into the wrapper');
  check((wrapper.match(/<iframe /g)||[]).length===1&&(wrapper.match(/<\/iframe>/g)||[]).length===1,'hostile closing tags cannot create extra frames');
  await ui.report(imported,'html',true);check(await blobs.get(clicks.at(-1).href).text()===html,'HTML download retains exact original text');check(clicks.at(-1).download==='original.html','HTML download retains original filename');
  await ui.report(imported,'md',true);check(await blobs.get(clicks.at(-1).href).text()===md,'Markdown download retains exact original text');
  answers.set(API+'?mode=hermes&id='+generated.id+'&artifact=html',{content:html,mime:'text/html;charset=utf-8',filename:'model.html'});
  await ui.report(generated,'html',false);check(await blobs.get(clicks.at(-1).href).text()===html,'ordinary report opening is unchanged');
  check(JSON.stringify([imported,generated])===original,'report objects, flags and old usage are not mutated');
  check(!requests.some(request=>request.options.body),'all import interactions are read-only');
  console.log('import UI: '+count+' assertions passed; synthetic DOM/API only, no real network or model calls');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
