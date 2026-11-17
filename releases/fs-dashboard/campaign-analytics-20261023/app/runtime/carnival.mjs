// MMOEXP Carnival 2026 (Nov 19 – Dec 2 ET) server side of /events/Carnival.html.
// - The schedule and Black Friday products live here, so a session's products are only
//   sent once that session has started (the page source carries none of them).
// - The Mystery Shop draw happens here with the confirmed odds and is stored per
//   member and game, so a refresh cannot redraw. The member id comes from the page
//   (the origin strips cookies); the coupons themselves are claimed from the main
//   site's carnival slots, which this server does not control.
// - A new round unlocks once a paid order used one of that game's Mystery coupons
//   after the round was drawn. Admin is only read when the member presses "verify":
//   this server drops a request file in dir/carnival-verify, the dashboard answers it
//   from Admin coupon logs and writes the paid-use list plus a check stamp to the
//   shared public directory, which is read here.
import fs from 'node:fs';
import path from 'node:path';
import {randomInt,createHash} from 'node:crypto';
import {atomic} from '../analytics/store.mjs';
import {fail} from './snapshot.mjs';

const ET='-05:00';
export const CARNIVAL={
 starts_at:'2026-11-19T00:00:00'+ET, ends_at:'2026-12-02T00:00:00'+ET,
 flash_starts_at:'2026-11-27T00:00:00'+ET, gacha_starts_at:'2026-11-30T00:00:00'+ET,
};
const DAYS=['2026-11-27','2026-11-28','2026-11-29','2026-11-30','2026-12-01'];
export const SESSIONS=DAYS.flatMap((date,day)=>[['12:00','16:00'],['19:00','23:00']].map(([start,end],slot)=>({
 index:day*2+slot,day,starts_at:`${date}T${start}:00${ET}`,ends_at:`${date}T${end}:00${ET}`,voucher_slot:'bf_vouchers_'+date.slice(5).replace('-',''),
})));
// Coupon ids by Mystery coupon set and discount (Admin, created 2026-11-17).
export const MYSTERY_SETS={
 fc27:{slot:'ms_fc27',coupons:{8:1401,10:1403,15:1405}},
 aion2:{slot:'ms_aion2',coupons:{8:1407,10:1409,15:1411}},
 wow:{slot:'ms_wow',coupons:{8:1413,10:1415,15:1417}},
 d4:{slot:'ms_d4',coupons:{8:1419,10:1421,15:1423}},
 poe:{slot:'ms_poe',coupons:{8:1425,10:1427,15:1429}},
 mix:{slot:'ms_mix',coupons:{8:1431,10:1433,15:1435}},
};
export const MYSTERY_GAMES={fc27:'fc27',aion2:'aion2',wow:'wow',d4:'d4',poe1:'poe',poe2:'poe',maple:'mix',arc:'mix',codmw4:'mix'};
const POOL_SIZE=9,PICKS=3;
// Confirmed odds per card: first round 8/10/15 = 30/30/40, later rounds 40/40/20.
export function rollDiscount(first,roll=randomInt(100)){return first?(roll<30?8:roll<60?10:15):(roll<40?8:roll<80?10:15);}
// A member's first round always shows at least one 15% card (one random card is raised
// to 15% when none rolled it); later rounds use the plain odds.
export function drawRound(first,count,roll){
 const offs=Array.from({length:count},()=>rollDiscount(first,roll?.()));
 if(first&&!offs.includes(15))offs[roll?roll()%count:randomInt(count)]=15;
 return offs;
}
const VERIFY_GAP_MS=30000,VERIFY_QUEUE_MAX=500;

