# -*- coding: utf-8 -*-
"""货架自检告警的微信通知（Server酱 · P1）

- 通道：Server酱（https://sctapi.ftqq.com/<SendKey>.send）
- 策略：**仅新增/变化时推**（用户 2026-10-01 拍板）
  同一签名（kind|key|row_id|front_name）内容不变 → 不推；
  签名消失后又出现 → 算新增，再推。
- 失败绝不影响主流程（网络异常只记日志）。
"""
import json
import re
import urllib.parse
import urllib.request

SCT_API = "https://sctapi.ftqq.com/%s.send"
TIMEOUT = 8


def _sig(x):
    """告警签名：内容变了才算「变化」"""
    return "|".join([
        str(x.get("kind") or ""), str(x.get("key") or ""),
        str(x.get("row_id") or ""), str(x.get("front_name") or ""),
        str(x.get("pack_size") or ""),
    ])


def _esc(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(sendkey, title, desp):
    """Server酱推送。返回 (ok, msg)。sendkey 为空直接跳过。"""
    if not sendkey:
        return False, "未配置 SendKey"
    url = SCT_API % sendkey
    data = urllib.parse.urlencode({"title": title[:32], "desp": desp}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "ignore")
        try:
            j = json.loads(body)
            # Server酱成功码：code=0
            ok = (j.get("code") == 0) or (j.get("data") and j["data"].get("pushid"))
            return bool(ok), body[:200]
        except Exception:
            return ("success" in body.lower()), body[:200]
    except Exception as e:
        return False, repr(e)


def notify_new(cfg, drift_items, prev_sigs, log=None):
    """按「仅新增/变化」策略推送。

    参数：
      cfg          配置 dict（读 cfg['报警']['微信SendKey'] / ['启用']）
      drift_items  本轮全部告警 [{kind,game,key,row_id,front_name,pack_size,detail}]
      prev_sigs    上轮已推过的签名集合（set）
    返回 dict：{"推送": n, "跳过": m, "签名": [所有本轮签名], "err": str|None}
    """
    def _lg(m):
        if log:
            log(m)

    al = (cfg.get("报警") or {})
    if not al.get("启用", True):
        return {"推送": 0, "跳过": len(drift_items or []), "签名": [], "err": "报警已关闭"}
    key = al.get("微信SendKey") or ""
    if not key:
        return {"推送": 0, "跳过": len(drift_items or []), "签名": [], "err": "未配置微信SendKey"}
    if not al.get("货架自检告警", True):
        return {"推送": 0, "跳过": len(drift_items or []), "签名": [], "err": "货架自检告警已关闭"}

    prev = set(prev_sigs or [])
    all_sigs, news = [], []
    for x in (drift_items or []):
        s = _sig(x)
        all_sigs.append(s)
        if s not in prev:
            news.append(x)
    if not news:
        return {"推送": 0, "跳过": len(drift_items or []), "签名": all_sigs, "err": None}

    # 组装 markdown
    by_kind = {"unmapped_shelf": [], "mismatched_pack": [], "orphan_row": []}
    for x in news:
        (by_kind.get(x.get("kind")) or by_kind["unmapped_shelf"]).append(x)
    lines = ["## 货架自检发现 %d 项新问题" % len(news), ""]
    label = {"unmapped_shelf": "🟠 未纳管档位", "mismatched_pack": "🔴 映射错位",
             "orphan_row": "⚠️ 人工价暴露"}
    for kind, arr in by_kind.items():
        if not arr:
            continue
        lines.append("### %s（%d）" % (label.get(kind, kind), len(arr)))
        for x in arr:
            lines.append("- %s" % x.get("detail"))
        lines.append("")
    lines.append("---")
    lines.append("系统不会自动改配置。请在改价页顶部查看并手动点「纳管」。")
    title = "【改价系统】货架自检 %d 项" % len(news)
    ok, msg = send(key, title, "\n".join(lines))
    if not ok:
        _lg("  ⚠ 微信推送失败：%s" % msg)
    return {"推送": (len(news) if ok else 0), "跳过": len(drift_items or []) - len(news),
            "签名": all_sigs, "err": None if ok else str(msg)}
