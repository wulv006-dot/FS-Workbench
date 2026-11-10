'use strict';
const fs = require('fs');
const path = require('path');
const {Events} = require('discord.js');

function welcomePayload(cfg, member) {
  const link = id => `https://discord.com/channels/${cfg.guildId}/${id}`;
  return {
    content: (member ? 'Welcome <@'+member.id+'> to **MMOEXP Official Club**!\n\n' : '**Welcome to MMOEXP Official Club!**\n\n') +
      '1. Read our community rules.\n' +
      '2. Open **Choose game roles** and select the games you play. The game buttons add your game badges.\n' +
      '3. Expand a game section whenever you need it.\n\n' +
      'Our team will never ask for your password or payment in an unsolicited DM.',
    components: [{type:1,components:[
      {type:2,style:5,label:'Choose game roles',url:link(cfg.channelId)+'/1569201629998092409'},
      {type:2,style:5,label:'Read rules',url:link(cfg.rulesChannelId)},
      {type:2,style:5,label:'Customer support',url:link(cfg.supportChannelId)}]}],
    allowedMentions:{parse:[],users:member ? [member.id] : []}
  };
}
function createWelcome({cfg, directory, getChannel, canWelcome=()=>true, now=()=>Date.now()}) {
  fs.mkdirSync(directory,{recursive:true});
  const ledger=path.join(directory,'welcome-delivery.jsonl');
  const seen=new Set();
  if(fs.existsSync(ledger)) {
    for(const line of fs.readFileSync(ledger,'utf8').split('\n').filter(Boolean)) {
      const row=JSON.parse(line); if(row.key) seen.add(row.key);
    }
  }
  const record=row=>fs.appendFileSync(ledger,JSON.stringify({...row,at:now()})+'\n',{mode:0o600});
  async function joined(member) {
    if(!cfg.enabled || member?.guild?.id!==cfg.guildId || !member.user || member.user.bot || !canWelcome(member)) return false;
    const stamp=member.joinedTimestamp;
    if(!Number.isSafeInteger(stamp) || stamp<=0) return false;
    const key=`${member.id}:${stamp}`;
    if(seen.has(key)) return false;
    // Reserve before sending. Unknown outcomes are never automatically resent.
    record({key,status:'reserved'});seen.add(key);
    try {
      const channel=await getChannel(cfg.channelId);
      if(channel?.guild?.id!==cfg.guildId) throw new Error('Welcome channel guild mismatch');
      const sent=await channel.send(welcomePayload(cfg,member));
      record({key,status:'sent',messageId:sent.id}); return true;
    } catch(error) {
      record({key,status:'not_delivered',code:String(error.code||'unknown')});
      console.warn('[WELCOME] Public welcome not delivered; no DM fallback.');return false;
    }
  }
  async function ensurePanel(client) {
    if(!cfg.enabled) return;
    const marker=path.join(directory,'welcome-panel.json');
    const channel=await client.channels.fetch(cfg.channelId);
    if(channel?.guild?.id!==cfg.guildId) throw new Error('Welcome channel guild mismatch');
    const payload=welcomePayload(cfg);
    if(fs.existsSync(marker)) {
      const saved=JSON.parse(fs.readFileSync(marker,'utf8'));
      if(saved.channelId!==cfg.channelId || saved.status!=='published') throw new Error('Reconcile welcome panel marker');
      const message=await channel.messages.fetch(saved.messageId);
      if(message.author.id!==client.user.id) throw new Error('Welcome panel author mismatch');
      await message.edit(payload);return;
    }
    fs.writeFileSync(marker,JSON.stringify({status:'sending',channelId:cfg.channelId}),{mode:0o600});
    const message=await channel.send(payload);
    fs.writeFileSync(marker,JSON.stringify({status:'published',channelId:cfg.channelId,messageId:message.id}),{mode:0o600});
  }
  return {joined,ensurePanel};
}
function install(client,{canWelcome}={}) {
  const cfg=JSON.parse(fs.readFileSync(path.join(__dirname,'welcome-config.json'),'utf8'));
  if(cfg.guildId!=='1041923524601851914' || cfg.channelId!=='1569198390107971795') throw new Error('Unapproved welcome route');
  const welcome=createWelcome({cfg,directory:path.join(__dirname,'welcome-state'),canWelcome,getChannel:id=>client.channels.fetch(id)});
  client.on(Events.GuildMemberAdd,m=>welcome.joined(m).catch(e=>console.error('[WELCOME] join',e.message)));
  client.once(Events.ClientReady,()=>welcome.ensurePanel(client).catch(e=>console.error('[WELCOME] panel',e.message)));
  return welcome;
}
module.exports={welcomePayload,createWelcome,install};

