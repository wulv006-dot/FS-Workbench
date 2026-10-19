# -*- coding: utf-8 -*-
"""统一告警出口（钉钉）—— 2026-10-19 新增

为什么单独一个模块
------------------
采集侧（app.py，跑在 gunicorn 里）和执行侧（srv_exec.py，常驻进程）都要能告警。
两边各写一套「读凭据 / 拼 markdown / 记冷却」必然漂移，出问题还查不到原因。

  · 凭据：统一交给 `dingtalk_push.DingTalkBot.from_env()`（先读环境变量，再读
    与本文件同目录的 `dingtalk.env`）。d4follow 的 systemd 单元**没有**
    EnvironmentFile，所以按文件读是最省事也最不容易坏的方式。
  · 冷却：落 sqlite `alert_state(sig,last_ts,last_detail)`（store.py 已有该表）。
    进程重启、gunicorn 重载都不会重复轰炸；同一 sig 默认 6 小时只发一条。

用法
----
    import msg_alert
    msg_alert.alert(con, "iggm-empty", "IGGM 连续 3 轮 0 条", "正文…",
                    cooldown_s=6 * 3600)

返回：True = 确实发出去了；False = 冷却中 / 未配置 / 发送失败（都会打日志留痕）。
⚠ 本模块**永不抛异常**：告警不能把业务链路带崩。
"""
import datetime as dt

PREFIX = "[告警]"


def _log(msg):
    print("%s %s %s" % (PREFIX, dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg),
          flush=True)


def _bot():
    """拿到已配置的钉钉机器人；未配置返回 None。"""
    try:
        import dingtalk_push as dp
        b = dp.DingTalkBot.from_env()
        return b if b.configured else None
    except Exception as e:                                  # noqa: BLE001
        _log("初始化钉钉失败：%r" % (e,))
        return None


def _recent(con, sig):
    try:
        r = con.execute("SELECT last_ts FROM alert_state WHERE sig=?", (sig,)).fetchone()
        return (r[0] if r else None)
    except Exception:
        return None


def _mark(con, sig, detail):
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        con.execute("INSERT OR REPLACE INTO alert_state(sig,last_ts,last_detail)"
                    " VALUES(?,?,?)", (sig, now, str(detail)[:500]))
        con.commit()
    except Exception as e:                                  # noqa: BLE001
        _log("写 alert_state 失败（不影响发送）：%r" % (e,))


def alert(con, sig, title, text, cooldown_s=6 * 3600, force=False):
    """发一条钉钉告警（带冷却）。绝不抛异常。

    sig        —— 告警指纹（同一件事用同一个 sig，才能正确去重）
    cooldown_s —— 冷却秒数；0 = 每次必发
    force      —— 无视冷却
    """
    now = dt.datetime.now()
    if not force and cooldown_s > 0:
        last = _recent(con, sig)
        if last:
            try:
                last_dt = dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%S")
                age = (now - last_dt).total_seconds()
                if age < cooldown_s:
                    _log("冷却中，跳过 %s（上次 %s，%d 分钟前，冷却 %.1f 小时）"
                         % (sig, last, age // 60, cooldown_s / 3600.0))
                    return False
            except Exception:
                pass                      # 时间格式不认识就当冷却过期
    bot = _bot()
    if bot is None:
        _log("钉钉未配置（DINGTALK_WEBHOOK 缺失）→ 只写日志：%s | %s" % (title, text))
        _mark(con, sig, "未配置：%s" % title)
        return False
    try:
        md = "### %s\n\n%s" % (title, text)
        bot.send_markdown(title, md)
        _log("已推送：%s" % title)
        _mark(con, sig, title)
        return True
    except Exception as e:                                  # noqa: BLE001
        _log("推送失败：%r（标题 %s）" % (e, title))
        _mark(con, sig, "发送失败：%r" % (e,))
        return False
