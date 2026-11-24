/* ================================================================
   CARNIVAL CONFIG —— 运营可配置区
   时间、游戏、商品、库存、场次、价格、折扣码全部在这里改
   每个商品/奖项支持 name (英文) 和 nameZh (中文)，缺省中文时显示英文
================================================================ */
const CONFIG = {
  tzLabel: 'ET (UTC-5)',
  events: {
    tg: { start: '2026-11-19T00:00:00-05:00', end: '2026-12-02T00:00:00-05:00' },
    bf: { start: '2026-11-27T00:00:00-05:00', end: '2026-12-02T00:00:00-05:00' },
    cm: { start: '2026-11-30T00:00:00-05:00', end: '2026-12-02T00:00:00-05:00' }
  },

  /* ---- Act 1: Mystery Shop 神秘商店 ----
     玩法：每个游戏一个商品池 → 用户任选 3 件 → 抽一次折扣
     首轮每张独立按 30% / 30% / 40% 抽取，后续按 20% / 30% / 50% 抽取（2026-11-24 调整）
     三件商品均可下单购买 */
  mystery: {
    pickCount: 3,                 // 预选商品数量
    discountSet: [15, 10, 8],     // 抽取的折扣组合（各一档，随机分配给 3 件）
    maxDraws: 1,                  // 每轮抽取次数
    // Next draw unlocks only after payment; no timer.
    mascotImg: 'assets/carnival-8a2a27b79ed6.webp',                // 平台吉祥物正式图片地址，填入后自动替换 SVG 占位形象
    games: [
      { id:'fc27', name:'FC 27', nameZh:'FC 27', icon:'⚽', items:[{"name":"100K FC 27 Coins","nameZh":"100K FC 27 金币","icon":"🪙","image":"fc27-generated-coin","price":null,"modelId":"41217957","productIds":{"ps":"163329311","xbox":"163329277","pc":"163329345"},"snapshots":{"ps":8.04,"xbox":7.9799999999999995,"pc":7.37}},{"name":"500K FC 27 Coins","nameZh":"500K FC 27 金币","icon":"🪙","image":"fc27-generated-coin","price":null,"modelId":"41217957","productIds":{"ps":"163329311","xbox":"163329277","pc":"163329345"},"snapshots":{"ps":40.2,"xbox":39.9,"pc":36.85}},{"name":"1000K FC 27 Coins","nameZh":"1000K FC 27 金币","icon":"🪙","image":"fc27-generated-coin","price":null,"modelId":"41217957","productIds":{"ps":"163329311","xbox":"163329277","pc":"163329345"},"snapshots":{"ps":80.4,"xbox":79.8,"pc":73.7}},{"name":"1500K FC 27 Coins","nameZh":"1500K FC 27 金币","icon":"🪙","image":"fc27-generated-coin","price":null,"modelId":"41217957","productIds":{"ps":"163329311","xbox":"163329277","pc":"163329345"},"snapshots":{"ps":93.45,"xbox":92.86,"pc":111.73}},{"name":"2000K FC 27 Coins","nameZh":"2000K FC 27 金币","icon":"🪙","image":"fc27-generated-coin","price":null,"modelId":"41217957","productIds":{"ps":"163329311","xbox":"163329277","pc":"163329345"},"snapshots":{"ps":160.8,"xbox":159.6,"pc":147.4}},{"name":"Caroline Graham Hansen","nameZh":"格雷厄姆·汉森","variant":"90 / RW++ / Thunderstruck","icon":"⚽","image":"https://assets.mmoexp.com/images/202611/51324f7a704a0fbc090bb9e95498d4911bdf5683.png","price":null,"modelId":"45657789","productIds":{"ps":"187669759","xbox":"187669763","pc":"187669767"},"snapshots":{"ps":81.68,"xbox":78.85,"pc":68.43}},{"name":"Bruno Miguel Borges Fernandes","nameZh":"B费","variant":"90 / CAM++ / Thunderstruck","icon":"⚽","image":"https://assets.mmoexp.com/images/202611/8acb9a602e919e0b7202a34b23e2d4b37f1bfff1.png","price":null,"modelId":"45657787","productIds":{"ps":"187669747","xbox":"187669751","pc":"187669755"},"snapshots":{"ps":49.84,"xbox":48.11,"pc":38.58}},{"name":"Lamine Yamal Nasraoui Ebana","nameZh":"亚马尔","variant":"92 / RW++ / Thunderstruck","icon":"⚽","image":"https://assets.mmoexp.com/images/202611/9f9fa22e1dbd0331219f8866c324d17977ee55af.png","price":null,"modelId":"45657781","productIds":{"ps":"187669711","xbox":"187669715","pc":"187669719"},"snapshots":{"ps":287.94,"xbox":277.99,"pc":330.66}},{"name":"Micky van de Ven","nameZh":"范德文","variant":"87 / CB++ / Thunderstruck","icon":"⚽","image":"https://assets.mmoexp.com/images/202611/3cfe10fe1188922b3d903090d01a7804c1bb97b8.png","price":null,"modelId":"45657809","productIds":{"ps":"187669879","xbox":"187669883","pc":"187669887"},"snapshots":{"ps":33.59,"xbox":32.43,"pc":27.1}}] },
      { id:'poe2', name:'PoE 2', nameZh:'流放之路 2', icon:'🔮', items:[{"name":"Mirror of Kalandra","nameZh":"Mirror of Kalandra","icon":"🔮","price":null,"poePrice":35.08,"poeGoodsId":"117074411","storeUrl":"https://www.mmoexp.com/Poe-2/Currency/Mirror-of-kalandra.html","image":"assets/carnival-f0b27a83fa55.webp"},{"name":"Divine Orb（1000+500Free）","nameZh":"Divine Orb（1000+500Free）","icon":"🔮","price":null,"poePrice":8.9,"poeGoodsId":"186208657","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-01455dbaacbe.webp"},{"name":"Mirror of Kalandra(Free Divine Orb *500 !)","nameZh":"Mirror of Kalandra(Free Divine Orb *500 !)","icon":"🔮","price":null,"poePrice":35.08,"poeGoodsId":"186208735","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-fb4c0908f773.webp"},{"name":"Divine Orb(500+25 Free)","nameZh":"Divine Orb(500+25 Free)","icon":"🔮","price":null,"poePrice":3.34,"poeGoodsId":"169682813","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-0988f3c73de4.webp"},{"name":"Divine Orb(200+10 Free)","nameZh":"Divine Orb(200+10 Free)","icon":"🔮","price":null,"poePrice":1.35,"poeGoodsId":"169644111","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-0c2f69b09bcb.webp"},{"name":"Mirror of Kalandra(1+1 Free)","nameZh":"Mirror of Kalandra(1+1 Free)","icon":"🔮","price":null,"poePrice":68.8,"poeGoodsId":"187497011","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-5a8a89573277.webp"},{"name":"Bundle - A","nameZh":"Bundle - A","icon":"🔮","price":null,"poePrice":0.25,"poeGoodsId":"169547725","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-b860e39ab804.webp"},{"name":"Bundle - B","nameZh":"Bundle - B","icon":"🔮","price":null,"poePrice":0.27,"poeGoodsId":"169547649","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-94efc9eff60c.webp"},{"name":"Bundle - C","nameZh":"Bundle - C","icon":"🔮","price":null,"poePrice":0.11,"poeGoodsId":"169547573","storeUrl":"https://www.mmoexp.com/Poe-2/Currency.html","image":"assets/carnival-2a0262c2ad9e.webp"}] },
      { id:'d4', name:'Diablo 4', nameZh:'暗黑破坏神4', icon:'🔥', items:[{"name":"Resplendent Spark x100 (Manual salvage required)","nameZh":"Resplendent Spark x100 (Manual salvage required)","icon":"💎","price":5.9,"fixedRealm":"Season 15 Softcore","goodsId":"170070065","fromPrice":false,"image":"assets/carnival-2ca444fddc2a.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Cuddly Conduit (Account credentials and some time required)","nameZh":"Cuddly Conduit (Account credentials and some time required)","icon":"💎","price":49.99,"fixedRealm":"Season 15 Softcore","goodsId":"186050303","fromPrice":true,"image":"assets/carnival-cf17dd5d9232.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Powerleveling/m44986151.html"},{"name":"(500) Crux of the False Prophet","nameZh":"(500) Crux of the False Prophet","icon":"💎","price":3.75,"fixedRealm":"Season 15 Softcore","goodsId":"187495953","fromPrice":false,"image":"assets/carnival-0aee3cdcc5b7.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Flawless Horadric Skull x5 (Lv.30)","nameZh":"Flawless Horadric Skull x5 (Lv.30)","icon":"💎","price":4.99,"fixedRealm":"Season 15 Softcore","goodsId":"187496117","fromPrice":false,"image":"assets/carnival-27a850cf9aa1.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Stone of Jordan – Common Base Gear x15 (Random 1GA,For Transmutation)","nameZh":"Stone of Jordan – Common Base Gear x15 (Random 1GA,For Transmutation)","icon":"💎","price":21.99,"fixedRealm":"Season 15 Softcore","goodsId":"187496035","fromPrice":false,"image":"assets/carnival-dd887b8fb31c.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Flawless Horadric Emerald x5 (Lv.30)","nameZh":"Flawless Horadric Emerald x5 (Lv.30)","icon":"💎","price":4.99,"fixedRealm":"Season 15 Softcore","goodsId":"187495871","fromPrice":false,"image":"assets/carnival-cafb9018f88f.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Flawless Horadric Sapphire x5 (Lv.30)","nameZh":"Flawless Horadric Sapphire x5 (Lv.30)","icon":"💎","price":4.99,"fixedRealm":"Season 15 Softcore","goodsId":"187495789","fromPrice":false,"image":"assets/carnival-4de983e30901.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Flawless Horadric Ruby x5 (Lv.30)","nameZh":"Flawless Horadric Ruby x5 (Lv.30)","icon":"💎","price":12.49,"fixedRealm":"Season 15 Softcore","goodsId":"187495707","fromPrice":false,"image":"assets/carnival-40d9a7055443.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"},{"name":"Ancestral Mythic Unique “Infinity”“Rain\" Runeword Set (Base Gear Required)","nameZh":"Ancestral Mythic Unique “Infinity”“Rain\" Runeword Set (Base Gear Required)","icon":"💎","price":5.99,"fixedRealm":"Season 15 Softcore","goodsId":"187495379","fromPrice":false,"image":"assets/carnival-5c41029202a7.webp","storeUrl":"https://www.mmoexp.com/Diablo-4/Items.html"}] },
      { id:'maple', name:'MapleStory', nameZh:'冒险岛', icon:'🍁', items:[] },
      { id:'aion2', name:'Aion 2', nameZh:'永恒之塔 2', icon:'⚔️', items:[] }
    ]
  },

  /* ---- Act 2: Flash Sale 秒杀 ---- */
  /* 商品分两类：普通商品(无 type 字段) + 券类商品(type:'coupon')。
     券类商品本身就是"可抢的优惠券/折扣券"，有独立库存，抢到即得，售罄即止。 */
  flash: { sessions: [] },

  /* ---- Act 3: Gacha 扭蛋机（每人独立 · 固定档位 · 抽奖免费） ---- */
  gacha: {
    thresholds: [1, 100, 300, 500, 800, 1000], // 六次抽奖所需的累计订单金额（固定）
    prizes: [                         // 无门槛优惠券，按固定顺序依次获得（6 个奖励均由消费门槛解锁）
      { name:'$1 Coupon (No Min.)',   nameZh:'$1 无门槛优惠券',   icon:'🎟️', rarity:'rare',   qty:1, left:1 },
      { name:'$5 Coupon (No Min.)',   nameZh:'$5 无门槛优惠券',   icon:'🎟️', rarity:'rare',   qty:1, left:1 },
      { name:'$12 Coupon (No Min.)',  nameZh:'$12 无门槛优惠券',  icon:'🎟️', rarity:'epic',   qty:1, left:1 },
      { name:'$18 Coupon (No Min.)',  nameZh:'$18 无门槛优惠券',  icon:'🎟️', rarity:'epic',   qty:1, left:1 },
      { name:'$25 Coupon (No Min.)', nameZh:'$25 无门槛优惠券', icon:'🎟️', rarity:'legend', qty:1, left:1 },
      { name:'$50 Coupon (No Min.)', nameZh:'$50 无门槛优惠券', icon:'🎟️', rarity:'legend', qty:1, left:1 }
    ]
  },

  /* ---- Act 3 搭配: 游戏专属折扣码（玩家自行领取） ---- */
  gameCodes: [
    {game:'College Football 27',code:'VZKZT',discount:10,theme:'cfb',url:'https://www.mmoexp.com/College-football-27/Coins.html'},
    {game:'Madden NFL 27',code:'TFLNV9',discount:10,theme:'madden',url:'https://www.mmoexp.com/Nfl-27/Coins.html'},
    {game:'MLB The Show 26',code:'KSPX1',discount:10,theme:'mlb',url:'https://www.mmoexp.com/Mlb-the-show-26.html'},
    {game:'Arena Breakout: Infinite',code:'RYQ3F',discount:10,theme:'arena',url:'https://www.mmoexp.com/Arena-breakout-infinite/Koens.html'},
    {game:'MONOPOLY GO!',code:'YHCAKJ',discount:10,theme:'monopoly',url:'https://www.mmoexp.com/Monopoly-go/Stickers.html'}

  ]
};
/* ================================================================
   I18N 双语文案
================================================================ */

/* Flash sessions: schedule only. Products arrive from the FS runtime once a session starts. */
CONFIG.flash.sessions = ['2026-11-27','2026-11-28','2026-11-29','2026-11-30','2026-12-01'].flatMap((date,i)=>[['12:00','16:00'],['19:00','23:00']].map(([start,end],j)=>({
 name:'Session '+(i*2+j+1),nameZh:'第 '+(i*2+j+1)+' 场',time:(i<4?'Nov '+(27+i):'Dec 1')+' · '+start+'–'+end+' ET',timeZh:(i<4?'11月'+(27+i)+'日':'12月1日')+' · '+start+'–'+end+' ET',
 start:date+'T'+start+':00-05:00',end:date+'T'+end+':00-05:00',items:[]
})));

