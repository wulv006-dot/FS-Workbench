# -*- coding: utf-8 -*-
"""
一次性部署：把频道设成「只读」+ 清掉 Carl-bot 的旧欢迎语 + 发布 Shugo-bot 菜单卡片。

用法:
  set SHUGO_TOKEN=xxx
  python setup.py --channel bot-test              # 只设只读 + 发卡片
  python setup.py --channel bot-test --purge      # 额外清掉 Carl-bot 的历史欢迎语
  python setup.py --channel bot-test --dry-run    # 只看将要做什么，不执行
"""
import argparse, asyncio, json, os, sys
from pathlib import Path
import discord

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
TOKEN = os.environ.get("SHUGO_TOKEN", "").strip()

CARL_ID = 235148962103951360
G = CFG["guild_id"]

CHANNEL_ALIAS = {
    "bot-test": "1557641711067467816",
    "get-roles": "1557683163122114630",
    "hub": "1555494315311239240",
}

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

from bot import Panel  # 复用同一套按钮/下拉组件


@client.event
async def on_ready():
    try:
        await run()
    except Exception as e:
        import traceback; traceback.print_exc()
    finally:
        await client.close()


async def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="bot-test")
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args, _ = ap.parse_known_args()

    g = client.get_guild(int(G))
    cid = CHANNEL_ALIAS.get(args.channel, args.channel)
    ch = g.get_channel(int(cid))
    print(f"guild = {g.name}   channel = #{ch.name} ({ch.id})   dry_run={args.dry_run}")

    # ---- 0. 诊断：owner 权限 / bot 位置 ----
    owner = g.get_member(g.owner_id)
    print("\n[0] 管理员诊断")
    print("   bot top_role:", g.me.top_role.name, "pos=", g.me.top_role.position,
          "| admin =", g.me.guild_permissions.administrator)
    if owner:
        print("   owner:", owner, "| roles:", [r.name for r in owner.roles if not r.is_default()],
              "| admin =", owner.guild_permissions.administrator,
              "| can see this ch =", ch.permissions_for(owner).view_channel)
    # 身份组层级检查
    need = [f["role_id"] for f in CFG["faction_roles"]] + [c["role_id"] for c in CFG["class_roles"]]
    bad = [r.name for r in [g.get_role(int(x)) for x in need]
           if r and r.position >= g.me.top_role.position]
    print("   role hierarchy check:", "OK (bot is above all assignable roles)" if not bad
          else f"!!! PROBLEM: {bad} 高于或等于 bot 最高身份组")

    # ---- 1. 频道设成只读 ----
    print("\n[1] 把 @everyone 设成只读")
    before = ch.overwrites_for(g.default_role)
    print("   before: view=%s send=%s history=%s react=%s" % (
        before.view_channel, before.send_messages, before.read_message_history, before.add_reactions))
    if not args.dry_run:
        await ch.set_permissions(
            g.default_role,
            view_channel=True,
            read_message_history=True,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            send_messages_in_threads=False,
            attach_files=False,
            embed_links=False,
        )
        after = ch.overwrites_for(g.default_role)
        print("   after : view=%s send=%s history=%s react=%s" % (
            after.view_channel, after.send_messages, after.read_message_history, after.add_reactions))

    # ---- 2. 清掉 Carl-bot 的旧欢迎语 ----
    if args.purge:
        print("\n[2] 清理 Carl-bot 的旧欢迎语")
        targets = []
        async for m in ch.history(limit=500):
            if m.author.id == CARL_ID and m.content.startswith("Hello,") and "welcome to" in m.content:
                targets.append(m)
        print(f"   找到 {len(targets)} 条")
        if not args.dry_run:
            for m in targets:
                try:
                    await m.delete()
                    print("   deleted:", m.content[:60])
                except discord.HTTPException as e:
                    print("   skip:", e)
        print("   完成")

    # ---- 3. 发布菜单卡片 ----
    print("\n[3] 发布菜单卡片")
    if args.dry_run:
        print("   (dry-run, skipped)")
    else:
        # 先清掉本 bot 之前发的卡片，避免重复
        async for m in ch.history(limit=50):
            if m.author.id == client.user.id and m.components:
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
        t = CFG["texts"]
        emb = discord.Embed(color=discord.Color.from_str("#60a5fa"),
                            title=t["card_title"], description=t["card_body"])
        emb.set_footer(text=t["card_footer"])
        msg = await ch.send(embed=emb, view=Panel())
        print(f"   ✅ 卡片已发布: https://discord.com/channels/{G}/{ch.id}/{msg.id}")
        print(f"   message_id = {msg.id}")


if __name__ == "__main__":
    if not TOKEN:
        print("ERROR: set SHUGO_TOKEN"); sys.exit(1)
    client.run(TOKEN, log_handler=None)
