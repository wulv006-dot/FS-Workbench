# -*- coding: utf-8 -*-
"""自包含看板生成器（零外部请求，手写 SVG，不引任何 CDN）

办公网常封 jsdelivr/unpkg/bootcdn，所以看板必须完全自包含：
数据内联成 const DATA = {...}，图表全部手写 SVG / CSS。
配色 Catppuccin Mocha 暗色。
"""
import datetime as dt
import json
import os
import re

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RPG 游戏改价系统 · 全游戏</title>
<style>
:root{
  --base:#1e1e2e; --mantle:#181825; --crust:#11111b; --surf0:#313244; --surf1:#45475a;
  --text:#cdd6f4; --sub:#a6adc8; --mauve:#cba6f7; --blue:#89b4fa; --peach:#fab387;
  --green:#a6e3a1; --red:#f38ba8; --yellow:#f9e2af; --teal:#94e2d5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--base);color:var(--text);font:13px/1.55 "Microsoft YaHei","Segoe UI",system-ui,sans-serif}
.wrap{max-width:1640px;margin:0 auto;padding:18px 20px 60px}
h1{font-size:20px;margin:0 0 3px;font-weight:650;letter-spacing:.4px}
h1 .sub{font-size:12px;color:var(--sub);font-weight:400;margin-left:8px}
h2{font-size:14px;margin:26px 0 10px;color:var(--mauve);font-weight:600;
   border-left:3px solid var(--mauve);padding-left:9px;display:flex;align-items:center;gap:10px}
h2 .hint{font-size:11px;color:var(--sub);font-weight:400}
.topbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:10px 0 4px}
.badge{display:inline-flex;align-items:center;gap:7px;padding:6px 13px;border-radius:99px;
   background:var(--surf0);font-size:12px;font-weight:600}
