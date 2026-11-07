# wowforever-bot 部署说明（Blingtron-9000）

服务器：`play187` = `47.85.224.112`　目录：`/opt/wowforever-bot/`
Python：`/opt/python39` 3.9.18 + 独立 venv（discord.py 2.7.1）
服务：`wowforever-bot.service`（`Restart=always`，已 `enable`）

---

## 一、目录结构

```
/opt/wowforever-bot/
  bot.py                 入口：模块注册 / 事件路由 / 豁免表
  selftest.py            离线自检（不连网关，只走 REST）
  config.json            频道别名、身份组、模块开关、特权意图开关
  lib/store.py           JSON 原子写状态
  modules/
    base.py              Module 基类 + STOP/PASS 约定 + Context
    guard.py             守卫（优先级 10，可短路）—— 骨架
    priceboard.py        价格看板（20）—— 骨架
    tickets.py           工单（30）—— 骨架
    welcome.py           欢迎/身份组（40）—— 已实现
  secrets/token.txt      令牌，chmod 600
  state/state.json       面板 message_id、豁免消息表
  logs/bot.log           滚动日志（2MB × 5）
  backup-YYYYMMDD/       改前备份
```

---

## 二、模块共存的三条纪律（改代码前必读）

1. **守卫先跑**：`on_message` 里按 `priority` 升序执行，守卫命中返回 `STOP` 即中断，后续模块收不到该消息。
2. **豁免表**：`bot.add_exempt(msg_id)` 登记的消息（欢迎面板、以后的价格看板/工单面板），任何清理逻辑必须先 `bot.is_exempt()` 再决定删不删。
3. **custom_id 前缀**：一律 `wf:<module>:<action>`。`on_interaction` 按前缀找模块，模块被关掉时回一句「This panel is not active right now」而不是石沉大海。

---

## 三、常用命令

```bash
systemctl status wowforever-bot
journalctl -u wowforever-bot -n 50 --no-pager
tail -f /opt/wowforever-bot/logs/bot.log

# 改完代码后
cd /opt/wowforever-bot && .venv/bin/python -m py_compile bot.py modules/*.py && systemctl restart wowforever-bot

# 自检（不连网关）
cd /opt/wowforever-bot && .venv/bin/python bot.py --check
cd /opt/wowforever-bot && .venv/bin/python selftest.py
```

---

## 四、回滚

```bash
systemctl disable --now wowforever-bot     # 停服（不删数据）
# 代码回滚：从 backup-YYYYMMDD/ 取回对应文件覆盖后 restart
```

线上写入只有两样，都可撤：
- `👋│welcome` 里的面板消息 `1568549337145942168`（删掉即可，重启会自动重发）
- `state/state.json`（删除后面板会重新发布一条新的）

---

## 五、两个前置（2026-11-07 17:10 已全部完成）

| 项 | 状态 |
|---|---|
| **特权意图** `MESSAGE CONTENT` + `SERVER MEMBERS` | ✅ 已在开发者后台打开；`config.json` 的 `intents` 已置 `true`，`members=True message_content=True` 连接正常 |
| **角色位置** | ✅ `Blingtron-9000` 已拖到 **pos=18**（`manager` 之下）；`selftest.py` 11 个身份组全部「可分配」，输出 `SELFTEST OK —— 配置全部可用` |

> 记死：机器人**永远无法**修改或抬高自身受管角色（`PATCH /guilds/{g}/roles/{own}` 恒 `403`，有无 Administrator 都一样）；也**改不了自己看不见的频道**（`403 Missing Access`）。这两条都只能人工在 UI 完成。

---

## 五·二、Zira 已移除（2026-11-07 17:12）

| 动作 | 结果 |
|---|---|
| 踢出 `Zira`（id `275813801792634880`，角色 pos=13） | `DELETE` → `204`，读回成员 18→**17**，机器人只剩 `Blingtron-9000` |
| 清理它在 `👋│welcome` 的 18 条公开欢迎 | 18 删 / 0 失败，读回 **Zira 残留 0** |
| 入群欢迎接替 | 我方 `welcome.send_join_message` 改 `true`，**克制版**：embed + 只 `@` 本人（`AllowedMentions(users=[member])`，不 `@everyone`） |

