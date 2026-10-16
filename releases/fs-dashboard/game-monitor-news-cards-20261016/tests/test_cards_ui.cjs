'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const code=fs.readFileSync(path.join(__dirname,'../source/daily.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../source/index.html'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const slice=(start,end)=>{
  const from=html.indexOf(start),to=html.indexOf(end,from+start.length);
  assert(from>=0&&to>from,`HTML source boundary: ${start}`);
  return html.slice(from,to);
};
const pageCode=[
  slice('window.GAME_TIMELINE_DATA =','</script>'),
  slice('const DATA =','const TYPE_STYLE'),
  slice('const MS_DAY =','/* ---------- 游戏详情三级'),
  'const GAME_THEME={}; const radarItems=[];',
  slice('function remainDays(','function radarNodeLessHtml('),
  slice('function renderRadar(','function renderHero('),
  slice('function renderTierTabs(','function renderUrgent('),
  slice('const fsGameSeed =','\nrenderHero();')
].join('\n');
const official=()=>({schema_version:1,status:'succeeded',version:'game-intel-'+'a'.repeat(20),
  collected_at:'2026-10-16T00:05:00+08:00',stale_after:'2099-01-01T00:00:00Z',
  events:[{event_id:'e1',game_key:'ea-sports-fc',game_name:'EA SPORTS FC',title:'官方节点 <script>',
    summary:'官方摘要',evidence:'Exact official evidence',source_id:'ea-news',source_url:'https://www.ea.com/news/official',
    kind:'season',event_date:'2026-10-20',event_time:'07:00',timezone:'UTC+08:00',collected_at:'2026-10-16T00:05:00+08:00'}],
  coverage:{covered_games:['ea-sports-fc'],event_covered_games:['ea-sports-fc'],total_games:29,missing_games:[]},source_status:[]});
const seo=()=>({contract:'mmoexp-seo-news-v1',source_kind:'mmoexp_seo',version:'mmoexp-news-'+'b'.repeat(20),status:'available',
  collected_at:'2026-10-16T00:05:00+08:00',stale_after:'2099-01-01T00:00:00Z',coverage:{game_keys:['ea-sports-fc','aion2']},
  documents:[{title:'News original <img src=x onerror="alert(1)">',summary:'Original <script>alert(2)</script> & "quoted"',
    title_zh:'中文标题 <img src=x onerror="alert(3)">',summary_zh:'中文摘要 <script>alert(4)</script> & "引号"',
    source_url:'https://www.mmoexp.com/News/aion-2-test.html',source_kind:'mmoexp_seo',published_at:'2026-10-15',
    event_date:null,event_time:null,game_keys:['ea-sports-fc','aion2'],profiles:['FC27','Aion2']}]});
const drain=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
class FixedDate extends Date {
  constructor(...args){super(...(args.length?args:['2026-10-16T08:00:00Z']));}
  static now(){return Date.parse('2026-10-16T08:00:00Z');}
}