const T = {
en:{
  heroTitle:'CARNIVAL FESTIVAL', heroBenefitCoupon:'Sign in and claim your <strong class="coupon-highlight">10% OFF</strong> coupon!', heroBenefitGacha:'Spend to unlock draws for no-minimum coupons.', agendaEnter:'ENTER EVENT →', railTitle:'EVENTS', rail1:'Thanksgiving', rail2:'Black Friday', rail3:'Cyber Monday', rail4:'Rules', storeTitle:'BLACK FRIDAY STORE', storeDemo:'Sample products and prices', storeSlogan:'DAILY DEALS · EXCLUSIVE SAVINGS', storeCurrency:'Currency', storeItems:'Items', storeVoucher:'Coupons', flashSlideHint:'Swipe to explore', couponEyebrow:'A GIFT FROM EXPIE', agendaTitle:'YOUR HOLIDAY EVENT GUIDE', agendaDate1:'NOV 19 — DEC 2 00:00', agendaDate2:'NOV 27 — DEC 2 00:00', agendaDate3:'NOV 30 — DEC 2 00:00', agendaName1:'THANKSGIVING · MYSTERY SHOP', agendaName2:'BLACK FRIDAY · FLASH SALE', agendaName3:'CYBER MONDAY · GACHA MACHINE', agendaBenefit1:'Choose 3 items · Reveal up to <strong class="benefit-highlight">15% OFF</strong>', agendaBenefit2:'Coins & items on sale · Free coupons', agendaBenefit3:'Spend $1 to unlock your first draw', agendaGachaSpeech:'Spending counts from Nov 19. Please sign in so your orders can be tracked!', gachaSpendReminder:'Spending counts from Nov 19. Please sign in, or your orders may not be counted.', agendaRule1:'Pick 3 items and reveal 15%, 10% and 8% discounts.', agendaRule2:'Daily offers on currency, items and vouchers.', agendaRule3:'Claim a free draw and unlock more with qualifying orders.', agendaRules:'View full rules →',
  logoTag:'CARNIVAL FESTIVAL', nav1:'Mystery Shop', nav2:'Flash Sale', nav3:'Gacha Machine', nav4:'Rules', backStore:'Back to Store',
  heroTag:'Nov 19 — Dec 2 · Thanksgiving × Black Friday × Cyber Monday',
  heroT2:'HOLIDAY', heroT3:'DEALS',
  heroSub:'Seven days, three events, one gateway. Pick 3 items and draw mystery discounts at the Kickoff, grab lightning deals during the Surge, and crack the gacha machine at the Closing — every order fuels your Cyber Monday draws.',
  heroClaimBtn:'🎟️ GET 10% OFF ANY ORDER',
  heroClaimNote:'Tap to claim a 10% OFF coupon for any single order, and unlock the flash sale early.',
  heroClaimDone:'🎟️ COUPON CLAIMED ✓',
  earlyLive:'Early Access',
  earlyToast:c=>`Coupon ${c} claimed & copied — 10% OFF any order.`,
  cpLabel:'HOLIDAY COUPON',
  cpOff:'10% OFF',
  cpNote:'All games · no minimum · cannot combine with other coupons or codes.', couponMin:'Min. spend: $0.00',
  cpCodeLbl:'CODE',
  cpBtn:'CLAIM COUPON',
  cpLater:'Maybe later', loginRequiredTitle:'Sign in to claim', loginRequiredText:'Please sign in or register with MMOEXP to claim your coupon.', loginGo:'SIGN IN / REGISTER', couponTicketFoot:'ALL GAMES · NO MINIMUM', loginPending:'Please sign in to continue.', loginLater:'Not now', couponPending:'Coupon service is not connected yet.',

  flashSchedule:'NOV 27–DEC 1 · Daily 12:00–16:00 &amp; 19:00–23:00 ET (UTC-5)',
  tzNote:'All event times in',
  p1t:'THANKSGIVING · MYSTERY SHOP', p1w:'Nov 19 00:00 — Dec 2 00:00',
  p1d:'Pick 3 products and reveal discounts. Pay for any one to unlock your next draw.',
  p1go:'Enter Mystery Shop →',
  p2t:'BLACK FRIDAY · FLASH SALE', p2w:'Nov 27 00:00 — Dec 2 00:00',
  p2d:'Shop daily offers on currency, items and vouchers.',
  p2go:'Shop Flash Deals →',
  p3t:'CYBER MONDAY · GACHA MACHINE', p3w:'Nov 30 00:00 — Dec 2 00:00',
  p3d:'100% win rate. Every capsule is a prize — but each draw costs more, and prizes never come back.',
  p3go:'Crack the Machine →',
  live:'Live Now', soon:'Upcoming', over:'Ended',
  startsIn:'Starts in', endsIn:'Ends in', ended:'Ended', d:'d',
  act1:'ACT 1', act2:'ACT 2', act3:'ACT 3',
  when1:'Nov 19 00:00 — Dec 2 00:00 ET', when2:'Nov 27 00:00 — Dec 2 00:00 ET', when3:'Nov 30 00:00 — Dec 2 00:00 ET',
  sub1:'Choose a game and pick 3 products to reveal mystery discounts. Each card reveals an independently drawn discount. Pay for any one product from this round to unlock your next draw for that game.',
  pickLeft:'Picked', drawLeft:'Draws remaining', drawRef:'Draw status',
  flipBonus:'🎁 Mystery Shop orders earn <b>+5% bonus credit</b>',
  msHint:'?% OFF', pickMax:'You can pick 3 items only', pickFirst:'Pick 3 items first!',
  drawDealBtn:'UNLOCK MYSTERY DISCOUNTS',
  reDraw:'Re-draw (uses 1 draw)', changePicks:'Change my picks', revealDone:'Mystery discounts unlocked! 🎉',
  mascotSay:'Pick 3 items you love — all 3 get a mystery discount!',
  mysteryDeal:'Mystery Deal', buyNow:'BUY NOW',
  noDraws:'Purchase any item from this round to unlock your next draw.', flipRefreshed:'Your draws have been refreshed!',
  sub2:'Explore a new selection of currency, items and vouchers every day.',
  sessEnds:'Session ends in', sessStarts:'Session starts in', sessOver:'Session ended',
  sold:'Sold', leftTxt:'left', soldOut:'SOLD OUT', notStarted:'NOT STARTED', grab:'GRAB IT NOW',
  grabCoupon:'GRAB COUPON',
  couponTag:'COUPON', couponGame:'BLACK FRIDAY EXCLUSIVE', free:'FREE',
  couponToast:c=>`Coupon ${c} claimed & copied!`,
  codeLbl:'Sitewide Code', copy:'Copy Code', copied:c=>`Code ${c} copied!`,
  sub3:"Your personal machine holds <b style=\"color:var(--txt)\">6 no-minimum coupons</b>, revealed up front in your prize pool on the right. Every draw is <b style=\"color:var(--txt)\">completely free</b>: reach a cumulative order milestone and the machine unlocks one capsule. Watch the progress bar to see how close you are.",
  drawFree:'GACHA REWARDS',
  drawFreeSub:'Unlock draws with cumulative spending',
  costNote:()=>`6 draws unlocked at cumulative spending of <b>$1 / $100 / $300 / $500 / $800 / $1000</b>`,
  draw:'DRAW A CAPSULE', poolEmpty:'POOL CLEARED!', spendMore:'SPEND MORE TO UNLOCK',
  spend1:'My event order total',
  spendRule:()=>`Reach each milestone to unlock a draw. Every draw is free.`,
  nextAt:(n,v)=>`Next draw at <b>$${v}</b> total orders`,
  allUnlocked:'All 5 milestones unlocked! 🎉',
  spendDemo:"(demo slider — in production this reads the user's real cumulative order amount)",
  poolT:'My Prize Pool', poolNote:'· 6 no-minimum coupons',
  poolLeft:'Capsules left in my pool:', poolLeft2:'', gone:'DRAWN', leftN:n=>`× ${n} left`,
  locked:'LOCKED', mysteryReward:'??? Mystery Reward',
  legend:'legend', epic:'epic', rare:'rare',
  mTitle2:'LUCKY GACHA', mIdle:'INSERT TO PLAY', mShaking:'SHAKING...', mDrop:'HERE IT COMES!',
  codesValidity:'Claim and reuse from Nov 19, 00:00 until Dec 2, 00:00 ET. Cannot be combined with other codes or coupons.', gcT:'🎮 Game-Exclusive Codes · Your favorite game might be here',
  gcSub:"Claim and reuse game-exclusive codes from Nov 19, 00:00 until Dec 2, 00:00 ET.",
  claim:'CLAIM', claimed:'CLAIMED ✓',
  claimedToast:c=>`Code ${c} claimed & copied!`,
  fdT:'🎁 Free First-Draw Gift',
  fdD:'Claim one free draw during the Cyber Monday event.',
  fdBtn:'🎁 HOLIDAY FREE DRAW · ONCE', fdDone:'CLAIMED ✓',
  fdToast:'Free draw claimed! Good luck! 🍀',
  rulesT:'Carnival Rules',
  footer:'MMOEXP · Max My Online Exp — Best price · Fast delivery · 24/7 support · © 2026 MMOEXP Carnival Festival',
  modalBtn:'Awesome', youWon:n=>`You won: ${n}`,
  winDesc:(d)=>`Prize #${d}. It has been removed from your pool.`,
  winDescFree:()=>`You used your free draw. Further draws unlock with cumulative spending.`
},
zh:{
  heroTitle:'狂欢盛典', heroBenefitCoupon:'登录账号，直领 <strong class="coupon-highlight">10% OFF</strong> 优惠券！', heroBenefitGacha:'活动期间累计消费，解锁扭蛋机会，抽取无门槛优惠券大奖！', agendaEnter:'进入活动 →', railTitle:'活动导航', rail1:'感恩节', rail2:'黑色星期五', rail3:'网络星期一', rail4:'活动规则', storeTitle:'黑色星期五商店', storeDemo:'商品与价格为演示', storeSlogan:'每日特惠 · 专属折扣', storeCurrency:'金币', storeItems:'道具', storeVoucher:'优惠券', flashSlideHint:'左右滑动查看更多', couponEyebrow:'EXPIE 送你一份礼物', agendaTitle:'节日活动抢先看', agendaDate1:'11月19日 — 12月2日 00:00', agendaDate2:'11月27日 — 12月2日 00:00', agendaDate3:'11月30日 — 12月2日 00:00', agendaName1:'感恩节 · 神秘商店', agendaName2:'黑色星期五 · 限时秒杀', agendaName3:'网络星期一 · 扭蛋机', agendaBenefit1:'任选 3 件商品，最高享 <strong class="benefit-highlight">15% OFF</strong>', agendaBenefit2:'金币、道具超低优惠，黑五专属优惠券免费抢！', agendaBenefit3:'累计消费满 $1 解锁首次抽奖', agendaGachaSpeech:'11 月 19 日起累计消费！记得登录，否则订单可能无法统计哦。', gachaSpendReminder:'累计消费从 11 月 19 日开始计算，请先登录账号，否则订单可能无法计入。', agendaRule1:'任选 3 件商品，抽取 15%、10%、8% 折扣。', agendaRule2:'每天一场，金币、道具和优惠券享专属优惠。', agendaRule3:'领取免费抽奖机会，累计订单金额解锁更多抽奖。', agendaRules:'查看完整规则 →',
  logoTag:'狂欢盛典', nav1:'神秘商店', nav2:'限时秒杀', nav3:'扭蛋机', nav4:'活动规则', backStore:'返回商城',
  heroTag:'11月19日 — 12月2日 · 感恩节 × 黑色星期五 × 网络星期一',
  heroT2:'节日', heroT3:'特惠',
  heroSub:'七天狂欢，三幕连台，一个入口。感恩启程挑 3 件抽神秘折扣，黑五狂潮抢闪电秒杀，网一收官砸扭蛋机——每一笔订单都为你的网一抽奖积攒机会。',
  heroClaimBtn:'🎟️ 领取任意订单 10% 折扣券',
  heroClaimNote:'点击领取一张任意订单可用的 10% 折扣券，并提前开启秒杀活动。',
  heroClaimDone:'🎟️ 折扣券已领取 ✓',
  earlyLive:'已提前开启',
  earlyToast:c=>`折扣券 ${c} 已领取并复制——任意订单享 10% OFF。`,
  cpLabel:'节日优惠券',
  cpOff:'10% OFF',
  cpNote:'注册用户可领 · 各游戏通用 · 不与其他优惠券或折扣码叠加。', couponMin:'最低消费：$0.00',
  cpCodeLbl:'券码',
  cpBtn:'领取优惠券',
  cpLater:'暂不领取', loginRequiredTitle:'登录后领取优惠券', loginRequiredText:'请先登录或注册，即可领取优惠券。', loginGo:'登录 / 注册', couponTicketFoot:'全游戏通用 · 无门槛', loginPending:'请先登录后继续。', loginLater:'暂不登录', couponPending:'优惠券暂不可领取。',
  flashSchedule:'11月27日—12月1日，每天两场：12:00–16:00、19:00–23:00（美东时间 ET，UTC-5）',
  tzNote:'活动时间均为',
  p1t:'感恩节 · 神秘商店', p1w:'11月19日 00:00 — 12月2日 00:00',
  p1d:'选择 3 件商品抽折扣，购买本轮任意一件并支付成功即可再次翻牌。',
  p1go:'进入神秘商店 →',
  p2t:'黑色星期五 · 限时秒杀', p2w:'11月27日 00:00 — 12月2日 00:00',
  p2d:'每天两场，金币、道具及优惠券专属特惠。',
  p2go:'去抢秒杀 →',
  p3t:'网络星期一 · 扭蛋机', p3w:'11月30日 00:00 — 12月2日 00:00',
  p3d:'100% 中奖率。每颗扭蛋都是奖品——但抽价逐次递增，奖品抽完不补。',
  p3go:'开扭蛋机 →',
  live:'进行中', soon:'未开始', over:'已结束',
  startsIn:'距开始', endsIn:'距结束', ended:'已结束', d:'天',
  act1:'活动 1', act2:'活动 2', act3:'活动 3',
  when1:'11月19日 00:00 — 12月2日 00:00（美东）', when2:'11月27日 00:00 — 12月2日 00:00（美东）', when3:'11月30日 00:00 — 12月2日 00:00（美东）',
  sub1:'选择游戏和 3 件心仪商品，抽取神秘折扣。每张牌独立抽取折扣；购买本轮任意一件商品并支付成功，即可解锁该游戏下一次翻牌。',
  pickLeft:'已选', drawLeft:'剩余抽取次数', drawRef:'翻牌状态',
  flipBonus:'🎁 神秘商店下单额外赠 <b>5% 礼金</b>',
  msHint:'?折 折扣', pickMax:'最多只能选择 3 件商品', pickFirst:'请先选满 3 件商品！',
  drawDealBtn:'开启神秘折扣',
  reDraw:'再抽一次（消耗 1 次）', changePicks:'重新挑选商品', revealDone:'神秘折扣已揭晓！🎉',
  mascotSay:'挑 3 件你最想要的——三件都有神秘折扣！',
  mysteryDeal:'神秘优惠', buyNow:'立即购买',
  noDraws:'购买本轮任意一件商品并支付成功后解锁。', flipRefreshed:'你的抽取次数已刷新！',
  sub2:'每天两场，发现金币、道具和优惠券的专属优惠。',
  sessEnds:'本场距结束', sessStarts:'本场距开始', sessOver:'本场已结束',
  sold:'已抢', leftTxt:'件剩余', soldOut:'已售罄', notStarted:'未开始', grab:'立即抢购',
  grabCoupon:'抢优惠券',
  couponTag:'优惠券', couponGame:'黑五专属优惠券', free:'免费抢',
  couponToast:c=>`优惠券 ${c} 已领取并复制！`,
  codeLbl:'全站折扣码', copy:'复制折扣码', copied:c=>`折扣码 ${c} 已复制！`,
  sub3:'你的专属扭蛋机内有 <b style="color:var(--txt)">6 张无门槛优惠券</b>，已在右侧奖池中公开透明展示。<b style="color:var(--txt)">抽奖完全免费</b>：累计订单金额每达到一个里程碑，就解锁一颗扭蛋。看进度条，就知道还差多少。',
  drawFree:'扭蛋抽奖',
  drawFreeSub:'累计消费解锁抽奖机会',
  costNote:()=>`共 6 抽 · 累计消费达 <b>$1 / $100 / $300 / $500 / $800 / $1000</b> 分别解锁`,
  draw:'抽一颗扭蛋', poolEmpty:'奖池已被你抽空！', spendMore:'继续消费以解锁',
  spend1:'我的活动累计订单金额',
  spendRule:()=>`每到达一个里程碑即可解锁一次抽奖，每次抽奖都免费。`,
  nextAt:(n,v)=>`下一抽：订单累计达 <b>$${v}</b>`,
  allUnlocked:'5 个里程碑已全部解锁！🎉',
  spendDemo:'（演示滑块——正式上线后读取用户真实订单累计金额）',
  poolT:'我的专属奖池', poolNote:'· 6 张无门槛优惠券',
  poolLeft:'我的奖池剩余：', poolLeft2:'颗扭蛋', gone:'已抽走', leftN:n=>`剩 ${n} 份`,
  locked:'未解锁', mysteryReward:'？？？ 神秘奖励',
  legend:'传说', epic:'史诗', rare:'稀有',
  mTitle2:'幸运扭蛋机', mIdle:'请投币', mShaking:'摇一摇中...', mDrop:'掉落啦！',
  codesValidity:'11月19日 00:00 至12月2日 00:00（美东）可领取和多次使用，不可与其他折扣码或优惠券叠加。', gcT:'🎮 游戏专属折扣码 · 你喜欢的游戏也许在这里',
  gcSub:'11月19日 00:00 至12月2日 00:00（美东）可领取并多次使用。',
  claim:'领取', claimed:'已领取 ✓',
  claimedToast:c=>`折扣码 ${c} 已领取并复制！`,
  fdT:'🎁 免费首抽福利',
  fdD:'网络星期一活动期间可免费领取一次扭蛋机会。',
  fdBtn:'🎁 节日限定 · 免费领 1 次', fdDone:'已领取 ✓',
  fdToast:'已领取 1 次免费抽奖，祝好运！🍀',
  rulesT:'活动规则',
  footer:'MMOEXP · Max My Online Exp — 价格最优 · 极速发货 · 24/7 客服 · © 2026 MMOEXP 狂欢盛典',
  modalBtn:'太棒了', youWon:n=>`恭喜抽中：${n}`,
  winDesc:(d)=>`第 ${d} 抽。该奖品已从你的专属奖池中移除。`,
  winDescFree:()=>`本次已使用免费抽奖机会，更多次数按累计实付金额解锁。`
}};