> 遗留：`👋│welcome` 还有 1 条 `Carl-bot` 的垃圾消息 `1567448604002492509`（2026-11-04 误发未渲染命令 `/greetings welcome ...`，该机器人本身也已不在服务器），未动，等确认再删。


---

## 六、已验证事实（2026-11-07）

- 服务 `active`，网关连上，日志无 traceback
- 面板 `1568549337145942168`：1 embed + 2 下拉（8 语言 / 3 玩法），重启后**原位更新，不重复发**
- `selftest.py`：10 个频道别名全部存在（`FAIL` 0 项）；11 项层级告警
- 后台价表读取验证：`GET /game/admin_game_price/index.html?gid=1364` → 40 行，`b2c` = 玩家价（USD / 1000G）

---

## 七、待接入

| 模块 | 状态 | 卡点 |
|---|---|---|
| welcome | ✅ 已上线（面板 + 身份组 + 入群欢迎） | 入群欢迎尚未被真实新人触发验证 |
| priceboard | ✅ 已上线（🪙│gold-price） | 无 |
| guard | ✅ 已上线（dry_run=false，实封） | 无 |
| giveaway | ✅ 已上线（🎁│giveaway 老虎机） | 无 |
| tickets | 骨架 | 无 |

---

## 八、2026-11-07 17:35 上线内容

### 8.1 清理
`Carl-bot`（`235148962103951360`，配置噪音 `<<No dm message>>` / `Greet message updated.` / 裸命令）
全服 **42 条** + `Zira` 漏网 **1 条** = 43 条，0 失败，残留 0。工具：`_purge_authors.py <author_id...>`。

### 8.2 守则
`📋│community-rules` → 消息 `1568559623890276496`，2 个 embed（英文 10 条 + 中文版），已置顶，
置顶系统提示（type=6）已删，频道只有这 1 条。工具：`_post_rules.py`（幂等，有记录就原位更新）。

### 8.3 金币查价频道
新建 `🪙｜gold-price`（`1568557228733104129`，COMMUNITY 分类，`@everyone` 只读：
allow `66560` / deny `377957124160`）。
看板消息 `1568557528390959116`，30 分钟原位刷新（`priceboard` 模块）。

数据源与口径（实测）：
```
GET /game/admin_game_price/index.html?gid=1364   (经 /opt/d4follow/core_p2pah.py 的 P2PAHClient)
40 行 = 4 大区 × 10 区服；b2c 列即玩家价，USD / 1000 金
b2c = 采购成本 ÷ 6.65 ÷ 0.8（40 行比值恒定 0.188）
```
交互：看板 1 个下拉（大区）→ 私密面板（大区 + 模式 两个下拉），显示 Alliance/Horde 价与
G2G / Eldorado 对照、便宜幅度。面板状态存 `state.json`，重启不失效。

### 8.4 守卫（沿用原规则 + 两处修正）
品牌表 `MMOEXP`（自家，official）/ `U4GM` / `IGGM` / `LOOTBAR`（竞品），`action=ban`，`dry_run=false`。
移植自 `2026-10-14_前缀冒充防护_GuardBot/index.js`：`canon`（NFKC + 去零宽 + 异体字归一）
→ `squash` → 片段匹配（1 字符容错）/ 前缀正则（strict·loose）/ `SUFFIX_OK` 后缀白名单。

**两处必要修正**（原逻辑的洞，已用 112 条原语料验证）：
1. 长度门槛 `6 → 4`。原版按 `mmoexp`(6) 定的，导致 `U4GM` / `IGGM` 这种 4 字符竞品名**完全裸奔**。
2. 新增 **leet 归一**（`0→o 1→i 4→a 3→e 9→g 8→b` 等），对名字与品牌词本体用同一套映射。
   这样 `l00tbar` / `L00TB4R` / `1ggm_support` / `ig9m_official` 都能抓，而
   `lootbag` / `lootbox` / `footbar` / `lootbarn` **不会误伤**（WoW 服里这是正常名字）。
   竞品品牌 `fuzzy` 设为 **0**，只有 MMOEXP 保留 1 字符容错。