async function fixture(initial={}) {
  const ids={};
  const element=()=>({textContent:'',innerHTML:'',hidden:false,className:'test-section',children:[],listeners:{},
    classList:{add(){},remove(){}},replaceChildren(){this.children=[];},append(child){this.children.push(child);},
    after(child){ids[child.id]=child;},addEventListener(name,fn){this.listeners[name]=fn;},scrollIntoView(){}});
  for(const id of ['fsDailyStatus','fsDailyCoverage','fsHistoryToggle','fsDailySources','fcGrid','fcMeta','fcBriefCount',
    'fcCollectBtn','rgUpdated','sec-fc','radarGrid','radarCount','tn-全部','tn-S','tn-A','tn-B','tn-长尾'])ids[id]=element();
  const document={readyState:'complete',body:{dataset:{}},getElementById:id=>ids[id],createElement:element};
  const replies={'daily.json':official(),'daily.status.json':{status:'succeeded'},'seo-news.json':seo(),
    'seo-news.status.json':{status:'available'},...initial};
  const failures=new Set(),intervals=[],applied=[],calls=[],listeners={};
  let user='wulv',swap=false;
  const window={REGION_RELEASES:{historical:true},FS_GAME_TIMERS:[],fsVerifyGameSession:async()=>true,
    fsGameSessionKey:()=>user,fsRenderGameRegion(){},dispatchEvent(){},addEventListener:(name,fn)=>listeners[name]=fn};
  const fetch=async url=>{
    calls.push(url);if(swap)user='different';
    if(failures.has(url)||replies[url]===null)throw Error('synthetic unavailable');
    return {ok:true,status:200,headers:{get:()=> 'application/json'},text:async()=>JSON.stringify(replies[url])};
  };
  const context=vm.createContext({document,window,fetch,URL,AbortController,Date:FixedDate,
    CustomEvent:class {constructor(type){this.type=type;}},setTimeout:()=>1,clearTimeout(){},
    setInterval:(fn,ms)=>(intervals.push({fn,ms}),intervals.length),
    renderHero(){},renderUrgent(){},renderFC(){},tickCd(){}});
  vm.runInContext(pageCode,context);
  const apply=window.fsApplyGameDaily;
  window.fsApplyGameDaily=(snapshot,news)=>{applied.push(snapshot);apply(snapshot,news);};
  vm.runInContext(code,context);
  await drain();
  return {ids,document,window,applied,calls,intervals,listeners,
    eval:expression=>vm.runInContext(expression,context),
    async refresh(updates={},failed=[],swapped=false){Object.assign(replies,clone(updates));failures.clear();failed.forEach(x=>failures.add(x));swap=swapped;await intervals[0].fn();await drain();}};
}
const gameExpr=key=>`DATA.find(g=>g.key===${JSON.stringify(key)})`;
const card=(f,key)=>f.eval(`radarNodeLessCardHtml(${gameExpr(key)})`);
const details=(f,key)=>f.eval(`dailyIntelHtml(${gameExpr(key)})`);

test('official content wins, including official events without precise countdown times',async()=>{
  for(const missing of [null,'event_date','event_time','timezone']){
    const snapshot=official();if(missing)snapshot.events[0][missing]=null;
    const f=await fixture({'daily.json':snapshot});
    const preview=f.eval(`dailyIntelPreview(${gameExpr('ea-sports-fc')})`);
    assert(preview.includes('官方摘要'));assert(!preview.includes('中文摘要'));
    const detail=details(f,'ea-sports-fc');
    assert(detail.includes('官方节点 &lt;script&gt;'));assert(detail.includes('查看官方来源'));
    assert(!detail.includes('中文标题'));assert.equal(f.eval(`${gameExpr('ea-sports-fc')}.seo_news.length`),0);
    assert.equal(f.eval(`${gameExpr('ea-sports-fc')}.events.length`),missing?0:1);
    assert(f.ids.radarGrid.innerHTML.includes('官方节点 &lt;script&gt;'));
  }
});

test('node-less main cards and details show Chinese News with an explicit SEO source and escaped text',async()=>{
  const f=await fixture(),main=card(f,'aion2'),detail=details(f,'aion2'),lower=f.ids.fsSeoNews.innerHTML;
  for(const output of [main,detail,lower]){
    assert(output.includes('中文标题 &lt;img src=x onerror=&quot;alert(3)&quot;&gt;'));
    assert(output.includes('中文摘要 &lt;script&gt;alert(4)&lt;/script&gt; &amp; &quot;引号&quot;'));
    assert(!/<(?:img|script)\b/.test(output));
    assert(/主站\s*SEO\s*资讯/.test(output));
  }
  assert(detail.includes('https://www.mmoexp.com/News/aion-2-test.html'));
  assert(detail.includes('rel="noopener noreferrer"'));assert(detail.includes('新闻发布：2026-10-15'));
  assert(main.includes('不生成倒计时'));assert(!main.includes('data-cd='));
  assert(f.ids.radarGrid.innerHTML.includes('中文标题'));
  assert.equal(f.eval(`${gameExpr('aion2')}.events.length`),0);
  assert.equal(f.eval(`${gameExpr('aion2')}.insight_events.length`),0);
  assert.equal(f.window.REGION_RELEASES.items.length,1,'SEO never enters official regional countdown inputs');
  assert.equal(f.applied.at(-1).events.length,1);
});

