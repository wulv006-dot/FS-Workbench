import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createCarnival,publicSchedule,rollDiscount,drawRound,SESSIONS,MYSTERY_SETS} from '../carnival.mjs';

const at=s=>Date.parse(s);
function setup(t,clock){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'carnival-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const published=path.join(dir,'public');fs.mkdirSync(published);
 const state={now:at(clock)},rolls=[];
 const carnival=createCarnival({dir,publishedDir:published,now:()=>state.now,roll:()=>rolls.length?rolls.shift():0});
 return {carnival,state,rolls,published,dir};
}
const q=uid=>new URLSearchParams({uid});

test('odds: first round 30/30/40, later rounds 40/40/20',()=>{
 const count=first=>{const c={8:0,10:0,15:0};for(let r=0;r<100;r++)c[rollDiscount(first,r)]++;return c;};
 assert.deepEqual(count(true),{8:30,10:30,15:40});
 assert.deepEqual(count(false),{8:40,10:40,15:20});
});

test('a first round always has a 15% card; later rounds keep the plain odds',()=>{
 for(let i=0;i<300;i++)assert.ok(drawRound(true,3).includes(15));
 let without=0;for(let i=0;i<300;i++)if(!drawRound(false,3).includes(15))without++;
 assert.ok(without>0,'later rounds can miss 15%');
 assert.deepEqual(drawRound(true,3,(r=>()=>r.shift())([0,35,99])),[8,10,15],'no change when 15% was rolled');
});

test('Black Friday products are released only once their session starts',()=>{
 const before=publicSchedule(at('2026-11-27T11:59:59-05:00'));
 assert.equal(before.sessions.length,10);
 assert.ok(before.sessions.every(s=>s.products.length===0&&s.vouchers.length===0));
 const live=publicSchedule(at('2026-11-27T12:00:00-05:00'));
 assert.equal(live.sessions[0].status,'live');assert.equal(live.sessions[0].products.length,8);
 assert.deepEqual(live.sessions[0].vouchers.map(v=>v.coupon_id),[1461,1463,1465,1467]);
 assert.ok(live.sessions.slice(1).every(s=>s.products.length===0),'later sessions stay hidden');
 const later=publicSchedule(at('2026-11-28T19:30:00-05:00'));
 assert.equal(later.sessions[3].status,'live');assert.equal(later.sessions[3].vouchers[0].slot,'bf_vouchers_1128');
 assert.equal(later.sessions[0].status,'ended');
 assert.equal(SESSIONS[9].ends_at,'2026-12-01T23:00:00-05:00');
});

test('a round is drawn once, stored per member and game, and repeats instead of redrawing',t=>{
 const {carnival,rolls}=setup(t,'2026-11-20T10:00:00-05:00');
 rolls.push(0,35,99);
 const first=carnival.draw({uid:'123456',game:'fc27',items:[0,4,8]});
 assert.equal(first.repeated,false);
 assert.deepEqual(first.current.picks,[{item:0,off:8,coupon_id:1401},{item:4,off:10,coupon_id:1403},{item:8,off:15,coupon_id:1405}]);
 assert.equal(first.coupon_slot,'ms_fc27');assert.equal(first.can_draw,false);
 rolls.push(99,99,99);
 const again=carnival.draw({uid:'123456',game:'fc27',items:[1,2,3]});
 assert.equal(again.repeated,true);assert.deepEqual(again.current.picks,first.current.picks);
 const state=carnival.state(q('123456'));
 assert.deepEqual(state.games.fc27.current.picks,first.current.picks);
 assert.equal(state.games.aion2.current,null);assert.equal(state.games.aion2.can_draw,true);
 assert.equal(carnival.state(q('999')).games.fc27.current,null,'another member is independent');
});