const VOUCHERS=[[60,5],[100,8],[150,12],[250,20]];
const VOUCHER_IDS={'1127':[1461,1463,1465,1467],'1128':[1469,1471,1473,1475],'1129':[1477,1479,1481,1483],'1130':[1485,1487,1489,1491],'1201':[1493,1495,1497,1499]};
const FC_PLATFORMS={ps:{label:'PlayStation 4 | 5',aid:21587},xbox:{label:'Xbox One | X | S',aid:21585},pc:{label:'PC',aid:21589}};
// Same products in every session (operations may make them per session later).
export const FLASH_PRODUCTS=[
 {key:'fc27-coins',category:'currency',game:'FC 27',name:'1000K FC 27 Coins',off:18,coupon_id:1513,image:'assets/carnival-c96b27222fd5.webp',store_url:'/Fc-27/Coins.html',
  quote:{game_id:1327,top_cid:1,category_id:9623,quantity:1000,options:Object.fromEntries(Object.entries(FC_PLATFORMS).map(([k,v])=>[k,{label:v.label,aid:v.aid,goods_id:{ps:163329311,xbox:163329277,pc:163329345}[k]}]))}},
 {key:'wow-gold',category:'currency',game:'WoW Forever',name:'10G WoW Forever Gold',off:20,coupon_id:1443,image:'assets/carnival-328e8cd04248.webp',store_url:'/wow-gold.html',
  quote:{game_id:1367,top_cid:1,category_id:9991,quantity:10,server_choice:'wow'}},
 {key:'arc-coins',category:'currency',game:'ARC Raiders',name:'500K ARC Raiders Coins',off:18,coupon_id:1445,image:'assets/carnival-e8d63d3be276.webp',store_url:'/Arc-raiders/Coins.html',
  quote:{game_id:925,top_cid:1,category_id:6955,quantity:500,options:{pc:{label:'PC',aid:19835,goods_id:105267633}}}},
 {key:'maple-mesos',category:'currency',game:'MapleStory Classic World',name:'1000K Mesos',off:20,coupon_id:1447,image:'assets/carnival-bc2fbaf50fad.webp',store_url:'/Maplestory-classic-world/Mesos.html',
  quote:{game_id:1333,top_cid:1,category_id:9661,quantity:1000,options:{windia:{label:'Global · Windia',aid:21627,goods_id:165167189}}}},
 {key:'fc27-yamal',category:'items',game:'FC 27',name:'Lamine Yamal 90 RW++ Gold Non Rare',off:20,coupon_id:1515,image:'assets/carnival-3ae22da86322.webp',store_url:'/Fc-27/Players.html',
  quote:{game_id:1327,top_cid:2,category_id:9627,quantity:1,keyword:'Lamine Yamal',options:Object.fromEntries(Object.entries(FC_PLATFORMS).map(([k,v])=>[k,{label:v.label,aid:v.aid,goods_id:{ps:170015245,xbox:170026709,pc:170015249}[k]}]))}},
 {key:'maple-gloves',category:'items',game:'MapleStory Classic World',name:'Gloves Attack Scroll: Intermediate',off:20,coupon_id:1455,image:'assets/carnival-acf5dde56ba3.webp',store_url:'/Maplestory-classic-world/Items.html',
  quote:{game_id:1333,top_cid:2,category_id:10079,quantity:1,keyword:'Gloves Attack Scroll',options:{windia:{label:'Global · Windia',aid:21627,goods_id:186209371}}}},
 {key:'poe2-divine',category:'items',game:'POE 2',name:'Divine Orb (1000+500 Free)',off:18,coupon_id:1457,image:'assets/carnival-01455dbaacbe.webp',store_url:'/Poe-2/Currency.html',
  quote:{game_id:552,top_cid:2,category_id:1338,quantity:1,keyword:'Divine Orb',options:{rites:{label:'Forbidden Rites',aid:20137,goods_id:186208657}}}},
 {key:'d4-spark',category:'items',game:'Diablo 4',name:'Resplendent Spark x100 (Manual salvage required)',off:20,coupon_id:1459,image:'assets/carnival-2ca444fddc2a.webp',store_url:'/Diablo-4/Items.html',
  quote:{game_id:456,top_cid:2,category_id:3955,quantity:1,keyword:'Resplendent Spark',options:{s15:{label:'Season 15 Softcore',aid:15943,goods_id:170070065}}}},
];

