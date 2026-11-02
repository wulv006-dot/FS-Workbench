# -*- coding: utf-8 -*-
"""主后台清缓存兜底重试（systemd timer 驱动，默认每 10 分钟一次）。

背景：`writegold` 里清缓存命中后台频控时，两次尝试仍可能只拿到 code=0，
工单被记成 `publication_status=cache_failed`；而「一键清理所有」是幂等的，
只是频控窗口比当时的 31 秒长。价格本身已经写对了，缺的只是这最后一步。

本脚本只做一件事：把最近 3 小时内 `cache_failed` 的工单再清一次缓存，
成功就把 result_json 回填成 `cache_complete` 并落日志。不改价、不改 status。
"""
import io
import json
import os
import sqlite3
import sys
import time
import datetime
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/d4follow/_p2pah_srv")
sys.path.insert(0, "/opt/fs-order-session")

DB = "/opt/d4follow/data/iggm_follow.db"
LOG = "/opt/d4follow/logs/cache_retry.log"
WINDOW_H = 3
MAX_ATTEMPTS = 4
FIRST_WAIT = 35

# 2026-10-27：admin 域已切到数据中台 HMAC。8767 的 batoken 拿不到了（真实登录要过
# Google 2FA），清缓存改走本机签名代理；代理不在了才回退老的 batoken 通道。
DC_PROXY = "http://127.0.0.1:8911"
DC_CLEAR_PATH = "/admin/tools.Caches/clear?server=1"


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 5 * 1024 * 1024:
            os.replace(LOG, LOG + ".1")
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                  # noqa: BLE001
        pass


def connect():
    con = sqlite3.connect(DB, timeout=10.0)
    con.execute("PRAGMA busy_timeout=10000")
    return con


def dc_alive(timeout=5):
    try:
        with urllib.request.urlopen(DC_PROXY + "/__health", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")).get("ok") is True
    except Exception:                                  # noqa: BLE001
        return False


def dc_clear(timeout=40):
    """经签名代理清「一键清理所有」。返回 (http_status, body)。"""
    body = json.dumps({"type": "all", "file": ""}).encode()
    req = urllib.request.Request(DC_PROXY + DC_CLEAR_PATH, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    try:
        import admin_cache_local as A
    except Exception:                                  # noqa: BLE001
        A = None

    con = connect()
    rows = []
    try:
        for r in con.execute(
                "SELECT id, kind, finished_at, result_json FROM local_job"
                " WHERE instr(COALESCE(result_json, ''), '\"cache_failed\"') > 0"
                " AND COALESCE(finished_at, created_at) >= ?",
                ((datetime.datetime.now() - datetime.timedelta(hours=WINDOW_H))
                 .strftime("%Y-%m-%dT%H:%M:%S"),)):
            rows.append({"id": r[0], "kind": r[1], "finished_at": r[2],
                         "res": json.loads(r[3] or "{}")})
    except Exception as e:                             # noqa: BLE001
        log("读工单出错：%r" % (e,))
        return 1

    if not rows:
        return 0

    use_proxy = dc_alive()
    tok = None
    if not use_proxy and A is not None:
        try:
            tok = A.load_token()
        except Exception as e:                         # noqa: BLE001
            log("取不到 FS 全局会话：%r" % (e,))
    if not use_proxy and not tok:
        log("dc-proxy 与 FS 全局会话都不可用，本轮放弃（%d 单待清）" % len(rows))
        return 0
    log("清缓存通道：%s" % ("dc-proxy 签名代理" if use_proxy else "FS 8767 batoken"))

    for row in rows:
        jid = row["id"]
        res = row["res"]
        tries = int(res.get("cache_retry_attempts") or 0)
        if tries >= MAX_ATTEMPTS:
            log("%s 已重试 %d 次仍不确认，停止自动重试（需人工看后台频控）" % (jid, tries))
            continue

        ok, note = False, ""
        for attempt in range(2):
            try:
                if use_proxy:
                    status, body = dc_clear()
                else:
                    status, body = A.clear_cache("all", tok)
            except Exception as e:                     # noqa: BLE001
                log("%s 第 %d 次调用异常：%r" % (jid, attempt + 1, e))
                break
            try:
                j = json.loads(body)
            except Exception:                          # noqa: BLE001
                j = {}
            code = j.get("code") if isinstance(j, dict) else None
            note = "http=%s code=%s msg=%s" % (status, code, (j.get("msg") or "")[:40] if isinstance(j, dict) else "")
            log("%s 第 %d 次清缓存：%s" % (jid, attempt + 1, note))
            if status == 200 and code == 1:
                ok = True
                break
            if attempt == 0:
                time.sleep(FIRST_WAIT)

        res["cache_retry_attempts"] = tries + 1
        res["cache_retry_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        res["cache_retry_note"] = note
        if ok:
            res["clearcache_ok"] = True
            res["publication_status"] = "cache_complete"
            res["cache_retry_result"] = "confirmed"
        else:
            res["cache_retry_result"] = "unconfirmed"
        try:
            con.execute("update local_job set result_json=? where id=?",
                        (json.dumps(res, ensure_ascii=False), jid))
            con.commit()
        except Exception as e:                         # noqa: BLE001
            log("%s 回填失败：%r" % (jid, e))
            continue

        log("%s 结论：%s" % (jid, "cache_complete（已回填）" if ok else "仍 unconfirmed（下一轮再试）"))
        try:
            import msg_alert
            if ok:
                msg_alert.alert(con, "cache-retry-ok-%s" % jid,
                                "RPG 清缓存已补清成功",
                                "%s 原先 publication_status=cache_failed，本轮补清确认为 cache_complete。\n价格此前已写入并复核通过，无需重发工单。" % jid,
                                cooldown_s=3600)
            elif res["cache_retry_attempts"] >= MAX_ATTEMPTS:
                msg_alert.alert(con, "cache-retry-giveup-%s" % jid,
                                "RPG 清缓存连续失败，需人工",
                                "%s 自动重试 %d 次仍未确认，最后一次：%s\n请到主后台手动点「缓存管理 → 一键清理所有」。" % (jid, res["cache_retry_attempts"], note),
                                cooldown_s=3600)
        except Exception:                              # noqa: BLE001
            pass

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
