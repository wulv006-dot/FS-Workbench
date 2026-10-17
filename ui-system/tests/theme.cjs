const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/../adapters/fs-theme.js','utf8');
function run(saved,url='https://fs.test/dashboard/',dark=false){
 const listeners={},events=[],storage=new Map(saved?[['fs-navigation-theme',saved]]:[]),host={dataset:{}};
 const html={dataset:{}},media={matches:dark,addEventListener:(t,f)=>listeners.media=f};
 const c={MutationObserver:class{constructor(fn){listeners.mutation=fn}observe(){}},window:{},URL,location:{href:url},matchMedia:()=>media,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},document:{documentElement:html,querySelectorAll:s=>s==='.native-content'?[host]:[],dispatchEvent:e=>events.push(e)},CustomEvent:class{constructor(type,o){this.type=type;this.detail=o.detail}},addEventListener:(t,f)=>listeners[t]=f};
 vm.runInNewContext(source,c);return {c,html,host,storage,media,listeners,events};
}
let q=run();assert.equal(q.html.dataset.fsTheme,'light');
q=run('dark');assert.equal(q.html.dataset.fsTheme,'dark');assert.equal(q.host.dataset.theme,'dark');
q=run('system',undefined,true);assert.equal(q.html.dataset.theme,'dark');q.media.matches=false;q.listeners.media();assert.equal(q.html.dataset.theme,'light');
q=run('dark','https://fs.test/?theme=light');assert.equal(q.html.dataset.theme,'light');q.c.window.FSTheme.set('dark');assert.equal(q.storage.get('fs-navigation-theme'),'dark');
q.listeners.storage({key:'fs-navigation-theme',newValue:'light'});assert.equal(q.html.dataset.theme,'light');q.c.window.FSTheme.set('not-a-theme');assert.equal(q.html.dataset.theme,'light');
q.html.dataset.theme='dark';q.listeners.mutation();assert.equal(q.html.dataset.fsTheme,'dark');
console.log('theme resolver: default, saved, system, query, cross-tab, invalid, host propagation PASS');
