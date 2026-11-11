'use strict';
const path=require('path');
const crypto=require('crypto');
const {Events,MessageFlags,SlashCommandBuilder}=require('discord.js');
const storage=require('./secure-storage');
const POLICY_URL='https://mmoexp-bot-privacy.workspace-584227.chatgpt.site/';
const SUPPORT_URL='https://www.mmoexp.com/Contact.html';
const RELEASE='2026-11-11.1';
function commands(){return [
  new SlashCommandBuilder().setName('privacy').setDescription('Read the bot privacy policy and manage your stored data'),
  new SlashCommandBuilder().setName('privacy-delete').setDescription('Delete your own bot data after a private confirmation')
].map(c=>c.toJSON());}
function privacyPayload(){return {
  embeds:[{title:'Your data in MMOEXP_BOT',color:0xF28C28,description:
    'We use member names and roles for community safety and onboarding. We do not track your presence or read general chat content.\n\n'+
    'Stored bot records are encrypted. Operational records expire after 30 days and diagnostic records after 7 days. Necessary server configuration and allowlists remain while configured.\n\n'+
    'You can delete your stored bot records and user ID exemptions below. This does not unban you, change your Discord roles, or erase Discord audit logs and previously posted messages. Future interactions and security events can create new necessary records.\n\n'+
    `[Privacy policy](${POLICY_URL}) · [Contact support](${SUPPORT_URL})`}],
  components:[{type:1,components:[{type:2,style:2,label:'Delete my stored data',custom_id:'privacy:delete'},{type:2,style:5,label:'Privacy policy',url:POLICY_URL}]}],allowedMentions:{parse:[]}
};}
function installConsole(store=storage){
  const originals={};
  for(const level of ['log','warn','error']) {
    originals[level]=console[level].bind(console);
    console[level]=(...args)=>{
      // The system journal receives a fixed label only, never names, IDs, message content or error payloads.
      try {store.appendFileSync(path.join(store.root,'runtime-events.jsonl'),JSON.stringify({at:new Date().toISOString(),level,
        text:args.map(v=>v instanceof Error ? `${v.name}: ${v.message}` : typeof v==='string'?v:JSON.stringify(v)).join(' ').slice(0,6000)})+'\n');}
      catch {originals.error('[guardbot] encrypted diagnostic write failed');}
      originals[level]('[guardbot] '+level+' event');
    };
  }
  return ()=>Object.assign(console,originals);
}
function createPrivacy({store=storage,onErase=()=>{},now=()=>Date.now()}={}){
  const confirmations=new Map();
  function confirmation(userId){
    for(const [key,value] of confirmations)if(value.expires<=now() || value.userId===userId)confirmations.delete(key);
    const nonce=crypto.randomBytes(16).toString('hex');
    confirmations.set(nonce,{userId,expires:now()+600000});
    return {content:'Delete bot records associated with your own Discord account, including any stored user ID exemption? This is permanent. Your Discord roles, bans, previous messages and Discord audit logs remain unchanged. You can use the bot again afterward.',
      components:[{type:1,components:[{type:2,style:4,label:'Confirm deletion',custom_id:'privacy:confirm:'+nonce},{type:2,style:2,label:'Cancel',custom_id:'privacy:cancel:'+nonce}]}],allowedMentions:{parse:[]}};
  }
  async function handle(i){
    const command=i.isChatInputCommand?.() && ['privacy','privacy-delete'].includes(i.commandName);
    const button=i.isButton?.() && i.customId?.startsWith('privacy:');
    if(!command&&!button)return false;
    if(!i.user?.id)return false;
    if(command){await i.reply({...((i.commandName==='privacy')?privacyPayload():confirmation(i.user.id)),flags:MessageFlags.Ephemeral});return true;}
    if(i.customId==='privacy:delete'){await i.reply({...confirmation(i.user.id),flags:MessageFlags.Ephemeral});return true;}
    const parts=i.customId.split(':'),nonce=parts[2],pending=confirmations.get(nonce);
    if(!pending||pending.userId!==i.user.id||pending.expires<=now()){
      await i.reply({content:'This confirmation is expired or belongs to another account. Run /privacy-delete for a new private confirmation.',flags:MessageFlags.Ephemeral});return true;
    }
    if(parts[1]==='cancel'){confirmations.delete(nonce);await i.update({content:'Deletion cancelled. Your data was not changed.',components:[]});return true;}
    if(parts[1]!=='confirm')return false;
    // Acknowledge before disk work. Identity always comes from Discord's authenticated interaction.
    await i.deferUpdate();confirmations.delete(nonce);
    try{
      const result=store.eraseSubject(i.user.id); await onErase(i.user.id);
      await i.editReply({content:`Deletion completed. Bot files and operational backup copies were checked; ${result.updatedFiles} file(s) updated. Your Discord roles, bans, previous messages and Discord audit logs were not changed.`,components:[]});
    }catch{
      await i.editReply({content:'Deletion could not be fully verified. Please contact support and request MMOEXP_BOT data deletion. We have not marked this request complete.',components:[]});
    }
    return true;
  }
  return {handle,confirmation};
}
function install(client,{onErase=()=>{}}={}){
  const privacy=createPrivacy({onErase});
  storage.verify();storage.prune();
  console.log('[PRIVACY] ready release='+RELEASE+' cipher=AES-256-GCM');
  const timer=setInterval(()=>{try{storage.prune();}catch{console.error('[PRIVACY] retention failed');}},3600000);timer.unref();
  client.on(Events.InteractionCreate,i=>privacy.handle(i).catch(()=>console.error('[PRIVACY] interaction failed')));
  client.on(Events.MessageCreate,async msg=>{
    if(msg.guildId||!msg.author||msg.author.bot||!/^privacy\s*$/i.test(msg.content||''))return;
    await msg.reply(privacyPayload()).catch(()=>{});
  });
  return privacy;
}
module.exports={RELEASE,POLICY_URL,SUPPORT_URL,commands,privacyPayload,createPrivacy,install,installConsole};
