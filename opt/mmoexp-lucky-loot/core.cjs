'use strict';
const crypto=require('node:crypto');
const GUILD='1041923524601851914';
const id=v=>typeof v==='string'&&/^\d{17,20}$/.test(v);
function need(x,msg){if(!x)throw Error(msg);}
function ids(a,max=100){need(Array.isArray(a)&&a.length<=max&&a.every(id),'身份组或用户 ID 格式不正确');return [...new Set(a)];}
function text(v,max,required=false){need(typeof v==='string'&&v.length<=max&&(!required||v.trim()),'文案长度或格式不正确');return v.trim();}
function number(v,min,max){need(Number.isInteger(v)&&v>=min&&v<=max,'数量或期限超出范围');return v;}
function normalize(raw,now=Date.now()){
 need(raw&&typeof raw==='object','活动配置无效');
 const c={title:text(raw.title,100,true),content:text(raw.content,2500,true),guild_id:GUILD,
  channel_id:raw.channel_id,chat_channel_id:raw.chat_channel_id||raw.channel_id,
  announcement_channel_id:raw.announcement_channel_id||raw.chat_channel_id||raw.channel_id,
  announce_join:raw.announce_join===true,join_template:text(raw.join_template??'🎉 {user} 已加入活动：MMOEXP NIUBI！',400,true),pin_message:raw.pin_message===true,
  mode:raw.mode,keyword:text(raw.keyword||'',120),keyword_requires_mention:raw.keyword_requires_mention!==false,eligible_roles:ids(raw.eligible_roles||[]),eligible_users:ids(raw.eligible_users||[]),excluded_roles:ids(raw.excluded_roles||[]),
  mention_roles:ids(raw.mention_roles||[],20),mention_users:ids(raw.mention_users||[],20),
  min_account_days:number(raw.min_account_days??7,0,3650),min_join_days:number(raw.min_join_days??0,0,3650),
  messages_required:number(raw.messages_required??3,1,100),cooldown_seconds:number(raw.cooldown_seconds??60,10,3600),
  start_at:Number(raw.start_at),end_at:Number(raw.end_at),draw_at:Number(raw.draw_at),claim_hours:number(raw.claim_hours??72,1,720),
  test_only:raw.test_only===true,prizes:[],result_content:text(raw.result_content||'GG, winners! Your loot is ready. 🍀',1000)};
 need(id(c.channel_id)&&id(c.chat_channel_id),'请选择活动和聊天频道');
 need(id(c.announcement_channel_id),'请选择报名播报频道');
 need(!c.announce_join||c.join_template.includes('{user}'),'报名播报文案必须包含 {user}，用于显示报名成员');
 need(['button','chat','keyword','button_chat'].includes(c.mode),'参与方式无效');
 need(c.mode!=='keyword'||c.keyword,'请填写报名口令');
 need([c.start_at,c.end_at,c.draw_at].every(Number.isSafeInteger)&&c.end_at>c.start_at&&c.draw_at>=c.end_at,'时间顺序必须为发布 → 截止 → 开奖');
 need(c.draw_at-c.start_at<=30*86400000&&c.draw_at>now,'活动最长30天，开奖时间必须在将来');
 need(Array.isArray(raw.prizes)&&raw.prizes.length>0&&raw.prizes.length<=10,'请配置1至10档奖励');
 for(const p of raw.prizes){need(['coupon','manual'].includes(p.type),'奖励类型无效');
  const prize={type:p.type,label:text(p.label,150,true),quantity:number(p.quantity,1,100),coupon_id:p.type==='coupon'?number(Number(p.coupon_id),1,100000000):null,site_id:266};
  c.prizes.push(prize);}
 need(c.prizes.reduce((a,p)=>a+p.quantity,0)<=100,'每次活动最多100名获奖者');
 return c;
}
function eligible(c,member,now=Date.now()){
 if(!member||member.bot||member.pending)return false;
 const roles=member.roles||[];
 if(c.test_only&&!member.admin)return false;
 if(c.excluded_roles.some(r=>roles.includes(r)))return false;
 if((c.eligible_roles.length||c.eligible_users.length)&&!c.eligible_users.includes(member.id)&&!c.eligible_roles.some(r=>roles.includes(r)))return false;
 if(now-member.created_at<c.min_account_days*86400000)return false;
 if(c.min_join_days&&(!member.joined_at||now-member.joined_at<c.min_join_days*86400000))return false;
 return true;
}
function qualified(c,e){if(!e||e.excluded)return false;return c.mode==='button'?e.joined:c.mode==='keyword'?e.keyword:c.mode==='button_chat'?e.joined&&e.count>=c.messages_required:e.count>=c.messages_required;}
function join(c,m,now){need(c.status==='open'&&now>=c.start_at&&now<c.end_at,'报名尚未开始或已经截止');need(eligible(c,m,now),'你不符合本次活动的参与条件');
 const e=c.entries[m.id]||(c.entries[m.id]={joined:false,count:0,last:0,seen:[],hashes:[]});e.joined=true;return e;}
