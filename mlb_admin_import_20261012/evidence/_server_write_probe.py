# -*- coding: utf-8 -*-
"""服务器写权限实证：存档 + 恒等写 + 逐字段 diff + 可还原。

═══════════════════════════════════════════════════════════════════════
要回答的问题
═══════════════════════════════════════════════════════════════════════
**47.85.224.112（play187）的出口 IP，到底有没有 p2pah 后台的写权限？**

历史事实：此前在服务器上跑过 `--dry-run` 与一次 `--apply`，但 4 张卡全部
`skipped` —— `add` / `edit` / `shelves` **一个都没真正执行过**。
所以「服务器能不能写」一直是空白（只有登录与只读被证过）。

⚠️ `admin_api_client.py` 的模块 docstring 里记着「旧服务器 47.253.252.55
   实测 403 No permission request」——但那是**另一台**。play187 从未验过。

═══════════════════════════════════════════════════════════════════════
为什么这样做是安全的（三重保险）
═══════════════════════════════════════════════════════════════════════
1. **恒等写**：把 `GET /admin/goods.GoodsMould/edit?id=<mid>` 拿到的表单
   **原样** POST 回去，不改任何字段 ⇒ 语义上是 no-op。
   生产链路本来就是 `body = dict(row)` 再覆盖 icon / _format / more，
   即「以原表单为基底」——本探针走的就是同一条路径，不引入新形态。
2. **先存档**：POST 之前把整份表单落盘到 `--archive/<mid>.before.json`，
   任何字段被意外改动都能拿它原值写回（`--restore` 模式）。
3. **逐字段 diff**：写后重新 GET，与存档逐字段比对，差异全部打印。

另外：若 IP 不在白名单，后台在**请求层**就返回 403/401，
写入根本不会发生 —— 也就是说**第一次尝试本身就是无害的**。

用法
----
  python3 _server_write_probe.py --cred _cred.json --archive _archive_wprobe \\
      --mids 44638327,44638391,44638393,44638395 \\
      --apply --confirm mlb26-players

  # 万一看完后想还原：
  python3 _server_write_probe.py --cred _cred.json --archive _archive_wprobe \\
      --restore --apply --confirm mlb26-players
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
from admin_api_client import (  # noqa: E402
    AdminApiClient, AdminAuthError, AdminUnknownResult,
)

EDIT_PATH = "/admin/goods.GoodsMould/edit"

# 视为「易变」的字段：后台每次写都会自己刷新，出现差异不算异常。
# 判定用子串匹配（小写），命中即归入 volatile。
VOLATILE_HINTS = ("update_time", "updatetime", "update_tm", "modify_time",
                  "last_time", "version", "etag")


def is_volatile(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in VOLATILE_HINTS)


def flatten(obj, prefix=""):
    """把嵌套 dict/list 摊平成 {点路径: 值}，便于逐字段 diff。"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, "%s.%s" % (prefix, k) if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, "%s[%d]" % (prefix, i)))
    else:
        out[prefix] = obj
    return out


def diff(before: dict, after: dict):
    fb, fa = flatten(before), flatten(after)
    changed, only_b, only_a = [], [], []
    for k in sorted(set(fb) | set(fa)):
        if k not in fb:
            only_a.append((k, fa[k]))
        elif k not in fa:
            only_b.append((k, fb[k]))
        elif fb[k] != fa[k]:
            changed.append((k, fb[k], fa[k]))
    return changed, only_b, only_a


def build_identity_body(row: dict) -> dict:
    """把 read 到的表单原样回填成写 body（与生产链路同源）。

    生产 `mlb_write_cards.py` 的写法是：
        body = dict(row)
        body["icon"] = <新附件 id>
        body["_format"]["icon_format"] = <full_url>
        body["more"]["extend"] = [{"key":"zh_title","value":<hash>}]
        body["_extend"]["gold_save_mode"] = "mould_only"
        body["_extend"]["confirm_mould_trigger"] = 1
    本探针**不改 icon / _format / more**，只保留那两个 _extend 开关
    （它们的作用是「只写模型、不动产品」，正是我们要的最小影响面）。
    """
    body = dict(row)
    ext = dict(row.get("_extend") or {})
    ext["gold_save_mode"] = "mould_only"
    ext["confirm_mould_trigger"] = 1
    body["_extend"] = ext
    return body


