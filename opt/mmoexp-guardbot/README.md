# MMOEXP Discord 防冒充防护方案（前缀冒充 → 自动踢出）

> 目标：任何以 **mmoexp** 开头、又不在白名单里的账号，一律视为骗子，**加入服务器的瞬间自动处置**。

---

## 0. 先看结论：为什么要"两层"

| 层 | 手段 | 能做到什么 | 做不到什么 |
|---|---|---|---|
| ① 原生 AutoMod | 服务器设置 → 安全设置 → AutoMod「封堵成员资料名称中的文字」 | 把 `mmoexp*` 加进黑名单词，冒充者**在改名之前无法发言/互动**，并给你发警报 | **不能踢人、不能封禁**（Discord 官方限制），也**管不到私信** |
| ② 自建 GuardBot（本方案核心） | `on_member_join` 事件 + 白名单 | **加入即踢 / 即封**，改名后也会被再抓一次，可一键清理存量 | 需要一台常开设备跑它（本机或你的云服务器） |

**关键事实**：Discord 原生 AutoMod **没有**「按用户名自动踢人」的能力，官方 FAQ 明确写了它只能阻止发言/互动并要求改名。所以"一律踢掉"这个动作，**必须**由机器人来完成。①层留着做零成本的兜底，②层才是真正执行踢人的。

```
新成员加入
   │
   ├─ 名字以 mmoexp 开头？
   │     否 ─→ 放行
   │     是
   │      ├─ 在官方角色白名单里？ ─→ 是 ─→ 放行（真客服）
   │      └─ 否 ─→ 【GuardBot 立即处置：踢出 / 封禁】+ 写日志
   │
   └─ 混进来之后偷偷改名？ ─→ 改名事件再次触发检查 ─→ 照样处置
```

本方案的识别已经考虑了骗子的常见绕过手法的变体：

| 骗子写法 | 是否命中 | 说明 |
|---|---|---|
| `MMOEXP`、`mmoexp` | ✅ | 完全一致 |
| `MMOEXP Support` / `MMOEXP_Official` / `MMOEXP-CS` | ✅ | 常见官方后缀 |
| `MMOEXP01`、`mmoexp_88` | ✅ | 纯数字尾巴 |
| `MM0EXP`、`MMOOEXP` | ✅ | 0 代替 O、多打 o |
| `ＭＭＯＥＸＰ`（全角） | ✅ | NFKC 归一化 |
| `ММОЕХР`（西里尔字母） | ✅ | 同形字折叠 |
| `MMO E X P` / `m.m.o.e.x.p` | ✅ | 去分隔符后比对 |
| `mmoexpert`、`mmoexpo` | ❌ 不命中 | strict 模式避免误伤（要最狠可切 loose） |

---

## 1. 五分钟先做（零代码，立刻见效）

在 Discord 客户端里点：

**① 开启 AutoMod 资料名黑名单**
`服务器设置` → `安全设置(Safety Setup)` → `AutoMod` 旁的 **Edit** → 找到 **Members / 封堵成员资料名称中的文字**，点 X 启用 →
在自定义词里加（一行一个）：

```
mmoexp*
mmo_exp*
mm0exp*
mmo exp*
```

可选：再加 `official support`、`mmoexp` 之类的相关词。保存。
→ 效果：冒充者**改名前不能说话、不能互动**，同时可在 AutoMod 里配置把警报发到 `#guard-log`。

**② 打开 DM 与规则门禁（挡私信诈骗的第二道闸）**
`服务器设置` → `安全设置` → `DM 与垃圾信息防护` → 勾选 **成员必须接受规则才能发言或私信**。
（需要服务器已开启"社区/Community"功能）
→ 效果：没接受规则的新号**发不出私信**，骗子"刚进来就群发私信"的路径被掐断。

