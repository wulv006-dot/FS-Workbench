# -*- coding: utf-8 -*-
"""新建 / 维护 #📰｜news 资讯频道。

做四件事：
  1. 找到或新建资讯频道（默认建在频道列表第 2 位，紧跟 👋｜welcome）
  2. 把它设成只读：@everyone 能看能翻历史，不能发消息 / 加表情
  3. 发一条置顶的频道说明（重复运行会自动替换旧的）
  4. 回填最近 N 条官方帖（公告 / 补丁说明 / 官方影像），并把已读状态写进 news_state.json

用法：
  python 09_news_setup.py                     # dry-run，只打印将要做什么
  python 09_news_setup.py --yes               # 执行
  python 09_news_setup.py --yes --backfill 10 # 回填条数
  python 09_news_setup.py --yes --rename "📰｜资讯"
  python 09_news_setup.py --yes --no-backfill # 只建频道，不回填

⚠️ 跑之前先把机器人停掉（同一 token 同时连两个实例会互相顶）：
     systemctl stop shugo-bot
  跑完再 systemctl start shugo-bot
"""
import asyncio
import json
import os
import sys

import discord

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import news  # noqa: E402

CFG_PATH = os.path.join(HERE, "config.json")
CFG = json.loads(open(CFG_PATH, encoding="utf-8").read())

GUILD = int(CFG["guild_id"])
NAME = "📰｜news"
TOPIC = ("Official AION 2 news, auto-posted by Shugo-bot — announcements, patch notes "
         "and media straight from aion2.plaync.com")
HEADER_MARK = "auto-posted from aion2.plaync.com"   # 用来识别本 bot 之前发的说明卡

DRY = "--yes" not in sys.argv
BACKFILL = int(CFG.get("news_backfill", 10) or 10)
BOARDS = CFG.get("news_boards") or news.DEFAULT_BOARDS
POSITION = 1

if "--backfill" in sys.argv:
    BACKFILL = int(sys.argv[sys.argv.index("--backfill") + 1])
if "--no-backfill" in sys.argv:
    BACKFILL = 0
if "--rename" in sys.argv:
    NAME = sys.argv[sys.argv.index("--rename") + 1]
if "--channel" in sys.argv:
    CFG["news_channel_id"] = sys.argv[sys.argv.index("--channel") + 1]


def env_token():
    t = os.environ.get("SHUGO_TOKEN", "").strip()
    if t:
        return t
    p = os.path.join(HERE, "token.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""


TOKEN = env_token()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    try:
        await run()
    except Exception:
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


def overwrites(g):
    return {
        g.default_role: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True,
            send_messages=False, add_reactions=False,
            create_public_threads=False, send_messages_in_threads=False,
        ),
        g.me: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, attach_files=True, manage_messages=True,
            manage_channels=True, pin_messages=True,
        ),
    }


async def run():
    g = client.get_guild(GUILD)
    if g is None:
        print("!! 找不到 guild", GUILD)
        return
    print("guild     : %s (%s)  成员 %s" % (g.name, g.id, g.member_count))
    print("dry_run   : %s" % DRY)
    print("backfill  : %s 条   板块: %s" % (BACKFILL, ", ".join(BOARDS)))
    print()

    # ---- 1. 找 / 建频道 ----
    ch = g.get_channel(int(CFG.get("news_channel_id") or 0))
    if ch is None:
        ch = discord.utils.get(g.text_channels, name=NAME)

    if ch is None:
        print("[1] 新建频道 #%s  (position=%s)" % (NAME, POSITION))
        if not DRY:
            ch = await g.create_text_channel(
                NAME, position=POSITION, topic=TOPIC,
                overwrites=overwrites(g), reason="AION 2 official news feed",
            )
            print("    -> 建好了  id=%s" % ch.id)
    else:
        print("[1] 复用已有频道 #%s  (id=%s, position=%s)" % (ch.name, ch.id, ch.position))

    if ch is None:
        print("    (dry-run 到此为止)")
        return

    # ---- 2. 权限 + 主题 ----
    print("\n[2] 设只读权限 + topic")
    print("    @everyone : view=Y  history=Y  send=N  react=N")
    print("    @Shugo-bot: send=Y  embed=Y  manage=Y")
    if not DRY:
        await ch.edit(name=NAME, topic=TOPIC, overwrites=overwrites(g),
                      reason="news channel: read-only")
        print("    -> OK")

    # ---- 3. 置顶说明卡 ----
    print("\n[3] 发 / 刷新置顶说明卡")
    if not DRY:
        async for m in ch.history(limit=50):
            if m.author.id == client.user.id and m.embeds and \
                    (m.embeds[0].footer.text or "").find(HEADER_MARK) >= 0:
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
        e = discord.Embed(
            color=discord.Color(0x60A5FA),
            title="📰  AION 2 Official News",
            description=("This channel is fed automatically by **Shugo-bot**, straight from the\n"
                         "official AION 2 site. No need to refresh the forum — new posts land here.\n\n"
                         "**📢 Announcements** — maintenance, outages, service notices\n"
                         "**🛠️ Patch Notes** — weekly update & balance changes\n"
                         "**🎬 Media** — official trailers and videos\n\n"
                         "🔎 Full archive → [aion2.plaync.com/en-us/board/notice]"
                         "(https://aion2.plaync.com/en-us/board/notice/list)\n"
                         "💰 Kinah for sale → [aion2kinah.com](https://www.aion2kinah.com/)"),
        )
        e.set_footer(text="🔒 Read-only  ·  auto-posted from aion2.plaync.com")
        msg = await ch.send(embed=e)
        try:
            await msg.pin(reason="news channel header")
        except discord.HTTPException:
            pass
        print("    -> message_id=%s (已置顶)" % msg.id)

    # ---- 4. 抓取 + 回填 ----
    print("\n[4] 抓取官方板块 …")
    items, errs = await asyncio.to_thread(news.fetch_all, BOARDS, 10)
    for e_ in errs:
        print("    !! 抓取失败", e_)
    print("    共取到 %d 条（去重后）" % len(items))

    if BACKFILL > 0:
        pick = items[:BACKFILL][::-1]        # 旧的先发
        print("    回填最近 %d 条（从旧到新）：" % len(pick))
        for it in pick:
            print("      - [%s] %s" % (it["tag"], it["title"][:66]))
        if not DRY:
            for i, it in enumerate(pick, 1):
                try:
                    await news.post_item(ch, it)
                    print("      %d/%d 已发 %s" % (i, len(pick), it["title"][:50]))
                except discord.HTTPException as ex:
                    print("      !! 发送失败: %r" % ex)
                await asyncio.sleep(1.2)

    # ---- 5. 写已读状态 + config ----
    print("\n[5] 写状态与配置")
    if not DRY:
        st = news.State(os.path.join(HERE, "news_state.json"))
        st.mark(*[i["id"] for i in items])
        st.save(initialized=True)
        print("    news_state.json: 认领 %d 条已读" % len(items))

        CFG["news_channel_id"] = str(ch.id)
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(CFG, f, ensure_ascii=False, indent=2)
        print("    config.json: news_channel_id = %s" % ch.id)
    else:
        print("    (dry-run 不写文件)")

    print("\n完成。执行时请记得：跑完 setup 再 systemctl start shugo-bot。")


if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: 没有 token（环境变量 SHUGO_TOKEN 或同目录 token.txt）")
        sys.exit(1)
    client.run(TOKEN, log_handler=None)
