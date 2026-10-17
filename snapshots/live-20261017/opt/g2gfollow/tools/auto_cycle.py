# -*- coding: utf-8 -*-
"""G2G 金币货架（AION2 Kinah）· 自动轮（2026-10-13 起 30 分钟一轮）。

一轮 = 采集（DD373 成本 + G2G 货架）→ 按「最小变动百分比」自动放行 → 真实写入。
走的是与本机看板按钮**完全同一条 HTTP 链路**（127.0.0.1:8903 的
/api/collect、/api/release_all、/api/execute），不复制、不绕过任何定价逻辑。

为什么不把定时器写进 app.py
---------------------------
app.py 是 gunicorn 单 worker，采集进度是进程内全局状态 JOB；在进程内再开调度线程
会和人工点按钮抢 JOB。放到 systemd 定时器里，天然「一轮没跑完不会叠下一轮」，
app.py 一行调度逻辑都不用改。

铁律仍在
--------
① 采集只出 dry-run 建议单；② 真写必须 confirm=true。
本脚本就是那个「自动替老板按 confirm 的手」，所以额外加了三道安全闸（见下）。

安全闸（任何一条不过 ⇒ 本轮不写入，只记日志）
--------------------------------------------
  A. 新鲜度：采集后 /api/state 的 plan_at 必须 ≥ 本轮开始时间（防止采集失败后
     拿着**上一轮的旧建议单**去执行 —— 那会把过期价写进前台）。
  B. 货源健康度：闸门价区数 > config `自动.闸门价区上限`（默认 20）⇒ 判定为
     「DD373 采集中断/大面积无货」，本轮停手（否则会把几十个区一把推到 $19.9）。
  C. 无成本数据区数 > `自动.无成本数据上限`（默认 15）⇒ 同上停手。
  D. 变动阈值：|目标价−现价| ÷ 现价 < `自动.最小变动百分比` 的行不放行，避免
     每轮把 74 个区无意义地重写一遍。

关掉自动
--------
  systemctl disable --now g2gfollow-auto.timer        # 关定时器
  改 config `自动.启用` = false                        # 关脚本（定时器留着也不动价）
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CFG_PATH = os.path.join(ROOT, "config.json")
LOG_PATH = os.path.join(ROOT, "logs", "auto_cycle.log")
LOG_MAX = 2 * 1024 * 1024

CFG = json.load(io.open(CFG_PATH, encoding="utf-8"))
BASE = "http://127.0.0.1:%d" % int(CFG["运行"]["端口"])


# ─────────────────────────── 日志 ───────────────────────────

def _rotate():
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX:
            bak = LOG_PATH + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(LOG_PATH, bak)
    except OSError:
        pass


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    sys.stdout.flush()
    try:
        _rotate()
        with io.open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ─────────────────────────── HTTP ───────────────────────────

def api(path, method="GET", body=None, timeout=120):
    """打本机 8903。返回解析后的 JSON；HTTP 错误抛 RuntimeError（带响应体）。"""
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %d %s %s -> %s" % (e.code, method, path, raw[:300]))
    except Exception as e:                          # noqa: BLE001
        raise RuntimeError("%s %s 失败：%r" % (method, path, e))


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    auto = CFG.get("自动") or {}
    if not auto.get("启用", False):
        log("自动轮未启用（config `自动.启用` = false）—— 直接退出，不动任何价")
        return 0

    op = auto.get("操作人") or "auto-15min"
    min_pct = float(auto.get("最小变动百分比", 0.5)) / 100.0
    gate_max = int(auto.get("闸门价区上限", 20))
    nocost_max = int(auto.get("无成本数据上限", 15))

    t0 = time.time()
    log("=== 自动轮开始（阈值 %.2f%% · 闸门价区上限 %d · 无成本上限 %d）==="
        % (min_pct * 100, gate_max, nocost_max))

    # 0. 探活
    try:
        h = api("/api/health")
    except RuntimeError as e:
        log("× 服务不可达：%s" % e)
        return 2
    log("服务在（%s · port %s）" % (h.get("service"), h.get("port")))

    # 1. 采集
    try:
        api("/api/collect", "POST", {})
    except RuntimeError as e:
        log("× 触发采集失败：%s" % e)
        return 2
    log("采集已启动，等它跑完 …")
    deadline = t0 + 900
    st = {}
    while True:
        time.sleep(5)
        try:
            st = api("/api/job")
        except RuntimeError as e:
            log("  轮询 /api/job 出错（继续等）：%s" % e)
            st = {"running": True}
        if not st.get("running"):
            break
        if time.time() > deadline:
            log("× 采集 15 分钟还没跑完 —— 本轮放弃")
            return 2
    if st.get("ok") is False:
        log("× 采集失败（phase=%s）—— 本轮不改价，保持现状" % st.get("phase"))
        return 3
    s = st.get("summary") or {}
    log("采集完成：%s" % json.dumps(s, ensure_ascii=False))

    # 2. 新鲜度 + 健康度（安全闸 A/B/C）
    try:
        state = api("/api/state")
    except RuntimeError as e:
        log("× 读 /api/state 失败：%s" % e)
        return 2
    plan_at = state.get("plan_at") or 0
    if plan_at < t0 - 5:
        log("× 安全闸 A 触发：建议单时间戳 %s 早于本轮开始（疑采集没落盘）—— 不改价"
            % time.strftime("%H:%M:%S", time.localtime(plan_at)) if plan_at else "无")
        return 4
    sum2 = state.get("summary") or {}
    gate_n = int(sum2.get("闸门价区数") or 0)
    nocost_n = int(sum2.get("无成本数据") or 0)
    if gate_n > gate_max:
        log("× 安全闸 B 触发：闸门价区数 %d > %d（疑 DD373 采集中断/大面积无货）—— 不改价"
            % (gate_n, gate_max))
        return 5
    if nocost_n > nocost_max:
        log("× 安全闸 C 触发：无成本数据区数 %d > %d —— 不改价" % (nocost_n, nocost_max))
        return 5

    # 3. 按阈值自动放行（安全闸 D）
    try:
        r = api("/api/release_all", "POST", {"on": True, "min_pct": min_pct})
    except RuntimeError as e:
        log("× 自动放行失败：%s" % e)
        return 2
    changed = int(r.get("changed") or 0)
    log("自动放行：放行 %d 行 / 因变动不足跳过 %s 行（阈值 %.2f%%）"
        % (changed, r.get("skipped"), min_pct * 100))
    if not changed:
        log("本轮没有达到变动阈值的行 —— 不写入。=== 结束（%.0fs）===" % (time.time() - t0))
        return 0

    # 4. 真实写入
    try:
        w = api("/api/execute", "POST",
                {"dry": False, "confirm": True, "operator": op}, timeout=1800)
    except RuntimeError as e:
        log("× 写入失败：%s" % e)
        return 6
    total = int(w.get("total") or 0)
    verified = int(w.get("verified") or 0)
    log("写入完成：total=%d verified=%d readback_waited=%ss"
        % (total, verified, w.get("readback_waited")))
    if total and verified < total:
        log("⚠ 有 %d 条回读未通过（详见看板「写入流水」红标）" % (total - verified))
    log("=== 结束（%.0fs）===" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                          # noqa: BLE001
        import traceback
        log("× 未捕获异常：%r" % e)
        log(traceback.format_exc()[-1500:])
        sys.exit(9)
