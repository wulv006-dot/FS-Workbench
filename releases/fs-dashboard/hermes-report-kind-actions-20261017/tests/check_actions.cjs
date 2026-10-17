const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../source/brain.js'),'utf8');
const actions=source.slice(source.indexOf('  async function actionRecords('),source.indexOf('  async function select('));
const refresh=source.slice(source.indexOf('  async function refresh('),source.indexOf('  const prompts='));
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{dataset:{},children:[],replaceChildren(){this.children=[];},classList:{add(){},remove(){}}});return nodes.get(id);};
let allow=true,poolFail=false,actionFail=true,changeSelection=false;
const c={selected:'history',busy:false,refreshQueued:false,uncertain:false,submitting:false,poolScope:'shared',items:[],canGenerate:false,completedResults:new Map(),chatSignature:'',document:{hidden:false,querySelector:()=>$('.live-dot')},$,clearTimeout(){},setTimeout(){return 1;},timer:null,poolParameters:()=>'?mode=hermes&scope=shared',list(){},schedules(){},detail(){},conversation:async()=>{},message(){},node:(tag,text,parent)=>{const n={tag,textContent:text};parent.children.push(n);return n;},request:async q=>{
 if(q.includes('actions=1')){if(changeSelection)c.selected='other';if(actionFail){const e=Error('action_source_unavailable');e.status=503;throw e;}return {actions:[]};}
 if(q.includes('id='))return {id:'history',state:'COMPLETED'};
 if(poolFail)throw Error('main_endpoint_unavailable');return {items:[],can_generate:allow,pool_scope:'shared'};
}};vm.createContext(c);vm.runInContext(actions+'\n'+refresh+'\nthis.refresh=refresh;this.actionRecords=actionRecords;',c);
(async()=>{
 await c.refresh();assert.equal($('submit').disabled,false);assert.equal($('connection').textContent,'已连接云端 Hermes');assert($('decision-list').children.some(n=>n.textContent?.includes('行动记录暂不可用')));assert(!$('decision-list').children.some(n=>n.textContent?.includes('本报告没有')));
 allow=false;await c.refresh();assert.equal($('submit').disabled,true);
 allow=true;c.uncertain=true;await c.refresh();assert.equal($('submit').disabled,true);c.uncertain=false;c.submitting=true;await c.refresh();assert.equal($('submit').disabled,true);c.submitting=false;
 const old=$('decision-list').children;changeSelection=true;await c.actionRecords({id:'history',state:'COMPLETED'});assert.equal($('decision-list').children,old);changeSelection=false;c.selected='history';actionFail=false;await c.actionRecords({id:'history',state:'COMPLETED'});assert($('decision-list').children.some(n=>n.textContent?.includes('本报告没有')));
 poolFail=true;await c.refresh();assert.equal($('submit').disabled,true);assert.equal($('connection').textContent,'连接待恢复');
 console.log('PASS actions 503 stays local; healthy submit, permissions, UNKNOWN/submitting and selection race remain enforced');
})().catch(e=>{console.error(e);process.exitCode=1;});