**③ 提高验证等级**
`安全设置` → `验证等级` → 设为 **高（最高）**：新号必须在本服待满 10 分钟才能说话。
→ 效果：批量注册的小号大量被挡在门外，也给 GuardBot 留出检查时间。

**④ 关掉"允许服务器成员私信"给玩家的建议**
这属于玩家个人设置（用户设置 → 隐私与安全 → 关闭"允许来自服务器成员的私信"），可以在 #公告 里劝导玩家开启。

---

## 2. 核心：部署 GuardBot（真正执行踢人的那个）

### 2.1 创建 Discord 应用 & 机器人（约 3 分钟）

1. 打开 https://discord.com/developers/applications → **New Application**，起名 `MMOEXP Guard`。
2. 左侧 **Bot** 页 →
   - **Reset Token** → 复制这串 Token（**只显示一次**）。
   - 往下拉到 **Privileged Gateway Intents**，把 **SERVER MEMBERS INTENT** 打开（开关变蓝）。⚠️ 不开这个，机器人收不到"有人加入"事件。
3. 左侧 **OAuth2 → URL Generator** →
   - Scopes 勾：`bot`、`applications.commands`
   - Bot Permissions 勾：`Kick Members`（踢人）、`Ban Members`（如果要用封禁）、`Moderate Members`（如果要用禁言）、`View Channels`、`Send Messages`。
   - 复制最下方生成的链接，在浏览器打开 → 选择 **MMOEXP 服务器** → 授权邀请。
4. 回到服务器 → `服务器设置` → `角色` → 把 `MMOEXP Guard` 这个机器人角色**拖到角色列表靠上的位置**（必须高于你希望它能踢掉的所有角色，不然踢不动）。

### 2.2 拿到两个关键 ID

先在 Discord 里开：`用户设置` → `高级` → 打开 **开发者模式**。
然后：
- **服务器 ID**：右键服务器图标 → `复制服务器 ID`
- **日志频道 ID**：先建一个只有管理员可见的频道 `#guard-log`，右键它 → `复制频道 ID`
- **白名单角色 ID**（推荐）：先建角色 `MMOEXP Staff`，右键该角色 → `复制角色 ID`

### 2.3 填配置

打开本文件夹里的 `config.json`：

```jsonc
{
  "token": "把机器人 Token 粘这里",
  "guildId": "服务器 ID",
  "action": "kick",          // 想彻底防再入就改成 "ban"
  "dryRun": true,            // ★ 先保持 true，观察 24 小时再改 false
  "whitelistRoleIds": ["你的 MMOEXP Staff 角色 ID"],
  "whitelistUserIds": [],
  "logChannelId": "guard-log 频道 ID"
}
```

### 2.4 启动

前置：装 Node.js 18+（你本机已有 v22.22.2，可直接用）。

**Windows 本机**：双击 `start.bat` 即可（首次会自动 `npm install`）。
或手动：

```bash
cd "D:\workbuddy文件目录\discord\2026-10-14_前缀冒充防护_GuardBot"
npm install
node index.js
```

**Linux 云服务器（推荐，稳定不会因为本机关机而失效）**：

```bash
# 服务器上（例：47.85.224.112）
mkdir -p /opt/mmoexp-guardbot && cd /opt/mmoexp-guardbot
# 把本目录全部文件传上来，然后：
npm install
node index.js            # 先手动跑一次，看是否提示 ✅ 已登录
# 确认没问题后改用 systemd 常驻：把 mmoexp-guardbot.service 放到 /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mmoexp-guardbot
journalctl -u mmoexp-guardbot -f   # 看日志
```

看到这几行就是成功了：

```
✅ 已登录：MMOEXP Guard#1234
✅ 已注册 6 条斜杠命令到服务器 xxxxx
模式：DRY-RUN（只记录）  动作：kick  匹配：strict
白名单：角色 1 个 / 用户 0 个
```

### 2.5 上线前必须做的验证（DRY-RUN 期）

`dryRun: true` 时机器人**只记录、不踢人**。这段时间：

