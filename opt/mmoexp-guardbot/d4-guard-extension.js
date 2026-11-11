'use strict';
// A separate guild-scoped policy using the existing GuardBot gateway connection.
const fs = require('./secure-storage');
const path = require('path');
const { Events, PermissionFlagsBits } = require('discord.js');
const GUILD_ID = '1565922092518613064';
const CONFIG = path.join(__dirname, 'd4-guard.json');
const LEDGER = path.join(__dirname, 'd4-action-ledger.jsonl');
const MAP = {
  'і':'i','ї':'i','ӏ':'i','ι':'i','ı':'i','ⅼ':'l',
  'ɡ':'g','ԍ':'g','ց':'g','м':'m','μ':'m','ӎ':'m',
  'о':'o','ο':'o','օ':'o','е':'e','ε':'e',
  'х':'x','χ':'x','р':'p','ρ':'p','υ':'u','ս':'u','ν':'v',
};
function normalize(raw) {
  return String(raw || '').normalize('NFKD').toLowerCase()
    .replace(/[\p{M}\p{Cf}]/gu, '')
    .replace(/./gu, c => MAP[c] || c);
}
const patterns = [
  ['IGGM', '[i1l!|]+[g69]+[g69]+(?:m+|rn)'],
  ['U4GM', '[uv]+[4a]+[g69]+(?:m+|rn)'],
  ['MMOEXP', '(?:m|rn){2,}[o0]+[e3]+[x×]+[p]+'],
];
const supportTail = '(?:support|official|staff|admin|service|team|giveaway|reward|gift|trade|shop|store|gold|sale|vip|cs|bot)';
function editOne(a,b) {
  if (Math.abs(a.length-b.length)>1) return false;
  if(a.length===b.length){let positions=[];for(let i=0;i<a.length;i++)if(a[i]!==b[i])positions.push(i);return positions.length===1 || (positions.length===2 && positions[1]===positions[0]+1 && a[positions[0]]===b[positions[1]] && a[positions[1]]===b[positions[0]]);}
  const big=a.length>b.length?a:b, small=a.length>b.length?b:a;
  for(let i=0;i<big.length;i++)if(big.slice(0,i)+big.slice(i+1)===small)return true;
  return false;
}
function classify(raw) {
  const normalized = normalize(raw);
  const compact = normalized.replace(/[^a-z0-9!|×]/g,'');
  const tokens = normalized.split(/[^a-z0-9!|×]+/).filter(Boolean);
  for(const [brand,pattern] of patterns) {
    const start=new RegExp('^(?:the|official|support|admin|vip|cs)?'+pattern);
    if(start.test(compact)||tokens.some(t=>new RegExp('^'+pattern).test(t)))return {brand,via:'normalized-brand'};
    if(new RegExp(pattern+supportTail).test(compact))return {brand,via:'brand-with-staff-suffix'};
  }
  for(const token of tokens) {
    const folded=token.replace(/0/g,'o').replace(/3/g,'e');
    if(folded.length>=5 && folded.length<=7 && editOne(folded,'mmoexp'))return {brand:'MMOEXP',via:'long-brand-edit-distance-one'};
  }
  return null;
}
function assess(member) {
  for(const [field,value] of [['username',member.user?.username],['globalName',member.user?.globalName],['nickname',member.nickname]]) {
    const hit=classify(value); if(hit)return {...hit,field,value};
  }
  return null;
}
function exempt(member,config,client) {
  if(member.guild.id!==GUILD_ID)return 'other-guild';
  if(member.id===member.guild.ownerId)return 'owner';
  if(member.id===client.user?.id)return 'self';
  if((config.whitelistUserIds||[]).includes(member.id))return 'approved-user';
  if(member.permissions?.has(PermissionFlagsBits.Administrator))return 'administrator';
  if((config.whitelistRoleIds||[]).some(id=>member.roles?.cache.has(id)))return 'approved-role';
  return null;
}
function install(client, providedConfig) {
  const config=providedConfig||JSON.parse(fs.readFileSync(CONFIG,'utf8'));
  if(config.guildId!==GUILD_ID)throw Error('D4 guard target mismatch');
  const inFlight=new Set();
  const recent=new Map();
  async function handle(member,source) {
    if(!member?.guild || member.guild.id!==GUILD_ID || exempt(member,config,client))return;
    const hit=assess(member); if(!hit || inFlight.has(member.id) || Date.now()-(recent.get(member.id)||0)<15000)return;
    inFlight.add(member.id);
    const entry={at:new Date().toISOString(),guildId:GUILD_ID,userId:member.id,source,...hit};
    try {
      const me=member.guild.members.me||await member.guild.members.fetch(client.user.id);
      if(!me.permissions.has(PermissionFlagsBits.BanMembers))throw Error('Missing BanMembers');
      if(!member.bannable)throw Error('Role hierarchy prevents action');
      if(config.dryRun)entry.outcome='dry-run';
      else {
        await member.ban({reason:`D4 anti-impersonation: ${hit.brand}; ${hit.field}=${String(hit.value).slice(0,180)}`,deleteMessageSeconds:0});
        entry.outcome='banned';
      }
      recent.set(member.id,Date.now());
      if(recent.size>2000)for(const [id,at] of recent)if(Date.now()-at>60000)recent.delete(id);
    } catch(error){entry.outcome='blocked-or-error';entry.error=String(error.message).slice(0,200);}
    finally {inFlight.delete(member.id);}
    if(!providedConfig)fs.appendFileSync(LEDGER,JSON.stringify(entry)+'\n',{mode:0o600});
    console.log('[D4-GUARD]',JSON.stringify(entry));
    if(config.logChannelId){
      try {
        const channel=await client.channels.fetch(config.logChannelId);
        if(channel?.guild?.id===GUILD_ID)await channel.send({content:`D4 Guard: **${entry.outcome}**\nUser ID: ${entry.userId}\nRule: ${hit.brand} / ${hit.via}\nField: ${hit.field}\nName: ${String(hit.value).replace(/[`\r\n]/g,' ').slice(0,180)}\nSource: ${source}${entry.error?'\nError: '+entry.error:''}`,allowedMentions:{parse:[]}});
      } catch(error){console.warn('[D4-GUARD] private log failed:',error.message);}
    }
    return entry;
  }
  client.on(Events.GuildMemberAdd,m=>handle(m,'join'));
  client.on(Events.GuildMemberUpdate,(oldM,newM)=>{
    if(oldM.nickname!==newM.nickname||oldM.user?.username!==newM.user?.username||oldM.user?.globalName!==newM.user?.globalName)return handle(newM,'rename');
  });
  client.on(Events.UserUpdate,async(oldU,newU)=>{
    if(oldU.username===newU.username&&oldU.globalName===newU.globalName)return;
    const guild=client.guilds.cache.get(GUILD_ID); if(!guild)return;
    const member=await guild.members.fetch(newU.id).catch(()=>null);if(member)return handle(member,'global-rename');
  });
  client.once(Events.ClientReady,()=>console.log(`[D4-GUARD] ready guild=${GUILD_ID} dryRun=${config.dryRun} log=${config.logChannelId}`));
  return {handle,config,forget:id=>{recent.delete(id);inFlight.delete(id);}};
}
module.exports={install,classify,normalize,assess,exempt,GUILD_ID};