3. 修了一个实现 bug：leet 曾把**后缀数字**也替换（`U4GM2026`→`uagm2o26`），导致数字后缀判定失效。
   现改为「匹配用归一形，判后缀用原始形」。

验证：`_guard_test.py` 跑原 112 条语料 → **命中 71 / 放行 41，硬断言 0 失败**；启动全量扫描
**17 成员 0 命中**（无误伤真人）。

⚠️ MMOEXP 仍是 `matchMode=loose`（与 2026-11-06 一致），意味着 `mmoexpert` / `mmoexpo` /
`mmoexpfan2026_play` 也会被判冒充。要收紧就把该品牌改成 `strict`（改 config 即可，不动代码）。

### 8.5 抽奖（老虎机）
`🎁│giveaway` 面板 `1568559401265270785`，按钮 `wf:giveaway:spin`。
三卷轴逐帧滚动（编辑同一条私密消息 3 次，0.55s/帧）→ 揭晓，颜色按奖品稀有度。

| 奖品 | 概率 | 库存 | 码 | 颜色 |
|---|---|---|---|---|
| 10-Slot Bag | 2% | 10 | — | `#7F77DD` |
| 8-Slot Bag | 30% | 50 | — | `#378ADD` |
| 5% Off Coupon | 50% | 不限 | **`wowexp`** | `#97C459` |
| 8% Off Coupon | 18% | 不限 | **`wowexp8`** | `#EF9F27` |

概率写在 `config.features.giveaway.prizes[].chance`（合计必须 100，否则面板 footer 报警）。
10 万次抽样验证：2.04% / 30.12% / 49.97% / 17.87%，`DIST TEST OK`。

**每人 2 次**：`spins_per_user: 2`；`bypass_users`（陈超 / Ryan）不受限，返回 `-1`。
`spins_left()` 的语义是 **`-1` = 不限、`0` = 用完**，判断写 `== 0`。

**库存**：`prizes[].stock` → 落 `state.json` 的 `giveaway_stock`。
抽到没货的奖品按 `fallback_prize`（默认 `coupon5`）**自动降级成 5% 券**，不发空奖。
面板每发一个包就地刷新一次 `N left`。清零库存 = 删 `giveaway_stock` 键，会按 config 重新播种。

**固定码**：奖池里配了 `code` 就不生成随机码。固定码**不写** `giveaway_codes`（那张表以 code
为键，共用会互相覆盖），改追加 `giveaway_coupon_log` 流水；只有随机唯一码才进 `giveaway_codes`。

### 8.7 抽奖 v2（2026-11-07 18:34）

**面板重排**：拆成两块 embed —— `Lucky Spin`（`## Prize pool` 放大 + 空行留白）与
`How it works`（背包 / 券两条说明），按钮独立一行。Discord 按钮字号固定、无法调大，
只能靠留白让整体不挤。

**奖品分两类**（`prizes[].type`）：

| type | 流程 |
|---|---|
| `bag` | 中奖卡 → 按钮 **Add delivery details** → 弹窗填 `Server / Sub-realm / Character name` → 落 `state.json` 的 `giveaway_claims` + 推 `🧾│order-logs` 并 **@ 运营** → 用户侧提示「Ryan Brooks 游戏内邮寄，一天没到就 ping 他」 |
| `coupon` | 配置了 `code` 直接发固定码（`wowexp` / `wowexp8`）；没配才生成唯一码 `WOWF-<5P\|8P>-XXXXXX` → 中奖卡用代码块展示 → 附 **Buy Cheap Gold Now** 跳转按钮 |

**面板文案**：英文魔兽风，`WOW FOREVER · Lucky Loot`，首屏大字
"Two spins. Zero gold. No catch."，正文「This disgustingly handsome bot just handed you
**2 free spins**」。

**版面结构（2026-11-07 19:14）**：一条消息 **5 个 embed** —— 1 张主卡（标题 + 文案 +
`## Prize pool` 分区标题）＋ **每个奖品一张独立卡片**，共 5 个 embed。每张奖品卡自带该奖品的
色条，卡片之间天然留白，不再 4 行挤成一段。原来的 `How it works` 说明块已删除。

