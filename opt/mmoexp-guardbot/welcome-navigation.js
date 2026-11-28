'use strict';
const fs = require('fs');
const path = require('path');
const {Events,MessageFlags,PermissionFlagsBits:P} = require('discord.js');
const PREFIX='mmoexp:onboard:v2';
const blockedParents=new Set(['1569624942172053525','1569198228367343697','1041923524601851915','1326761290177314896']);
const ordinary=['CreateInstantInvite','ViewChannel','ReadMessageHistory','SendMessages','SendTTSMessages','AddReactions','EmbedLinks','AttachFiles','UseExternalEmojis','UseExternalStickers','Connect','Speak','Stream','UseVAD','RequestToSpeak','UseApplicationCommands','CreatePublicThreads','CreatePrivateThreads','SendMessagesInThreads','SendVoiceMessages','SendPolls','UseSoundboard','UseExternalSounds','UseExternalApps'].reduce((mask,k)=>mask|(P[k]||0n),0n);
const mentions={parse:[]};
function entries(cfg){return[{type:1,components:[
 {type:2,style:1,label:'Choose Roles',emoji:{name:'🎭'},custom_id:PREFIX+':roles'},
 {type:2,style:5,label:'Contact Support',emoji:{name:'🎧'},url:`https://discord.com/channels/${cfg.guildId}/${cfg.supportChannelId}`}]}];}
