# -*- coding: utf-8 -*-
"""当期金币售价自动取价桥：订单后台 → 工作台 `rate` 输入框。

它在整条链路里的位置
---------------------------------------------------------
    网页「当期金币售价」输入框
        ↑ 预填（人工仍可覆盖）
    GET /api/coins-rate  →  本模块
        │  子进程（可超时 kill / 依赖隔离 / 独立演进）
        ▼
    /opt/mlb-admin-write/src/p2pah_price.py
        登录 order.p2pah.cn → 金币价格管理(GID 922) → 读 b2c → ×100 → USD/100K

为什么走子进程而不是 import
---------------------------------------------------------
1. **可超时 kill**：登录要过验证码、要连外网，挂住时 hub 不受影响。
2. **依赖隔离**：取价脚本要 `ddddocr`（过码），hub 保持标准库零依赖。
3. **口径隔离**：单位换算（b2c 是 USD/1K，工作台要 USD/100K）全在脚本内，
   hub 只做搬运和缓存 —— 换算错了只改一个地方。

★ 三条安全设计
---------------------------------------------------------
- **永不阻塞采集链路**：取价只是"预填一个输入框"，失败就退回人工填写，
  绝不影响建任务/采集/上架。
- **永不自动提交**：取到的价只填进输入框，**不做任何自动提交**。
- **原值一定回吐**：`b2c` 原值 + `multiplier` + 换算式都回吐给页面展示，
  人工一眼能看出换算是否合理（避免 100 倍级别的静默错误）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

#: 内存缓存：{at, data}。避免同一页面反复刷新时反复登录后台。
_CACHE = {"at": 0.0, "data": None}

#: ★ 失败负缓存（秒）。**这条不能少**：取价每次都要登录订单后台并过验证码，
#: 如果失败就立刻让前端重试，页面 5 秒一轮 = 每小时 720 次登录 ——
#: 很可能把后台账号试到锁定。失败后先冷却一段时间，期间直接回上次的失败结果。
FAIL_BACKOFF_SEC = 60
_NEG = {"at": 0.0, "data": None}


def cfg(config):
    """取 `server_config.coins_rate` 段，缺失给安全默认值。"""
    cr = (config or {}).get("coins_rate") or {}
    return {
        # ⚠️ 缺省 False：脚本/凭据没配好时宁可让人工填，也不要去连后台
        "enabled": bool(cr.get("enabled", False)),
        "python": cr.get("python") or sys.executable,
        "script": cr.get("script") or "",
        "cred": cr.get("cred") or "",
        "gid": int(cr.get("gid") or 922),
        "area": cr.get("area") or "PS 5",
        "multiplier": float(cr.get("multiplier") or 100),
        "timeout": int(cr.get("timeout") or 90),
        "cache_sec": int(cr.get("cache_sec") or 600),
        "cache_dir": cr.get("cache_dir") or "",
    }


def status(c):
    """给 `/api/health` 用的**布尔量**（不回路径）。"""
    return {
        "enabled": bool(c.get("enabled")),
        "script_ok": bool(c.get("script") and os.path.isfile(c["script"])),
        "cred_ok": bool(c.get("cred") and os.path.isfile(c["cred"])),
        "gid": c.get("gid"),
        "area": c.get("area"),
        "multiplier": c.get("multiplier"),
    }


def _cache_file(c):
    d = c.get("cache_dir")
    if not d:
        return None
    return os.path.join(d, "coins_rate.json")


def _read_disk(c):
    p = _cache_file(c)
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                 # noqa: BLE001
        return None


def _write_disk(c, data):
    p = _cache_file(c)
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:                                 # noqa: BLE001
        pass                                          # 缓存写不进去不影响主流程


def _fresh(c, data):
    if not isinstance(data, dict) or not data.get("ok"):
        return False
    at = float(data.get("_cached_at") or 0)
    return (time.time() - at) < max(0, c.get("cache_sec") or 0)


def _num(x):
    """整数值就不要写成 `100.0` —— 命令行与证据文件里读起来更清楚。"""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    return int(f) if f == int(f) else f


def build_cmd(c, out_path):
    return [c["python"], c["script"],
            "--gid", str(_num(c["gid"])),
            "--area", str(c["area"]),
            "--multiplier", str(_num(c["multiplier"])),
            "--cred", c["cred"],
            "--out", out_path,
            "--json"]


def fetch(c, *, log=print, out_dir=None):
    """真跑一次取价。**永不抛异常** —— 一切失败都变成可返回的字典。"""
    if not c.get("enabled"):
        return {"ok": False, "step": "disabled",
                "error": "服务端未开启自动取价（server_config.coins_rate.enabled）"}
    if not c.get("script") or not os.path.isfile(c["script"]):
        return {"ok": False, "step": "config",
                "error": "取价脚本不存在：%s" % (c.get("script") or "(未配置)")}
    if not c.get("cred") or not os.path.isfile(c["cred"]):
        return {"ok": False, "step": "config",
                "error": "订单后台凭据不存在：%s" % (c.get("cred") or "(未配置)")}

    out_path = os.path.join(out_dir or (c.get("cache_dir") or "."),
                            "coins_rate.raw.json")
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
    except Exception:                                 # noqa: BLE001
        pass

    cmd = build_cmd(c, out_path)
    started = time.time()
    log("[rate] 取价：gid=%s area=%s ×%s" % (c["gid"], c["area"], c["multiplier"]))
    stdout, rc, timed_out = "", None, False
    try:
        p = subprocess.run(cmd, cwd=os.path.dirname(c["script"]) or None,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=c.get("timeout") or 90)
        stdout = (p.stdout or b"").decode("utf-8", "replace")
        rc = p.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout = (e.stdout or b"").decode("utf-8", "replace") \
            if isinstance(e.stdout, bytes) else (e.stdout or "")
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "step": "spawn", "error": "%s: %r" % (type(e).__name__, e)}

    data = None
    # 1) 先看脚本 stdout 的最后一行（脚本契约：stdout 只出 JSON）
    for ln in reversed([x for x in stdout.strip().splitlines() if x.strip()]):
        try:
            data = json.loads(ln)
            break
        except Exception:                             # noqa: BLE001
            continue
    # 2) 兜底读 --out 文件
    if not isinstance(data, dict) and os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:                             # noqa: BLE001
            data = None

    if not isinstance(data, dict):
        return {"ok": False,
                "step": "timeout" if timed_out else "parse",
                "error": "取价脚本超时被 kill" if timed_out
                         else "取价脚本没有输出可用 JSON（returncode=%s）" % rc,
                "log_tail": [x for x in stdout.strip().splitlines() if x.strip()][-20:]}

    data["_cached_at"] = time.time()
    data["cached"] = False
    data["elapsed_sec"] = round(time.time() - started, 1)
    if data.get("ok"):
        _write_disk(c, data)
        log("[rate] OK  %s" % data.get("formula"))
    else:
        log("[rate] 失败 @%s：%s" % (data.get("step"), data.get("error")))
    return data


def get(c, *, force=False, log=print, out_dir=None):
    """带缓存的取价。`force=True` 跳过缓存（页面上的「重新取价」）。"""
    if not force and _fresh(c, _CACHE["data"]):
        return dict(_CACHE["data"], cached=True)
    if not force:
        disk = _read_disk(c)
        if _fresh(c, disk):
            _CACHE["data"] = disk
            return dict(disk, cached=True)
        # 失败负缓存：冷却期内不重复登录后台
        if _NEG["data"] and (time.time() - _NEG["at"]) < FAIL_BACKOFF_SEC:
            return dict(_NEG["data"], cached=True, backoff=True)

    data = fetch(c, log=log, out_dir=out_dir)
    if isinstance(data, dict):
        # ★ 新鲜度时间戳由**这里**盖，不能指望 fetch 记得盖 ——
        #   否则缓存判定会永远"不新鲜"，每次调用都重新登录后台。
        data["_cached_at"] = time.time()
    _CACHE["data"] = data
    _CACHE["at"] = time.time()
    if data.get("ok"):
        _NEG["data"] = None
    else:
        _NEG["at"] = time.time()
        _NEG["data"] = data
    return data
