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
 let saved;
 const api=async (route,options)=>{
  if(options){saved=options.body;cfg={...cfg,...saved.player_panel};return {restarted:true};}
  if(route==='player/config')return {revision:'a'.repeat(64),can_write:true,player_panel:cfg};
  if(route==='player/selection')return {items:cfg.featured_model_ids.map(id=>cards.find(c=>c.model_id===id))};
  if(route.startsWith('player/inspect?'))return {model_id:Number(route.split('=')[1]),platforms:[{platform:'PlayStation 5',goods_id:201,available:true,sale_price:'4.41',quote_enabled:false}],checked_at:1700000000};
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
 assert.deepEqual(Array.from(saved.player_panel.allowed_tag_ids),[12]);
 assert.equal(saved.player_panel.easysbc.template,'card');
 assert.ok($('#player-message').textContent.includes('尚未接通'));
 $('#player-selected').children[0].children.at(-1).children[3].onclick();
 assert.equal(vm.runInContext('playerSelected.length',context),1);
});
