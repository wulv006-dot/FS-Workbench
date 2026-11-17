// Carnival capsule (cumulative-spend) tier rules as scenarios, agreed 2026-11-17.
// The tier claim itself is issued by the main site (interface pending from main-site
// development), so this file is the executable acceptance table for that interface:
// `claim` below is the reference model, and the same table is in
// docs/planning/carnival-landing-20261117/CAPSULE-SCENARIOS.md for the main-site team.
// When the interface exists, the page wiring and its browser test use these rules.
import test from 'node:test';
import assert from 'node:assert/strict';

const TIERS=[[1,1501],[100,1503],[300,1505],[500,1507],[800,1509],[1000,1511]];
// One press: every tier the paid total has reached and that was never issued is issued
// now, lowest first; nothing already issued is issued again.
function claim(paidTotal,issued){
 const fresh=TIERS.filter(([at,id])=>paidTotal>=at&&!issued.includes(id)).map(([,id])=>id);
 return {fresh,issued:[...issued,...fresh]};
}
// Paid total = sum of the member's paid orders in the carnival window (main site).
const total=orders=>Math.round(orders.reduce((s,o)=>s+o,0)*100)/100;

test('one $1000 order, one press: all six tier coupons at once',()=>{
 assert.deepEqual(claim(total([1000]),[]).fresh,[1501,1503,1505,1507,1509,1511]);
});

test('cumulative orders: each press issues only the newly reached tiers',()=>{
 let issued=[];const orders=[];
 const step=(order,expect)=>{orders.push(order);const r=claim(total(orders),issued);issued=r.issued;assert.deepEqual(r.fresh,expect,'after paying $'+total(orders));};
 step(50,[1501]);            // $50: tier $1
 step(60,[1503]);            // $110: tier $100
 step(100,[]);               // $210: nothing new
 step(400,[1505,1507]);      // $610: tiers $300 and $500 together
 step(390,[1509,1511]);      // $1000: tiers $800 and $1000
 step(500,[]);               // $1500: all issued, nothing more
 assert.deepEqual(issued,[1501,1503,1505,1507,1509,1511]);
});

test('pressing again without new spend never issues a second copy',()=>{
 const first=claim(320,[]);assert.deepEqual(first.fresh,[1501,1503,1505]);
 assert.deepEqual(claim(320,first.issued).fresh,[]);
 assert.deepEqual(claim(320,first.issued).issued,first.issued);
});

test('thresholds are inclusive and cents count',()=>{
 assert.deepEqual(claim(0.99,[]).fresh,[]);
 assert.deepEqual(claim(1,[]).fresh,[1501]);
 assert.deepEqual(claim(total([33.33,33.33,33.34]),[]).fresh,[1501,1503]);
 assert.deepEqual(claim(99.99,[]).fresh,[1501]);
});

test('a member who skipped pressing still gets every missed tier later',()=>{
 assert.deepEqual(claim(850,[1501]).fresh,[1503,1505,1507,1509]);
});
