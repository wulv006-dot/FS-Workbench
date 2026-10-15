# Shugo-bot — AION 2 Kinah 新成员引导机器人

## 它做什么

| 场景 | 行为 |
|---|---|
| **新成员加入服务器** | 机器人**私信**一条欢迎卡（带频道直达链接）。**频道里一条都不发** → 零刷屏 |
| **成员打开 `#👋｜welcome`** | 看到一条置顶常驻卡片：2 个阵营按钮 + 8 个职业按钮（5 行组件） |
| **点阵营 / 选职业** | 身份组立刻到账，回执**只有本人看得见**（ephemeral） |
| **改主意** | 再点一次即可，自动移除旧身份组（阵营互斥、职业单选） |
| 频道权限 | 只读：`@everyone` 能看、能翻历史，**不能发消息、不能加表情** |

---

## 文件清单

| 文件 | 作用 |
|---|---|
| `bot.py` | **主程序**（常驻运行）。监听"有人加入" + 处理按钮/下拉点击 + 定时抓官方资讯 |
| `news.py` | **官方资讯模块**：抓 plaync 接口 + 渲染 Discord 卡片（`python news.py` 可单独干跑验证） |
| `config.json` | **配置**：频道 ID、身份组 ID、文案、资讯板块。改文案改这里 |
| `news_state.json` | 已推送过的文章 id（防重启重复刷屏），自动生成 |
| `token.txt` | 机器人令牌（`SHUGO_TOKEN` 环境变量优先） |
| `start.bat` | 双击启动，带日志窗口 |
| `start-silent.bat` | 双击启动，最小化窗口 |
| `install.bat` | 换电脑后先跑这个建环境 |
| `setup.py` | 一次性部署：设只读权限 + 发卡片 + 清旧欢迎语 |
| `09_news_setup.py` | 建/维护 `#📰｜news` 资讯频道：建频道 + 只读 + 置顶说明 + 回填 |
| `test_dm.py` | 给服主发一条欢迎私信做预览 |
| `01_inspect.py` / `02_probe.py` / `03_overwrites.py` / `04_at_everyone.py` / `05_verify.py` | 只读体检工具，排查用 |
| `shugo-bot.log` | 运行日志 |

---

## 日常使用

```
双击 start.bat        # 启动（这个窗口别关，关了机器人就下线）
```

**机器人必须一直开着**，否则：新成员收不到私信、按钮点了会显示「交互失败」。
长期 24 小时在线，建议放到服务器上跑（见下方）。

---

## 改配置

所有**文字**都在 `config.json` 的 `texts` 里：

| 键 | 显示在哪 |
|---|---|
| `card_title` | 卡片标题（`Welcome to AION 2 Kinah`） |
| `card_body` | 卡片正文（1️⃣ 2️⃣ 那两行 + 说明） |
| `divider_faction` | 阵营分隔条上的字 |
| `divider_class` | 职业分隔条上的字 |
| `card_footer` | 卡片底部小灰字（🔒 只读提示） |
| `dm_title` / `dm_body` | 新成员收到的**私信**内容 |

`dm_body` 支持占位符：`{name}` 名字、`{ordinal}` 第几位成员、`{link}` 频道链接。

### 按钮外观

```json
"layout": {
  "class_per_row": 4,
  "faction_style": "primary",
  "class_style": "primary",
  "divider_style": "secondary",
  "equal_width": true,
  "row_px": 480
}
```

| 键 | 作用 | 可选值 |
|---|---|---|
| `faction_style` | 阵营按钮颜色 | `primary` 蓝 · `secondary` 灰 · `success` 绿 · `danger` 红 |
| `class_style` | 职业按钮颜色 | 同上 |
| `divider_style` | 两条分隔条的颜色 | 同上 |
| `class_per_row` | **每行几个职业按钮 = 宽度** | `4`（默认）· `5` |
| `equal_width` | 把所有按钮撑到等宽 | `true` / `false` |
| `row_px` | 目标行宽（像素）。太宽被截断就调小 | `480`（默认）· 试 `440` / `400` |

#### 「等宽」是怎么做到的（重要）

Discord **没有给机器人任何宽度参数**，按钮宽度完全由客户端按内容决定 —— 所以
`Elyos` 比 `Asmodian` 窄、`Cleric` 比 `Spiritmaster` 窄，一行参差不齐。

实测得到的渲染模型（14px / 100% 缩放）：

```
带 emoji 的按钮宽 ≈ 58 + 4.5 × 标签字数 + 填充字符数 × 9
分隔条（禁用按钮）宽 ≈ 7.4 × 虚线数 + 4.5 × 名字字数 + 73
```

于是用 **U+2800（BRAILLE PATTERN BLANK）** 给短标签居中补长 —— 它是一个真正的
空白字形，**能通过 Discord 的校验和渲染**。

