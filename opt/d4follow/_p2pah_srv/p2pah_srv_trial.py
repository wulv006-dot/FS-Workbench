# -*- coding: utf-8 -*-
"""服务端「直连改价后台」验证脚本（在容器 p2pah-srv 内运行）

目标
----
证明**服务器自己**能完成整条改价链路，不再依赖本机执行器：
    登录（账号密码 + 图形验证码本地 OCR）
      → 读价（金币价格管理 / 物品列表）
      → 写价（金币采购成本）

设计原则
--------
1. **一行都不改本机执行器**：业务逻辑全部复用 `p2pah_local.py` / `p2pah_autologin.py`
   原文件（只 import，不修改）。容器特有的差异集中在下面 `SrvSession` 里：
     · 去掉 `channel="msedge"` —— 容器里只有 playwright 自带 chromium；
     · 补 `--no-sandbox`（容器内以 root 跑 chromium 必须给）。
2. **写操作是受控往返，不是单向改**：写探针值 → 读回复核 → **立刻还原原值** → 再复核。
   并且**不点「同步价格」、不清缓存** —— 按后台机制，这两步才是把变更推给前端的开关，
   不做就等于线上可见价格完全不变。
3. 任何一步异常，`finally` 里都会尽力把原值写回去。

子命令
------
  login   只登录（验证：服务端能否自己过图形验证码）
  read    登录 + 读「金币价格管理」全部服务区行 + 物品列表（纯只读）
  write   登录 + 读 + 受控往返写入（默认只预演；--confirm 才真写）
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time

import p2pah_local as P

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT_OUT = os.path.join(HERE, "srv_trial_result.json")


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


class SrvSession(P.Session):
    """容器版会话：唯一差别是浏览器通道与启动参数。"""

    def __init__(self, profile, keep_open=False):
        self._p = P.sync_playwright().start()
        self.ctx = self._p.chromium.launch_persistent_context(
            profile,
            headless=not keep_open,          # 容器无 X，必须 headless
            viewport={"width": 1400, "height": 950},
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--no-zygote"])
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self._inject_saved_cookies()
        self.auto_login = bool(P.AUTO_LOGIN[0]) and (P.autologin is not None)
        try:
            _a = P.autologin.accounts()["order"]
            self.user = _a.get("username") or ""
            self.pw = _a.get("password") or ""
        except Exception:
            self.user = self.pw = ""


def save(res):
    io.open(RESULT_OUT, "w", encoding="utf-8").write(
        json.dumps(res, ensure_ascii=False, indent=1))
    log("结果已存 → %s" % RESULT_OUT)


def do_login(s):
    """登录：先看是否已是登录态，否则用账号密码 + OCR 过验证码。"""
    log("=== 登录 ===")
    t0 = time.time()
    s.pg.goto(P.LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    s.pg.wait_for_timeout(1500)
    if "login.html" not in (s.pg.url or ""):
        log("已是登录态（无需重登）")
        return True, 0.0, "already"
    log("被弹到登录页 → 用账号密码 + ddddocr 自动识别验证码")
    ok = P.autologin.login_order_in(s.pg, s.user, s.pw, log=log)
    sec = time.time() - t0
    if ok:
        log("✅ 服务端自动登录成功（%.1fs）" % sec)
        s.save_cookies()
    else:
        log("✘ 服务端自动登录失败（%.1fs）" % sec)
    return ok, sec, "fresh"


def do_read(s):
    """只读：金币全部服务区行 + 物品列表。"""
    log("=== 读数据 ===")
    t0 = time.time()
    gold = s.gold_rows()
    log("金币价格管理：%d 行" % len(gold))
    for rid in sorted(gold):
        r = gold[rid]
        log("   行%-8s 采购成本=%-14s 利润率=%-10s b2c=%-16s %s"
            % (rid, r.get("costprice"), r.get("lirunlv"), r.get("b2c"),
               (r.get("title") or "")[:28]))

    rows = s.read_rows()
    log("物品列表第 1 页：%d 行（样例前 3）" % len(rows))
    for r in rows[:3]:
        log("   %-12s %-30s 价=%-12s 成本=%s"
            % (r["id"], (r["name"] or "")[:30], r["unit_price"], r["cprice"]))
    sec = time.time() - t0
    log("✅ 服务端抓取完成（%.1fs）" % sec)

    # 落盘：只留结构化摘要，便于外部比对（不落全量，避免体积大）
    return {"gold_n": len(gold),
            "gold": {rid: {"costprice": gold[rid].get("costprice"),
                           "b2c": gold[rid].get("b2c"),
                           "title": (gold[rid].get("title") or "")}
                     for rid in sorted(gold)},
            "item_n": len(rows),
            "item_sample": [{k: r.get(k) for k in ("id", "name", "unit_price", "cprice")}
                            for r in rows[:5]],
            "sec": round(sec, 1)}


def do_write(s, confirm=False):
    """受控往返写：探针值 → 复核 → 还原 → 复核。绝不点同步价格、绝不清缓存。"""
    log("=== 受控往返写（金币采购成本）===")
    gold = s.gold_rows()
    if not gold:
        log("✘ 读不到任何行，放弃")
        return {"ok": False, "msg": "no rows"}

    rid = sorted(gold)[0]
    orig = gold[rid].get("costprice")
    log("选定探针行：行ID=%s 名称=%s 原始采购成本=%s"
        % (rid, (gold[rid].get("title") or "")[:30], orig))
    if orig is None:
        log("✘ 原始值为空，放弃")
        return {"ok": False, "msg": "orig is None"}

    probe = "0.000123" if abs(float(orig) - 0.000123) > 1e-12 else "0.000456"
    log("探针值 = %s（与原值差 %.6f，足以判定是否真的落库）"
        % (probe, abs(float(probe) - float(orig))))

    res = {"row_id": rid, "title": (gold[rid].get("title") or ""),
           "orig": orig, "probe": probe, "confirmed": bool(confirm)}

    if not confirm:
        log("★ 预演结束（没加 --confirm，未发任何写请求）")
        res["ok"] = None
        return res

    restored = False
    try:
        log("① 写探针值 %s …" % probe)
        r1 = s.set_gold_cost(rid, probe)
        log("   返回 ok=%s msg=%s http=%s" % (r1.get("ok"), r1.get("msg"), r1.get("http")))
        time.sleep(2)
        a = s.gold_rows().get(rid) or {}
        got = a.get("costprice")
        log("② 读回复核：采购成本 = %s（%s）" % (got, "一致 ✅" if _eq(got, probe) else "不一致 ✘"))
        res["write_ok"] = bool(r1.get("ok"))
        res["after_write"] = got
        res["write_verified"] = _eq(got, probe)
    finally:
        log("③ 还原原值 %s …" % orig)
        try:
            r2 = s.set_gold_cost(rid, str(orig))
            log("   返回 ok=%s msg=%s" % (r2.get("ok"), r2.get("msg")))
        except Exception as e:
            log("   ✘✘ 还原异常（请立刻人工检查行%s）：%r" % (rid, e))
        time.sleep(2)
        try:
            b = s.gold_rows().get(rid) or {}
            got2 = b.get("costprice")
            restored = _eq(got2, orig)
            log("④ 还原复核：采购成本 = %s（%s）"
                % (got2, "已还原 ✅" if restored else "✘ 未还原，请人工检查！"))
            res["after_restore"] = got2
            res["restored"] = restored
        except Exception as e:
            log("   ✘ 还原复核异常：%r" % e)
            res["restored"] = False

    res["ok"] = bool(res.get("write_verified") and restored)
    log("⑤ 全程未点「同步价格」、未清缓存 —— 线上可见价格不受影响")
    return res


def _eq(a, b):
    try:
        return abs(float(a) - float(b)) <= 1e-12
    except Exception:
        return False


def _find_item(rows, rid):
    for r in rows:
        if str(r.get("id")) == str(rid):
            return r
    return None


def do_write_item(s, confirm=False):
    """物品价受控往返（另一个写接口 goodsEdit）。

    探针只挪动 1e-5（最小可判定位），写完立刻读回、再还原。
    同样**不清缓存** —— 按后台机制，不清缓存前端不会变。
    """
    log("=== 受控往返写（物品 $每个价格 / goodsEdit）===")
    rows = s.read_rows()
    if not rows:
        log("✘ 读不到物品行，放弃")
        return {"ok": False, "msg": "no rows"}
    row0 = rows[0]
    rid = str(row0["id"])
    gid = str(row0.get("gid") or "456")
    orig = float(row0["unit_price"])
    probe = round(orig + 0.00001, 5)
    if abs(probe - orig) < 1e-9:
        probe = round(orig - 0.00001, 5)
    log("选定探针行：ID=%s gid=%s 名称=%s" % (rid, gid, (row0["name"] or "")[:34]))
    log("原始 $每个价格 = %.5f → 探针 %.5f（差 %.5f）" % (orig, probe, abs(probe - orig)))

    res = {"row_id": rid, "gid": gid, "name": row0["name"], "orig": orig,
           "probe": probe, "confirmed": bool(confirm)}
    if not confirm:
        log("★ 预演结束（没加 --confirm，未发任何写请求）")
        res["ok"] = None
        return res

    restored = False
    try:
        log("① 写探针价 %.5f（goodsEdit）…" % probe)
        r1 = s.write_rows([{"id": int(rid), "gid": gid, "min_qty": 0,
                            "unit_price": "%.5f" % probe, "cprice": None}])
        log("   返回 ok=%s msg=%s http=%s" % (r1.get("ok"), r1.get("msg"), r1.get("http")))
        time.sleep(2)
        got = (_find_item(s.read_rows(), rid) or {}).get("unit_price")
        res["write_ok"] = bool(r1.get("ok"))
        res["after_write"] = got
        res["write_verified"] = _eq(got, probe)
        log("② 读回复核：$每个价格 = %s（%s）"
            % (got, "一致 ✅" if res["write_verified"] else "不一致 ✘"))
    finally:
        log("③ 还原原值 %.5f …" % orig)
        try:
            r2 = s.write_rows([{"id": int(rid), "gid": gid, "min_qty": 0,
                                "unit_price": "%.5f" % orig, "cprice": None}])
            log("   返回 ok=%s msg=%s" % (r2.get("ok"), r2.get("msg")))
        except Exception as e:
            log("   ✘✘ 还原异常（请立刻人工检查 ID=%s）：%r" % (rid, e))
        time.sleep(2)
        try:
            got2 = (_find_item(s.read_rows(), rid) or {}).get("unit_price")
            restored = _eq(got2, orig)
            log("④ 还原复核：$每个价格 = %s（%s）"
                % (got2, "已还原 ✅" if restored else "✘ 未还原，请人工检查！"))
            res["after_restore"] = got2
            res["restored"] = restored
        except Exception as e:
            log("   ✘ 还原复核异常：%r" % e)
            res["restored"] = False
    res["ok"] = bool(res.get("write_verified") and restored)
    log("⑤ 全程未清缓存 —— 线上可见价格不受影响")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["login", "read", "write", "writeitem"])
    ap.add_argument("--profile", default=os.path.join(HERE, "_srv_profile"))
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args()

    out = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "cmd": a.cmd,
           "host": os.uname()[1] if hasattr(os, "uname") else "?",
           "runner": "container"}
    s = SrvSession(a.profile, keep_open=False)
    try:
        ok, sec, how = do_login(s)
        out["login_ok"] = ok
        out["login_sec"] = round(sec, 1)
        out["login_how"] = how
        if not ok:
            out["ok"] = False
            log("✘ 登录没过，后续跳过")
            return 1
        if a.cmd in ("read", "write", "writeitem"):
            out["read"] = do_read(s)
        if a.cmd == "write":
            out["write"] = do_write(s, confirm=a.confirm)
            if a.confirm and not out["write"].get("ok"):
                return 1
        if a.cmd == "writeitem":
            out["writeitem"] = do_write_item(s, confirm=a.confirm)
            if a.confirm and not out["writeitem"].get("ok"):
                return 1
        out["ok"] = True
        return 0
    finally:
        try:
            s.close()
        except Exception:
            pass
        save(out)


if __name__ == "__main__":
    sys.exit(main())
