# -*- coding: utf-8 -*-
"""统一出网入口（2026-10-16 建立）

只做两件事，都只在这一处实现：

【一】把连接收干净 —— 修 socket 泄漏
    urllib 在 HTTP 4xx/5xx 时抛 HTTPError，而 HTTPError 本身就是一个
    「响应体还没读」的 response 对象。旧代码写成：
        try:
            with urllib.request.urlopen(req, timeout=...): ...
        except Exception as e:
            last = e; time.sleep(...)        # ← 从不 read()/close()
    于是连接停在 ESTABLISHED，对端发来的响应体全部堆在本地 Recv-Q
    （2026-10-16 实测：9 条连接各堵 80~96KB，对端全是 mmoexp 的 CF IP
    104.18.30.246 / 104.18.31.246），socket 与 fd 只增不减。
    本模块的 urlopen() 在任何异常路径上先 drain + close，然后再抛。

【二】唯一出口开关 —— 换出口 IP 只改一处
    读环境变量 FS_OUTBOUND_PROXY：
        留空                  = 直连（默认，行为与改动前逐字节一致）
        http://host:port      = HTTP/HTTPS 代理
        socks5h://host:port   = SOCKS5（需 PySocks）
    设置后本进程所有出网都走它，业务代码一行不用动。
"""
import os
import urllib.error
import urllib.request

_PROXY = (os.environ.get("FS_OUTBOUND_PROXY") or "").strip()


def current_proxy():
    """当前出口（空串 = 直连）。"""
    return _PROXY


def proxy_handlers():
    """给自建 opener 用：返回 ProxyHandler 列表（无代理则空列表）。"""
    if not _PROXY:
        return []
    return [urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY})]


def _build():
    return urllib.request.build_opener(*proxy_handlers())


_OPENER = _build()


def drain_close(exc):
    """把响应体排干并关闭。HTTPError/URLError 都可能带着没读完的连接。"""
    if exc is None:
        return
    try:
        exc.read()
    except Exception:
        pass
    try:
        exc.close()
    except Exception:
        pass


def urlopen(req, timeout=None, **kw):
    """urllib.request.urlopen 的安全替代：4xx/5xx 一定 drain+close 后再抛。

    返回值与 urlopen 一致，调用方照常 `with ... as r:` 使用。
    """
    try:
        return _OPENER.open(req, timeout=timeout, **kw)
    except urllib.error.HTTPError as e:
        drain_close(e)
        raise
