# -*- coding: utf-8 -*-
"""Sales HTTP clients using the global Admin and Order sessions only."""
from __future__ import annotations

import sys as _order_sys
from pathlib import Path as _OrderPath
for _order_root in ('/opt/fs-order-session', '/opt/fc27-collector', '/opt/madden-workbench', '/srv'):
    if _OrderPath(_order_root, 'fs_order_client.py').is_file():
        _order_sys.path.insert(0, _order_root)
        break
import fs_order_client as _global_order

import time

import requests
import urllib3

urllib3.disable_warnings()


ADMIN_SITE = "https://admin.p2pah.cn"
ADMIN_API = "https://admin-api.p2pah.cn"
ORDER_SITE = "https://order.p2pah.cn"


# 唯一登录方：server 侧会话服务

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def admin_token_from_service(timeout=8.0):
    from shared_admin import admin_token_from_service as read_shared
    return read_shared(timeout)


def needs_new_token(result) -> bool:
    """这个响应是不是「token 失效」而不是业务失败。"""
    try:
        status, js = result
    except Exception:
        return False
    if status in (301, 302, 401, 403):
        return True
    if isinstance(js, dict):
        msg = str(js.get("msg") or "")
        if js.get("code") != 1 and any(k in msg for k in ("登录", "token", "Token", "过期", "失效")):
            return True
    return False


# ------------------------------------------------------------------ Session
class Session:
    def __init__(self):
        self.token = None
        self.admin = requests.Session()
        self.admin.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Origin": ADMIN_SITE,
            "Referer": ADMIN_SITE + "/",
            "server": "1",
            "think-lang": "zh-cn",
        })
        # 保留 keep-alive：每页 5.5s → 约 3s，发货 177 页省掉一半时间
        # （旧版本照抄了本地 `Connection: close`，每请求重做 TCP+TLS 握手）
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
        self.admin.mount("https://", adapter)
        self.order = requests.Session()
        self.order.headers.update({
            "User-Agent": UA,
            "Referer": ORDER_SITE + "/",
        })
        self.order.mount("https://", requests.adapters.HTTPAdapter(
            pool_connections=4, pool_maxsize=8, max_retries=0))

    # ---------------- admin 侧（JSON） ----------------
    def bind_admin_token(self, token) -> bool:
        token = str(token or "")
        if not token or token == self.token:
            return False
        self.token = token
        return True

    def get_admin(self, path, **params):
        result = self._get_admin_once(path, params)
        if needs_new_token(result):
            tok, why = admin_token_from_service()
            if tok and self.bind_admin_token(tok):
                log("admin token 已轮换，重试一次 %s" % path)
                result = self._get_admin_once(path, params)
            elif why:
                log("admin token 失效且会话服务未就绪（%s），不自行登录" % why)
        return result

    def _get_admin_once(self, path, params):
        h = {"batoken": self.token or ""}
        for i in range(3):
            try:
                r = self.admin.get(ADMIN_API + path, params=params, headers=h, timeout=60)
                try:
                    return r.status_code, r.json()
                except Exception:
                    return r.status_code, {"_raw": r.text[:400]}
            except Exception as e:
                if i == 2:
                    return 0, {"_err": "%s: %s" % (type(e).__name__, e)}
                time.sleep(1.2 * (i + 1))

    def post_admin(self, path, payload=None, **params):
        result = self._post_admin_once(path, payload, params)
        if needs_new_token(result):
            tok, why = admin_token_from_service()
            if tok and self.bind_admin_token(tok):
                log("admin token 已轮换，重试一次 POST %s" % path)
                result = self._post_admin_once(path, payload, params)
        return result

    def _post_admin_once(self, path, payload, params):
        h = {"batoken": self.token or "", "Content-Type": "application/json"}
        for i in range(3):
            try:
                r = self.admin.post(ADMIN_API + path, json=payload or {}, params=params,
                                    headers=h, timeout=90)
                try:
                    return r.status_code, r.json()
                except Exception:
                    return r.status_code, {"_raw": r.text[:400]}
            except Exception as e:
                if i == 2:
                    return 0, {"_err": "%s: %s" % (type(e).__name__, e)}
                time.sleep(1.2 * (i + 1))

    # ---------------- order 侧（HTML） ----------------
    def get_order(self, path, **params):
        _global_order.fill_jar(self.order.cookies)
        for i in range(3):
            try:
                r = self.order.get(ORDER_SITE + path, params=params,
                                   timeout=120, verify=False)
                return r.status_code, r.text
            except Exception as e:
                if i == 2:
                    return 0, ""
                time.sleep(1.5 * (i + 1))

    def order_alive(self) -> bool:
        st, txt = self.get_order("/order/admin_delivery/index.html", gid="826", page="1",
                                 start="2026-10-01 00:00", end="2026-10-02 23:59",
                                 genre="1", aid="0", cid="1", status="-1", op_id="0",
                                 show_ccy="-1", is_stock="", keyword="", sn="")
        return st == 200 and 'name="password"' not in txt and "table-list" in txt

    # ---------------- 保存 ----------------

    def close(self) -> None:
        for s in (self.admin, self.order):
            try:
                s.close()
            except Exception:
                pass


def bootstrap(reuse: bool = True) -> Session:
    s = Session()
    try:
        token, _ = admin_token_from_service()
        if not token:
            raise RuntimeError('shared_admin_unavailable')
        s.bind_admin_token(token)
        _global_order.fill_jar(s.order.cookies)
        return s
    except Exception:
        s.close()
        raise


