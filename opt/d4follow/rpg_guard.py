#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPG 改价系统 · 常态看护（2026-10-23 大超裁定 C）

由 rpg-guard.timer 每 15 分钟跑一次。**只读**，不改价、不改配置。

判据（全部来自库表/结果文件，不依赖外部 AI 会话）：
  ① 服务存活      d4follow / p2pah-srv-exec 非 active ⇒ 先看心跳/等 25 秒复检，
                   仍非 active 才告警（避开部署重启的 5~35 秒空窗）
  ② 近 30 分钟失败 窗口内 status=failed 的工单 ⇒ 告警（列 id/kind/title）；已被补派覆盖（result_json.superseded_by）的不算
  ③ 同单反复失败   同一 id attempts ≥3 且 failed ⇒ 告警
  ④ 采集/派单停滞  最新快照距今 > 90 分钟 ⇒ 告警
  ⑤ 人工改价保护   保护名单超过 24h 未解除 ⇒ 提示（可能冻结在人工价）
  ⑥ 人工价被覆盖   结果文件里「改前实际」≠ 本链路上次写入、且该区**没进保护名单**
                   ⇒ 告警（说明保护闸没兜住）

告警走项目现有 msg_alert（钉钉），带指纹冷却，不会刷屏。
"""
import datetime as dt
import glob
import json
import os
import sqlite3
import subprocess
import sys
import time

ROOT = "/opt/d4follow"
DB = os.path.join(ROOT, "data", "iggm_follow.db")
MANUAL = os.path.join(ROOT, "data", "gold_manual.json")
STATE = os.path.join(ROOT, "data", "rpg_guard_state.json")
CONFIG = os.path.join(ROOT, "config.json")
# 不走「物品决策（decisions）」通道的游戏：AION2 由 g2gfollow 独立跑，
# MSCW 走 iggm_undercut，两者都不写 decisions 表 ⇒ 算停滞阈值时要排除。
DECISIONS_SKIP_GAMES = ("AION2", "MapleStory Classic World")

sys.path.insert(0, ROOT)
import msg_alert  # noqa: E402

FAIL_WINDOW_MIN = 30
STALL_MIN = 90
PROTECT_MAX_H = 24
GUARD_TOL = 0.01


def _now():
    return dt.datetime.now()


def _ago(mins):
    return (_now() - dt.timedelta(minutes=mins)).isoformat(timespec="seconds")


def _unit_active(unit):
    try:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, timeout=10)
        return (r.stdout or b"").decode().strip() == "active"
    except Exception:
        return False


def _hb_age_s():
    """执行器心跳是否新鲜（srv_exec.json 的 ts，轮询 10 秒刷一次）。"""
    try:
        with open(os.path.join(ROOT, "data", "srv_exec.json"), encoding="utf-8") as f:
            d = json.load(f)
        t = dt.datetime.strptime(str(d.get("ts"))[:19], "%Y-%m-%dT%H:%M:%S")
        return (_now() - t).total_seconds(), d
    except Exception:
        return None, {}


def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _latest_ts(con, table):
    try:
        r = con.execute("SELECT MAX(ts) t FROM %s" % table).fetchone()
        return r["t"] if r else None
    except Exception:
        return None


def _collect_periods():
    """各游戏采集周期（小时）→ dict；读不到/非法一律返回空 dict。"""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        d = (cfg.get("运行") or {}).get("采集周期小时") or {}
        out = {}
        for k, v in d.items():
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return out
    except Exception:                          # noqa: BLE001
        return {}


def _stall_min_for(table):
    """停滞阈值（分钟）——按「这张表正常多久该更新一次」给，不再写死 90。

    `gold_price` 由金币通道每 30 分钟刷一次 ⇒ 固定 STALL_MIN（90）。
    `decisions`（物品决策）只在「本轮有游戏到期、且跑完一整轮采集」后才写，
    所以它的正常间隔 ≈ 各物品类游戏里**最短的那个采集周期**。

    2026-10-26 事故：采集周期被调成 D4/POE2/WoW 3h、ARC 2.5h，而阈值仍是
    1 小时周期时代的 90 分钟 ⇒ 每两轮就必然误报一次「停滞 100+ 分钟」
    （实际下一次物品轮在 18:09 才到期，系统完全正常）。
    改为「最短物品周期 × 60 + 45 分钟宽限」，跟随配置自动伸缩；
    配置读不到才回落到 STALL_MIN（保住原来的保守行为）。
    """
    if table != "decisions":
        return STALL_MIN
    cand = [v for g, v in _collect_periods().items()
            if g not in DECISIONS_SKIP_GAMES and 0.25 <= v <= 24]
    if not cand:
        return STALL_MIN
    return max(STALL_MIN, int(round(min(cand) * 60)) + 45)


def main():
    out = {"ts": _now().isoformat(timespec="seconds"), "alerts": [], "notes": []}
    con = _con()

    # ① 服务存活（带重启宽限）
    #    2026-10-23 19:05 改：干净重启必然有 5~35 秒空窗（Restart=always + RestartSec=5，
    #    且退出前要等当前工单跑完，实测 19:00:37→19:01:08 停了 31 秒）。
    #    原来一看到非 active 就告警 ⇒ 我每次部署都自造一条"服务未运行"。
    #    现在：非 active ⇒ 先看执行器心跳（10 秒一刷），新鲜就算重启中；
    #          否则等 25 秒复检，仍非 active 才告警。
    for u in ("d4follow.service", "p2pah-srv-exec.service"):
        if _unit_active(u):
            continue
        _age, _hb = _hb_age_s()
        if u.startswith("p2pah-srv-exec") and _age is not None and _age < 120 and _hb.get("pid"):
            out["notes"].append("unit:%s 非 active 但心跳 %.0f 秒新鲜（重启中）" % (u, _age))
            continue
        time.sleep(25)
        if _unit_active(u):
            out["notes"].append("unit:%s 曾短暂非 active（重启窗口），已自动恢复" % u)
            continue
        msg_alert.alert(con, "guard-unit-" + u, "RPG 服务未运行：%s" % u,
                        "%s 当前不是 active，改价链路会整体停摆，请立刻处理。\n时间：%s"
                        % (u, out["ts"]), cooldown_s=900)
        out["alerts"].append("unit:" + u)

    # ①' order 后台会话（写价单的 cookie 来源，2026-10-23 补）
    #    执行器每张单初始化浏览器时都要注入 order.p2pah.cn 的 cookie；
    #    这个 broker 一旦 ready=false，**所有写价单都会整单失败**，而 systemd
    #    看到的服务是 active —— 不查就会"看着一切正常、其实一单都写不进去"。
    try:
        # ⚠ 用 curl 不用 urllib：broker 在 not ready 时返回 **503**，
        #    urllib 会把它当异常、读不到 JSON body，判据就永远不触发。
        def _order_health():
            # 2026-10-26：站点变慢时 broker 单次复验可到 10~16 秒，6 秒上限会把
            # 「正在复验」误判成「会话失效」（00:47:41 那次就是）。
            r = subprocess.run(["curl", "-s", "-m", "20",
                                "http://127.0.0.1:8768/health"],
                               capture_output=True, timeout=25)
            return json.loads((r.stdout or b"{}").decode("utf-8", "replace") or "{}")

        h = _order_health()
        if not h.get("ready"):
            # 2026-10-23 19:05：单次探针不可信（broker 每 N 秒复验一次，
            #   复验窗口内 ready 会短暂翻 false）⇒ 等 10 秒再确认一次。
            time.sleep(10)
            h2 = _order_health()
            if h2.get("ready"):
                out["notes"].append("order 会话探针瞬时 false，10 秒后恢复（不告警）")
                out["order_session"] = "ready"
                h = {"ready": True}
            elif h2.get("checking"):
                out["notes"].append("order 会话 broker 正在复验（checking=true）"
                                    "，本轮不判失效")
                out["order_session"] = "checking"
                h = {"ready": True}
            else:
                h = h2
        if not h.get("ready"):
            msg_alert.alert(
                con, "guard-order-session",
                "order 后台会话失效：接下来的改价单会全部失败",
                "fs-order-session 报 ready=false（%s，已验证 %.0f 秒前）。\n"
                "执行器每次起容器都要注入 order.p2pah.cn 的 cookie，取不到就抛 "
                "global_order_unavailable ⇒ 整单失败。\n"
                "处置：在 fs-order-browser 那个浏览器里重新登录 order.p2pah.cn"
                "（该账号只允许这一个登录方，脚本不得自行登录）。"
                % (h.get("last_error") or "-", float(h.get("verified_age_seconds") or 0)),
                cooldown_s=1800)
            out["alerts"].append("order_session")
        else:
            out["order_session"] = "ready"
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("order 健康检查失败：%r" % e)

    # ①'' 容器起不来（docker 层面，2026-10-23 22:39 事故新增）
    #   事故：srv_exec.py 被外部改动加了 `--memory 2g --memory-swap 2g`，与原有
    #   `--memory=3g` 冲突 ⇒ docker run 返回 125「memoryswap 必须 ≥ memory」，
    #   所有改价单与只读对账 0 秒失败，而 systemd 仍是 active（又一次"看着正常"）。
    #   这条判据只读日志：近 30 分钟内出现过 docker 守护进程报错 ⇒ 告警。
    try:
        import re
        logp = os.path.join(ROOT, "logs", "srv_exec.log")
        recent = []
        with open(logp, encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 120000))
            for line in f:
                if "Error response from daemon" not in line and "docker:" not in line:
                    continue
                m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
                if not m:
                    continue
                try:
                    t = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if (_now() - t).total_seconds() <= 30 * 60:
                    recent.append((m.group(1), line.strip()[40:160]))
        if recent:
            msg_alert.alert(
                con, "guard-docker-run",
                "执行器容器起不来：docker 直接拒绝（改价单会全部 0 秒失败）",
                "\n".join("- %s %s" % x for x in recent[-4:])
                + "\n\n多半是 docker run 参数冲突（如 --memory 与 --memory-swap 不一致）"
                  "或守护进程/磁盘异常。先看 /opt/d4follow/srv_exec.py 的 docker run 参数"
                  "是否被改动，再手动跑一次 docker run 验证。",
                cooldown_s=1800)
            out["alerts"].append("docker_run:%d" % len(recent))
            out["docker_run"] = [x[0] for x in recent[-4:]]
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("docker 日志检查失败：%r" % e)

    # ①''' 库锁（2026-10-26：pricing_monitor_read_failed:OperationalError）
    #    事故：外部只读巡检（fs-pricing-alerts，timeout=2s）读 RPG 库报 database is locked；
    #    实测 00:20:03~00:20:07 连续 7 次读失败，00:07:21~00:12:02 连写者都进不去。
    #    已把库切 WAL（读者读快照、不再被写者阻塞），现场探针仍留着兜底：
    #      a) 用**和外部巡检同款**的 2 秒超时读一次 local_job ⇒ 失败即告警；
    #      b) 看门狗 data/db_lock_state.json 里 held_s ≥ 30 且是近 20 分钟的
    #         ⇒ 有过长时间持锁，把持锁进程一起报出来（这才是根因线索）。
    try:
        import sqlite3 as _sq
        locked = None
        try:
            _c = _sq.connect("file:%s?mode=ro" % DB, uri=True, timeout=2)
            _c.execute("PRAGMA query_only=ON")
            _c.execute("SELECT id FROM local_job ORDER BY id DESC LIMIT 2001").fetchall()
            _c.close()
            out["db_read"] = "ok"
        except Exception as e:                   # noqa: BLE001
            locked = repr(e)
            out["db_read"] = "locked:%s" % locked
        st = {}
        try:
            with open(os.path.join(ROOT, "data", "db_lock_state.json"), encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = {}
        held = float(st.get("held_s") or 0)
        fresh = False
        try:
            fresh = (_now() - dt.datetime.strptime(str(st.get("ts"))[:19],
                                                   "%Y-%m-%dT%H:%M:%S")).total_seconds() <= 20 * 60
        except Exception:                        # noqa: BLE001
            fresh = False
        if fresh:
            out["db_lock"] = {"held_s": held, "holders": st.get("holders")}
        if locked or (fresh and held >= 30):
            hs = st.get("holders") or []
            msg_alert.alert(
                con, "guard-db-lock",
                "RPG 库被写锁挡住（外部巡检/接口会报 database is locked）",
                ("现场探针：2 秒超时读 local_job 失败 ⇒ %s\n" % locked) if locked
                else "现场可读，但看门狗记录到一次长持锁。\n"
                + "\n时间：%s ｜ 持锁 %.1f 秒\n" % (st.get("ts"), held)
                + "持锁/打开该库的进程：\n"
                + ("\n".join("- pid %s  %s" % (p, c[:120]) for p, c in hs) or "- （进程已退出）")
                + "\n\n该库已切 WAL（journal_mode=wal），读者不再被写者阻塞；"
                  "若仍报 locked，说明有人把写事务开得很长（BEGIN 后不提交）。"
                  "优先查上面列出的进程。",
                cooldown_s=1800)
            out["alerts"].append("db_lock")
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("库锁检查失败：%r" % e)

    # ② 近 30 分钟失败单
    rows = []
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT id, kind, title, attempts,"
            " COALESCE(finished_at, created_at) AS t"
            " FROM local_job WHERE status='failed'"
            " AND COALESCE(finished_at, created_at) >= ?"
            " AND instr(COALESCE(result_json, ''), '\"superseded_by\"') = 0",
            (_ago(FAIL_WINDOW_MIN),))]
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("读失败单出错：%r" % e)
    if rows:
        msg_alert.alert(
            con, "guard-failed-%d" % (_now().hour // 2),
            "RPG 改价失败 %d 单（近 %d 分钟）" % (len(rows), FAIL_WINDOW_MIN),
            "\n".join("- %s [%s] %s（attempts=%s）"
                      % (r["id"], r["kind"], (r["title"] or "")[:40], r["attempts"])
                      for r in rows[:6])
            + "\n\n请看护日志与 _p2pah_srv/_jobs/ 下的执行回执。",
            cooldown_s=1800)
        out["alerts"].append("failed:%d" % len(rows))

    # ③ 同一单反复失败
    rep = []
    try:
        rep = [dict(r) for r in con.execute(
            "SELECT id, kind, title, attempts FROM local_job"
            " WHERE status='failed' AND COALESCE(attempts, 0) >= 3"
            " AND COALESCE(finished_at, created_at) >= ?"
            " AND instr(COALESCE(result_json, ''), '\"superseded_by\"') = 0",
            (_ago(24 * 60),))]
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("读反复失败出错：%r" % e)
    if rep:
        msg_alert.alert(con, "guard-repeat-fail",
                        "RPG 同一工单反复失败 %d 单" % len(rep),
                        "\n".join("- %s [%s] attempts=%s %s"
                                  % (r["id"], r["kind"], r["attempts"],
                                     (r["title"] or "")[:40]) for r in rep[:6])
                        + "\n\n反复失败通常意味着后台页面结构变了或会话失效，不是价格问题。",
                        cooldown_s=3600)
        out["alerts"].append("repeat:%d" % len(rep))

    # ④ 停滞
    for tbl, label in (("gold_price", "金币快照"), ("decisions", "物品决策快照")):
        t = _latest_ts(con, tbl)
        if not t:
            continue
        try:
            age = (_now() - dt.datetime.strptime(
                str(t)[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 60.0
        except Exception:
            continue
        out.setdefault("age_min", {})[label] = round(age, 1)
        lim = _stall_min_for(tbl)
        out.setdefault("stall_min", {})[label] = lim
        if age > lim:
            msg_alert.alert(con, "guard-stall-" + tbl,
                            "%s 停滞 %.0f 分钟" % (label, age),
                            "最新%s是 %s，已 %.0f 分钟没有新数据（阈值 %d 分钟）。\n"
                            "可能原因：采集被熔断 / 进程卡住 / IGGM 抓取失败。"
                            % (label, t, age, lim), cooldown_s=3600)
            out["alerts"].append("stall:%s" % tbl)

    # ⑤ 人工改价保护悬挂
    try:
        man = json.load(open(MANUAL, encoding="utf-8")) if os.path.exists(MANUAL) else {}
    except Exception:
        man = {}
    if not isinstance(man, dict):
        man = {}
    hung = []
    for k, v in man.items():
        try:
            age_h = (_now() - dt.datetime.strptime(
                str((v or {}).get("ts"))[:19],
                "%Y-%m-%dT%H:%M:%S")).total_seconds() / 3600.0
        except Exception:
            continue
        if age_h > PROTECT_MAX_H:
            hung.append((k, (v or {}).get("现值"), round(age_h, 1)))
    out["manual_protected"] = sorted(man.keys())
    if hung:
        msg_alert.alert(con, "guard-manual-hung",
                        "人工改价保护 %d 个区已超 %d 小时" % (len(hung), PROTECT_MAX_H),
                        "\n".join("- %s 后台 ￥%s（%.1f 小时）" % h for h in hung)
                        + "\n\n这些区一直在用人工价、不跟 IGGM（IGGM 未变价）。"
                          "若人工价已不需要，把后台改回算法值即可解除。",
                        cooldown_s=12 * 3600)
        out["alerts"].append("manual_hung:%d" % len(hung))

    # ⑥ 人工价被覆盖（保护闸没兜住）
    # 🔴 2026-10-29 老板口径：人工改价保护已**彻底关闭**。实际业务里同事改的是后台
    #    **折扣系数（0.2 → 0.3 之类）**，脚本按固定 0.2 反推写 costprice，与「改过系数
    #    后的后台实际值」本来就必然不等 —— 这是设计内的正常差异，不是"人工价被覆盖"。
    #    闸关掉以后 `if k in man` 恒为假 ⇒ 这条检查把每轮正常差异全报成覆盖
    #    （实测一口气报 82 处），因此配置关闭时整段跳过。
    over = []
    try:
        _mgcfg = {}
        try:
            with open(CONFIG, encoding="utf-8") as _f:
                _mgcfg = ((json.load(_f).get("金币") or {}).get("人工改价保护") or {})
        except Exception:                        # noqa: BLE001
            _mgcfg = {}
        if _mgcfg.get("启用") is False:
            out["notes"].append("人工改价保护已关闭 ⇒ 跳过「人工价被覆盖」检查")
        else:
            files = sorted(glob.glob(os.path.join(
                ROOT, "_p2pah_srv", "p2pah_writegold_result_*.json")))[-12:]
            for fp in files:
                try:
                    d = json.load(open(fp, encoding="utf-8"))
                except Exception:
                    continue
                for x in (d.get("jobs") or []):
                    k = str((x or {}).get("key") or "")
                    cur, old = x.get("改前实际"), x.get("旧")
                    try:
                        if cur is None or old is None or float(old) <= 0:
                            continue
                        if abs(float(cur) - float(old)) / abs(float(old)) > GUARD_TOL:
                            if k in man:
                                continue        # 已进保护：正常
                            over.append((os.path.basename(fp), k, cur, old))
                    except (TypeError, ValueError):
                        continue
    except Exception as e:                       # noqa: BLE001
        out["notes"].append("读金币结果出错：%r" % e)
    if over:
        msg_alert.alert(con, "guard-overwrite",
                        "检测到 %d 处疑似人工价被覆盖" % len(over),
                        "\n".join("- %s %s：后台现值 %s（本链路上次写入 %s）" % o
                                  for o in over[:8]),
                        cooldown_s=1800)
        out["alerts"].append("overwrite:%d" % len(over))

    con.close()
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
