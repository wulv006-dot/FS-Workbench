const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'source/app.js'),'utf8');
const update=source.slice(source.indexOf('  function updateConfirm()'),source.indexOf('  async function confirmPlan()'));
const state={role:'admin',auth:true,write:false,addTagsWrite:true,recommendWrite:false,plan:{kind:'existing_action',action:'add_tags',blockers:[],expires_at:new Date(Date.now()+60000).toISOString()}};
const elements={confirm:{},scopeChecked:{checked:true}};
const context={state,page:'models',$:id=>elements[id],msg:()=>{},Date};vm.createContext(context);vm.runInContext(update,context);
function check(disabled){vm.runInContext('updateConfirm()',context);assert.equal(elements.confirm.disabled,disabled);}
check(false);
for(const action of ['recommend_enable','recommend_disable','remove_tags']){state.plan.action=action;check(true);}
state.plan.action='add_tags';state.addTagsWrite=false;check(true);state.addTagsWrite=true;
state.auth=false;check(true);state.auth=true;state.role='readonly';check(true);state.role='admin';
elements.scopeChecked.checked=false;check(true);elements.scopeChecked.checked=true;
state.plan.blockers=['UNRESOLVED_IMPORT'];check(true);state.plan.blockers=[];
state.plan.expires_at='2000-01-01T00:00:00Z';check(true);
console.log('manual add-tag button: independent permission, confirmation, auth, role, blockers and expiry passed');
