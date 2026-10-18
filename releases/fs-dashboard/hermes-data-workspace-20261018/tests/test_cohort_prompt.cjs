'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const source=fs.readFileSync(process.env.BRAIN_SOURCE||path.join(__dirname,'../source/brain.js'),'utf8');
const begin=source.indexOf('  const dataKind=initial.get');
const end=source.indexOf('  refresh().then',begin);
assert(begin>=0&&end>begin);
const handoff=new Function('initial','$','message','let dataRequest=null;'+source.slice(begin,end)+';return dataRequest;');
function fill(kind,evidence){
 const fields={};const data=handoff(new URLSearchParams({data_kind:kind,data_evidence:evidence,start:'2026-10-17',end:'2026-10-17',profile:'FC27',platform:'all',site_group:'main',window_days:'30'}),id=>fields[id]||(fields[id]={}),()=>{});
 return {data,question:fields.question?.value};
}
const cohort=fill('cohort','cohort_0123456789abcdef01234567');
assert.equal(cohort.data.kind,'cohort_observation');
assert.equal(cohort.data.query.window_days,30);
for(const clause of ['一句不超过100字','本次只回答该归档cohort','忽略不相关的收入、利润','实际子群范围','不能据此决定优惠、预算等策略','完整闭日规则计算','证据不足就不写具体日期'])assert(cohort.question.includes(clause),clause);
assert(!/10\/24|10\/25|58名|103|166/.test(cohort.question),'no hardcoded business result or maturity date');
const discount=fill('discount','ws_0123456789abcdef01234567');
assert(discount.question.includes('一句不超过100字'));
assert(!discount.question.includes('本次只回答该归档cohort'));
assert.equal(fill('cohort','invalid').question,undefined);
console.log('PASS cohort-only evidence scope, maturity and concise prompt; other queries unchanged');
