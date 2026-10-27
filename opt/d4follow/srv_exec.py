# -*- coding: utf-8 -*-
"""服务器端执行器 · 宿主侧常驻进程（systemd: p2pah-srv-exec.service）

干什么
------
让新机 `47.85.224.112` **自己**把改价工单跑完，不再需要本机开机：

    认领工单（exec_mode='server'）
      → 快照 config.json 进容器挂载目录
      → docker run p2pah-srv:1 python /srv/srv_run.py <write|writegold> --confirm
      → 解析结果 → 回写 local_job（看板直接可见）

为什么能这么做
--------------
2026-09-27 起新机 IP 已被加入 `order.p2pah.cn` 白名单（同一 cookie、同一受保护页，
新机与本机 200 / 107017 字节、md5 一致），服务器登录/读/写三条通道都已实测通过。
容器 `p2pah-srv:1` = `qd-render:1.47`（playwright 1.47 + chromium）+ ddddocr，
所以「图形验证码登录」也在服务器本地完成，全程无人值守。

安全闸门（按顺序，任一不满足就不执行）
--------------------------------------
1. `data/srv_exec_off` 文件存在        → 急停（运维用，UI 不暴露）。
2. `config 跟价.系统开关` == false     → 认领到的单原样退回 pending（不误改价）。
3. docker daemon 不可用                → 退单，等恢复。

关于 `config 跟价.执行方式`
---------------------------
这个开关**只决定派单侧给新单打什么标记**：`server` → 新单 exec_mode='server'；
`local` → 新单 exec_mode='local'。执行器**不看这个开关**，只看单子身上的
exec_mode —— 因为看板要支持「逐单改派」，若执行器在 mode=local 时整体待命，
人工改派过来的单就永远没人执行。要整体停服务器执行请用 `srv_exec_off` 或 stop 服务。

⚠ 单实例：同一个 browser profile 不能被两个容器同时打开（chromium profile 会锁），
  所以本脚本单线程串行，并用文件锁兜住「被启动两次」。
"""
import datetime as dt
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time

ROOT = "/opt/d4follow"
DATA = os.path.join(ROOT, "data")
SRV = os.path.join(ROOT, "_p2pah_srv")
JOBS = os.path.join(SRV, "_jobs")
CFG = os.path.join(ROOT, "config.json")
CFG_SNAP = os.path.join(SRV, "_cfg", "config.json")
STATE = os.path.join(DATA, "srv_exec.json")
OFF_SWITCH = os.path.join(DATA, "srv_exec_off")
LOCK = os.path.join(DATA, "srv_exec.lock")
LOG_DIR = os.path.join(ROOT, "logs")

DOCKER = "/usr/bin/docker"
IMAGE = "p2pah-srv:1"
# 2026-10-23（裁定 D 配套）：金币现值只读对账
RECON_EVERY_MIN = 20
RECON_STATE = os.path.join(DATA, "gold_recon_state.json")
RECON_DUMP = os.path.join(JOBS, "_gold_recon.json")
RECON_TOL = 0.01
POLL_S = 10                 # 空转轮询间隔
JOB_TIMEOUT_S = 3600        # 单张工单最长执行时间（金币单要跑推送+清缓存，给足）

sys.path.insert(0, ROOT)
import msg_alert  # noqa: E402
import store as S  # noqa: E402

STOP = False
ST = {
    "started": None, "state": "starting", "job": None, "kind": None,
    "mode": None, "done": 0, "failed": 0, "last_result": None, "note": "",
}


