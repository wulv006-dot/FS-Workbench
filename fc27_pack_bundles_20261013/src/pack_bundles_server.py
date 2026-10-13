#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FC27 捆绑包定价工具（一期 · 只读定价，不写后台）

数据链路：
  1. Futbin 数据库（默认 http://139.28.18.234:8001，老大自建采集库）
     GET /api/export/players.json  → 全量球员快照（gzip），按 futbin_id 建 map
     字段：ps_price / pc_price / xbox_price（金币原值，非 K）
     口径：PS/Xbox 共用 ps_price（库内 xbox 大多为空，与腾讯文档口径一致），PC 用 pc_price
  2. 我方后台金币单价：/var/lib/fc27-cloud/monitor/storefront.json
     rows.<PS|XBOX|PC>.usd_per_k（USD/千币，FC27 云端采集自动产出）
  3. 计价公式（腾讯文档「捆绑包」prices 表，2026-10-13 逆向确认）：
     球员页实际售价 = 金币数/1000 × 金币单价 × 1.1
     球员页划线价   = 实际售价 / 0.9
     捆绑包页面售价 = Σ(球员划线价) × 0.8        ← 商品页红价
     捆绑包页面原价 = 页面售价 / 0.7             ← 商品页灰划线价（角标 30% OFF）
     对比实际让利   = (页面售价 − Σ球员实际售价) / Σ球员实际售价
     中间链路不舍入（与表格一致），仅展示层保留 2 位小数。

接口（前置 nginx auth_request，本服务只绑 127.0.0.1）：
  GET  /health
  GET  /api/state
  GET  /api/search?q=
  POST /api/config    {expected_revision, settings?, bundles?}
  POST /api/refresh
