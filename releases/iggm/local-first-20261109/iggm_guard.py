#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
IGGM 本机兜底守护（2026-10-21）

用途
----
服务器出口被 IGGM 的 Cloudflare 拦（403）时，服务器自己抓不到价。
本机（住宅 IP）能抓到，所以由本机代抓并推给服务器。

本脚本实现「服务器失败 → 自动启用本机」这一兜底策略：
  · 每 N 分钟（计划任务）跑一次 --once
  · 先问服务器：IGGM 空轮计数 n、本机上次推送多久了
  · 满足条件才真跑抓取（避免无谓消耗），否则立刻退出
  · 服务器恢复正常抓取（n 归零）时完全不动作

判定条件（全部满足才抓）
------------------------
  1. 服务器 IGGM 空轮计数 n >= --min-streak （默认 2）
  2. 本机物品推送距今 > --min-gap 分钟（默认 25）
  3. 金币推送距今 > --min-gap 分钟（或者干脆一起抓，物品+金币同一轮的）
  4. 没有另一份守护正在跑（锁文件）

用法
----
  python iggm_guard.py --once      # 给计划任务用，检查一次，需要才抓
  python iggm_guard.py --force     # 不管条件，立刻抓一轮并推送
  python iggm_guard.py --check     # 只打印判定结果，不抓（排查用）
"""
import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# 2026-10-23 修「每 10 分钟弹窗」：本脚本由计划任务用 pythonw 起，本身没控制台；
# 但它 spawn 的 ssh / scp / taskkill 都是控制台程序 ⇒ 系统会给每个子进程新开一个控制台，
# Win11 默认交给 Windows Terminal 显示，于是弹出一个标题为
# `C:\WINDOWS\System32\OpenSSH\ssh.exe` 的黑窗口，干扰前台工作。
# 统一加 CREATE_NO_WINDOW（0x08000000），子进程完全无窗口。
NO_WIN = 0x08000000 if os.name == "nt" else 0
LOG_DIR = os.path.join(HERE, "logs")
LOCK = os.path.join(HERE, ".guard.lock")
PIDFILE = os.path.join(HERE, ".guard.pid")
GUARD_LOG = os.path.join(LOG_DIR, "guard.log")

SSH_KEY = r"C:\Users\yi\.ssh\fs_admin"
SSH_HOST = "root@47.85.170.62"

# 服务器上一次问清楚所有状态，避免多次 ssh
REMOTE_PROBE = r"""
import json,datetime as dt,os
base='/opt/d4follow/data'
def rd(p):
    try: return json.load(open(p,encoding='utf-8'))
    except Exception: return {}
def age(p):
    try:
        d=rd(os.path.join(base,p))
        t=d.get('pushed_at') or d.get('ts')
        if not t: return -1
        t=dt.datetime.strptime(str(t).replace('T',' ')[:19],'%Y-%m-%d %H:%M:%S')
        return int((dt.datetime.now()-t).total_seconds())
    except Exception:
        return -1
st=rd(os.path.join(base,'iggm_empty_streak.json'))
def _mode():
    try:
        c=json.load(open('/opt/d4follow/config.json',encoding='utf-8'))
        return str(((c.get('iggm') or {}).get('抓取来源')) or 'auto').strip().lower()
    except Exception:
        return 'auto'
