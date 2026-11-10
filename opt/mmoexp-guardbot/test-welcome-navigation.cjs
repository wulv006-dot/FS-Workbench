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
 check(validateGames(games).length,24);check(entries(cfg)[0].components.length,3);
 check(entries(cfg)[0].components.map(x=>x.label),['Choose Roles','Contact Support','My Game Channels']);
 check(games.find(g=>g.key==='22').label,'New World');check(games.find(g=>g.key==='23').label,'Crimson desert');
 assert.throws(()=>validateGames([...games.slice(0,23),games[0]]));checks++;
 const f=fixture(),nav=createNavigation({cfg,games});
 let i=f.interaction(PREFIX+':roles');check(await nav.handle(i));check(i.deferFlags,64);check(i.response.components.flatMap(x=>x.components).length,24);check(f.writes.length,0);
 check(i.response.components[0].components[0].style,games[0].style);check(i.response.components[0].components[0].custom_id.includes(f.member.id));
 i=f.interaction(PREFIX+':channels');await nav.handle(i);check(i.deferFlags,64);check(i.response.embeds[0].fields.length,0);check(f.writes.length,0);
 const game=games[0],role=f.roles.get(game.roleIds[0]);
 i=f.interaction(`${PREFIX}:role:${f.member.id}:${game.key}`);check(await nav.handle(i));check(f.owned.has(role.id));check(f.owned.has('999999999999999999'));check(f.writes,[['add',role.id]]);check(i.updated);
 i=f.interaction(PREFIX+':channels');await nav.handle(i);check(i.response.embeds[0].fields.length,1);check(i.response.embeds[0].fields[0].value.includes('<#'));
 const hidden=f.channels.get(game.channelIds[0]);hidden.permissionsFor=()=>({has:()=>false});
 const blocked=f.channels.get(game.channelIds[1]);blocked.parentId='1569198228367343697';
 let guide=gameChannels(games,f.member,f.guild);check(guide.embeds[0].fields[0].value.includes(hidden.id),false);check(guide.embeds[0].fields[0].value.includes(blocked.id),false);
 const moved=f.channels.get(game.channelIds[2]);moved.parentId='another-game-category';guide=gameChannels(games,f.member,f.guild);check(guide.embeds[0].fields[0].value.includes(moved.id),false);
 i=f.interaction(`${PREFIX}:role:${f.member.id}:${game.key}`);await nav.handle(i);check(f.owned.has(role.id),false);check(f.owned.has('999999999999999999'));
 const before=f.writes.length;
 i=f.interaction(`${PREFIX}:role:222222222222222222:${game.key}`);await nav.handle(i);check(i.response.flags,64);check(f.writes.length,before);
 i=f.interaction(PREFIX+':roles');i.guildId='different';check(await nav.handle(i),false);
 i=f.interaction(PREFIX+':roles');i.channelId='different';check(await nav.handle(i),false);
 i=f.interaction(PREFIX+':roles');i.user.bot=true;check(await nav.handle(i),false);
 i=f.interaction(`${PREFIX}:role:${f.member.id}:missing`);check(await nav.handle(i),false);
 role.permissions.bitfield=P.Administrator;check(safeRole(role,f.bot,f.guild),false);
 i=f.interaction(`${PREFIX}:role:${f.member.id}:${game.key}`);await nav.handle(i);check(f.writes.length,before);
 role.permissions.bitfield=0n;role.managed=true;check(safeRole(role,f.bot,f.guild),false);role.managed=false;
 role.comparePositionTo=()=>1;check(safeRole(role,f.bot,f.guild),false);role.comparePositionTo=()=>-1;
 blocked.permissionOverwrites.cache.set(role.id,{allow:{bitfield:P.ManageChannels}});check(safeRole(role,f.bot,f.guild),false);blocked.permissionOverwrites.cache.clear();
 const f2=fixture();f2.owned.set(games[0].aliasRoleIds[0],{});check(gameChannels(games,f2.member,f2.guild).embeds[0].fields[0].name,'🎮 '+games[0].label);
 for(const g of games)f2.owned.set(g.roleIds[0],{});
 check(gameChannels(games,f2.member,f2.guild,0).embeds[0].fields.length,4);
 check(gameChannels(games,f2.member,f2.guild,999).embeds[0].footer.text.includes('Page 6/6'));
 check(gameChannels(games,f2.member,f2.guild,0).components[0].components.some(x=>x.label==='Next'));
 // An uncertain role API error is reconciled from the same member before reporting success.
 const f3=fixture();f3.member.roles.add=async r=>{f3.owned.set(r.id,r);throw{code:500};};
 i=f3.interaction(`${PREFIX}:role:${f3.member.id}:${game.key}`);await createNavigation({cfg,games}).handle(i);check(i.response.content.startsWith('✅'));
 // Real event registration persists across new welcome messages; no login or network in tests.
 const client=new EventEmitter();installNavigation(client,cfg);i=f2.interaction(PREFIX+':channels');await client.listeners(Events.InteractionCreate)[0](i);check(i.deferFlags,64);check(i.response.embeds[0].fields.length,4);
 console.log(`PASS ${checks} checks: actor isolation, ephemeral navigation, old button layout, exact role toggle, privilege denial, role aliases, visibility filtering, paging, API reconciliation, persistent event wiring.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
