# -*- coding: utf-8 -*-
"""MLB 后台写卡完整流水线（执行器采集结果 → 后台模型+产品+主图+扩展属性）。

═══════════════════════════════════════════════════════════════════════
完整链路（五步，2026-10-12 全部实跑验证）
═══════════════════════════════════════════════════════════════════════
输入：执行器任务结果 JSON（含 cards[]，每张卡有 name/ovr/team/position/
      series/sale_price/hash/product_name）

 ⓿ 写前基线存档（`--archive`）：把每张要写的模型当前完整表单落盘
    → `<archive>/<mid>.before.json`；新建的模型记进 `<archive>/_created.json`
    ⇒ 任何写入都可原值还原（`--restore`）

 ① POST https://b2c-api.p2pah.cn/upload/network?pic_list=<卡图URL>
    → file.id（附件 ID）、file.full_url（内网图 URL）
    卡图 URL = https://cards.theshow.com/mlb26/<hash>-baked-sm.webp

 ② POST /admin/goods.GoodsMould/add
    → 建模型骨架（⚠️ 无 gid 限制，MLB 可走；响应不含 id）

 ③ 回读 GET /admin/goods.GoodsMould/index（按 title 精确匹配）→ 拿 mid

 ④ POST /admin/goods.GoodsMould/edit
    → 写 icon（附件 ID）+ _format.icon_format + more.extend=[zh_title]
    参数 _extend.gold_save_mode="mould_only"（只写模型不改产品）

 ⑤ POST /admin/goods.GoodsMould/shelves
    → body: site_ids(15) + aids(3) + search.mids=mid → 生成 48 个产品
    （异步，须 sleep ≥4s 再回读；会自动把模型 is_put 置 1）

═══════════════════════════════════════════════════════════════════════
⚠️ 关键教训（务必遵守）
═══════════════════════════════════════════════════════════════════════
- **`zh_title` 绝不能漏**：自动改价脚本靠它关联卡牌，漏了等于废卡
  · zh_title 值 = 卡图 URL 里的 32 位 hash（与 icon URL 同源）
  · 位置 = `more.extend = [{"key":"zh_title","value":"<hash>"}]`
- **`icon` 绝不能留 0**：主图附件 ID，展示与改价都要用
- `add` 响应**不返回新模型 id** → 必须回读定位
- POST 写操作**绝不自动重试**；未知结果一律转人工
- **写前必存档**：`--archive` 不是可选项。存的是「写入前」的完整表单，
  这是唯一能在写错时原样回退的依据

═══════════════════════════════════════════════════════════════════════
服务器写权限（2026-10-12 实证，勿再凭旧记忆断言）
═══════════════════════════════════════════════════════════════════════
play187（47.85.224.112）**具备** `/admin/*` 写权限：
对 4 张已存在卡做「原值恒等写」，全部 `HTTP=200 code=1 msg='保存成功'`，
写后逐字段 diff 内容字段变化 **0**。
（旧记录里 403 的是 47.253.252.55，**另一台**，别混。）

用法：
  python mlb_write_cards.py --result <执行器结果.json> --dry-run
  python mlb_write_cards.py --result <执行器结果.json> --archive _archive \\
      --apply --confirm mlb26-players
  python mlb_write_cards.py --archive _archive --restore \\
      --apply --confirm mlb26-players        # 万一写错 → 原值还原
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../src
EVID = HERE.parent / "evidence"
sys.path.insert(0, str(HERE))
from admin_api_client import AdminApiClient, AdminUnknownResult  # noqa: E402

GID, CID = 927, 8233
ICON_BASE = "https://cards.theshow.com/mlb26/"
B2C_BASE = "https://b2c-api.p2pah.cn"
EXPECTED_PRODUCTS = 48
EDIT_PATH = "/admin/goods.GoodsMould/edit"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    urllib.request.ProxyHandler({}))


# ------------------------------------------------------------------ 工具
def upload_network(img_url: str) -> dict:
    """外链图转内部附件 → {"id": <icon>, "full_url": <url>}（幂等）。"""
    u = B2C_BASE + "/upload/network?" + urllib.parse.urlencode({"pic_list": img_url})
    req = urllib.request.Request(u, method="POST", headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Origin": "https://admin.p2pah.cn", "Referer": "https://admin.p2pah.cn/"})
    with _opener.open(req, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    net = (j.get("upload") or {}).get("network") or {}
    if net.get("code") != 200 or not net.get("file"):
        raise RuntimeError("upload/network 失败: %s" % json.dumps(net, ensure_ascii=False)[:300])
    return net["file"]


def card_icon_url(card_hash: str) -> str:
    return ICON_BASE + card_hash + "-baked-sm.webp"


def _restore_body(row: dict) -> dict:
    """还原用 body：原表单 + 那两个「只写模型」开关。

    `gold_save_mode="mould_only"` 与 `confirm_mould_trigger=1` 的作用是
    **只写模型、不动已生成的产品**，属于影响面最小的写形态，因此还原
    与生产写都带上它们。
    """
    body = dict(row)
    ext = dict(row.get("_extend") or {})
    ext["gold_save_mode"] = "mould_only"
    ext["confirm_mould_trigger"] = 1
    body["_extend"] = ext
    return body


# ------------------------------------------------------------------ 主流程
class Writer:
    def __init__(self, client: AdminApiClient, dry_run: bool, log=print,
                 archive_dir=None):
        self.c = client
        self.dry = dry_run
        self.log = log
        self.arch = Path(archive_dir) if archive_dir else None
        self.snapshots = {}     # mid -> Path（本进程内只存第一次，保留最初基线）
        self.created = []       # 本次**新建**的 mid（存档里无 before，需人工决定去留）

    # ---- 只读：按 title 定位模型 ----
    def find_model(self, title: str):
        page = 1
        while page <= 10:
            d = self.c.list_models(gid=GID, cid=CID, page=page, limit=200)
            for row in d.get("list") or []:
                if (row.get("title") or "").strip() == title:
                    return row
            if page * 200 >= int(d.get("total") or 0):
                break
            page += 1
        return None

    def products_of(self, mid: int):
        d = self.c._json("GET", "/admin/goods.Goods/index",
                         params={"page": 1, "limit": 1, "order": "id,desc",
                                 "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
        return int((d.get("data") or {}).get("total") or 0)

    def read_row(self, mid: int) -> dict:
        """取写表单（与 POST /edit 同源的完整 row）。"""
        ed = self.c._json("GET", EDIT_PATH, params={"id": mid})
        return (ed.get("data") or {}).get("row") or {}

    # ---- 写前基线存档 ----
    def snapshot(self, mid):
        """把 mid 当前完整表单落盘。**同一次运行内只存第一次**（最初基线），
        文件已存在也不覆盖 —— 否则第二次跑会把"被写坏之后"的状态当成基线，
        还原就会还原成坏的值。"""
        if self.arch is None:
            return None
        if mid in self.snapshots:
            return self.snapshots[mid]
        row = self.read_row(mid)
        self.arch.mkdir(parents=True, exist_ok=True)
        p = self.arch / ("%d.before.json" % mid)
        if p.is_file():
            self.log("  📦 基线已存在（保留最初基线，不覆盖）：%s" % p.name)
        else:
            p.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log("  📦 基线存档 → %s（%d 字节）" % (p.name, p.stat().st_size))
        self.snapshots[mid] = p
        return p

    def write_manifest(self):
        """记录本次新建的模型 —— 它们没有 before 基线，还原时需人工判断。"""
        if self.arch is None:
            return None
        self.arch.mkdir(parents=True, exist_ok=True)
        p = self.arch / "_created.json"
        data = {"created_mids": sorted(set(self.created)),
                "note": "这些模型是本次**新建**的，没有 before 基线；"
                        "未经确认不要自动删除（删除可能连带已生成产品）。"}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    # ---- 单卡：五步 ----
    def write_one(self, card: dict) -> dict:
        title = card["product_name"]
        h = card["hash"]
        price = float(card["sale_price"])
        rec = {"title": title, "hash": h, "price": price}
        self.log("\n" + "=" * 66)
        self.log("[%s]  $%s  hash=%s" % (title, price, h))

        # ---- 幂等：模型已存在且字段齐全 → 跳过 ----
        exist = self.find_model(title)
        if exist:
            mid = exist.get("id")
            pt = self.products_of(mid)
            zh = next((e.get("value") for e in (exist.get("more") or {}).get("extend") or []
                       if isinstance(e, dict) and e.get("key") == "zh_title"), None)
            if exist.get("icon") and zh == h and pt >= EXPECTED_PRODUCTS:
                self.log("  ⏭ 已存在且完整（mid=%s icon=%s 产品=%s），跳过" % (mid, exist.get("icon"), pt))
                rec.update({"verdict": "skipped", "mid": mid})
                return rec
            self.log("  ⚠️ 已存在但字段不全（icon=%s zh=%s 产品=%s）mid=%s → 走补全"
                     % (exist.get("icon"), zh, pt, mid))
            rec["mid"] = mid
        else:
            rec["mid"] = None

        # ---- ⓿ 写前基线存档（dry-run 不动线上，无基线可存）----
        if rec.get("mid") and not self.dry:
            rec["archive"] = str(self.snapshot(rec["mid"]))

        # ---- ① 上传图 ----
        self.log("  ① upload/network …")
        if self.dry:
            rec["icon"] = "(dry)"
            rec["icon_url"] = card_icon_url(h)
            f = {"id": 0, "full_url": card_icon_url(h)}
        else:
            f = upload_network(card_icon_url(h))
            self.log("     icon=%s" % f["id"])
            rec["icon"] = f["id"]
            rec["icon_url"] = f["full_url"]

        # ---- ② add（若模型不存在）----
        mid = rec.get("mid")
        if not mid:
            self.log("  ② POST /add 建模型 …")
            if self.dry:
                mid = 0
                rec["mid"] = "(dry)"
            else:
                body = {
                    "gid": GID, "cid": CID, "top_cid": 2, "sid": 0, "aid": 0,
                    "title": title, "icon": f["id"], "pic": "",
                    "price": price, "discount": 100, "min_qty": 1,
                    "receiving_price": 0, "sort": 1000,
                    "status": "1", "is_put": "0",
                    "is_hot": "0", "is_rec": "0", "is_code": "0", "auto_off": "0",
                    "buy_status": 0, "attr_switch": "0", "sku_switch": "0",
                    "partner": "", "summary": "", "desc": "",
                    "duration": "0", "shelf_time": "0", "tid": "0",
                    "more": {"extend": [{"key": "zh_title", "value": h}]},
                    "_format": {"icon_format": f["full_url"]},
                    "_extend": {"site_ids": [], "aids": [], "duration": "0"},
                }
                try:
                    res = self.c._json("POST", "/admin/goods.GoodsMould/add", json_body=body)
                    self.log("     %s" % res.get("msg"))
                except AdminUnknownResult as e:
                    rec["verdict"] = "add-unknown(no-retry)"
                    self.log("     [X] 结果未知，停止: %s" % e)
                    return rec
                except Exception as e:
                    rec["verdict"] = "add-failed: %r" % e
                    self.log("     [X] 被拒: %r" % e)
                    return rec
                time.sleep(2)
                m = self.find_model(title)
                if not m:
                    rec["verdict"] = "readback-missing"
                    self.log("     [X] 回读找不到模型")
                    return rec
                mid = m["id"]
                rec["mid"] = mid
                self.created.append(mid)      # 新建 → 无 before 基线，记进 manifest
                self.log("     ✅ mid=%s（新建，已记入 _created.json）" % mid)

        if self.dry:
            rec["verdict"] = "dry-run"
            return rec

        # ---- ④ edit：写 icon + zh_title（确保齐全）----
        row = self.read_row(mid)
        need_fix = (str(row.get("icon")) != str(f["id"])
                    or not (row.get("more") or {}).get("extend"))
        if need_fix:
            self.log("  ④ POST /edit 写 icon + zh_title …")
            body = dict(row)
            body["icon"] = f["id"]
            fmt = dict(row.get("_format") or {})
            fmt["icon_format"] = f["full_url"]
            body["_format"] = fmt
            more = dict(row.get("more") or {})
            more["extend"] = [{"key": "zh_title", "value": h}]
            body["more"] = more
            ext = dict(row.get("_extend") or {})
            ext["gold_save_mode"] = "mould_only"
            ext["confirm_mould_trigger"] = 1
            body["_extend"] = ext
            try:
                res = self.c._json("POST", EDIT_PATH, json_body=body)
                self.log("     %s" % res.get("msg"))
            except AdminUnknownResult as e:
                rec["verdict"] = "edit-unknown(no-retry)"
                self.log("     [X] 结果未知，停止: %s" % e)
                return rec
            except Exception as e:
                rec["verdict"] = "edit-failed: %r" % e
                self.log("     [X] 被拒: %r" % e)
                return rec
            time.sleep(2)
        else:
            self.log("  ④ icon/zh_title 已齐全，跳过")

        # ---- ⑤ shelves：建产品（若缺）----
        pt = self.products_of(mid)
        if pt < EXPECTED_PRODUCTS:
            self.log("  ⑤ POST /shelves 建产品（现有 %s）…" % pt)
            r2 = self.read_row(mid)
            ext2 = r2.get("_extend") or {}
            sbody = {
                "num": ext2.get("num", 1), "min_qty": r2.get("min_qty", 1),
                "total": ext2.get("total", 0), "discount": r2.get("discount", 100),
                "price": r2.get("price"), "status": str(r2.get("status", 1)),
                "is_rec": str(r2.get("is_rec", 0)),
                "duration": str(r2.get("duration", 0)),
                "open_watermark": str(ext2.get("open_watermark", 0)),
                "site_ids": ext2.get("all_site_ids") or [],
                "aids": ext2.get("all_aids") or [],
                "search": {"mids": mid},
            }
            try:
                res = self.c._json("POST", "/admin/goods.GoodsMould/shelves", json_body=sbody)
                self.log("     %s" % res.get("msg"))
            except AdminUnknownResult as e:
                rec["verdict"] = "shelves-unknown(no-retry)"
                self.log("     [X] 结果未知，停止: %s" % e)
                return rec
            except Exception as e:
                rec["verdict"] = "shelves-failed: %r" % e
                self.log("     [X] 被拒: %r" % e)
                return rec
            time.sleep(4)
        else:
            self.log("  ⑤ 产品已齐全（%s），跳过" % pt)

        # ---- 校验 ----
        pt = self.products_of(mid)
        r3 = self.read_row(mid)
        zh3 = next((e.get("value") for e in (r3.get("more") or {}).get("extend") or []
                    if isinstance(e, dict) and e.get("key") == "zh_title"), None)
        ok = (str(r3.get("icon")) == str(f["id"]) and zh3 == h
              and pt >= EXPECTED_PRODUCTS)
        self.log("  ✅ 校验 icon=%s zh=%s 产品=%s → %s"
                 % (r3.get("icon"), zh3, pt, "达标" if ok else "⚠️不符"))
        rec.update({"icon_readback": r3.get("icon"), "zh_title": zh3,
                    "products": pt, "verdict": "ok" if ok else "mismatch"})
        return rec

    # ---- 还原：把存档里的 before 原值写回 ----
    def restore_all(self) -> list:
        if self.arch is None or not self.arch.is_dir():
            raise RuntimeError("没有可用的存档目录：%s" % self.arch)
        files = sorted(self.arch.glob("*.before.json"))
        if not files:
            raise RuntimeError("存档目录里没有 *.before.json：%s" % self.arch)
        out = []
        for p in files:
            mid = int(p.name.split(".")[0])
            row = json.loads(p.read_text("utf-8"))
            try:
                res = self.c._json("POST", EDIT_PATH, json_body=_restore_body(row))
                self.log("  ↩ mid=%-10s 已还原：%s" % (mid, res.get("msg")))
                out.append({"mid": mid, "ok": True, "msg": res.get("msg")})
            except AdminUnknownResult as e:
                self.log("  [X] mid=%-10s 还原结果未知（不重试）：%s" % (mid, e))
                out.append({"mid": mid, "ok": False, "error": "unknown: %r" % e})
            except Exception as e:
                self.log("  [X] mid=%-10s 还原失败：%r" % (mid, e))
                out.append({"mid": mid, "ok": False, "error": "%r" % e})
            time.sleep(1)
        return out


# ------------------------------------------------------------------ 入口
def load_cred(explicit_path=None):
    """读取 admin-api 凭据。

    优先级（安全考虑，明文文件不是默认项）：
      1. --cred 显式指定的 JSON 文件（可放库外）
      2. 环境变量 P2PAH_USERNAME / P2PAH_PASSWORD
    ⛔ 库内 evidence/_cred.json 已被 .gitignore 排除，不要把默认值指回它。
    """
    if explicit_path:
        p = Path(explicit_path)
        if not p.is_file():
            print("[X] --cred 指向的文件不存在: %s" % p)
            sys.exit(2)
        d = json.loads(p.read_text("utf-8"))
    else:
        u = os.environ.get("P2PAH_USERNAME", "").strip()
        pw = os.environ.get("P2PAH_PASSWORD", "").strip()
        if not (u and pw):
            print("[X] 未提供凭据。请二选一：")
            print("    a) 设环境变量 P2PAH_USERNAME / P2PAH_PASSWORD")
            print("    b) 传 --cred <库外 JSON 文件路径>")
            sys.exit(2)
        d = {"P2PAH_USERNAME": u, "P2PAH_PASSWORD": pw}
    if not (d.get("P2PAH_USERNAME") and d.get("P2PAH_PASSWORD")):
        print("[X] 凭据不完整，需含 P2PAH_USERNAME 与 P2PAH_PASSWORD")
        sys.exit(2)
    return d


def run_pipeline(cards, cred, *, dry_run=False, archive_dir=None,
                 out_path=None, log=print) -> list:
    """可调用入口（CLI 与外部编排共用同一条路径）。

    ⛔ 本函数**不做确认闸门** —— 闸门在 `main()` 里、在**任何副作用之前**。
       调用方若要用于生产，必须自己先完成闸门判断。
    """
    c = AdminApiClient(log=lambda *a: log(*a))
    # dry-run 也登录：需要只读查询判断幂等/字段是否齐全（只发 GET）
    c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])
    w = Writer(c, dry_run=dry_run, log=log, archive_dir=archive_dir)
    report = []
    for card in cards:
        try:
            report.append(w.write_one(card))
        except Exception as e:
            log("  [X] 未捕获异常，停止本卡: %r" % e)
            report.append({"title": card.get("product_name"),
                           "verdict": "exception: %r" % e})
            break  # 异常即停，不继续
    if not dry_run:
        w.write_manifest()
        if w.created:
            log("\n⚠️ 本次新建模型 %d 个（无 before 基线）：%s"
                % (len(w.created), w.created))
    if out_path:
        Path(out_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        log("\n已写入 %s" % out_path)
    return report


def main(argv=None):
    # argv 可注入，供离线用例在不启动真流程的前提下验证「确认闸门」行为。
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default=None, help="执行器任务结果 JSON")
    ap.add_argument("--cred", default=None,
                    help="凭据 JSON 路径（库外）；不传则读环境变量 P2PAH_USERNAME/P2PAH_PASSWORD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--archive", default=str(EVID / "_archive"),
                    help="写前基线存档目录（还原依据；默认 evidence/_archive）")
    ap.add_argument("--restore", action="store_true",
                    help="还原模式：用 --archive 里的 *.before.json 原值写回")
    ap.add_argument("--out", default=str(EVID / "_pipeline_result.json"))
    args = ap.parse_args(argv)

    # ⛔ 闸门前置：必须在读文件/连网/取凭据之前拦下，否则「误触即改线上」。
    if not args.dry_run:
        if not args.apply or args.confirm != "mlb26-players":
            print("[X] 生产写入必须 --apply --confirm mlb26-players")
            sys.exit(2)

    cred = load_cred(args.cred)
    log = lambda *a: print(*a, flush=True)          # noqa: E731

    # ---------- 还原模式 ----------
    if args.restore:
        c = AdminApiClient(log=log)
        c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])
        w = Writer(c, dry_run=False, log=log, archive_dir=args.archive)
        out = w.restore_all()
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("\n还原 %d / %d 成功" % (sum(1 for r in out if r["ok"]), len(out)))
        print("已写入 %s" % args.out)
        return

    # ---------- 写入模式 ----------
    if not args.result:
        print("[X] 写入模式必须给 --result <执行器结果.json>")
        sys.exit(2)
    data = json.loads(Path(args.result).read_text("utf-8"))
    cards = [c for c in data.get("cards", []) if c.get("include")]
    print("待写入 %d 张卡" % len(cards))

    report = run_pipeline(cards, cred, dry_run=args.dry_run,
                          archive_dir=args.archive, out_path=args.out, log=log)
    print("\n汇总:")
    for r in report:
        print("  %-52s %s" % ((r.get("title") or "")[:50], r.get("verdict")))


if __name__ == "__main__":
    main()