test('a paid use of the game coupon set after the draw unlocks the next round with later-round odds',t=>{
 const {carnival,state,rolls,published,dir}=setup(t,'2026-11-20T10:00:00-05:00');
 rolls.push(0,0,0,1);const firstRound=carnival.draw({uid:'42',game:'poe2',items:[0,1,2]});
 assert.deepEqual(firstRound.current.picks.map(p=>p.off),[8,15,8],'first round: one card raised to 15%');
 // The member presses verify; the dashboard answers (here: the queue is simply emptied).
 const press=()=>{carnival.verify({uid:'42',game:'poe2'});fs.rmSync(path.join(dir,'carnival-verify'),{recursive:true,force:true});};
 // A use before the draw, of another set, or of another member does not unlock.
 fs.writeFileSync(path.join(published,'carnival-unlocks.json'),JSON.stringify({uses:[
  {uid:'42',set:'poe',used_at:'2026-11-20T14:00:00Z'},{uid:'42',set:'fc27',used_at:'2026-11-21T00:00:00Z'},{uid:'7',set:'poe',used_at:'2026-11-21T00:00:00Z'}]}));
 press();assert.equal(carnival.state(q('42')).games.poe2.can_draw,false);
 state.now+=31000;
 fs.writeFileSync(path.join(published,'carnival-unlocks.json'),JSON.stringify({uses:[{uid:'42',set:'poe',used_at:'2026-11-20T16:00:00Z'}]}));
 press();const s=carnival.state(q('42'));
 assert.equal(s.games.poe2.can_draw,true);
 assert.equal(carnival.draw({uid:'42',game:'poe1',items:[0,1,2]}).current.round,1);
 assert.equal(carnival.state(q('42')).games.poe1.can_draw,false,'the use reopened POE 2 only');
 state.now=at('2026-11-21T10:00:00-05:00');rolls.push(79,80,99);
 const second=carnival.draw({uid:'42',game:'poe2',items:[3,4,5]});
 assert.equal(second.current.round,2);assert.deepEqual(second.current.picks.map(p=>p.off),[10,15,15]);
 assert.deepEqual(second.current.picks.map(p=>p.coupon_id),[MYSTERY_SETS.poe.coupons[10],MYSTERY_SETS.poe.coupons[15],MYSTERY_SETS.poe.coupons[15]]);
});

test('requests are validated and the event window is enforced',t=>{
 const {carnival,state}=setup(t,'2026-11-18T23:59:59-05:00');
 const err=(fn,code)=>assert.throws(fn,e=>e.code===code);
 err(()=>carnival.draw({uid:'1',game:'fc27',items:[0,1,2]}),'EVENT_NOT_STARTED');
 state.now=at('2026-11-19T00:00:00-05:00');
 err(()=>carnival.draw({uid:'abc',game:'fc27',items:[0,1,2]}),'MEMBER_REQUIRED');
 err(()=>carnival.draw({uid:'1',game:'gta',items:[0,1,2]}),'INVALID_GAME');
 err(()=>carnival.draw({uid:'1',game:'fc27',items:[0,0,2]}),'INVALID_PICKS');
 err(()=>carnival.draw({uid:'1',game:'fc27',items:[0,1,9]}),'INVALID_PICKS');
 err(()=>carnival.draw({uid:'1',game:'fc27',items:[0,1,2],extra:1}),'INVALID_REQUEST');
 err(()=>carnival.state(q('')),'MEMBER_REQUIRED');
 state.now=at('2026-12-02T00:00:00-05:00');
 err(()=>carnival.draw({uid:'1',game:'fc27',items:[0,1,2]}),'EVENT_ENDED');
});

test('an internal test file opens everything before the event until open_until, then closes by itself',t=>{
 const {carnival,state,published}=setup(t,'2026-11-17T10:00:00-05:00');
 const file=path.join(published,'carnival-test.json'),write=v=>fs.writeFileSync(file,typeof v==='string'?v:JSON.stringify(v));
 const good={open_until:'2026-11-18T23:00:00-05:00',coupon_id:1601,slot:'carnival_test'};
 assert.throws(()=>carnival.draw({uid:'1',game:'fc27',items:[0,1,2]}),e=>e.code==='EVENT_NOT_STARTED');
 assert.equal(carnival.schedule().test,undefined);
 write(good);
 const s=carnival.schedule();
 assert.deepEqual(s.test,{open_until:'2026-11-19T04:00:00.000Z',coupon_id:1601,slot:'carnival_test'});
 assert.equal(s.status,'live');assert.ok(s.sessions.every(x=>x.status==='live'&&x.products.length>0),'all Black Friday sessions shown');
 assert.equal(carnival.draw({uid:'1',game:'fc27',items:[0,1,2]}).current.round,1);
 // Rejected: past open_until, open_until beyond the real start, extra/missing fields, bad ids.
 state.now=at('2026-11-18T23:00:00-05:00');assert.equal(carnival.schedule().test,undefined);
 assert.throws(()=>carnival.draw({uid:'2',game:'fc27',items:[0,1,2]}),e=>e.code==='EVENT_NOT_STARTED');
 state.now=at('2026-11-17T10:00:00-05:00');
 for(const bad of [{...good,open_until:'2026-11-19T00:00:01-05:00'},{...good,extra:1},{open_until:good.open_until,coupon_id:1601},
  {...good,coupon_id:'1601'},{...good,coupon_id:0},{...good,slot:'Bad Slot'},'not json'])
 {write(bad);assert.equal(carnival.schedule().test,undefined,JSON.stringify(bad));}
});

test('stored files never contain the member id in their name',t=>{
 const {carnival,dir}=setup(t,'2026-11-20T10:00:00-05:00');
 carnival.draw({uid:'5550123',game:'wow',items:[0,1,2]});
 const names=fs.readdirSync(path.join(dir,'carnival-mystery'));
 assert.equal(names.length,1);assert.ok(!names[0].includes('5550123'));
});
