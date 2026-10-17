# -*- coding: utf-8 -*-
"""统一出网入口（2026-10-16 建立，2026-10-17 增补 Worker 出网）

只做三件事，都只在这一处实现：

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

【三】Cloudflare Worker 出网（2026-10-17 新增）—— 按域名分流
    背景：CF 把本机机房 IP 打进 managed challenge，mmoexp / p2pah / u4gm
      直连恒返 403（实测**换 TLS 指纹无效**：curl_cffi 的 Chrome 指纹一样 403；
      换出口才有效）。经 CF 自家网络的 Worker 出网实测 200 + 真页面。
    开关：`data/outbound_worker.json`，**文件不存在 = 完全关闭**（默认行为一字不差）
        {"worker": "https://cf-proxy.xxx.workers.dev", "key": "<secret>"}
    范围：只对 _WORKER_HOSTS 里的域生效，其余域照旧直连（IGGM / DD373 等不受影响）。
    传输：必须 curl_cffi —— CentOS 7 的 OpenSSL 1.0.2k / curl 7.29 连 workers.dev
      会 SSL_ERROR_NO_CYPHER_OVERLAP（不支持其 TLS 1.3 套件），urllib 连不上。
    ⚠ Worker 不可用 / 报错时**自动退回直连**，绝不因为代理挂了而改变原有行为。
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

_PROXY = (os.environ.get("FS_OUTBOUND_PROXY") or "").strip()

# ---------------------------------------------------------------- Worker 出网
_WORKER_HOSTS = ("mmoexp.com", "p2pah.com", "u4gm.com")
_WORKER_CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "outbound_worker.json")
_CFG = {"mtime": None, "val": (None, None)}


def _worker_conf():
    """读 Worker 配置（带 mtime 缓存）。返回 (基址, 密钥)；未配置返回 (None, None)。"""
    try:
        mt = os.path.getmtime(_WORKER_CONF)
    except OSError:
        return None, None
    if _CFG["mtime"] != mt:
        try:
            with open(_WORKER_CONF, encoding="utf-8") as fh:
                d = json.load(fh) or {}
            _CFG["val"] = ((d.get("worker") or "").strip(),
                           (d.get("key") or "").strip())
        except Exception:
            _CFG["val"] = (None, None)
        _CFG["mtime"] = mt
    w, k = _CFG["val"]
    return (w, k) if (w and k) else (None, None)


def _need_worker(url):
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return any(h == x or h.endswith("." + x) for x in _WORKER_HOSTS)


class _BufResp(object):
    """把 Worker 拿到的字节包成 urlopen 响应的形状（只实现调用方用到的接口）。"""

    def __init__(self, body, status=200, headers=None, url=""):
        self._body = body or b""
        self.status = status
        self.code = status
        self.headers = headers or {}
        self._url = url

    def read(self, n=None):
        return self._body if n is None else self._body[:n]

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def info(self):
        return self.headers

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _unpack(req):
    """统一 str / urllib.request.Request 两种传参。"""
    if hasattr(req, "full_url"):
        return (req.full_url, req.data, dict(getattr(req, "headers", {}) or {}),
                req.get_method())
    return str(req), None, {}, "GET"


def _worker_open(url, data, hdrs, method, timeout):
    """经 Worker 取一次。任何失败都返回 None（调用方退回直连）。"""
    base, key = _worker_conf()
    if not base:
        return None
    try:
        from curl_cffi import requests as _cq
    except Exception:
        return None
    purl = (base.rstrip("/") + "/proxy?u=" + urllib.parse.quote(url, safe="")
            + "&k=" + key)
    try:
        r = _cq.request(method, purl, data=data, headers=dict(hdrs or {}),
                        impersonate="chrome", timeout=(timeout or 60))
        return _BufResp(r.content, r.status_code, dict(r.headers or {}), url)
    except Exception:
        return None


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

    若目标是 _WORKER_HOSTS 里被 CF 挑战的域，且 outbound_worker.json 已配置，
    则改由 Cloudflare Worker 出网（结果形状与 urlopen 一致）。
    返回值与 urlopen 一致，调用方照常 `with ... as r:` 使用。
    """
    url, data, hdrs, method = _unpack(req)
    if _need_worker(url):
        resp = _worker_open(url, data, hdrs, method, timeout)
        if resp is not None:
            if 200 <= resp.status < 400:
                return resp
            # Worker 拿到了明确的失败码：与直连 HTTPError 语义保持一致，
            # 让上层的重试 / 熔断逻辑照常生效。
            raise urllib.error.HTTPError(url, resp.status,
                                         "worker upstream %s" % resp.status,
                                         resp.headers, None)
    try:
        return _OPENER.open(req, timeout=timeout, **kw)
    except urllib.error.HTTPError as e:
        drain_close(e)
        raise