"""

import argparse
import gc
import gzip
import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TZ8 = timezone(timedelta(hours=8))
HTTP_TIMEOUT = 180
MAX_BODY = 1024 * 1024
HISTORY_CAP = 48
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
WRITE_LOCK = threading.Lock()

DEFAULT_SETTINGS = {
    "interval_hours": 1,
    "futbin_base": "http://139.28.18.234:8001",
    "storefront_path": "/var/lib/fc27-cloud/monitor/storefront.json",
    # 计价系数（与腾讯文档公式一一对应；改前先和老大对齐）
    "markup_player_actual": "1.1",
    "player_strike_divisor": "0.9",
    "bundle_sale_factor": "0.8",
    "bundle_orig_divisor": "0.7",
    # ---- 二期：订单后台 b2c 取价（优先于 storefront）----
    "order_price_enabled": True,
    "order_gid": 1322,              # 订单后台 FC27（≠商品后台 1327）
    "cred_path": "/opt/mlb-admin-write/_cred.json",
    # ---- 二期：Admin 后台自动改价（四道闸门，默认全关）----
    "write_enabled": False,         # 总开关
    "write_dry_run": True,          # 试运行（只算不写）
    "write_auto": False,            # 采集后自动写（否则只能手动触发）
}

# 站点-ALL 上的捆绑包产品 aid（商品后台 goods.Goods，gid=1327 / cid=10255 Packs）
AID_PLATFORM = {21587: "ps", 21585: "xbox", 21589: "pc"}
PLATFORM_AID = {v: k for k, v in AID_PLATFORM.items()}


def now8():
    return datetime.now(TZ8)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def atomic_write(path, data: bytes, mode=0o644):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))
    try:
        os.chmod(str(path), mode)
    except OSError:
        pass


def load_json(path: Path, default):
    try:
        with open(str(path), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def dec(value):
    """转 Decimal；失败返回 None。"""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def money2(value: Decimal):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Store:
    """配置 / 缓存 / 刷新结果的进程内状态。"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.config_path = data_dir / "config.json"
        self.players_path = data_dir / "futbin_players.json.gz"
        self.refresh_path = data_dir / "last_refresh.json"
        self.history_path = data_dir / "history.json"
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.players = {}       # futbin_id -> slim dict
        self.rates = {}         # platform -> {usd_per_k, checked_at, status}
        self.storefront_meta = {}
        cfg = load_json(self.config_path, None)
        if cfg is None or "bundles" not in cfg:
            cfg = self._default_config()
            self._save_config(cfg)
        else:
            # 轻迁移：**键缺失**的 bundle 才从默认表补 products（Codex #9：
            # 操作员故意清空绑定的 products:{} 是有效状态，不能被重启重填回默认 ID）
            defaults = {b["id"]: b.get("products")
                        for b in self._default_config()["bundles"]}
            for b in cfg.get("bundles") or []:
                if isinstance(b, dict) and "products" not in b:
                    if b.get("id") in defaults:
                        b["products"] = defaults[b["id"]]
            self._save_config(cfg)
        self.config = cfg
        # 启动时尽量把缓存捡回来（没有也不阻塞服务）
        self._load_players_cache()
        self._load_rates(force_read=True)
        self._sweep_stale_running()

    def _sweep_stale_running(self):
        """开机清扫：上一进程被 OOM/重启打断时 last_refresh 会卡在 running，
        调度器判 due=False → 永不自动刷新（MLB §10.6 同款教训）。
        本进程启动时未见任何在跑线程 ⇒ 标记 interrupted 让调度恢复。
        """
        last = load_json(self.refresh_path, None)
        if isinstance(last, dict) and last.get("status") == "running":
            last["status"] = "interrupted"
            last["note"] = ("startup sweep: previous run interrupted "
                            "(OOM/restart? see journalctl -u fc27-pack-bundles)")
            atomic_write(str(self.refresh_path),
                         json.dumps(last, ensure_ascii=False, indent=2).encode("utf-8"))

    # ---------- 默认配置（首次启动预置腾讯文档两个捆绑包） ----------

    def _default_config(self):
        return {
            "revision": 1,
            "settings": dict(DEFAULT_SETTINGS),
            "bundles": [
                {
                    "id": "mancity11",
                    "title": "ManCity11-PlayerBundle",
                    "products": {"ps": 185327193, "xbox": 185327229, "pc": 185327265},
                    "players": [
                        {"futbin_id": 1, "position": "ST"},
                        {"futbin_id": 67, "position": "GK"},
                        {"futbin_id": 256, "position": "RW"},
                        {"futbin_id": 594, "position": "CB"},
                        {"futbin_id": 436, "position": "LW"},
                        {"futbin_id": 224, "position": "CB"},
                        {"futbin_id": 21975, "position": "CM"},
                        {"futbin_id": 223, "position": "RW"},
                        {"futbin_id": 439, "position": "CB"},
                        {"futbin_id": 21982, "position": "LM"},
                        {"futbin_id": 438, "position": "CB"},
                    ],
                },
                {
                    "id": "paris11",
                    "title": "Paris11-Player Bundle",
                    "products": {"ps": 185327085, "xbox": 185327121, "pc": 185327157},
                    "players": [
                        {"futbin_id": 31, "position": "ST"},
                        {"futbin_id": 39, "position": "LB"},
                        {"futbin_id": 44, "position": "CM"},
                        {"futbin_id": 25, "position": "CB"},
                        {"futbin_id": 49, "position": "LW"},
                        {"futbin_id": 97, "position": "CM"},
                        {"futbin_id": 102, "position": "RB"},
                        {"futbin_id": 774, "position": "CM"},
                        {"futbin_id": 1061, "position": "GK"},
                        {"futbin_id": 651, "position": "CB"},
                        {"futbin_id": 654, "position": "ST"},
                    ],
                },
            ],
        }

    # ---------- 配置读写 ----------

    def _save_config(self, cfg):
        atomic_write(str(self.config_path),
                     json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"))

    def settings(self):
        with self.lock:
            merged = dict(DEFAULT_SETTINGS)
            merged.update(self.config.get("settings") or {})
            return merged

    def interval_seconds(self):
        try:
            hours = float(self.settings().get("interval_hours") or 1)
        except (TypeError, ValueError):
            hours = 1.0
        # ⚠️ 下限对齐校验器的 0.1 小时（Codex #8）：原 max(1.0, …) 会把
        #    0.5 小时静默抬成 1 小时——设置显示已保存却不生效。
        return max(0.1, hours) * 3600.0

    def save_config(self, payload):
        """校验并保存整份配置，返回新 revision。"""
        with self.lock:
            current_rev = int(self.config.get("revision") or 1)
            expected = payload.get("expected_revision")
            if expected is None or int(expected) != current_rev:
                raise ValueError("revision_conflict")
            new_cfg = {
                "revision": current_rev + 1,
                "settings": dict(self.settings()),
                "bundles": list(self.config.get("bundles") or []),
            }
            if "settings" in payload:
                new_cfg["settings"] = validate_settings(payload["settings"],
                                                        new_cfg["settings"])
            if "bundles" in payload:
                new_cfg["bundles"] = validate_bundles(payload["bundles"])
            self._save_config(new_cfg)
            self.config = new_cfg
            return new_cfg["revision"]

    # ---------- Futbin 缓存 ----------

    def _load_players_cache(self):
        try:
            raw = gzip.open(str(self.players_path), "rb").read()
        except OSError:
            try:  # 兼容历史误写的裸 JSON
                raw = self.players_path.read_bytes()
            except OSError:
                self.players = {}
                return
        try:
            loaded = json.loads(raw.decode("utf-8"))
            # JSON 对象键恒为字符串，统一转回 int（下载时是 int 键）
            self.players = {int(k): v for k, v in loaded.items()}
        except (ValueError, TypeError, AttributeError):
            self.players = {}

    def futbin_updated_at(self):
        try:
            return datetime.utcfromtimestamp(self.players_path.stat().st_mtime)
        except OSError:
            return None

    def download_players(self, base):
        url = base.rstrip("/") + "/api/export/players.json"
        req = urllib.request.Request(url, headers={"User-Agent": "fc27-pack-bundles/1.0"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
        try:
            raw = gzip.decompress(body)
        except OSError:
            raw = body
        data = json.loads(raw.decode("utf-8"))
        items = data if isinstance(data, list) else data.get("items") or []
        slim = {}
        for it in items:
            fid = it.get("futbin_id")
            if not isinstance(fid, int):
                continue
            slim[fid] = {
                "futbin_id": fid,
                "name": it.get("common_name") or it.get("name") or "",
                "rating": it.get("rating"),
                "position": it.get("position") or "",
                "version": it.get("rare_type_name") or "",
                "ps_price": _num_or_none(it.get("ps_price")),
                "pc_price": _num_or_none(it.get("pc_price")),
                "xbox_price": _num_or_none(it.get("xbox_price")),
                "image": it.get("image") or "",
                "source_updated_at": it.get("updated_at") or "",
            }
        if not slim:
            raise ValueError("futbin_export_empty")
        # ★ 内存：22.7MB 原文 + 全量 dict 峰值可达数百 MB（曾 OOM 被内核 KILL），
        #   落盘后立刻释放大对象，压低峰值。
        del data, items, raw
        gc.collect()
        payload = json.dumps(slim, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        atomic_write(str(self.players_path), gzip.compress(payload))
        with self.lock:
            self.players = slim
        return len(slim)

    # ---------- 金币单价 ----------

    def _load_rates(self, force_read=False):
        path = Path(self.settings().get("storefront_path") or
                    DEFAULT_SETTINGS["storefront_path"])
        try:
            st = path.stat().st_mtime
        except OSError:
            return self.rates
        if not force_read and getattr(self, "_rates_mtime", None) == st:
            return self.rates
        data = load_json(path, None)
        rows = (data or {}).get("rows") or {}
        rates = {}
        for plat in ("PS", "XBOX", "PC"):
            row = rows.get(plat) or {}
            # ⚠️ 口径（2026-10-13 老大纠正）：金币单价 = 页面标价 ÷ 标称金币量
            # （package_usd / base_k），**赠送的 bonus 金币不能摊进去**。
            # storefront.json 自带的 usd_per_k 是 package_usd/(base_k+bonus_k)，
            # 会把单价压低（12.57÷105=0.1197 ✗，应为 12.57÷100=0.1257 ✓）。
            package = dec(row.get("package_usd"))
            base_k = dec(row.get("base_k"))
            if package and base_k:
                usd_per_k = package / base_k  # 赠送不计入
                basis = "package/base_k"
            else:  # 字段缺失才退回文件自带值（含赠送，标注出来）
                usd_per_k = dec(row.get("usd_per_k"))
                basis = "storefront_usd_per_k(includes_bonus)"
            rates[plat] = {
                "usd_per_k": str(usd_per_k.quantize(Decimal("0.000001"),
                                rounding=ROUND_HALF_UP)) if usd_per_k else None,
                "basis": basis,
                "package_usd": str(row.get("package_usd") or "") or None,
                "base_k": str(row.get("base_k") or "") or None,
                "bonus_k": str(row.get("bonus_k") or "") or None,
                "status": row.get("status"),
                "checked_at": row.get("checked_at"),
                "error": row.get("error"),
            }
        with self.lock:
            self.rates = rates
            self.storefront_meta = {
                "source": (data or {}).get("source"),
                "collection_run_id": (data or {}).get("collection_run_id"),
                "last_attempt_at": (data or {}).get("last_attempt_at"),
                "file_mtime": fmt_ts(datetime.utcfromtimestamp(st)),
            }
            self._rates_mtime = st
        return self.rates

    def get_rates(self):
        with self.lock:
            self._load_rates()
            return json.loads(json.dumps(self.rates)), \
                json.loads(json.dumps(self.storefront_meta))

    def _overlay_order_b2c(self, rates, summary):
        """订单后台 b2c（gid=settings.order_gid）优先覆盖金币单价。

        ⚠️ 频控：b2c 只在 refresh 时拉取（登录要过验证码），
        /api/state 一律读缓存，绝不实时登录（防锁号，MLB §11.3 惯例）。
        """
        s = self.settings()
        if not s.get("order_price_enabled"):
            return rates
        cred_path = s.get("cred_path") or DEFAULT_SETTINGS["cred_path"]
        try:
            with open(cred_path, "r", encoding="utf-8") as fh:
                cred = json.load(fh)
            user = str(cred.get("P2PAH_USERNAME") or "")
            pwd = str(cred.get("P2PAH_PASSWORD") or "")
            if not user or not pwd:
                raise ValueError("cred_missing_fields")
            vendor = Path(__file__).resolve().parent / "vendor"
            if str(vendor) not in sys.path:
                sys.path.insert(0, str(vendor))
            import p2pah_price  # ddddocr 惰性 import（只在函数内）
            parsed = p2pah_price.fetch_rows(user=user, password=pwd,
                                            gid=int(s.get("order_gid") or 1322))
            if not parsed.get("ok"):
                raise ValueError("parse_failed:%s" % parsed.get("error"))
            got = {}
            mismatched = []
            for r in parsed.get("rows") or []:
                area = (r.get("area") or "").strip().upper()
                row_gid = r.get("gid")
                try:
                    b2c = float(r.get("b2c"))
                except (TypeError, ValueError):
                    continue
                if area not in ("PS", "XBOX", "PC") or b2c <= 0:
                    continue
                # ★ 行 gid 校验（Codex #7）：页面若返回未过滤的其它游戏行，
                #   会把别人的 b2c 喂进自动写价 ⇒ 必须匹配 order_gid。
                if row_gid is not None and int(row_gid) != int(s.get("order_gid") or 1322):
                    mismatched.append("%s:gid=%s" % (area, row_gid))
                    continue
                got[area] = b2c
            if mismatched:
                raise ValueError("gid_mismatch:%s" % ",".join(mismatched))
            if not got:
                raise ValueError("no_b2c_rows")
            for plat, b2c in got.items():
                rates[plat] = dict(rates.get(plat) or {})
                rates[plat]["usd_per_k"] = ("%.6f" % b2c)
                rates[plat]["basis"] = "order_b2c"
                rates[plat]["checked_at"] = fmt_ts(now8())
            summary["order_b2c"] = got
        except Exception as exc:  # 回退 storefront 自算，不阻塞刷新
            summary["errors"].append("order_b2c: %s" % exc)
        return rates

    def cached_rates(self):
        """上轮刷新产出的单价（含来源），无则现算 storefront。"""
        data = load_json(self.data_dir / "order_rates.json", None)
        if isinstance(data, dict) and data:
            return data
        rates, _ = self.get_rates()
        return rates

    # ---------- 刷新 ----------

    def refresh(self, trigger="manual"):
        """跑一轮采集。返回摘要 dict；由调用方保证 refresh_lock 串行。"""
        started = now8()
        summary = {"trigger": trigger, "started_at": fmt_ts(started),
                   "status": "running", "players_count": 0, "errors": []}
        self._write_refresh(summary)
        base = self.settings().get("futbin_base") or DEFAULT_SETTINGS["futbin_base"]
        try:
            summary["players_count"] = self.download_players(base)
        except Exception as exc:  # 采集失败不致命：沿用旧缓存继续算价
            summary["errors"].append("futbin: %s" % exc)
        rates, meta = self.get_rates()
        rates = self._overlay_order_b2c(rates, summary)
        bad_rates = [p for p, r in rates.items() if not (r or {}).get("usd_per_k")]
        if bad_rates:
            summary["errors"].append("storefront missing: %s" % ",".join(bad_rates))
        summary["rates"] = {p: (r or {}).get("usd_per_k") for p, r in rates.items()}
        summary["rate_sources"] = {p: (r or {}).get("basis") for p, r in rates.items()}
        # 落盘供 /api/state 展示（不重复登录订单后台）
        atomic_write(str(self.data_dir / "order_rates.json"),
                     json.dumps(rates, ensure_ascii=False, indent=2).encode("utf-8"))
        self._last_rates = rates
        finished = now8()
        summary["finished_at"] = fmt_ts(finished)
        summary["duration_seconds"] = round((finished - started).total_seconds(), 1)
        summary["status"] = "ok" if not summary["errors"] else "partial"
        # ---- 二期：采集后自动写价（三开关全开才真正写）----
        # ⚠️ 必须放在 _write_refresh 之前，否则写价结果不进 last_refresh（排查盲点）
        s = self.settings()
        if (s.get("write_enabled") and s.get("write_auto")):
            # ★ 与手动写价互斥（Codex #11）：拿不到锁就跳过本轮（下轮再写），
            #   绝不并发操作同一批产品/审计日志。
            if WRITE_LOCK.acquire(blocking=False):
                try:
                    entry = execute_write(self, actor="auto",
                                          dry_run=bool(s.get("write_dry_run")))
                    summary["write"] = {
                        "dry_run": entry["dry_run"],
                        "count": len(entry["results"]),
                        "actions": [r.get("action") for r in entry["results"]],
                    }
                except Exception as exc:
                    summary["errors"].append("auto_write: %r" % exc)
                    self._append_write_log({"time": fmt_ts(now8()), "actor": "auto",
                                            "action": "error",
                                            "error": repr(exc)[:200]})
                finally:
                    WRITE_LOCK.release()
            else:
                summary["write"] = {"skipped": "write_in_progress"}
        self._write_refresh(summary)
        self._append_history(summary)
        return summary

    def _write_refresh(self, summary):
        atomic_write(str(self.refresh_path),
                     json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"))

    def _append_history(self, summary):
        hist = load_json(self.history_path, [])
        hist.append({
            "started_at": summary.get("started_at"),
            "finished_at": summary.get("finished_at"),
            "status": summary.get("status"),
            "players_count": summary.get("players_count"),
            "errors": summary.get("errors") or [],
        })
        hist = hist[-HISTORY_CAP:]
        atomic_write(str(self.history_path),
                     json.dumps(hist, ensure_ascii=False, indent=2).encode("utf-8"))

    # ---------- 写价日志 ----------

    def write_log(self):
        return load_json(self.data_dir / "write_log.json", [])

    def _append_write_log(self, entry):
        log = self.write_log()
        log.append(entry)
        log = log[-200:]
        atomic_write(str(self.data_dir / "write_log.json"),
                     json.dumps(log, ensure_ascii=False, indent=2).encode("utf-8"))

    def last_refresh(self):
        return load_json(self.refresh_path, None)

    def refresh_history(self):
        return load_json(self.history_path, [])

    # ---------- 展示层：实时算价 ----------

    def compute_state(self):
        with self.lock:
            settings = self.settings()
            rates = self.cached_rates()
            _, storefront_meta = self.get_rates()
            players_snapshot = dict(self.players)
            bundles_cfg = json.loads(json.dumps(self.config.get("bundles") or []))
            revision = int(self.config.get("revision") or 1)
        markups = {k: dec(settings.get(k)) for k in
                   ("markup_player_actual", "player_strike_divisor",
                    "bundle_sale_factor", "bundle_orig_divisor")}
        bad = [k for k, v in markups.items() if not v or v <= 0]
        bundles_out = []
        if not bad:
            for b in bundles_cfg:
                bundles_out.append(compute_bundle(b, players_snapshot, rates, markups))
            # ★ 回填配置里的 products 绑定（Codex #6）：/api/state 若不回传，
            #   前端编辑保存时会发 products:{} 把绑定清空（连带停掉自动写价）。
            cfg_products = {b.get("id"): (b.get("products") or {})
                            for b in bundles_cfg}
            for out_b in bundles_out:
                out_b["products"] = cfg_products.get(out_b.get("id"), {})
        return {
            "revision": revision,
            "settings": settings,
            "rates": rates,
            "storefront_meta": storefront_meta,
            "futbin": {
                "players_cached": len(players_snapshot),
                "updated_at": fmt_ts(self.futbin_updated_at()),
            },
            "pricing_formula_ok": not bad,
            "bundles": bundles_out,
            "write": {
                "enabled": bool(settings.get("write_enabled")),
                "dry_run": bool(settings.get("write_dry_run")),
                "auto": bool(settings.get("write_auto")),
                "log": self.write_log()[-20:],
            },
            "last_refresh": self.last_refresh(),
            "history": self.refresh_history()[-12:],
            "server_time": fmt_ts(now8()),
        }


def _num_or_none(v):
    if v is None:
        return None
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


def compute_bundle(bundle_cfg, players, rates, markups):
    rate_ps = dec((rates.get("PS") or {}).get("usd_per_k")) or Decimal(0)
    rate_pc = dec((rates.get("PC") or {}).get("usd_per_k")) or Decimal(0)
    rate_xbox = dec((rates.get("XBOX") or {}).get("usd_per_k")) or rate_ps
    mu = markups["markup_player_actual"]
    sd = markups["player_strike_divisor"]
    bf = markups["bundle_sale_factor"]
    od = markups["bundle_orig_divisor"]

    players_out = []
    warn = []
    sum_strike_ps = sum_strike_pc = Decimal(0)
    sum_actual_ps = sum_actual_pc = Decimal(0)
    count_ok = 0
    cnt_ps = cnt_pc = 0   # ★ 参与各平台求和的球员数（完整性判据，Codex #2）
    for entry in bundle_cfg.get("players") or []:
        fid = entry.get("futbin_id")
        info = players.get(int(fid)) if isinstance(fid, int) else None
        row = {"futbin_id": fid, "position": entry.get("position") or
               (info or {}).get("position") or ""}
        if info is None:
            row.update({"name": None, "rating": None, "status": "not_found",
                        "ps_coins": None, "pc_coins": None,
                        "ps_actual": None, "ps_strike": None,
                        "pc_actual": None, "pc_strike": None})
            warn.append("futbin %s 未收录" % fid)
            players_out.append(row)
            continue
        ps_coins = info.get("ps_price")
        if ps_coins is None:
            ps_coins = info.get("xbox_price")
        pc_coins = info.get("pc_price")
        row.update({
            "name": info.get("name"), "rating": info.get("rating"),
            "version": info.get("version"), "image": info.get("image"),
            "ps_coins": ps_coins, "pc_coins": pc_coins,
        })
        if ps_coins and rate_ps and mu and sd:
            actual_ps = Decimal(str(ps_coins)) / 1000 * rate_ps * mu
            row["ps_actual"] = float(money2(actual_ps))
            row["ps_strike"] = float(money2(actual_ps / sd))
            sum_actual_ps += actual_ps
            sum_strike_ps += actual_ps / sd
            cnt_ps += 1
        else:
            row.update({"ps_actual": None, "ps_strike": None})
            warn.append("%s：PS 价缺失" % (info.get("name") or fid))
        if pc_coins and rate_pc and mu and sd:
            actual_pc = Decimal(str(pc_coins)) / 1000 * rate_pc * mu
            row["pc_actual"] = float(money2(actual_pc))
            row["pc_strike"] = float(money2(actual_pc / sd))
            sum_actual_pc += actual_pc
            sum_strike_pc += actual_pc / sd
            cnt_pc += 1
        else:
            row.update({"pc_actual": None, "pc_strike": None})
            warn.append("%s：PC 价缺失" % (info.get("name") or fid))
        row["status"] = "ok" if (row.get("ps_strike") or row.get("pc_strike")) \
            else "no_price"
        if row["status"] == "ok":
            count_ok += 1
        players_out.append(row)

    out = {
        "id": bundle_cfg.get("id"),
        "title": bundle_cfg.get("title"),
        "players_count": len(players_out),
        "players_ok": count_ok,
        "players": players_out,
        "warnings": warn,
    }
    if sum_strike_ps and bf and od:
        sale_ps = sum_strike_ps * bf
        out["ps"] = {
            "sum_strike": float(money2(sum_strike_ps)),
            "sum_actual": float(money2(sum_actual_ps)),
            "sale": float(money2(sale_ps)),
            "orig": float(money2(sale_ps / od)),
            "players_counted": cnt_ps,          # ★ 完整性判据（Codex #2）
            "players_expected": len(players_out),
            "discount_vs_actual_pct": float(
                ((sale_ps - sum_actual_ps) / sum_actual_ps * 100)
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }
    else:
        out["ps"] = None
    if sum_strike_pc and bf and od:
        sale_pc = sum_strike_pc * bf
        out["pc"] = {
            "sum_strike": float(money2(sum_strike_pc)),
            "sum_actual": float(money2(sum_actual_pc)),
            "sale": float(money2(sale_pc)),
            "orig": float(money2(sale_pc / od)),
            "players_counted": cnt_pc,          # ★ 完整性判据（Codex #2）
            "players_expected": len(players_out),
            "discount_vs_actual_pct": float(
                ((sale_pc - sum_actual_pc) / sum_actual_pc * 100)
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }
    else:
        out["pc"] = None
    return out


# ---------- 配置校验 ----------

def validate_settings(payload, base):
    out = dict(base)
    allowed = set(DEFAULT_SETTINGS)
    unknown = set(payload or {}) - allowed
    if unknown:
        raise ValueError("unknown_settings:%s" % ",".join(sorted(unknown)))
    for key, value in (payload or {}).items():
        if key == "interval_hours":
            hours = float(value)
            if not (0.1 <= hours <= 168):
                raise ValueError("interval_out_of_range")
            out[key] = hours
        elif key == "futbin_base":
            text = str(value).strip().rstrip("/")
            if not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?$", text):
                raise ValueError("futbin_base_invalid")
            out[key] = text
        elif key == "storefront_path":
            text = str(value).strip().replace("\\", "/")
            if ".." in text or not (text.startswith("/") or
                                    re.match(r"^[A-Za-z]:/", text)):
                raise ValueError("storefront_path_invalid")
            out[key] = text
        elif key == "order_gid":
            gid = int(value)
            if not (1 <= gid <= 999999):
                raise ValueError("order_gid_invalid")
            out[key] = gid
        elif key == "cred_path":
            text = str(value).strip().replace("\\", "/")
            if ".." in text or not (text.startswith("/") or
                                    re.match(r"^[A-Za-z]:/", text)):
                raise ValueError("cred_path_invalid")
            out[key] = text
        elif key in ("order_price_enabled", "write_enabled",
                     "write_dry_run", "write_auto"):
            # ⚠️ 只收真 JSON bool（Codex review #16）：bool("false") 恒 True，
            #    字符串值会把"关闸"变成"开闸"。
            if not isinstance(value, bool):
                raise ValueError("bool_required:%s" % key)
            out[key] = value
        else:
            d = dec(value)
            if not d or d <= 0 or d > 100:
                raise ValueError("markup_invalid:%s" % key)
            out[key] = str(value)
    return out


def validate_bundles(payload):
    if not isinstance(payload, list) or not payload:
        raise ValueError("bundles_required")
    if len(payload) > 20:
        raise ValueError("too_many_bundles")
    seen = set()
    out = []
    for b in payload:
        if not isinstance(b, dict):
            raise ValueError("bundle_invalid")
        bid = str(b.get("id") or "").strip()
        title = str(b.get("title") or "").strip()
        if not ID_RE.match(bid) or bid in seen:
            raise ValueError("bundle_id_invalid:%s" % (bid or "?"))
        if not title or len(title) > 120:
            raise ValueError("bundle_title_invalid:%s" % bid)
        seen.add(bid)
        players = b.get("players")
        if not isinstance(players, list) or not players or len(players) > 50:
            raise ValueError("players_invalid:%s" % bid)
        clean = []
        ids = set()
        for p in players:
            if not isinstance(p, dict):
                raise ValueError("player_invalid:%s" % bid)
            fid = p.get("futbin_id")
            if isinstance(fid, bool) or not isinstance(fid, int) or fid <= 0:
                raise ValueError("futbin_id_invalid:%s" % bid)
            if fid in ids:
                raise ValueError("futbin_id_dup:%s:%s" % (bid, fid))
            ids.add(fid)
            pos = str(p.get("position") or "").strip()[:8]
            clean.append({"futbin_id": fid, "position": pos})
        entry = {"id": bid, "title": title, "players": clean}
        products = b.get("products")
        if products is not None:
            if not isinstance(products, dict):
                raise ValueError("products_invalid:%s" % bid)
            clean_products = {}
            for plat in ("ps", "xbox", "pc"):
                pid = products.get(plat)
                if pid in (None, "", 0):
                    continue
                if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                    raise ValueError("product_id_invalid:%s:%s" % (bid, plat))
                clean_products[plat] = pid
            entry["products"] = clean_products
        out.append(entry)
    return out


# ---------- 二期：Admin 后台写价（goods.Goods，站点-ALL） ----------

MIN_DELTA = Decimal("0.005")   # 变化小于此视为无变化（幂等跳过）
EXPECT_GID = 1327              # 商品后台 FC27
EXPECT_CID = 10255             # FC27-Packs 分类
EXPECT_SITE_ID = 0             # 站点-ALL


class AdminWriter:
    """admin-api.p2pah.cn 产品改价（最小字段 POST + 回读验证）。

    红线（沿 MLB §10.4）：
    - POST 一律不自动重试（超时 ≠ 失败；重试可能重复写）→ 未知结果 needs_review
    - 写前快照该产品完整 row（首次基线，绝不覆盖已存在的快照）
    - 验证码 OCR 重试语义由 vendor/admin_api_client 保证（密码错不耗 tries）
    """

    def __init__(self, cred_path: str):
        self.cred_path = cred_path
        self._client = None
        self._lock = threading.Lock()

    def _api(self):
        with self._lock:
            if self._client is not None:
                return self._client
            with open(self.cred_path, "r", encoding="utf-8") as fh:
                cred = json.load(fh)
            user = str(cred.get("P2PAH_USERNAME") or "")
            pwd = str(cred.get("P2PAH_PASSWORD") or "")
            if not user or not pwd:
                raise ValueError("cred_missing_fields")
            vendor = Path(__file__).resolve().parent / "vendor"
            if str(vendor) not in sys.path:
                sys.path.insert(0, str(vendor))
            from admin_api_client import AdminApiClient
            cli = AdminApiClient()
            cli.login_with_ocr(user, pwd)
            self._client = cli
            return cli

    def get_product(self, pid: int):
        env = self._api()._json("GET", "/admin/goods.Goods/edit", params={"id": int(pid)})
        data = env.get("data")
        row = data.get("row") if isinstance(data, dict) else None
        if not isinstance(row, dict):
            raise ValueError("product_row_missing:%s" % pid)
        return row

    def write_price(self, pid: int, unit_price: Decimal,
                    before_dir: Path, dry_run: bool,
                    *, expect_platform=None, expect_title=None):
        """按后台现值 discount 折算 target price = unit × discount/100。

        ★ 身份校验（Codex #1）：错填的产品 ID 必须 fail closed，
          绝不能因为配置笔误改到目录里的其它商品。
        返回 {action: skip|planned|written|mismatch|rejected_identity|needs_review, ...}
        """
        row = self.get_product(pid)
        # ---- 身份校验：gid/cid/site_id/aid/标题 全部要匹配 ----
        problems = []
        if int(row.get("gid") or 0) != EXPECT_GID:
            problems.append("gid=%s≠%s" % (row.get("gid"), EXPECT_GID))
        if int(row.get("cid") or 0) != EXPECT_CID:
            problems.append("cid=%s≠%s" % (row.get("cid"), EXPECT_CID))
        if int(row.get("site_id") if row.get("site_id") is not None else -1) != 0:
            problems.append("site_id=%s≠0(站点-ALL)" % row.get("site_id"))
        if expect_platform:
            aid = PLATFORM_AID.get(expect_platform)
            if aid and int(row.get("aid") or 0) != aid:
                problems.append("aid=%s≠%s(%s)" % (row.get("aid"), aid,
                                                   expect_platform))
        if expect_title and (row.get("title") or "").strip() != expect_title.strip():
            problems.append("title=%r≠%r" % (row.get("title"), expect_title))
        if problems:
            return {"product_id": pid, "action": "rejected_identity",
                    "title": row.get("title"), "problems": problems}
        cur_unit = dec(row.get("unit_price"))
        cur_price = dec(row.get("price"))
        discount = dec(row.get("discount")) or Decimal(100)
        price = (unit_price * discount / 100).quantize(Decimal("0.001"),
                                                       rounding=ROUND_HALF_UP)
        rec = {"product_id": pid, "title": row.get("title"),
               "discount": str(discount),
               "current": {"unit_price": str(cur_unit), "price": str(cur_price)},
               "target": {"unit_price": str(unit_price), "price": str(price)}}
        if (cur_unit is not None and abs(cur_unit - unit_price) < MIN_DELTA
                and cur_price is not None and abs(cur_price - price) < MIN_DELTA):
            rec["action"] = "skip"
            return rec
        if dry_run:
            rec["action"] = "planned"
            return rec
        snap = before_dir / ("%s.json" % pid)
        if not snap.exists():  # ★ 首次基线优先，绝不覆盖
            atomic_write(str(snap), json.dumps({"product_id": pid, "row": row},
                                               ensure_ascii=False, indent=2).encode("utf-8"))
        # ★ POST 不重试：异常直接上抛，由调用方记 needs_review
        # ⚠️ 后台 edit 不接受部分字段（MLB §4.2 同款教训）：
        #    只发 id/gid/sid+价格 → 逐项报 '请选定游戏！'/'请选定游戏服务区！'。
        #    正确姿势 = **完整回读 row 全字段回填**，只改 unit_price/price。
        payload = {k: v for k, v in row.items()}
        payload["unit_price"] = float(unit_price)
        payload["price"] = float(price)
        self._api()._json("POST", "/admin/goods.Goods/edit", json_body=payload)
        rec["action"] = "written"
        time.sleep(2)  # 后台落库缓冲（MLB shelves 同款节奏）
        row2 = self.get_product(pid)
        got_unit, got_price = dec(row2.get("unit_price")), dec(row2.get("price"))
        if (got_unit is None or abs(got_unit - unit_price) >= MIN_DELTA
                or got_price is None or abs(got_price - price) >= MIN_DELTA):
            rec["action"] = "mismatch"
            rec["after"] = {"unit_price": str(got_unit), "price": str(got_price)}
        return rec


def execute_write(store: "Store", bundle_id=None, dry_run=None, actor="manual"):
    """对绑定产品执行写价。四道闸门：enabled / dry_run / auto(手动触发豁免) / delta。

    ★ 并发互斥（Codex #5/#11）：**调用方**必须已持有 WRITE_LOCK；
      本函数自身不再取锁（避免手动/自动两条路径重入死锁）。
    ★ dry_run 只能收紧（Codex #4）：请求参数无法把配置的试运行放宽为真实写入。
    """
    s = store.settings()
    if not s.get("write_enabled"):
        raise ValueError("write_disabled")
    eff_dry = bool(s.get("write_dry_run")) or bool(dry_run)
    rates = store.cached_rates()
    players = dict(store.players)
    markups = {k: dec(s.get(k)) for k in
               ("markup_player_actual", "player_strike_divisor",
                "bundle_sale_factor", "bundle_orig_divisor")}
    if any(not v for v in markups.values()):
        raise ValueError("markup_invalid")
    with store.lock:
        bundles = json.loads(json.dumps(store.config.get("bundles") or []))
    if bundle_id:
        bundles = [b for b in bundles if b.get("id") == bundle_id]
        if not bundles:
            raise ValueError("bundle_not_found")
    writer = AdminWriter(s.get("cred_path") or DEFAULT_SETTINGS["cred_path"])
    before_dir = store.data_dir / "before"
    before_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for b in bundles:
        computed = compute_bundle(b, players, rates, markups)
        for plat, key in (("ps", "ps"), ("xbox", "ps"), ("pc", "pc")):
            pid = ((b.get("products") or {}).get(plat))
            side = computed.get(key)
            if not pid or not side:
                continue
            # ★ 完整性闸门（Codex #2）：该平台不是全员有价 ⇒ 拒绝写，
            #   否则 11 人包可能按 10 人价被写进去（少收钱/价格失真）。
            if side.get("players_counted") != side.get("players_expected"):
                results.append({
                    "product_id": pid, "platform": plat, "bundle": b.get("id"),
                    "action": "skipped_incomplete", "dry_run": eff_dry,
                    "detail": "%s/%s 名球员有价（缺价或未收录）" % (
                        side.get("players_counted"), side.get("players_expected"))})
                continue
            unit = money2(Decimal(str(side["orig"])))
            try:
                rec = writer.write_price(int(pid), unit, before_dir, eff_dry,
                                         expect_platform=plat,
                                         expect_title=b.get("title"))
            except Exception as exc:
                rec = {"product_id": pid, "platform": plat,
                       "target": {"unit_price": str(unit)},
                       "action": "needs_review", "error": repr(exc)[:200]}
            rec["platform"] = plat
            rec["bundle"] = b.get("id")
            rec["dry_run"] = eff_dry
            results.append(rec)
    entry = {"time": fmt_ts(now8()), "actor": actor, "dry_run": eff_dry,
             "results": results}
    store._append_write_log(entry)
    return entry


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "fc27-pack-bundles/1.0"
    store = None  # type: Store
    state = {"refreshing": False}

    def log_message(self, fmt, *args):  # 精简日志
        print("[%s] %s" % (fmt_ts(now8()), fmt % args), flush=True)

    # --- helpers ---
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _https_required(self):
        return self.headers.get("X-Forwarded-Proto") == "https"

    def do_GET(self):
        parsed = urlsplit(self.path)
        parts = [x for x in parsed.path.strip("/").split("/") if x]
        if parts == ["health"]:
            self._json(200, {"ok": True, "service": "fc27-pack-bundles",
                             "time": fmt_ts(now8())})
            return
        if parts == ["api", "state"]:
            self._json(200, self.store.compute_state())
            return
        if parts == ["api", "search"]:
            q = (parse_qs(parsed.query).get("q") or [""])[0].strip().lower()
            if len(q) < 2:
                self._json(200, {"items": []})
                return
            hits = []
            with self.store.lock:
                pool = list(self.store.players.values())
            for info in pool:
                if q in (info.get("name") or "").lower():
                    hits.append({k: info.get(k) for k in
                                 ("futbin_id", "name", "rating", "position",
                                  "ps_price", "pc_price")})
                    if len(hits) >= 12:
                        break
            hits.sort(key=lambda x: (x.get("rating") or 0), reverse=True)
            self._json(200, {"items": hits[:12]})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        if not self._https_required():
            self._json(403, {"error": "https_required"})
            return
        parts = [x for x in urlsplit(self.path).path.strip("/").split("/") if x]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json(413, {"error": "body_too_large"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._json(400, {"error": "bad_json"})
            return
        try:
            if parts == ["api", "config"]:
                rev = self.store.save_config(data)
                self._json(200, {"ok": True, "revision": rev})
                return
            if parts == ["api", "refresh"]:
                if not self.store.refresh_lock.acquire(blocking=False):
                    self._json(409, {"error": "refresh_in_progress"})
                    return
                try:
                    self.state["refreshing"] = True
                    threading.Thread(target=self._refresh_job, daemon=True).start()
                finally:
                    self.store.refresh_lock.release()
                self._json(202, {"ok": True, "status": "started"})
                return
            if parts == ["api", "write-prices"]:
                # 手动写价（受 write_enabled / write_dry_run 闸门约束）
                # ★ 锁由 worker 的 finally 释放（Codex #5）：
                #   原实现在起线程后立刻释放，第二次请求可并发进入。
                if not WRITE_LOCK.acquire(blocking=False):
                    self._json(409, {"error": "write_in_progress"})
                    return
                try:
                    threading.Thread(
                        target=self._write_job,
                        args=(data.get("bundle_id"),
                              data.get("dry_run") if isinstance(data.get("dry_run"), bool)
                              else None),
                        daemon=True).start()
                except Exception as exc:
                    WRITE_LOCK.release()
                    self._json(500, {"error": "write_start_failed",
                                     "detail": repr(exc)[:120]})
                    return
                self._json(202, {"ok": True, "status": "started"})
                return
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "not_found"})

    def _refresh_job(self):
        try:
            self.store.refresh(trigger="manual")
        except Exception as exc:  # 兜底：任何异常都落到 last_refresh
            self.store._write_refresh({
                "trigger": "manual", "status": "error",
                "started_at": fmt_ts(now8()),
                "finished_at": fmt_ts(now8()),
                "errors": [repr(exc)]})
        finally:
            self.state["refreshing"] = False

    def _write_job(self, bundle_id, dry_run):
        try:
            execute_write(self.store, bundle_id=bundle_id,
                          dry_run=dry_run, actor="manual")
        except Exception as exc:
            self.store._append_write_log({"time": fmt_ts(now8()),
                                          "actor": "manual", "action": "error",
                                          "error": repr(exc)[:200]})
        finally:
            WRITE_LOCK.release()   # ★ 与 do_POST 的 acquire 配对（Codex #5）


def scheduler_loop(store: Store, state: dict):
    """每分钟看一眼：距上次成功刷新超过间隔就补一轮。"""
    while True:
        try:
            last = store.last_refresh() or {}
            last_ok = last.get("finished_at") or last.get("started_at")
            due = True
            if last_ok:
                last_dt = datetime.strptime(last_ok, "%Y-%m-%d %H:%M:%S")
                age = (now8() - last_dt.replace(tzinfo=TZ8)).total_seconds()
                if last.get("status") == "running":
                    # ★ 卡死保护（Codex #10）：正常一轮 <2 分钟；
                    #   running 超过 2 小时视为 abandoned，恢复调度。
                    due = age >= 7200
                else:
                    due = age >= store.interval_seconds()
            if due and store.refresh_lock.acquire(blocking=False):
                try:
                    state["refreshing"] = True
                    store.refresh(trigger="auto")
                except Exception as exc:
                    store._write_refresh({
                        "trigger": "auto", "status": "error",
                        "started_at": fmt_ts(now8()),
                        "finished_at": fmt_ts(now8()),
                        "errors": [repr(exc)]})
                finally:
                    state["refreshing"] = False
                    store.refresh_lock.release()
        except Exception as exc:
            print("[scheduler] %r" % exc, flush=True)
        time.sleep(60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8904)
    ap.add_argument("--data", default="/opt/fc27-pack-bundles/data")
    args = ap.parse_args()
    data_dir = Path(args.data)
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir)
    Handler.store = store
    threading.Thread(target=scheduler_loop, args=(store, Handler.state),
                     daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("[start] fc27-pack-bundles on 127.0.0.1:%d data=%s"
          % (args.port, data_dir), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