test('an SEO-only version update rerenders main cards while preserving the official version',async()=>{
  const f=await fixture(),before=f.applied.length,next=seo();
  next.version='mmoexp-news-'+'c'.repeat(20);next.documents[0].title_zh='更新后的中文标题';
  next.documents[0].summary_zh='更新后的中文摘要';
  await f.refresh({'seo-news.json':next});
  assert.equal(f.applied.length,before+1);assert.equal(f.applied.at(-1).version,official().version);
  assert(f.ids.radarGrid.innerHTML.includes('更新后的中文标题'));
  assert(details(f,'aion2').includes('更新后的中文摘要'));
  assert(f.ids.fsSeoNews.innerHTML.includes('更新后的中文标题'));
  await f.refresh();assert.equal(f.applied.length,before+1,'unchanged versions do not rerender');
});

test('CFB26 stays retired even if an old official snapshot mentions it; both game counters derive from DATA',async()=>{
  const snapshot=official();snapshot.events.push({...snapshot.events[0],event_id:'old-cfb',game_key:'college-football-26',game_name:'CFB26'});
  const f=await fixture({'daily.json':snapshot});
  assert.equal(f.eval('DATA.length'),29);assert.equal(f.eval('DATA.some(g=>g.key==="college-football-26")'),false);
  assert.equal(Number(f.ids.radarCount.textContent),29);assert.equal(Number(f.ids['tn-全部'].textContent),29);
  assert.equal((f.ids.radarGrid.innerHTML.match(/class="radar-card /g)||[]).length,29);
  assert(!f.ids.radarGrid.innerHTML.includes('college-football-26'));
  f.eval('DATA.pop();renderRadar();renderTierTabs()');
  assert.equal(Number(f.ids.radarCount.textContent),28);assert.equal(Number(f.ids['tn-全部'].textContent),28);
  f.ids.fsHistoryToggle.listeners.click();assert.equal(f.eval('DATA.length'),29);
});

test('history hides SEO; updates received while hidden appear on returning to daily mode',async()=>{
  const f=await fixture();f.ids.fsHistoryToggle.listeners.click();
  assert.equal(f.ids.fsSeoNews.hidden,true);assert.equal(f.applied.at(-1),null);
  assert.equal(f.eval('DATA.some(g=>g.seo_news.length>0)'),false);
  assert.equal(details(f,'aion2'),'');assert.equal(f.window.REGION_RELEASES.historical,true);
  const next=seo();next.version='mmoexp-news-'+'d'.repeat(20);next.documents[0].title_zh='历史期间更新';
  await f.refresh({'seo-news.json':next});assert.equal(f.ids.fsSeoNews.hidden,true);
  assert.equal(f.eval('window.FS_GAME_DAILY_MODE'),'history');
  f.ids.fsHistoryToggle.listeners.click();assert.equal(f.ids.fsSeoNews.hidden,false);
  assert(f.ids.radarGrid.innerHTML.includes('历史期间更新'));assert.equal(f.document.body.dataset.dailyState,'live');
  assert.equal(f.intervals.length,1);assert.equal(f.intervals[0].ms,300000);
});

test('untranslated old English articles remain folded originals and are not promoted as Chinese main cards',async()=>{
  const old=seo();delete old.documents[0].title_zh;delete old.documents[0].summary_zh;
  const f=await fixture({'seo-news.json':old}),lower=f.ids.fsSeoNews.innerHTML;
  assert(lower.includes('<h3>中文标题待整理</h3>'));assert(lower.includes('中文摘要暂未生成'));
  assert(lower.includes('<details><summary>原文与来源</summary><p>News original &lt;img'));
  assert(!card(f,'aion2').includes('News original'));assert.equal(f.eval(`${gameExpr('aion2')}.seo_news.length`),0);
  assert.equal(f.eval(`${gameExpr('aion2')}.events.length`),0);
});

test('URL and presentation validation preserve last good SEO and allow official updates',async()=>{
  const f=await fixture();
  for(const url of ['javascript:alert(1)','https://other.test/News/aion-2-test.html',
    'https://www.mmoexp.com.evil.test/News/aion-2-test.html','http://www.mmoexp.com/News/aion-2-test.html',
    'https://user:pass@www.mmoexp.com/News/aion-2-test.html','https://www.mmoexp.com:444/News/aion-2-test.html',
    'https://www.mmoexp.com/News/aion-2-test.html?x=1','https://www.mmoexp.com/News/aion-2-test.html#x',
    'https://www.mmoexp.com/News/../private.html']){
    const invalid=seo();invalid.documents[0].source_url=url;invalid.documents[0].title_zh='应拒绝的新内容';
    await f.refresh({'seo-news.json':invalid});
    assert(!f.ids.fsSeoNews.innerHTML.includes('应拒绝的新内容'),url);
    assert(!f.ids.radarGrid.innerHTML.includes('应拒绝的新内容'),url);
    assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'),url);
    assert(!f.ids.fsDailyStatus.textContent.includes('⚠'));
  }
  const malformed=seo();malformed.documents[0].title_zh={unsafe:'value'};
  const next=official();next.version='game-intel-'+'e'.repeat(20);next.events[0].title='新的官方节点';
  await f.refresh({'seo-news.json':malformed,'daily.json':next});
  assert(f.ids.radarGrid.innerHTML.includes('新的官方节点'));assert.equal(f.applied.at(-1).version,next.version);
  assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
});

test('SEO refresh still reaches main cards when official GET fails and reports source freshness separately',async()=>{
  const f=await fixture(),next=seo();next.version='mmoexp-news-'+'f'.repeat(20);next.documents[0].title_zh='独立更新';
  await f.refresh({'seo-news.json':next},['daily.json']);
  assert(f.ids.radarGrid.innerHTML.includes('独立更新'));assert.equal(f.applied.at(-1).version,official().version);
  assert(f.ids.fsDailyStatus.textContent.includes('保留上一成功'));
  await f.refresh({},['seo-news.json']);assert(f.ids.fsSeoNews.innerHTML.includes('保留上次结果'));
  assert(f.ids.radarGrid.innerHTML.includes('独立更新'));assert.equal(f.intervals.length,1);
});

test('missing SEO keeps official cards usable and session changes reject incoming payloads',async()=>{
  const f=await fixture({'seo-news.json':null,'seo-news.status.json':null});
  assert(f.ids.fsSeoNews.innerHTML.includes('等待夜间采集结果'));assert.equal(f.document.body.dataset.dailyState,'live');
  assert(f.ids.radarGrid.innerHTML.includes('官方节点'));assert.equal(f.eval(`${gameExpr('aion2')}.events.length`),0);
  const next=seo();next.documents[0].title_zh='其他会话的数据';next.version='mmoexp-news-'+'1'.repeat(20);
  await f.refresh({'seo-news.json':next},[],true);
  assert(!f.ids.radarGrid.innerHTML.includes('其他会话的数据'));assert(!f.ids.fsSeoNews.innerHTML.includes('其他会话的数据'));
  assert.equal(f.intervals.length,1);assert.equal(f.intervals[0].ms,300000);
});