**库存颜色**：`stock_line()` 用色点表达（Discord 没有文字颜色能力）：

| 余量 | 显示 |
|---|---|
| > 50% | `🟢 10 / 10 left` |
| 20–50% | `🟡 4 / 10 left` |
| < 20% | `🔴 1 / 10 left` |
| 0 | `🔴 sold out` |
| 不限量（券） | `♾️ unlimited` |

**公开面板不嵌 `<@id>`** —— 用纯文本 `staff_name`（`Ryan Brooks`），否则每次重启编辑面板
都会把运营拽一遍；`staff_contact` 只在登记通知里 @。

**无限次**：`features.giveaway.bypass_users`（陈超 `1037677694487384104` / Ryan `1477093313265008720`）。
注意 `cooldown_hours=0` 时本来全员不限次，bypass 是为将来设冷却时准备的白名单。

**跳转联动**：链接与文案抽到顶层 `config.shop`（`url` / `label`），金币看板与抽奖页共用一份，
改一处两边同步；各模块仍可用 `features.<x>.shop_url` 覆盖。

**已知限制**：`Add delivery details` 按钮原先挂在 15 分钟临时消息上（重启或超时失效）。
**2026-11-07 18:57 已修**：`DeliveryView` 改为 `timeout=None` + 固定 `custom_id`
`wf:giveaway:deliver`，随 `views()` 持久化注册；中包先落 `giveaway_pending`
记录，按钮按「该用户最早一条待登记」反查奖品。登记通知会 **@ 运营（`staff_contact`）**。

### 8.8 欢迎面板改四级反应式（2026-11-07 18:39，参考 AION2）

**公共消息不再挂下拉**，只留一个 `🎭 Pick your roles` 按钮；点开是**私密面板**，四级逐级解锁：

| 级 | 组 | 选项数 | 来源 |
|---|---|---|---|
| 1 | Region（国家/地区） | 8 | 原语言组（English … Chinese (Traditional)） |
| 2 | Faction（阵容） | 2 | **新建** Alliance / Horde |
| 3 | Ruleset（规则集） | 3 | 原 PVE / PVP / RPG |
| 4 | Class（职业） | 9 | **新建** Warrior…Druid |

**新建了 11 个身份组**（本脚本 `_make_role_groups.py`，幂等）：
`Alliance #3B82F6` `Horde #EF4444`，职业按 WoW 职业色：Warrior `#C79C6E` / Paladin `#F58CBA` /
Hunter `#ABD473` / Rogue `#FFF569` / Priest `#E8E8E8` / Shaman `#0070DE` / Mage `#69CCF0` /
Warlock `#9482C9` / Druid `#FF7D0A`。全部 0 权限、不 hoist、不可 mention。

**交互细节**
- 上一级没选，下一级菜单**不出现**（不是禁灰，是不渲染）
- 占位文字直接显示当前答案：`2 · Faction — Horde`；未选时显示 `3 · Ruleset — choose`
- 面板顶部四行汇总：`**1 Region**　✓　English`
- 改上层答案会清空下层，避免出现 Faction 与 Region 错位
- 四级齐了一次性挂 4 个组（同组旧的自动摘掉）
- 状态按**私密消息 id** 存 `state.json`（`rolehub_<message_id>`），重启后旧面板仍可用

**验证**：`_welcome_check.py` 断言「空状态 1 个下拉 / 选地区后 2 个 / 四级齐 4 个」全过
（`WELCOME CHECK OK`）；`selftest.py` 22 个组全部「可分配」；线上公共面板读回 `embeds=1` +
1 个按钮、无下拉。

### 8.9 职业口径核实 + 清理空壳角色（2026-11-07 18:44）

**职业 = Classic 9 职业，已核实无误**。WoW Forever 是 Blizzard 2026-11-04 上线的 Classic+ 分支
（等级上限 60，永久不提升），**没有 Death Knight / Monk / Demon Hunter / Evoker**，所以 9 职业配置不需要改。