def log(msg):
    print("[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def _sig(_sig, _frm):
    global STOP
    STOP = True
    log("收到信号 %s：当前工单跑完就退出" % _sig)


def flush_state():
    ST["ts"] = dt.datetime.now().isoformat(timespec="seconds")
    ST["pid"] = os.getpid()
    try:
        os.makedirs(DATA, exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(ST, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
    except Exception as e:
        log("写状态失败：%r" % e)


def read_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("读 config 失败：%r" % e)
        return {}


def cfg_get(c, path, default=None):
    cur = c
    for p in str(path).split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def _requeue(con, jid, why):
    """把认领回来、但决定不执行的单**原样退回 pending**（不是失败）。

    这类「不执行」是可恢复的（总开关关着 / docker 挂了），不能标 failed 把单弄丢。
    """
    now = dt.datetime.now().isoformat(timespec="seconds")
    con.execute("UPDATE local_job SET status='pending', agent=NULL, claimed_at=NULL,"
                " log=coalesce(log,'')||char(10)||?"
                " WHERE id=? AND status='dispatched'",
                ("%s 退回排队：%s" % (now, why), jid))
    con.commit()


def _record_gold_manual(con, res, jid):
    """登记「人工改价保护」（2026-10-23 大超裁定 D）。

    执行器在现场发现「后台现值 ≠ 本链路上次写入值」⇒ 判定有人工改价、跳过该区。
    这里把这次判定落成 data/gold_manual.json：{key: {ts, 现值, 上次写入, job, iggm锚}}。
    app.py 派单前读这张表：保护中且 **IGGM 锚价未变** ⇒ 不派单（不重复覆盖、不刷单）；
    IGGM 一变价就解除，恢复正常跟随。

    ⚠ 用文件不用新表：这张表只服务派单闸，读写都在同一台机器，
      与 auto_dispatch_state.json 同一套路（写 .tmp 再 os.replace，原子替换）。
    """
    items = (res or {}).get("manual_skip") or []
    if not items:
        return 0
    path = os.path.join(DATA, "gold_manual.json")
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
        if not isinstance(cur, dict):
            cur = {}
    except (OSError, ValueError):
        cur = {}
    ig = {}
    try:
        rows, _gts = S.gold_latest(con)
        for r in rows:
            ig[str(r.get("key"))] = r.get("iggm_per_m")
    except Exception:
        pass
    ts = dt.datetime.now().isoformat(timespec="seconds")
    n = 0
    for x in items:
        k = str((x or {}).get("key") or "")
        if not k:
            continue
        cur[k] = {"ts": ts, "现值": x.get("现值"), "上次写入": x.get("上次写入"),
                  "差异%": x.get("差异%"), "job": jid, "iggm锚": ig.get(k)}
        log("  ⏸ 人工改价保护登记 %s：后台 ￥%s（本链路上次写入 ￥%s）"
            % (k, x.get("现值"), x.get("上次写入")))
        n += 1
    if not n:
        return 0
    try:
        os.makedirs(DATA, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception as e:                       # noqa: BLE001
        log("  ⚠ 人工改价保护落盘失败：%r" % e)
        return 0
    return n


def _recon_apply(con, cfg, d):
    """把只读对账结果落到 gold_actual.json，并对「被手工改过」的区登记保护。"""
    svs = ((cfg.get("金币") or {}).get("服务区") or [])
    key_of_row = {}
    for sv in svs:
        rid = str((sv or {}).get("后台行ID") or "")
        if rid:
            key_of_row[rid] = sv.get("key")

    rows = (d or {}).get("rows") or {}
    actual = {}
    for rid, rec in rows.items():
        k = key_of_row.get(str(rid))
        if not k:
            continue
        try:
            v = float((rec or {}).get("costprice"))
        except (TypeError, ValueError):
            continue
        actual[k] = {"现值": v, "row_id": str(rid), "ts": d.get("ts")}

    known = {}
    ig = {}
    try:
        known = {r["key"]: r["cost"] for r in con.execute("SELECT key,cost FROM gold_state")}
        t = con.execute("SELECT MAX(ts) t FROM gold_price").fetchone()["t"]
        for r in con.execute("SELECT key,iggm_per_m FROM gold_price WHERE ts=?", (t,)):
            ig[r["key"]] = r["iggm_per_m"]
    except Exception as e:                       # noqa: BLE001
        log("  对账读库失败（继续按现值落盘）：%r" % e)

    man_path = os.path.join(DATA, "gold_manual.json")
    try:
        with open(man_path, encoding="utf-8") as f:
            man = json.load(f)
        if not isinstance(man, dict):
            man = {}
    except (OSError, ValueError):
        man = {}

    ts = dt.datetime.now().isoformat(timespec="seconds")
    changed = []
    for k, info in actual.items():
        cur = info["现值"]
        try:
            old = float(known.get(k))
        except (TypeError, ValueError):
            continue
        if old <= 0:
            continue
        if abs(cur - old) / abs(old) <= RECON_TOL:
            continue
        changed.append((k, cur, old))
        if k in man:
            continue                          # 已在保护中：保持原 ts / 原 IGGM 锚
        man[k] = {"ts": ts, "现值": cur, "上次写入": old,
                  "差异%": round((cur - old) / old * 100.0, 2),
                  "job": "recon", "iggm锚": ig.get(k)}

    try:
        p = os.path.join(DATA, "gold_actual.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": ts, "rows": actual}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception as e:                       # noqa: BLE001
        log("  ⚠ 写 gold_actual 失败：%r" % e)

    if changed:
        try:
            tmp = man_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(man, f, ensure_ascii=False, indent=1)
            os.replace(tmp, man_path)
        except Exception as e:                   # noqa: BLE001
            log("  ⚠ 写 gold_manual 失败：%r" % e)
        log("  ⏸ 对账发现 %d 个服务区被手工改过 → 登记人工改价保护：%s"
            % (len(changed),
               "、".join("%s(￥%s≠￥%s)" % (k, c, o) for k, c, o in changed[:6])))
        try:
            msg_alert.alert(
                con, "gold-recon-manual-" + dt.datetime.now().strftime("%Y%m%d%H"),
                "对账发现 %d 个服务区的采购成本被手工改过" % len(changed),
                "\n".join("- %s 后台 ￥%.6f（链路记账 ￥%.6f，差 %.1f%%）"
                          % (k, c, o, (c - o) / o * 100.0) for k, c, o in changed)
                + "\n\n已登记「人工改价保护」：IGGM 未变价前不再覆盖这些区。",
                cooldown_s=1800)
        except Exception:
            pass
    return len(actual), len(changed)


def _recon_readgold(con, cfg):
    """起只读容器读后台采购成本现值（不写价、不推前端、不清缓存）。"""
    try:
        shutil.copyfile(CFG, CFG_SNAP)
    except Exception as e:                       # noqa: BLE001
        log("  对账：config 快照失败 %r" % e)
    os.makedirs(JOBS, exist_ok=True)
    if os.path.exists(RECON_DUMP):
        try:
            os.remove(RECON_DUMP)
        except OSError:
            pass
    cmd = [DOCKER, "run", "--rm", "--init", "--memory", "3g", "--memory-swap", "3g",
           "--cpus", "2",
           "--network", "fc27-cloud-net",
           "-e", "FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767",
           "--mount", "type=bind,src=/opt/fs-order-session/fc_shared_admin.py,"
                      "dst=/srv/fc_shared_admin.py,readonly",
           "-v", "%s:/srv" % SRV, "-w", "/srv",
           "--shm-size=1g", "--memory=3g",
           "-e", "P2PAH_CHANNEL=",
           IMAGE, "python", "/srv/srv_run.py", "readgold",
           "--dump", "/srv/_jobs/_gold_recon.json",
           "--config", "/srv/_cfg/config.json",
           "--profile", "/srv/_srv_profile"]
    log("  ▶ 只读对账：读后台金币采购成本现值 …")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=JOB_TIMEOUT_S)
        rc = r.returncode
        out = ((r.stdout or b"").decode("utf-8", "replace")
               + (r.stderr or b"").decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        log("  ⚠ 对账容器超时（%ss）" % JOB_TIMEOUT_S)
        return False
    except Exception as e:                       # noqa: BLE001
        log("  ⚠ 对账容器异常：%r" % e)
        return False
    if rc != 0:
        log("  ⚠ 对账容器返回 %s：%s" % (rc, " / ".join(
            [x for x in out.strip().splitlines() if x.strip()][-3:])))
        return False
    try:
        with open(RECON_DUMP, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        log("  ⚠ 读不到对账输出：%r" % e)
        return False
    n, c = _recon_apply(con, cfg, d)
    log("  对账完成：读到 %d 行采购成本，其中 %d 个区被手工改过" % (n, c))
    return True


def _recon_due():
    """距上次对账是否已超过 RECON_EVERY_MIN 分钟"""
    try:
        with open(RECON_STATE, encoding="utf-8") as f:
            last = json.load(f).get("ts")
        age = (dt.datetime.now() - dt.datetime.strptime(
            str(last)[:19], "%Y-%m-%dT%H:%M:%S")).total_seconds() / 60.0
        return age >= RECON_EVERY_MIN
    except Exception:
        return True


def _recon_mark(ok=True):
    """成功 => 整个周期后再跑；失败 => 5 分钟后重试。

    2026-10-23 19:04 修：原来不判成败就写时间戳。18:49 那次因 order 会话失效失败，
    却照样把「上次对账」推到 18:49 => 白等一个整周期，人工改动 20 分钟无人发现。
    """
    try:
        tmp = RECON_STATE + ".tmp"
        _t = dt.datetime.now()
        if not ok:
            _t = _t - dt.timedelta(minutes=max(0, RECON_EVERY_MIN - 5))
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": _t.isoformat(timespec="seconds"), "ok": bool(ok)}, f)
        os.replace(tmp, RECON_STATE)
    except Exception:
        pass


def _read_result(kind, t0):
    """读 p2pah_local 落盘的结果 JSON（容器内 HERE=/srv = 宿主 _p2pah_srv/）。"""
    pat = "p2pah_writegold_result_" if kind == "writegold" else "p2pah_write_result_"
    best, best_m = None, 0.0
    try:
        for fn in os.listdir(SRV):
            if fn.startswith(pat) and fn.endswith(".json"):
                fp = os.path.join(SRV, fn)
                m = os.path.getmtime(fp)
                if m >= t0 - 5 and m > best_m:
                    best, best_m = fp, m
    except Exception:
        return None
    if not best:
        return None
    try:
        with open(best, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log("结果文件解析失败 %s：%r" % (best, e))
        return None


def _failover_to_local(con, cfg, job, why):
    """改价失败 → 把同一张工单**克隆成 exec_mode='local'**，交本机执行器重试。

    为什么需要（2026-10-19 老板要求）：服务器出口 IP 被 CF / 后台风控拦住的场景，
    在容器里怎么重试都没用；本机是住宅 IP + 独立浏览器 profile，往往一次就过。
    等人工在看板点「改用本机执行」太慢，这里失败即自动改派。

    三道闸（防重复 / 防循环 / 防误发）：
      ① config `跟价.本机兜底` = false → 不兜底（只告警）；
      ② 本单本身已经是兜底单（标题带「本机兜底」）→ 不再二次兜底，只告警，
         否则两边会互相踢单、无限重试；
      ③ 队列里已有**同内容**（同 kind + 同 plan_json）的 pending/dispatched 本机单
         → 不重复派，避免同一批价改两遍。
    返回新单号（没派则 None）。
    """
    jid = job.get("id") or "?"
    title = job.get("title") or ""
    if not bool(cfg_get(cfg, "跟价.本机兜底", True)):
        log("  ↪ 失败转本机：config 跟价.本机兜底=false，不兜底（仅告警）")
        msg_alert.alert(con, "job-fail-" + jid, "改价失败（未兜底）",
                        "- 工单：%s（%s）\n- 原因：%s\n\n兜底开关已关，需人工处理。"
                        % (jid, title, why), cooldown_s=1800)
        return None
    if "本机兜底" in title:
        log("  ↪ 本单已是本机兜底单，失败后不再二次兜底（防来回踢单）")
        msg_alert.alert(con, "job-local-fail-" + jid, "本机兜底单也失败了",
                        "- 工单：%s（%s）\n- 原因：%s\n\n请人工核对后台价格。"
                        % (jid, title, why), cooldown_s=900)
        return None

    # 2026-10-21 事故：本机不在线时**不要改派**。
    # broker（fs-order-session）掉线 -> 服务器单全失败 -> 每张都克隆一张「本机兜底」单，
    # 而本机执行器 2026-09-29 起改为按需启动（心跳停在 10-14），10 张单静默排队 1.5h。
    # 判据与 app._pick_exec_mode 保持一致：本机心跳 <=5 分钟才算在线。
    _ls, _fresh = "", False
    try:
        _ag = S.local_agent_get(con) or {}
        _ls = str(_ag.get("last_seen") or "")
        if _ls:
            _age = (dt.datetime.now()
                    - dt.datetime.strptime(_ls, "%Y-%m-%dT%H:%M:%S")).total_seconds()
            _fresh = _age <= 300
    except Exception:
        _fresh = False
    if not _fresh:
        log("  ↪ 本机执行器未在线（心跳 %s）→ **不改派**：单子留作失败，"
            "等下一轮采集按新价重出单" % (_ls or "从无"))
        msg_alert.alert(con, "job-fail-nolocal", "改价失败且本机执行器未在线",
                        "- 工单：%s（%s）\n- 原因：%s\n- 本机心跳：%s\n\n"
                        "未自动转本机（转了也没人跑）。请检查 fs-order-session / 后台登录态。"
                        % (jid, title, why, _ls or "从无"), cooldown_s=1800)
        return None

    try:
        plan = json.loads(job.get("plan_json") or "{}")
    except Exception as e:
        log("  ⚠ 兜底派单失败：工单 JSON 解析不了：%r" % e)
        return None
    try:
        dup = con.execute(
            "SELECT id FROM local_job WHERE kind=? AND exec_mode='local'"
            " AND status IN ('pending','dispatched') AND plan_json=? LIMIT 1",
            (job.get("kind"), job.get("plan_json") or "")).fetchone()
    except Exception:
        dup = None
    if dup:
        log("  ↪ 队列里已有同内容的本机单 %s，不重复派" % dup[0])
        return None
    try:
        nid = S.local_job_add(
            con, kind=job.get("kind") or "write",
            title=("%s（服务器失败→本机兜底）" % title)[:120],
            plan_path=job.get("plan_path") or "", plan=plan,
            summary="服务器执行失败自动转本机：%s" % (why or "")[:120],
            actor="srv-exec/auto-failover", exec_mode="local")
    except Exception as e:
        log("  ⚠ 兜底派单失败：%r" % e)
        return None
    # 原单留痕（看板上能直接看到「这单被谁接手了」）
    try:
        now = dt.datetime.now().isoformat(timespec="seconds")
        con.execute("UPDATE local_job SET log=coalesce(log,'')||char(10)||? WHERE id=?",
                    ("%s ↩ 已自动转本机兜底：新单 %s" % (now, nid), jid))
        con.commit()
    except Exception as e:
        log("  ⚠ 原单留痕失败：%r" % e)
    log("  ↪ 已自动转本机兜底：新单 %s" % nid)
    msg_alert.alert(
        con, "job-failover-" + nid, "改价失败，已自动转本机执行",
        "- 原工单：%s（%s）\n- 失败原因：%s\n- 兜底单：**%s**\n\n"
        "本机执行器在线即自动执行；不在线会在队列里等，不会丢单。"
        % (jid, title, why, nid), cooldown_s=600)
    return nid


def execution_state(result, phase, returncode):
    """Only a finished, persisted zero-write phase proves failover is safe."""
    complete = (isinstance(result, dict) and isinstance(result.get("jobs"), list)
                and "ok" in result and "fail" in result and isinstance(result.get("mismatch"), list))
    if returncode == 0 and complete:
        return "confirmed", False
    if complete and (result.get("ok") or result.get("mismatch")):
        return "partial", False
    if (returncode not in (0, -9, -1) and phase.get("finished") is True
            and type(phase.get("write_attempts")) is int and phase["write_attempts"] == 0):
        return "prewrite_failed", True
    return "unknown", False


def run_once():
    """跑一轮：有单就执行（返回 True），没单/不满足条件返回 False。"""
    cfg = read_cfg()
    mode = str(cfg_get(cfg, "跟价.执行方式", "server")).lower()
    ST["mode"] = mode

    # 「执行方式」只管**派单侧给新单打什么标记**（app.py 读同一个配置）：
    #   server → 新单 exec_mode='server'；local → 新单 exec_mode='local'。
    # 执行器这边**不再因为 mode=local 就整体待命** —— 否则看板上「改用服务器」
    # 这个人工改派按钮在 mode=local 时会彻底失效（改派了也没人执行）。
    # 所以判据只有一条：单子自己身上的 exec_mode 是不是 'server'
    # （local_job_claim_srv 已按此过滤，人工改派过来的单也算）。
    # 要整体停掉服务器执行：建 data/srv_exec_off 急停文件，或 systemctl stop。
    # ⚠ 每轮都重设 note：否则切回 server 后，看板还在显示上一次 local 时留下的话。
    if mode == "local":
        ST["note"] = "当前执行方式=本机（新单给本机）；服务器仍会执行被人工改派过来的单"
    else:
        ST["note"] = ""

    if os.path.exists(OFF_SWITCH):
        ST["state"] = "off"
        ST["note"] = "急停开关存在：%s（删掉该文件即恢复）" % OFF_SWITCH
        return False

    con = S.connect(DATA)
    job = S.local_job_claim_srv(con)
    if not job:
        ST["state"] = "idle"
        if not ST.get("note"):
            ST["note"] = "队列里没有待服务器执行的工单"
        return False

    jid, kind = job["id"], job["kind"]
    ST.update({"state": "running", "job": jid, "kind": kind, "note": ""})
    flush_state()
    log("认领工单 %s（%s）" % (jid, kind))

    # 闸门③：执行时再核一次总开关（派单时是开的，执行时可能已被关）
    if not cfg_get(cfg, "跟价.系统开关", True):
        _requeue(con, jid, "系统总开关=关（只看不改）")
        ST.update({"state": "idle", "job": None, "kind": None,
                   "note": "系统总开关=关，工单已退回排队"})
        log("  ⏸ 系统总开关=关 → 工单退回排队，未发任何写请求")
        return False

    # 闸门④：docker 可用性
    try:
        chk = subprocess.run([DOCKER, "info"], capture_output=True, timeout=30)
        if chk.returncode != 0:
            _requeue(con, jid, "docker daemon 不可用")
            ST.update({"state": "error", "job": None, "kind": None,
                       "note": "docker daemon 不可用，工单已退回排队"})
            log("  ⚠ docker 不可用 → 工单退回排队")
            return False
    except Exception as e:
        _requeue(con, jid, "docker 探测失败：%r" % e)
        ST.update({"state": "error", "job": None, "kind": None,
                   "note": "docker 探测失败，工单已退回排队"})
        log("  ⚠ docker 探测失败：%r" % e)
        return False

    # ① config 快照（容器里读不到宿主的 /opt/d4follow/config.json，只挂了 _p2pah_srv）
    os.makedirs(os.path.dirname(CFG_SNAP), exist_ok=True)
    shutil.copyfile(CFG, CFG_SNAP)

    # ② 工单落盘（容器内路径 /srv/_jobs/<jid>.json）
    os.makedirs(JOBS, exist_ok=True)
    plan_path = os.path.join(JOBS, jid + ".json")
    try:
        plan = json.loads(job.get("plan_json") or "{}")
    except Exception as e:
        S.local_job_finish(con, jid, ok=False, log="工单 JSON 解析失败：%r" % e,
                           agent="srv-exec")
        ST.update({"state": "idle", "job": None, "kind": None, "failed": ST["failed"] + 1,
                   "last_result": {"job": jid, "ok": False, "ts": ST["ts"],
                                   "why": "工单 JSON 解析失败"}})
        return False
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)

    cmd = [DOCKER, "run", "--rm", "--init", "--memory", "3g", "--memory-swap", "3g",
           "--cpus", "2",
           "--network", "fc27-cloud-net",
           "-e", "FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767",
           "-e", "FS_RPG_JOB_ID=" + jid,
           "-e", "FS_RPG_EXECUTION_RECEIPT=/srv/_jobs/" + jid + ".execution.json",
           "--mount", "type=bind,src=/opt/fs-order-session/fc_shared_admin.py,dst=/srv/fc_shared_admin.py,readonly",
           "-v", "%s:/srv" % SRV, "-w", "/srv",
           "--shm-size=1g", "--memory=3g",
           # 容器里没有 Edge：让 p2pah_autologin / admin_cache_local 回落到
           # playwright 自带 chromium（不设该变量时默认 msedge，本机行为不变）。
           "-e", "P2PAH_CHANNEL=",
           IMAGE, "python", "/srv/srv_run.py",
           "writegold" if kind == "writegold" else "write",
           "--plan", "/srv/_jobs/%s.json" % jid,
           "--confirm",
           "--config", "/srv/_cfg/config.json",
           "--profile", "/srv/_srv_profile"]

    t0 = time.time()
    log("  ▶ 容器执行：%s" % " ".join(cmd[-9:]))
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=JOB_TIMEOUT_S)
        rc = r.returncode
        out = ((r.stdout or b"").decode("utf-8", "replace")
               + (r.stderr or b"").decode("utf-8", "replace"))
    except subprocess.TimeoutExpired:
        rc, out = -9, "执行超时（%ss）—— 容器已被放弃，请人工核对后台价格" % JOB_TIMEOUT_S
    except Exception as e:
        rc, out = -1, "执行器异常：%r" % e
    sec = round(time.time() - t0, 1)

    res = _read_result(kind, t0)
    try:
        with open(os.path.join(JOBS, jid + ".execution.json"), encoding="utf-8") as stream:
            phase = json.load(stream)
        if not isinstance(phase, dict) or phase.get("job_id") != jid:
            phase = {}
    except (OSError, ValueError):
        phase = {}
    if not isinstance(res, dict) or res.get("operation_id") != jid:
        res = None
    write_state, safe_failover = execution_state(res, phase, rc)
    ok = rc == 0 and write_state == "confirmed" and res.get("ok") is not False
    if res is None:
        res = {"ok": False, "returncode": rc, "sec": sec}
    res["write_state"] = write_state
    res["write_attempts"] = phase.get("write_attempts")
    res["original_job_id"] = jid

    if isinstance(res, dict):
        res["publication_status"] = (
            "cache_failed" if ok and res.get("clearcache_wanted") and res.get("clearcache_ok") is False
            else "backend_complete" if ok else "unconfirmed")

    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-160:]
    S.local_job_finish(con, jid, ok=ok, log="\n".join(tail), result=res, agent="srv-exec")

    # 2026-10-19：改价失败（含超时 / 复核不通过）→ 自动把同一张工单转本机重试。
    # 先写结果再兜底：即使兜底派单出错，原单的成败已经落库，不会变成"状态不明"。
    if not ok and safe_failover:
        try:
            _failover_to_local(con, cfg, job, (tail[-1] if tail else "执行失败"))
        except Exception as e:
            log("  ⚠ 转本机兜底异常（不影响本单结论）：%r" % e)

    if not ok and not safe_failover:
        log("  写入状态 %s：保留原工单 %s 待对账，不克隆或重放价格" % (write_state, jid))
        msg_alert.alert(con, "job-reconcile-" + jid, "改价结果待核（禁止重复执行）",
                        "原工单 %s 的写入状态为 %s；请按原ID核对已写行及回执，不新建重试单。" % (jid, write_state),
                        cooldown_s=1800)

    # 金币单：把容器现场读到的「采购成本现值」落 gold_state 表（与本机通道同一张表）。
    # 容器直接产出的是 p2pah_local 的原始结果，只有 jobs[].改前实际；本机 worker 会把它
    # 包成「成本回执」再回传，服务器执行器没有那一步 —— 这里按同一口径现构造。
    try:
        hz = (res or {}).get("成本回执") if isinstance(res, dict) else None
        if not hz and isinstance(res, dict):
            _hz = {}
            for _j in (res.get("jobs") or []):
                if isinstance(_j, dict) and _j.get("key") and _j.get("改前实际") is not None:
                    # 2026-10-26 修：被判「人工改价」/ 未真正写入的行**不得**把目标值记成现值。
                    #   原 bug：整单 ok=True 就把每行的「新」写成 gold_state.cost ⇒ 记账被
                    #   污染成目标值（0.38205），下一轮幂等闸与执行端人工闸都拿它当基线，
                    #   于是「现值 0.45 ≠ 记账 0.38205」永远成立 ⇒ 永冻 + 反复重登记保护。
                    _wrote = not _j.get("人工改价")
                    _hz[_j["key"]] = {"现行": _j.get("改前实际"),
                                      "目标": (_j.get("新") if _wrote else None),
                                      "行ID": _j.get("row_id")}
            hz = _hz or None
        if hz and kind == "writegold":
            n = S.gold_state_upsert(con, hz, ok=ok, src="%s/srv-exec" % jid)
            log("  gold_state 落库 %d 个服务区的现行采购成本（src=%s/srv-exec）" % (n, jid))
        elif kind == "writegold":
            log("  本单无成本回执（可能全部已等值跳过），gold_state 不动")
    except Exception as e:
        log("  gold_state 落库失败（不影响本单）：%r" % e)

    # 2026-10-23（裁定 D）：本单里被判「人工改价」而跳过的区 → 登记保护，
    # 让 app.py 在 IGGM 变价前不要再派单（否则每轮重复出单、每轮都被跳）。
    try:
        _nman = _record_gold_manual(con, res, jid) if kind == "writegold" else 0
        if _nman:
            log("  人工改价保护登记 %d 个服务区（IGGM 变价前不再派单）" % _nman)
    except Exception as e:
        log("  ⚠ 人工改价保护登记失败（不影响本单）：%r" % e)

    if ok:
        ST["done"] += 1
    else:
        ST["failed"] += 1
    ST.update({
        "state": "idle", "job": None, "kind": None,
        "last_result": {
            "job": jid, "kind": kind, "ok": bool(ok), "sec": sec,
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "rc": rc,
            "why": ("" if ok else (tail[-1] if tail else "执行失败")),
            "clearcache_ok": (res or {}).get("clearcache_ok") if isinstance(res, dict) else None,
            "publication_status": (res or {}).get("publication_status"),
            "write_state": write_state,
        },
    })
    log("  %s 工单 %s：%s（%.1fs）"
        % ("✅" if ok else "✘", jid, "成功" if ok else "失败", sec))

    # 2026-10-22：后台价已写成功、但主后台「一键清理所有」失败 ⇒ 前台仍是旧价。
    # 这类问题不会让工单变红（后台价是对的），历史上因此静默烂了约 30 小时，
    # 所以单独发一条告警；同一信号 6 小时内只发一次，避免每个采集周期刷屏。
    try:
        _cc_want = isinstance(res, dict) and bool(res.get("clearcache_wanted"))
        _cc_ok = isinstance(res, dict) and res.get("clearcache_ok")
        if ok and _cc_want and _cc_ok is False:
            msg_alert.alert(
                con, "clearcache-fail",
                "前端缓存未刷新（后台价已改成功）",
                "工单 %s：后台价格已写入，但 admin.p2pah.cn「缓存管理 → 一键清理所有」失败，"
                "前台可能仍在展示旧价。\n\n"
                "常见原因：batoken 过期且账号密码自动重登失败（凭据失效 / 验证码识别错）。\n"
                "处置：在 play187 上跑（必须带 --network 与 FS_ADMIN_SESSION_URL，"
                "清缓存鉴权走 fs27 全局会话 8767）\n"
                "`docker run --rm --network fc27-cloud-net "
                "-e FS_ADMIN_SESSION_URL=http://fc27-p2pah-session:8767 "
                "-v /opt/d4follow/_p2pah_srv:/srv -w /srv "
                "p2pah-srv:1 python /srv/admin_cache_local.py clear`" % jid,
                cooldown_s=6 * 3600)
    except Exception as e:                                  # noqa: BLE001
        log("  ⚠ 清缓存告警发送异常（不影响本单）：%r" % e)

    return True


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    # 单实例锁（被 systemd 重复拉起 / 手工起第二次时兜住）
    lf = open(LOCK, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("已有另一个执行器实例在跑（%s 被占），本进程退出" % LOCK)
        return 1

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    ST["started"] = dt.datetime.now().isoformat(timespec="seconds")
    ST["state"] = "idle"
    flush_state()
    log("服务器执行器启动 ｜ pid=%s ｜ 镜像=%s ｜ 轮询=%ss" % (os.getpid(), IMAGE, POLL_S))
    log("  工单目录 %s ｜ 配置快照 %s ｜ 状态文件 %s" % (JOBS, CFG_SNAP, STATE))

    while not STOP:
        busy = False
        try:
            busy = run_once()
        except Exception as e:
            ST["state"] = "error"
            ST["note"] = repr(e)[:300]
            log("循环异常：%r" % e)
        flush_state()
        # 2026-10-23（裁定 D 配套）：空转时每 RECON_EVERY_MIN 分钟做一次只读对账。
        #   只在**明确空闲**时跑：容器串行，绝不与写价单抢 chromium profile。
        if not busy and not STOP:
            try:
                if _recon_due():
                    _c2 = S.connect(DATA)
                    try:
                        _rok = _recon_readgold(_c2, read_cfg())
                    finally:
                        try:
                            _c2.close()
                        except Exception:
                            pass
                    _recon_mark(bool(_rok))
            except Exception as e:
                log("  ⚠ 对账异常（不影响派单）：%r" % e)
        # 有单就立刻接着跑下一张；空转按轮询间隔睡
        time.sleep(1 if busy else POLL_S)

    ST["state"] = "stopped"
    ST["note"] = "已按信号退出"
    flush_state()
    log("服务器执行器退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