.badge .dot{width:9px;height:9px;border-radius:99px;background:var(--sub)}
.badge.off{background:#45233a;color:#f5c2e7}
.badge.off .dot{background:var(--red);box-shadow:0 0 9px var(--red)}
.badge.on{background:#1e3b2c;color:#a6e3a1}
.badge.on .dot{background:var(--green);box-shadow:0 0 9px var(--green)}
.badge.warn{background:#4a3a1a;color:var(--yellow)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:11px;margin:14px 0 6px}
.kpi{background:var(--mantle);border:1px solid var(--surf0);border-radius:12px;padding:12px 14px}
.kpi .l{font-size:11px;color:var(--sub);letter-spacing:.3px}
.kpi .v{font-size:23px;font-weight:680;margin-top:3px;font-variant-numeric:tabular-nums}
.kpi .n{font-size:11px;color:var(--sub);margin-top:2px}
.card{background:var(--mantle);border:1px solid var(--surf0);border-radius:12px;padding:14px;margin-top:10px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid #2a2a3c;white-space:nowrap}
th{color:var(--sub);font-weight:600;font-size:11px;position:sticky;top:0;background:var(--mantle);z-index:2}
tbody tr:hover{background:#24243a}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.up{color:var(--red);font-weight:600}      /* 中文习惯：涨=红 */
.dn{color:var(--green);font-weight:600}    /* 跌=绿 */
.flat{color:var(--sub)}
.tag{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}
.t-follow_up{background:#4a2229;color:#f38ba8}
.t-follow_down{background:#1e3b2c;color:#a6e3a1}
.t-hold{background:#313244;color:var(--sub)}
.t-blocked{background:#4a3a1a;color:var(--yellow)}
.t-none{background:#313244;color:var(--sub)}
.small{font-size:11px;color:var(--sub)}
.mono{font-variant-numeric:tabular-nums;font-family:Consolas,"Courier New",monospace}
.flexrow{display:flex;gap:14px;flex-wrap:wrap;align-items:stretch}
.flexrow>.card{flex:1;min-width:330px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--sub);margin:4px 0 8px}
.legend i{display:inline-block;width:16px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle}
.note{background:#23233a;border-left:3px solid var(--blue);border-radius:0 8px 8px 0;
  padding:9px 13px;font-size:12px;color:var(--sub);margin:8px 0}
.note.warnbox{background:#33291a;border-left-color:var(--yellow)}
select{background:var(--surf0);color:var(--text);border:1px solid var(--surf1);
  border-radius:8px;padding:5px 9px;font-size:12px}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--surf0);
  font-size:11px;color:var(--sub);line-height:1.9}
.scroll{overflow:auto;max-height:620px}
.pill{background:var(--surf0);border-radius:99px;padding:2px 9px;font-size:11px;color:var(--sub)}
.bar{height:7px;border-radius:99px;background:var(--surf0);overflow:hidden;min-width:64px}
.bar>i{display:block;height:100%;border-radius:99px}
/* ---------- 按游戏分区（多游戏）---------- */
.gsec{font-size:14px;margin:20px 0 9px;display:flex;align-items:center;gap:9px;font-weight:650;
  border-left:4px solid var(--surf1);padding-left:10px;letter-spacing:.3px}
.gsec:first-child{margin-top:10px}
.gsec .gi{display:inline-flex;width:24px;height:24px;border-radius:8px;align-items:center;
  justify-content:center;font-size:14px;line-height:1;flex:0 0 auto}
.gsec .hint{font-size:11px;color:var(--sub);font-weight:400;margin-left:auto}
.gsec .mech{font-size:11px;color:var(--sub);font-weight:400;
  background:var(--surf0);border-radius:99px;padding:2px 9px}
</style></head><body><div class="wrap">

<h1>RPG 游戏改价系统 <span class="sub" id="h1sub">全游戏竞品价格跟随 + 利润率监控</span></h1>
<div class="topbar" id="topbar"></div>
<div id="staleness"></div>

<div class="kpis" id="kpis"></div>

<h2>一、金币跟价（Gold） <span class="hint">按游戏分区 · 口径：我方前端每 M 价 = IGGM 每 M 价 × (1−让价) · <b>单价一律按「每 10 万 M」展示</b></span></h2>
<div class="card">
  <div class="note" id="goldNote"></div>
</div>
<div id="goldBlocks"></div>
<div id="goldTicket" class="small" style="margin-top:9px"></div>

<h2>二、跟价主表 <span class="hint">按游戏分区 · 涨=红 / 跌=绿（中文习惯）· 整包价｜目标价 = 后台「$每个价格」口径</span></h2>
<div class="card">
  <div class="small" style="margin-bottom:6px">
    <b style="color:var(--text)">说明</b>：IGGM 是我们 D4 的核心竞品。本表把
    <span style="color:var(--blue)">IGGM 单价</span>、<span style="color:var(--peach)">我方前端价</span>、
    <span style="color:var(--teal)">千岛进货成本</span> 摆在一起，实时算毛利率，
    并按跟价开关给出「应该改成多少」。
  </div>
</div>

<div id="mappingWarn"></div>
<div id="qdWarn"></div>
<div id="mainBlocks"></div>

<h2>三、价格走势 <span class="hint">IGGM 竞品价 vs 我方前端价</span></h2>
<div class="card">
  <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:6px">
    <select id="selItem"></select>
    <span class="legend">
      <span><i style="background:#89b4fa"></i>IGGM 单价</span>
      <span><i style="background:#fab387"></i>我方前端价</span>
      <span><i style="background:#94e2d5"></i>千岛成本($)</span>
    </span>
  </div>
  <div id="chart"></div>
</div>

<h2>四、采购成本 ↔ 前端价格 换算关系</h2>
<div class="card">
  <div class="note" id="formula">__FORMULA__</div>
  <div id="formulaTable"></div>
</div>

<h2>五、改价决策台账 <span class="hint">最近 30 条</span></h2>
<div class="card">
  <div class="scroll"><table id="dec">
    <thead><tr><th>时间</th><th>商品</th><th>动作</th>
      <th class="num">IGGM</th><th class="num">我方</th><th class="num">目标</th>
      <th class="num">毛利率</th><th>开关</th><th>说明</th></tr></thead>
    <tbody></tbody>
  </table></div>
</div>

<h2>六、改价后台接入状态</h2>
<div class="card" id="p2pahStatus"></div>

<footer>
  <div><b>跟价开关</b>：改 <span class="mono">config.json → 跟价.模式</span> 为
    <b>OFF</b>（只观察）或 <b>AUTO</b>（自动跟）。也可直接跑
    <span class="mono">python tracker.py --set-mode AUTO</span>。</div>
  <div><b>安全闸</b>：目标价不得低于「成本 × (1 + 最低毛利率)」；方向开关可分别关闭涨 / 跌。</div>
  <div><b>改价必须显式确认</b>：<span class="mono">python apply_price.py --confirm</span>，
    不加只打印计划。改完自动清缓存。</div>
  <div><b>数据新鲜度</b>：页面载入时间 <span id="loaded"></span>；数据快照见页头。
    若数字没变，先 <span class="mono">Ctrl+F5</span> 强刷。</div>
  <div>生成时间：__GEN__ ｜ 引擎：IGGM goods_ajax + 千岛签名拦截 + order.p2pah.cn</div>
</footer>
</div>

<script>
const DATA = __DATA__;
const RATE = DATA.rate;
function fmt(v,d){ if(v===null||v===undefined||v==='') return '--';
  const n=Number(v); if(!isNaN(n)) return n.toFixed(d===undefined?4:d); return String(v); }
function usd(v,d){ if(v===null||v===undefined) return '--'; return '$'+Number(v).toFixed(d===undefined?4:d); }
function cny(v){ if(v===null||v===undefined) return '--'; return '¥'+Number(v).toFixed(4); }
function pct(v,d){ if(v===null||v===undefined) return '--'; return (v*100).toFixed(d===undefined?1:d)+'%'; }
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function hexA(c,a){ const m=/^#?([0-9a-f]{6})$/i.exec(String(c||'')); if(!m) return 'transparent';
  const n=parseInt(m[1],16); return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a+')'; }

/* ---------- 按游戏分区（通用）----------
   两块表（金币明细 / 跟价主表）都按「游戏」切段：段标题 = 图标 + 游戏名 + 机制 + 条数统计，
   段内一张独立表。分段完全由数据的 game 字段驱动，新增游戏不用改这里。 */
const MAIN_COLS = [{t:'商品'},{t:'IGGM 上轮',n:1},{t:'IGGM 现价',n:1},{t:'IGGM 变动',n:1},
  {t:'我方现价',n:1},{t:'目标价',n:1},{t:'千岛成本',n:1},{t:'成本($)',n:1},{t:'毛利率',n:1},
  {t:'动作'},{t:'原因 / 依据'}];
/* 金币单价的展示倍率 —— **按游戏取**（2026-10-01 多游戏）：
   暗黑4 单价 5e-4 量级 → ×100000 显示成「每 10 万 M」（2026-09-27 用户口径：
   「后台展示的金币单价是 4.5364e-4 这种科学计数法，看不明白，
     你改成以 100000M 为单位的展示好了」）；
   AION2 单价本身就是 $/M（5.99 / 10.99）→ ×1 显示成「每 M」。
   倍率由 _gold_payload 为每个游戏段给出的 unit 决定。
   任何地方都不再出现 e-4 / E-6 / toExponential。 */
const GOLD_UNIT = 100000;                       // 兜底：段没给 unit 时用
function goldUnitOfGrp(gr){
  if(gr && gr.unit != null){ const u=Number(gr.unit); if(isFinite(u)&&u>0) return u; }
  const r=(gr&&gr.rows&&gr.rows[0])||{};
  const u = (r.unit!=null) ? Number(r.unit) : GOLD_UNIT;
  return (isFinite(u)&&u>0) ? u : GOLD_UNIT;
}
function goldUnitLabel(u){
  u = Number(u)||GOLD_UNIT;
  if(Math.abs(u-100000)<1) return '10万M';
  if(Math.abs(u-1)<1e-9) return 'M';
  return u+'M';
}
function goldCols(u){
  const UL = goldUnitLabel(u);
  return [{t:'服务区'},{t:'利润率',n:1},{t:'IGGM $/'+UL,n:1},{t:'我方前端 $/'+UL,n:1},
    {t:'差距',n:1},{t:'目标采购成本 ￥/M',n:1},{t:'最大档对照',n:1},{t:'动作'},{t:'说明'}];
}

function gameMeta(name){
  const gs = DATA.games || [];
  for(let i=0;i<gs.length;i++){ if(gs[i].name===name) return gs[i]; }
  return {};
}
function actTag(a, labels){
  const L = labels || {follow_up:'跟涨',follow_down:'跟降',hold:'仅观察',blocked:'已拦截'};
  return '<span class="tag t-'+(a||'hold')+'">'+(L[a]||a||'--')+'</span>';
}
/* 主表行（物品口径；POE2 的金币在后台也是普通商品，复用这套列） */
function mainCells(r){
  let chg = '';
  if(r.iggmOld && r.iggmNew){
    const p = (r.iggmNew-r.iggmOld)/r.iggmOld*100;
    const c = Math.abs(p)<0.0001?'flat':(p>0?'up':'dn');
    chg = '<span class="'+c+'">'+(p>0?'▲ +':(p<0?'▼ ':'– '))+p.toFixed(2)+'%</span>';
  } else chg = '<span class="flat small">建立基线</span>';
  const act = actTag(r.action);
  const mgn = r.margin!=null ? '<span class="'+(r.margin<0.05?'dn':(r.margin>0.6?'up':''))+'">'+pct(r.margin)+'</span>' : '--';
  const tgt = r.target ? '<b class="mono">'+usd(r.target)+'</b>'
      + (r.targetFront!=null ? '<div class="small mono">前端 '+usd(r.targetFront)+'</div>' : '')
      : '<span class="small">--</span>';
  const packTag = r.pack>1 ? ' <span class="pill">'+r.pack+' 件装</span>' : '';
  const ourCell = r.oursOld==null ? '<span class="small">--</span>'
      : '<span class="mono">'+usd(r.oursOld)+'</span>'
        + (r.oursBid!=null ? '<div class="small mono">标价 '+usd(r.oursBid)+'</div>' : '')
        + (r.ourUnit!=null && r.pack>1 ? '<div class="small mono">单价 '+usd(r.ourUnit)+'</div>' : '');
  const igCell = r.iggmNew==null ? '<span class="small">--</span>'
      : '<span class="mono">'+usd(r.iggmNew)+'</span>'
        + (r.pack>1 ? '<div class="small mono">单价 '+(r.iggmNew/r.pack).toFixed(4)+'</div>' : '');
  const costTag = (r.costTrust===false)
      ? ' <span class="badge warn" style="padding:1px 7px;font-size:10px">'
        + esc(r.costSpec||'参考区服')+'</span>' : '';
  return '<td><b>'+esc(r.title)+'</b>'+packTag+'<div class="small">'+esc(r.iggmTitle||'')+'</div></td>'
    + '<td class="num mono">'+usd(r.iggmOld)+'</td>'
    + '<td class="num">'+igCell+'</td>'
    + '<td class="num">'+chg+'</td>'
    + '<td class="num" style="color:var(--peach)">'+ourCell+'</td>'
    + '<td class="num">'+tgt+'</td>'
    + '<td class="num mono" style="color:var(--teal)">'+cny(r.costCny)+costTag+'</td>'
    + '<td class="num mono">'+usd(r.costUsd)+'</td>'
    + '<td class="num">'+mgn+'</td>'
    + '<td>'+act+'</td>'
    + '<td class="small" style="white-space:normal;max-width:420px">'+esc(r.reason)+'</td>';
}
/* 金币行（采购成本口径：暗黑4 后台「金币价格管理」一行 = 一个服务区） */
function goldCells(r){
  /* 每 M 价 → 「按该游戏倍率放大」的定点字符串（D4 → 每 10 万 M；AION2 → 每 M）。
     🔴 绝不再用 toExponential —— 用户看到的那串 4.5364e-4 就是这里吐出来的。 */
  const _U0 = (r && r.unit != null) ? Number(r.unit) : GOLD_UNIT;
  const _U = (isFinite(_U0) && _U0 > 0) ? _U0 : GOLD_UNIT;
  function pm(v){ if(v===null||v===undefined||v==='') return '--';
    const n=Number(v); if(isNaN(n)) return '--';
    const x = n*_U;
    return (Math.abs(x)>=1000) ? x.toFixed(0) : x.toFixed(2); }
  function c6(v){ if(v===null||v===undefined||v==='') return '--';
    const n=Number(v); return isNaN(n)?'--':n.toFixed(6); }
  let gap = '<span class="small">--</span>';
  if(r.ratio!==null && r.ratio!==undefined){
    const d = (Number(r.ratio)-1)*100;
    const c = Math.abs(d) < 0.5 ? 'flat' : (d>0 ? 'up' : 'dn');
    gap = '<span class="'+c+'">x'+Number(r.ratio).toFixed(4)
        + '<div class="small mono">'+(d>0?'+':'')+d.toFixed(2)+'%</div></span>';
  }
  const our = (r.ourPerM===null||r.ourPerM===undefined) ? '<span class="small">--</span>'
    : '<span class="mono">$'+pm(r.ourPerM)+'</span>';
  const ig = (r.iggmPerM===null||r.iggmPerM===undefined) ? '<span class="small">--</span>'
    : '<span class="mono">$'+pm(r.iggmPerM)+'</span>'
      + (r.iggmRaw!=null && Math.abs(Number(r.iggmRaw)-Number(r.iggmPerM))>1e-12
         ? '<div class="small mono">机房原始 $'+pm(r.iggmRaw)+'</div>' : '');
  const tgt = (r.costTarget===null||r.costTarget===undefined) ? '<span class="small">--</span>'
    : '<b class="mono">'+c6(r.costTarget)+'</b>'
      + (r.costOld!=null ? '<div class="small mono">现 '+c6(r.costOld)+'</div>' : '');
  /* 最大档对照（用户口径：金币单位大，拿「最大的那个金币选项」直接看价格变化）。
     一行读作：该档 IGGM 真价 $X ／ 我方现价 $Y → 改后 $Z，改后低 N%。 */
  let big = '<span class="small">--</span>';
  if(r.bigTier!=null && r.iggmBig!=null){
    const okc = r.ok===1 ? 'up' : 'dn';
    big = '<span class="mono">'+Number(r.bigTier).toLocaleString()+' M</span>'
      + '<div class="small mono">IGGM $'+Number(r.iggmBig).toFixed(2)
      + ' ｜ 我方 $'+(r.ourBig!=null?Number(r.ourBig).toFixed(2):'--')
      + ' → <b>$'+(r.tgtBig!=null?Number(r.tgtBig).toFixed(2):'--')+'</b></div>'
      + (r.belowPct!=null
         ? '<div class="small '+okc+' mono">'+(r.ok===1?'✔':'✘')+' 改后低 '
           +Number(r.belowPct).toFixed(2)+'%</div>' : '');
  }
  return '<td><b>'+esc(r.title)+'</b><div class="small">后台行 '+esc(r.rowId||'--')
      + ' ｜ 前端 aid '+esc(r.aid||'--')+'</div></td>'
    + '<td class="num">'+pct(r.marginRate)+'</td>'
    + '<td class="num" style="color:var(--blue)">'+ig+'</td>'
    + '<td class="num" style="color:var(--peach)">'+our+'</td>'
    + '<td class="num">'+gap+'</td>'
    + '<td class="num">'+tgt+'</td>'
    + '<td class="num">'+big+'</td>'
    + '<td>'+actTag(r.action, {follow_up:'跟涨',follow_down:'跟降',hold:'已持平',blocked:'已拦截'})+'</td>'
    + '<td class="small" style="white-space:normal;max-width:420px">'+esc(r.reason||'')+'</td>';
}
/* 一个游戏段：标题 + 独立表格。rows 为空也渲染段标题（显示"本轮没有数据"），
   让用户知道这个游戏是被监控的、只是本轮没抓到。 */
function sectionHtml(gname, mech, rows, cols, cellsFn, emptyMsg){
  const gm = gameMeta(gname);
  const color = gm.color || '#45475a';
  const stat = {follow_up:0,follow_down:0,hold:0,blocked:0};
  rows.forEach(function(r){ if(stat[r.action]!==undefined) stat[r.action]++; });
  const pend = stat.follow_up + stat.follow_down;
  let cnt = rows.length+' 条';
  if(pend) cnt += ' ｜ <b style="color:var(--red)">待改 '+pend+'</b>';
  cnt += ' ｜ 跟涨 '+stat.follow_up+' / 跟降 '+stat.follow_down+' / 观察 '+(stat.hold+stat.blocked);
  // 行少就整段铺开（限高会把最后一行切一半）；行多才限高滚动
  const scrollStyle = rows.length > 12 ? ' style="max-height:620px"' : '';
  return '<h3 class="gsec" style="border-left-color:'+color+'">'
    + '<span class="gi" style="background:'+hexA(color,0.16)+';color:'+color+'">'+esc(gm.icon||'')+'</span>'
    + esc(gname)
    + (mech ? '<span class="mech">'+mech+'</span>' : '')
    + '<span class="hint">'+esc(gm.en||'')+(gm.en?' · ':'')+cnt+'</span></h3>'
    + '<div class="card"><div class="scroll"'+scrollStyle+'><table>'
    + '<thead><tr>'+cols.map(function(c){ return '<th'+(c.n?' class="num"':'')+'>'+c.t+'</th>'; }).join('')+'</tr></thead><tbody>'
    + (rows.length ? rows.map(function(r){ return '<tr>'+cellsFn(r)+'</tr>'; }).join('')
                   : '<tr><td colspan="'+cols.length+'" class="small">'+esc(emptyMsg||'本轮没有数据')+'</td></tr>')
    + '</tbody></table></div></div>';
}
/* 按 DATA.games 的顺序把行分组（顺序里没有的游戏接在末尾） */
function groupRows(rows){
  const m = {};
  rows.forEach(function(r){ const g = r.game || '未分组'; (m[g]=m[g]||[]).push(r); });
  const names = (DATA.games||[]).map(function(x){ return x.name; })
                  .filter(function(g){ return m[g]; });
  Object.keys(m).forEach(function(g){ if(names.indexOf(g)<0) names.push(g); });
  return names.map(function(g){ return {name:g, meta:gameMeta(g), rows:m[g]}; });
}

/* ---------- 页头 ---------- */
(function(){
  const m = DATA.mode || 'OFF';
  const cls = m==='AUTO' ? 'on' : 'off';
  const label = m==='AUTO' ? '自动跟踪 · 已开启' : '关闭 · 只观察不改价';
  let h = '<span class="badge '+cls+'"><span class="dot"></span>跟价开关：'+label+'</span>';
  h += '<span class="badge">快照 '+esc(DATA.ts)+'</span>';
  h += '<span class="badge">汇率固定 '+RATE+'</span>';
  if(DATA.strategy) h += '<span class="badge">策略：'+esc(DATA.strategyName)+'</span>';
  if(DATA.mode!=='AUTO') h += '<span class="badge warn">改价需先切 AUTO 并人工放行</span>';
  document.getElementById('topbar').innerHTML = h;
  const age = DATA.ageHours;
  if(age!==null && age!==undefined && age>6){
    document.getElementById('staleness').innerHTML =
      '<div class="note warnbox">⚠ 数据已过 '+age.toFixed(1)+' 小时未更新（超过 6 小时）。请重跑 tracker.py。</div>';
  }
  document.getElementById('loaded').textContent = new Date().toLocaleString('zh-CN');
  // 标题按实际接入的游戏自动拼（含游戏数量变化时不用改模板）
  const gnames = (DATA.games||[]).filter(function(g){ return !g.reserved && g.name; })
                    .map(function(g){ return g.name; });
  const sub = document.getElementById('h1sub');
  if(sub) sub.textContent = (gnames.length ? gnames.join(' · ')+' · ' : '')+'竞品价格跟随 + 利润率监控';
  if(gnames.length) document.title = 'RPG 游戏改价系统 · '+gnames.join(' / ');
})();

/* ---------- KPI ---------- */
(function(){
  const K = DATA.kpi;
  const items = [
    ['IGGM 监控商品', K.iggmCount, '个', ''],
    ['本轮有变动', K.changed, '个', '进死区的已剔除'],
    ['我方已接入', K.ourCount, '个', K.ourCount? '' : '待接入改价后台'],
    ['平均毛利率', (K.avgMargin===null?'--':(K.avgMargin*100).toFixed(1)+'%'), '', '按已接入商品'],
    ['24h 决策记录', K.decisions24, '条', '可执行 涨'+K.up24+' / 降'+K.down24],
    ['24h 被安全闸拦下', K.blocked24, '条', K.blocked24? '需人工判断':'无'],
  ];
  document.getElementById('kpis').innerHTML = items.map(function(x){
    return '<div class="kpi"><div class="l">'+x[0]+'</div><div class="v">'+x[1]+'</div>'
      + '<div class="n">'+x[2]+(x[3]?' · '+x[3]:'')+'</div></div>';
  }).join('');
})();

/* ---------- 金币（Gold）：按游戏分区 ---------- */
(function(){
  const g = DATA.gold || {};
  const note = document.getElementById('goldNote');
  if(note){
    note.innerHTML =
      '<b>本区块按游戏分区</b>：暗黑4 的金币走后台「金币价格管理」（一行 = 一个服务区，可改的量是'
      + '<b>采购成本</b> ￥/M）；POE2 的金币在后台是「产品价格管理 · Quick Gold」的<b>普通商品</b>，'
      + '改的是<b>标价 $每个价格</b> —— 两套机制不一样，所以分段各自一套列，不要混着看。<br>'
      + '<b>单价展示倍率按游戏取</b>：暗黑4 ×100000 → 「每 10 万 M」（例如 0.0004536/M 显示成 '
      + '<span class="mono">$45.36/10万M</span>）；AION2 ×1 → 「每 M」（它的单价本身就是 $/M，'
      + '例如 <span class="mono">$10.99/M</span>）。表头列名跟着当前游戏自动切换，'
      + '不再出现 4.5364e-4 那种科学计数法。<br>'
      + '暗黑4 换算：<span class="mono">前台每M价($) = 后台b2c × 前台系数(1.0526)'
      + ' = 采购成本 ÷ [汇率 × (1−利润率) ÷ 前台系数]</span>，'
      + '反用 <span class="mono">目标采购成本 = 目标每M价 × 成本除数</span>（成本除数实测 '
      + (g.divisor? Number(g.divisor).toFixed(4) : '5.0540')
      + '；<b>不是</b> 汇率×(1−利润率) 的 '+(g.rate? (Number(g.rate)*0.8).toFixed(3):'5.320')
      + ' —— 按后者写会把采购成本写高 5.3%，正好把让价整条吃掉）。'
      + 'AION2 前台系数 = 1.0（TW/KR 实测 4/4 吻合），成本除数 = 汇率 × (1−利润率) ÷ 1.0。<br>'
      + '「最大档对照」列：拿该服务区<b>最大的那个金币档位</b>，把 IGGM 真价 / 我方现价 / '
      + '改后价都换成美元总额摆在一起，直接看「改完是不是低了让价那么多」。<br>'
      + '改价是<b>三步</b>：① 改采购成本 → ② 点后台右上角的<b>刷新图标「更新b2c网站」</b>'
      + '（<span class="mono">saveprice.html?getweb=1</span>；只点文案为「同步价格」的按钮 getweb=0 推不动前端）'
      + ' → ③ 去<b>主后台 admin.p2pah.cn「工具箱 → 缓存管理 → 一键清理所有」</b>'
      + '（<span class="mono">POST admin-api.p2pah.cn/admin/tools.Caches/clear</span>，'
      + '<b>只能在能打开该后台的机器上执行</b>）。🔴 全程绝不勾「所有区」；三步齐了前端约 5~15 分钟生效。<br>'
      + '对标档位 '+(g.tier||10000)+'M ｜ 汇率 '+(g.rate||RATE)+' ｜ ±0.5% 内视为持平'
      + ' ｜ IGGM 每M 已按折算系数还原成客户真价'
      + (g.ts? ' ｜ 快照 '+esc(g.ts) : '');
  }
  const host = document.getElementById('goldBlocks');
  const tk = document.getElementById('goldTicket');
  const groups = (g.groups || []).filter(function(x){ return (x.rows||[]).length; });
  if(!host) return;
  if(!groups.length){
    host.innerHTML = '<div class="card"><div class="small">'
      + '本轮没有金币数据（采集时未启用，或 IGGM / 前端抓取失败）</div></div>';
    if(tk) tk.innerHTML = '';
    return;
  }
  const ORD = {follow_up:1, follow_down:2, hold:3, blocked:4};
  let costN = 0, itemN = 0;
  const costByGame = {};      // 金币（改采购成本）· 按游戏计数（工单提示要分游戏说清）
  let detectN = 0;            // 「仅检测」服务区里本轮价差够改的条数
  const detectGames = [];     // 「仅检测」涉及的游戏名
  host.innerHTML = groups.map(function(gr){
    const cost = (gr.kind === 'cost');
    const rows = (gr.rows||[]).slice().sort(function(a,b){ return (ORD[a.action]||9)-(ORD[b.action]||9); });
    rows.forEach(function(r){
      if(r.action!=='follow_up' && r.action!=='follow_down') return;
      if(!cost){ itemN++; return; }
      if(r.detectOnly){                       // 仅检测：只观测，不进工单
        detectN++;
        if(detectGames.indexOf(gr.game)<0) detectGames.push(gr.game);
        return;
      }
      costN++;
      costByGame[gr.game] = (costByGame[gr.game]||0) + 1;
    });
    return sectionHtml(gr.game,
      cost ? ('金币价格管理 · 改采购成本(￥/M)' + (gr.detectOnly ? ' · 仅检测' : ''))
           : '产品价格管理 Quick Gold · 改标价($)',
      rows, cost?goldCols(goldUnitOfGrp(gr)):MAIN_COLS, cost?goldCells:mainCells,
      '本游戏本轮没有金币数据');
  }).join('');
  if(tk){
    let h = '';
    const cnames = Object.keys(costByGame);
    if(cnames.length){
      h += '↳ <b>金币 · 可改</b>：本轮 ' + cnames.map(function(n){
          return '<b>'+esc(n)+'</b> '+costByGame[n]+' 个服务区';
        }).join(' ＋ ')
        + ' 需改采购成本 → 生成金币工单后，在能打开后台的机器上执行：'
        + '<span class="mono">python p2pah_local.py writegold '
        + '--plan &lt;金币工单.json&gt; --confirm</span><br>';
    }
    if(detectN){
      h += '↳ <b>仅检测</b>：' + detectGames.map(function(n){ return esc(n); }).join(' ＋ ')
        + ' 有 <b>'+detectN+'</b> 个服务区本轮价差够改，但已标记「仅检测」'
        + ' → <b>不进工单、不动后台</b>（新游上线先观测，口径见 config「金币.服务区[].仅检测」）。<br>';
    }
    if(itemN) h += '↳ <b>POE2</b>：本轮 <b>'+itemN+'</b> 条金币需改标价 → 走物品工单执行：'
      + '<span class="mono">python p2pah_local.py write --plan &lt;金币工单.json&gt; --confirm</span>';
    tk.innerHTML = h || '↳ 本轮金币价全部持平，无需改价。';
  }
})();

/* ---------- 主表：按游戏分区 ---------- */
(function(){
  // 金币行不在这里 —— 它们归上方的「一、金币跟价」区，避免一行两处、也避免金币
  // 的「$每个价格 / 采购成本」两种口径在同一张表里对着看。
  const rows = (DATA.rows || []).filter(function(r){ return !r.isGold; });
  const host = document.getElementById('mainBlocks');
  if(!host) return;
  const gs = groupRows(rows);
  if(!gs.length){
    host.innerHTML = '<div class="card"><div class="small">暂无数据（还没跑过采集，或本轮 IGGM / 前端都没抓到）</div></div>';
    return;
  }
  host.innerHTML = gs.map(function(x){
    return sectionHtml(x.name, '', x.rows, MAIN_COLS, mainCells, '本游戏本轮没有物品数据');
  }).join('');
})();

/* ---------- 映射异常告警 ---------- */
(function(){
  const w = DATA.mappingWarn;
  if(!w) return;
  document.getElementById('mappingWarn').innerHTML =
    '<div class="note warnbox">⚠ <b>商品映射存疑，请确认后再开 AUTO</b><br>'+w+'</div>';
})();

/* ---------- 千岛成本可信度告警（降级到参考区服 → 成本不可信、跟价已冻结） ---------- */
(function(){
  var bad = (DATA.rows||[]).filter(function(r){ return r.costTrust === false; });
  var el = document.getElementById('qdWarn');
  if(!el || !bad.length) return;
  var specs = {};
  bad.forEach(function(r){ var k = r.costSpec || '?'; specs[k] = (specs[k]||0)+1; });
  var det = Object.keys(specs).map(function(k){ return k+'（'+specs[k]+' 项）'; }).join('、');
  el.innerHTML = '<div class="note warnbox">⚠ <b>千岛「'
    + esc(DATA.qdBaseSpec||'对标区服') + '」本轮无数据</b>，共 ' + bad.length
    + ' 项成本取自参考区服：' + esc(det)
    + '。参考区服里含<b>专家（硬核）服</b>，报价常为普通服的数倍～十几倍 → 成本虚高、毛利率失真；'
    + '<b>这些行已冻结跟价</b>（不出写操作、也不参与成本地板）。请检查千岛抓取是否漏了区服。</div>';
})();

/* ---------- 走势图（纯手写 SVG） ---------- */
(function(){
  const hist = DATA.history || {};
  const keys = Object.keys(hist);
  const sel = document.getElementById('selItem');
  if(!keys.length){ document.getElementById('chart').innerHTML='<div class="small">暂无历史数据（跑满两轮后出现）</div>'; return; }
  // 下拉也按游戏分组（只有一个游戏时退化成平铺，不显示多余的分组头）
  (function(){
    const m = {};
    keys.forEach(function(k){ const g = (hist[k].game || '未分组'); (m[g]=m[g]||[]).push(k); });
    const names = (DATA.games||[]).map(function(x){ return x.name; })
                    .filter(function(g){ return m[g]; });
    Object.keys(m).forEach(function(g){ if(names.indexOf(g)<0) names.push(g); });
    if(names.length <= 1){
      sel.innerHTML = keys.map(function(k){
        return '<option value="'+esc(k)+'">'+esc(hist[k].title||k)+'</option>'; }).join('');
      return;
    }
    sel.innerHTML = names.map(function(g){
      const gm = gameMeta(g);
      return '<optgroup label="'+esc((gm.icon?gm.icon+' ':'')+g)+'">'
        + m[g].map(function(k){ return '<option value="'+esc(k)+'">'+esc(hist[k].title||k)+'</option>'; }).join('')
        + '</optgroup>';
    }).join('');
  })();
  function draw(key){
    const d = hist[key]; const W=1340,H=300,P={l:62,r:16,t:14,b:34};
    const dates = d.dates||[];
    if(dates.length<1){ document.getElementById('chart').innerHTML='<div class="small">该商品暂无历史</div>'; return; }
    const series = [{n:'IGGM 单价',c:'#89b4fa',v:d.iggm},{n:'我方前端价',c:'#fab387',v:d.ours},{n:'千岛成本($)',c:'#94e2d5',v:d.cost}];
    let all=[]; series.forEach(s=>s.v.forEach(x=>{ if(x!=null) all.push(x); }));
    if(!all.length){ document.getElementById('chart').innerHTML='<div class="small">无有效数值</div>'; return; }
    let lo=Math.min.apply(null,all), hi=Math.max.apply(null,all);
    if(hi-lo<1e-9){ hi=hi*1.15+1e-6; lo=lo*0.85; }
    const pad=(hi-lo)*0.12; lo-=pad; hi+=pad; if(lo<0) lo=0;
    const X=i=>P.l+(dates.length===1?0.5:i/(dates.length-1))*(W-P.l-P.r);
    const Y=v=>H-P.b-(v-lo)/(hi-lo)*(H-P.t-P.b);
    let g='';
    for(let i=0;i<=4;i++){ const v=lo+(hi-lo)*i/4, y=Y(v);
      g+='<line x1="'+P.l+'" y1="'+y.toFixed(1)+'" x2="'+(W-P.r)+'" y2="'+y.toFixed(1)+'" stroke="#2a2a3c"/>';
      g+='<text x="'+(P.l-8)+'" y="'+(y+4).toFixed(1)+'" fill="#a6adc8" font-size="10" text-anchor="end">'+v.toFixed(3)+'</text>';
    }
    let ticks='';
    const step=Math.max(1,Math.ceil(dates.length/9));
    for(let i=0;i<dates.length;i+=step){
      ticks+='<text x="'+X(i).toFixed(1)+'" y="'+(H-P.b+16)+'" fill="#a6adc8" font-size="10" text-anchor="middle">'+dates[i].slice(5)+'</text>';
    }
    let paths='';
    series.forEach(function(s){
      let pts=[],area=[];
      s.v.forEach(function(v,i){ if(v==null) return; pts.push([X(i),Y(v)]); });
      if(!pts.length) return;
      let dd='M'+pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join('L');
      paths+='<path d="'+dd+'" fill="none" stroke="'+s.c+'" stroke-width="2" stroke-linejoin="round"/>';
      pts.forEach(function(p){ paths+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="2.6" fill="'+s.c+'"/>'; });
    });
    document.getElementById('chart').innerHTML =
      '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+ticks+paths+'</svg>';
  }
  sel.onchange=function(){ draw(sel.value); };
  draw(keys[0]);
})();

/* ---------- 换算关系 ---------- */
(function(){
  const f = DATA.formula || {};
  document.getElementById('formula').innerHTML = esc(f.conclusion||'暂无样本');
  const rs = f.rows||[];
  if(!rs.length){ document.getElementById('formulaTable').innerHTML=''; return; }
  document.getElementById('formulaTable').innerHTML =
    '<table><thead><tr><th>商品</th><th class="num">采购成本(¥)</th><th class="num">成本($) = ¥/'+RATE+'</th>'
    +'<th class="num">前端价($)</th><th class="num">隐含倍率</th><th class="num">加价额($)</th></tr></thead><tbody>'
    + rs.map(function(r){ return '<tr><td>'+esc(r.name)+'</td><td class="num mono">'+cny(r.cost_cny)+'</td>'
      + '<td class="num mono">'+usd(r.cost_usd)+'</td><td class="num mono">'+usd(r.front_usd)+'</td>'
      + '<td class="num mono">'+(r.ratio==null?'--':r.ratio.toFixed(4))+'</td>'
      + '<td class="num mono">'+(r.addon==null?'--':r.addon.toFixed(4))+'</td></tr>'; }).join('')
    + '</tbody></table>';
})();

/* ---------- 决策台账 ---------- */
(function(){
  const ds = DATA.decisions||[];
  const tb = document.querySelector('#dec tbody');
  if(!ds.length){ tb.innerHTML='<tr><td colspan="9" class="small">暂无决策记录</td></tr>'; return; }
  tb.innerHTML = ds.map(function(d){
    return '<tr><td class="small mono">'+esc(d.ts)+'</td>'
      + '<td><b>'+esc(d.title)+'</b>'+(d.game?'<div class="small">'+esc(d.game)+'</div>':'')+'</td>'
      +'<td><span class="tag t-'+d.action+'">'+({follow_up:'跟涨',follow_down:'跟降',hold:'仅观察',blocked:'已拦截'}[d.action]||d.action)+'</span></td>'
      +'<td class="num mono">'+usd(d.iggm_new)+'</td><td class="num mono">'+usd(d.ours_old)+'</td>'
      +'<td class="num mono">'+usd(d.target_usd)+'</td><td class="num">'+pct(d.margin_new)+'</td>'
      +'<td><span class="pill">'+esc(d.mode)+'</span></td>'
      +'<td class="small" style="white-space:normal;max-width:460px">'+esc(d.reason)+'</td></tr>';
  }).join('');
})();

/* ---------- 改价后台接入状态 ---------- */
(function(){
  document.getElementById('p2pahStatus').innerHTML = DATA.p2pahHtml || '<div class="small">--</div>';
})();
</script></body></html>
"""


def _gold_payload(cfg, gold, gold_ts, rate, item_rows=None):
    """金币区块数据 —— **按游戏分段**（看板「一、金币跟价」区）。

    金币在本系统里有**两套来源、两套口径**，分段时必须分开，不能混成一张表：

    | kind | 游戏 | 来源 | 后台页 | 可改的量 |
    |---|---|---|---|---|
    | `cost` | 暗黑4 | `gold_price` 表（core_gold 专线） | 金币价格管理 | 采购成本 ￥/M |
    | `item` | POE2 | decisions（物品链路，Quick Gold 是普通商品） | 产品价格管理 | 标价 $每个价格 |

    所以返回 `groups = [{game, kind, rows, unit, unitLabel, detectOnly}, ...]`，
    前端按 `kind` 选各自的列（`goldCols(unit)` / `MAIN_COLS`），再由 `游戏顺序` 决定段落先后。

    2026-10-01 多游戏：`cost` 段不再只有暗黑4 —— AION2 的金币（Kinah/Kina）也走这条专线，
    但**单价量级完全不同**（D4 是 5e-4 量级、AION2 本身即 $/M），所以每行/每段都带上
    `unit`（展示倍率）：D4=100000（每 10 万 M）、AION2=1（每 M）。
    `detectOnly` 是该段里 config 标了「仅检测」的行数（只观测不进工单）。
    """
    import engine as _engine
    import core_gold as _cg
    g = cfg.get("金币") or {}
    # 金币单价的展示倍率**按游戏取**（2026-10-01 多游戏）：
    #   暗黑4 单价 5e-4 量级 → 100000（每 10 万 M）；AION2 单价即 $/M → 1（每 M）。
    #   倍率随每条行与每个游戏段一起下发，前端据此换算，绝不用全局常量硬乘。
    _u_cache = {}
    # 「仅检测」服务区（config.金币.服务区[].仅检测）：只观测不出单，看板要标出来。
    #   AION2 刚上线，用户口径「只做检测不自动改价」。
    _det_only = {sv.get("key") for sv in (g.get("服务区") or [])
                 if isinstance(sv, dict) and sv.get("仅检测")}

    def _unit_of(gm):
        if gm not in _u_cache:
            try:
                _u_cache[gm] = float(_cg.display_mult_of(cfg, gm))
            except Exception:
                _u_cache[gm] = float(_cg.PER_100K)
        return _u_cache[gm]

    def _ulabel_of(gm):
        try:
            return _cg.unit_label(_unit_of(gm))
        except Exception:
            return "10万M"

    groups = {}
    for r in (gold or []):
        k = r.get("key")
        gm = _engine.game_of(cfg, k)
        groups.setdefault(gm, {"cost": [], "item": []})["cost"].append({
            "key": k, "title": r.get("title") or k, "game": gm,
            "rowId": r.get("row_id"), "aid": r.get("aid"),
            "marginRate": r.get("margin_rate"),
            "iggmPerM": r.get("iggm_per_m"), "iggmRaw": r.get("iggm_raw"),
            "ourPerM": r.get("our_per_m"), "ourTier": r.get("our_tier"),
            "costTarget": r.get("cost_target"), "costOld": r.get("cost_old"),
            "ratio": r.get("ratio"),
            "divisor": r.get("divisor"),
            # 展示倍率（按游戏）：D4=100000（每 10 万 M）、AION2=1（每 M）
            "unit": _unit_of(gm), "unitLabel": _ulabel_of(gm),
            "detectOnly": k in _det_only,
            # 最大档对照（2026-09-27 用户口径）：金币单价一律按「每 10 万 M」展示，
            # 并用**最大的那个金币档位**给一个能直接读的美元总额。
            "bigTier": r.get("big_tier"),
            "iggmBig": r.get("iggm_big"), "ourBig": r.get("our_big"),
            "tgtBig": r.get("tgt_big"), "belowPct": r.get("below_pct"),
            "ok": r.get("ok"),
            "action": r.get("action") or "hold",
            "reason": r.get("reason") or "",
        })
    for r in (item_rows or []):
        groups.setdefault(r.get("game") or _engine.default_game(cfg),
                         {"cost": [], "item": []})["item"].append(r)
    order = {n: i for i, n in enumerate(_engine.game_order(cfg))}
    out = []
    for gm in sorted(groups, key=lambda x: order.get(x, 999)):
        v = groups[gm]
        if v["cost"]:
            _det_n = sum(1 for x in v["cost"] if x.get("detectOnly"))
            out.append({"game": gm, "kind": "cost", "rows": v["cost"],
                        "unit": _unit_of(gm), "unitLabel": _ulabel_of(gm),
                        "detectOnly": _det_n})
        if v["item"]:
            out.append({"game": gm, "kind": "item", "rows": v["item"]})
    try:
        tier = int(g.get("对标档位") or 10000)
    except (TypeError, ValueError):
        tier = 10000
    try:
        grate = float(g.get("汇率") or 0) or float(rate)
    except (TypeError, ValueError):
        grate = float(rate)
    # 成本除数与前台系数：看板要把「为什么不是 汇率×(1−利润率)」写清楚，所以带到前端。
    try:
        import core_gold as _cg
        _div = float(_cg.cost_divisor_of(cfg, 0.20))
        _ff = float(_cg.front_factor_of(cfg))
        _unit = int(_cg.PER_100K)
    except Exception:
        _div, _ff, _unit = 0.0, 1.0, 100000
    return {"ts": gold_ts, "tier": tier, "rate": grate, "divisor": _div,
            "frontFactor": _ff, "unit": _unit, "unitByGame": dict(_u_cache),
            "groups": out, "rows": [x for gg in out for x in gg["rows"]]}


def build(cfg, con, ts, decisions, iggm_now, iggm_prev, ours_now, qd_map, log=print,
          out_path=None, gold=None, gold_ts=None):
    rate = float(cfg["汇率"]["USDCNY"])
    mode = str(cfg["跟价"].get("模式", "OFF")).upper()
    root = os.path.dirname(os.path.abspath(__file__))

    # 后台折扣：前端价 = 我方标价 × 折扣。两个口径都展示，避免看板与在线页口径不一致。
    # 2026-09-25：改为按商品/按游戏取（暗黑4=90、POE2=100）。
    import engine as _engine
    _k2it = {x["key"]: x for x in cfg["商品映射"]["对照项"]}

    def _disc_of_key(k):
        return _engine.disc_of(cfg, _k2it.get(k) or {})

    _disc = _engine.disc_of(cfg, {})

    # ---- 主表数据 ----
    rows = []
    changed = 0
    margins = []
    for d in decisions:
        it = next((x for x in cfg["商品映射"]["对照项"] if x["key"] == d["key"]), {})
        _dsc = _disc_of_key(d["key"])
        gn = d["iggm_no"]
        cur = iggm_now.get(gn) or {}
        ours_row = ours_now.get(d["key"]) or {}
        rows.append({
            "key": d["key"],
            "game": _engine.game_of(cfg, d["key"]),        # 看板按它分区
            "isGold": _engine.is_gold_key(cfg, d["key"]),  # 金币行归「金币明细」区
            "title": d["title"],
            "iggmTitle": cur.get("title") or (it.get("iggm") or {}).get("title") or "",
            "iggmNo": gn,
            "pack": int(it.get("装量", 1) or 1),
            "iggmOld": d.get("iggm_old"),
            "iggmNew": d.get("iggm_new"),
            "oursOld": d.get("ours_old"),                 # 前端展示价（客户实付）
            "oursBid": (d.get("ours_old") / _dsc) if d.get("ours_old") else None,
            "ourUnit": ours_row.get("unit_price_usd"),
            "target": d.get("target_usd"),                # 目标标价（= IGGM 折后价）
            "targetFront": (round(d["target_usd"] * _dsc, 4)
                            if d.get("target_usd") is not None else None),
            "costCny": d.get("cost_cny"),
            "costUsd": d.get("cost_usd"),
            # ★ 成本可信度（2026-09-27）：千岛对标区服缺失时会降级到参考区服取成本，
            #   看板必须显式标出来，不能像以前那样和正常价长得一模一样。
            "costTrust": d.get("_成本可信", True),
            "costSpec": d.get("_成本区服"),
            "margin": d.get("margin_old"),
            "action": d.get("action"),
            "reason": d.get("reason"),
            "仅展示": d.get("仅展示"),
        })
        if d.get("iggm_old") and d.get("iggm_new") and abs(d["iggm_new"] - d["iggm_old"]) > 1e-12:
            changed += 1
        if d.get("margin_old") is not None and d.get("ours_old"):
            margins.append(d["margin_old"])

    # ---- 映射存疑自检：任一重点商品毛利为负 → 提示可能映射错了 ----
    qd_ts = con.execute("SELECT MAX(ts) t FROM qd_cost WHERE ts<=?", (ts,)).fetchone()["t"]
    qd_names = {}
    if qd_ts:
        for r in con.execute("SELECT name, MIN(price_cny) c FROM qd_cost WHERE ts=? "
                             "GROUP BY name", (qd_ts,)):
            qd_names[r["name"]] = r["c"]
    mapping_warn = _mapping_warning(cfg, decisions, rate, qd_names)

    # ---- 历史序列 ----
    history = {}
    for it in cfg["商品映射"]["对照项"]:
        gn = str((it.get("iggm") or {}).get("goods_no") or "")
        ig = con.execute("SELECT ts,price_usd FROM iggm_price WHERE goods_no=? ORDER BY ts", (gn,)).fetchall()
        ou = con.execute("SELECT ts,price_usd FROM our_price WHERE key=? ORDER BY ts", (it["key"],)).fetchall()
        # 千岛成本历史（按 spu 名匹配太脆弱，这里只给当前值拉平）
        qd_hist = con.execute("SELECT ts,price_cny FROM qd_cost WHERE name=? AND spec=? ORDER BY ts",
                              ((it.get("千岛") or {}).get("商品"),
                               __import__("store").canon_spec(cfg["千岛"]["对标区服"]))).fetchall()
        dates = sorted({r["ts"][:10] for r in ig} | {r["ts"][:10] for r in ou})
        if not dates:
            continue
        igd = {r["ts"][:10]: r["price_usd"] for r in ig}
        oud = {r["ts"][:10]: r["price_usd"] for r in ou}
        scale = float((it.get("千岛") or {}).get("刻度", 1) or 1)
        # ⚠ 2026-09-29 修：千岛某商品可能整段没有订单簿深度（实测皇家档 7 个宝石
        #   无人挂售 → price_cny = NULL）。原写法 None * float 抛 TypeError，会把
        #   **整个离线看板 HTML** 打挂（采集日志只有一行 ⚠，在线看板看似正常，
        #   但 /api/board 会一直供旧文件）。NULL 按「该日无成本」处理。
        qdd = {}
        for _r in qd_hist:
            _c = _r["price_cny"]
            qdd[_r["ts"][:10]] = None if _c is None else (_c * scale / rate)
        last_ig, last_ou, last_qd = None, None, None
        si, so, sq = [], [], []
        for d0 in dates:
            last_ig = igd.get(d0, last_ig)
            last_ou = oud.get(d0, last_ou)
            last_qd = qdd.get(d0, last_qd)
            si.append(last_ig)
            so.append(last_ou)
            sq.append(last_qd)
        history[it["key"]] = {"title": it.get("中文名") or it["key"], "dates": dates,
                              "game": it.get("游戏") or _engine.game_of(cfg, it["key"]),
                              "iggm": si, "ours": so, "cost": sq}

    # ---- KPI ----
    fc = __import__("store").follow_counts(con)
    kpi = {
        "iggmCount": len(decisions),
        "changed": changed,
        "ourCount": len(ours_now),
        "avgMargin": (sum(margins) / len(margins)) if margins else None,
        "decisions24": fc["tot"],
        "up24": fc["up"],
        "down24": fc["dn"],
        "blocked24": fc["bl"],
    }

    # ---- 换算关系分析 ----
    pairs = []
    for it in cfg["商品映射"]["对照项"]:
        o = ours_now.get(it["key"]) or {}
        q = qd_map.get(it["key"]) or {}
        if not o or not q:
            continue
        try:
            cost_cny = float(q.get("price_cny") or 0) * float((it.get("千岛") or {}).get("刻度", 1) or 1)
        except (TypeError, ValueError):
            continue
        pairs.append((it.get("中文名") or it["key"], cost_cny, o.get("price_usd")))
    formula = __import__("engine").formula_analysis(pairs, rate)
    if not pairs:
        formula["conclusion"] = (
            "尚未接入 order.p2pah.cn 的实际价格数据，暂时无法反推公式。<br>"
            "已确认的前提：汇率固定 <b>%.2f</b>（不是千岛对外常用的 7.15）。<br>"
            "待接入后本表会自动列出每条商品的「采购成本(¥) → 成本($) → 前端价($) → 隐含倍率」，"
            "用倍率是否一致来判断公式是 **乘法**（前端价 = 采购成本 ÷ %.2f × 倍率）还是 **加法**。"
            % (rate, rate))

    # ---- p2pah 接入状态 HTML ----
    p = cfg["p2pah"]
    acc = p.get("账号") or {}
    has_acc = bool(acc.get("username") and acc.get("password"))
    gm = p.get("金币价格管理", {}).get("换算公式", {})
    st = []
    st.append("<table><tbody>")
    st.append("<tr><th style='width:190px'>项目</th><th>状态</th></tr>")
    st.append("<tr><td>改价后台</td><td><span class='mono'>%s</span> （ThinkPHP + SimpleBoot3，私有 CA 证书）</td></tr>" % p["base"])
    st.append("<tr><td>登录账号</td><td>%s</td></tr>"
              % ("<span class='up'>已配置</span> <span class='small'>%s</span>" % acc.get("username")
                 if has_acc else "<span class='tag t-blocked'>未配置</span> <span class='small'>需要在 config.json → p2pah.账号 填入 order.p2pah.cn 的用户名/密码</span>"))
    st.append("<tr><td>金币价格管理</td><td>路径 <span class='mono'>%s</span> ｜ 换算公式：<b>%s</b></td></tr>"
              % (p.get("金币价格管理", {}).get("路径", "-"), gm.get("状态", "待确认")))
    st.append("<tr><td>产品价格管理</td><td>路径 <span class='mono'>%s</span> ｜ 改的就是前端展示价 <span class='mono'>$</span></td></tr>"
              % (p.get("产品价格管理", {}).get("路径", "-")))
    cf = cfg["跟价"]["缓存刷新"]
    st.append("<tr><td>缓存刷新</td><td>%s ｜ 入口 <span class='mono'>%s</span> ｜ 菜单：%s</td></tr>"
              % ("改价后自动执行" if cf.get("自动刷新") else "需手动执行",
                 cf.get("入口"), " → ".join(cf.get("菜单", []))))
    st.append("<tr><td>改价执行</td><td>%s</td></tr>"
              % "<span class='tag t-hold'>必须</span> <span class='mono'>apply_price.py --confirm</span> 或本机执行器 <span class='mono'>--confirm</span> 才真改")
    st.append("</tbody></table>")
    p2pah_html = "".join(st)

    # ---- 组装 ----
    # 策略只剩一条：我方前端价 = IGGM 真价 × (1 − 让价百分比)。
    # 标签直接由让价算出来，不再有「按 策略 字段查表」那一层
    # （2026-09-27：relative_follow / benchmark_delta / fixed_gap 三个分支已从引擎删除，
    #   配置里的「策略」字段也一并归档，留着只会让人以为还能切）。
    _sc = cfg["跟价"].get("跟随策略") or {}
    try:
        _gap = max(0.0, min(float(_sc.get("让价百分比", 0.0) or 0.0), 90.0))
    except (TypeError, ValueError):
        _gap = 0.0
    strat = "allow_%g" % _gap
    strat_names = {strat: ("我方前端价 = IGGM 价（不让价）" if _gap == 0
                           else "我方前端价 = IGGM 价 − %.1f%%" % _gap)}
    dec_rows = []
    for r in __import__("store").decisions(con, limit=30):
        d0 = dict(r)
        d0["game"] = _engine.game_of(cfg, d0.get("key"))
        dec_rows.append(d0)
    data = {
        "ts": ts, "mode": mode, "rate": rate,
        "ageHours": _age_hours(ts),
        "kpi": kpi, "rows": rows, "history": history,
        # 游戏元数据（顺序 / 图标 / 颜色）—— 分区展示全靠它，新增游戏不用改前端
        "games": [_engine.game_meta(cfg, n) for n in _engine.game_order(cfg)],
        "mappingWarn": mapping_warn,
        # 千岛对标区服名（供「成本不可信」告警文案使用）
        "qdBaseSpec": (cfg.get("千岛") or {}).get("对标区服"),
        "strategy": strat, "strategyName": strat_names.get(strat, strat),
        "formula": {"conclusion": formula.get("conclusion"), "kind": formula.get("kind"),
                    "rows": formula.get("rows", [])},
        "decisions": dec_rows,
        "p2pahHtml": p2pah_html,
        "gold": _gold_payload(cfg, gold, gold_ts, rate,
                              item_rows=[r for r in rows if r.get("isGold")]),
    }
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str))
    html = html.replace("__GEN__", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    html = html.replace("__FORMULA__", "占位")
    # formula 占位在 <div class="note" id="formula"> 里，由 JS 覆盖，兜底也换掉
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        log("  看板已写出：%s (%.1f KB)" % (out_path, len(html.encode("utf-8")) / 1024.0))
    return html


def _age_hours(ts):
    try:
        t = dt.datetime.fromisoformat(ts)
        return (dt.datetime.now() - t).total_seconds() / 3600.0
    except Exception:
        return None


def _mapping_warning(cfg, decisions, rate, qd_names=None):
    """毛利为负的重点商品 → 十有八九是「IGGM/前端英文名 ↔ 千岛中文名」映射配错了。

    做法：把负毛利项列出来，并给出「换成候选中文名后」的毛利，让用户一眼决定。
    不自动改映射 —— 数据类改动必须先给 diff 等确认。
    """
    qd_names = qd_names or {}
    bad = [d for d in decisions
           if d.get("margin_old") is not None and d["margin_old"] < 0
           and not d.get("仅展示") and d.get("ours_old")]
    if not bad:
        return None
    lines = []
    for d in bad:
        it = next((x for x in cfg["商品映射"]["对照项"] if x["key"] == d["key"]), {})
        pack = float(it.get("装量", 1) or 1)
        lines.append(
            "· <b>%s</b>（%s 件装）我方整包价 <b>$%.4f</b>，"
            "现按千岛「%s」算成本 <b>$%.4f</b> → 毛利 <b>%.1f%%</b>（负数，等于卖一件亏一件）"
            % (d["title"], int(pack), d["ours_old"], d.get("qd_name") or "—",
               d.get("cost_usd") or 0, d["margin_old"] * 100))
        for alt in (it.get("映射候选") or []):
            cny = qd_names.get(alt)
            if not cny:
                continue
            cost = cny * pack / rate
            m = (d["ours_old"] - cost) / d["ours_old"]
            tag = "（毛利转正 ✔）" if m > 0 else ""
            lines.append(
                "　　 → 若改按千岛「%s」（¥%.4f/个 → 成本 $%.4f），毛利变成 <b>%.1f%%</b> %s"
                % (alt, cny, cost, m * 100, tag))
    return "<br>".join(lines)


if __name__ == "__main__":
    print("请通过 tracker.py 调用本模块（需要 cfg/con/decisions 等上下文）")
