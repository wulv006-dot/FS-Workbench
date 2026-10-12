# -*- coding: utf-8 -*-
"""执行器端到端验证（真实网络，打线上）。

覆盖：
  A) Cookie 会话登录：错误密码 -> 明确失败；正确密码 -> 拿到 Cookie
  B) 心跳 + 认领 + 进度 + 回传 全链路
  C) 会话过期后的自动重登

凭据来源：环境变量 MLB_TEST_USER / MLB_TEST_PASSWORD。
没给凭据时只跑「错误密码」与「未认证」两组负向用例，不产生误锁。
"""
import os
import sys
import time
import json
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client"))
from mlb_agent import Hub  # noqa: E402

SITE = os.environ.get("MLB_TEST_SERVER", "https://47.85.224.112")
USER = os.environ.get("MLB_TEST_USER", "")
PWD = os.environ.get("MLB_TEST_PASSWORD", "")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  -- " + detail) if detail else ""))


def t1_error_password_gives_clear_reason():
    """错误密码必须明确报「账号或密码不对」，而不是 JSON 解析错误。"""
    if not USER:
        check("1.1 错误密码报错清晰（跳过：无测试账号）", True, "skipped")
        return
    h = Hub(SITE, USER, "definitely-not-the-password", timeout=30)
    ok = h.login()
    check("1.1 错误密码应登录失败", ok is False)
    # 确认不是拿到 200 就当成功
    check("1.2 失败时不持有 Cookie", not h.cookie)


def t2_unauthenticated_is_detected():
    """无凭据访问 API，必须被识别为「认证没过」而不是崩溃/静默。"""
    h = Hub(SITE, "", "", timeout=30)
    try:
        h.heartbeat("t-noauth", "test")
        check("2.1 无凭据访问应报错", False, "居然成功了")
    except RuntimeError as e:
        msg = str(e)
        check("2.1 无凭据访问被拦截且提示可读",
              ("重定向" in msg or "认证" in msg or "HTTP" in msg),
              msg[:110])
    except Exception as e:
        check("2.1 无凭据访问被拦截且提示可读", False, "%s: %s" % (type(e).__name__, e))


def t3_login_and_heartbeat():
    """正向：登录 -> 心跳 -> 认领。"""
    if not (USER and PWD):
        check("3.x 正向链路（跳过：未提供 MLB_TEST_PASSWORD）", True, "skipped")
        return
    h = Hub(SITE, USER, PWD, timeout=30, log=lambda m: print("      |", m))
    ok = h.login()
    check("3.1 正确凭据登录成功", ok)
    if not ok:
        return
    check("3.2 Cookie 已保存", bool(h.cookie))

    agent = "e2e-auto-%d" % int(time.time())
    try:
        hb = h.heartbeat(agent, "mlb-agent/1.1-e2e", "端到端验证")
        check("3.3 心跳返回 ok", bool(hb and hb.get("ok")), str(hb)[:90])
    except Exception as e:
        check("3.3 心跳返回 ok", False, "%s" % e)
        return

    try:
        r = h.claim(agent)
        task = (r or {}).get("task")
        check("3.4 认领接口可用", r is not None,
              ("领到任务 %s" % task["id"]) if task else "当前无待处理任务（也算通过）")
    except Exception as e:
        check("3.4 认领接口可用", False, "%s" % e)

    try:
        cfg = h.agent_config()
        check("3.5 配置接口可用", isinstance(cfg, dict) and "markup" in cfg, str(cfg)[:90])
    except Exception as e:
        check("3.5 配置接口可用", False, "%s" % e)


def t4_session_recovery():
    """会话失效后应能自动重登，而不是直接死掉。"""
    if not (USER and PWD):
        check("4.x 会话自愈（跳过：未提供 MLB_TEST_PASSWORD）", True, "skipped")
        return
    h = Hub(SITE, USER, PWD, timeout=30)
    h.login()
    h.cookie = "MMOEXP_AUTH=invalid.token.value"   # 故意弄坏
    try:
        info = h.heartbeat("e2e-recover", "mlb-agent/1.1-e2e", "会话自愈验证")
        check("4.1 会话失效后自动重登并成功", bool(info and info.get("ok")))
    except Exception as e:
        check("4.1 会话失效后自动重登并成功", False, "%s" % e)


if __name__ == "__main__":
    print("=" * 62)
    print("MLB 执行器端到端验证   目标站点：%s" % SITE)
    print("凭据：%s" % ("已提供" if (USER and PWD) else "未提供（只跑负向）"))
    print("=" * 62)
    t1_error_password_gives_clear_reason()
    t2_unauthenticated_is_detected()
    t3_login_and_heartbeat()
    t4_session_recovery()

    print("-" * 62)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("结果：%d/%d 通过" % (passed, total))
    for n, ok, d in results:
        if not ok:
            print("  未通过：%s  %s" % (n, d))
    sys.exit(0 if passed == total else 1)
