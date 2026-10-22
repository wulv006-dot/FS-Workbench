#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MapleStory Classic World 上线版职业技能证据表（单一事实来源）。

用途：
1. tools/content_part2.py 的职业卡技能/被动/循环只从本表取"已核"条目；
2. tools/make_class_review.py 用它生成 CLASS-SKILLS-REVIEW.json（职业/技能/适用版本/资料/证据摘要/已核或未核）；
3. tools/verify.py 的回归检查用它判断"未核技能不得进入建议循环"。

证据等级：
- 官方（O*）：Nexon 官方公告/职业页。官方 10/21 上线说明确认 4 个一转 + 10 条二转、Lv100 上限；
  官方职业页对无 JS 客户端只返回空壳（3766 bytes，无职业/技能文本），本轮无法从官方页取得技能级细节。
- 社区数据（Q/W/M）：三个独立的 Classic World 数据站。技能名、层级、上限等级三者一致时记 verified；
  仅单站有记录时记 verified_single_source；三转（CoT2 早期测试）条目记 out_of_scope_3rd_job；
  在三个数据源中都找不到的旧稿技能名记 not_found。
"""
import datetime as dt

VERSION_LABEL = ("Classic World 公共上线版（2026-10-21 18:00 UTC 开服；Lv10 一转 / Lv30 二转 / "
                 "Lv100 上限；三转未在上线版开放）")

SOURCES = {
    "O1": {
        "id": "O1", "name": "Nexon Grand Launch Release Notes (46506)",
        "url": "https://www.nexon.com/maplestory/news/general/46506/grand-launch-release-notes",
        "kind": "official", "scope": "Classic World 上线说明",
        "note": "官方原文确认 10/21 18:00 UTC 开服、四职业、十条二转分支、Lv100 上限；不含技能级数据。"
                "容器内该域对无头/浏览器请求只返回空壳，正文由本轮 Codex 独立复核（REVIEW-5）。",
    },
    "O2": {
        "id": "O2", "name": "Nexon MapleStory Classic World · Classes & Jobs",
        "url": "https://www.nexon.com/maplestory/game/mscw/classes-and-jobs",
        "kind": "official", "scope": "Classic World 职业页",
        "note": "前端渲染页；本轮无头 GET 与浏览器均只得到空壳（无职业/技能文本），"
                "因此本轮不把任何技能级结论归因为官方页。职业名与分支以 O1 为准。",
    },
    "Q": {
        "id": "Q", "name": "MapleStory Quest（Classic World 客户端数据）",
        "url": "https://maplestory.quest/classes/spearman",
        "kind": "community-datamine", "scope": "Classic World Public Release 客户端数据",
        "note": "站点声明数据来自 Public Release 客户端（页面 dateModified 2026-10-21）；逐职业页按 1st/2nd job 分节，"
                "并标注 3rd job 仅存在于 Closed Online Test 2。职业总览 /classes 本轮间歇返回 500，逐职业页均为 200，本表以逐职业页为准。",
    },
    "W": {
        "id": "W", "name": "MapleClassic Wiki",
        "url": "https://mapleclassic.wiki/wiki/Skills",
        "kind": "community-wiki", "scope": "Classic World 技能总表",
        "note": "按 Job 分组的技能总表（Skill/Job/Tier/Max level/MP/Requires），"
                "Jobs 页明确 'There is no 3rd job advancement in Classic World yet'。",
    },
    "M": {
        "id": "M", "name": "NiaMeowDB（MapleStory Classic 数据库）",
        "url": "https://meowdb.com/msclassic/skills",
        "kind": "community-datamine", "scope": "Classic World 技能/职业数据",
        "note": "技能库声明 163 技能、'Third job is not part of the initial launch'，"
                "并注明 Orbis/El Nath/三转将在 rework 后到来（引用 Nexon 报告）。",
    },
}

# --------------------------------------------------------------------------- 职业
# tier: 1 = 一转, 2 = 二转
JOBS = [
    {"key": "beginner", "cn": "初学者", "en": "Beginner", "tier": 1,
     "adv": "Maple Island 起始职业，Lv10 可选择一转", "official": True},
    {"key": "warrior", "cn": "战士", "en": "Warrior", "tier": 1,
     "adv": "Perion / Dances with Balrog；Lv30 分化为 Fighter / Page / Spearman", "official": True},
    {"key": "fighter", "cn": "剑客", "en": "Fighter", "tier": 2,
     "adv": "Warrior 二转（剑/斧）", "official": True},
    {"key": "page", "cn": "准骑士", "en": "Page", "tier": 2,
     "adv": "Warrior 二转（剑/钝器）", "official": True},
    {"key": "spearman", "cn": "枪战士", "en": "Spearman", "tier": 2,
     "adv": "Warrior 二转（枪/戟）", "official": True},
    {"key": "magician", "cn": "法师", "en": "Magician", "tier": 1,
     "adv": "Ellinia / Grendel the Really Old；Lv30 分化为 F/P Wizard、I/L Wizard、Cleric", "official": True},
    {"key": "fp-wizard", "cn": "火毒法师", "en": "Wizard (Fire/Poison)", "tier": 2,
     "adv": "Magician 二转", "official": True},
    {"key": "il-wizard", "cn": "冰雷法师", "en": "Wizard (Ice/Lightning)", "tier": 2,
     "adv": "Magician 二转", "official": True},
    {"key": "cleric", "cn": "牧师", "en": "Cleric", "tier": 2,
     "adv": "Magician 二转", "official": True},
    {"key": "archer", "cn": "弓箭手", "en": "Bowman / Archer", "tier": 1,
     "adv": "Henesys / Athena Pierce；Lv30 分化为 Hunter / Crossbowman", "official": True},
    {"key": "hunter", "cn": "猎人", "en": "Hunter", "tier": 2,
     "adv": "Bowman 二转（弓）", "official": True},
    {"key": "crossbowman", "cn": "弩弓手", "en": "Crossbowman", "tier": 2,
     "adv": "Bowman 二转（弩）", "official": True},
    {"key": "thief", "cn": "飞侠", "en": "Thief / Rogue", "tier": 1,
     "adv": "Kerning City / Dark Lord；Lv30 分化为 Assassin / Bandit", "official": True},
    {"key": "assassin", "cn": "刺客", "en": "Assassin", "tier": 2,
     "adv": "Thief 二转（拳套投掷）", "official": True},
    {"key": "bandit", "cn": "侠客", "en": "Bandit", "tier": 2,
     "adv": "Thief 二转（匕首）", "official": True},
]

# --------------------------------------------------------------------------- 技能
# kind: active / buff / passive / passive_trigger
# ev: 一致记录该技能名 + 层级 + 上限等级的资料 id；status 由 ev 数量推导（见 STATUS_OVERRIDE）
def S(job, n, tier, kind, mx, eff, ev, status=None, note=None):
    return {"job": job, "n": n, "tier": tier, "kind": kind, "mx": mx,
            "eff": eff, "ev": ev, "status": status, "note": note}


SKILLS = [
    # ---- Beginner
    S("beginner", "Three Snails", 1, "active", 3, "投掷蜗牛壳，满级 40 伤害；初学者唯一主动攻击", ["Q", "W"]),
    S("beginner", "Recovery", 1, "buff", 3, "30 秒内回复 72 HP，冷却 2 分钟", ["Q", "W"]),
    S("beginner", "Nimble Feet", 1, "buff", 3, "30 秒内移速 +10，冷却 3 分钟", ["Q", "W"]),

    # ---- Warrior 1st
    S("warrior", "Power Strike", 1, "active", 20, "单体 260% 伤害", ["Q", "W"]),
    S("warrior", "Slash Blast", 1, "active", 20, "范围 130%，最多 6 只，需 Power Strike ≥1", ["Q", "W"]),
    S("warrior", "Improved HP Recovery", 1, "passive", 15, "每 10 秒回 HP，道具回血 +50%", ["Q", "W"]),
    S("warrior", "Max HP Increase", 1, "passive", 15, "最大 HP +25%，需 Improved HP Recovery Lv3", ["Q", "W"]),
    S("warrior", "Iron Body", 1, "buff", 20, "武器防御 +40%，600 秒", ["Q", "W"]),
    S("warrior", "Precise Strikes", 1, "passive", 15, "命中 +20、暴击率 +5%", ["Q", "W"]),

    # ---- Fighter
    S("fighter", "Sword Mastery", 2, "passive", 20, "剑熟练 + 命中（只对剑生效）", ["Q", "W"]),
    S("fighter", "Axe Mastery", 2, "passive", 20, "斧熟练；25% 概率造成 3 秒流血（只对斧生效）", ["Q", "W"]),
    S("fighter", "Final Attack: Sword", 2, "passive_trigger", 30, "攻击技能 25% 触发，对最多 3 只追加 200%，需 Sword Mastery Lv3", ["Q", "W"]),
    S("fighter", "Final Attack: Axe", 2, "passive_trigger", 30, "攻击技能 25% 触发，对最多 3 只追加 200%，需 Axe Mastery Lv3", ["Q", "W"]),
    S("fighter", "Sword Booster", 2, "buff", 20, "剑攻速 +2 阶段 300 秒，消耗 HP/MP，需 Sword Mastery Lv5", ["Q", "W"]),
    S("fighter", "Axe Booster", 2, "buff", 20, "斧攻速 +2 阶段 300 秒，消耗 HP/MP，需 Axe Mastery Lv5", ["Q", "W"]),
    S("fighter", "Rage", 2, "buff", 30, "队伍攻击 +40、武器防御 -40，300 秒", ["Q", "W"]),
    S("fighter", "Rush", 2, "active", 20, "向前冲 150，80% 伤害、击退最多 6 只，2 秒冷却", ["Q", "W"]),

    # ---- Page
    S("page", "Sword Mastery", 2, "passive", 20, "剑熟练 + 命中（只对剑生效）", ["Q", "W"]),
    S("page", "Blunt Weapon Mastery", 2, "passive", 20, "钝器熟练 + 暴击伤害 +20%（只对钝器生效）", ["Q", "W"]),
    S("page", "Final Attack: Sword", 2, "passive_trigger", 30, "攻击技能 25% 触发，追加 360%，需 Sword Mastery Lv3", ["Q", "W"]),
    S("page", "Final Attack: Blunt Weapon", 2, "passive_trigger", 30, "攻击技能 25% 触发，追加 360%，需 Blunt Weapon Mastery Lv3", ["Q", "W"]),
    S("page", "Sword Booster", 2, "buff", 20, "剑攻速 +2 阶段 300 秒，需 Sword Mastery Lv5", ["Q", "W"]),
    S("page", "Blunt Weapon Booster", 2, "buff", 20, "钝器攻速 +2 阶段 300 秒，需 Blunt Weapon Mastery Lv5", ["Q", "W"]),
    S("page", "Threaten", 2, "buff", 30, "最多 4 只怪 速度/攻击/防御 下降，30 秒", ["Q", "W", "M"]),
    S("page", "Rush", 2, "active", 20, "向前冲 150，80% 伤害、击退最多 6 只，2 秒冷却", ["Q", "W"]),

    # ---- Spearman
    S("spearman", "Spear Mastery", 2, "passive", 20, "枪熟练 + 附加效果（数据站对附加效果描述不一致，具体以游戏内为准）", ["Q", "W", "M"],
      note="三站对附加效果描述不一致（忽略敌防概率 / 回避加成），卡片只写通用定位，不写具体数值"),
    S("spearman", "Polearm Mastery", 2, "passive", 20, "戟熟练 + 移速（只对戟生效）", ["Q", "W"]),
    S("spearman", "Final Attack: Spear", 2, "passive_trigger", 30, "攻击技能 25% 触发，追加 350% 并吸收部分伤害为 HP，需 Spear Mastery Lv3", ["Q", "W", "M"]),
    S("spearman", "Final Attack: Polearm", 2, "passive_trigger", 30, "攻击技能 25% 触发，追加 350% 并吸收部分伤害为 HP，需 Polearm Mastery Lv3", ["Q", "W", "M"]),
    S("spearman", "Spear Booster", 2, "buff", 20, "枪攻速 +2 阶段 300 秒，需 Spear Mastery Lv5", ["Q", "W"]),
    S("spearman", "Polearm Booster", 2, "buff", 20, "戟攻速 +2 阶段 300 秒，需 Polearm Mastery Lv5", ["Q", "W"]),
    S("spearman", "Iron Will", 2, "buff", 30, "武器防御 +50、35% 概率忽略击退，300 秒（自身增益）", ["Q", "W", "M"]),
    S("spearman", "Rush", 2, "active", 20, "向前冲 150，80% 伤害、击退最多 6 只，2 秒冷却", ["Q", "W"]),

    # ---- Magician 1st
    S("magician", "Energy Bolt", 1, "active", 20, "单体基础攻击 130", ["Q", "W"]),
    S("magician", "Magic Claw", 1, "active", 20, "单次两段，基础攻击 65×2，需 Energy Bolt Lv1", ["Q", "W"]),
    S("magician", "Magic Guard", 1, "buff", 15, "把 80% 的 HP 伤害转为 MP 消耗", ["Q", "W"]),
    S("magician", "Magic Armor", 1, "buff", 20, "武器/魔法防御 +120，600 秒，需 Magic Guard Lv3", ["Q", "W"]),
    S("magician", "Improved MP Recovery", 1, "passive", 15, "每 10 秒回 1% 最大 MP，道具回蓝 +25%", ["Q", "W"]),
    S("magician", "Max MP Increase", 1, "passive", 15, "最大 MP +25%，需 Improved MP Recovery Lv3", ["Q", "W"]),

    # ---- F/P Wizard
    S("fp-wizard", "Fire Arrow", 2, "active", 30, "单体基础攻击 180，并附带持续伤害", ["Q", "W", "M"]),
    S("fp-wizard", "Poison Breath", 2, "active", 30, "基础攻击 80，75% 概率附加持续毒伤", ["Q", "W", "M"]),
    S("fp-wizard", "Meditation", 2, "buff", 20, "队伍魔法攻击 +25，300 秒，需 MP Eater Lv3", ["Q", "W"]),
    S("fp-wizard", "Teleport", 2, "active", 20, "瞬移 150 距离", ["Q", "W"]),
    S("fp-wizard", "Slow", 2, "buff", 20, "降低怪物速度与回避，需 Teleport Lv5", ["Q", "W"]),
    S("fp-wizard", "MP Eater", 2, "passive_trigger", 20, "每次攻击 50% 概率吸取怪物 50% 最大 MP", ["Q", "W"]),

    # ---- I/L Wizard
    S("il-wizard", "Cold Beam", 2, "active", 30, "单体基础攻击 170，命中后减速 3 秒", ["Q", "W", "M"]),
    S("il-wizard", "Thunder Bolt", 2, "active", 30, "群体基础攻击 70，25% 概率感电", ["Q", "W"]),
    S("il-wizard", "Meditation", 2, "buff", 20, "队伍魔法攻击 +25，300 秒，需 MP Eater Lv3", ["Q", "W"]),
    S("il-wizard", "Teleport", 2, "active", 20, "瞬移 150 距离", ["Q", "W"]),
    S("il-wizard", "Slow", 2, "buff", 20, "降低怪物速度与回避，需 Teleport Lv5", ["Q", "W"]),
    S("il-wizard", "MP Eater", 2, "passive_trigger", 20, "每次攻击 50% 概率吸取怪物 50% 最大 MP", ["Q", "W"]),

    # ---- Cleric
    S("cleric", "Heal", 2, "active", 30, "范围治疗队伍，周围不死系同时受到伤害", ["Q", "W", "M"]),
    S("cleric", "Holy Arrow", 2, "active", 30, "远程攻击，对不死/恶魔系特效", ["Q", "W"]),
    S("cleric", "Invincible", 2, "buff", 20, "物理伤害降低，并对接触伤害自己的怪物造成少量魔法伤害，需 Heal Lv5", ["Q", "W"]),
    S("cleric", "Bless", 2, "buff", 20, "队伍增益：命中/回避与道具-技能回血提升（两站描述不一致，具体以游戏内为准）", ["Q", "W"],
      note="两站描述不一致（一处为命中/回避/回血，一处为受伤 -15% 与 Heal 回血 +10%），卡片只写“队伍增益”，不写具体数值"),
    S("cleric", "MP Eater", 2, "passive_trigger", 20, "每次攻击 50% 概率吸取怪物 50% 最大 MP", ["Q", "W"]),
    S("cleric", "Teleport", 2, "active", 20, "瞬移 150 距离", ["Q", "W"]),

    # ---- Bowman 1st
    S("archer", "Arrow Blow", 1, "active", 20, "单体 240% 伤害", ["Q", "W"]),
    S("archer", "Double Shot", 1, "active", 20, "单次两段，120%×2，需 Arrow Blow Lv1", ["Q", "W"]),
    S("archer", "Power Knockback", 1, "active", 15, "180% 伤害并击退最多 4 只", ["Q", "W"]),
    S("archer", "Focus", 1, "buff", 20, "命中 +20、回避 +25，300 秒", ["Q", "W"]),
    S("archer", "Critical Shot", 1, "passive", 15, "暴击率 +20%、暴击伤害 +15%", ["Q", "W"]),
    S("archer", "The Eye of Amazon", 1, "passive", 15, "弓/弩射程 +120", ["Q", "W"]),

    # ---- Hunter
    S("hunter", "Bow Mastery", 2, "passive", 20, "弓熟练 + 暴击率 +10% + 移速 +10（只对弓生效）", ["Q", "W"]),
    S("hunter", "Final Attack: Bow", 2, "passive_trigger", 30, "攻击技能 25% 触发，对最多 3 只追加 120%，需 Bow Mastery Lv3", ["Q", "W"]),
    S("hunter", "Bow Booster", 2, "buff", 20, "弓攻速 +2 阶段 300 秒，需 Bow Mastery Lv5", ["Q", "W"]),
    S("hunter", "Soul Arrow: Bow", 2, "buff", 20, "300 秒内攻击不消耗箭矢，需 Bow Booster Lv5", ["Q", "W"]),
    S("hunter", "Arrow Bomb: Bow", 2, "active", 30, "130% 伤害，60% 概率眩晕 2 秒", ["Q", "W", "M"]),
    S("hunter", "Amazon's Judgement", 2, "passive", 20, "暴击时 100% 概率降低怪物速度 35", ["Q", "W", "M"]),

    # ---- Crossbowman
    S("crossbowman", "Crossbow Mastery", 2, "passive", 20, "弩熟练 + 暴击伤害 +20%（只对弩生效）", ["Q", "W"]),
    S("crossbowman", "Final Attack: Crossbow", 2, "passive_trigger", 30, "攻击技能 25% 触发，追加 360%，需 Crossbow Mastery Lv3", ["Q", "W"]),
    S("crossbowman", "Crossbow Booster", 2, "buff", 20, "弩攻速 +2 阶段 300 秒，需 Crossbow Mastery Lv5", ["Q", "W"]),
    S("crossbowman", "Soul Arrow: Crossbow", 2, "buff", 20, "300 秒内攻击不消耗箭矢，需 Crossbow Booster Lv5", ["Q", "W"]),
    S("crossbowman", "Iron Arrow: Crossbow", 2, "active", 30, "180% 伤害，直线穿透多目标", ["Q", "W", "M"]),
    S("crossbowman", "Amazon's Judgement", 2, "passive", 20, "暴击时 100% 概率降低怪物速度 35", ["Q", "W", "M"]),

    # ---- Thief 1st
    S("thief", "Lucky Seven", 1, "active", 20, "投掷 140% 伤害（远程）", ["Q", "W"]),
    S("thief", "Double Stab", 1, "active", 20, "单次两段 160% 伤害（近身）", ["Q", "W"]),
    S("thief", "Disorder", 1, "buff", 20, "降低怪物攻击与武器防御，30 秒", ["Q", "W"]),
    S("thief", "Dark Sight", 1, "buff", 20, "隐身并保持正常移速，需 Disorder Lv3", ["Q", "W"]),
    S("thief", "Nimble Body", 1, "passive", 15, "命中 +15、回避 +15", ["Q", "W"]),
    S("thief", "Keen Eyes", 1, "passive", 15, "投掷武器射程 +200，需 Nimble Body Lv3", ["Q", "W"]),

    # ---- Assassin
    S("assassin", "Claw Mastery", 2, "passive", 20, "拳套熟练 + 攻击 +20，25% 概率回收飞镖（只对拳套生效）", ["Q", "W", "M"]),
    S("assassin", "Critical Throw", 2, "passive", 30, "暴击率 +15%、暴击伤害 +35%", ["Q", "W", "M"]),
    S("assassin", "Claw Booster", 2, "buff", 20, "拳套攻速 +2 阶段 300 秒，需 Claw Mastery Lv5", ["Q", "W", "M"]),
    S("assassin", "Haste", 2, "buff", 20, "移速 +30、跳跃 +10，300 秒", ["Q", "W", "M"]),
    S("assassin", "Drain", 2, "active", 30, "240% 伤害，15% 概率吸收部分伤害为 HP，需 Critical Recovery Lv3", ["Q", "W", "M"]),
    S("assassin", "Critical Recovery", 2, "passive", 20, "暴击命中时 100% 回复 10% HP 与 MP", ["Q", "W", "M"]),

    # ---- Bandit
    S("bandit", "Dagger Mastery", 2, "passive", 20, "匕首熟练 + 暴击率 +20%，20% 概率忽略击退（只对匕首生效）", ["Q", "W"]),
    S("bandit", "Savage Blow", 2, "active", 30, "最多 6 段，满级每段 75% 伤害", ["Q", "W", "M"]),
    S("bandit", "Dagger Booster", 2, "buff", 20, "匕首攻速 +2 阶段 300 秒，需 Dagger Mastery Lv5", ["Q", "W"]),
    S("bandit", "Haste", 2, "buff", 20, "移速 +30、跳跃 +10，300 秒", ["Q", "W"]),
    S("bandit", "Steal", 2, "active", 30, "90% 概率偷取并造成 180% 伤害，成功后攻击 +35 持续 60 秒，需 Haste Lv5", ["Q", "W"]),
    S("bandit", "Nimble Recovery", 2, "passive", 20, "回避时 100% 回复 10% HP 与 MP", ["Q", "W"]),
]

# --------------------------------------------------------------------------- 旧稿错误条目
# 上一版职业卡里出现、但不属于当前 Classic 上线版二转的技能。
# status: out_of_scope_3rd_job = 属三转（CoT2/后续版本）；not_found = 三个数据源都没有该技能。
CORRECTIONS = [
    {
        "skill": "Spear Crusher", "job": "spearman", "claimed_tier": 2,
        "status": "not_found",
        "detail": "上一版把 Spear Crusher 写成 Spearman 二转主力输出并放进 Boss 循环。三个 Classic 数据源都没有该技能名；"
                  "枪系三转（Dragon Knight，仅 CoT2 测试）的对应技能名为 Piercing Crusher。已从技能表与循环中删除。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/dragon-knight", "https://meowdb.com/msclassic/classes/dragon-knight"],
    },
    {
        "skill": "Hyper Body", "job": "spearman", "claimed_tier": 2,
        "status": "out_of_scope_3rd_job",
        "detail": "上一版把 Hyper Body 写成 Spearman 二转的队伍 HP/MP 增益与核心卖点。当前 Classic 上线版属 Dragon Knight（三转，仅 CoT2），"
                  "NiaMeowDB 明写 'Hyper Body is a Dragon Knight skill'，MapleStory Quest 的 Dragon Knight 页确认其为 +30% 最大 HP 的队伍增益。已删除。",
        "ev": ["Q", "M", "W"],
        "urls": ["https://maplestory.quest/classes/dragon-knight", "https://meowdb.com/msclassic/classes/spearman"],
    },
    {
        "skill": "Power Guard", "job": "fighter", "claimed_tier": 2,
        "status": "out_of_scope_3rd_job",
        "detail": "复审提出 Fighter 的 Power Guard 归属存疑。核对结果：Fighter 二转 8 技能为 Mastery/Booster/Final Attack 两套 + Rage + Rush，"
                  "不含 Power Guard；Power Guard 属 White Knight（三转，仅 CoT2），MapleStory Quest 的 White Knight 页与 NiaMeowDB 均如此标注。已从 Fighter 与 Page 卡删除。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/white-knight", "https://meowdb.com/msclassic/skills/white-knight/power-guard"],
    },
    {
        "skill": "Weapon Mastery", "job": "fighter", "claimed_tier": 2,
        "status": "not_found",
        "detail": "上一版 Fighter 卡写 Weapon Mastery。Classic 数据里 Fighter 的熟练类技能是 Sword Mastery 与 Axe Mastery（按武器分开），"
                  "不存在通用的 Weapon Mastery。已按实际技能名替换。",
        "ev": ["Q", "W"],
        "urls": ["https://maplestory.quest/classes/fighter", "https://mapleclassic.wiki/wiki/Skills"],
    },
    {
        "skill": "Shield Mastery", "job": "page", "claimed_tier": 2,
        "status": "not_found",
        "detail": "上一版 Page 卡写 Shield Mastery。Page 二转 8 技能为两套 Mastery/Booster/Final Attack + Threaten + Rush，"
                  "三个数据源均无 Shield Mastery；盾是装备选择，不占技能位。已删除。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/page", "https://mapleclassic.wiki/wiki/Skills"],
    },
    {
        "skill": "Poison Brace", "job": "fp-wizard", "claimed_tier": 2,
        "status": "not_found",
        "detail": "上一版火毒卡写 Poison Brace。Classic F/P Wizard 的毒系技能是 Poison Breath。已改名并补充其定位。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/fp-wizard", "https://mapleclassic.wiki/wiki/Skills"],
    },
    {
        "skill": "Basic Attack", "job": "beginner", "claimed_tier": 1,
        "status": "not_found",
        "detail": "上一版初学者卡把 Basic Attack 当技能。Classic Beginner 只有 Three Snails / Recovery / Nimble Feet 三个技能（各上限 3 级）。已替换。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/beginner", "https://mapleclassic.wiki/wiki/Skills"],
    },
    {
        "skill": "涂毒类辅助", "job": "bandit", "claimed_tier": 2,
        "status": "not_found",
        "detail": "上一版侠客卡写“匕首熟练与涂毒类辅助”。Classic Bandit 二转 6 技能（Dagger Mastery/Savage Blow/Dagger Booster/Haste/Steal/Nimble Recovery）"
                  "没有毒系技能。已删除该表述。",
        "ev": ["Q", "W", "M"],
        "urls": ["https://maplestory.quest/classes/bandit", "https://mapleclassic.wiki/wiki/Skills"],
    },
]

FORBIDDEN_IN_CLASSIC = ["Spear Crusher", "Hyper Body", "Power Guard", "Weapon Mastery", "Shield Mastery",
                        "Poison Brace", "Piercing Crusher", "Dragon Fury", "Dragon Roar", "涂毒"]


def status_of(ev):
    return "verified" if len(ev) >= 2 else "verified_single_source"


def skill_status(s):
    return s["status"] or status_of(s["ev"])


def job_meta(key):
    for j in JOBS:
        if j["key"] == key:
            return j
    raise KeyError(key)


def verified_skills(job):
    """可用于职业卡与建议循环的技能（上线版一转/二转 + 至少一个当前 Classic 数据源）。"""
    out = []
    for s in SKILLS:
        if s["job"] != job:
            continue
        st = skill_status(s)
        if st in ("verified", "verified_single_source") and s["tier"] <= 2:
            out.append(s)
    return out


def verified_names():
    return {s["n"] for s in SKILLS if skill_status(s) in ("verified", "verified_single_source") and s["tier"] <= 2}


def card_skills(job, only=None):
    """生成职业卡 skills 字段：[{n, lv, d}]，lv 标明一转/二转。"""
    rows = []
    for s in verified_skills(job):
        if only and s["n"] not in only:
            continue
        rows.append({"n": s["n"], "lv": "二转" if s["tier"] == 2 else "一转", "d": s["eff"]})
    return rows


def primary_url(s):
    return SOURCES[s["ev"][0]]["url"] if s["ev"] else ""


def review_payload(now=None):
    """CLASS-SKILLS-REVIEW.json 的完整内容。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    jobs = []
    for j in JOBS:
        rows = []
        for s in [x for x in SKILLS if x["job"] == j["key"]]:
            rows.append({
                "skill": s["n"],
                "job": j["en"],
                "tier": s["tier"],
                "kind": s["kind"],
                "max_level": s["mx"],
                "applicable_version": VERSION_LABEL,
                "sources": [{"id": i, "name": SOURCES[i]["name"], "url": SOURCES[i]["url"], "kind": SOURCES[i]["kind"]} for i in s["ev"]],
                "evidence_summary": s["eff"],
                "status": skill_status(s),
                "in_card": True,
                "note": s["note"],
            })
        for c in [x for x in CORRECTIONS if x["job"] == j["key"]]:
            rows.append({
                "skill": c["skill"],
                "job": j["en"],
                "tier": c["claimed_tier"],
                "kind": "n/a",
                "max_level": None,
                "applicable_version": VERSION_LABEL,
                "sources": [{"id": i, "name": SOURCES[i]["name"], "url": SOURCES[i]["url"], "kind": SOURCES[i]["kind"]} for i in c["ev"]],
                "evidence_summary": c["detail"],
                "status": c["status"],
                "in_card": False,
                "note": "旧稿条目：已从职业卡与建议循环移除",
                "legacy_urls": c["urls"],
            })
        jobs.append({
            "job_key": j["key"], "job_cn": j["cn"], "job_en": j["en"], "tier": j["tier"],
            "advancement": j["adv"], "official_branch_confirmed": j["official"],
            "official_source": SOURCES["O1"]["url"],
            "verified_skills": sum(1 for r in rows if r["status"].startswith("verified")),
            "skills": rows,
        })

    counts = {
        "jobs": len(jobs),
        "first_jobs": sum(1 for j in jobs if j["tier"] == 1 and j["job_key"] != "beginner"),
        "beginner": sum(1 for j in jobs if j["job_key"] == "beginner"),
        "second_jobs": sum(1 for j in jobs if j["tier"] == 2),
        "skills_total": len(SKILLS),
        "verified": sum(1 for s in SKILLS if skill_status(s) == "verified"),
        "verified_single_source": sum(1 for s in SKILLS if skill_status(s) == "verified_single_source"),
        "corrections": len(CORRECTIONS),
        "out_of_scope": sum(1 for c in CORRECTIONS if c["status"] == "out_of_scope_3rd_job"),
        "not_found": sum(1 for c in CORRECTIONS if c["status"] == "not_found"),
    }
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "game_key": "maplestory",
        "scope": VERSION_LABEL,
        "method": "以三份独立的 Classic World 数据源逐技能比对技能名与所属职业层级（两源以上一致记 verified，单源记 verified_single_source）；"
                  "上限等级取自站点数据表的对应条目，仅用于内部核对，卡片不把这些数值宣称为官方数值。"
                  "三转（CoT2）归属记 out_of_scope_3rd_job；三源均无的旧稿技能名记 not_found。"
                  "官方公告只用于确认 4 个一转 + 10 条二转与 Lv100 上限，未用于任何技能级结论。",
        "official_facts": [
            {"claim": "Lv10 一转四职业（Warrior / Magician / Bowman / Thief），Lv30 十条二转分支，Lv100 上限", "url": SOURCES["O1"]["url"], "status": "official"},
            {"claim": "上线版没有三转；三转技能只存在于 Closed Online Test 2 测试数据", "url": "https://mapleclassic.wiki/wiki/Jobs", "status": "community_corroborated"},
            {"claim": "官方职业页对无 JS 客户端只返回空壳，本轮未从官方页取得技能级数据", "url": SOURCES["O2"]["url"], "status": "blocked"},
        ],
        "sources": [SOURCES[k] for k in ("O1", "O2", "Q", "W", "M")],
        "jobs": jobs,
        "corrections": CORRECTIONS,
        "forbidden_in_classic": FORBIDDEN_IN_CLASSIC,
        "unverified_skills": [
            {"skill": c["skill"], "job": job_meta(c["job"])["en"], "status": c["status"], "handling": "不进职业卡技能表、不进建议循环；在 corrections 中留证"}
            for c in CORRECTIONS
        ],
        "limits": [
            "技能数值（伤害倍率、触发概率、持续时间）取自社区数据站的客户端数据整理，非官方页；卡片只保留定位级描述，未核数值不写成官方数值。",
            "Spear Mastery 附加效果、Bless 具体效果在两站描述不一致，卡片只写通用定位，具体以游戏内为准。",
            "星级难度、优势/短板、build 与循环顺序为 Hermes 判断，非官方评级。",
            "三转（Dragon Knight / White Knight / Crusader 等）不在上线版，未做技能级覆盖。",
        ],
        "counts": counts,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(review_payload()["counts"], ensure_ascii=False))
