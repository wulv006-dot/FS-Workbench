'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {createWelcome}=require('./public-welcome.js');const cfg=require('./welcome-config.json');
const dirs=[];let messages=[];
const channel={guild:{id:cfg.guildId},send:async p=>{messages.push(p);return{id:'public-message'};}};
function env(extra={}){const directory=fs.mkdtempSync(path.join(os.tmpdir(),'mmoexp-welcome-'));dirs.push(directory);return{directory,cfg,getChannel:async()=>channel,...extra};}
function member(extra={}){return{guild:{id:cfg.guildId},id:'123456789',user:{bot:false},joinedTimestamp:12345,send:()=>{throw Error('DM forbidden');},...extra};}
(async()=>{
 const e=env(),w=createWelcome(e),m=member();assert.equal(await w.joined(m),true);assert.equal(messages.length,1);
 assert(messages[0].content.includes('<@123456789>'));assert.deepEqual(messages[0].allowedMentions,{parse:[],users:[m.id]});
 assert.equal(messages[0].components[0].components.length,3);
 assert.equal(await w.joined(m),false);assert.equal(await createWelcome(e).joined(m),false);assert.equal(messages.length,1);
 assert.equal(await w.joined(member({user:{bot:true}})),false);
 assert.equal(await w.joined(member({guild:{id:'different'}})),false);
 assert.equal(await w.joined(member({joinedTimestamp:null})),false);
 assert.equal(await createWelcome(env({canWelcome:()=>false})).joined(m),false);
 assert.equal(await createWelcome(env({cfg:{...cfg,enabled:false}})).joined(m),false);
 const f=createWelcome(env({getChannel:async()=>({guild:{id:cfg.guildId},send:async()=>{throw{code:50013};}})}));
 assert.equal(await f.joined(m),false);assert.equal(await f.joined(m),false);
 assert.equal(await createWelcome(env({getChannel:async()=>({guild:{id:'wrong'}})})).joined(m),false);
 let panels=0,edits=0;const p=createWelcome(env());const pc={guild:{id:cfg.guildId},send:async p=>{panels++;assert.deepEqual(p.allowedMentions,{parse:[],users:[]});return{id:'panel'};},messages:{fetch:async()=>({author:{id:'guard'},edit:async()=>{edits++;}})}};
 const client={user:{id:'guard'},channels:{fetch:async()=>pc}};
 await p.ensurePanel(client);await p.ensurePanel(client);assert.equal(panels,1);assert.equal(edits,1);
 const bad=env();fs.writeFileSync(path.join(bad.directory,'welcome-panel.json'),JSON.stringify({status:'sending',channelId:cfg.channelId}));await assert.rejects(createWelcome(bad).ensurePanel(client),/Reconcile/);
 console.log('PASS: public welcome only, no DMs, exact-member mention, role links, dedupe/restart, scope, anti-abuse gate, send failure, persistent guide, unknown-send protection');
})().finally(()=>{for(const d of dirs)fs.rmSync(d,{recursive:true,force:true});}).catch(e=>{console.error(e);process.exitCode=1;});