const time=s=>Date.parse(s);
const status=(start,end,clock)=>clock<time(start)?'upcoming':clock<time(end)?'live':'ended';
// Internal test before the event: the shared public directory may hold
// carnival-test.json = {open_until, coupon_id, slot}, written by an operator on the server.
// While it is valid every act is open and every claim uses that one test coupon. It can
// never reach into the real event (open_until must not be after the real start), so it
// switches itself off at the latest when the event begins; deleting the file closes it.
export const CARNIVAL_TEST_FILE='carnival-test.json';
export function carnivalTest(dir,clock){
 if(!dir)return null;let t;
 try{const f=path.join(dir,CARNIVAL_TEST_FILE),st=fs.lstatSync(f);if(st.isSymbolicLink()||!st.isFile()||st.size>2000)return null;t=JSON.parse(fs.readFileSync(f,'utf8'));}catch{return null;}
 if(!exact(t,['open_until','coupon_id','slot']))return null;
 const until=time(t.open_until);
 if(!Number.isFinite(until)||clock>=until||until>time(CARNIVAL.starts_at))return null;
 if(!Number.isInteger(t.coupon_id)||t.coupon_id<=0||t.coupon_id>=1e9||typeof t.slot!=='string'||!/^[a-z0-9_]{1,40}$/.test(t.slot))return null;
 return {open_until:new Date(until).toISOString(),coupon_id:t.coupon_id,slot:t.slot};
}
export function publicSchedule(clock,test=null){
 if(test)return {server_time:new Date(clock).toISOString(),...CARNIVAL,status:'live',test,
  sessions:SESSIONS.map(s=>({...publicSchedule(time(s.starts_at)).sessions[s.index],status:'live'}))};
 return {server_time:new Date(clock).toISOString(),...CARNIVAL,status:status(CARNIVAL.starts_at,CARNIVAL.ends_at,clock),
  sessions:SESSIONS.map(s=>{const st=status(s.starts_at,s.ends_at,clock);
   // Products and voucher ids are released only once a session has started.
   const released=st!=='upcoming';
   return {index:s.index,day:s.day,starts_at:s.starts_at,ends_at:s.ends_at,status:st,
    products:released?structuredClone(FLASH_PRODUCTS):[],
    vouchers:released?VOUCHERS.map(([attain,reduce],i)=>({key:`voucher-${reduce}`,category:'voucher',attain,reduce,slot:s.voucher_slot,coupon_id:VOUCHER_IDS[s.voucher_slot.slice(-4)][i]})):[]};
  })};
}

const member=v=>{if(typeof v!=='string'||!/^[1-9]\d{0,19}$/.test(v))fail('MEMBER_REQUIRED',400);return v;};
const gameId=v=>{if(typeof v!=='string'||!Object.hasOwn(MYSTERY_GAMES,v))fail('INVALID_GAME',400);return v;};
const exact=(v,keys)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).every(k=>keys.includes(k))&&keys.every(k=>Object.hasOwn(v,k));