1. 用你自己的小号，或让同事，把名字改成 `MMOEXP Support` → 加入服务器。
2. 看 `#guard-log` 是否出现【DRY-RUN】命中记录。✅ 说明规则在工作。
3. 把名字改成普通名字 → 再加入 → 应该**没有**任何记录。✅ 说明不会乱杀。
4. 观察 1～2 天，确认日志里**没有**真客服、真客户被误报。
5. 确认无误后：聊天框输入 `/guard-dryrun enabled:false`，或把 `config.json` 里 `dryRun` 改成 `false` 后重启。
6. 再拿小号实测一次 → 这次应该**进不去**（被秒踢）。

### 2.6 清理存量冒充号

服务器里已经躺着的骗子号，一条命令清掉：

```
/guard-scan              # 先看名单，不动作
/guard-purge confirm:true   # 真处置（会跳过白名单）
```

---

## 3. 日常会用到的斜杠命令

| 命令 | 作用 |
|---|---|
| `/guard-status` | **状态自检**：回报实时运行状态 + 当前配置 + 体检提醒 |
| `/guard-check user:@某人` | 检查某人会不会被判定为冒充（会告诉你命中哪个字段、是否在白名单） |
| `/guard-scan` | 扫描全员，列出命中名单（不处置） |
| `/guard-purge confirm:true` | 对存量命中者执行处置；加 `force:true` 可无视 dryRun 强制踢 |
| `/guard-whitelist action:add type:role id:角色ID` | 把角色加进白名单（推荐给真客服） |
| `/guard-whitelist action:list` | 查看白名单 |
| `/guard-dryrun enabled:false` | 正式上线 / 临时关回观察模式（**会写入 config.json，重启后保持**） |

> 命令权限：扫描/检查/状态需要"管理服务器"；白名单、purge、dryrun 需要"管理员"。

### 3.1 状态自检：给机器人发条消息，它回报自己的状态与配置

三条路都能拿到**同一份报告**：

| 触发方式 | 行为 |
|---|---|
| **私信机器人**（随便发一句） | 直接回复完整报告 |
| **在频道里 @机器人** | 报告**私信**给你；频道里只回一句短提示（不把配置发到公开频道） |
| **`/guard-status`** | 回复完整报告（仅自己可见） |

**报告里有 10 块内容**：运行环境（Node / discord.js / PID / 内存 / 网关心跳 / 已运行多久）·
连接与服务器 · 角色层级（能处置到哪一层）· 当前处置规则（dryRun / action / matchMode / 正则 / 理由）·
日志频道 · 本次运行统计 · **最近一次命中记录** · 白名单角色 · 白名单用户 · **体检提醒**
（比如"没配日志频道""白名单为空""dryRun 还开着""角色位置不够高"，直接列出来提醒你）。

**只有白名单里的人能用**（`whitelistUserIds` / `whitelistRoleIds` 两条通道）。
服务器拥有者、有「管理服务器」权限的人**都不例外** —— 冒充者也在同一个服务器里，
用权限位判定对他们可能意外为真，所以只用名单说话。

⚠️ **不在白名单的任何人私信机器人：完全静默。**
一个字都不回，连"无权限"都不回，连「正在输入…」都不会出现。
理由：冒充者私信时，任何形式的回复都是在给他反馈
（等于告诉他"机器人是活的""我这个号还没被标记"）。
探测尝试只写进服务器 journal（同一人 10 分钟只记一次），Discord 里**不留任何痕迹**。

报告**绝不含 token**。

> **为什么不需要开 MESSAGE CONTENT INTENT？**
> Discord 官方文档明确：私信、@提及、机器人自己发的消息这三种情况**永远可读**。
> 所以只需声明**非特权**的 `DirectMessages` intent + `Partials.Channel`。
> ⚠️ 千万别顺手加特权的 `MessageContent` —— 后台没开它，声明了会以 `4014 disallowed intents` 断连。
>
> 另外这个功能在私信里**不检查内容**（任何一条私信都触发回报），
> 所以即使将来豁免策略有变，也只会"读不到文字"，不会"收不到事件"。