> ⚠️ 踩过的坑：**U+2002 EN SPACE 和普通空格都不行**。Discord 服务端会把按钮标签
> 首尾的空白字符 **strip 掉**（实测 API 回读为 0 个）。只有 `U+2800` 这种
> 「不是空白字符、但渲染为空」的字符才能留存。

补长后各行实测/预测宽度：

| 行 | 内容 | 行宽 |
|---|---|---|
| row0 | FACTION 分隔条 | ≈482 px |
| row1 | 🪽 Elyos / 😈 Asmodian | ≈484 px |
| row2 | CLASS 分隔条 | ≈489 px |
| row3 | ⚔️ Gladiator … 🏹 Ranger | ≈475 px |
| row4 | 📖 Sorcerer … 🎵 Chanter | ≈480 px |

**组件排布（一条消息共 5 行，正好顶到 Discord 上限）：**

```
row0  ────────  ⚜️  FACTION  ────────     ← 禁用按钮
row1  🪽 Elyos            😈 Asmodian
row2  ────────  ⚔️  CLASS  ────────       ← 禁用按钮
row3  ⚔️ Gladiator  🛡️ Templar  🗡️ Assassin  🏹 Ranger
row4  📖 Sorcerer   🪄 Spiritmaster  ✨ Cleric  🎵 Chanter
```

**Discord 的硬限制：**
1. **颜色只有 4 种预设**，不能自定义任意色值（做不出身份组那种紫色 `#a855f7`）
2. **按钮宽度不能直接设**，只能靠补长字符间接撑（见上）
3. **一条消息最多 5 行组件**。阵营/职业各占 1 条分隔条 + 阵营 1 行 = 已用 3 行，
   职业只剩 2 行 → `class_per_row` **最小只能到 4**（填 1/2/3 会被自动提升为 4 并打 WARNING）

单个角色也能单独指定颜色，优先级高于上面的全局设置：

```json
{ "label": "Gladiator", "emoji": "⚔️", "role_id": "...", "style": "danger" }
```

改完记得**重启机器人**（`start.bat`），再刷新卡片：

```
python setup.py --channel <频道名>
```

---

## 重新部署 / 迁移频道

```
set SHUGO_TOKEN=<token>
python setup.py --channel bot-test            # 设只读 + 发卡片
python setup.py --channel bot-test --purge    # 顺带清掉 Carl-bot 的旧欢迎语
python setup.py --channel bot-test --dry-run  # 只看会做什么，不动
```

频道别名在 `setup.py` 的 `CHANNEL_ALIAS` 里，也可以直接传频道 ID。

---

## 常见问题

**Q: 点了按钮显示「交互失败」**
机器人没在线。双击 `start.bat`。

**Q: 身份组没到账**
检查 服务器设置 → 角色：Shugo-bot 的身份组必须**排在** `Elyos`/`Asmodian`/各职业**上面**。
（脚本每次运行都会自动检查并提示）

**Q: 新成员收不到私信**
Discord 隐私设置 → 「允许来自服务器成员的私信」被对方关了。这个无法绕过，建议在
`#rules` 里补一句提示。

**Q: 频道里还能看到 Carl-bot 的欢迎语**
Carl-bot 的频道欢迎必须在它自己的后台关：carl.gg → 选服务器 → Modules → Greetings →
取消「发送欢迎消息到频道」。**别的机器人改不了 Carl-bot 的配置。**

**Q: 卡片被删了 / 想换频道**
重新跑 `setup.py --channel <频道名>`。

---

## 📰｜news 资讯频道（自动抓官方通告）

机器人每 **30 分钟**轮询一次 AION 2 官方站，把**新出现**的官方帖自动发到 `#📰｜news`。
频道**只读**（`@everyone` 能看能翻历史，不能发言/加表情），成员只能读。

| 板块 | 内容 | 频道内标签 | 卡片颜色 |
|---|---|---|---|
| `notice_en` | Announcements 公告（维护、停服、服务通知、补偿） | 📢 ANNOUNCEMENT | 蓝 `#60A5FA` |
| `update_en` | Patch Notes 补丁说明 / 更新日志 | 🛠️ PATCH NOTES | 紫 `#A855F7` |
| `movie_clip_en` | Media 官方影像（预告片） | 🎬 MEDIA | 红 `#EF4444` |

每张卡片 = 标题（可点，直达官方原文）+ 摘要 + 官方配图 + 发布时间（Discord 本地化时间戳）。

### 数据从哪来

plaync 全球社区的 JSON 接口，**不用登录、不用鉴权**，只要请求头：

```
列表  https://api-global-community.plaync.com/aion2_global/board/{alias}/article?page=1&size=10
原文  https://aion2.plaync.com/en-us/board/{path}/view?articleId={id}
板块  https://api-global-community.plaync.com/aion2_global/board/{alias}
```