function validateGames(games){
 if(!Array.isArray(games)||games.length!==13)throw Error('Expected approved 12 games plus Other Games');
 const keys=new Set(),roles=new Set();
 for(const g of games){
  if(!/^\d{1,2}$/.test(g.key)||keys.has(g.key)||typeof g.label!=='string'||g.label.length>60||typeof g.emoji!=='string'||typeof g.description!=='string'||g.description.length>100)throw Error('Invalid game option');
  keys.add(g.key);
  for(const k of ['roleIds','aliasRoleIds','channelIds'])if(!Array.isArray(g[k])||g[k].some(id=>typeof id!=='string'||!/^\d{17,20}$/.test(id)))throw Error('Invalid catalog IDs');
  if(!g.roleIds.length||g.roleIds.some(id=>roles.has(id)))throw Error('Ambiguous game roles');
  for(const id of g.roleIds)roles.add(id);
 }
 return games;
}
function rolePanel(games,member,status='',preview=null){
 const selected=new Set(preview===null?games.filter(g=>g.roleIds.some(id=>member.roles.cache.has(id))).map(g=>g.key):preview);
 const chosen=games.filter(g=>selected.has(g.key));const encoded=chosen.map(g=>g.key).join(',')||'none';
 return{content:status||null,embeds:[{title:'🎮 Make it your community',description:'Choose the games you play below.\nPress **Save Games** when you’re ready — you can change this anytime.',color:0xF28C28,
  fields:[{name:`Your selection · ${chosen.length}`,value:chosen.length?chosen.map(g=>`${g.emoji} ${g.label}`).join(' · '):'No games selected yet. Open the menu below to get started.',inline:false}],
  footer:{text:'Only you can see this • Your choices apply after saving'}}],components:[
   {type:1,components:[{type:3,custom_id:`${PREFIX}:pick:${member.id}`,placeholder:'Choose your games · select more than one',min_values:0,max_values:games.length,options:games.map(g=>({label:g.label,value:g.key,description:g.description,emoji:{name:g.emoji},default:selected.has(g.key)}))}]},
   {type:1,components:[{type:2,style:1,label:'Save Games',emoji:{name:'✅'},custom_id:`${PREFIX}:save:${member.id}:${encoded}`}]}
  ],allowedMentions:mentions};
}
function gameChannels(games,member,guild,page=0){
 const selected=games.filter(g=>[...g.roleIds,...g.aliasRoleIds].some(id=>member.roles.cache.has(id)));
 const pages=Math.max(1,Math.ceil(selected.length/4));page=Math.max(0,Math.min(page,pages-1));
 const fields=selected.slice(page*4,page*4+4).map(g=>{
  const mapped=g.channelIds.map(id=>guild.channels.cache.get(id)).filter(Boolean);
  const homes=new Set(mapped.filter(c=>c.name.includes('chat')).map(c=>c.parentId));
  const channels=mapped.filter(c=>(!homes.size||homes.has(c.parentId)||c.parentId==='1569624939060006962')&&!blockedParents.has(c.parentId)&&!(/^(ticket|closed)-/.test(c.name))&&c.permissionsFor(member)?.has(P.ViewChannel));
  channels.sort((a,b)=>Number(!a.name.includes('chat'))-Number(!b.name.includes('chat'))||a.position-b.position);
  return{name:'🎮 '+g.label,value:channels.length?channels.map(c=>`<#${c.id}>`).join(' · '):'No accessible channels right now. Please contact support.',inline:false};
 });
 const controls=[{type:2,style:1,label:'Choose Roles',emoji:{name:'🎭'},custom_id:PREFIX+':roles'}];
 if(page>0)controls.push({type:2,style:2,label:'Previous',custom_id:`${PREFIX}:page:${member.id}:${page-1}`});
 if(page<pages-1)controls.push({type:2,style:2,label:'Next',custom_id:`${PREFIX}:page:${member.id}:${page+1}`});
 return{content:null,embeds:[{title:'🧭 Your games, one click away',description:selected.length?'These shortcuts match your current game roles.\nTap any channel below to jump straight in.':'🎭 You have no game roles yet. Choose your games first, then your shortcuts will appear here.',color:0x3498DB,fields,footer:{text:`Only you can see this • Page ${page+1}/${pages}`}}],components:[{type:1,components:controls}],allowedMentions:mentions};
}
function safeRole(role,bot,guild){return !!role&&!role.managed&&role.id!==guild.id&&role.permissions.bitfield===0n&&role.comparePositionTo(bot.roles.highest)<0&&bot.permissions.has(P.ManageRoles)&&![...guild.channels.cache.values()].some(c=>((c.permissionOverwrites?.cache.get(role.id)?.allow.bitfield||0n)&~ordinary)!==0n);}
function createNavigation({cfg,games}){
 validateGames(games);const busy=new Set();
 async function handle(i){
  const button=!!i.isButton?.(),select=!!i.isStringSelectMenu?.();
  if((!button&&!select)||!i.customId?.startsWith(PREFIX+':'))return false;
  if(i.guildId!==cfg.guildId||i.channelId!==cfg.channelId||i.guild?.id!==cfg.guildId||i.user?.bot)return false;
  const parts=i.customId.split(':');const action=parts[3];
  if(!['roles','channels','role','page','pick','save'].includes(action))return false;
  if((action==='pick'&&!select)||(action!=='pick'&&!button))return false;
  if((action==='roles'||action==='channels')&&parts.length!==4)return false;
  if(['role','page','pick','save'].includes(action)&&((parts.length!==(action==='pick'?5:6))||parts[4]!==i.user.id)){
   await i.reply({content:'Please open your own game menu using the welcome card.',flags:MessageFlags.Ephemeral,allowedMentions:mentions});return true;
  }
  if(['role','channels','page'].includes(action)){
   await i.reply({content:'This game menu has been refreshed. Open Choose Roles for the new compact menu.',flags:MessageFlags.Ephemeral,components:[{type:1,components:[{type:2,style:1,label:'Choose Roles',custom_id:PREFIX+':roles'}]}],allowedMentions:mentions});return true;
  }
  if(action==='page'&&!/^\d{1,2}$/.test(parts[5]))return false;
  let selected=null;
  if(action==='pick')selected=i.values;
  if(action==='save')selected=parts[5]==='none'?[]:parts[5].split(',');
  if(selected!==null&&(!Array.isArray(selected)||selected.length>games.length||new Set(selected).size!==selected.length||selected.some(key=>!games.some(g=>g.key===key)))){
   await i.reply({content:'That selection is no longer available. Please reopen Choose Roles.',flags:MessageFlags.Ephemeral,allowedMentions:mentions});return true;
  }
  const key=`${i.user.id}:${['roles','pick','save'].includes(action)?'roles':action}`;
  if(busy.has(key)){await i.reply({content:'Your previous choice is still being saved. Please wait a moment.',flags:MessageFlags.Ephemeral,allowedMentions:mentions});return true;}
  busy.add(key);
  try{
   const update=['pick','save','page'].includes(action);
   if(update)await i.deferUpdate();else await i.deferReply({flags:MessageFlags.Ephemeral});
   let member=await i.guild.members.fetch(i.user.id);
   if(member.id!==i.user.id||member.user.bot)throw Error('Member mismatch');
   if(action==='roles'){await i.editReply(rolePanel(games,member));return true;}
   if(action==='pick'){await i.editReply(rolePanel(games,member,'Ready when you are — press Save Games to apply your selection.',selected));return true;}
   await i.guild.roles.fetch();await i.guild.channels.fetch();
   if(action==='channels'||action==='page'){await i.editReply(gameChannels(games,member,i.guild,action==='page'?Number(parts[5]):0));return true;}
   const bot=await i.guild.members.fetchMe();
   const roles=games.flatMap(g=>g.roleIds).map(id=>i.guild.roles.cache.get(id));
   if(!roles.every(r=>safeRole(r,bot,i.guild)))throw Error('Game role cannot be safely assigned');
   const wanted=new Set(games.filter(g=>selected.includes(g.key)).flatMap(g=>g.roleIds));
   const matches=actor=>roles.every(role=>actor.roles.cache.has(role.id)===wanted.has(role.id));
   try{
    for(const role of roles){if(wanted.has(role.id)&&!member.roles.cache.has(role.id))await member.roles.add(role,'MMOEXP self-service game selection');else if(!wanted.has(role.id)&&member.roles.cache.has(role.id))await member.roles.remove(role,'MMOEXP self-service game selection');}
   }catch(error){
    member=await i.guild.members.fetch(i.user.id);
    if(!matches(member)){await i.editReply(rolePanel(games,member,'⚠️ Some choices could not be saved. Your current game roles are shown below. Please try again or contact support.'));return true;}
   }
   member=await i.guild.members.fetch(i.user.id);
   if(!matches(member))throw Error('Role update not confirmed');
   await i.editReply(rolePanel(games,member,`✅ Saved ${selected.length} game choices. Your channel shortcuts are ready.`));
   return true;
  }catch(error){
   console.warn('[WELCOME] Navigation failed:',error.code||error.message);
   const payload={content:'We could not confirm that change. Please try again later or contact support.',allowedMentions:mentions};
   if(i.deferred||i.replied)await i.editReply(payload).catch(()=>{});else await i.reply({...payload,flags:MessageFlags.Ephemeral}).catch(()=>{});
   return true;
  }finally{busy.delete(key);}
 }
 return{handle};
}
function installNavigation(client,cfg){
 const games=JSON.parse(fs.readFileSync(path.join(__dirname,'welcome-games.json'),'utf8'));
 const nav=createNavigation({cfg,games});
 client.on(Events.InteractionCreate,i=>nav.handle(i).catch(e=>console.warn('[WELCOME] Interaction error',e.code||'unknown')));
 return nav;
}
module.exports={PREFIX,entries,validateGames,rolePanel,gameChannels,safeRole,createNavigation,installNavigation};