判据（比网页搜索更可靠）：后台 `gid=1364` 的区服类型正好是 `Normal / PVP / Roleplay / Hardcore`，
对应官方四个 ruleset；WotLK 时代不存在 Hardcore 服。搜索里 `wowforever.games` 说「WotLK 3.3.5a / DK 是 S 级」
是蹭名的 SEO 站，别采信。

**删除 4 个空壳角色**（判定条件：0 人持有 + `permissions=0` + 未被 config 引用）：

| 角色 | 权限值 | 持有者 |
|---|---|---|
| `muted` | 0 | 0 |
| `Trader` | 0 | 0 |
| `Moderator` | 0 | 0 |
| `Game Master` | 0 | 0 |

角色总数 **30 → 26**，4 条 `DELETE` 均返回 `204`。

**没动的**：`manager`（12 人）/ `BOT` / `Blingtron-9000`（托管）/ 22 个功能组。

**回滚**：删前已备份定义到 `_backup_roles_<时间戳>.json`（含色值、权限、hoist、mentionable），
按 name/color/permissions 依次 `POST /guilds/{gid}/roles` 即可重建（新 id，但这 4 个原本没被引用，不用改配置）。

**Hardcore 决议（2026-11-07）**：**暂不添加**。官方 Hardcore ruleset 预计 **约 2027-01 开放**
（发布时说「冬 2026/27」），现在建组没人能选、只会占位置。到期后补的做法（约 2 分钟）：

1. 建角色 `Hardcore`（色值建议 `#8B0000`，0 权限、不 hoist、不可 mention）
2. `config.features.welcome.role_hub.rulesets` 追加一条
   `{"key":"hardcore","label":"Hardcore","emoji":"💀","role_id":"<新id>"}`
3. `systemctl restart wowforever-bot` — 四级菜单自动多出这一项，代码零改动



### 8.6 价格数据源改为 RPG 改价系统（2026-11-07 18:00）

**不再由机器人去后台页面抓 HTML**，改吃 183 改价系统自己的产物：

```
play183 47.85.170.62 (内网 172.18.108.183)
  /opt/d4follow  wow-gold-follow.timer  每 10 分钟一轮
      └─ output/魔兽金币台账_<YYYYMMDD_HHMMSS>.json   （plan 40 行）
              ↓ ssh（既有 transfer_key，不新建凭据）
play187 /opt/wowforever-bot/sync_wow_gold.py       每 10 分钟（wowforever-goldsync.timer）
      └─ state/gold_prices.json   （归一化快照）
              ↓ bot 每 60 秒看一次文件 mtime
priceboard 模块 → 原位刷新看板
```

| 项 | 值 |
|---|---|
| 取数字段 | **目标b2c**（改价系统算出的目标价），缺失时回退 `现b2c` |
| 中转脚本（183） | `/opt/d4follow/_wow_ledger_dump.py` —— 远端自己找最新台账，避免命令行里传中文文件名 |
| 同步脚本（187） | `/opt/wowforever-bot/sync_wow_gold.py`，原子写快照 |
| 定时器 | `wowforever-goldsync.timer`（`OnActiveSec=45` + `OnUnitInactiveSec=10min`，CentOS7 systemd 219 只认单调时钟） |
| 陈旧判定 | 台账超过 25 分钟没更新 → 看板加 ⚠️ 提示 |

**单位自证**（这是判断「每 1 金」而非「每 1000 金」的硬证据）：
```
均价元每金 16.819966 元/金  ×  IGGM倍数 1.05  ≈ 17.66 元
17.66 ÷ 汇率 6.65 = $2.655  ≈  目标b2c 2.6145  ✅
```
整条链路（DD373 均价 → ×倍数 → ÷汇率 → b2c）都在「每 1 金」上闭环，所以看板写 `USD per 1 Gold`。

**实测（2026-11-07 17:57）**
```
wowforever-goldsync.timer  LAST=17:57:23  NEXT=18:07:23
[sync] OK 40 行（有价 40） ledger=魔兽金币台账_20261107_175048.json ts=2026-11-07T17:51:14
bot 17:57:56 检测到新台账 2026-11-07T17:51:14 -> 刷新看板
看板：NA $2.61 / EU $3.87 / KR $4.37 / Asia $1.97
```
