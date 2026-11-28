'use strict';
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {PermissionFlagsBits:P,Events}=require('discord.js');
const {PREFIX,entries,validateGames,rolePanel,gameChannels,safeRole,createNavigation,installNavigation}=require('./welcome-navigation');
const games=require('./welcome-games.json'),cfg=require('./welcome-config.json');
let checks=0;const check=(actual,expected=true)=>{assert.deepEqual(actual,expected);checks++;};
function fixture(){
 const owned=new Map([['999999999999999999',{id:'999999999999999999'}]]),writes=[];
 const member={id:'111111111111111111',user:{bot:false},roles:{cache:owned,
  add:async r=>{writes.push(['add',r.id]);owned.set(r.id,r);},
  remove:async r=>{writes.push(['remove',r.id]);owned.delete(r.id);}}};
 const bot={roles:{highest:{position:90}},permissions:{has:p=>p===P.ManageRoles}};
 const roles=new Map(games.flatMap(g=>g.roleIds.map(id=>[id,{id,managed:false,permissions:{bitfield:0n},comparePositionTo:()=>-1}])));
 const channels=new Map(games.flatMap(g=>g.channelIds.map((id,index)=>[id,{id,name:index?'news':'chat',position:index,parentId:'game-category',permissionsFor:()=>({has:p=>p===P.ViewChannel}),permissionOverwrites:{cache:new Map()}}])));
 const guild={id:cfg.guildId,members:{fetch:async id=>{assert.equal(id,member.id);return member;},fetchMe:async()=>bot},roles:{cache:roles,fetch:async()=>roles},channels:{cache:channels,fetch:async()=>channels}};
 function interaction(id){return{isButton:()=>true,customId:id,guildId:cfg.guildId,channelId:cfg.channelId,user:{id:member.id,bot:false},guild,
  reply:async function(p){this.response=p;this.replied=true;},
  deferReply:async function(p){this.deferFlags=p.flags;this.deferred=true;},
  deferUpdate:async function(){this.deferred=true;this.updated=true;},
  editReply:async function(p){this.response=p;}};}
 return{member,bot,guild,writes,owned,roles,channels,interaction};
}
(async()=>{
 check(validateGames(games).length,13);check(entries(cfg)[0].components.map(x=>x.label),['Choose Roles','Contact Support']);
 check(games.map(g=>g.label),['FC27','D4','POE2','WoW','ARC','MLB','COD','GTA','AION2','NBA','Dark and Darker','MapleStory Classic World','Other Games']);
 const f=fixture(),nav=createNavigation({cfg,games});let i=f.interaction(PREFIX+':roles');await nav.handle(i);check(i.deferFlags,64);check(i.response.components[0].components[0].options.length,13);check(i.response.components[1].components.length,1);check(f.writes.length,0);
 i=f.interaction(`${PREFIX}:pick:${f.member.id}`);i.isButton=()=>false;i.isStringSelectMenu=()=>true;i.values=['1','25'];await nav.handle(i);check(f.writes.length,0);check(i.response.components[1].components[0].custom_id.endsWith(':1,25'));check(i.updated);
 const retired=games.at(-1).aliasRoleIds[0];f.owned.set(retired,{});
 i=f.interaction(`${PREFIX}:save:${f.member.id}:1,25`);await nav.handle(i);check(f.writes.length,2);check(f.owned.has(games[0].roleIds[0]));check(f.owned.has(games[11].roleIds[0]));check(f.owned.has(retired));check(f.owned.has('999999999999999999'));check(i.response.content.startsWith('✅'));
 await nav.handle(f.interaction(`${PREFIX}:save:${f.member.id}:1,25`));check(f.writes.length,2);
 await nav.handle(f.interaction(`${PREFIX}:save:${f.member.id}:none`));check(f.writes.length,4);check(f.owned.has(retired));check(f.owned.has('999999999999999999'));
 let before=f.writes.length;await nav.handle(f.interaction(`${PREFIX}:role:${f.member.id}:1`));check(f.writes.length,before);
 for(const suffix of [':save:222222222222222222:1',`:save:${f.member.id}:1,1`,`:save:${f.member.id}:99`]){i=f.interaction(PREFIX+suffix);await nav.handle(i);check(i.response.flags,64);check(f.writes.length,before);}
 for(const field of ['guildId','channelId']){i=f.interaction(PREFIX+':roles');i[field]='wrong';check(await nav.handle(i),false);}
 const role=f.roles.get(games[0].roleIds[0]);role.permissions.bitfield=P.Administrator;await nav.handle(f.interaction(`${PREFIX}:save:${f.member.id}:1`));check(f.writes.length,before);role.permissions.bitfield=0n;
 role.managed=true;check(safeRole(role,f.bot,f.guild),false);role.managed=false;role.comparePositionTo=()=>1;check(safeRole(role,f.bot,f.guild),false);role.comparePositionTo=()=>-1;
 const ch=[...f.channels.values()][0];ch.permissionOverwrites.cache.set(role.id,{allow:{bitfield:P.ManageChannels}});check(safeRole(role,f.bot,f.guild),false);ch.permissionOverwrites.cache.clear();
 const f2=fixture();f2.member.roles.add=async r=>{f2.owned.set(r.id,r);throw{code:500};};i=f2.interaction(`${PREFIX}:save:${f2.member.id}:1`);await createNavigation({cfg,games}).handle(i);check(i.response.content.startsWith('✅'));
 const f3=fixture();f3.member.roles.add=async()=>{throw{code:500};};i=f3.interaction(`${PREFIX}:save:${f3.member.id}:1`);await createNavigation({cfg,games}).handle(i);check(i.response.content.startsWith('⚠️'));check(f3.writes.length,0);
 console.log('PASS '+checks+' checks: compact catalog, preview without writes, explicit save, idempotence, preserved legacy roles, actor isolation, privilege boundaries, API reconciliation');
})().catch(e=>{console.error(e);process.exitCode=1;});
