/* Progressive enhancement shared by static and dynamic navigation. No business APIs. */
(function start(){
 'use strict';
 if(window.parent!==window||window.__fsNavExperience)return;
 const nav=document.getElementById('hubNav');if(!nav){document.addEventListener('DOMContentLoaded',start,{once:true});return;}
 window.__fsNavExperience=true;
 const registry=__FS_NAV_REGISTRY__;
 const root=document.documentElement,KEY='fs-nav-experience-v4';
 let saved={};try{saved=JSON.parse(sessionStorage.getItem(KEY)||'{}')||{};}catch{}
 const persist=()=>{try{sessionStorage.setItem(KEY,JSON.stringify(saved));}catch{}};
 root.dataset.fsNavReady='20261103';root.dataset.fsNavCompact=String(saved.compact===true);
 if(location.pathname.startsWith('/dashboard/analytics/campaigns/analytics/'))root.dataset.fsNavPage='campaign';
 nav.classList.add('fs-nav-v4');
 function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;}
 function valid(path){return typeof path==='string'&&path.startsWith('/')&&!path.startsWith('//')&&!path.includes('..');}
 function matches(path){const u=new URL(path,location.origin),c=new URL(location.href);return c.pathname===u.pathname&&[...u.searchParams].every(([k,v])=>c.searchParams.get(k)===v);}
 let query='',building=false,scheduled=false,tree,search;
 function setOpen(group,open){group.dataset.open=String(open);const button=group.querySelector('.hn-expander'),panel=group.querySelector('.hn-children');button?.setAttribute('aria-expanded',String(open));if(panel)panel.inert=!open;}
 function filter(){
  const q=query.trim().toLowerCase();let count=0;
  nav.querySelectorAll('.hn-group').forEach(g=>{
   const title=g.querySelector('.hn-heading').textContent.toLowerCase();let hits=0;
   g.querySelectorAll('.hn-tool').forEach(a=>{a.hidden=!!q&&!title.includes(q)&&!a.textContent.toLowerCase().includes(q);if(!a.hidden)hits++;});
   g.hidden=!!q&&!hits;count+=g.hidden?0:1;
   setOpen(g,q?hits>0:g.dataset.key===saved.open);
  });
  const empty=nav.querySelector('.hn-empty');if(empty)empty.hidden=count>0;
 }
 function build(){
  if(building)return;building=true;
  try{
   // Keep current server-provided account/permission links and theme control.
   const account=nav.querySelector('.hn-account'),theme=nav.querySelector('.hn-theme');
   const brand=nav.querySelector('.hn-brand')||el('a','hn-brand','FS · MMOEXP');brand.href='/dashboard/';
   const links=new Map([...nav.querySelectorAll('a[href]')].map(a=>[a.getAttribute('href'),a]));
   const fragment=document.createDocumentFragment();fragment.append(brand);
   const box=el('div','hn-search-box');search=el('input','hn-search');search.type='search';search.placeholder='搜索工作区或工具';search.setAttribute('aria-label','搜索导航');search.value=query;
   search.addEventListener('input',()=>{query=search.value;filter();});
   search.addEventListener('keydown',e=>{if(e.key==='Escape'){query='';search.value='';filter();e.stopPropagation();}if(e.key==='ArrowDown'){e.preventDefault();nav.querySelector('.hn-group:not([hidden]) .hn-tool:not([hidden])')?.focus();}});
   box.append(search,el('kbd','', 'Ctrl K'));fragment.append(box);
   tree=el('div','hn-tree');const home=el('a','hn-home','首页');home.href='/dashboard/';home.title='首页';if(matches('/dashboard/'))home.setAttribute('aria-current','page');tree.append(home);
   const all=registry.sections.filter(s=>valid(s.path));
   const active=all.find(s=>matches(s.path))||all.find(s=>s.ids.some(id=>{const t=registry.tools.find(t=>t.id===id);return t&&matches(t.path);}));
   if(saved.path!==location.pathname+location.search){saved.open=active?.id||saved.open||null;saved.path=location.pathname+location.search;persist();}
   for(const section of all){
    const group=el('section','hn-group');group.dataset.key=section.id;
    const row=el('div','hn-row'),heading=el('a','hn-heading');heading.href=section.path;heading.title=section.title;heading.append(el('span','hn-icon',section.icon||'◈'),el('span','',section.title));
    if(active?.id===section.id)heading.setAttribute('aria-current','true');
    const expander=el('button','hn-expander');expander.type='button';expander.setAttribute('aria-label','展开或收起'+section.title);expander.setAttribute('aria-controls','hn-children-'+section.id);expander.append(el('span','','›'));
    expander.onclick=()=>{saved.open=group.dataset.open==='true'?null:section.id;query='';search.value='';persist();filter();};
    row.append(heading,expander);group.append(row);
    const children=el('div','hn-children');children.id='hn-children-'+section.id;const inner=el('div','hn-children-inner');
    const direct=registry.tools.find(t=>section.ids.includes(t.id)&&t.path===section.path);
    const overview=el('a','hn-tool',direct?.label||'工作区概览');overview.href=section.path;if(matches(section.path))overview.setAttribute('aria-current','page');inner.append(overview);
    for(const id of section.ids||[]){const t=registry.tools.find(t=>t.id===id);if(!t||!valid(t.path)||t.path===section.path||t.requiredGroup==='deploy'&&!links.has(t.path))continue;
     const a=el('a','hn-tool',t.label);a.href=t.path;a.title=t.label;if(matches(t.path))a.setAttribute('aria-current','page');
     const old=links.get(t.path);if(old?.getAttribute('aria-disabled')==='true'){a.removeAttribute('href');a.setAttribute('aria-disabled','true');}
     if(t.requiredGroup==='deploy'){a.dataset.requiresGroup='deploy';/* Existing server gate remains authoritative. */}
     inner.append(a);
    }
    children.append(inner);group.append(children);tree.append(group);
   }
   const empty=el('p','hn-empty','没有匹配的入口，试试游戏名称或功能名称。');empty.hidden=true;tree.append(empty);fragment.append(tree);
   if(theme)fragment.append(theme);
   const footer=el('div','hn-footer');if(account)footer.append(account);
   const collapse=el('button','hn-collapse',saved.compact?'»':'«');collapse.type='button';collapse.title=saved.compact?'展开侧栏':'收起侧栏';collapse.setAttribute('aria-label',collapse.title);collapse.setAttribute('aria-expanded',String(!saved.compact));
   collapse.onclick=()=>{saved.compact=!saved.compact;persist();root.dataset.fsNavCompact=String(saved.compact);collapse.textContent=saved.compact?'»':'«';collapse.title=saved.compact?'展开侧栏':'收起侧栏';collapse.setAttribute('aria-label',collapse.title);collapse.setAttribute('aria-expanded',String(!saved.compact));};
   footer.append(collapse);fragment.append(footer);nav.replaceChildren(fragment);filter();
  }finally{building=false;}
 }
 build();
 const grid=document.getElementById('workspaces');let cardsObserver=null;
 if(grid&&location.pathname==='/dashboard/'){
  const syncCards=()=>{for(const section of registry.sections){
   let card=grid.querySelector('.workspace-card.'+section.id);
   if(!card){card=el('article','workspace-card '+section.id);const a=el('a','workspace-main');a.href=section.path;a.append(el('span','workspace-icon',section.icon),el('h3','',section.title),el('p','',section.intro),el('span','entry','进入工作区 →'));card.append(a);grid.append(card);}
   const a=card.querySelector('.workspace-main');if(a&&a.getAttribute('href')!==section.path)a.href=section.path;
  }};
  syncCards();cardsObserver=new MutationObserver(syncCards);cardsObserver.observe(grid,{childList:true});
 }
 document.addEventListener('fs-nav-account-ready',e=>{const incoming=e.detail?.account;if(!incoming)return;const footer=nav.querySelector('.hn-footer');if(!footer)return;footer.querySelector('.hn-account')?.remove();footer.prepend(incoming);});
 // A delayed identity/registry update can replace legacy tree contents once.
 // Old cached shell scripts may still rewrite a group after this bundle runs.
 // Repair only a broken structure; account updates and our own animations do not rebuild it.
 function intact(){return nav.querySelectorAll('.hn-tree > .hn-group').length===registry.sections.filter(s=>valid(s.path)).length && !nav.querySelector('.hn-group .hn-group') && [...nav.querySelectorAll('.hn-tree > .hn-group')].every(g=>g.querySelector(':scope > .hn-row > .hn-expander'));}
 const observer=new MutationObserver(()=>{if(!intact()&&!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;build();});}});
 observer.observe(nav,{childList:true,subtree:true});
 const toggle=document.getElementById('hubNavToggle'),scrim=document.getElementById('hubNavScrim');
 function mobile(open){nav.classList.toggle('open',open);nav.inert=innerWidth<900&&!open;if(scrim)scrim.hidden=!open;toggle?.setAttribute('aria-expanded',String(open));if(open)search.focus();}
 if(toggle)toggle.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();mobile(!nav.classList.contains('open'));},true);
 if(scrim)scrim.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();mobile(false);toggle?.focus();},true);
 mobile(false);
 addEventListener('resize',()=>{if(innerWidth>=900)mobile(false);else nav.inert=!nav.classList.contains('open');});
 document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();saved.compact=false;persist();root.dataset.fsNavCompact='false';const b=nav.querySelector('.hn-collapse');if(b){b.textContent='«';b.title='收起侧栏';b.setAttribute('aria-label','收起侧栏');b.setAttribute('aria-expanded','true');}if(innerWidth<900)mobile(true);search.focus();}
  if(e.key==='Escape'&&nav.classList.contains('open')){mobile(false);toggle?.focus();}
  if(e.key==='Tab'&&innerWidth<900&&nav.classList.contains('open')){const list=[...nav.querySelectorAll('a[href],button,input,select')].filter(n=>n.getClientRects().length&&!n.closest('[inert]'));const first=list[0],last=list.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
 });
 nav.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(a&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&e.button===0){saved.scroll=tree.scrollTop;persist();}});
 addEventListener('pagehide',()=>{observer.disconnect();cardsObserver?.disconnect();});
 addEventListener('pageshow',e=>{if(e.persisted){observer.observe(nav,{childList:true,subtree:true});if(!intact())build();if(cardsObserver)cardsObserver.observe(grid,{childList:true});mobile(false);}});
})();