---

## 4. 白名单怎么用最省事

**推荐做法：只加角色，不加人。**

1. 建一个角色 `MMOEXP Staff`（紫色，显眼）。
2. 把它加进 `whitelistRoleIds`（或 `/guard-whitelist action:add type:role id:...`）。
3. 以后招新客服 → 直接发这个角色给他，**不用改任何配置**。
4. 客服离职 → 收回角色，立刻恢复被防护状态。

同时这个角色就是给玩家看的"官方身份标识"，配合 `规则公告_中英.txt` 一起发到 #公告，玩家一眼就能分辨真假客服。

### 4.1 官方管理组（Admin）永不被处理 —— 硬保护

除了白名单，代码里还有一道**与白名单无关**的硬保护：

> 任何成员，只要他身上的某个角色带 **`Administrator` 权限**，就一律**不看名字、不计命中、不处置**。

这条独立于白名单 —— 即使有人把 `Admin` 从白名单里删掉、或者把机器人角色拖到 `Admin` 之上，
依然拦得住。（`handle()` / `canActOn()` / `guard-purge` 扫描循环三处都加了这道闸。）

本服实测带该权限的角色：

| 角色 | 位置 | 人类成员持有 |
|---|---|---|
| `Admin` | 36 | 7 人 |
| `MMOEXP_Official_Player` | 35 | 5 人 |
| `MEE6` / `Bot` / `MMOEXP_BOT` / `Query_Invite_Member` | 33 / 34 / 1 / 2 | **0 人**（都是机器人或服务角色） |

> 这里特地核过一次：`Query_Invite_Member` 这种"邀请追踪"角色**也是 0 个人类持有**。
> 这点很关键 —— 如果它被自动发给每个新成员，那"带 Administrator 权限就保护"的规则
> 就等于把守卫整体架空。实测没有这个问题，所以这条规则在本服是安全的。

所以一个成员要被处置，必须**同时**满足四条：
① 名字命中规则　② 不在白名单（人 / 角色）　③ 角色不带 `Administrator` 权限
　④ 最高角色位置**低于机器人**（本服机器人位置 = 34）。

---

## 5. 常见问题

**Q：会不会误伤正常客户？**
strict 模式下，只有名字**以品牌词开头**且后面接的是分隔符/数字/官方类后缀才会命中。`mmoexpert`、`mmoexpo` 这类不会被踢。若你希望宁可错杀，把 `matchMode` 改成 `"loose"`。

**Q：骗子进来先取个正常名字，之后再改成 MMOEXP 怎么办？**
机器人监听了昵称、全局显示名、用户名的变更事件，**改名后会被再抓一次**。

**Q：为什么原生 AutoMod 做不到？**
Discord 官方限制：AutoMod 的资料名规则只能"阻止互动/要求改名 + 发警报"，**没有踢人/封禁能力**。所以必须上机器人。

**Q：机器人离线了怎么办？**
离线期间新加入的冒充者不会被秒踢（AutoMod 的第①层仍会拦发言）。所以建议部署到你的云服务器并配 `Restart=always`，或者本机开机自启。

**Q：机器人踢不动人？**
99% 是角色层级问题：`服务器设置 → 角色`，把 `MMOEXP Guard` 拖到你要踢的那些角色**上面**。机器人踢不掉服务器主和管理员。

**Q：能不能顺便封禁而不是踢出？**
`config.json` 里 `"action": "ban"`。封禁能防止骗子反复重新加入（踢出后他们可以马上再进来）。

---

## 6. 文件清单

