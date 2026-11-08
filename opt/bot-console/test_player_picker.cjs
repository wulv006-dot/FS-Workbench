const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
class Element {
 constructor(){this.children=[];this.value='';this.disabled=false;this.checked=false;}
 set textContent(value){this.text=String(value);this.children=[];}
 get textContent(){return this.text||'';}
 append(...nodes){this.children.push(...nodes);}
}
test('actual picker handlers search, deduplicate, reorder, select named tags and save IDs', async()=>{
 const elements=new Map(), $=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 let cfg={enabled:true,guild_id:'1565922092518613064',channel_id:'1568260661010497627',featured_model_ids:[],allowed_tag_ids:[],verified_prices:{'101':[21587]}};
 const cards=[{model_id:101,title:'Haaland/91/ST/Gold',model_available:true,verified_platforms:['PlayStation 5']},{model_id:102,title:'Haaland/92/ST/Special',model_available:true,verified_platforms:[]},{model_id:103,title:'Haaland/90/ST/Old',model_available:false,verified_platforms:[]}];
 let saved, deferMatch=false, finishMatch, plans=0, deferPlan=false, finishPlan;
 const api=async (route,options)=>{
  if(options){saved=options.body;cfg={...cfg,...saved.player_panel};return {restarted:true};}
  if(route.startsWith('player/dispatch-plan?')){plans++;if(deferPlan)return new Promise(resolve=>{finishPlan=resolve;});return {plan:{text:'Saved execution instructions',items:cfg.featured_model_ids.map(id=>cards.find(c=>c.model_id===id))}};}
  if(route==='player/config')return {revision:'a'.repeat(64),can_write:true,player_panel:cfg};
  if(route==='player/selection')return {items:cfg.featured_model_ids.map(id=>cards.find(c=>c.model_id===id))};
  if(route.startsWith('player/inspect?'))return {model_id:Number(route.split('=')[1]),platforms:[{platform:'PlayStation 5',goods_id:201,available:true,sale_price:'4.41',quote_enabled:false}],checked_at:1700000000};
  if(route.startsWith('player/match?')){if(deferMatch)return new Promise(resolve=>{finishMatch=resolve;});const model_id=Number(route.split('=')[1]);return {status:'matched',mapping:{model_id,easysbc_id:String(model_id+1000),easysbc_role_id:'44',easysbc_url:'https://www.easysbc.io/players/test/gold/'+(model_id+1000)+'?player-role-id=44'}};}
  if(route==='player/tags')return {items:[{id:'12',name:'Popular'}]};
  if(route.startsWith('player/search?'))return {items:cards,page:1,has_more:false};
  throw Error(route);
 };
 const context=vm.createContext({$,api,document:{createElement:()=>new Element(),createTextNode:text=>({textContent:text})},setTimeout,clearTimeout,console});
 const html=fs.readFileSync(path.join(__dirname,'static/fc27.html'),'utf8');
 const script=html.slice(html.indexOf("let playerRevision=''"),html.lastIndexOf('Promise.allSettled('));
 vm.runInContext(script,context);
 await new Promise(setImmediate);await new Promise(setImmediate);
 $('#player-query').value='Haaland';await vm.runInContext('searchPlayers(1)',context);
 let rows=$('#player-results').children;
 assert.equal(rows.length,3);assert.equal(rows[2].children.at(-1).disabled,true);
 rows[0].children.at(-1).onclick();
 assert.equal($('#player-results').children[0].children.at(-1).disabled,true);
 $('#player-results').children[1].children.at(-1).onclick();
 assert.equal(vm.runInContext('playerSelected.length',context),2);
 $('#player-selected').children[1].children.at(-1).children[1].onclick();
 assert.deepEqual(Array.from(vm.runInContext('playerSelected.map(c=>c.model_id)',context)),[102,101]);
 const tag=$('#player-tags').children[0].children[0];tag.checked=true;tag.onchange();
 await $('#player-form').onsubmit({preventDefault(){}});
 assert.deepEqual(Array.from(saved.player_panel.featured_model_ids),[102,101]);
 assert.equal(plans,1);assert.equal($('#player-dispatch-text').value,'Saved execution instructions');
 assert.ok(vm.runInContext('currentPlayerDispatch()',context));
 assert.deepEqual(Array.from(saved.player_panel.allowed_tag_ids),[12]);
 assert.equal(saved.player_panel.easysbc.template,'card');
 assert.ok($('#player-message').textContent.includes('尚未发送消息'));
 assert.deepEqual(Array.from(saved.player_panel.easysbc.mappings.map(m=>m.model_id)).sort(),[101,102]);
 assert.ok(saved.player_panel.easysbc.mappings.every(m=>m.easysbc_role_id==='44'));
 assert.ok($('#player-mappings').value.includes('1101'));
 $('#player-selected').children[0].children.at(-1).children[3].onclick();
 assert.equal(vm.runInContext('playerSelected.length',context),1);
 assert.equal(vm.runInContext('currentPlayerDispatch()',context),null);
 const beforePlans=plans;await vm.runInContext('generatePlayerDispatch()',context);assert.equal(plans,beforePlans);
 // A result started before reload must not overwrite a newly loaded mapping.
 deferMatch=true;
 vm.runInContext('playerMappings.delete(101)',context);
 const stale=vm.runInContext('matchPlayer(101)',context);
 await vm.runInContext('loadPlayer()',context);
 finishMatch({status:'matched',mapping:{model_id:101,easysbc_id:'9999',easysbc_role_id:'44',easysbc_url:'https://www.easysbc.io/players/9999?player-role-id=44'}});
 await stale;
 assert.equal(vm.runInContext('playerMappings.get(101).easysbc_id',context),'1101');
 // Unsaved style changes cannot export; target changes invalidate a pending preview.
 $('#player-with-card').checked=!$('#player-with-card').checked;
 const oldPlans=plans;await vm.runInContext('generatePlayerDispatch()',context);assert.equal(plans,oldPlans);
 await vm.runInContext('loadPlayer()',context);
 deferPlan=true;$('#player-dispatch-target').value='test';
 const stalePlan=vm.runInContext('generatePlayerDispatch()',context);
 $('#player-dispatch-target').value='official';$('#player-dispatch-target').onchange();
 finishPlan({plan:{text:'Wrong target',items:[]}});await stalePlan;
 assert.equal($('#player-dispatch-text').value,'');assert.equal($('#player-dispatch-copy').disabled,true);

});
