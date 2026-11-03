window.createManagementSandbox=function(P,identity){
"use strict";
var G=P.games, TOTAL=P.total, FLOOR=P.floor, DRAFT="fs-management-sandbox-v2:"+encodeURIComponent(identity)+":"+P.period+":"+P.targetVersion;
var W=G.map(function(g){return {profile:g.profile,rev:g.tgt.rev};});
var curG="ALL", editedProfile=null, draftError="";
document.getElementById("sandboxTotal").textContent="$"+fmt(TOTAL);
document.getElementById("sandboxRules").textContent="锁定总目标 $"+fmt(TOTAL)+"；按其他项目可调整目标余量平账，每项最低 $"+fmt(FLOOR)+"。仅作本地推演，正式目标须另行审核后发布。";
function wOf(p){for(var i=0;i<W.length;i++)if(W[i].profile===p)return W[i].rev;return 0;}
function setW(p,v){for(var i=0;i<W.length;i++)if(W[i].profile===p)W[i].rev=v;}
function fmt(n){return Number.isFinite(n)?Math.round(n).toLocaleString("en-US"):"—";}
function gm(p){for(var i=0;i<G.length;i++)if(G[i].profile===p)return G[i];return null;}

// reallocate keeping sum == TOTAL exactly; per-game floor enforced
function rebalance(changedProfile, changedVal){
  changedVal=Math.round(changedVal);
  var pub={tgt:{rev:wOf(changedProfile)}};
  var others=G.filter(function(g){return g.profile!==changedProfile;});
  var big=others.slice().sort(function(a,b){return b.tgt.rev-a.tgt.rev;})[0];
  if(changedVal>pub.tgt.rev){
    // increase: others give room, weighted by each one's reducible slack (rev-floor)
    var need=changedVal-pub.tgt.rev;
    var avail=others.reduce(function(s,g){return s+wOf(g.profile)-FLOOR;},0);
    if(need>avail)return {ok:false,msg:"可削减空间不足：其余游戏最多再让出 $"+fmt(avail)+"，本次需 $"+fmt(need)+"。请降低该款增幅。"};
    others.forEach(function(g){
      if(g.profile===big.profile)return;
      var room=wOf(g.profile)-FLOOR;
      var cut=Math.round(need*room/avail);
      setW(g.profile,wOf(g.profile)-cut);
    });
    var interim=changedVal+others.reduce(function(s,g){return s+wOf(g.profile);},0);
    var bigv=Math.max(TOTAL-(interim-wOf(big.profile)),FLOOR);
    setW(big.profile,bigv);
  }else{
    // decrease: freed budget flows to others weighted by natural-forecast slack
    var freed=pub.tgt.rev-changedVal;
    function weight(g){return Math.max(g.proj.rev-FLOOR,0);}
    var wsum=others.reduce(function(s,g){return s+weight(g);},0);
    if(wsum<=0)return {ok:false,msg:"其余游戏没有可承接的预测余量，无法自动加派。"};
    others.forEach(function(g){
      if(g.profile===big.profile)return;
      var add=Math.round(freed*weight(g)/wsum);
      setW(g.profile,wOf(g.profile)+add);
    });
    var interim2=changedVal+others.reduce(function(s,g){return s+wOf(g.profile);},0);
    setW(big.profile, wOf(big.profile)+(TOTAL-interim2));
  }
  setW(changedProfile,changedVal);
  // enforce exact total & floor (absorb any rounding into the biggest participant)
  var drift=TOTAL-G.reduce(function(s,g){return s+wOf(g.profile);},0);
  var holder=drift>=0?big:gm(changedProfile);
  setW(holder.profile,wOf(holder.profile)+drift);
  var bad=G.filter(function(g){return wOf(g.profile)<FLOOR;});
  if(bad.length)return {ok:false,msg:"有游戏跌破地板 $"+fmt(FLOOR)+"："+bad.map(function(g){return g.name;}).join("、")};
  if(Math.abs(G.reduce(function(s,g){return s+wOf(g.profile);},0)-TOTAL)>0)return {ok:false,msg:"平账失败，合计未锁定到总目标。"};
  return {ok:true};
}

function derived(g){
  var rev=wOf(g.profile);
  var ord=Number.isFinite(g.aov)&&g.aov>0?Math.round(rev/g.aov):null;
  var prof=Number.isFinite(g.mar)?Math.max(Math.round(rev*g.mar/100/1000)*1000,0):null;
  return {ord:ord,prof:prof};
}
function feas(g){
  var rev=wOf(g.profile);
  if(!Number.isFinite(g.proj.rev)||g.proj.rev<=0)return {cls:"flat",txt:"预测未评估"};
  if(rev<=g.proj.rev*1.05)return {cls:"ok",txt:"预测内"};
  if(rev<=g.proj.rev*1.10)return {cls:"warn",txt:"贴近预测"};
  return {cls:"risk",txt:"超预测 "+Math.round(rev/g.proj.rev*100)+"%"};
}
function tierCls(t){return t==="S"?"t-S":t==="A"?"t-A":t==="B"?"t-B":"t-X";}

function render(){
  var tb=document.getElementById("tb");tb.innerHTML="";
  var list=G.filter(function(g){return curG==="ALL"||g.grp===curG;});
  var sumAct=0,sumFc=0,sumPub=0,sumMine=0,sumOrd=0,sumProf=0;
  list.forEach(function(g){
    var d=derived(g),f=feas(g),rev=wOf(g.profile);
    sumAct=Number.isFinite(sumAct)&&Number.isFinite(g.act.rev)?sumAct+g.act.rev:null;sumFc=Number.isFinite(sumFc)&&Number.isFinite(g.proj.rev)?sumFc+g.proj.rev:null;sumPub+=g.tgt.rev;sumMine+=rev;sumOrd=Number.isFinite(sumOrd)&&Number.isFinite(d.ord)?sumOrd+d.ord:null;sumProf=Number.isFinite(sumProf)&&Number.isFinite(d.prof)?sumProf+d.prof:null;
    var diff=rev-g.tgt.rev;
    var dcls=diff>0?"up":diff<0?"dn":"flat";
    var dtxt=diff===0?"—":(diff>0?"+":"−")+"$"+fmt(Math.abs(diff));
    var editedCls=(editedProfile===g.profile)?" edited":"";
    var tr=document.createElement("tr");
    tr.innerHTML='<td><div class="gname">'+g.name+'<span class="tag '+tierCls(g.tier)+'">'+g.tier+'</span></div>'+
      '<div class="meta">'+g.grp.replace("运营组","")+" · "+g.owner+" · "+g.regime+'</div></td>'+
      '<td class="r">$'+fmt(g.act.rev)+'</td>'+
      '<td class="r meta">$'+fmt(g.proj.rev)+'</td>'+
      '<td class="r meta">$'+fmt(g.tgt.rev)+'</td>'+
      '<td class="r"><input class="tgt'+editedCls+'" data-p="'+g.profile+'" value="'+rev+'" inputmode="numeric"></td>'+
      '<td class="r">'+fmt(d.ord)+'</td>'+
      '<td class="r">$'+fmt(d.prof)+'</td>'+
      '<td class="r delta '+dcls+'">'+dtxt+'</td>'+
      '<td class="r"><span class="pill '+f.cls+'">'+f.txt+'</span></td>';
    tb.appendChild(tr);
  });
  document.getElementById("footName").textContent=curG==="ALL"?"全盘 · "+G.length+" 款":curG+" · "+list.length+" 款";
  document.getElementById("fAct").textContent="$"+fmt(sumAct);
  document.getElementById("fFc").textContent="$"+fmt(sumFc);
  document.getElementById("fPub").textContent="$"+fmt(sumPub);
  document.getElementById("fMine").textContent="$"+fmt(sumMine);
  document.getElementById("fOrd").textContent=fmt(sumOrd);
  document.getElementById("fProf").textContent="$"+fmt(sumProf);
  // totals (always all 15)
  var tRev=G.reduce(function(s,g){return s+wOf(g.profile);},0);
  var tOrd=G.reduce(function(s,g){return Number.isFinite(s)&&Number.isFinite(derived(g).ord)?s+derived(g).ord:null;},0);
  var tProf=G.reduce(function(s,g){return Number.isFinite(s)&&Number.isFinite(derived(g).prof)?s+derived(g).prof:null;},0);
  var diff=tRev-TOTAL;
  document.getElementById("vTotal").textContent=fmt(tRev);
  document.getElementById("vOrd").textContent=fmt(tOrd);
  document.getElementById("vProf").textContent=fmt(tProf);
  var vd=document.getElementById("vDiff");
  var bc=document.getElementById("balTotal");
  if(diff===0){vd.textContent="$0 ✓ 已平账";vd.style.color="#9ff0d0";bc.className="bal-card bal-ok";}
  else{vd.textContent=(diff>0?"+":"−")+"$"+fmt(Math.abs(diff));vd.style.color="#ffc7bb";bc.className="bal-card bal-bad";}
  // warnings
  var over=G.filter(function(g){return Number.isFinite(g.proj.rev)&&wOf(g.profile)>g.proj.rev*1.10;});
  var wb=document.getElementById("warnBox");
  if(over.length){wb.style.display="block";
    wb.textContent="模拟提示：以下草稿目标超过当前线性情景的 110%，不是正式可行性结论："+over.map(function(g){return g.name+"（"+Math.round(wOf(g.profile)/g.proj.rev*100)+"%）";}).join("、");}
  else wb.style.display="none";
  if(draftError){wb.style.display="block";wb.textContent=draftError;}
  bindInputs();updateExport();
}

function bindInputs(){
  document.querySelectorAll("input.tgt").forEach(function(inp){
    inp.onchange=function(){
      var p=inp.getAttribute("data-p");var v=Number(inp.value);if(!Number.isFinite(v)||v<FLOOR||v>TOTAL){alert("请输入地板与总目标之间的有效金额");render();return;}
      v=Math.max(FLOOR,Math.round(v));
      editedProfile=p;
      var before=W.map(function(x){return {...x};});var r=rebalance(p,v);
      if(!r.ok){W=before;alert(r.msg);}
      saveDraft();render();
    };
  });
}
function updateExport(){
  var rows=G.map(function(g){var d=derived(g);return {profile:g.profile,name:g.name,grp:g.grp,owner:g.owner,rev:wOf(g.profile),ord:d.ord,prof:d.prof};});
  var payload={type:"FS_KPI_TARGET_SIMULATION_v1",status:"local_draft_only",assumptions:"latest_actual_linear_scenario_and_reference_margin",period:P.period,snapshotId:P.snapshotId,author:identity,total:G.reduce(function(s,g){return s+wOf(g.profile);},0),targets:rows};
  document.getElementById("export").value=JSON.stringify(payload,null,1);
}
function saveDraft(){try{localStorage.setItem(DRAFT,JSON.stringify(W));draftError="";}catch(e){draftError="本机草稿保存失败；当前更改仅在此页面内有效。";}}
function loadDraft(){try{var d=JSON.parse(localStorage.getItem(DRAFT));if(Array.isArray(d)&&d.length===W.length&&G.every(function(g){return d.filter(function(x){return x.profile===g.profile&&Number.isFinite(x.rev)&&x.rev>=FLOOR&&x.rev<=TOTAL;}).length===1;})&&d.reduce(function(s,x){return s+x.rev;},0)===TOTAL)W=d;}catch(e){}}
function reset(){try{localStorage.removeItem(DRAFT);draftError="";}catch(e){draftError="本机旧草稿清除失败；当前仅在页面内恢复原包目标。";}W=G.map(function(g){return {profile:g.profile,rev:g.tgt.rev};});editedProfile=null;render();}

document.getElementById("btnReset").onclick=reset;
document.getElementById("btnCopy").onclick=function(){
  var ta=document.getElementById("export");ta.select();
  try{if(!document.execCommand("copy"))throw Error("copy_failed");alert("模拟配置已复制；尚未修改任何正式目标。");}
  catch(e){alert("请手动全选复制下方文本框内容。");}
};
var onGroup=function(e){
  if(e.target.tagName!=="BUTTON")return;
  document.querySelectorAll("#gtab button").forEach(function(b){b.className="";});
  e.target.className="on";curG=e.target.getAttribute("data-g");render();
};document.getElementById("gtab").addEventListener("click",onGroup);
loadDraft();render();return {destroy:function(){document.getElementById("gtab").removeEventListener("click",onGroup);document.getElementById("btnReset").onclick=null;document.getElementById("btnCopy").onclick=null;},update:function(values){G.forEach(function(g){g.act=values[g.profile]||{rev:null,ord:null,prof:null};});render();},clear:function(){W=G.map(function(g){return {profile:g.profile,rev:g.tgt.rev};});G.forEach(function(g){g.act={rev:null,ord:null,prof:null};});render();}};

};
