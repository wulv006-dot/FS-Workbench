const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../player_web/static/app.js'),'utf8');
const update=source.slice(source.indexOf('  function updateConfirm()'),source.indexOf('  async function confirmPlan()'));
const state={role:'admin',auth:true,write:false,recommendWrite:true,plan:{kind:'existing_action',action:'recommend_enable',blockers:[],expires_at:new Date(Date.now()+60000).toISOString()}};
const elements={confirm:{},scopeChecked:{checked:true}};
const context={state,page:'models',$:id=>elements[id],msg:()=>{},Date};
vm.createContext(context);vm.runInContext(update,context);
function check(disabled){vm.runInContext('updateConfirm()',context);assert.equal(elements.confirm.disabled,disabled);}
check(false);
for(const action of ['recommend_disable','add_tags','remove_tags']){state.plan.action=action;check(true);}
state.plan.action='recommend_enable';state.recommendWrite=false;check(true);
state.recommendWrite=true;state.auth=false;check(true);state.auth=true;
state.role='readonly';check(true);state.role='admin';
elements.scopeChecked.checked=false;check(true);elements.scopeChecked.checked=true;
state.plan.blockers=['LEGACY_UNRESOLVED'];check(true);state.plan.blockers=[];
state.plan.expires_at='2000-01-01T00:00:00Z';check(true);assert.match(elements.confirm.title,/过期/);
state.plan={kind:'new_cards',blockers:[],expires_at:new Date(Date.now()+60000).toISOString()};context.page='new';check(true);state.write=true;check(false);
console.log('manual recommendation button guards passed');