| 文件 | 说明 |
|---|---|
| `index.js` | 机器人的全部逻辑（加入即检、改名复检、扫描清理、斜杠命令、**状态自检**） |
| `config.json` | ★ 你要改的就这一个文件（token / 服务器ID / 动作 / dryRun / 白名单 / 日志频道） |
| `whitelist.json` | 白名单数据（也可用 `/guard-whitelist` 在线维护） |
| `start.bat` | Windows 一键启动（自动装依赖） |
| `mmoexp-guardbot.service` | Linux systemd 常驻服务文件 |
| `规则公告_中英.txt` | 发到 #公告 的防冒充公告（中英双语，直接贴） |
| `_test_match.js` | 名称判定自检（37 用例） |
| `_test_selfcheck.js` | 状态自检单测（76 项：报告内容、不泄露 token、**门禁只认白名单**、Admin 硬保护、落盘、dryRun 硬闸） |
| `_test_selfcheck_integration.js` | 事件接线集成测试（27 项：投递合成 `messageCreate`，验证非白名单**零回复零信号**、白名单正常回报） |
| `_ops_set_dryrun.py` | 开关 dryRun 的运维脚本（幂等，自动备份，跑完打印复核结果） |
| `_ops_preflight_scan.cjs` | **上线前体检**：全量成员过一遍规则 + 统计"带 Administrator 权限的角色各被多少人持有"，输出会被处置 / 白名单豁免 / 硬保护跳过三张名单 |
| `_ops_list_channels.cjs` | 列出文本频道，挑 `logChannelId` 候选 |
| `部署记录_服务器.md` | 服务器部署记录 + 排查记录 + 回滚步骤 |
| `README.md` | 本文件 |


## 2026-11-10：Official Club公开欢迎

public-welcome.js由index.js在登录前接入，仅处理Official Club的新成员加入。在welcome-config.json指定的欢迎频道公开欢迎，并提供原游戏身份组菜单、规则和客服链接；不发送私信、不自动授予身份组、不处理其他服务器。保留既有防冒充规则，命中且非白名单的新成员不欢迎。按成员ID和入群时间先登记发送预占，重复事件/重启不重复欢迎，未知发送结果不自动重发。welcome-state/包含运行时面板和投递账本，必须保留且不入Git。

验证：node test-public-welcome.cjs。79项品牌规则与27项状态自检事件测试在活动服务器源码的隔离副本通过；历史_test_match/_test_selfcheck在未改基线也分别失败4/5项，不作为本次新回归。生产守卫源码含既有未回填变更，本PR仅添加欢迎接线及独立模块，不以仓库旧整包覆盖生产。

回滚：恢复本批部署前index.js并重启mmoexp-guardbot，保留全部配置/原账本/welcome-state及已发消息。正式备份：/opt/mmoexp-guardbot/backups/public-welcome-20261110/index.js。


### 欢迎卡与紧凑游戏选择

欢迎卡使用橙色Embed和表情分段，只保留Choose Roles与Contact Support。游戏角色采用13项多选下拉菜单（FC27、D4、POE2、WoW、ARC、MLB、COD、GTA、AION2、NBA、Dark and Darker、MapleStory Classic World、Other Games），统一图标和简短说明；先预览，点击Save Games才应用。菜单仅本人可见，旧成员历史角色不批量迁移，MapleStory使用已有普通角色。国家／地区仅方案，未部署角色或入口。

角色保存只处理目录中的普通0权限角色，校验本人、服务器、欢迎频道、Bot层级及频道覆写；保留其他身份组和历史别名，接口结果不明时先读回确认。旧按钮给出刷新提示；My Game Channels已移除，历史欢迎卡已同步为两个入口。

验证：公开欢迎测试与36项菜单/权限边界检查通过，真实Discord菜单13项、现有角色默认选中、仅本人可见及Save Games已核；未替真实成员保存。生产index/config.json/d4-guard.json/welcome-config.json保持。恢复备份三个模块/目录文件并重启可回退；备份/opt/mmoexp-guardbot/backups/role-compact-20261110，保留账本、消息和成员后续自选角色。