def get_row(c, mid):
    r = c._json("GET", EDIT_PATH, params={"id": mid})
    return (r.get("data") or {}).get("row") or {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cred", required=True)
    ap.add_argument("--mids", default="", help="逗号分隔的模型 id")
    ap.add_argument("--mid-file", default="", help="或从 JSON 文件读 mid 列表")
    ap.add_argument("--archive", default=str(HERE / "_archive_wprobe"))
    ap.add_argument("--restore", action="store_true",
                    help="用存档里的 before 原值写回（还原模式）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--out", default=str(HERE / "_server_write_probe.json"))
    ap.add_argument("--only-first", action="store_true",
                    help="只测第一张，看完 diff 再决定是否全测")
    args = ap.parse_args(argv)

    if not args.apply or args.confirm != "mlb26-players":
        print("[X] 本探针会对线上发 POST，必须 --apply --confirm mlb26-players")
        sys.exit(2)

    mids = [int(x) for x in args.mids.split(",") if x.strip()]
    if args.mid_file:
        j = json.loads(Path(args.mid_file).read_text("utf-8"))
        mids = [int(x.get("mid", x)) if isinstance(x, dict) else int(x) for x in j]
    if not mids:
        print("[X] 没有 mid，用 --mids 或 --mid-file 指定")
        sys.exit(2)
    if args.only_first:
        mids = mids[:1]

    arch = Path(args.archive)
    arch.mkdir(parents=True, exist_ok=True)

    cred = json.loads(Path(args.cred).read_text("utf-8"))
    c = AdminApiClient(log=lambda *a: print(*a, flush=True))
    c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])
    print("登录成功；模式 = %s" % ("RESTORE（用存档还原）" if args.restore else "IDENTITY-WRITE（恒等写）"))
    print("目标 mid = %s" % mids)

    report = []
    for mid in mids:
        print("\n" + "=" * 70)
        print("mid = %d" % mid)
        rec = {"mid": mid}
        before_path = arch / ("%d.before.json" % mid)

        # ---------- 存档 / 读取当前态 ----------
        try:
            cur = get_row(c, mid)
        except Exception as e:
            print("  [X] 读表单失败：%r" % e)
            rec["verdict"] = "read-failed: %r" % e
            report.append(rec)
            continue
        rec["title"] = cur.get("title")

        if args.restore:
            if not before_path.is_file():
                print("  [X] 没有存档 %s，无法还原" % before_path.name)
                rec["verdict"] = "restore-no-archive"
                report.append(rec)
                continue
            body = json.loads(before_path.read_text("utf-8"))
            print("  存档还原：用 %s 写入" % before_path.name)
        else:
            if not before_path.is_file():
                before_path.write_text(
                    json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
                print("  ① 已存档 → %s（%d 字节）"
                      % (before_path.name, before_path.stat().st_size))
            else:
                print("  ① 存档已存在（不覆盖，保留最初基线）：%s" % before_path.name)
            body = build_identity_body(cur)

        # ---------- 写 ----------
        print("  ② POST %s（%s）…" % (EDIT_PATH, "还原" if args.restore else "恒等"))
        t0 = time.time()
        write_err = None
        try:
            res = c._json("POST", EDIT_PATH, json_body=body)
            print("     HTTP=%s code=1 msg=%r（%.1fs）"
                  % (c.last_status, res.get("msg"), time.time() - t0))
            rec["write"] = {"ok": True, "msg": res.get("msg"),
                            "http": c.last_status, "secs": round(time.time() - t0, 2)}
        except AdminUnknownResult as e:
            write_err = "unknown: %r" % e
            print("     [X] 结果未知（不回滚、不重试）：%s" % e)
        except AdminAuthError as e:
            write_err = "auth: %r" % e
            print("     [X] 权限被拒（HTTP=%s）：%s" % (c.last_status, e))
        except Exception as e:
            write_err = "%s: %r" % (type(e).__name__, e)
            print("     [X] 失败：%s" % write_err)
        if write_err:
            rec["write"] = {"ok": False, "error": write_err, "http": c.last_status}
            rec["verdict"] = "write-rejected"
            report.append(rec)
            continue

        # ---------- 回读 + diff ----------
        time.sleep(2)
        try:
            after = get_row(c, mid)
        except Exception as e:
            print("  [X] 回读失败：%r" % e)
            rec["verdict"] = "readback-failed: %r" % e
            report.append(rec)
            continue
        after_path = arch / ("%d.after.json" % mid)
        after_path.write_text(json.dumps(after, ensure_ascii=False, indent=2),
                              encoding="utf-8")

        baseline = json.loads(before_path.read_text("utf-8"))
        changed, only_b, only_a = diff(baseline, after)
        hard = [(k, a, b) for k, a, b in changed if not is_volatile(k)]
        soft = [(k, a, b) for k, a, b in changed if is_volatile(k)]

        print("  ③ diff（基线 %s vs 回读）" % before_path.name)
        print("     内容字段变化：%d 个 %s" % (len(hard), "✅" if not hard else "⛔"))
        for k, a, b in hard:
            print("        ⛔ %s: %r → %r" % (k, a, b))
        print("     易变字段变化：%d 个（%s）" % (len(soft), "正常" if soft else "无"))
        for k, a, b in soft:
            print("        · %s: %r → %r" % (k, a, b))
        for k, v in only_b:
            print("        ⛔ 回读丢失字段 %s = %r" % (k, v))
        for k, v in only_a:
            print("        · 回读新增字段 %s = %r" % (k, v))

        rec["diff"] = {"hard": len(hard), "volatile": len(soft),
                       "only_before": len(only_b), "only_after": len(only_a)}
        rec["content_field_changes"] = [{"field": k, "before": a, "after": b}
                                        for k, a, b in hard]
        rec["verdict"] = "clean" if (not hard and not only_b) else "content-changed"
        rec["icon"] = after.get("icon")
        rec["zh_title"] = next(
            (e.get("value") for e in (after.get("more") or {}).get("extend") or []
             if isinstance(e, dict) and e.get("key") == "zh_title"), None)
        report.append(rec)

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print("\n" + "=" * 70)
    print("汇总（存档目录 %s）：" % arch)
    for r in report:
        print("  mid=%-10s %-46s %s"
              % (r.get("mid"), (r.get("title") or "")[:44], r.get("verdict")))
    ok = [r for r in report if r.get("write", {}).get("ok")]
    print("\n写请求成功 %d / %d" % (len(ok), len(report)))
    if args.restore:
        print("→ 若上方 diff 为 0，说明已回到存档基线。")
    else:
        print("→ 若上方 diff（内容字段）为 0：恒等写成立，服务器写权限 ✅")
        print("→ 若有变化：用 --restore 跑一遍即可原值还原。")
    print("报告：%s" % args.out)


if __name__ == "__main__":
    main()
