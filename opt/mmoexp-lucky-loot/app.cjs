'use strict';
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {Client,GatewayIntentBits,Partials,PermissionFlagsBits,ModalBuilder,TextInputBuilder,TextInputStyle,ActionRowBuilder,MessageFlags,MessageType}=require('discord.js');
const C=require('./core.cjs'),coupon=require('./coupon.cjs'),{Store}=require('./store.cjs');
const APP='1570345932699074611',TEST_CHANNEL='1570346273330954270';
const DATA=process.env.LOOT_DATA||'/var/lib/mmoexp-lucky-loot',KEY=process.env.LOOT_KEY||'/etc/mmoexp-lucky-loot/data.key',TOKEN=process.env.LOOT_TOKEN||'/etc/mmoexp-lucky-loot/token';
const SOCK=process.env.LOOT_SOCKET||'/run/mmoexp-lucky-loot/control.sock';
const MC=process.env.LOOT_MESSAGE_CONTENT==='1';
const store=new Store(path.join(DATA,'state.enc'),KEY);
const client=new Client({intents:[GatewayIntentBits.Guilds,GatewayIntentBits.GuildMessages,...(MC?[GatewayIntentBits.MessageContent]:[])],partials:[Partials.Channel],sweepers:{messages:{interval:60,lifetime:60}},allowedMentions:{parse:[]}});
let token='',busy=false,connecting=false,lastError='',lastTick=0,mutating=false,lastCleanup=0;
const privateFlags=MessageFlags.Ephemeral;
function memberInfo(m){return {id:m.id,bot:m.user.bot,pending:m.pending,admin:m.permissions.has(PermissionFlagsBits.Administrator),roles:[...m.roles.cache.keys()],created_at:m.user.createdTimestamp,joined_at:m.joinedTimestamp};}
async function member(uid){const g=await client.guilds.fetch(C.GUILD);return memberInfo(await g.members.fetch({user:uid,force:true}));}
function activity(cid){const c=store.data.campaigns[cid];C.need(c,'找不到活动');return c;}
function change(cid,fn){return store.update(s=>fn(s.campaigns[cid],s));}
const Cards=require('./cards.cjs'),{card,rules}=Cards;
async function dc(path,method='GET',body){const r=await fetch('https://discord.com/api/v10'+path,{method,headers:{Authorization:'Bot '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(25000),redirect:'error'});C.need(r.ok,'Discord HTTP '+r.status);return r.status===204?null:r.json();}
async function postOnce(cid,key,body){const c=activity(cid);if(c[key]?.state)return;
 const nonce=String(BigInt('0x'+crypto.createHash('sha256').update(cid+key).digest('hex').slice(0,16)));
 change(cid,x=>x[key]={state:'sending',nonce,at:Date.now()});
 try{const msg=await dc('/channels/'+c.channel_id+'/messages','POST',{...body,nonce,enforce_nonce:true});change(cid,x=>x[key]={state:'sent',id:msg.id,nonce,at:Date.now()});}
 catch(e){change(cid,x=>{x[key].state='unknown';x[key].error='发送结果待核对；不会重复发帖';});}
}
async function pinStart(cid){const c=activity(cid);if(!c.pin_message||!c.start_message?.id||c.pin_state)return;
 change(cid,x=>x.pin_state='sending');try{await dc('/channels/'+c.channel_id+'/messages/pins/'+c.start_message.id,'PUT');change(cid,x=>x.pin_state='pinned');}catch(e){change(cid,x=>{x.pin_state='unknown';x.error='活动已发布；置顶未确认，请核对频道权限后刷新卡片';});}}
async function refreshStart(cid){const c=activity(cid);if(!c.start_message?.id)return;const payload=card(c);payload.allowed_mentions={parse:[]};try{await dc('/channels/'+c.channel_id+'/messages/'+c.start_message.id,'PATCH',payload);}catch(e){change(cid,x=>x.card_error='活动卡片刷新失败，可在看板重试');}}
let announceBusy=false,nextAnnounceAt=0;
async function flushAnnouncements(){if(announceBusy||Date.now()<nextAnnounceAt||!client.isReady())return;announceBusy=true;
 try{for(const c of Object.values(store.data.campaigns)){for(const [uid,e] of Object.entries(c.entries)){if(e.announcement?.state!=='pending')continue;
  if(c.status!=='open'||Date.now()>=c.end_at){change(c.id,x=>{if(x.entries[uid])x.entries[uid].announcement.state='skipped';});continue;}
  const nonce=String(BigInt('0x'+crypto.createHash('sha256').update(c.id+':join:'+uid).digest('hex').slice(0,16)));
  change(c.id,x=>x.entries[uid].announcement={state:'sending',nonce,at:Date.now()});nextAnnounceAt=Date.now()+1100;
  try{const msg=await dc('/channels/'+c.announcement_channel_id+'/messages','POST',{...Cards.announcement(c,uid),nonce,enforce_nonce:true});change(c.id,x=>{if(x.entries[uid])x.entries[uid].announcement={state:'sent',id:msg.id,nonce,at:Date.now()};});}
  catch(e){change(c.id,x=>{if(x.entries[uid])x.entries[uid].announcement={state:'unknown',nonce,at:Date.now()};});}
  return;
 }} }finally{announceBusy=false;}}
async function joinCampaign(cid,m){let first=false;change(cid,c=>{C.need(Object.keys(c.entries).length<10000||c.entries[m.id],'本活动人数已达上限');first=!c.entries[m.id]?.joined;const e=C.join(c,m,Date.now());if(first&&c.announce_join)e.announcement={state:'pending',at:Date.now()};});await flushAnnouncements();return first;}
async function recoverMessage(cid,key){const c=activity(cid);if(!['unknown','sending'].includes(c[key]?.state))return;
 const list=await dc('/channels/'+c.channel_id+'/messages?limit=100');const hits=list.filter(m=>m.author.id===APP&&m.embeds?.some(e=>e.footer?.text==='Lucky Loot · '+cid+(key==='result_message'?' · Results':' · Seed '+c.commitment.slice(0,16))));
 if(hits.length===1)change(cid,x=>x[key]={...x[key],state:'sent',id:hits[0].id});}
async function preflight(c){C.need(client.isReady(),'机器人未连接 Discord');const guild=await client.guilds.fetch(C.GUILD);const me=await guild.members.fetchMe();
 for(const chId of new Set([c.channel_id,c.chat_channel_id,...(c.announce_join?[c.announcement_channel_id]:[])])){const ch=await guild.channels.fetch(chId);C.need(ch&&ch.isTextBased()&&[0,5].includes(ch.type),'仅支持本服务器的文字或公告频道');const p=ch.permissionsFor(me);C.need(p?.has([PermissionFlagsBits.ViewChannel,PermissionFlagsBits.ReadMessageHistory]),'机器人无法读取所选频道');if(chId===c.channel_id||c.announce_join&&chId===c.announcement_channel_id)C.need(p.has([PermissionFlagsBits.SendMessages,PermissionFlagsBits.EmbedLinks]),'机器人无法在所选频道发布活动');
  if(c.pin_message&&chId===c.channel_id)C.need(p.has(1n<<51n),'机器人尚无此频道的置顶消息权限');
  if(c.test_only){C.need(chId===TEST_CHANNEL,'测试活动只能使用管理员测试频道');const deny=ch.permissionOverwrites.cache.get(C.GUILD);C.need(deny?.deny.has(PermissionFlagsBits.ViewChannel),'测试频道必须保持私密');}}
 for(const roleId of [...c.eligible_roles,...c.excluded_roles,...c.mention_roles])C.need(guild.roles.cache.has(roleId),'所选身份组已不存在');
 for(const rid of c.mention_roles){const role=guild.roles.cache.get(rid);C.need(role.mentionable||me.permissions.has(PermissionFlagsBits.MentionEveryone),'要提醒的身份组不可被机器人提及，请改选可提及身份组');}
 C.need(c.mode!=='keyword'||c.keyword_requires_mention||MC,'未开启消息正文权限：口令参与请加 @机器人');
 for(const p of c.prizes)if(p.type==='coupon')p.coupon_snapshot=coupon.validate(await coupon.detail(p.coupon_id));
}
async function tick(){if(busy||!client.isReady())return;busy=true;lastTick=Date.now();try{
 for(const cid of Object.keys(store.data.campaigns)){let c=activity(cid),now=Date.now();
  if(c.status==='scheduled'&&now>=c.start_at){if(now>=c.end_at){change(cid,x=>{x.status='expired';x.error='机器人离线期间活动已过期，未发布';});continue;}
   try{await preflight(c);if(activity(cid).status!=='scheduled')continue;change(cid,x=>{x.status='open';});await postOnce(cid,'start_message',card(activity(cid)));await pinStart(cid);}catch(e){change(cid,x=>{if(x.status==='scheduled'){x.status='attention';x.error=e.message;}});}c=activity(cid);}
  if(c.status==='open'&&now>=c.end_at)change(cid,x=>x.status='closed');
  c=activity(cid);
  if(['open','closed'].includes(c.status)&&now>=c.draw_at){try{const valid=new Set();for(const uid of Object.keys(c.entries)){if(!C.qualified(c,c.entries[uid]))continue;try{const m=await member(uid);if(C.eligible(c,m,now))valid.add(uid);}catch(e){if(e.code===10007)continue;throw Error('成员资格复核失败，开奖暂缓');}}
    change(cid,x=>C.draw(x,valid,Date.now()));await postOnce(cid,'result_message',card(activity(cid),true));await refreshStart(cid);
   }catch(e){change(cid,x=>x.error=e.message);} }
  c=activity(cid);if(c.status==='drawn'&&!c.result_message)await postOnce(cid,'result_message',card(c,true));
  for(const w of c.winners||[]){if(w.state==='pending'&&w.job_id){try{await reconcileWinner(cid,w.claim_id);}catch(e){/* retained for explicit review; no re-dispatch */}}}
 }
 if(Date.now()-lastCleanup>3600000){cleanup();lastCleanup=Date.now();}
}finally{busy=false;}}
function cleanup(){const now=Date.now();store.update(s=>{for(const [cid,c] of Object.entries(s.campaigns)){const expires=(c.claim_deadline||c.draw_at||c.created_at)+30*86400000;if(now>expires&&['drawn','cancelled','expired','draft','attention'].includes(c.status))delete s.campaigns[cid];}s.audit=s.audit.filter(x=>now-x.at<7*86400000);});}
async function reconcileWinner(cid,wid){const w=activity(cid).winners.find(w=>w.claim_id===wid);C.need(w,'中奖记录不存在');if(!['pending','unknown'].includes(w.state))return;const r=await coupon.reconcile(w);change(cid,c=>Object.assign(c.winners.find(x=>x.claim_id===wid),r,{updated_at:Date.now()}));}
const inFlightClaims=new Set();
async function claim(cid,uid,address){const c=activity(cid);C.need(c.status==='drawn'&&Date.now()<=c.claim_deadline,'领奖尚未开放或已过期');const w=c.winners.find(x=>x.user_id===uid);C.need(w,'你不是本次中奖者');
 if(w.state!=='unclaimed')return w.reason||'该奖励已有领取记录，请查看状态';
 C.need(!inFlightClaims.has(w.claim_id),'领奖处理中');inFlightClaims.add(w.claim_id);
 try{const addr=C.email(address),p=c.prizes[w.prize_index];C.need(await member(uid),'请先加入活动服务器');
  C.need(!c.winners.some(x=>x.claim_id!==w.claim_id&&x.email===addr),'此邮箱已用于本次活动的其他奖励');
  if(p.type==='coupon'){const row=coupon.validate(await coupon.detail(p.coupon_id));C.need(JSON.stringify(row)===JSON.stringify(p.coupon_snapshot),'券模板已有变化，需管理员核对后处理');}
  const batch='LL_'+cid.replace(/-/g,'')+'_'+w.claim_id.slice(0,8);
  // Persist admission before any external write; no unknown outcome is ever reissued.
  change(cid,x=>{const record=x.winners.find(r=>r.claim_id===w.claim_id);C.need(record?.state==='unclaimed','已有领取记录');record.email=addr;record.batch=batch;record.state=p.type==='manual'?'manual_pending':'dispatching';record.updated_at=Date.now();record.reason=p.type==='manual'?'已登记，等待管理员发放':'后台正在发放';});
  if(p.type==='manual')return 'Email recorded privately. A moderator will arrange your reward.';
  let result;try{result=await coupon.grant(p.coupon_id,addr,batch);}catch(e){result={state:'unknown',reason:'后台结果待核对，请勿重复领取'};}
  change(cid,x=>{const record=x.winners.find(r=>r.claim_id===w.claim_id);if(record)Object.assign(record,result,{updated_at:Date.now()});});
  return result.state==='confirmed'?'Your coupon has been issued to your MMOEXP account. Check your coupons after signing in.':result.state==='pending_register'?'Your email is queued by MMOEXP. Register with this email to receive your coupon.':result.state==='pending'?'Your reward is being processed. Use My status to check.':'Your claim is recorded and requires moderator review. It will not be sent twice.';
 }finally{inFlightClaims.delete(w.claim_id);}}
const deleteTokens=new Map();
const privacy='MMOEXP Lucky Loot ('+APP+') stores activity entry counts, Discord IDs, winner results and privately submitted reward emails. Chat text is not stored. Data is encrypted; activity records expire within 30 days after the claim deadline (up to 90 days from activity start). Email goes only to MMOEXP coupon delivery. /privacy-delete removes this bot’s local records and withdraws your entries; already-issued coupons and Discord messages remain. Contact a server administrator for MMOEXP account data.';
async function respond(i,content){const payload={content,flags:privateFlags,allowedMentions:{parse:[]}};if(i.deferred||i.replied)return i.followUp(payload);return i.reply(payload);}
client.on('interactionCreate',async i=>{try{
 if(i.guildId!==C.GUILD)return;
 const command=i.isChatInputCommand()?i.commandName:null;
 if(command==='privacy'||i.customId?.startsWith('ll:privacy:'))return respond(i,privacy);
 if(command==='privacy-delete'){const k=crypto.randomBytes(18).toString('hex');deleteTokens.set(k,{uid:i.user.id,expires:Date.now()+600000});return i.reply({content:'Delete this bot’s records and withdraw your entries? Delivered coupons and Discord messages remain. Any in-progress delivery must finish first.',flags:privateFlags,components:[{type:1,components:[{type:2,style:4,label:'Delete my data',custom_id:'ll:delete:'+k}]}]});}
 const [prefix,action,cid]=String(i.customId||'').split(':');if(prefix!=='ll')return;
 if(action==='delete'){const d=deleteTokens.get(cid);C.need(d&&d.uid===i.user.id&&d.expires>Date.now(),'Confirmation expired; run /privacy-delete again.');deleteTokens.delete(cid);
  C.need(!Object.values(store.data.campaigns).some(c=>(c.winners||[]).some(w=>w.user_id===i.user.id&&(inFlightClaims.has(w.claim_id)||['dispatching','pending','unknown','pending_register'].includes(w.state)))),'A delivery needs reconciliation before all related records can be removed. Please contact a moderator.');
  store.update(s=>{for(const c of Object.values(s.campaigns)){delete c.entries[i.user.id];c.winners=(c.winners||[]).filter(w=>w.user_id!==i.user.id);}});
  const disk=store.read();C.need(!Object.values(disk.campaigns).some(c=>c.entries[i.user.id]||(c.winners||[]).some(w=>w.user_id===i.user.id)),'Deletion verification failed. Contact a moderator.');return respond(i,'Your local records for MMOEXP Lucky Loot have been deleted. Discord posts and MMOEXP account/coupon records remain.');}
 const c=activity(cid);C.need(c.guild_id===i.guildId,'Wrong server');
 if(action==='rules')return i.reply({...Cards.details(c),flags:privateFlags});
 if(action==='join'){await i.deferReply({flags:privateFlags});const m=memberInfo(await i.guild.members.fetch({user:i.user.id,force:true}));const first=await joinCampaign(cid,m);return i.editReply({content:!first?'✅ You’re already signed up!':c.mode==='button'?'✅ You’re in! Good luck! 🍀':`✅ Signed up!\n${Cards.entryHint(c)}`,allowedMentions:{parse:[]}});}
 if(action==='progress')return respond(i,Cards.progress(c,i.user.id));
 if(action==='claim'){C.need(c.status==='drawn'&&c.winners.some(w=>w.user_id===i.user.id),'Only winners may claim.');const w=c.winners.find(w=>w.user_id===i.user.id);if(w.state!=='unclaimed')return respond(i,w.reason||w.state);
  const input=new TextInputBuilder().setCustomId('email').setLabel('Your MMOEXP account email (private)').setStyle(TextInputStyle.Short).setRequired(true).setMaxLength(254);
  return i.showModal(new ModalBuilder().setCustomId('ll:email:'+cid).setTitle('Claim your reward').addComponents(new ActionRowBuilder().addComponents(input)));}
 if(action==='email'&&i.isModalSubmit()){await i.deferReply({flags:privateFlags});const result=await claim(cid,i.user.id,i.fields.getTextInputValue('email'));return i.editReply({content:result,allowedMentions:{parse:[]}});}
 }catch(e){try{if(i.deferred)await i.editReply({content:String(e.message).slice(0,500)});else await respond(i,String(e.message).slice(0,500));}catch(_){lastError='Interaction response failed';}}});
client.on('messageCreate',m=>{if(m.guildId!==C.GUILD||m.author.bot||m.webhookId||![MessageType.Default,MessageType.Reply].includes(m.type)||!m.member)return;
 try{const info=memberInfo(m.member),event={id:m.id,at:m.createdTimestamp,channel_id:m.channelId,content:m.content,mentioned:m.mentions.users.has(APP)};const candidates=Object.values(store.data.campaigns).filter(c=>c.status==='open'&&c.chat_channel_id===m.channelId&&c.mode!=='button');if(!candidates.length)return;
  store.update(s=>{for(const c of Object.values(s.campaigns)){if(Object.keys(c.entries).length>=10000&&!c.entries[info.id])continue;C.message(c,info,event,Date.now());}});
 }catch(e){lastError='Chat progress could not be saved';}});
client.on('error',()=>{lastError='Discord connection error';});
client.once('ready',async()=>{lastError='';try{await client.application.commands.set([{name:'privacy',description:'Data use and privacy for MMOEXP Lucky Loot'},{name:'privacy-delete',description:'Privately delete your Lucky Loot records'}],C.GUILD);}catch(e){lastError='Privacy command registration failed';}await tick();});
async function connect(value){C.need(!connecting,'正在连接');connecting=true;try{token=value.trim();C.need(/^[A-Za-z0-9_.-]{40,200}$/.test(token),'令牌格式不正确');const who=await dc('/users/@me');C.need(who.id===APP&&who.bot,'令牌不属于本次新机器人');fs.writeFileSync(TOKEN,token,{mode:0o600});await client.login(token);return {hasToken:true};}finally{connecting=false;}}
function status(){return {ok:true,application_id:APP,guild_id:C.GUILD,test_channel_id:TEST_CHANNEL,connected:client.isReady(),hasToken:fs.existsSync(TOKEN),message_content:MC,last_error:lastError,last_tick:lastTick,version:'1.1.0',policy:privacy,campaigns:Object.values(store.data.campaigns).map(C.publicCampaign).sort((a,b)=>b.created_at-a.created_at)};}
async function api(method,url,b){const u=new URL(url,'http://local');const route=u.pathname;
 if(method==='GET'&&route==='/status')return status();
 if(method==='GET'&&route==='/coupon'){const n=Number(u.searchParams.get('id'));C.need(Number.isInteger(n)&&n>0,'券编号无效');return {coupon:coupon.validate(await coupon.detail(n))};}
 if(method==='GET'&&route==='/meta'){C.need(client.isReady(),'机器人尚未连接');const g=await client.guilds.fetch(C.GUILD),channels=await g.channels.fetch();await g.roles.fetch();return {channels:[...channels.values()].filter(x=>x&&[0,5].includes(x.type)).map(x=>({id:x.id,name:x.name})),roles:[...g.roles.cache.values()].filter(r=>r.id!==C.GUILD&&!r.managed).map(r=>({id:r.id,name:r.name})),guild:g.name};}
 if(method==='POST'&&route==='/connect')return connect(b.token);
 if(method==='POST'&&route==='/save'){const cfg=C.normalize(b);const old=b.id?activity(b.id):null;C.need(!old||old.status==='draft','已发布活动规则不能修改，请复制新建');const now=Date.now(),cid=old?.id||crypto.randomUUID();
  C.need(!cfg.test_only||(cfg.channel_id===TEST_CHANNEL&&cfg.chat_channel_id===TEST_CHANNEL&&(!cfg.announce_join||cfg.announcement_channel_id===TEST_CHANNEL)),'测试活动必须留在私密测试频道');
  const c={...cfg,id:cid,status:'draft',created_at:old?.created_at||now,updated_at:now,entries:{},winners:[]};store.update(s=>s.campaigns[cid]=c);return {campaign:C.publicCampaign(c)};}
 if(method==='POST'&&route==='/schedule'){const c=structuredClone(activity(b.id));C.need(c.status==='draft','活动已提交');C.need(c.end_at>Date.now()+10000,'活动截止时间太近或已过期');await preflight(c);c.seed=crypto.randomBytes(32).toString('hex');c.commitment=C.commitment(c.seed);c.status='scheduled';c.approved_at=Date.now();
  store.update(s=>{C.need(s.campaigns[c.id].status==='draft','活动状态已变化');s.campaigns[c.id]=c;});await tick();return {campaign:C.publicCampaign(activity(c.id))};}
 if(method==='POST'&&route==='/cancel'){change(b.id,c=>{C.need(['draft','scheduled','open','closed','attention'].includes(c.status),'已经开奖，不能取消');c.status='cancelled';c.cancelled_at=Date.now();});const c=activity(b.id);if(c.start_message?.id)await dc('/channels/'+c.channel_id+'/messages/'+c.start_message.id,'PATCH',{content:'This giveaway has been cancelled by the organizer.',components:[],embeds:[],allowed_mentions:{parse:[]}});return {ok:true};}
 if(method==='POST'&&route==='/reconcile'){const c=activity(b.id);if(b.claim_id)await reconcileWinner(c.id,b.claim_id);else{await recoverMessage(c.id,'start_message');await recoverMessage(c.id,'result_message');}return {campaign:C.publicCampaign(activity(c.id))};}
 if(method==='POST'&&route==='/refresh-card'){const c=activity(b.id);C.need(c.start_message?.id,'活动尚未发布');await refreshStart(c.id);if(c.result_message?.id){const payload=card(c,true);payload.allowed_mentions={parse:[]};await dc('/channels/'+c.channel_id+'/messages/'+c.result_message.id,'PATCH',payload);}if(c.pin_message){const msg=await dc('/channels/'+c.channel_id+'/messages/'+c.start_message.id);change(c.id,x=>x.pin_state=msg.pinned?'pinned':null);await pinStart(c.id);}return {campaign:C.publicCampaign(activity(c.id))};}
 if(method==='POST'&&route==='/recipient'){const c=activity(b.id),w=c.winners.find(x=>x.claim_id===b.claim_id);C.need(w&&c.prizes[w.prize_index].type==='manual'&&w.email&&['manual_pending','manual_delivered'].includes(w.state),'不是已登记的人工奖励');return {email:w.email};}
 if(method==='POST'&&route==='/manual'){change(b.id,c=>{const w=c.winners.find(w=>w.claim_id===b.claim_id);C.need(w&&c.prizes[w.prize_index].type==='manual'&&w.state==='manual_pending','不是待处理的人工奖励');w.state='manual_delivered';w.reason='管理员已确认发放';w.updated_at=Date.now();});return {ok:true};}
 if(method==='POST'&&route==='/preview'){const c=C.normalize(b);c.id='PREVIEW';c.commitment='preview';c.winners=[{user_id:'preview',prize_index:0}];c.claim_deadline=c.draw_at+c.claim_hours*3600000;return {preview:card(c),result_preview:card(c,true),announcement:c.announce_join?Cards.announcement(c,'preview').content:null};}
 throw Error('未知操作');}
const server=http.createServer(async(req,res)=>{let raw='',ownsMutation=false;try{for await(const part of req){raw+=part.toString('utf8');C.need(raw.length<=100000,'请求过大');}const b=raw?JSON.parse(raw):{};
  C.need(!mutating||req.method==='GET','已有操作处理中，请稍后');if(req.method==='POST'){mutating=true;ownsMutation=true;}
  const result=await api(req.method,req.url,b);res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(result));
 }catch(e){res.writeHead(400,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify({ok:false,error:String(e.message).slice(0,500)}));}
 finally{if(ownsMutation)mutating=false;}});
