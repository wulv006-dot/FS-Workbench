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

    cmd = [DOCKER, "run", "--rm",
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
    ok = (rc == 0) and (res or {}).get("ok") is not False
    if res is None:
        res = {"ok": rc == 0, "returncode": rc, "sec": sec}

    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-160:]
    S.local_job_finish(con, jid, ok=ok, log="\n".join(tail), result=res, agent="srv-exec")

    # 2026-10-19：改价失败（含超时 / 复核不通过）→ 自动把同一张工单转本机重试。
    # 先写结果再兜底：即使兜底派单出错，原单的成败已经落库，不会变成"状态不明"。
    if not ok:
        try:
            _failover_to_local(con, cfg, job, (tail[-1] if tail else "执行失败"))
        except Exception as e:
            log("  ⚠ 转本机兜底异常（不影响本单结论）：%r" % e)

    # 金币单：把容器现场读到的「采购成本现值」落 gold_state 表（与本机通道同一张表）。
    # 容器直接产出的是 p2pah_local 的原始结果，只有 jobs[].改前实际；本机 worker 会把它
    # 包成「成本回执」再回传，服务器执行器没有那一步 —— 这里按同一口径现构造。
    try:
        hz = (res or {}).get("成本回执") if isinstance(res, dict) else None
        if not hz and isinstance(res, dict):
            _hz = {}
            for _j in (res.get("jobs") or []):
                if isinstance(_j, dict) and _j.get("key") and _j.get("改前实际") is not None:
                    _hz[_j["key"]] = {"现行": _j.get("改前实际"),
                                      "目标": _j.get("新"),
                                      "行ID": _j.get("row_id")}
            hz = _hz or None
        if hz and kind == "writegold":
            n = S.gold_state_upsert(con, hz, ok=ok, src="%s/srv-exec" % jid)
            log("  gold_state 落库 %d 个服务区的现行采购成本（src=%s/srv-exec）" % (n, jid))
        elif kind == "writegold":
            log("  本单无成本回执（可能全部已等值跳过），gold_state 不动")
    except Exception as e:
        log("  gold_state 落库失败（不影响本单）：%r" % e)

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
        },
    })
    log("  %s 工单 %s：%s（%.1fs）"
        % ("✅" if ok else "✘", jid, "成功" if ok else "失败", sec))
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
        # 有单就立刻接着跑下一张；空转按轮询间隔睡
        time.sleep(1 if busy else POLL_S)

    ST["state"] = "stopped"
    ST["note"] = "已按信号退出"
    flush_state()
    log("服务器执行器退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
