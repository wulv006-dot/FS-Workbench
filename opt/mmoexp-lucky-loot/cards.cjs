'use strict';
const C=require('./core.cjs');
const APP='1570345932699074611',POLICY='https://47.85.224.112/lucky-loot/privacy';
const stamp=t=>`<t:${Math.floor(t/1000)}:R>`;
function entryHint(c){
 if(c.mode==='button')return '🎟️ Click **Join giveaway** below — you’re in!';
 if(c.mode==='button_chat')return `🎟️ Join below, then send ${c.messages_required} message${c.messages_required===1?'':'s'} in <#${c.chat_channel_id}>.`;
 if(c.mode==='chat')return `💬 Send ${c.messages_required} message${c.messages_required===1?'':'s'} in <#${c.chat_channel_id}> to enter.`;
 return `💬 Send ${c.keyword_requires_mention?'<@'+APP+'> ':''}**${c.keyword}** in <#${c.chat_channel_id}>.`;
}
function rules(c){
 const lines=[entryHint(c),'🎫 One entry per person. Free to enter; no purchase needed.'];
 if(['chat','button_chat'].includes(c.mode))lines.push(`Messages count once every ${c.cooldown_seconds}s. Extra messages do not improve your odds.`);
 if(c.test_only)lines.push('🧪 Administrator-only test.');
 if(c.eligible_roles.length)lines.push('Eligible roles: '+c.eligible_roles.map(x=>'<@&'+x+'>').join(', '));
 if(c.eligible_users.length)lines.push(c.eligible_roles.length?'Selected members may also enter.':'Selected members only.');
 if(c.excluded_roles.length)lines.push('Excluded roles: '+c.excluded_roles.map(x=>'<@&'+x+'>').join(', '));
 if(c.min_account_days)lines.push(`Account age: ${c.min_account_days}+ days.`);
 if(c.min_join_days)lines.push(`Server membership: ${c.min_join_days}+ days.`);
 lines.push(`Entry closes <t:${Math.floor(c.end_at/1000)}:F> · Draw <t:${Math.floor(c.draw_at/1000)}:F>.`);
 lines.push(`Random draw; one prize per person. Claim within ${c.claim_hours} hours. If there are fewer eligible entries, fewer prizes are awarded.`);
 return lines.join('\n');
}
function rewardRules(c){return c.prizes.map(p=>{
 const s=p.coupon_snapshot;if(!s)return `**${p.label}** · ${p.quantity} winner${p.quantity===1?'':'s'}`;
 return `**${p.label}** · ${p.quantity} winner${p.quantity===1?'':'s'}\n${Number(s.attain)===0?'No minimum spend':'Minimum spend $'+s.attain} · ${s.mode_type===1?'$'+s.reduce+' off':'discount '+s.reduce} · ${s.days?s.days+' days validity':'fixed validity'} · ${s.repeat_qty||'unlimited'} per account\n${s.game_id?'Game restriction: '+s.game_id:'All games'} · MMOEXP account delivery`;
}).join('\n\n');}
function details(c){return {embeds:[{title:'📋 Activity rules',description:rules(c).slice(0,4096),color:0x7c6cf0,fields:[{name:'🎁 Reward details',value:rewardRules(c).slice(0,1024)}]}],components:[{type:1,components:[{type:2,style:5,label:'🔒 Privacy policy',url:POLICY}]}],allowedMentions:{parse:[]}};}
function buttons(c,drawn=false){
 const closed=['closed','drawn','cancelled','expired','attention'].includes(c.status);
 const primary=drawn?{label:'🎁 Claim reward',custom_id:'ll:claim:'+c.id,style:3,disabled:!(c.winners||[]).length}:{label:closed?'🔒 Entry closed':'🎟️ Join giveaway',custom_id:'ll:join:'+c.id,style:1,disabled:closed||c.mode==='chat'||c.mode==='keyword'};
 return [{type:1,components:[{type:2,...primary},{type:2,style:2,label:drawn?'📬 My status':'✅ My entry',custom_id:'ll:progress:'+c.id},{type:2,style:2,label:'📋 Rules',custom_id:'ll:rules:'+c.id},{type:2,style:5,label:'🔒 Privacy',url:POLICY}]}];
}
function footer(c,drawn){return drawn?'MMOEXP · Thanks for playing! 🍀':'MMOEXP · One entry, one chance 🍀';}
function card(c,drawn=false){
 const empty=drawn&&!(c.winners||[]).length;
 const fields=[];let description;
 if(drawn){
  const copy=c.result_content==='Congratulations to our winners! Click Claim reward to enter your email privately.'?'GG, winners! Your loot is ready. 🍀':c.result_content;
  description=empty?'🌙 No eligible entries this time. Catch the next drop!':(copy||'GG, winners! Your loot is ready.').slice(0,700)+'\n\n🎁 Click **Claim reward** below to collect privately.';
  for(let p=0;p<c.prizes.length;p++){const users=c.winners.filter(w=>w.prize_index===p).map(w=>'<@'+w.user_id+'>');for(let j=0;j<users.length;j+=30)fields.push({name:'🏆 '+c.prizes[p].label,value:users.slice(j,j+30).join(' ')});}
  if(!empty)fields.push({name:'⏳ Claim deadline',value:stamp(c.claim_deadline)});
 }else{
  description=c.content.slice(0,900)+'\n\n'+( ['closed','drawn'].includes(c.status)?'🔒 Entries are closed. Thanks for joining!':entryHint(c));
  fields.push({name:'🎁 Up for grabs',value:c.prizes.map(p=>`**${p.quantity} × ${p.label}**`).join('\n').slice(0,1024)});
  if(c.end_at!==c.draw_at)fields.push({name:'⏰ Entry closes',value:stamp(c.end_at),inline:true});
  fields.push({name:'🎲 Draw',value:stamp(c.draw_at),inline:true});
 }
 const mentions=drawn?[]:c.mention_roles.map(x=>'<@&'+x+'>').concat(c.mention_users.map(x=>'<@'+x+'>'));
 return {content:mentions.join(' '),embeds:[{title:(c.test_only?'🧪 ':'')+(drawn?'🎉 Winners — ':'🎁 ')+c.title,color:drawn?0x42d6a4:0x8b6cef,description,fields,footer:{text:footer(c,drawn)}}],components:buttons(c,drawn),allowed_mentions:{parse:[],roles:drawn?[]:c.mention_roles,users:drawn?c.winners.map(w=>w.user_id):c.mention_users,replied_user:false}};
}
function announcement(c,uid){return {content:c.join_template.replaceAll('{user}','<@'+uid+'>').replaceAll('{activity}',c.title).slice(0,1800),allowed_mentions:{parse:[],users:[uid],roles:[],replied_user:false}};}
function progress(c,uid){const e=c.entries[uid],w=c.winners?.find(w=>w.user_id===uid);if(w)return `🏆 **${c.prizes[w.prize_index].label}**\n${w.reason||'🎁 You won! Click Claim reward to collect privately.'}`;if(C.qualified(c,e))return '✅ You’re entered. Good luck! 🍀';if(c.mode==='button')return '🎟️ Click Join giveaway to enter.';return `💬 Progress: ${e?.count||0}/${c.messages_required}\n${entryHint(c)}`;}
module.exports={card,buttons,entryHint,rules,details,announcement,progress,footer};