function recoverState(){store.update(s=>{for(const c of Object.values(s.campaigns)){for(const e of Object.values(c.entries))if(e.announcement?.state==='sending')e.announcement.state='unknown';for(const w of c.winners||[])if(w.state==='dispatching'){w.state='unknown';w.reason='服务重启前发券结果未确认，请核对原批次';}}});}
if(require.main===module){
 const lock=path.join(DATA,'instance.lock');
 if(fs.existsSync(lock)){const pid=Number(fs.readFileSync(lock,'utf8'));let alive=true;try{process.kill(pid,0);}catch(e){if(e.code==='ESRCH')alive=false;}C.need(!alive,'Another instance is active');fs.unlinkSync(lock);}
 fs.writeFileSync(lock,String(process.pid),{flag:'wx',mode:0o600});
 fs.mkdirSync(path.dirname(SOCK),{recursive:true,mode:0o700});if(fs.existsSync(SOCK))fs.unlinkSync(SOCK);server.listen(SOCK,()=>fs.chmodSync(SOCK,0o600));
 recoverState();
 if(fs.existsSync(TOKEN))connect(fs.readFileSync(TOKEN,'utf8')).catch(()=>{lastError='Discord token could not connect; check installation and token';});
 setInterval(()=>flushAnnouncements().catch(()=>{lastError='Join announcement queue failed';}),1100).unref();
 setInterval(()=>tick().catch(()=>{lastError='Scheduler failed; check campaign status';}),10000).unref();
 setInterval(()=>{const now=Date.now();for(const [k,v] of deleteTokens)if(v.expires<now)deleteTokens.delete(k);},60000).unref();
 process.on('SIGTERM',()=>{client.destroy();server.close(()=>{if(fs.existsSync(lock))fs.unlinkSync(lock);process.exit(0);});});
}
module.exports={api,tick,claim,store,client,card,recoverState,cleanup,joinCampaign,flushAnnouncements};
