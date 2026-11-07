# -*- coding: utf-8 -*-
"""在 📋│community-rules 发布英文守则（幂等：有记录就原位更新）。

硬约束：**全英文，禁止任何中文字符**。发布前用 CJK 正则断言，命中就直接退出，
不把中文发到频道里（这是用户明确要求，不是可选项）。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, "_local_secrets_DO_NOT_COMMIT", "wowforever_token.txt"),
             encoding="utf-8").read().strip()
API = "https://discord.com/api/v10"
CH = "1567714666891976817"      # 📋│community-rules
STATE = os.path.join(HERE, "_rules_state.json")
GOLD = 0xC69B3F
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")

DESC = (
    "This is a **World of Warcraft: Forever** trading and community server.\n"
    "The short version: **be decent, trade in the right channel, don't scam.**\n"
    "Everything below is that sentence with details."
)

RULES = [
    ("1 · Respect everyone",
     "No harassment, hate speech, slurs, or NSFW content. Disagree about prices without "
     "attacking the person. Zero tolerance for racism and threats."),
    ("2 · Trade in 💱│the-exchange only",
     "All buy / sell / price talk belongs there. Do not advertise in other channels and "
     "**do not DM members to sell**. Unsolicited sales DMs = warning, then ban."),
    ("3 · Never impersonate",
     "Do not use staff names, the MMOEXP brand, or another site's brand in your nickname. "
     "Impersonation is removed automatically — no warning, no appeal."),
    ("4 · No competitor advertising",
     "Links, names, or invitations to other gold shops, boosting services, or Discord "
     "servers are removed. That includes referral and affiliate links."),
    ("5 · No spam",
     "No mass mentions, no repeated copy-paste, no walls of emoji. One post per topic — "
     "edit it instead of bumping."),
    ("6 · Scams are an instant ban",
     "Fake proof, chargeback threats, phishing links, and \"pay me first off-site\" all "
     "result in a permanent ban on first offence."),
    ("7 · Use your language channel",
     "🇬🇧 English · 🇫🇷 French · 🇩🇪 German · 🇪🇸 Spanish · 🇵🇹 Portuguese · "
     "🇰🇷 Korean · 🇯🇵 Japanese · 🇨🇳 Chinese (Traditional). "
     "English is the default everywhere else."),
    ("8 · Orders go through support",
     "Open a ticket in 🎫│support instead of DMing staff or traders. Orders and payments "
     "only happen on the official site — **never** by DM transfer."),
    ("9 · Verified proof only",
     "When you vouch for a trade, include a screenshot of the order. Unverifiable claims "
     "may be removed."),
    ("10 · Staff decisions are final",
     "We may mute, kick, or ban without prior notice. To appeal, open a ticket — do not "
     "argue in public channels."),
]

payload = {
    "embeds": [{
        "title": "WOW FOREVER · Community Rules",
        "description": DESC,
        "color": GOLD,
        "fields": [{"name": n, "value": v, "inline": False} for n, v in RULES],
        "footer": {"text": "Breaking a rule may result in mute, kick, or ban — "
                           "with or without notice."},
    }],
    "allowed_mentions": {"parse": []},
    "components": [],
}


def api(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bot " + TOKEN,
        "User-Agent": "DiscordBot (mmoexp-ops, 1.0)",
        **({"Content-Type": "application/json"} if data else {})})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception as e:                                # noqa: BLE001
            if i == 2:
                return -1, repr(e)
            time.sleep(2)


# ---- 发布前硬校验：整份 payload 不许出现任何 CJK 字符 ----
blob = json.dumps(payload, ensure_ascii=False)
hits = CJK.findall(blob)
if hits:
    print("!! 断言失败：守则内容含 %d 个中文字符 %r —— 拒绝发布" % (len(hits), set(hits)))
    raise SystemExit(2)
print("断言通过：payload 中文字符 = 0")

state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}
mid = state.get("rules_msg")
if mid:
    st, body = api("/channels/%s/messages/%s" % (CH, mid), "PATCH", payload)
    if st == 200:
        print("守则已原位更新 message_id=%s" % mid)
    else:
        print("更新失败 %s（多半是原消息已被删），改为重新发布" % st)
        mid = None

if not mid:
    st, body = api("/channels/%s/messages" % CH, "POST", payload)
    if st not in (200, 201):
        print("发布失败", st, body)
        raise SystemExit(1)
    mid = body["id"]
    json.dump({"rules_msg": mid}, open(STATE, "w", encoding="utf-8"))
    print("守则已发布 message_id=%s" % mid)
    api("/channels/%s/pins/%s" % (CH, mid), "PUT")
    time.sleep(1)
    st, msgs = api("/channels/%s/messages?limit=20" % CH)
    if st == 200 and isinstance(msgs, list):
        for m in msgs:
            if m["type"] == 6:
                api("/channels/%s/messages/%s" % (CH, m["id"]), "DELETE")
                print("已删除置顶系统提示", m["id"])

# ---- 读回验证 ----
st, msgs = api("/channels/%s/messages?limit=20" % CH)
if st == 200:
    print("\n频道消息 %d 条" % len(msgs))
    for m in msgs:
        raw = json.dumps(m.get("embeds") or [], ensure_ascii=False)
        print("  %s type=%s embeds=%d 中文字符=%d"
              % (m["id"], m["type"], len(m.get("embeds") or []), len(CJK.findall(raw))))