print(json.dumps({
  'empty_n': int(st.get('n') or 0),
  'last_fail': st.get('last_fail') or '',
  'item_age_s': age('iggm_local_push.json'),
  'gold_age_s': age('iggm_gold_push.json'),
  'ig_mode': _mode(),
  'srv_now': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
}))
"""


def log(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = "[%s] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(GUARD_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ssh(cmd, timeout=60):
    p = subprocess.run(
        ["ssh", "-o", "UserKnownHostsFile=C:/Users/yi/.ssh/known_hosts_rpg183",
         "-o", "KexAlgorithms=curve25519-sha256", "-o", "ConnectTimeout=15",
         "-i", SSH_KEY, SSH_HOST, cmd],
        capture_output=True, timeout=timeout, creationflags=NO_WIN,
    )
    out = p.stdout.decode("utf-8", "replace")
    # 去掉新版 openssh 的 post-quantum 提示
    lines = [l for l in out.splitlines()
             if "post-quantum" not in l and "store now" not in l
             and "may need to be upgraded" not in l and "openssh.com/pq" not in l]
    return "\n".join(lines).strip(), p.returncode


def probe():
    """问服务器：空轮计数 + 本机两条推送的年龄。失败返回 None。"""
    remote = "cd /opt/d4follow && venv/bin/python -c %s" % shquote(REMOTE_PROBE)
    out, rc = ssh(remote)
    if rc != 0 or not out:
        return None
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def acquire_lock():
    if os.path.exists(LOCK):
        try:
            age = time.time() - os.path.getmtime(LOCK)
        except OSError:
            age = 999999
        if age < 20 * 60:          # 20 分钟内视为还在跑
            return False
        log("发现过期锁（%.0f 分钟前），忽略" % (age / 60))
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def run_step(title, script, timeout=1800):
    """script 允许带参数（如 "iggm_local_collect.py --push"）。

    2026-10-21 修：原来是 os.path.join(HERE, script)，把 "--push" 一起拼进了文件名
    ⇒ 子进程报 `can't open file '...iggm_local_collect.py --push'`，物品侧从没抓成功过。
    同时给子进程注入 UTF-8：pythonw 下 stdout 是管道，默认走 GBK，
    脚本里的 ✔/✘ 会抛 UnicodeEncodeError（金币侧 10:14 起全挂就是它）。
    """
    log("▶ %s" % title)
    t0 = time.time()
    parts = shlex.split(script)
    cmd = [PY, os.path.join(HERE, parts[0])] + parts[1:]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run(cmd, cwd=HERE, capture_output=True, timeout=timeout, env=env,
                       creationflags=NO_WIN)
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    tail = "\n".join([l for l in (out + "\n" + err).splitlines() if l.strip()][-6:])
    log("  耗时 %.0fs rc=%s" % (time.time() - t0, p.returncode))
    if tail:
        log("  " + tail.replace("\n", "\n  "))
    return p.returncode == 0


def do_run(need_gold=True, need_item=True):
    """金币慢不了（约 40 秒，直接决定能否出单），物品较慢（约 5~6 分钟）。
    两者独立判定、独立跑，避免「只缺金币」却把物品也重抓一遍。"""
    ok = True
    if need_gold:
        # 2026-10-22 老板要求「IGGM 也要能看价」⇒ 金币侧显式点名补上 AION2 的 86 个区。
        #   iggm_gold_local.py 默认只抓 PRICING_GAMES（参与定价的 3 个游戏）；AION2 走
        #   DD373 定价、IGGM 仅作展示参照，故**不改 PRICING_GAMES**，只在这里传 --games。
        #   --gap 0.6：86 个区连击会触发 Cloudflare，限速后每轮约 +50s，可接受。
        ok = run_step("抓 IGGM 金币行情 → 推送",
                      'iggm_gold_local.py --gap 0.6 --games '
                      '"ARC Raiders,MapleStory Classic World,暗黑破坏神4" --host root@47.85.170.62') and ok
    if need_item:
        ok = run_step("抓 IGGM 物品行情 → 推送", "iggm_local_collect.py --push") and ok
    if not (need_gold or need_item):
        log("（无需要抓取的项）")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="检查一次，需要才抓（计划任务用）")
    ap.add_argument("--loop", action="store_true", help="常驻：每 N 分钟检查一次（默认 10）")
    ap.add_argument("--interval", type=int, default=10, help="--loop 的检查间隔分钟数")
    ap.add_argument("--stop", action="store_true", help="停掉常驻守护")
    ap.add_argument("--force", action="store_true", help="无条件立刻抓一轮")
    ap.add_argument("--check", action="store_true", help="只打印判定，不抓")
    ap.add_argument("--min-streak", type=int, default=2, help="空轮达到几次才接管（默认 2）")
    ap.add_argument("--gold-gap", type=int, default=40, help="金币侧推送间隔分钟（默认 40）")
    ap.add_argument("--item-gap", type=int, default=60, help="物品侧推送间隔分钟（默认 60）")
    a = ap.parse_args()

    if a.stop:
        return stop_loop()
    if a.loop:
        return run_loop(a)
    return tick(a)


def run_loop(a):
    """常驻模式：每 interval 分钟跑一次判定。"""
    try:
        with open(PIDFILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    log("═" * 60)
    log("守护启动 pid=%d，每 %d 分钟检查一次（服务器被拦才接管）" % (os.getpid(), a.interval))
    try:
        while True:
            try:
                tick(a)
            except Exception:
                import traceback
                log("✗ 本轮异常：%s" % traceback.format_exc()[-400:])
            # 分片 sleep，便于 --stop 及时生效
            for _ in range(a.interval * 60):
                if not os.path.exists(PIDFILE):
                    log("检测到停止标记，退出")
                    return 0
                time.sleep(1)
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


def stop_loop():
    if not os.path.exists(PIDFILE):
        log("守护未在运行（无 pid 文件）")
        return 0
    try:
        pid = int(open(PIDFILE, encoding="utf-8").read().strip())
    except Exception:
        pid = 0
    if pid:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=20, creationflags=NO_WIN)
            log("已停止守护 pid=%d" % pid)
        except Exception as e:
            log("停止失败：%s" % e)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    return 0


def tick(a):
    st = probe()
    if not st:
        log("✗ 连不上服务器，无法判定；本轮放弃（继续等下一轮）")
        return 2

    n = st["empty_n"]
    item_age = st["item_age_s"]
    gold_age = st["gold_age_s"]
    mode = str(st.get("ig_mode") or "auto").lower()
    imin = lambda s: "从未" if s < 0 else "%.0f 分钟前" % (s / 60.0)
    log("服务器 %s | IGGM 空轮=%d | 取价来源=%s | 物品推送=%s | 金币推送=%s"
        % (st["srv_now"], n, mode, imin(item_age), imin(gold_age)))

    # 2026-10-29：本机抓不抓，现在由服务器的「IGGM 取价来源」说了算。
    #   server    → 老板明确只用服务器，本机一律不抓（省资源、不白打 CF）
    #   auto/local/alternate → 本机是主力/备份，按间隔照抓，**不再等服务器空轮**
    #   （原来是「服务器连续 2 轮 0 条才接管」，等于永远不主动抓；
    #     老板要的是「电脑开着就优先本机」，所以改成按模式无条件参与。）
    if mode == "server":
        log("→ 取价来源=仅服务器 ⇒ 本机不抓（要本机抓请在控制台切到 自动/仅本机/交替）")
        return 0
    _local_active = mode in ("auto", "local", "alternate")

    if a.force:
        need_item = need_gold = True
        need = True
        reason = "手动 --force"
    elif a.check:
        need_item = need_gold = need = False
        reason = "仅检查"
    else:
        # 金币快（~40s）、物品慢（~5min），两者各有自己的间隔，互不拖累
        need_item = ((_local_active or n >= a.min_streak)
                     and (item_age < 0 or item_age > a.item_gap * 60))
        need_gold = ((_local_active or n >= a.min_streak)
                     and (gold_age < 0 or gold_age > a.gold_gap * 60))
        need = need_item or need_gold
        if not need:
            if not _local_active and n < a.min_streak:
                reason = "服务器抓取正常（空轮 %d < %d），无需接管" % (n, a.min_streak)
            else:
                reason = ("取价来源=%s，但两条都在新鲜期内（物品 %s / 金币 %s），不重复抓"
                          % (mode, imin(item_age), imin(gold_age)))
        else:
            todo = []
            if need_gold:
                todo.append("金币")
            if need_item:
                todo.append("物品")
            reason = "服务器连续 %d 轮抓不到 → 本机接管（%s）" % (n, "+".join(todo))

    log("判定：%s → %s" % ("需要抓取" if need else "不动作", reason))

    if a.check or not need:
        return 0

    if not acquire_lock():
        log("已有另一份守护在跑，跳过")
        return 0
    try:
        ok = do_run(need_gold=need_gold, need_item=need_item)
        return 0 if ok else 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