export function createCarnival({dir,publishedDir,now=Date.now,roll}={}){
 const base=path.join(dir,'carnival-mystery'),queue=path.join(dir,'carnival-verify');
 // File names never contain the member id itself.
 const hashed=uid=>createHash('sha256').update('carnival-2026:'+uid).digest('hex').slice(0,32);
 const file=(uid,game)=>path.join(base,hashed(uid)+'-'+game+'.json');
 const checkKey=(uid,game)=>hashed(uid)+'-'+MYSTERY_GAMES[game];
 const requestFile=(uid,game)=>path.join(queue,checkKey(uid,game)+'.json');
 function read(uid,game){
  const f=file(uid,game);if(!fs.existsSync(f))return {game,rounds:[]};
  let record;try{const st=fs.lstatSync(f);if(st.isSymbolicLink()||!st.isFile()||st.size>64000)throw Error();record=JSON.parse(fs.readFileSync(f,'utf8'));}catch{fail('MYSTERY_RECORD_UNKNOWN',409);}
  if(record.game!==game||!Array.isArray(record.rounds))fail('MYSTERY_RECORD_UNKNOWN',409);
  return record;
 }
 // Paid uses of Mystery coupons: {generated_at, uses:[{uid,set,used_at}]}. Missing file = none known yet.
 function paidUses(){
  if(!publishedDir)return null;const f=path.join(publishedDir,'carnival-unlocks.json');
  try{const data=JSON.parse(fs.readFileSync(f,'utf8'));return Array.isArray(data.uses)?data:null;}catch{return null;}
 }
 function unlocked(uid,game,round){
  const uses=paidUses();if(!uses)return false;const set=MYSTERY_GAMES[game];
  return uses.uses.some(u=>u.uid===uid&&u.set===set&&time(u.used_at)>time(round.drawn_at));
 }
 // Outcome of the member's last "verify" press while the round is still locked.
 function verifyState(uid,game,record){
  const asked=record.verify_requested_at;if(!asked)return null;
  if(fs.existsSync(requestFile(uid,game)))return {status:'checking'};
  const check=paidUses()?.checked?.[checkKey(uid,game)];
  if(check&&time(check.at)>=time(asked))return {status:check.ok?'not_found':'error'};
  return {status:'checking'};
 }
 function view(uid,game,record){
  const last=record.rounds.at(-1),locked=!!last&&!unlocked(uid,game,last);
  const set=MYSTERY_SETS[MYSTERY_GAMES[game]];
  return {game,coupon_slot:set.slot,rounds_drawn:record.rounds.length,
   current:locked?{round:last.round,drawn_at:last.drawn_at,picks:last.picks.map(p=>({item:p.item,off:p.off,coupon_id:set.coupons[p.off]}))}:null,
   can_draw:!locked,verify:locked?verifyState(uid,game,record):null};
 }
 function window(){const clock=now();if(clock<time(CARNIVAL.starts_at)&&!carnivalTest(publishedDir,clock))fail('EVENT_NOT_STARTED',409);if(clock>=time(CARNIVAL.ends_at))fail('EVENT_ENDED',409);return clock;}
 return {
  schedule:()=>{const clock=now();return publicSchedule(clock,carnivalTest(publishedDir,clock));},
  state(query){const uid=member(query.get('uid')),games=Object.keys(MYSTERY_GAMES);
   return {server_time:new Date(now()).toISOString(),games:Object.fromEntries(games.map(g=>[g,view(uid,g,read(uid,g))]))};},
  draw(body){
   if(!exact(body,['uid','game','items']))fail('INVALID_REQUEST',400);
   const uid=member(body.uid),game=gameId(body.game),items=body.items;
   if(!Array.isArray(items)||items.length!==PICKS||new Set(items).size!==PICKS||items.some(i=>!Number.isInteger(i)||i<0||i>=POOL_SIZE))fail('INVALID_PICKS',400);
   const clock=window(),record=read(uid,game),last=record.rounds.at(-1);
   // An open round is returned as it is: the same picks never get a second roll.
   if(last&&!unlocked(uid,game,last))return {...view(uid,game,record),repeated:true};
   const offs=drawRound(record.rounds.length===0,PICKS,roll);
   record.rounds.push({round:record.rounds.length+1,drawn_at:new Date(clock).toISOString(),picks:items.map((item,i)=>({item,off:offs[i]}))});
   delete record.verify_requested_at;
   fs.mkdirSync(base,{recursive:true,mode:0o700});atomic(file(uid,game),record);
   return {...view(uid,game,record),repeated:false};
  },
  // The member says the round's order is paid: queue one Admin check (at most one per
  // member and coupon set every 30 seconds). The page then polls the state.
  verify(body){
   if(!exact(body,['uid','game']))fail('INVALID_REQUEST',400);
   const uid=member(body.uid),game=gameId(body.game),clock=window(),record=read(uid,game);
   const current=view(uid,game,record);if(!current.current)return current;
   const pending=fs.existsSync(requestFile(uid,game));
   if(pending||record.verify_requested_at&&clock-time(record.verify_requested_at)<VERIFY_GAP_MS)return current;
   fs.mkdirSync(queue,{recursive:true,mode:0o700});
   if(fs.readdirSync(queue).length>=VERIFY_QUEUE_MAX)fail('VERIFY_BUSY',503);
   record.verify_requested_at=new Date(clock).toISOString();
   atomic(requestFile(uid,game),{uid,set:MYSTERY_GAMES[game],requested_at:record.verify_requested_at});
   atomic(file(uid,game),record);
   return view(uid,game,record);
  },
 };
}
