'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const code=fs.readFileSync(path.join(__dirname,'../source/daily.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const official=()=>({schema_version:1,status:'succeeded',version:'game-intel-'+'a'.repeat(20),
  collected_at:'2026-10-16T00:05:00+08:00',stale_after:'2099-01-01T00:00:00Z',
  events:[{event_id:'e1',game_key:'ea-sports-fc',game_name:'EA SPORTS FC',title:'Official <script>',
    summary:'Official summary',evidence:'Exact official evidence',source_id:'ea-news',source_url:'https://www.ea.com/news/official',
    kind:'season',event_date:'2026-10-20',event_time:'07:00',timezone:'UTC+08:00',collected_at:'2026-10-16T00:05:00+08:00'}],
  coverage:{covered_games:['ea-sports-fc'],event_covered_games:['ea-sports-fc'],total_games:30,missing_games:[]},source_status:[]});
const seo=()=>({contract:'mmoexp-seo-news-v1',source_kind:'mmoexp_seo',version:'mmoexp-news-'+'b'.repeat(20),status:'available',
  collected_at:'2026-10-16T00:05:00+08:00',stale_after:'2099-01-01T00:00:00Z',coverage:{game_keys:['ea-sports-fc']},
  documents:[{title:'FC27 SEO <img src=x onerror="alert(1)">',summary:'Summary <script>alert(2)</script> & "quoted"',
    source_url:'https://www.mmoexp.com/News/fc27-test.html',source_kind:'mmoexp_seo',published_at:'2026-10-15',
    event_date:null,event_time:null,game_keys:['ea-sports-fc'],profiles:['FC27']}]});
const drain=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};

async function fixture(initial={}) {
  const ids={};
  const element=()=>({textContent:'',innerHTML:'',hidden:false,className:'test-section',children:[],listeners:{},
    classList:{add(){},remove(){}},replaceChildren(){this.children=[];},append(child){this.children.push(child);},
    after(child){ids[child.id]=child;},addEventListener(name,fn){this.listeners[name]=fn;},scrollIntoView(){}});
  for(const id of ['fsDailyStatus','fsDailyCoverage','fsHistoryToggle','fsDailySources','fcGrid','fcMeta','fcBriefCount','fcCollectBtn','rgUpdated','sec-fc'])ids[id]=element();
  const document={readyState:'complete',body:{dataset:{}},getElementById:id=>ids[id],createElement:element};
  const replies={'daily.json':official(),'daily.status.json':{status:'succeeded'},'seo-news.json':seo(),'seo-news.status.json':{status:'available'},...initial};
  const failures=new Set(),intervals=[],applied=[],calls=[],listeners={};
  let user='wulv',swap=false;
  const window={REGION_RELEASES:{historical:true},FS_GAME_TIMERS:[],fsVerifyGameSession:async()=>true,fsGameSessionKey:()=>user,
    fsApplyGameDaily:value=>applied.push(value),fsRenderGameRegion(){},addEventListener:(name,fn)=>listeners[name]=fn};
  const fetch=async url=>{
    calls.push(url);if(swap)user='different';
    if(failures.has(url)||replies[url]===null)throw Error('synthetic unavailable');
    return {ok:true,status:200,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify(replies[url])};
  };
  vm.runInNewContext(code,{document,window,fetch,URL,AbortController,Date,setTimeout:()=>1,clearTimeout(){},
    setInterval:(fn,ms)=>(intervals.push({fn,ms}),intervals.length)});
  await drain();
  return {ids,document,window,applied,calls,intervals,listeners,
    async refresh(updates={},failed=[],swapped=false){Object.assign(replies,clone(updates));failures.clear();failed.forEach(x=>failures.add(x));swap=swapped;await intervals[0].fn();await drain();}};
}

