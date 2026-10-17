# -*- coding: utf-8 -*-
"""DD373 风控实时探针（只读、极轻量：仅 2 个请求）

判定与线上采集完全一致 —— 直接复用 /opt/d4follow/core_dd373_cost.py 的
_get() / _short_url() / _blocked()，不自己另写一套，避免口径漂移。

输出：
  · 磁盘区服树缓存的更新时间（判断 url_seg 是否还新鲜）
  · 2 个不同大区商品短页的返回：字节数 / goods-list-item / sell-btn-box / blocked / 滑块特征 / title
"""
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, "/opt/d4follow")
import core_dd373_cost as C  # noqa: E402


def sniff(tag, url):
    t0 = time.time()
    try:
        h = C._get(url)
    except Exception as e:  # noqa: BLE001
        print("  [%s] 请求异常: %r" % (tag, e))
        return None
    dt = time.time() - t0
    h = h or ""
    has_goods = "goods-list-item" in h
    has_sell = "sell-btn-box" in h
    blk = C._blocked(h)
    hits = [k for k in ("滑动验证", "nocaptcha", "aliyunCaptcha", "AliyunCaptcha", "captcha") if k in h]
    m = re.search(r"<title>(.*?)</title>", h, re.S | re.I)
    title = (m.group(1).strip()[:90] if m else "n/a")
    print("  [%s] %s" % (tag, url))
    print("       返回 bytes=%d  用时=%.2fs" % (len(h), dt))
    print("       goods-list-item=%s  sell-btn-box=%s  ⇒  blocked=%s"
          % (has_goods, has_sell, blk))
    print("       滑块特征命中: %s" % (hits if hits else "无"))
    print("       title: %s" % title)
    return {"blocked": blk, "goods": has_goods, "sell": has_sell, "hits": hits, "bytes": len(h)}


def main():
    f = os.path.join("/opt/d4follow", "data", "dd373_zone_tree.json")
    print("== 区服树磁盘缓存 ==")
    print("  文件:", f, "存在:", os.path.exists(f))
    tree = {}
    try:
        j = json.load(io.open(f, encoding="utf-8"))
        ts = float(j.get("ts") or 0)
        tree = j.get("tree") or {}
        age = (time.time() - ts) / 3600.0 if ts else -1
        print("  更新时间:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "n/a",
              " (%.2f 小时前)" % age if age >= 0 else "")
        print("  区数:", len(tree))
    except Exception as e:  # noqa: BLE001
        print("  读取失败:", repr(e))

    # 从缓存里挑 2 个不同大区的真实游戏区段
    picks = []
    seen = set()
    for k in sorted(tree.keys()):
        area = k.split("|", 1)[0]
        if area in seen:
            continue
        v = tree[k]
        seg = v.get("url_seg")
        if not seg:
            continue
        seen.add(area)
        picks.append((area, k.split("|", 1)[1], seg))
        if len(picks) >= 2:
            break
    if not picks:
        picks = [("NA West", "siel(示例)", "m4rgrr")]

    print()
    print("== 实时探测（%d 个请求，间隔 %.1fs，与线上采集同频）==" % (len(picks), C.GAP_SAFE if hasattr(C, "GAP_SAFE") else 1.3))
    res = []
    for i, (area, name, seg) in enumerate(picks):
        if i:
            time.sleep(1.3)
        r = sniff("%s/%s" % (area, name), C._short_url(seg))
        res.append(r)

    print()
    ok = [r for r in res if r]
    blocked_n = sum(1 for r in ok if r["blocked"])
    normal_n = sum(1 for r in ok if not r["blocked"])
    print("== 结论 ==")
    print("  正常页 %d 个 / 被拦 %d 个" % (normal_n, blocked_n))
    if blocked_n and not normal_n:
        print("  ⛔ 仍在风控：返回的是阿里云 ESA 滑块验证页")
    elif normal_n and not blocked_n:
        print("  ✅ 已恢复：页面正常渲染（含 goods-list-item 或 sell-btn-box）")
    elif normal_n and blocked_n:
        print("  ⚠ 部分被拦：可能仍在限流边缘")
    else:
        print("  ⚠ 全部请求异常，无法判定（可能网络问题）")


if __name__ == "__main__":
    main()
