# -*- coding: utf-8 -*-
"""钉钉机器人推送（AION2 金币价监控专用）。

零第三方依赖：只用标准库 urllib / hmac / hashlib / base64 / json。

用法：
    from dingtalk_push import DingTalkBot, send_aion2_report
    bot = DingTalkBot.from_env()          # 读 DINGTALK_WEBHOOK / DINGTALK_SECRET
    bot.send_markdown("标题", markdown_text)

安全设置三选一（钉钉后台「机器人 → 安全设置」）：
    1. 自定义加签（推荐）→ 需要 SECRET，本模块自动算 sign
    2. 关键词→ 消息里必须含该词，本模块在正文里带 `关键词` 占位，由钉钉侧匹配
    3. IP 白名单 → 什么都不用配，但换机器要改
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 服务器上 /usr/bin/python3 的 ssl 不可用，必须显式给一个 context（见技能分册 05）
_SSL_CTX = ssl.create_default_context()


class DingTalkError(Exception):
    pass


class DingTalkBot:
    """钉钉自定义机器人。

    必填：webhook
    选填：secret（自定义加签时必填）
    """

    def __init__(self, webhook: str = "", secret: str = "", timeout: int = 20):
        # ⛔ 不要在这里校验/抛错：`from_env()` 在「凭据还没配」时必须能正常返回一个
        #   未配置实例，让调用方用 `bot.configured` 判断并跳过 —— 否则定时器首轮就崩。
        #   真正发消息时（send）才校验，避免把地址打错这类错误拖到很晚才暴露。
        self.webhook = (webhook or "").strip()
        self.secret = (secret or "").strip()
        self.timeout = int(timeout)
        # 命中的签名策略（None = 尚未试出）；成功后记住，避免每条消息都重试 4 遍
        self._ok_mode = None

    # ------------------------------------------------------------------ 构造
    @classmethod
    def from_env(cls, prefix: str = "DINGTALK") -> "DingTalkBot":
        """从环境变量读凭据。

        密钥文件查找顺序（都存在时后者覆盖前者）：
          1. `<prefix>_ENV_FILE` 环境变量指向的文件
          2. 与本文件同目录的 `dingtalk.env`（推荐：不用往 systemd 里塞明文）
        文件格式：每行 `KEY=VALUE`，`#` 开头为注释。
        """
        vals = {}
        candidates = []
        if os.environ.get(prefix + "_ENV_FILE"):
            candidates.append(os.environ[prefix + "_ENV_FILE"])
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "dingtalk.env"))
        for path in candidates:
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            vals[k.strip()] = v.strip()
                except Exception as e:           # noqa: BLE001
                    # 不要静默 continue —— 凭据读不到时必须留痕，
                    # 否则表现为「configured: False」这种查不到原因的静默失败。
                    print("[钉钉] 读取 %s 失败：%r" % (path, e))
                    continue
        for k in ("WEBHOOK", "SECRET"):
            envk = "%s_%s" % (prefix, k)
            if os.environ.get(envk):
                vals[envk] = os.environ[envk]
        # ⚠ 键名必须与 dingtalk.env 里的**完整键名**一致（`DINGTALK_WEBHOOK`），
        #   不能只取 `vals["WEBHOOK"]` —— 那样永远取不到值，且因为被 except 吞掉
        #   表现为「configured: False」这种毫无线索的静默失败（踩过）。
        #   两种写法都兜住：`DINGTALK_WEBHOOK` 与裸 `WEBHOOK`。
        return cls(vals.get("%s_WEBHOOK" % prefix) or vals.get("WEBHOOK", ""),
                   vals.get("%s_SECRET" % prefix) or vals.get("SECRET", ""))

    @property
    def configured(self) -> bool:
        return bool(self.webhook)

    # ------------------------------------------------------------------ 签名
    # 签名策略表：钉钉「先encode / 不encode」「SECRET 带不带 SEC 前缀」四种组合。
    # 官方文档只明确了一种，但不同版本/资料口径不一，且失败时钉钉只回笼统的
    # 310000，**无法从报错区分是算法问题还是密钥问题** ⇒ 逐个试，一次跑清楚。
    _SIGN_MODES = ("官方：先URL-encode再HMAC",
                   "变体：不encode 直接HMAC",
                   "变体：去SEC前缀 + 先encode",
                   "变体：去SEC前缀 + 不encode")

    def _signed_url(self, mode: int = 0, ts: str = "") -> str:
        """自定义加签：返回带 timestamp/sign 的完整 URL。

        `mode` =签名策略（见`_sign_variants`）。默认走官方文档口径（mode 0）。

        钉钉文档口径：
          1. stringToSign = timestamp + "\\n" + secret
          2. 对 stringToSign 做 **URL-encode**
          3. sign = Base64( HMAC-SHA256( key=secret, msg=stringToSign ) )，再 URL-encode
          4. timestamp 用**毫秒**；与钉钉服务器时差须<= 1 小时，否则同样报 310000。

        ⚠ 为什么有多个策略：第 2 步「是否先encode」在不同资料/版本里说法不一致，
          而两种实现算出的 sign 完全不同（secret 里的 `SEC` 前缀与换行符都会被转义）。
          只按一种实现硬发，失败时报的都是笼统的 310000「签名不匹配」，
          **无法区分是算法错还是密钥错**。故这里内置多种策略逐个试，
          命中后记住（`self._ok_mode`），后续直接复用，不重复试错。
        """
        if not self.secret:
            return self.webhook
        ts = ts or str(int(time.time() * 1000))
        digest = self._sign_digest(ts, mode)
        sign = urllib.parse.quote_plus(base64.b64encode(digest))
        sep = "&" if ("?" in self.webhook) else "?"
        return "%s%stimestamp=%s&sign=%s" % (self.webhook, sep, ts, sign)

    def _sign_digest(self, ts: str, mode: int) -> bytes:
        """按策略算 HMAC 摘要。mode 见 `_SIGN_MODES`。"""
        raw = "%s\n%s" % (ts, self.secret)
        enc = urllib.parse.quote_plus(raw)
        secret_b = self.secret.encode("utf-8")
        if mode == 0:      # 官方：先URL-encode 再 HMAC
            msg = enc
        elif mode == 1:    # 变体：直接对原始字符串 HMAC
            msg = raw
        elif mode == 2:    # 变体：secret 去掉 SEC 前缀 + 先encode
            msg = urllib.parse.quote_plus("%s\n%s" % (ts, self.secret[3:]))
        else:              # 变体：secret 去掉 SEC 前缀 + 不encode
            msg = "%s\n%s" % (ts, self.secret[3:])
        return hmac.new(secret_b, msg.encode("utf-8"), digestmod=hashlib.sha256).digest()

    # ------------------------------------------------------------------ 发送
    def send(self, payload: dict) -> dict:
        """POST 已构造好的消息体。返回钉钉的 JSON 响应。

        签名策略回退：首次成功会自动记住命中的策略（`_ok_mode`），
        之后直接用它；只有在报 310000 时才换下一个策略重试。
        """
        if not self.webhook:
            raise DingTalkError("webhook 未配置")
        if "oapi.dingtalk.com" not in self.webhook:
            # 挡住「贴错地址 / 复制到别的机器人」这类低级错，给出可读的提示
            raise DingTalkError("webhook 域名不对，应为 oapi.dingtalk.com/robot/send")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        modes = ([self._ok_mode] if self._ok_mode is not None
                 else list(range(len(self._SIGN_MODES))))
        last = None
        for mode in modes:
            url = self._signed_url(mode=mode)
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json; charset=utf-8",
                         "User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout,
                                            context=_SSL_CTX) as r:
                    raw = r.read().decode("utf-8", "replace")
                try:
                    data = json.loads(raw)
                except Exception:                   # noqa: BLE001
                    raise DingTalkError("钉钉返回非 JSON（多半是网关拦截）：%s" % raw[:200])
                if data.get("errcode") == 0:
                    self._ok_mode = mode          # 记住命中的策略
                    return data
                errmsg = str(data.get("errmsg") or "")
                if "310000" in errmsg or "签名" in errmsg:
                    last = DingTalkError(
                        "钉钉拒绝：签名不匹配（已试 %d 种签名策略都不通过）"
                        "——多半是 dingtalk.env 里的 SECRET 与该 webhook 不是同一个机器人，"
                        "请到钉钉后台重新复制该机器人的密钥" % len(modes))
                    continue                        # 换下一个策略
                raise DingTalkError("钉钉拒绝：errcode=%s errmsg=%s"
                                    % (data.get("errcode"), errmsg))
            except DingTalkError as e:
                if "310000" not in str(e) and "签名" not in str(e):
                    raise
                last = e
            except Exception as e:                  # noqa: BLE001
                last = e
                time.sleep(1.5)
        raise last or DingTalkError("发送失败")

    def send_text(self, content: str, at_mobiles: str = "") -> dict:
        return self.send({"msgtype": "text", "text": {"content": content},
                          "at": {"atMobiles": at_mobiles, "isAtAll": False}})

    def send_markdown(self, title: str, markdown: str, at_mobiles: str = "") -> dict:
        return self.send({
            "msgtype": "markdown",
            "markdown": {"title": title, "text": markdown},
            "at": {"atMobiles": at_mobiles, "isAtAll": False},
        })


# ============================================================ AION2 报告渲染

REGION_ORDER = ["NA East", "NA West", "EU", "South America"]
REGION_CN = {"NA East": "北美东", "NA West": "北美西",
             "EU": "欧洲", "South America": "南美"}


def _fmt(v, nd=4):
    return "—" if v is None else ("%.*f" % (nd, v))


def _arrow(cur, prev, tol=0.0005):
    """涨跌箭头。tol 内视作持平。"""
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if abs(d) <= tol:
        return " 持平"
    return " ↑%.4f" % d if d > 0 else " ↓%.4f" % (-d)


def _short(name: str) -> str:
    """`NA East · Siel - Elyos（天族）` → `Siel-Elyos(天)`，让表格窄一点。"""
    s = str(name or "")
    if " · " in s:
        s = s.split(" · ", 1)[1]
    s = s.replace(" - ", "-").replace("（", "(").replace("）", ")")
    s = s.replace("Elyos", "E").replace("Asmodian", "A")
    s = s.replace("(天族)", "(天)").replace("(魔族)", "(魔)")
    return s.strip()


def _margin(base, our):
    """毛利率 = (我方 − 基准) / 我方。这是「我方价里有多少是溢价」的占比。

    ⚠ 2026-10-06 起**报表不再展示毛利率**（它随竞品基准剧烈波动，
    基准走兜底或被污染时会出现 -385870% 这种荒谬值）。
    函数保留：Excel 链路与调试仍可能用到。
    """
    if base in (None, 0) or our in (None, 0):
        return None
    return (our - base) / our


def _rate(v):
    """把 config 里的「利润率」归一成**小数**（0.2 → 0.2；20 → 0.2；"20%" → 0.2）。

    容错：后台有人填 `20` 或 `20%` 时不应显示成 2000%。
    """
    if v is None or v == "":
        return None
    if isinstance(v, str):
        s = v.strip().rstrip("%")
        try:
            f = float(s)
        except ValueError:
            return None
        return f / 100.0 if f > 1.0 else f
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 100.0 if f > 1.0 else f


def render_aion2_markdown(cur_rows, prev_rows, round_no=0, total_rounds=4) -> str:
    """渲染 AION2 金币价 Markdown 报告 —— **全量小服明细**。

    2026-10-03 用户要求：「每个小服务器的价格，不要大区均价」⇒
    改成**每个服务区一行**，大区只作为分组标题 + 一行小计（不再拿均价代替明细）。

    同日用户反馈 Excel 链接形式不好用，要求换回 Markdown 明细表，
    并**去掉「基准价」「较上轮」两列**。

    ⛔⛔ 2026-10-06 用户再要求：**去掉「毛利率」，改用「利润率」**。
    两者完全不同，别混：
      · 毛利率 = (我方 − 竞品基准)/我方 —— **现算**，随竞品基准剧烈波动
        （基准走兜底或被污染时曾出现 -385870%），不是业务指标。
      · 利润率 = **改价系统看板**（`/api/gold_cost`）给的真实盈亏
        = (售价 − DD373 进货成本) / 售价，**可以为负**（亏就是亏）。
        ⚠ 不是 config 里的 `服务区.利润率`（那是**目标**值，恒 0.2）。
    ⇒ 本表展示**看板利润率**。基准只作为三源参考出现。

    cur_rows / prev_rows: [{key, 大区, 名称, 基准, 我方价, 利润率,
                            看板售价, 看板成本, G2G, ELD, IGGM, 兜底}]

    列：服务区 | 我方 | 利润率 | 三源明细
    ⚠ 钉钉 markdown 表格列数不宜过多（窄屏会横向滚动），故三源压成一列。
    """
    lines = []
    lines.append("## AION2 金币价 · 全量小服明细（第 %d 轮）" % round_no)
    lines.append("")
    lines.append("> 利润率来自改价系统看板 = (售价 − DD373 成本) / 售价，可为负；"
                 "单价 $/M。")
    lines.append("")

    groups = {}
    for r in cur_rows:
        groups.setdefault(r.get("大区") or "-", []).append(r)

    # 大区按「配置里出现次数」降序，让大区多的排在前面
    order = sorted(groups, key=lambda k: (-len(groups[k]), k))
    n_loss = [0]          # 负利润率（真亏损）行数，用列表以便内层函数累加
    for reg in order:
        rows = groups[reg]
        # 组内按服务区名排序，输出稳定（否则每轮顺序跳动，难比对）
        rows = sorted(rows, key=lambda z: str(z.get("名称") or z.get("key") or ""))
        ours = [r["我方价"] for r in rows if r.get("我方价") is not None]
        avg_o = sum(ours) / len(ours) if ours else None
        # 大区利润率均值（仅对**有配置**的区求均值，配置缺失的不参与）
        rates = [_rate(r.get("利润率")) for r in rows]
        rates = [v for v in rates if v is not None]
        avg_r = sum(rates) / len(rates) if rates else None

        lines.append("### %s（%s）· %d 个小服" % (reg, REGION_CN.get(reg, ""), len(rows)))
        lines.append("")
        lines.append("| 服务区 | 我方 | 利润率 | 三源（G2G/ELD/IGGM） |")
        lines.append("| --- | --- | --- | --- |")
        for r in rows:
            rv = _rate(r.get("利润率"))
            srcs = "%s / %s / %s" % (_fmt(r.get("G2G"), 3), _fmt(r.get("ELD"), 3),
                                     _fmt(r.get("IGGM"), 3))
            if r.get("兜底"):
                srcs += " · %s" % r["兜底"]
            # ⚠ 看板口径：利润率为负 = 真亏损，**必须原样显示**并标记，不淡化、不截断
            if rv is None:
                cell = "—"
            elif rv < 0:
                n_loss[0] += 1
                cell = "**%.1f%%** ⚠亏" % (rv * 100)
            else:
                cell = "%.1f%%" % (rv * 100)
            lines.append("| %s | %s | %s | %s |" % (
                _short(r.get("名称") or r.get("key")),
                _fmt(r.get("我方价")), cell, srcs))
        # 小计行：给出大区层面的参考，但**不替代**上面的明细
        lines.append("| **小计 / 均值** | **%s** | **%s** | %d 个小服 |" % (
            _fmt(avg_o),
            ("%.1f%%" % (avg_r * 100)) if avg_r is not None else "—", len(rows)))
        lines.append("")

    # 全局速览：一行看清整体
    all_o = [r["我方价"] for r in cur_rows if r.get("我方价") not in (None, 0)]
    g_o = sum(all_o) / len(all_o) if all_o else None
    all_r = [_rate(r.get("利润率")) for r in cur_rows]
    all_r = [v for v in all_r if v is not None]
    g_r = sum(all_r) / len(all_r) if all_r else None
    lines.append("---")
    lines.append("")
    lines.append("**全局**：%d 个小服 · 我方均价 %s · 平均利润率 %s%s" % (
        len(cur_rows), _fmt(g_o),
        ("%.1f%%" % (g_r * 100)) if g_r is not None else "—",
        " ·⚠ 亏损 %d 个" % n_loss[0] if n_loss[0] else ""))
    lines.append("")
    lines.append("- 利润率取自改价系统看板（售价 − DD373 成本）/ 售价，可为负")
    lines.append("- 数据源：G2G / ELD / IGGM 三源 + 我方前台价（mmoexp）")
    lines.append("- 每 15 分钟采集，每 %d 轮（约 1 小时）推送一次" % total_rounds)
    lines.append("- 竞品源低于同区中位价 1/3 会自动剔除、同一问题只告警一次；货源不足的区不判定")
    return "\n".join(lines)



def send_aion2_report(bot, cur_rows, prev_rows, round_no=1, total_rounds=4,
                      at_mobiles=""):
    """渲染并推送。返回钉钉响应 dict。"""
    md = render_aion2_markdown(cur_rows, prev_rows, round_no, total_rounds)
    return bot.send_markdown("AION2 金币实时价", md, at_mobiles=at_mobiles)


if __name__ == "__main__":
    b = DingTalkBot.from_env()
    if not b.configured:
        print("[钉钉] 未配置 webhook。设置 DINGTALK_WEBHOOK / DINGTALK_SECRET 或 "
              "DINGTALK_ENV_FILE 指向的密钥文件。")
        raise SystemExit(2)
    b.send_text("AION2 金币监控机器人已连通 ✅")
    print("[钉钉] 连通测试已发送")