function message(c,m,event,now){
 if(c.status!=='open'||now<c.start_at||now>=c.end_at||event.at<c.start_at||event.at>=c.end_at||event.channel_id!==c.chat_channel_id||!eligible(c,m,now))return false;
 if(c.mode==='button'||(c.mode==='button_chat'&&!c.entries[m.id]?.joined))return false;
 if(c.mode==='keyword'&&((c.keyword_requires_mention&&!event.mentioned)||!String(event.content||'').toLowerCase().includes(c.keyword.toLowerCase())))return false;
 let e=c.entries[m.id];
 if(e&&(e.seen.includes(event.id)||event.at-e.last<c.cooldown_seconds*1000||e.excluded||qualified(c,e)))return false;
 // Ordinary chat content is never required or stored. If content is available because
 // the member mentions the bot, only a bounded digest is retained for duplicate checks.
 const digest=event.content?crypto.createHash('sha256').update(event.content.trim().toLowerCase()).digest('hex'):null;
 if(digest&&e?.hashes.includes(digest))return false;
 if(!e)e=c.entries[m.id]={joined:false,count:0,last:0,seen:[],hashes:[]};
 e.count++;e.last=event.at;e.seen.push(event.id);if(digest)e.hashes.push(digest);if(c.mode==='keyword')e.keyword=true;return true;
}
function commitment(seed){return crypto.createHash('sha256').update(seed).digest('hex');}
function draw(c,allowedIds,now=Date.now()){
 need(['open','closed'].includes(c.status)&&now>=c.draw_at,'未到开奖时间或已开奖');
 const entrants=Object.keys(c.entries).filter(uid=>allowedIds.has(uid)&&qualified(c,c.entries[uid])).sort();
 c.eligible_hash=crypto.createHash('sha256').update(entrants.join('\n')).digest('hex');c.eligible_count=entrants.length;
 let counter=0;const rand=n=>{const max=0x100000000-(0x100000000%n);let x;do{x=crypto.createHmac('sha256',c.seed).update(c.eligible_hash+':'+counter++).digest().readUInt32BE();}while(x>=max);return x%n;};
 for(let i=entrants.length-1;i>0;i--){const j=rand(i+1);[entrants[i],entrants[j]]=[entrants[j],entrants[i]];}
 c.winners=[];let i=0;
 for(let pi=0;pi<c.prizes.length;pi++){for(let q=0;q<c.prizes[pi].quantity&&i<entrants.length;q++)c.winners.push({user_id:entrants[i++],prize_index:pi,state:'unclaimed',claim_id:crypto.randomUUID(),created_at:now});}
 c.status='drawn';c.drawn_at=now;c.claim_deadline=now+c.claim_hours*3600000;
 return c.winners;
}
function email(value){need(typeof value==='string'&&value.length<=254&&/^[^\s@,;，；<>]+@[^\s@,;，；<>]+\.[^\s@,;，；<>]+$/.test(value),'请填写一个有效的注册邮箱');return value.trim().toLowerCase();}
function grantResult(d,emailValue,batch,job){
 const result={state:'unknown',reason:'发券结果未确认，请核对原记录'};
 if(!d||typeof d!=='object'||(d.batch_no&&d.batch_no!==batch))return result;
 if(job&&String(d.job_id||job)!==String(job))return result;
 if(!job&&d.mode==='async'&&d.job_id)return {state:'pending',job_id:String(d.job_id),reason:'后台发券任务处理中'};
 if(job&&['running','pending'].includes(d.status))return {state:'pending',job_id:String(job),reason:'后台发券任务处理中'};
 const row=Array.isArray(d.rows)&&d.rows.length===1?d.rows[0]:null;
 if(!row||String(row.email||'').toLowerCase()!==emailValue)return result;
 const keys=['success','not_found','pending_register','skipped_limit','failed'];
 if(keys.some(k=>d[k]!==undefined&&(!Number.isInteger(d[k])||d[k]<0||d[k]>1)))return result;
 if((d.total!==undefined&&d.total!==1)||(d.processed!==undefined&&d.processed!==1))return result;
 if(keys.filter(k=>Number(d[k])===1).length!==1)return result;
 const issued=/^[1-9]\d*$/.test(String(row.member_coupon_id||''));
 if(d.success===1&&issued&&d.status!=='failed'&&keys.slice(1).every(k=>!d[k]))return {state:'confirmed',member_coupon_id:String(row.member_coupon_id),reason:'优惠券已发放到账户'};
 if(d.success===0&&!issued&&d.pending_register===1)return {state:'pending_register',reason:'后台已记录，等待该邮箱注册；请勿重复发送'};
 if(d.success===0&&!issued&&d.skipped_limit===1)return {state:'limit',reason:'该邮箱已达此券领取上限'};
 if(d.success===0&&!issued&&(d.failed===1||d.not_found===1))return {state:'rejected',reason:'后台未发放，需管理员处理'};
 return result;
}
function publicCampaign(c){const out=structuredClone(c);delete out.entries;delete out.seed;out.entry_count=Object.values(c.entries||{}).filter(e=>qualified(c,e)).length;
 out.joined_count=Object.keys(c.entries||{}).length;out.winners=(c.winners||[]).map(w=>({user_id:w.user_id,prize_index:w.prize_index,state:w.state,reason:w.reason,claim_id:w.claim_id}));return out;}
module.exports={GUILD,normalize,eligible,qualified,join,message,draw,commitment,email,grantResult,publicCampaign,need};