/* localStorage 安全封装：预览沙箱/隐私模式下自动降级为内存存储 */
const store = {
  _m: {},
  get(k){ try{ return localStorage.getItem(k); }catch(e){ return this._m[k] ?? null; } },
  set(k,v){ try{ localStorage.setItem(k,v); }catch(e){ this._m[k]=v; } }
};
// English only, like the main site (the language switch was removed 2026-11-17).
let LANG = 'en';
const t = k => T[LANG][k];
const nm = o => (LANG==='zh' && o.nameZh) ? o.nameZh : o.name;
const tm = o => (LANG==='zh' && o.timeZh) ? o.timeZh : o.time;

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const now = () => new Date();
const pad = n => String(n).padStart(2,'0');

function fmtDur(ms){
  if(ms<0) ms=0;
  const s=Math.floor(ms/1000), d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60), ss=s%60;
  return (d>0? d+t('d')+' ':'') + pad(h)+':'+pad(m)+':'+pad(ss);
}
function toast(msg){ const e=$('#toast'); e.textContent=msg; e.classList.add('show'); setTimeout(()=>e.classList.remove('show'),2200); }
function copyCode(c){ try{ navigator.clipboard?.writeText(c); }catch(e){} toast(t('copied')(c)); }

/* ---------- Event status / hero countdowns ---------- */
function phaseStatus(ev){
  const n=now(), s=new Date(ev.start), e=new Date(ev.end);
  if(n<s) return {k:'soon', label:t('soon'), cd:t('startsIn')+' '+fmtDur(s-n)};
  if(n>=e) return {k:'over', label:t('over'), cd:t('ended')};
  return {k:'live', label:t('live'), cd:t('endsIn')+' '+fmtDur(e-n)};
}
$('#tz-label').textContent = CONFIG.tzLabel;

/* ================= Act 1: Mystery Shop（任选 3 件 → 抽折扣分配） ================= */
let curGame = CONFIG.mystery.games[0].id;

let msDrawsLeft=1;
let msProgress={};
try{msProgress=JSON.parse(store.get('mystery-purchase-unlock-v2-reset')||'{}')||{};}catch(e){msProgress={};}
function mysteryGameState(){return msProgress[curGame]||(msProgress[curGame]={rounds:0,pending:null});}
function persistMysteryProgress(){store.set('mystery-purchase-unlock-v2-reset',JSON.stringify(msProgress));}
function syncMysteryCooldown(){msDrawsLeft=mysteryGameState().pending?0:1;}
let picked=[];
let revealed=null;
let msBusy=false;
function saveMysteryResult(){
 mysteryGameState().pending={items:revealed,picked,platform:curGame==='fc27'?document.getElementById('fc27Platform').value:null,wowChoice:curGame==='wow'?wowChoice():null,poeLeague:curGame==='poe2'?document.getElementById('poeLeague').value:null};
 persistMysteryProgress();syncMysteryCooldown();
}
function restoreMysteryResult(){
 picked=[];revealed=null;
 const saved=mysteryGameState().pending;
 if(saved&&Array.isArray(saved.items)&&saved.items.length===CONFIG.mystery.pickCount){
  revealed=saved.items;picked=Array.isArray(saved.picked)?saved.picked:[];
  if(curGame==='fc27'&&['ps','xbox','pc'].includes(saved.platform))document.getElementById('fc27Platform').value=saved.platform;
  if(curGame==='poe2'&&saved.poeLeague)document.getElementById('poeLeague').value=saved.poeLeague;
  if(curGame==='wow'&&saved.wowChoice){for(const [k,id] of [['region','wowRegion'],['faction','wowFaction'],['realm','wowRealm']])document.getElementById(id).value=saved.wowChoice[k];}
 }
 syncMysteryCooldown();
}
function mysteryDiscountRoll(first=false){const n=Math.random();return first?(n<0.3?8:n<0.6?10:15):(n<0.4?8:n<0.8?10:15);}
function mysteryRoundDiscounts(first){return Array.from({length:CONFIG.mystery.pickCount},()=>mysteryDiscountRoll(first));}

/* 吉祥物：配置了 mascotImg 用正式图，否则用内置 SVG 占位形象 */
function renderMascot(){
  const box=$('#mascotBox');
  if(CONFIG.mystery.mascotImg){ box.innerHTML=`<img src="${CONFIG.mystery.mascotImg}" alt="MMOEXP Mascot">`; return; }
  box.innerHTML=`<svg viewBox="0 0 200 212" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="mbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8f6fff"/><stop offset="1" stop-color="#5a3df0"/></linearGradient></defs>
  <line x1="100" y1="16" x2="100" y2="36" stroke="#ffb84d" stroke-width="4" stroke-linecap="round"/>
  <circle cx="100" cy="12" r="7" fill="#ffb84d"/>
  <rect x="52" y="36" width="96" height="72" rx="26" fill="url(#mbg)"/>
  <circle cx="80" cy="68" r="11" fill="#0b0e17"/><circle cx="120" cy="68" r="11" fill="#0b0e17"/>
  <circle cx="83" cy="65" r="4" fill="#35e0ff"/><circle cx="123" cy="65" r="4" fill="#35e0ff"/>
  <path d="M84 90 Q100 102 116 90" stroke="#0b0e17" stroke-width="4" fill="none" stroke-linecap="round"/>
  <rect x="64" y="116" width="72" height="58" rx="20" fill="url(#mbg)"/>
  <circle cx="100" cy="145" r="13" fill="#ffb84d"/>
  <text x="100" y="150" text-anchor="middle" font-size="14" font-weight="700" fill="#0b0e17" font-family="Arial">M</text>
  <rect x="34" y="122" width="18" height="34" rx="9" fill="#5a3df0"/>
  <rect x="146" y="106" width="34" height="44" rx="6" fill="#ffb84d" transform="rotate(12 163 128)"/>
  <text x="163" y="136" text-anchor="middle" font-size="20" font-weight="700" fill="#7c5cff" font-family="Arial" transform="rotate(12 163 128)">?</text>
  <rect x="72" y="178" width="20" height="18" rx="8" fill="#3a2b8f"/>
  <rect x="108" y="178" width="20" height="18" rx="8" fill="#3a2b8f"/>
</svg>`;
}

