const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../source/fc27-reference-observer.js'),'utf8');
class Element{constructor(tag){this.tag=tag;this.children=[];this.textContent='';}append(n){this.children.push(n);}replaceChildren(){this.children=[];}}
const nodes={};const document={getElementById:id=>nodes[id]||(nodes[id]=new Element('div')),createElement:tag=>new Element(tag)};
const fn=source.slice(source.indexOf('  const $'),source.indexOf('  let loading'))+'\n globalThis.render=render;';
const env={document,Date};vm.runInNewContext(fn,env);
const data={observed_count:1,window_count:1,comparable_count:0,history:[],latest_observed:{status:'observed',run_id:'original',itemd2r:[],market:[],weighted:[]},eldorado:{status:'observed',kind:'user_requested_initial_public_observation',platforms:[{platform:'PS',status:'observed',lowest_observed_100k_usd:'5.43',observed_sellers:8,eligible_100k_sellers:4,offers:[{seller:'<img onerror=alert(1)>',minimum_k:'300',stock_k:'1234',displayed_usd_per_k:'.0543',rating_pct:'99.2',reviews:1000,delivery_time:'4 min - 5 h',quantity_eligible_100k:false}]}]}};
env.render(data);assert.equal(nodes['reference-prices'].children.length,6);
const text=n=>n.textContent+' '+n.children.map(text).join(' ');const result=text(nodes['reference-prices']);
assert(result.includes('ELD · PS'));assert(result.includes('生产直接权重0'));assert(result.includes('仅首屏8卖家'));
assert(result.includes('未逐卖家核实'));assert(result.includes('不符合100K起购量'));assert(result.includes('<img onerror=alert(1)>'));
assert(result.includes('首次公开校准，独立于自然周期样本'));
const html=fs.readFileSync(require('node:path').join(__dirname,'../source/fc27-coins.html'),'utf8');
assert(html.includes('fc27-reference-observer.js?v=eld-20261026-v1'));assert(html.includes('fc27-quote-cloud.js?v=fc-owner-pricing-20261026-135e13af08f7'));
env.render({...data,eldorado:{status:'failed',platforms:[]}});assert(text(nodes['reference-prices']).includes('未取得本轮卖家数据'));
console.log('11 ELD UI assertions passed');
