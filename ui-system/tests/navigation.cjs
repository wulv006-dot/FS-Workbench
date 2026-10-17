const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(__dirname+'/../adapters/hubnav.js','utf8');
const fn=src.match(/function matches\(path\)\{[^\n]+\}/)[0];
function check(current,path){const u=new URL(current),c={URL,location:u};vm.runInNewContext(fn,c);return c.matches(path)}
assert(!check('https://fs.test/dashboard/fs-home/brain/index.html','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(check('https://fs.test/dashboard/fs-home/brain/index.html?report_kind=weekly#reports','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(!check('https://fs.test/dashboard/fs-home/brain/index.html?report_kind=daily#reports','/dashboard/fs-home/brain/index.html?report_kind=weekly#reports'));
assert(check('https://fs.test/dashboard/management/fc27.html','/dashboard/management/'));
assert(!check('https://fs.test/dashboard/analytics/','/dashboard/management/'));
console.log('navigation query-aware selection: 5 cases PASS');
// Exercise homepage card placement, re-render, identity and permission boundaries.
class Item{
 constructor(tag,text,cls){this.tag=tag;this.text=text;this.className=cls||'';this.children=[];this.dataset={};this.parent=null;}
 append(...items){for(const x of items){if(x.parent)x.remove();x.parent=this;this.children.push(x)}}
 remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null;}}
 after(x){const p=this.parent;x.remove();x.parent=p;p.children.splice(p.children.indexOf(this)+1,0,x)}
 get nextElementSibling(){return this.parent?.children[this.parent.children.indexOf(this)+1]||null}
 querySelector(q){if(q==='.workspace-card.arpg')return this.children.find(x=>x.className==='workspace-card arpg');const id=q.match(/data-fs-home-shortcut="([^"]+)"/)?.[1];return this.children.find(x=>x.dataset.fsHomeShortcut===id)||null;}
}
const grid=new Item('div');grid.append(new Item('article',null,'workspace-card arpg'),new Item('article',null,'workspace-card bots'));
let callback;const context={location:{pathname:'/dashboard/'},currentUser:{name:'operator'},stopped:false,
 document:{getElementById:id=>id==='workspaces'?grid:null,querySelectorAll:()=>grid.children.filter(x=>x.dataset.fsHomeShortcut)},
 MutationObserver:class{constructor(f){callback=f}observe(){}disconnect(){}},
 element:(t,x,c)=>new Item(t,x,c),link:(x,path,c)=>Object.assign(new Item('a',x,c),{href:path})};
const home=src.slice(src.indexOf(' let homeCardsObserver='),src.indexOf(' function render(user,tools)'));
vm.runInNewContext(home,context);
const tools=[{id:'management',path:'/dashboard/management/',available:true},{id:'game-monitor',path:'/dashboard/game-monitor/',available:true}];
context.mountHomeCards({name:'operator'},tools);
assert.deepEqual(grid.children.map(x=>x.dataset.fsHomeShortcut||x.className),['workspace-card arpg','management','game-monitor','workspace-card bots']);
assert.equal(grid.children[1].children[0].href,'/dashboard/management/');
assert.equal(grid.children[2].children[0].href,'/dashboard/game-monitor/');
callback();assert.equal(grid.children.length,4);
context.mountHomeCards({name:'operator'},tools);assert.equal(grid.children.length,4);
context.clearHomeCards();assert.equal(grid.children.length,2);
context.mountHomeCards({name:'operator'},tools.map(x=>({...x,available:false})));assert.equal(grid.children.length,2);
context.mountHomeCards({name:'another-user'},tools);assert.equal(grid.children.length,2);
context.location.pathname='/dashboard/analytics/';context.mountHomeCards({name:'operator'},tools);assert.equal(grid.children.length,2);
console.log('homepage shortcuts: order, destinations, repeated render, cleanup, denied, identity, non-home PASS');

assert(src.includes('三组进度 · 健康度责任到人 · 目标沙盘与经营决策'));
assert(src.includes('全球新游上线 · 版本赛季 · 开服节点一屏追踪'));

const styledExpression=src.match(/const styledModule=([^;]+);/)[1];
for(const pathname of ['/dashboard/management/','/dashboard/analytics/','/tools/fc27-gallery/','/tools/fc27-players/']){
 assert.equal(vm.runInNewContext(styledExpression,{location:{pathname},document:{body:{hasAttribute:()=>false}}}),true);
 assert.equal(vm.runInNewContext(styledExpression,{location:{pathname},document:{body:{hasAttribute:()=>true}}}),false);
}
assert.equal(vm.runInNewContext(styledExpression,{location:{pathname:'/d4/'},document:{body:{hasAttribute:()=>false}}}),false);
console.log('management-specific palette isolation preserves existing module styling PASS');