// Keep each game's existing product pool; new games await product configuration.
const existingMysteryGames = Object.fromEntries(CONFIG.mystery.games.map(g => [g.id, g]));
CONFIG.mystery.games = [
  existingMysteryGames.fc27,
  {id:'wow', name:'WoW Forever', nameZh:'魔兽 Forever', icon:'🛡️', items:[{"name":"3G WoW Forever Gold","nameZh":"3G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":3,"wowSnapshot":3.86,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"5G WoW Forever Gold","nameZh":"5G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":5,"wowSnapshot":6.43,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"8G WoW Forever Gold","nameZh":"8G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":8,"wowSnapshot":10.29,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"10G WoW Forever Gold","nameZh":"10G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":10,"wowSnapshot":12.87,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"20G WoW Forever Gold","nameZh":"20G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":20,"wowSnapshot":25.74,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"30G WoW Forever Gold","nameZh":"30G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":30,"wowSnapshot":38.61,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"50G WoW Forever Gold","nameZh":"50G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":50,"wowSnapshot":64.34,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"70G WoW Forever Gold","nameZh":"70G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":70,"wowSnapshot":90.08,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"},{"name":"100G WoW Forever Gold","nameZh":"100G 魔兽 Forever 金币","icon":"🪙","price":null,"wowAmount":100,"wowSnapshot":128.69,"wowGameId":"1367","wowModelId":"43352405","storeUrl":"https://www.mmoexp.com/wow-gold.html","image":"assets/carnival-328e8cd04248.webp"}]},
  {id:'poe1', name:'POE 1', nameZh:'POE 1', icon:'⚔️', items:[{"name":"Divine Orb(20+1 Free)","nameZh":"Divine Orb(20+1 Free)","icon":"⚔️","price":12.6,"image":"assets/carnival-13fd4d6619bb.webp","modelId":"9493707","productId":"71488531","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":true},{"name":"Divine Orb","nameZh":"Divine Orb","icon":"⚔️","price":0.63,"image":"assets/carnival-e6c9660d694c.webp","modelId":"70079","productId":"38588459","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Chaos Orb(1000+100 Free)","nameZh":"Chaos Orb(1000+100 Free)","icon":"⚔️","price":6.2,"image":"assets/carnival-1577a01ad315.webp","modelId":"9493711","productId":"71488587","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Chaos Orb","nameZh":"Chaos Orb","icon":"⚔️","price":0.62,"image":"assets/carnival-5e34067109b6.webp","modelId":"70083","productId":"38588315","minQuantity":100,"displayNote":"100 ORBS","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Mirror of Kalandra","nameZh":"Mirror of Kalandra","icon":"⚔️","price":174,"image":"assets/carnival-f181a84624bc.webp","modelId":"70081","productId":"38588383","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Exalted Orb","nameZh":"Exalted Orb","icon":"⚔️","price":0.43,"image":"assets/carnival-07d1b2b7e501.webp","modelId":"70085","productId":"40602987","minQuantity":100,"displayNote":"100 ORBS","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Divine Orb(100+5 Free)","nameZh":"Divine Orb(100+5 Free)","icon":"⚔️","price":63,"image":"assets/carnival-9d7891770f78.webp","modelId":"45612087","productId":"187535323","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Currency.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Build 2 : Bow Starter Pack","nameZh":"Build 2 : Bow Starter Pack","icon":"⚔️","price":4.49,"image":"assets/carnival-e7acfa662767.webp","modelId":"114429","productId":"45283535","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Items.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false},{"name":"Build 3 : Melee Phys Starter Pack","nameZh":"Build 3 : Melee Phys Starter Pack","icon":"⚔️","price":5.99,"image":"assets/carnival-e7acfa662767.webp","modelId":"114427","productId":"45283527","minQuantity":1,"displayNote":"","poeLeague":"PC-Covens of Umbra SC","storeUrl":"https://www.mmoexp.com/Path-of-exile/Items.html","quoteSource":"MMOEXP PC-Covens of Umbra SC storefront snapshot 2026-11-16","modelStatusPending":false}]},
  existingMysteryGames.poe2,
  existingMysteryGames.d4,
  existingMysteryGames.maple,
  {id:'arc', name:'ARC Raiders', nameZh:'ARC Raiders', icon:'🎯', items:[]},
  {id:'codmw4', name:'COD MW4', nameZh:'COD MW4', icon:'🎮', items:[]}
];
// 商品与价格：2026-11-13 后台及网站快照，实时价格接口尚未接入。
for(const [id,items] of Object.entries({"maple":[{"name":"300K Mesos","nameZh":"300K Mesos","icon":"🎮","price":12.21,"productId":"165167189","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Mesos.html"},{"name":"1000K Mesos","nameZh":"1000K Mesos","icon":"🎮","price":44.95,"productId":"165167189","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Mesos.html"},{"name":"Gloves Attack Scroll: Intermediate","nameZh":"Gloves Attack Scroll: Intermediate","icon":"🎮","price":119.99,"productId":"186209371","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Tobi Throwing Stars","nameZh":"Tobi Throwing Stars","icon":"🎮","price":143.85,"productId":"186282265","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Icicle","nameZh":"Icicle","icon":"🎮","price":40.85,"productId":"186282115","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Mokbi Throwing Stars","nameZh":"Mokbi Throwing Stars","icon":"🎮","price":29.35,"productId":"186282205","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Overall Armor LUK Scroll: Intermediate","nameZh":"Overall Armor LUK Scroll: Intermediate","icon":"🎮","price":45.45,"productId":"186209281","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Steely Throwing Knives","nameZh":"Steely Throwing Knives","icon":"🎮","price":475.49,"productId":"186282235","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"},{"name":"Kumbi Throwing Stars","nameZh":"Kumbi Throwing Stars","icon":"🎮","price":35.45,"productId":"186282175","displayNote":"Windia","storeUrl":"https://www.mmoexp.com/Maplestory-classic-world/Items.html"}],"arc":[{"name":"Stencil Parts ×10","nameZh":"Stencil Parts ×10","icon":"🎮","price":0.8,"productId":"185981107","displayNote":"PC / PS / XBOX · min. 10","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"Fossilized Lightning","nameZh":"Fossilized Lightning","icon":"🎮","price":1.61,"productId":"185382277","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"Looting Mk.3 (Survivor)","nameZh":"Looting Mk.3 (Survivor)","icon":"🎮","price":0.5,"productId":"112802085","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"Medium Shield","nameZh":"Medium Shield","icon":"🎮","price":0.36,"productId":"112802373","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"ARC Data Module","nameZh":"ARC Data Module","icon":"🎮","price":0.75,"productId":"185383333","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"Advanced Mechanical Components ×5","nameZh":"Advanced Mechanical Components ×5","icon":"🎮","price":1.25,"productId":"112807773","displayNote":"PC / PS / XBOX · min. 5","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"Queen Reactor","nameZh":"Queen Reactor","icon":"🎮","price":1.34,"productId":"112811421","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Arc-raiders/Items.html"},{"name":"500K Coins","nameZh":"500K Coins","icon":"🎮","price":11.34,"productId":"105267633","displayNote":"PC","storeUrl":"https://www.mmoexp.com/Arc-raiders/Coins.html"},{"name":"1500K Coins","nameZh":"1500K Coins","icon":"🎮","price":33.32,"productId":"105267633","displayNote":"PC","storeUrl":"https://www.mmoexp.com/Arc-raiders/Coins.html"}],"codmw4":[{"name":"1 Run Domination Bot Lobby","nameZh":"1 Run Domination Bot Lobby","icon":"🎮","price":3.99,"productId":"165175543","displayNote":"PC","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Bot-lobbies.html"},{"name":"Binding Catalyst","nameZh":"Binding Catalyst","icon":"🎮","price":0.29,"productId":"186374427","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"High-Tenacity Fibers","nameZh":"High-Tenacity Fibers","icon":"🎮","price":0.3,"productId":"186374619","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"2 Hours Bot Lobbies + 2 Hour Weapon & Rank XP Token","nameZh":"2 Hours Bot Lobbies + 2 Hour Weapon & Rank XP Token","icon":"🎮","price":23.98,"productId":"165175575","displayNote":"PS","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Bot-lobbies.html"},{"name":"Comms Module","nameZh":"Comms Module","icon":"🎮","price":0.47,"productId":"186372891","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"Alloyed Plating","nameZh":"Alloyed Plating","icon":"🎮","price":0.47,"productId":"186372603","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"Stock Rod","nameZh":"Stock Rod","icon":"🎮","price":0.3,"productId":"186372507","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"Structural Alloy","nameZh":"Structural Alloy","icon":"🎮","price":0.3,"productId":"186372699","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"},{"name":"Power Regulator","nameZh":"Power Regulator","icon":"🎮","price":0.47,"productId":"186373083","displayNote":"PC / PS / XBOX","storeUrl":"https://www.mmoexp.com/Cod-modern-warfare-4/Dmz-items.html"}]})) CONFIG.mystery.games.find(g=>g.id===id).items=items;

const marketGames=['maple','arc','codmw4'];
const marketSelections={maple:'Windia',arc:'PC',codmw4:'PC'};
const marketOptions={maple:['Windia'],arc:['PC','PS','XBOX'],codmw4:['PC','PS','XBOX']};
for(const id of marketGames){const items=CONFIG.mystery.games.find(g=>g.id===id).items;items.forEach((it,i)=>{it.marketGame=id;it.marketPrices={};if(id==='maple')it.marketPrices.Windia=it.price;else if(id==='arc'){it.marketPrices.PC=it.price;if(i<7)it.marketPrices.PS=it.marketPrices.XBOX=it.price;}else {if(i===0)it.marketPrices.PC=it.price;else if(i===3)it.marketPrices.PS=it.price;else it.marketPrices.PC=it.marketPrices.PS=it.marketPrices.XBOX=it.price;}})}
function marketSelectionChanged(){marketSelections[curGame]=document.getElementById('marketChoiceSelect').value;picked=[];renderMsZone();}
function marketItemNote(it){if(!it.marketGame)return it.displayNote||'';return (it.marketChoice||marketSelections[it.marketGame])+(it.marketGame==='arc'&&it.name.includes('×10')?' · min. 10':it.marketGame==='arc'&&it.name.includes('×5')?' · min. 5':'');}

const marketArt={"300K Mesos":"assets/carnival-bc2fbaf50fad.webp","1000K Mesos":"assets/carnival-bc2fbaf50fad.webp","Gloves Attack Scroll: Intermediate":"assets/carnival-acf5dde56ba3.webp","Tobi Throwing Stars":"assets/carnival-ef76bf7acc63.webp","Icicle":"assets/carnival-7f98dc6fddd4.webp","Mokbi Throwing Stars":"assets/carnival-c02826de54e9.webp","Overall Armor LUK Scroll: Intermediate":"assets/carnival-acf5dde56ba3.webp","Steely Throwing Knives":"assets/carnival-fa806cb1da8b.webp","Kumbi Throwing Stars":"assets/carnival-e1d9b886a8a9.webp","Stencil Parts ×10":"assets/carnival-ad375d067752.webp","Fossilized Lightning":"assets/carnival-28d5b0091ec0.webp","Looting Mk.3 (Survivor)":"assets/carnival-26e823f53d34.webp","Medium Shield":"assets/carnival-1eacbea0622e.webp","ARC Data Module":"assets/carnival-55863fcff593.webp","Advanced Mechanical Components ×5":"assets/carnival-fd5783bed5ad.webp","Queen Reactor":"assets/carnival-ba3eb239a042.webp","500K Coins":"assets/carnival-e8d63d3be276.webp","1500K Coins":"assets/carnival-e8d63d3be276.webp","1 Run Domination Bot Lobby":"assets/carnival-2eaf8f6eea1d.webp","2 Hours Bot Lobbies + 2 Hour Weapon & Rank XP Token":"assets/carnival-2eaf8f6eea1d.webp","Binding Catalyst":"assets/carnival-bded1bccaf92.webp","High-Tenacity Fibers":"assets/carnival-a14c604de1e5.webp","Power Regulator":"assets/carnival-8920f4836c23.webp","Comms Module":"assets/carnival-e6866ad33d8d.webp","Alloyed Plating":"assets/carnival-154bff68a5d5.webp","Stock Rod":"assets/carnival-3fde2ce1d685.webp","Structural Alloy":"assets/carnival-17fdc9187af7.webp"};
for(const id of marketGames) for(const it of CONFIG.mystery.games.find(g=>g.id===id).items){it.image=marketArt[it.name];if(id==='arc'&&it.name.includes('Coins'))it.marketPrices.PS=it.marketPrices.XBOX=it.price;if(id==='codmw4'&&(it.name==='1 Run Domination Bot Lobby'||it.name.startsWith('2 Hours Bot Lobbies'))){it.marketPrices.PC=it.marketPrices.PS=it.marketPrices.XBOX=it.price;}}
const cuddly=CONFIG.mystery.games.find(g=>g.id==='d4').items.find(x=>x.goodsId==='186050303');if(cuddly)cuddly.fromPrice=false;

const gameVisuals={
 fc27:{icon:'1327', art:'assets/carnival-d433419c8187.webp', fallback:'⚽'},
 poe2:{icon:'552', art:'assets/carnival-0f3d1db1cf1a.webp', fallback:'🔮'},
 d4:{icon:'456', art:'assets/carnival-26268c9a5aa7.webp', fallback:'🔥'},
 maple:{icon:'1333', art:'assets/carnival-153c560245b8.webp', fallback:'🍁'},
 aion2:{icon:'891', art:'assets/carnival-188c013d1128.webp', fallback:'⚔️'}
};
// Preview sample inventory; replace with actual product configuration on integration.
CONFIG.mystery.games.forEach(game=>{
 if(!game.items.length){
  game.items=Array.from({length:9},(_,i)=>({name:'Sample Item '+(i+1),nameZh:'演示商品 '+(i+1),icon:['🪙','💎','🎁'][i%3],price:10+i*5,url:'',demo:true}));
 }
});
// Additional artwork from game publishers and official game listings.
Object.assign(gameVisuals, {
  poe1:{icon:'',art:'assets/carnival-27eb73aa6f62.webp'},
  wow:{icon:'',art:'assets/carnival-07e3dde47a0c.webp'},
  arc:{icon:'',art:'assets/carnival-f71626002ce3.webp'},
  codmw4:{icon:'',art:'assets/carnival-4461a4b40077.webp'}
});

/* AION 2 catalog and selected-server snapshot. */
const AION_SERVERS={"EU":{"Asmodian":["Israphel","Zikel","Triniel","Lumiel","Marchutan","Beritra","Azphel","Ereshkigal","Hadala","Ludra","Ulgorn","Munin","Odar","Zemurru","Kromede","Quai","Baba","Nemon","Fafnir","Indnath","Agnita","Atiel","Tassin"],"Elyos":["Siel","Nezekan","Vaizel","Kaisinel","Yustiel","Meslamtaeda","Ariel","Fregion","Nania","Tahavatha","Luteros","Phernos","Daminu","Kasaka","Bakarma","Tsenka","Kochi","Hithanya","Lamuatan","Ishtar","Tiamat","Gauss","Nathara"]},"NA West":{"Asmodian":["Israphel","Zikel","Triniel","Lumiel","Marchutan"],"Elyos":["Siel","Nezekan","Vaizel","Kaisinel","Yustiel"]},"NA East":{"Asmodian":["Israphel","Zikel","Triniel","Lumiel","Marchutan","Azphel","Ereshkigal","Beritra","Nemon"],"Elyos":["Siel","Nezekan","Vaizel","Kaisinel","Yustiel","Ariel","Fregion","Meslamtaeda","Hithaya"]},"South America":{"Asmodian":["Israphel","Zikel","Triniel","Lumiel","Marchutan","Azphel"],"Elyos":["Siel","Nezekan","Vaizel","Kaisinel","Yustiel","Ariel"]},"Asia":{"Asmodian":["Israphel","Zikel","Lumiel","Marchutan","Azphel","Triniel","Ereshkigal","Beritra","Hadala","Nemon"],"Elyos":["Siel","Nezekan","Kaisinel","Yustiel","Ariel","Vaizel","Fregion","Meslamtaeda","Hithanya","Nania"]}};
const AION_EU_ASMO_ISRAPHEL_PRICES={10:4.30,30:12.90,50:21.50,100:42.99,300:128.99,500:214.98,600:257.98,800:354.68,1000:455.85};
CONFIG.mystery.games.splice(1,0,{id:'aion2',name:'AION 2',nameZh:'AION 2',icon:'🪙',items:[10,30,50,100,300,500,600,800,1000].map(amount=>({name:amount+'M AION 2 Kina',nameZh:amount+'M AION 2 Kina',icon:'🪙',aionAmount:amount,price:AION_EU_ASMO_ISRAPHEL_PRICES[amount],modelId:'17815737',storeUrl:'https://www.mmoexp.com/Aion-2/Kinah.html'}))});
gameVisuals.aion2={icon:'',art:'assets/carnival-bd44e344faea.webp'};
function aionSelectionChanged(resetServer){
 if(curGame!=='aion2')return;const r=document.getElementById('aionRegion').value,f=document.getElementById('aionFaction').value,select=document.getElementById('aionServer');
 const choices=AION_SERVERS[r]?.[f]||[];const old=select.value;select.innerHTML=choices.map(x=>'<option value="'+x+'">'+x+'</option>').join('');select.value=(!resetServer&&choices.includes(old))?old:choices[0];
 const available=r==='EU'&&f==='Asmodian'&&select.value==='Israphel';
 CONFIG.mystery.games.find(g=>g.id==='aion2').items.forEach(it=>it.price=available?AION_EU_ASMO_ISRAPHEL_PRICES[it.aionAmount]:null);
 document.getElementById('aionPriceNote').textContent=available?(LANG==='zh'?'该服务器价格为 11 月 17 日前台快照':'Server prices are a Nov 17 storefront snapshot'):(LANG==='zh'?'该服务器价格暂不可用':'Price unavailable for this server');
 if(!revealed){picked=[];renderMsZone();}
}

function renderTabs(){
  // The live page removes the demo notice (carnival-live.js), so these may be absent.
  const demoText=$('#mysteryDemoNoticeText'),demoReset=$('#mysteryDemoReset');
  if(demoText)demoText.textContent=LANG==='zh'?'流程演示：商品和价格仅供测试，登录、发券及购买均为模拟。':'TEST PREVIEW · Sample products and prices. Login, coupons and checkout are simulated.';
  if(demoReset)demoReset.textContent=LANG==='zh'?'重置当前游戏演示':'RESET CURRENT GAME (DEMO)';
  $('#gameTabs').innerHTML=CONFIG.mystery.games.map(g=>{
    const v=gameVisuals[g.id], active=g.id===curGame;
    const picture=`<img class="game-art-img" src="${v.art}" alt="" loading="lazy" onerror="this.style.display='none'"><span class="game-art-shade"></span>`;
    return `<button type="button" class="gtab ${active?'on':''} game-${g.id}" onclick="selGame('${g.id}')" aria-pressed="${active}" aria-label="${nm(g)}">${picture}<span class="game-mark dragon-ico-gid-${v.icon}" aria-hidden="true"><span class="game-fallback">${v.fallback}</span></span><span class="game-name">${nm(g)}</span><span class="game-selected">✓</span></button>`;
  }).join('');
}
// Arrows move the game list without intercepting ordinary page scrolling.
const gameCarousel = $('#gameTabs');
function updateGameArrows(){
  const max = Math.max(0, gameCarousel.scrollWidth - gameCarousel.clientWidth);
  $('#gamePrev').disabled = gameCarousel.scrollLeft <= 1;
  $('#gameNext').disabled = gameCarousel.scrollLeft >= max - 1;
}
function moveGameCarousel(direction){
  const first = gameCarousel.querySelector('.gtab');
  const distance = first ? first.getBoundingClientRect().width + 12 : gameCarousel.clientWidth * .7;
  gameCarousel.scrollBy({left: direction * distance * 2, behavior:'smooth'});
}
$('#gamePrev').addEventListener('click',()=>moveGameCarousel(-1));
$('#gameNext').addEventListener('click',()=>moveGameCarousel(1));
gameCarousel.addEventListener('scroll', updateGameArrows, {passive:true});
window.addEventListener('resize', updateGameArrows);
requestAnimationFrame(updateGameArrows);
function selGame(id){ if(msBusy)return; curGame=id; syncMysteryCooldown(); restoreMysteryResult(); renderTabs(); renderMsZone(); tickMs(); }
function gameItems(){ return CONFIG.mystery.games.find(g=>g.id===curGame); }

/* 顶部进度信息 */
function renderMsMeta(){
  $('#pickCount').textContent = revealed ? CONFIG.mystery.pickCount : picked.length;
  $('#pickMax').textContent = CONFIG.mystery.pickCount;
  $('#msDrawLeft').textContent = msDrawsLeft;
}
/* 底部操作按钮：选择态=抽取按钮；揭晓态=再抽/改选 */
function renderMsActions(){
  const box=$('#msActions');
  if(!gameItems().items.length){ box.innerHTML=''; return; }
  if(revealed){
    box.innerHTML='';
  }else{
    const full = picked.length>=CONFIG.mystery.pickCount;
    box.innerHTML=`<button class="drawdeal-btn" ${full&&msDrawsLeft>0?'':'disabled'} onclick="drawDeal()">`+
      `${msDrawsLeft<=0?t('noDraws'):t('drawDealBtn')}</button>`;
  }
}
/* 整区渲染入口（切换游戏/语言/改选后调用） */
function wowChoice(){return {region:document.getElementById('wowRegion').value,faction:document.getElementById('wowFaction').value,realm:document.getElementById('wowRealm').value};}
function wowSelectionChanged(){if(curGame==='wow'&&picked.length)picked=[];const region=document.getElementById('wowRegion').value,realm=document.getElementById('wowRealm');if(region==='Asia'&&['Roleplay','Roleplay-PVP'].includes(realm.value))realm.value='Normal';for(const option of realm.options)option.disabled=region==='Asia'&&['Roleplay','Roleplay-PVP'].includes(option.value);renderMsZone();}
function poeLeagueChanged(){if(curGame==='poe2'&&picked.length)picked=[];renderMsZone();}
const WOW_PRICE_SNAPSHOT={"US":{"Alliance":{"Normal":[187090053,1.12972],"PVP":[187090087,1.101708],"Roleplay":[187090121,1.6],"Roleplay-PVP":[187090155,1.6]},"Horde":{"Normal":[187090223,1.286853],"PVP":[187090257,0.952348],"Roleplay":[187090291,1.6],"Roleplay-PVP":[187090325,1.6]}},"EU":{"Alliance":{"Normal":[187090427,1.6],"PVP":[187090461,1.6],"Roleplay":[187090495,1.6],"Roleplay-PVP":[187090529,1.6]},"Horde":{"Normal":[187090597,1.387809],"PVP":[187090631,1.303259],"Roleplay":[187090665,1.6],"Roleplay-PVP":[187090699,1.6]}},"Asia":{"Alliance":{"Normal":[187090733,1.494472],"PVP":[187090767,0.892142]},"Horde":{"Normal":[187090937,1.145718],"PVP":[187090971,0.73713]}},"KR":{"Alliance":{"Normal":[187091107,2.99],"PVP":[187091141,1.6],"Roleplay":[187091175,2.99],"Roleplay-PVP":[187091209,1.6]},"Horde":{"Normal":[187091277,1.6],"PVP":[187091311,1.335629],"Roleplay":[187091345,2.99],"Roleplay-PVP":[187091379,1.6]}}};
function fc27Price(it){if(it.marketGame){const choice=it.marketChoice||marketSelections[it.marketGame];return Number.isFinite(it.marketPrices?.[choice])?it.marketPrices[choice]:null;}if(it.poeGoodsId){const league=it.poeLeague||document.getElementById('poeLeague').value;return league==='Forbidden Rites'?it.poePrice:null;}if(it.wowAmount){const c=it.wowChoice||wowChoice();const entry=WOW_PRICE_SNAPSHOT[c.region]?.[c.faction]?.[c.realm];return entry?Math.round((entry[1]*it.wowAmount+Number.EPSILON)*100)/100:null;}if(!it.snapshots)return Number.isFinite(it.price)?it.price:null;const platform=document.getElementById('fc27Platform').value;return platform&&Number.isFinite(it.snapshots[platform])?it.snapshots[platform]:null;}
const fc27GeneratedCoin='assets/carnival-c96b27222fd5.webp';
const aionKinaCoin='assets/carnival-61d6a31a2486.webp';
function fc27Art(it){const current=CONFIG.mystery.games.flatMap(g=>g.items).find(item=>item.name===it.name);const image=it.aionAmount?aionKinaCoin:it.modelId==='41217957'?fc27GeneratedCoin:(current?.image||it.image);return image?'<img class="fc27-product-img" src="'+image+'" alt="" loading="lazy">':it.icon;}
function renderMsZone(){if(curGame==='d4'&&revealed)for(const r of revealed)if(r.it.goodsId==='186050303')r.it.fromPrice=false;
  document.getElementById('fc27PlatformBar').style.display=curGame==='fc27'?'flex':'none';
  const marketVisible=marketGames.includes(curGame),marketBox=document.getElementById('marketSelector'),marketSelect=document.getElementById('marketChoiceSelect');
  marketBox.style.display=marketVisible?'block':'none';
  if(marketVisible){if(revealed&&revealed[0]?.it?.marketChoice)marketSelections[curGame]=revealed[0].it.marketChoice;if(curGame==='maple')marketSelections.maple='Windia';marketSelect.innerHTML=marketOptions[curGame].map(x=>'<option value="'+x+'">'+(curGame==='maple'?'Global / Windia':x)+'</option>').join('');marketSelect.value=marketSelections[curGame];marketSelect.disabled=curGame==='maple'||!!revealed;document.getElementById('marketSelectorTitle').textContent=curGame==='maple'?'MapleStory · Server':curGame==='arc'?'ARC Raiders · Platform':'COD MW4 · Platform';document.getElementById('marketSelectLabel').textContent=curGame==='maple'?'Server':'Platform';}
  document.getElementById('d4PriceNote').style.display=curGame==='d4'?'block':'none';
  document.getElementById('wowSelector').style.display=curGame==='wow'?'block':'none';
  document.getElementById('aionSelector').style.display=curGame==='aion2'?'block':'none';
  if(curGame==='aion2'){
   const rs=document.getElementById('aionRegion'),fs=document.getElementById('aionFaction'),ss=document.getElementById('aionServer');
   if(!ss.options.length){ss.innerHTML=AION_SERVERS.EU.Asmodian.map(x=>'<option value="'+x+'">'+x+'</option>').join('');ss.value='Israphel';}
   const valid=rs.value==='EU'&&fs.value==='Asmodian'&&ss.value==='Israphel';
   document.getElementById('aionPriceNote').textContent=valid?(LANG==='zh'?'该服务器价格为 11 月 17 日前台快照':'Server prices are a Nov 17 storefront snapshot'):(LANG==='zh'?'该服务器价格暂不可用':'Price unavailable for this server');
   [rs,fs,ss].forEach(x=>x.disabled=!!revealed);
  }
  document.getElementById('poe1Selector').style.display=curGame==='poe1'?'block':'none';
  document.getElementById('poeSelector').style.display=curGame==='poe2'?'block':'none';
  document.getElementById('poeLeague').disabled=true;if(curGame==='poe2')document.getElementById('poeLeague').value='Forbidden Rites';
  for(const id of ['wowRegion','wowFaction','wowRealm'])document.getElementById(id).disabled=curGame==='wow'&&!!revealed;
  document.getElementById('msResult').classList.toggle('d4-results',curGame==='d4');
  document.getElementById('fc27Platform').disabled=curGame==='fc27'&&(picked.length>0||!!revealed);
  if(revealed){ renderReveal(true); }
  else{
    $('#msResult').style.display='none';
    $('#msPool').style.display='grid';
    const g=gameItems();
    $('#msPool').innerHTML = g.items.length ? g.items.map((it,i)=>{
      const sel=picked.includes(i);
      return `<div class="pcard ${sel?'sel':''}" onclick="togglePick(${i})">
        <span class="pcheck">✓</span>
        <div class="picon">${fc27Art(it)}</div>
        <h4>${nm(it)}</h4>${marketItemNote(it)?`<div class="phint">${marketItemNote(it)}</div>`:''}
        <div class="pprice">${fc27Price(it)!==null?(it.fromPrice?(LANG==='zh'?'起价 ':'From '):'')+'$'+fc27Price(it).toFixed(2):((it.wowAmount||it.poeGoodsId)?(LANG==='zh'?'价格暂不可用':'PRICE PENDING'):it.snapshots?(LANG==='zh'?'价格待确认':'PRICE PENDING'):(LANG==='zh'?'价格暂不可用':'PRICE PENDING'))}</div>
      </div>`;
    }).join('') : `<div class="game-empty">${LANG==='zh'?'该游戏的活动商品待确认':'Event items for this game are coming soon.'}</div>`;
  }
  renderMsMeta(); renderMsActions();
}
/* 勾选/取消勾选商品（最多 3 件） */
function togglePick(i){
  if(revealed||msBusy) return;
  if(curGame==='aion2'&&!Number.isFinite(gameItems().items[i]?.price)){toast(LANG==='zh'?'该服务器价格暂不可用':'Server price unavailable');return;}
  syncMysteryCooldown();
  if(msDrawsLeft<=0){toast(t('noDraws'));return;}
  const idx=picked.indexOf(i);
  if(idx>=0) picked.splice(idx,1);
  else{
    if(picked.length>=CONFIG.mystery.pickCount){ toast(t('pickMax')); return; }
    picked.push(i);
  }
  renderMsZone();
}
/* 结果卡 HTML（open=true 直接翻开；false 保持背面等待动画） */
function revealCardHTML(r, open){
  const g=gameItems();
  return `<div class="fcard ${open?'open':''}">
    <div class="fcard-in">
      <div class="fface back"><div class="qm">%</div><div class="tap">${t('mysteryDeal')}</div></div>
      <div class="fface front">
        <div><div class="pgame">${nm(g)}</div><div class="picon">${fc27Art(r.it)}</div><h4>${nm(r.it)}</h4>${marketItemNote(r.it)?`<div class="phint">${marketItemNote(r.it)}</div>`:''}</div>
        <div class="rv-off off-${r.off}">${r.off}% OFF</div>
        <div class="price-row">${fc27Price(r.it)!==null?`<span class="old">${r.it.fromPrice?(LANG==='zh'?'起价 ':'From '):''}$${fc27Price(r.it).toFixed(2)}</span><span class="now">$${(fc27Price(r.it)*(1-r.off/100)).toFixed(2)}</span>`:`<span class="now">${r.it.snapshots?(LANG==='zh'?'价格待确认':'PRICE PENDING'):(LANG==='zh'?'价格暂不可用':'PRICE PENDING')}</span>`}</div>
        <button class="buybtn" onclick="event.stopPropagation();startMysteryPurchase(${revealed.indexOf(r)})">${t('buyNow')}</button>
      </div>
    </div>
  </div>`;
}
/* 渲染揭晓结果（静态=open 直接全部翻开，用于语言切换；动画版见 drawDeal） */
function renderReveal(open){
  $('#msPool').style.display='none';
  const res=$('#msResult'); res.style.display='grid';
  res.innerHTML = revealed.map(r=>revealCardHTML(r, open)).join('');
}
/* 抽取：3 件随机分配 15%/10%/8%（洗牌），翻卡动画逐张揭晓 */
function drawDeal(){
  if(msBusy||revealed) return;
  if(picked.length<CONFIG.mystery.pickCount){ toast(t('pickFirst')); return; }
  syncMysteryCooldown();
  if(msDrawsLeft<=0){ toast(t('noDraws')); return; }
  const roundDiscounts=mysteryRoundDiscounts(mysteryGameState().rounds===0);
  // Demo only: each selected product can independently receive 8%, 10% or 15%.
  // Production probabilities and secure drawing must be configured server-side.
  revealed = picked.map((pi,drawIndex)=>({ it:marketGames.includes(curGame)?{...gameItems().items[pi],marketChoice:marketSelections[curGame]}:curGame==='wow'?{...gameItems().items[pi],wowChoice:wowChoice()}:curGame==='poe2'?{...gameItems().items[pi],poeLeague:document.getElementById('poeLeague').value}:gameItems().items[pi], off:roundDiscounts[drawIndex] }));
  mysteryGameState().rounds++;
  saveMysteryResult();
  if(marketGames.includes(curGame))document.getElementById('marketChoiceSelect').disabled=true;if(curGame==='fc27')document.getElementById('fc27Platform').disabled=true;if(curGame==='wow')for(const id of ['wowRegion','wowFaction','wowRealm'])document.getElementById(id).disabled=true;if(curGame==='poe2')document.getElementById('poeLeague').disabled=true;
  // 渲染背面卡，逐张翻开
  $('#msPool').style.display='none';
  const res=$('#msResult'); res.style.display='grid';
  res.innerHTML = revealed.map(r=>revealCardHTML(r,false)).join('');
  renderMsMeta();
  msBusy=true;
  const cards=res.querySelectorAll('.fcard');
  setTimeout(()=>{ cards[0]?.classList.add('open'); },300);
  setTimeout(()=>{ cards[1]?.classList.add('open'); },1000);
  setTimeout(()=>{ cards[2]?.classList.add('open'); },1700);
  setTimeout(()=>{ msBusy=false; renderMsActions(); toast(t('revealDone')); },2400);
}
// Simulated purchase journey. This does not authenticate, issue real coupons or create orders.
let mysteryFlowResult=null, mysteryFlowGame='', mysteryDemoSignedIn=false, mysteryDemoSelection=null;
const mysteryFlowText=(zh,en)=>LANG==='zh'?zh:en;
function mysteryEscape(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function mysteryBox(html){$('#mysteryFlowContent').innerHTML=html;$('#mysteryFlowMask').classList.add('show');}
function closeMysteryFlow(){$('#mysteryFlowMask').classList.remove('show');}
function startMysteryPurchase(index){
 if(!revealed || !revealed[index])return;
 mysteryFlowResult=revealed[index];mysteryFlowGame=nm(gameItems());mysteryDemoSelection=null;
 if(!mysteryDemoSignedIn){showMysteryDemoLogin();return;}
 showMysteryDemoCoupon();
}
function showMysteryDemoLogin(){
 mysteryBox(`<div class="mystery-flow-label">${mysteryFlowText('登录','SIGN IN')}</div><h3 id="mysteryFlowTitle">${mysteryFlowText('登录后领取商品优惠券','Sign in to receive your coupon')}</h3><p>${mysteryFlowText('登录后，所抽折扣对应的优惠券将发放至你的账户。','Sign in to receive the coupon for your selected item.')}</p><p class="mystery-flow-disclaimer">${mysteryFlowText('当前为测试流程，使用演示账号，不会登录真实账户。','Preview only: use a demo account; no real sign-in.')}</p><button class="buybtn" onclick="closeMysteryFlow();document.getElementById('loginRequiredMask').classList.add('show')">${mysteryFlowText('登录 / 注册','SIGN IN / REGISTER')}</button><button class="btn-ghost coupon-close flow-back" onclick="closeMysteryFlow()">${mysteryFlowText('关闭','Close')}</button>`);
}

function showMysteryDemoCoupon(){
 if(!mysteryFlowResult||!mysteryDemoSignedIn)return;
 const r=mysteryFlowResult;
 mysteryBox(`<div class="mystery-flow-label">${mysteryFlowText('商品专属优惠券','ITEM COUPON')}</div><h3 id="mysteryFlowTitle">${mysteryFlowText('恭喜获得专属优惠','Your item discount is ready')}</h3>${couponCard({amount:r.off+'% OFF',description:mysteryFlowText('适用于选中的商品：','For selected item: ')+nm(r.it)+(r.it.fixedRealm?' · '+r.it.fixedRealm:r.it.wowChoice?' · '+Object.values(r.it.wowChoice).join(' / '):r.it.poeLeague?' · '+r.it.poeLeague:''),minText:mysteryFlowText('适用条件以结算为准','Subject to checkout terms')})}<p class="mystery-flow-disclaimer">${mysteryFlowText('演示优惠券；真实领取和支付需接入接口。','Demo coupon; actual issuance and payment require integration.')}</p>${r.it.fixedRealm?`<p class="mystery-flow-disclaimer">${mysteryFlowText('正式购买需要接入接口以锁定 Season 15 Softcore，当前为演示。','Live checkout integration is required to lock Season 15 Softcore. Preview only.')}</p>`:(r.it.modelId||r.it.storeUrl)?`<p class="mystery-flow-disclaimer">${mysteryFlowText('跳转至 MMOEXP 商品列表，需自行选择商品和平台；当前不会发放真实优惠券。','Opens the MMOEXP product listing. Select the item and platform there; no real coupon is issued yet.')}</p><a class="buybtn store-link" href="${r.it.storeUrl|| (r.it.modelId==='41217957'?'https://www.mmoexp.com/Fc-27/Coins.html':'https://www.mmoexp.com/Fc-27/Players.html')}" target="_blank" rel="noopener noreferrer">${mysteryFlowText('查看商品','VIEW PRODUCT')}</a>`:''}<button class="buybtn demo-checkout" onclick="claimMysteryDemoAndCheckout()">${mysteryFlowText('领取并购买','CLAIM & BUY')}</button><button class="btn-ghost coupon-close flow-back" onclick="closeMysteryFlow()">${mysteryFlowText('暂不购买','Not now')}</button>`);
}
function claimMysteryDemoAndCheckout(){
 if(!mysteryFlowResult||!mysteryDemoSignedIn)return;
 // Integration point: authenticate, issue a product-bound coupon, obtain a server quote and checkout URL.
 // Until those APIs exist this function is a local simulation and issues no coupon or order.
 mysteryDemoSelection={couponClaimed:true,couponApplied:false};
 showMysteryDemoCheckout();
}
function showMysteryDemoCheckout(){
 if(!mysteryFlowResult||!mysteryDemoSelection?.couponClaimed)return;
 const r=mysteryFlowResult,price=fc27Price(r.it),hasPrice=price!==null;
 const platform={ps:'PlayStation 4 | 5',xbox:'Xbox One | X | S',pc:'PC'}[document.getElementById('fc27Platform').value]||'';
 const platformInfo=r.it.marketChoice?'<p>'+mysteryFlowText('平台 / 服务器','Platform / Server')+': '+mysteryEscape(r.it.marketChoice)+'</p>':r.it.poeLeague?'<p>'+mysteryFlowText('赛季','League')+': '+mysteryEscape(r.it.poeLeague)+'</p>':r.it.wowChoice?'<p>'+mysteryFlowText('服务器','Server')+': '+mysteryEscape(Object.values(r.it.wowChoice).join(' / '))+'</p>':r.it.fixedRealm?'<p>'+mysteryFlowText('固定赛季','Fixed realm')+': '+mysteryEscape(r.it.fixedRealm)+'</p>':r.it.snapshots?'<p>'+mysteryFlowText('平台','Platform')+': '+mysteryEscape(platform)+'</p>':'';
 mysteryBox(`<div class="mystery-flow-label">${mysteryFlowText('确认订单','CHECKOUT')}</div><h3 id="mysteryFlowTitle">${mysteryFlowText('确认订单','Review your order')}</h3><div class="mystery-flow-box"><p>${mysteryEscape(mysteryFlowGame)} · ${mysteryEscape(nm(r.it))}</p>${platformInfo}<p>${mysteryFlowText('商品价格','Item price')}: ${hasPrice?(r.it.fromPrice?mysteryFlowText('起价 ','From '):'')+'$'+price.toFixed(2):mysteryFlowText('价格暂不可用','Price unavailable')}</p><label class="checkout-demo-coupon">${couponCard({amount:r.off+'% OFF',description:mysteryFlowText('指定商品优惠券','Selected-item coupon'),minText:mysteryFlowText('适用条件以结算为准','Subject to checkout terms')})}<input id="mysteryApplyCoupon" type="checkbox" onchange="updateMysteryDemoTotal()"> ${mysteryFlowText('使用优惠券','Apply coupon')}</label><p>${mysteryFlowText('预计应付','Estimated total')}</p><div class="mystery-flow-total" id="mysteryDemoTotal">${hasPrice?(r.it.fromPrice?mysteryFlowText('起价 ','From '):'')+'$'+price.toFixed(2):mysteryFlowText('待计算','Pending')}</div></div><p class="mystery-flow-disclaimer">${mysteryFlowText('这是支付流程预览，价格为后台快照；优惠券、订单和付款尚未接入。','Checkout preview only. Prices are snapshots; coupon issuance, orders and payment are not connected.')}</p><button class="buybtn" onclick="mysteryDemoPaymentUnavailable()">${mysteryFlowText('确认付款','CONFIRM PAYMENT')}</button><button class="btn-ghost coupon-close flow-back" onclick="showMysteryDemoCoupon()">${mysteryFlowText('返回优惠券','Back to coupon')}</button>`);
}
function updateMysteryDemoTotal(){
 if(!mysteryFlowResult||!mysteryDemoSelection)return;
 const price=fc27Price(mysteryFlowResult.it),applied=$('#mysteryApplyCoupon').checked;
 mysteryDemoSelection.couponApplied=applied;
 $('#mysteryDemoTotal').textContent=price===null?mysteryFlowText('待计算','Pending'):(mysteryFlowResult.it.fromPrice?mysteryFlowText('起价 ','From '):'')+'$'+(price*(applied?1-mysteryFlowResult.off/100:1)).toFixed(2);
}
function mysteryDemoPaymentUnavailable(){
 if(!mysteryFlowResult||!mysteryGameState().pending)return;
 mysteryGameState().pending=null;persistMysteryProgress();
 picked=[];revealed=null;syncMysteryCooldown();renderMsZone();tickMs();
 mysteryBox(`<div class="mystery-flow-label">${mysteryFlowText('支付完成','PAYMENT COMPLETE')}</div><h3 id="mysteryFlowTitle">${mysteryFlowText('已解锁下一次翻牌','Your next draw is unlocked')}</h3><p>${mysteryFlowText('当前游戏已解锁下一次翻牌。','The next draw for this game is unlocked.')}</p><p class="mystery-flow-disclaimer">${mysteryFlowText('未产生真实付款或订单。正式上线需接入支付成功通知和订单校验。','No real payment or order was created. Live use requires verified payment and order integration.')}</p><button class="buybtn" onclick="closeMysteryFlow()">${mysteryFlowText('继续翻牌','CONTINUE')}</button>`);

}$('#mysteryFlowMask').addEventListener('click',e=>{if(e.target.id==='mysteryFlowMask')closeMysteryFlow();});
function resetMysteryDemo(){
 if(msBusy)return;
 delete msProgress[curGame];persistMysteryProgress();picked=[];revealed=null;syncMysteryCooldown();renderMsZone();tickMs();
}
function tickMs(){
 syncMysteryCooldown();
 $('#msTimer').textContent=msDrawsLeft?(LANG==='zh'?'可以翻牌':'READY'):(LANG==='zh'?'支付本轮商品后解锁':'UNLOCK AFTER PAYMENT');
}

restoreMysteryResult(); renderTabs(); renderMsZone();
tickMs(); setInterval(tickMs,1000);

/* ================= Act 2: Flash Sale ================= */
function currentFlashSession(){const live=CONFIG.flash.sessions.findIndex(x=>phaseStatus(x).k==='live');if(live>=0)return live;const next=CONFIG.flash.sessions.findIndex(x=>phaseStatus(x).k==='soon');return next>=0?next:CONFIG.flash.sessions.length-1;}
let curSess=currentFlashSession();
let flashCategory='currency';
let flashFc27Platform='ps';
const flashSelections={wow:{region:'US',faction:'Alliance',realm:'Normal'},maple:{region:'Global',realm:'Windia'},arc:{platform:'PC'}};
function flashSelectionChanged(game,key,value){
 const c=flashSelections[game];if(!c||!(key in c))return;c[key]=value;
 if(game==='wow'&&c.region==='Asia'&&!['Normal','PVP'].includes(c.realm))c.realm='Normal';
 renderFlash();
}
function flashSelect(game,key,values,current){return '<select aria-label="'+key+'" onchange="flashSelectionChanged(\''+game+'\',\''+key+'\',this.value)">'+values.map(([v,label])=>'<option value="'+v+'"'+(v===current?' selected':'')+'>'+label+'</option>').join('')+'</select>'}
function setFlashFc27Platform(value){if(['ps','xbox','pc'].includes(value)){flashFc27Platform=value;renderFlash();}}
function flashItemCategory(it){ if(it.category) return it.category; if(it.type==='coupon') return it.coupon.off.startsWith('$')?'voucher':'other'; return /coins|gold|kinah|mesos/i.test(it.name)?'currency':'items'; }
function selectFlashCategory(category){flashCategory=category;renderFlash();$('#flashGrid').scrollLeft=0;}
let earlyAccess = false; // This preview cannot verify issued coupons without the website API.
function renderSessTabs(){
 const zh=LANG==='zh', day=Math.floor(curSess/2);
 const dates=zh?['11月27日','11月28日','11月29日','11月30日','12月1日']:['NOV 27','NOV 28','NOV 29','NOV 30','DEC 1'];
 const days=dates.map((date,i)=>'<button type="button" class="stab day-tab '+(day===i?'on':'')+'" onclick="selectFlashDay('+i+')">'+(zh?'第 '+(i+1)+' 天':'DAY '+(i+1))+'<small>'+date+'</small></button>').join('');
 const times=[['12:00','16:00'],['19:00','23:00']].map(([start,end],i)=>{
  const index=day*2+i,st=phaseStatus(CONFIG.flash.sessions[index]);
  return '<button type="button" class="flash-time '+(index===curSess?'on':'')+'" onclick="selSess('+index+')"><span>'+start+'–'+end+' ET</span><small>'+st.label+'</small></button>';
 }).join('');
 $('#sessTabs').innerHTML='<div class="flash-day-row">'+days+'</div><div class="flash-time-row"><span class="flash-time-title">'+(zh?'每日场次':'DAILY SESSIONS')+'</span>'+times+'</div>';
}
function selectFlashDay(day){
 const indices=[day*2,day*2+1];
 const index=indices.find(i=>phaseStatus(CONFIG.flash.sessions[i]).k==='live')??indices.find(i=>phaseStatus(CONFIG.flash.sessions[i]).k==='soon')??indices[1];
 selSess(index);
}
function selSess(i){ curSess=i; renderSessTabs(); renderFlash(); $('#flashGrid').scrollLeft=0; }
function syncFlashScroll(){
 const grid=$('#flashGrid'), bar=$('#flashScrollBar');
 if(!grid||!bar)return;
 const max=Math.max(0,grid.scrollWidth-grid.clientWidth);
 bar.disabled=max<2;
 bar.value=max?Math.round(grid.scrollLeft/max*1000):0;
 bar.style.setProperty('--progress',`${bar.value/10}%`);
 bar.setAttribute('aria-label',LANG==='zh'?'横向浏览秒杀商品':'Scroll flash sale products horizontally');
}
$('#flashScrollBar').addEventListener('input',function(){
 const grid=$('#flashGrid'), max=Math.max(0,grid.scrollWidth-grid.clientWidth);
 grid.scrollLeft=max*(Number(this.value)/1000);
 this.style.setProperty('--progress',`${this.value/10}%`);
});
$('#flashGrid').addEventListener('scroll',syncFlashScroll,{passive:true});
{
 const grid=$('#flashGrid');let drag=null;
 grid.addEventListener('pointerdown',e=>{if(e.pointerType!=='mouse'||e.button!==0||e.target.closest('select,option,button,input,a'))return;drag={id:e.pointerId,x:e.clientX,left:grid.scrollLeft,moved:false};grid.setPointerCapture(e.pointerId);});
 grid.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const delta=e.clientX-drag.x;if(Math.abs(delta)>3){drag.moved=true;grid.classList.add('dragging');grid.scrollLeft=drag.left-delta;}});
 const end=e=>{if(!drag||drag.id!==e.pointerId)return;grid.classList.remove('dragging');if(grid.hasPointerCapture(e.pointerId))grid.releasePointerCapture(e.pointerId);drag=null;};
 grid.addEventListener('pointerup',end);grid.addEventListener('pointercancel',end);
}
window.addEventListener('resize',syncFlashScroll,{passive:true});
if(typeof ResizeObserver!=='undefined') new ResizeObserver(syncFlashScroll).observe($('#flashGrid'));
function couponCard({amount,description,minText,actionText='',disabled=false,action='',extraClass=''}){
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 return `<div class="unified-coupon ${extraClass}"><div class="uc-side"><span class="uc-gift" aria-hidden="true">🎁</span><span class="uc-min">${esc(minText)}</span></div><div class="uc-main"><strong class="uc-amount">${esc(amount)}</strong><span class="uc-desc">${esc(description)}</span>${actionText?`<button class="uc-action" ${disabled?'disabled':''} ${action?`onclick="${action}"`:''}>${esc(actionText)}</button>`:''}</div></div>`;
}

function renderFlash(){
  const s=CONFIG.flash.sessions[curSess],st=phaseStatus(s),locked=st.k!=='live';
  const savedScroll=$('#flashGrid').scrollLeft;
  $('#sessCdLbl').textContent=st.k==='live'?t('sessEnds'):st.k==='soon'?t('sessStarts'):t('sessOver');
  document.querySelectorAll('.store-categories button').forEach(b=>{const on=b.dataset.category===flashCategory;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));});
  $('#flashGrid').classList.toggle('four-currency',flashCategory==='currency'||flashCategory==='items'||flashCategory==='voucher');
  $('#sessCdLbl').textContent=st.k==='live'?t('sessEnds'):st.k==='soon'?t('sessStarts'):t('sessOver');
  document.querySelectorAll('.store-categories button').forEach(b=>{const on=b.dataset.category===flashCategory;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));});
  if(st.k==='soon'){ const zh=LANG==='zh'; $('#flashGrid').innerHTML=Array.from({length:4},()=>'<div class="fitem mystery-flash"><div class="mystery-flash-icon" aria-hidden="true">?</div><strong>'+(zh?'神秘特惠':'MYSTERY DEAL')+'</strong><span>'+(zh?'本场开始后揭晓':'Revealed when the session starts')+'</span><button class="buybtn" disabled>'+(zh?'未开始':'NOT STARTED')+'</button></div>').join('');return; }
  $('#flashGrid').innerHTML=s.items.map((it,idx)=>({it,idx})).filter(x=>flashItemCategory(x.it)===flashCategory).map(({it,idx})=>{
    if(it.type==='coupon'){
      const cp=it.coupon;
      return `<div class="fitem fitem-coupon"><div class="off-badge">${t('couponTag')}</div><div class="fgame">${t('couponGame')}</div>${couponCard({amount:LANG==='zh'?cp.offZh:cp.off,description:LANG==='zh'?'黑五专属优惠券':'Black Friday exclusive coupon',minText:LANG==='zh'?cp.noteZh:cp.note})}<button class="buybtn" ${locked?'disabled':''} onclick="claimFlashCoupon(${curSess},${idx})">${LANG==='zh'?'免费抢':'CLAIM FREE'}</button></div>`;
    }
    if(it.modelItemSnapshot){
      const zh=LANG==='zh', source=CONFIG.mystery.games.find(g=>g.id===it.sourceGame)?.items.find(x=>x.name===it.sourceName);
      const img=source?fc27Art(source):'🎮';
      const discounted=Math.round((it.price*(100-it.discountPercent)+Number.EPSILON))/100;
      const opts=[['ps','PlayStation 4|5'],['xbox','Xbox One|X|S'],['pc','PC']].map(([value,label])=>`<option value="${value}" ${flashFc27Platform===value?'selected':''}>${label}</option>`).join('');
      const scope=it.sourceGame==='fc27'?`<label class="flash-platform-label">${zh?'平台':'PLATFORM'}<select aria-label="${zh?'选择 FC 27 平台':'Select FC 27 platform'}" onchange="setFlashFc27Platform(this.value)">${opts}</select></label>`:`<span class="flash-fixed-scope">${it.scope}</span>`;
      const note=it.sourceGame==='fc27'?(zh?'模型价 · 平台报价待确认':'PRICE TO BE CONFIRMED'):(zh?'模型价格快照 · 11月16日':'MODEL SNAPSHOT · NOV 16');
      return `<div class="fitem flash-real flash-item-model"><div class="off-badge">-${it.discountPercent}%</div><div class="fgame">${it.game}</div><div class="ficon flash-coin-art">${img}</div><h4>${it.name}</h4><div class="flash-choice">${scope}</div><div class="fprice"><span class="now">$${discounted.toFixed(2)}</span><span class="old">$${it.price.toFixed(2)}</span></div><div class="flash-price-note">${note}</div><button class="buybtn" ${locked?'disabled':''} onclick="previewFlashPurchase(${curSess},${idx})">${locked?(st.k==='soon'?t('notStarted'):t('over')):t('grab')}</button></div>`;
    }
    if(it.verifiedSnapshot){
      const sel=flashSelections[it.gameKey], zh=LANG==='zh'; let price=null, controls='', date='NOV 14';
      if(it.gameKey==='wow'){
        const regions=[['US','US'],['EU','EU'],['Asia','Asia'],['KR','KR']];
        controls=flashSelect('wow','region',regions,sel.region);
        {
          const entry=WOW_PRICE_SNAPSHOT[sel.region]?.[sel.faction]?.[sel.realm];
          if(sel.region==='US'&&sel.faction==='Alliance'&&sel.realm==='Normal'){price=18.04;date='NOV 14';}
          else {if(entry)price=Math.round((entry[1]*it.amount+Number.EPSILON)*100)/100;date='NOV 13';}
          controls+=flashSelect('wow','faction',[['Alliance','Alliance'],['Horde','Horde']],sel.faction);
          const realms=sel.region==='Asia'?['Normal','PVP']:['Normal','PVP','Roleplay','Roleplay-PVP'];
          controls+=flashSelect('wow','realm',realms.map(v=>[v,v]),sel.realm);
        }
      }else if(it.gameKey==='maple'){
        price=it.old;controls='<span class="flash-fixed-scope">Global · Windia</span>';
      }else if(it.gameKey==='arc'){
        controls='<label class="flash-platform-label">'+(zh?'平台':'PLATFORM')+flashSelect('arc','platform',[['PC','PC'],['PS','PS'],['XBOX','XBOX']],sel.platform)+'</label>';
        price=({PC:11.34,PS:11.34,XBOX:11.34})[sel.platform]??null;
      }
      const discounted=price===null?null:Math.round((price*(100-it.discountPercent)+Number.EPSILON))/100;
      const game=CONFIG.mystery.games.find(g=>g.id===it.gameKey);
      const source=game?.items?.find(x=>x.name===it.name)||game?.items?.find(x=>x.image);
      const img=source?.image?`<img src="${source.image}" alt="" loading="lazy">`:it.icon;
      const prices=price===null?`<div class="flash-pending">${zh?'价格待核对':'PRICE PENDING'}</div>`:`<div class="fprice"><span class="now">$${discounted.toFixed(2)}</span><span class="old">$${price.toFixed(2)}</span></div>`;
      return `<div class="fitem flash-real"><div class="off-badge">-${it.discountPercent}%</div><div class="fgame">${it.game}</div><div class="ficon flash-coin-art">${img}</div><h4>${it.name}</h4><div class="flash-choice">${controls}</div>${prices}<div class="flash-price-note">${price===null?(zh?'该选项报价待核对':'QUOTE NOT VERIFIED'):(zh?'模型价格快照 · ':'MODEL SNAPSHOT · ')+date}</div><button class="buybtn" ${locked||price===null?'disabled':''} onclick="previewFlashPurchase(${curSess},${idx})">${price===null?(zh?'价格待核对':'PRICE PENDING'):locked?(st.k==='soon'?t('notStarted'):t('over')):t('grab')}</button></div>`;
    }
    if(it.modelSnapshot){
      const price=it.priceSnapshot[flashFc27Platform], discounted=Math.round(price*(100-it.discountPercent))/100;
      const opts=[['ps','PlayStation 4|5'],['xbox','Xbox One|X|S'],['pc','PC']].map(([value,label])=>`<option value="${value}" ${flashFc27Platform===value?'selected':''}>${label}</option>`).join('');
      return `<div class="fitem flash-real"><div class="off-badge">-${it.discountPercent}%</div><div class="fgame">${it.game}</div><div class="ficon flash-coin-art"><img src="${fc27GeneratedCoin}" alt="" loading="lazy"></div><h4>${nm(it)}</h4><label class="flash-platform-label">${LANG==='zh'?'平台':'PLATFORM'}<select aria-label="${LANG==='zh'?'选择 FC 27 平台':'Select FC 27 platform'}" onchange="setFlashFc27Platform(this.value)">${opts}</select></label><div class="fprice"><span class="now">$${discounted.toFixed(2)}</span><span class="old">$${price.toFixed(2)}</span></div><div class="flash-price-note">${LANG==='zh'?'模型快照 · 11月13日':'MODEL SNAPSHOT · NOV 13'}</div><button class="buybtn" ${locked?'disabled':''} onclick="previewFlashPurchase(${curSess},${idx})">${locked?(st.k==='soon'?t('notStarted'):t('over')):t('grab')}</button></div>`;
    }
    const pct=Math.round((1-it.now/it.old)*100);
    return `<div class="fitem"><div class="off-badge">-${pct}%</div><div class="fgame">${it.game}</div><div class="ficon">${it.icon}</div><h4>${nm(it)}</h4><div class="fprice"><span class="now">$${it.now.toFixed(2)}</span><span class="old">$${it.old.toFixed(2)}</span></div><button class="buybtn" ${locked?'disabled':''} onclick="previewFlashPurchase(${curSess},${idx})">${locked?(st.k==='soon'?t('notStarted'):t('over')):t('grab')}</button></div>`;
  }).join('')||`<div class="flash-empty">${LANG==='zh'?'本场该分类商品待配置':'Products for this category are to be announced.'}</div>`;
  $('#flashGrid').scrollLeft=savedScroll;
  requestAnimationFrame(syncFlashScroll);
}
function previewFlashPurchase(si,ii){
  const it=CONFIG.flash.sessions[si]?.items[ii];if(!it)return;
  if(!getAuthenticatedCouponUser()){ $('#loginRequiredMask').classList.add('show');return; }
  toast(LANG==='zh'?'暂时无法继续购买':'Purchase is currently unavailable.');
}
function claimFlashCoupon(si,ii){previewFlashPurchase(si,ii);}
let lastSessionTick=null, lastLiveFlashSession=CONFIG.flash.sessions.findIndex(x=>phaseStatus(x).k==='live');
function tickSess(){
 const live=CONFIG.flash.sessions.findIndex(x=>phaseStatus(x).k==='live');
 if(live>=0 && live!==lastLiveFlashSession){curSess=live;renderSessTabs();renderFlash();}
 lastLiveFlashSession=live;
 let session=CONFIG.flash.sessions[curSess], status=phaseStatus(session);
 if(lastSessionTick && (lastSessionTick.index!==curSess || lastSessionTick.status!==status.k)){renderSessTabs();renderFlash();}
 lastSessionTick={index:curSess,status:status.k};
 $('#sessCd').textContent=status.k==='over'?t('ended'):fmtDur(new Date(status.k==='live'?session.end:session.start)-now());
}

renderSessTabs(); renderFlash();
tickSess(); setInterval(tickSess,1000);

/* ================= Act 3: Gacha ================= */
let drawCount = 0;
const ballColors=['#ffb84d','#7c5cff','#35e0ff','#ff5c7a','#3ddc97','#ff8a3d'];
function renderGlobe(){
  const g=$('#globe'); g.innerHTML='';
  // 球的数量 = 我的奖池剩余扭蛋数，抽中一颗少一颗
  const n=CONFIG.gacha.prizes.reduce((sum,p)=>sum+p.left,0); // Match the remaining prize pool.
  const size = 44;   // 球少时放大，球多时略小避免过度重叠
  for(let i=0;i<n;i++){
    const b=document.createElement('div'); b.className='ball';
    b.style.width=b.style.height=size+'px';
    b.style.setProperty('--egg-color',ballColors[i%ballColors.length]);
    const positions=[[14,59],[38,67],[64,57],[26,36],[56,33],[42,12]]; const [x,y]=positions[i%positions.length]; b.style.left=x+'%'; b.style.top=y+'%'; b.style.setProperty('--delay',(-i*.11)+'s');
    g.appendChild(b);
  }
}
function renderPool(){
  const totalLeft=CONFIG.gacha.prizes.reduce((a,p)=>a+p.left,0);
  // 奖池公开展示所有真实奖励，2 列网格；抽走后划线+标注"已抽走"
  $('#pool').innerHTML=CONFIG.gacha.prizes.map(p=>'<div class="pitem '+(p.left<=0?'gone':'')+'">'+couponCard({amount:(p.name.match(/\$[0-9]+/)||[''])[0]+' OFF',description:LANG==='zh'?'无门槛优惠券':'No-minimum coupon',minText:LANG==='zh'?'最低消费：$0.00':'Min. spend: $0.00'})+(p.left<=0?'<span class="pool-card-status">'+t('gone')+'</span>':'')+'</div>').join('');
  $('#poolLeft').textContent = totalLeft;
}
function renderPrice(){
  $('#drawPrice').innerHTML=t('drawFree')+'<small>'+t('drawFreeSub')+'</small>';
  // Available draws are calculated in refreshDrawState().
}
/* 已解锁抽数 = 累计订单金额达到门槛的个数 + 免费福利 */
let bonusDraws = 0;   // 免费领取的抽数（限 1 次）
let freeDrawn = false;// 免费抽是否已使用（用于让免费抽不占用消费解锁额度）
function drawsUnlocked(spend){
  return CONFIG.gacha.thresholds.filter(x=>spend>=x).length;
}
function renderFreeDraw(){
  const b=$('#freeDrawBtn');
  const claimed=bonusDraws>=1 || freeDrawn;
  const unavailable=!claimed && CONFIG.gacha.prizes.every(p=>p.left<=0);
  if(b){
    b.classList.toggle('claimed',claimed);
    b.disabled=claimed||unavailable;
    b.textContent=claimed?t('fdDone'):(unavailable?(LANG==='zh'?'奖池已抽完':'POOL CLEARED'):t('fdBtn'));
  }
}
function claimFreeDraw(){
  if(bonusDraws>=1 || freeDrawn || CONFIG.gacha.prizes.every(p=>p.left<=0)) return;
  bonusDraws=1;
  renderFreeDraw(); refreshDrawState();
  toast(t('fdToast'));
}
$('#freeDrawBtn').addEventListener('click',claimFreeDraw);

/* ---- 首屏钩子：提前开启黑五活动价（10% 折扣 + 提前解锁秒杀） ---- */
function renderEarlyBtn(){
  const hb=$('#heroEarlyBtn');
  if(!hb) return;
  const on = earlyAccess===true;
  hb.classList.toggle('claimed',on);
  hb.disabled=on;
  const speech=$('#couponSpeech');
  speech.textContent=on ? (LANG==='zh'?'10% 优惠券已领取':'10% COUPON CLAIMED') : (LANG==='zh'?'领取 10% 无门槛优惠券':'CLAIM 10% OFF COUPON');
  hb.setAttribute('aria-label',speech.textContent);
}
// Website login and coupon issuance are not connected in this local preview.
function getAuthenticatedCouponUser(){ return null; }
function openCoupon(){
 $('#couponMask').classList.add('show');
}
function closeCoupon(){ $('#couponMask').classList.remove('show'); }
function claimCoupon(){
 if(phaseStatus(CONFIG.events.tg).k!=='live'){closeCoupon();toast(LANG==='zh'?'活动未开始或已结束':'Event is not active');return;}
 if(!getAuthenticatedCouponUser()){closeCoupon();$('#loginRequiredMask').classList.add('show');return;}
 toast(t('couponPending'));
}
$('#heroEarlyBtn').addEventListener('click',()=>{if(!earlyAccess)openCoupon();});
$('#couponClaimBtn').addEventListener('click',claimCoupon);
$('#couponMask').addEventListener('click',e=>{if(e.target.id==='couponMask')closeCoupon();});
// Connect this button to the MMOEXP site's login dialog when integrating.
$('#loginRequiredGo').addEventListener('click',()=>toast(t('loginPending')));
$('#loginRequiredClose').addEventListener('click',()=>$('#loginRequiredMask').classList.remove('show'));
$('#loginRequiredMask').addEventListener('click',e=>{if(e.target.id==='loginRequiredMask')$('#loginRequiredMask').classList.remove('show');});
// The actual paid-order total is unavailable until an authenticated order API is integrated.
function getVerifiedOrderTotal(){ return null; }
function refreshDrawState(){
  const verifiedSpend=getVerifiedOrderTotal(), hasOrderData=Number.isFinite(verifiedSpend)&&verifiedSpend>=0;
  const spend=hasOrderData?verifiedSpend:0, th=CONFIG.gacha.thresholds;
  document.querySelector('.gacha-wrap .spend-foot').hidden=!hasOrderData;
  $('#spendVal').textContent=hasOrderData?'$'+spend.toFixed(2):'—';
  $('#spendRule').textContent=hasOrderData?t('spendRule')():(LANG==='zh'?'累计实付金额暂不可用':'Actual paid total is currently unavailable');
  const unlocked=drawsUnlocked(spend);   // 消费解锁的档位数
  // 已用消费抽次数 = 已抽总数 - 免费抽已用（免费抽只 1 次，不计入消费解锁额度）
  const paidDrawn = drawCount;
  // 可抽次数 = 消费解锁剩余 + 免费机会剩余
  let avail = Math.max(0, unlocked - paidDrawn);

  avail=Math.min(avail,CONFIG.gacha.prizes.reduce((sum,p)=>sum+p.left,0));
  $('#mCost').innerHTML=(LANG==='zh'?'我的可抽次数':'My available draws')+` <strong>${avail}</strong>`;
  renderFreeDraw();
  // 距下一档门槛的进度条（免费抽数不影响门槛进度）
  const thUnlocked=CONFIG.gacha.thresholds.filter(x=>spend>=x).length;
  const nextT=th[thUnlocked];
  // 进度条以最高门槛 $1000 为满格基准
  const maxT=th[th.length-1];
  const barPct=Math.min(100, Math.max(0, spend/maxT*100));
  $('#spendBarFill').style.width=barPct+'%';
  // 渲染里程碑格子（每个门槛一个格子，达成高亮）
  $('#spendMarks').innerHTML=th.map((v,i)=>{
    const hit=spend>=v;
    return `<span class="${hit?'hit':''}">$${v}</span>`;
  }).join('');
  if(!hasOrderData){
    $('#nextAt').textContent=LANG==='zh'?'订单数据接入后显示解锁进度':'Unlock progress will appear when order data is available';
  }else if(nextT===undefined){
    $('#nextAt').innerHTML=t('allUnlocked');
  }else{
    const prev=thUnlocked>0?th[thUnlocked-1]:0;
    $('#nextAt').innerHTML=t('nextAt')(thUnlocked+1, nextT);
  }
  const poolEmpty=CONFIG.gacha.prizes.every(p=>p.left<=0);
  $('#drawBtn').disabled = avail<=0 || poolEmpty;
  $('#drawBtn').textContent = poolEmpty?t('poolEmpty'):(avail<=0?(hasOrderData?t('spendMore'):(LANG==='zh'?'抽奖机会待解锁':'UNLOCK DRAWS WITH SPENDING')):t('draw'));
}
let gachaBusy=false;   // 抽奖动画进行中，防止连点
$('#drawBtn').addEventListener('click',()=>{
  if(gachaBusy) return;
  const actualSpend=getVerifiedOrderTotal();
  const unlocked=drawsUnlocked(Number.isFinite(actualSpend)&&actualSpend>=0?actualSpend:0);
  const win=CONFIG.gacha.prizes[drawCount];
  if(!win || win.left<=0) return;
  // 判断本次抽奖资格：
  // 1) 有免费机会 → 用免费机会抽（不扣消费解锁数）
  // 2) 否则需消费解锁数足够（消费抽次数 < unlocked）
  const useFree = false;
  if(useFree){
    bonusDraws--;                 // 消耗免费机会
    freeDrawn=true;
    renderFreeDraw();
  }else{
    const paidDrawn = drawCount - (freeDrawn ? 1 : 0);
    if(unlocked<=paidDrawn){
      return;                     // 消费未达标，拦截
    }
  }

  // —— 摇一摇 + 掉落动画 ——
  gachaBusy=true;
  $('#drawBtn').disabled=true;
  const machine=$('#machine');
  $('#mScreen').textContent=t('mShaking');
  machine.classList.add('shaking');
  setTimeout(()=>{
    machine.classList.remove('shaking');
    win.left--; drawCount++;
    renderGlobe(); renderPool(); renderPrice(); refreshDrawState();
    // 掉落一颗蛋到出口
    $('#mScreen').textContent=t('mDrop');
    const egg=document.createElement('div');
    egg.className='drop-egg';
    egg.style.background=`radial-gradient(circle at 30% 30%,rgba(255,255,255,.7),${ballColors[(drawCount-1)%ballColors.length]})`;
    $('#mOut').appendChild(egg);
    $('#mOut').classList.add('pop');
    setTimeout(()=>{
      egg.remove(); $('#mOut').classList.remove('pop');
      $('#mScreen').textContent=t('mIdle');
      // 展示中奖结果
      $('#mIcon').style.display='none';
      $('#gachaCoupon').innerHTML=couponCard({amount:(win.name.match(/\$[0-9]+/)||[''])[0]+' OFF',description:LANG==='zh'?'无门槛优惠券':'No-minimum coupon',minText:LANG==='zh'?'最低消费：$0.00':'Min. spend: $0.00'});
      $('#mTitle').textContent=t('youWon')(nm(win));
      $('#mDesc').textContent=useFree?t('winDescFree')():t('winDesc')(drawCount);
      $('#modalMask').classList.add('show');
      gachaBusy=false;
      refreshDrawState();
    }, 1200);
  }, 1800);
});
function closeModal(){ $('#modalMask').classList.remove('show'); }
$('#modalMask').addEventListener('click',e=>{ if(e.target.id==='modalMask') closeModal(); });

/* ================= Act 3 搭配: 游戏专属折扣码 ================= */
const exclusiveArt={"madden":"assets/carnival-f775d2300f2f.webp","cfb":"assets/carnival-96fa27f06814.webp","mlb":"assets/carnival-e7f94de3cacd.webp","monopoly":"assets/carnival-3ef015010f32.webp","arena":"assets/carnival-4fb4e493b2e0.webp"};
function renderCodes(){
 $('#codesGrid').innerHTML=CONFIG.gameCodes.map((c,i)=>{
  const ready=Boolean(c.code && c.code.trim());
  const offer=LANG==='zh'?'专属 '+(100-c.discount)/10+' 折优惠':'EXCLUSIVE '+c.discount+'% OFF';
  const code=ready?c.code:(LANG==='zh'?'折扣码待配置':'CODE COMING SOON');
  return `<article class="ccode exclusive-game exclusive-${c.theme}">
    <div class="exclusive-art"><img src="${exclusiveArt[c.theme]}" alt="" loading="lazy"></div><h4 class="exclusive-title">${c.game}</h4>
    <div class="exclusive-offer">${offer}</div>
    <div class="exclusive-code ${ready?'':'is-pending'}">${code}</div>
    <button class="exclusive-shop" onclick="copyGameCodeAndShop(${i})" ${ready?'':'disabled'}>${LANG==='zh'?'复制并购买 →':'COPY & SHOP →'}</button>
  </article>`;
 }).join('');
}
async function copyGameCodeAndShop(i){
 if(phaseStatus(CONFIG.events.tg).k!=='live'){toast(LANG==='zh'?'活动未开始或已结束':'Event is not active');return;}
 const c=CONFIG.gameCodes[i];if(!c||!c.code||!c.code.trim())return;
 let copied=false;try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(c.code);copied=true;}}catch(e){}
 if(!copied){const el=document.createElement('textarea');el.value=c.code;el.style.cssText='position:fixed;left:-9999px;top:0';document.body.appendChild(el);el.select();try{copied=document.execCommand('copy')}catch(e){}el.remove()}
 if(copied)window.location.href=c.url;else toast(LANG==='zh'?'复制失败，请手动复制折扣码。':'Unable to copy. Please copy the code manually.');
}
/* ================= i18n apply / switch ================= */

/* Concise bilingual rules, grouped by activity. */
function renderEventRules(){
 const zh=LANG==='zh';
 const entries=zh?[
  '<b>活动时间：</b>2026年11月19日 00:00 至 12月2日 00:00，均为美东时间 ET（UTC-5）。',
  '活动期间，注册用户可在首页领取一张各游戏通用的 10% OFF 无门槛优惠券，每人限领一次。请于 12月2日 00:00 前使用，逾期失效；不可与其他优惠券或折扣码叠加。',
  '<b>感恩节神秘商店：</b>11月19日 00:00 至 12月2日 00:00 开放。选择游戏，从该游戏的 9 件商品中选择 3 件并随机抽取折扣，三件均可购买。<br><b>翻牌机会：</b>各游戏独立计算。本轮任意一件商品支付成功后，解锁该游戏下一次翻牌。',
  '<b>黑色星期五秒杀商店：</b>11月27日 00:00 至 12月2日 00:00 开放，11月27日至12月1日每天两场，时间为 12:00–16:00 和 19:00–23:00（美东时间 ET，UTC-5），提供金币、道具及优惠券，具体优惠以当场展示为准。黑五专属优惠券请于领取当日 23:59:59（美东时间 ET）前使用，逾期失效；不可与其他优惠券或折扣码叠加。',
  '<b>网络星期一扭蛋机：</b>11月30日 00:00 至 12月2日 00:00 开放。登录用户可查看 2026 年 11 月 19 日 00:00 至 12 月 2 日 00:00（美东时间 ET）期间的累计订单金额，以实际支付金额为准；累计达到对应门槛后获得抽奖次数。<br><b>扭蛋奖励：</b>奖池不重置，奖励顺位越高越丰厚，每抽一次移除一颗球。抽取的无门槛优惠券请于 12月2日 00:00 前使用，逾期失效；不可与其他优惠券或折扣码叠加。',
  '<b>游戏专属折扣码：</b>11月19日 00:00 至 12月2日 00:00 活动期间领取，可多次使用，须在 12月2日 00:00 前使用；不可与其他折扣码或优惠券叠加。'
 ]:[
  '<b>Event dates:</b> November 19, 2026, 00:00 to December 2, 00:00. All times are Eastern Time (ET, UTC-5).',
  'During the event, registered users may claim one 10% OFF no-minimum coupon valid across games, limited to one per user. Use it before December 2, 00:00 ET; it expires thereafter and cannot be combined with other coupons or discount codes.',
  '<b>Thanksgiving Mystery Shop:</b> Open November 19, 00:00 to December 2, 00:00. Choose a game and select 3 of its 9 products to reveal random discounts; all 3 may be purchased.<br><b>Draw eligibility:</b> Each game is independent. Successfully pay for any one product from this round to unlock the next draw for that game.',
  '<b>Black Friday Flash Sale:</b> Open November 27, 00:00 to December 2, 00:00, with two daily sessions from November 27 to December 1, 12:00–16:00 and 19:00–23:00 Eastern Time (ET, UTC-5). Currency, items and coupons are available; see each session for offers. Black Friday coupons must be used by 23:59:59 ET on the day they are claimed; they expire thereafter. They cannot be combined with other coupons or discount codes.',
  '<b>Cyber Monday Gacha:</b> Open November 30, 00:00 to December 2, 00:00. Signed-in users can view their cumulative order amount from November 19, 2026, 00:00 to December 2, 2026, 00:00 ET, based on the amount actually paid. Reaching the thresholds unlocks draws.<br><b>Gacha rewards:</b> The pool does not reset, later rewards are more valuable, and each draw removes one capsule. No-minimum coupons won must be used before December 2, 00:00 ET; they expire thereafter and cannot be combined with other coupons or discount codes.',
  '<b>Game-exclusive discount codes:</b> Claim from November 19, 00:00 to December 2, 00:00 ET. Codes can be used multiple times before December 2, 00:00 ET, and cannot be combined with other discount codes or coupons.'
 ];
 $('#rulesList').innerHTML=`<ol class="rules-numbered">${entries.map((v,i)=>`<li><span class="rule-index">${i+1}</span><div>${v}</div></li>`).join('')}</ol>`;
}

function applyLang(){
  document.documentElement.lang = LANG==='zh'?'zh-CN':'en';
  document.body.classList.toggle('zh', LANG==='zh');
  $$('[data-i18n]').forEach(el=>{ const v=T[LANG][el.dataset.i18n]; if(typeof v==='string') el.innerHTML=v; });
  renderEventRules();
  // re-render dynamic zones
  renderMascot();
  renderTabs(); renderMsZone();
  renderSessTabs(); renderFlash();
  renderGlobe(); renderPool(); renderPrice(); refreshDrawState();
  renderFreeDraw();
  renderEarlyBtn();
  renderCodes();
  tickMs(); tickSess();
}
function setLang(l){ LANG=l; store.set('carnival-lang',l); applyLang(); }

renderGlobe(); renderPool(); renderPrice(); refreshDrawState();
applyLang();

/* subtle globe ball wobble */
const gachaStage=document.querySelector('.gacha-art-stage');
gachaStage.addEventListener('click',()=>{if(!$('#drawBtn').disabled)$('#drawBtn').click();});
gachaStage.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&!$('#drawBtn').disabled){e.preventDefault();$('#drawBtn').click();}});

const eventIds=['mystery','flash','gacha'];
let selectedEvent='mystery';
function selectEvent(id,scroll=true){
 if(!eventIds.includes(id)) return;
 selectedEvent=id;
 if(id==='flash') requestAnimationFrame(syncFlashScroll);
 document.querySelectorAll('.rail-link').forEach(link=>{const active=link.dataset.event===id; link.classList.toggle('active',active); if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
 eventIds.forEach(x=>{document.getElementById(x).hidden=x!==id;});
 updateEventGates();
 if(scroll) document.getElementById(id).scrollIntoView({behavior:'smooth',block:'start'});
}
function updateEventGates(){
 const keys=['tg','bf','cm'];
 eventIds.forEach((id,i)=>{
  const eventPhase=CONFIG.events[keys[i]], st=phaseStatus(i===1?{start:CONFIG.flash.sessions[0].start,end:eventPhase.end}:eventPhase), card=document.querySelector('.agenda-'+(i+1));
  const badge=document.getElementById('cardStatus'+(i+1));
  badge.innerHTML=i===0&&st.k==='soon'?'':i>0&&st.k==='soon'?(LANG==='zh'?'距开始 ':'Starts in ')+'<span class="countdown-value">'+fmtDur(new Date(i===1?CONFIG.flash.sessions[0].start:CONFIG.events[keys[i]].start)-now())+'</span>':st.label; card.classList.remove('is-upcoming'); card.classList.toggle('is-active',st.k==='live'); card.classList.toggle('preview-upcoming',i>0&&st.k==='soon');
  if(i===0)return; // Thanksgiving remains the default preview.
  const locked=false, section=document.getElementById(id), content=document.getElementById(id+'Content'), gate=document.getElementById(id+'Gate');
  section.classList.toggle('is-locked',locked); content.inert=locked; content.setAttribute('aria-hidden',String(locked));
  const zh=LANG==='zh';
  gate.querySelector('b').textContent=st.k==='soon'?(zh?'活动未开始':'EVENT NOT STARTED'):(zh?'活动已结束':'EVENT ENDED');
  gate.querySelector('span').textContent=st.k==='soon'?(zh?'距离开始：':'Starts in: ')+fmtDur(new Date(CONFIG.events[keys[i]].start)-now()):'';
 });
}
document.querySelectorAll('a[href="#mystery"],a[href="#flash"],a[href="#gacha"]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();selectEvent(a.getAttribute('href').slice(1));}));
const originalSetLang=setLang;
setLang=function(l){originalSetLang(l);updateEventGates();updateBackToTop();};
function currentFeaturedEvent(){const n=now();if(n>=new Date(CONFIG.events.cm.start))return 'gacha';if(n>=new Date(CONFIG.events.bf.start))return 'flash';return 'mystery';}
let featuredEvent=currentFeaturedEvent();selectEvent(featuredEvent,false);
setInterval(()=>{const next=currentFeaturedEvent();if(next!==featuredEvent){featuredEvent=next;selectEvent(next,false);}else updateEventGates();},1000);
document.addEventListener('click',function(e){
 const checks=[['#msPool, #msActions, #msResult','tg'],['#flashGrid .buybtn','bf'],['#freeDrawBtn, #drawBtn, .gacha-art-stage','cm'],['.codes-block .exclusive-shop','tg']];
 for(const [selector,key] of checks){if(e.target.closest(selector)&&phaseStatus(CONFIG.events[key]).k!=='live'){e.preventDefault();e.stopImmediatePropagation();toast(LANG==='zh'?(phaseStatus(CONFIG.events[key]).k==='soon'?'活动尚未开始':'活动已结束'):(phaseStatus(CONFIG.events[key]).k==='soon'?'Event not started yet':'Event ended'));return;}}
},true);


/* Show activity navigation only while an activity section is in view. */
const activityRail=document.querySelector('.activity-rail');
function updateRailVisibility(){
 const section=document.getElementById(selectedEvent);
 const rect=section.getBoundingClientRect();
 const rules=document.getElementById('rules'), rr=rules.getBoundingClientRect();
 const rulesInView=rr.top<=Math.max(115,window.innerHeight*.48) && rr.bottom>110;
 const activityInView=!section.hidden && rect.top<=105 && rect.bottom>120;
 const visible=rulesInView || activityInView;
 const current=rulesInView?'rules':selectedEvent;
 document.querySelectorAll('.rail-link').forEach(link=>{
   const active=link.dataset.event===current;
   link.classList.toggle('active',active);
   if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
 });
 activityRail.classList.toggle('rail-visible',visible);
 activityRail.setAttribute('aria-hidden',String(!visible));
 activityRail.inert=!visible;
}
window.addEventListener('scroll',updateRailVisibility,{passive:true});
window.addEventListener('resize',updateRailVisibility,{passive:true});
updateRailVisibility();


/* Return to the page top without changing the selected activity. */
const backToTop=document.getElementById('backToTop');
function updateBackToTop(){
 backToTop.classList.toggle('is-visible',window.scrollY>250);
 const label=LANG==='zh'?'回到顶部':'Back to top';
 backToTop.setAttribute('aria-label',label);backToTop.setAttribute('title',label);
}
backToTop.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));
window.addEventListener('scroll',updateBackToTop,{passive:true});
updateBackToTop();
;(() => {
 const selector='#aionSelector select,#wowSelector select,#poeSelector select,#poe1Selector select,#marketSelector select,#fc27PlatformBar select,#flashGrid select';
 const controls=new WeakMap();let open=null, sequence=0, scheduled=false;
 const escapeText=s=>String(s??'');
 function closeMenu(restoreFocus=false){if(!open)return;const {button,menu}=open;open=null;menu.remove();button.setAttribute('aria-expanded','false');if(restoreFocus&&button.isConnected)button.focus();}
 function position(){if(!open||!open.button.isConnected){closeMenu();return;}const {button,menu}=open,r=button.getBoundingClientRect();const width=Math.min(Math.max(r.width,175),window.innerWidth-20);menu.style.width=width+'px';menu.style.left=Math.max(10,Math.min(r.left,window.innerWidth-width-10))+'px';const h=Math.min(menu.scrollHeight,260,window.innerHeight-20);const below=window.innerHeight-r.bottom;const top=(below>=h+8||below>=r.top)?Math.min(r.bottom+5,window.innerHeight-h-10):Math.max(10,r.top-h-5);menu.style.top=top+'px';menu.style.maxHeight=Math.max(80,Math.min(260,window.innerHeight-top-10))+'px';}
 function makeMenu(select,button){
  if(select.disabled)return;if(open?.button===button){closeMenu(true);return;}closeMenu();
  const menu=document.createElement('div');menu.className='game-select-menu';menu.id='game-select-options-'+(++sequence);menu.setAttribute('role','listbox');
  const options=Array.from(select.options);
  options.forEach((opt,i)=>{const item=document.createElement('button');item.type='button';item.className='game-select-option';item.setAttribute('role','option');item.setAttribute('aria-selected',String(opt.selected));item.disabled=opt.disabled;item.textContent=escapeText(opt.textContent.trim());item.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();if(opt.disabled)return;select.value=opt.value;closeMenu();select.dispatchEvent(new Event('change',{bubbles:true}));refresh();if(button.isConnected)button.focus();});menu.appendChild(item);});
  button.setAttribute('aria-controls',menu.id);button.setAttribute('aria-expanded','true');document.body.appendChild(menu);open={button,menu,select};position();
  const enabled=()=>Array.from(menu.querySelectorAll('button:not(:disabled)'));
  menu.addEventListener('keydown',e=>{const list=enabled();if(!list.length)return;let i=list.indexOf(document.activeElement);if(e.key==='Escape'){e.preventDefault();closeMenu(true);}else if(e.key==='ArrowDown'||e.key==='ArrowUp'||e.key==='Home'||e.key==='End'){e.preventDefault();i=e.key==='Home'?0:e.key==='End'?list.length-1:(i+(e.key==='ArrowDown'?1:-1)+list.length)%list.length;list[i].focus();}else if(e.key==='Tab'){closeMenu();}});
  (menu.querySelector('[aria-selected="true"]:not(:disabled)')||enabled()[0])?.focus();
 }
 function refresh(){
  document.querySelectorAll(selector).forEach(select=>{
   let ctl=controls.get(select);
   if(!ctl){const wrap=document.createElement('span');wrap.className='game-select-wrap';const button=document.createElement('button');button.type='button';button.className='game-select-trigger';button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');const value=document.createElement('span');value.className='game-select-value';const arrow=document.createElement('span');arrow.className='game-select-arrow';arrow.setAttribute('aria-hidden','true');button.append(value,arrow);wrap.appendChild(button);select.insertAdjacentElement('afterend',wrap);select.classList.add('game-select-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');button.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();makeMenu(select,button);});button.addEventListener('keydown',e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();makeMenu(select,button);}});controls.set(select,ctl={button,value});}
   ctl.value.textContent=select.selectedOptions[0]?.textContent.trim()||'—';ctl.button.disabled=select.disabled;
   const name=select.getAttribute('aria-label')||select.closest('label')?.firstChild?.textContent?.trim()||select.id||'Option';ctl.button.setAttribute('aria-label',name+': '+ctl.value.textContent);
  });
  if(open&&(!open.button.isConnected||open.select.disabled))closeMenu();
 }
 function schedule(){if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh();});}
 document.addEventListener('click',e=>{if(open&&!open.menu.contains(e.target)&&!open.button.contains(e.target))closeMenu();});
 window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
 const observer=new MutationObserver(records=>{if(records.some(r=>r.target instanceof HTMLSelectElement||Array.from(r.addedNodes).some(n=>n.nodeType===1&&(n.matches?.(selector)||n.querySelector?.(selector)))))schedule();});
 observer.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['disabled','selected']});
 const previousMs=renderMsZone;renderMsZone=function(...args){const value=previousMs.apply(this,args);schedule();return value;};
 const previousFlash=renderFlash;renderFlash=function(...args){const value=previousFlash.apply(this,args);schedule();return value;};
 refresh();
})();
