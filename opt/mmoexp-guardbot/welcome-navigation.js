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
 {type:2,style:5,label:'Contact Support',emoji:{name:'🎧'},url:`https://discord.com/channels/${cfg.guildId}/${cfg.supportChannelId}`},
 {type:2,style:2,label:'My Game Channels',emoji:{name:'🧭'},custom_id:PREFIX+':channels'}]}];}
function validateGames(games){
 if(!Array.isArray(games)||games.length!==24)throw Error('Expected existing 24-game catalog');
 const keys=new Set(),roles=new Set();
 for(const g of games){
  if(!/^\d{1,2}$/.test(g.key)||keys.has(g.key)||typeof g.label!=='string'||g.label.length>60||![1,2,3,4].includes(g.style))throw Error('Invalid game button');
  keys.add(g.key);
  for(const k of ['roleIds','aliasRoleIds','channelIds'])if(!Array.isArray(g[k])||g[k].some(id=>typeof id!=='string'||!/^\d{17,20}$/.test(id)))throw Error('Invalid catalog IDs');
  if(!g.roleIds.length||g.roleIds.some(id=>roles.has(id)))throw Error('Ambiguous game roles');
  for(const id of g.roleIds)roles.add(id);
 }
 return games;
}
function rolePanel(games,member,status=''){
 const rows=[];
 for(let offset=0;offset<games.length;offset+=5)rows.push({type:1,components:games.slice(offset,offset+5).map(g=>({type:2,style:g.style,label:g.label,custom_id:`${PREFIX}:role:${member.id}:${g.key}`,...(g.roleIds.some(id=>member.roles.cache.has(id))?{emoji:{name:'✅'}}:{})}))});
 return{content:status||null,embeds:[{title:'🎭 Pick your games. Find your people.',description:'Choose as many games as you like.\n✅ = selected · Click again to remove that game role.\n\nYour existing game badges stay with you.',color:0xF28C28}],components:rows,allowedMentions:mentions};
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
  if(!i.isButton?.()||!i.customId?.startsWith(PREFIX+':'))return false;
  if(i.guildId!==cfg.guildId||i.channelId!==cfg.channelId||i.guild?.id!==cfg.guildId||i.user?.bot)return false;
  const parts=i.customId.split(':');const action=parts[3];
  if(!['roles','channels','role','page'].includes(action))return false;
  if((action==='roles'||action==='channels')&&parts.length!==4)return false;
  if((action==='role'||action==='page')&&(parts.length!==6||parts[4]!==i.user.id)){
   await i.reply({content:'Please open your own game menu using the welcome card.',flags:MessageFlags.Ephemeral,allowedMentions:mentions});return true;
  }
  const game=action==='role'?games.find(g=>g.key===parts[5]):null;
  if(action==='role'&&!game)return false;
  if(action==='page'&&!/^\d{1,2}$/.test(parts[5]))return false;
  const key=`${i.user.id}:${game?.key||action}`;
  if(busy.has(key)){await i.reply({content:'Your previous choice is still being saved. Please wait a moment.',flags:MessageFlags.Ephemeral,allowedMentions:mentions});return true;}
  busy.add(key);
  try{
   const update=action==='role'||action==='page';
   if(update)await i.deferUpdate();else await i.deferReply({flags:MessageFlags.Ephemeral});
   let member=await i.guild.members.fetch(i.user.id);
   if(member.id!==i.user.id||member.user.bot)throw Error('Member mismatch');
   if(action==='roles'){await i.editReply(rolePanel(games,member));return true;}
   await i.guild.roles.fetch();await i.guild.channels.fetch();
   if(action==='channels'||action==='page'){await i.editReply(gameChannels(games,member,i.guild,action==='page'?Number(parts[5]):0));return true;}
   const bot=await i.guild.members.fetchMe();
   const roles=game.roleIds.map(id=>i.guild.roles.cache.get(id));
   if(!roles.every(r=>safeRole(r,bot,i.guild)))throw Error('Game role cannot be safely assigned');
   const remove=game.roleIds.every(id=>member.roles.cache.has(id));
   try{
    for(const role of roles){if(remove)await member.roles.remove(role,'MMOEXP self-service game role');else if(!member.roles.cache.has(role.id))await member.roles.add(role,'MMOEXP self-service game role');}
   }catch(error){
    member=await i.guild.members.fetch(i.user.id);
    const done=game.roleIds.every(id=>member.roles.cache.has(id)!==remove);
    if(!done)throw error;
   }
   member=await i.guild.members.fetch(i.user.id);
   if(!game.roleIds.every(id=>member.roles.cache.has(id)!==remove))throw Error('Role update not confirmed');
   await i.editReply(rolePanel(games,member,remove?`➖ ${game.label} role removed.`:`✅ ${game.label} selected! Use **My Game Channels** on the welcome card to jump in.`));
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