⚠️ **两个坑**（换接口/加板块必踩）：

1. **必须带请求头 `x-nc-service: aion2_global`**。不带会返回**空壳 JSON**
   （`{"board":null,"contentList":[]}`），看着像"官方没发东西"，其实是没带头。
2. **板块别名必须带 `_en` 后缀**。写 `notice` 同样返回空壳，必须写 `notice_en`。

> EN 站目前**没有** event 板块（`/board/event/list` 会 302 到 `www.plaync.com/error/404`）。
> 一旦官方开通，把 `"event_en"` 加进 `config.json` 的 `news_boards` 就自动生效，不用改代码。
> 单页最多返回 10 条，够用（我们只关心最新几条）。

### 配置（`config.json`）

| 键 | 作用 | 默认 |
|---|---|---|
| `news_channel_id` | 目标频道 ID（`09_news_setup.py` 自动写；**留空 = 不推送**） | `""` |
| `news_boards` | 抓哪些板块，数组 | `["notice_en","update_en","movie_clip_en"]` |
| `news_poll_minutes` | 轮询间隔（分钟，最小 5） | `30` |
| `news_backfill` | `09_news_setup.py` 回填条数 | `10` |

### 防重复刷屏

已推送的文章 id 记在 `news_state.json`（滚动保留最近 600 条），**重启不会重发**。

> **首次启动**时若 `news_state.json` 不存在，机器人会**静默认领**当时所有文章、一条不倒灌
> —— 所以半夜部署也不会一觉醒来看到满屏历史帖。想要历史内容是显式跑 `09_news_setup.py --backfill`。

### 建频道 / 改频道

```bash
systemctl stop shugo-bot           # ⚠️ 必须先停：同一 token 两个实例会互相顶掉
cd /opt/shugo-bot
.venv/bin/python 09_news_setup.py             # dry-run，只打印将要做什么
.venv/bin/python 09_news_setup.py --yes       # 执行（幂等，可重复跑）
systemctl start shugo-bot
```

| 参数 | 作用 |
|---|---|
| `--backfill N` | 回填最近 N 条（从旧到新发） |
| `--no-backfill` | 只建频道/设权限，不发历史帖 |
| `--rename "📰｜资讯"` | 顺便改名 |
| `--channel <id>` | 指定用已有频道，不新建 |

单独验证抓取（不发 Discord，纯打印）：

```bash
/opt/shugo-bot/.venv/bin/python /opt/shugo-bot/news.py
```

---

## 长期在线：已部署到阿里云服务器（7×24）

机器人已用 **systemd** 托管在阿里云 `play187`（`47.85.224.112`），**已设开机自启 + 崩溃自动重启**，不需要再开你本机。

| 项目 | 值 |
|---|---|
| 服务器 | `root@47.85.224.112`（CentOS 7.9），SSH 密钥 `No1.pem`（复用） |
| 程序目录 | `/opt/shugo-bot/` |
| 解释器 | `/opt/shugo-bot/.venv/bin/python`（基于 `/opt/python39`，**必须用这个**，见下方坑） |
| 服务名 | `shugo-bot.service` |
| 应用日志 | `/opt/shugo-bot/shugo-bot.log` |

### 常用命令

```bash
systemctl status  shugo-bot      # 看状态
systemctl restart shugo-bot      # 重启（改完 config.json 后用）
systemctl stop    shugo-bot      # 停
systemctl disable shugo-bot      # 取消开机自启
tail -f /opt/shugo-bot/shugo-bot.log   # 跟日志
```

改配置后生效流程：改 `/opt/shugo-bot/config.json` → `systemctl restart shugo-bot` → 若要刷新卡片再跑
`/opt/shugo-bot/.venv/bin/python /opt/shugo-bot/setup.py --channel <频道名>`。

### ⚠️ 部署时踩到的坑（换服务器会再遇到）

服务器上**有两个 Python 3.9.18**：

| 解释器 | SSL | 能否跑本机器人 |
|---|---|---|
| `/usr/bin/python3` → `/usr/local/python39` | ❌ **无 `_ssl`** | **不行**，会报 `RuntimeError: SSL is not supported.` |
| **`/opt/python39/bin/python3.9`** | ✅ OpenSSL 1.0.2k | **用这个** |

所以建 venv 必须显式指定：`/opt/python39/bin/python3.9 -m venv /opt/shugo-bot/.venv`。

---

## 本地运行（备用方案）

| 方案 | 说明 |
|---|---|
| 本机常驻 | 双击 `start.bat`，别关机 |
| 服务器 | 已部署，见上方（推荐） |

> ⚠️ **同一时间只能跑一个实例**。服务器已经常驻，本机就不要再开 `start.bat`，
> 否则新成员会收到**两条**欢迎私信。要临时在本机调试，先 `systemctl stop shugo-bot`。