test('SEO titles and summaries escape HTML while official cards remain separate',async()=>{
  const f=await fixture(),html=f.ids.fsSeoNews.innerHTML;
  assert(html.includes('FC27 SEO &lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
  assert(html.includes('Summary &lt;script&gt;alert(2)&lt;/script&gt; &amp; &quot;quoted&quot;'));
  assert(!/<(?:img|script)\b/.test(html));
  assert(html.includes('新闻发布：2026-10-15'));assert(html.includes('主站 SEO 资讯'));
  assert(html.includes('https://www.mmoexp.com/News/fc27-test.html'));
  assert(html.includes('rel="noopener noreferrer"'));
  assert(f.ids.fcGrid.innerHTML.includes('Official &lt;script&gt;'));
  assert(!f.ids.fcGrid.innerHTML.includes('FC27 SEO'));
  assert.equal(f.applied.at(-1).events.length,1);
  assert.equal(f.window.REGION_RELEASES.items.length,1,'SEO never enters official countdown inputs');
  assert.equal(f.document.body.dataset.dailyState,'live');
});

test('only HTTPS MMOEXP News article URLs replace a valid SEO snapshot',async()=>{
  const f=await fixture();
  for(const url of ['javascript:alert(1)','https://other.test/News/fc27-test.html','https://www.mmoexp.com.evil.test/News/fc27-test.html',
    'http://www.mmoexp.com/News/fc27-test.html','https://user:pass@www.mmoexp.com/News/fc27-test.html',
    'https://www.mmoexp.com:444/News/fc27-test.html','https://www.mmoexp.com/News/fc27-test.html?x=1',
    'https://www.mmoexp.com/News/fc27-test.html#x','https://www.mmoexp.com/News/../private.html']){
    const invalid=seo();invalid.documents[0].source_url=url;invalid.documents[0].title='Rejected replacement';
    await f.refresh({'seo-news.json':invalid});
    assert(!f.ids.fsSeoNews.innerHTML.includes('Rejected replacement'),url);
    assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'),url);
    assert(!f.ids.fsDailyStatus.textContent.includes('⚠'),'SEO rejection does not taint official status');
  }
});

test('history hides SEO and restores it on return without creating refresh timers',async()=>{
  const f=await fixture();
  f.ids.fsHistoryToggle.listeners.click();assert.equal(f.ids.fsSeoNews.hidden,true);
  assert.equal(f.applied.at(-1),null);assert.equal(f.window.REGION_RELEASES.historical,true);
  const next=seo();next.documents[0].title='Updated while hidden';
  await f.refresh({'seo-news.json':next});assert.equal(f.ids.fsSeoNews.hidden,true);
  f.ids.fsHistoryToggle.listeners.click();assert.equal(f.ids.fsSeoNews.hidden,false);
  assert(f.ids.fsSeoNews.innerHTML.includes('Updated while hidden'));
  assert.equal(f.intervals.length,1);assert.equal(f.intervals[0].ms,300000);
});

test('SEO GET failure and collector failure status preserve the last cards',async()=>{
  const f=await fixture();
  await f.refresh({},['seo-news.json']);
  assert(f.ids.fsSeoNews.innerHTML.includes('FC27 SEO'));assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  await f.refresh({'seo-news.status.json':{status:'unavailable',last_success_preserved:true}});
  assert(f.ids.fsSeoNews.innerHTML.includes('FC27 SEO'));assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  assert(!f.ids.fsDailyStatus.textContent.includes('⚠'));
  await f.refresh({'seo-news.status.json':{status:'available'}});
  assert(!f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  assert.equal(f.intervals.length,1);
});

test('invalid SEO presentation fields preserve previous cards and permit official updates',async()=>{
  const f=await fixture();const malformed=seo();malformed.documents[0].profiles='FC27';
  const next=official();next.version='game-intel-'+'c'.repeat(20);next.events[0].title='Next official update';
  await f.refresh({'seo-news.json':malformed,'daily.json':next});
  assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  assert.equal(f.applied.at(-1).version,next.version);assert(f.ids.fcGrid.innerHTML.includes('Next official update'));
});

test('official failure keeps its previous successful version while SEO still refreshes',async()=>{
  const f=await fixture();const next=seo();next.documents[0].title='Independent SEO update';
  await f.refresh({'seo-news.json':next},['daily.json']);
  assert.equal(f.applied.at(-1).version,official().version);
  assert(f.ids.fsDailyStatus.textContent.includes('保留上一成功'));
  assert(f.ids.fsSeoNews.innerHTML.includes('Independent SEO update'));
  const invalid=official();invalid.events[0].source_url='javascript:alert(1)';invalid.version='game-intel-'+'d'.repeat(20);
  await f.refresh({'daily.json':invalid});assert.equal(f.applied.at(-1).version,official().version);
});

test('missing or stale SEO keeps official information usable and states uncertainty',async()=>{
  const f=await fixture({'seo-news.json':null,'seo-news.status.json':null});
  assert(f.ids.fsSeoNews.innerHTML.includes('等待夜间采集结果'));assert.equal(f.document.body.dataset.dailyState,'live');
  const stale=seo();stale.stale_after='2000-01-01T00:00:00Z';
  await f.refresh({'seo-news.json':stale,'seo-news.status.json':{status:'available'}});
  assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  const partial=seo();partial.status='partial';
  await f.refresh({'seo-news.json':partial,'seo-news.status.json':{status:'partial'}});
  assert(f.ids.fsSeoNews.innerHTML.includes('部分文章未读取成功'));
});

test('session identity changes cannot display incoming SEO or official payloads',async()=>{
  const f=await fixture();const next=seo();next.documents[0].title='Other user snapshot';
  await f.refresh({'seo-news.json':next},[],true);
  assert(!f.ids.fsSeoNews.innerHTML.includes('Other user snapshot'));assert.equal(f.intervals.length,1);
});
