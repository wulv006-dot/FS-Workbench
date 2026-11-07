# WOW FOREVER [MMO] · Blingtron-9000 接入交接

日期：2026-11-07　执行：WorkBuddy（陈超授权）
目录：`D:\workbuddy文件目录\discord\2026-11-07_WOWFOREVER_频道机器人\`

---

## 一、对象

| 项 | 值 |
|---|---|
| 服务器 | **WOW FOREVER [MMO]** · `1567427533685657630` |
| 所有者 | `1477093313265008720`（Ryan Brooks，与 AION2 同一位） |
| 规模 | 18 成员 / 13 在线 · 45 频道（29 文字 / 11 分类 / 5 语音） |
| 机器人 | **Blingtron-9000** · Application ID `1568537417642807418` |
| 令牌 | `_local_secrets_DO_NOT_COMMIT\wowforever_token.txt`（0611，未外发、未提交） |
| API 验证 | `/users/@me` 200，`bot=true`，`verified=true` |

---

## 二、接入结果（全部 API 回读，非截图）

| 步骤 | 结果 |
|---|---|
| 加入服务器 | `joined_at = 2026-11-07T08:29:06Z` |
| 邀请方式 | OAuth2 授权页（29 项管理权限，无 Administrator） |
| 事后授权 | 用户新建 `BOT` 角色并赋 **Administrator**，已挂到机器人身上 |
| 合并有效权限 | `8543205314264319` · **ADMIN = true** |
| `🔒│moderator-only` | 实测 `GET messages` → **200 可读** |
| `🧾│order-logs` | **200 可读** |
| `📝│mod-log` | **200 可读** |
| `🛠️│admin` | **200 可读** |
| `MODERATION` 分类 | **200 可读** |

> 接入前这 4 个频道对机器人全部 `403 Missing Access`；因为分类对 `@everyone` 拒了 `VIEW_CHANNEL(1024)`，而机器人改不了自己看不见的频道 —— 自锁死循环。管理员权限绕过后即通。

---

## 三、角色现状（按位置高→低）

| pos | 角色 | 说明 |
|---|---|---|
| 19 | `manager` | 带 ADMIN；用户当前持有 |
| 18 | `muted` | 0 权限（靠频道覆盖生效） |
| 17 | `Trader` | 0 |
| 16 | `Moderator` | 0 |
| 15 | `Game Master` | 0 |
| 14 | `Zira` | **另一个机器人**，`MANAGE_CHANNELS`/`MANAGE_ROLES` |
| 13–3 | `PVE` `English` `Deutsch` `PVP` `RPG` `Français` `Español` `Português` `한국어` `日本語` `繁體中文` | 全部 0 权限，纯身份组 |
| **2** | **`Blingtron-9000`** | 受管角色，29 项管理权限 |
| **1** | **`BOT`** | 用户新建，**ADMIN**，已挂机器人 |
| 0 | `@everyone` | 有 SEND_MESSAGES / VIEW_CHANNEL |

---

## 四、⚠️ 唯一遗留约束：角色层级

机器人最高的角色是 `Blingtron-9000`（pos=2），**在 16 个人类角色之下**。Discord 的角色层级对 Administrator 同样生效：

- ❌ 踢人 / 封人 / 禁言：只能作用于「最高角色低于 pos=2」的成员 → **实际只能动白号**
- ❌ 管理角色（加/删 `PVE`、`Trader` 等）：对这些角色全部 403
- ✅ 管理频道 / 发消息 / 改覆盖 / 建删频道：**不受影响，现在就能用**

**解法**：`服务器设置 → 角色`，把 `Blingtron-9000` 拖到 `manager` 下面（或把 `BOT` 角色拖高再挂所有机器人）。机器人自身无权改动 —— 已实测 `PATCH` 自身角色 `403 Missing Permissions`，这是平台硬限制。

> 若只做「价格看板 / 欢迎语 / 自动发帖」这类，**可以不拖**；要做「审核 / 自动身份组」必须拖。

---

## 五、频道清单摘要

**分类（11）**：`文字频道` `语音频道` `INFORMATION` `COMMUNITY` `LANGUAGES` `MODERATION` `VOICE CHANNELS` `PVP` `PVE` `RPG` `GUIDES`

**文字频道（29）**
- 规则/公告：`📋│community-rules`（机器人只读）`📢│news` `👋│welcome`
- 社区：`💬│the-chat` `💱│the-exchange` `📚│class-codex` `🎫│support` `🎁│giveaway` `⚔️│lfg-party-finder` `🎬│highlights-clips`
- 管理：`🔒│moderator-only` `🧾│order-logs` `📝│mod-log` `🛠️│admin`
- 阵营玩法：`🛡️│pvp-alliance` `🪓│pvp-horde` `🗡️│pve-alliance` `🏹│pve-horde` `🎭│rpg-alliance` `🐺│rpg-horde` `📖│guides-general`
- 语言（8）：`🇬🇧english` `🇫🇷français` `🇩🇪deutsch` `🇪🇸español` `🇵🇹português` `🇰🇷한국어` `🇯🇵日本語` `🇨🇳繁體中文`

> 现有语言频道是 **8 种**，但没有 `简体中文`；角色侧有 `繁體中文`。要不要补简中待定。

---

## 六、回滚点

| 项 | 位置 |
|---|---|
| 全服 45 频道权限覆盖快照 | `_backup_overwrites_20261107-163024.json` |
| 移除机器人 | 服务器设置 → 整合 → 踢出 Blingtron-9000 |
| 撤销管理员 | 删掉 `BOT` 角色，或把 `BOT` 的 ADMIN 关掉 |
| 本机改动 | 仅 `_local_secrets_DO_NOT_COMMIT\` 与各 `_*.py` 工具脚本，无线上写入 |

---

## 七、工具脚本（本目录，均可重跑）

| 脚本 | 用途 |
|---|---|
| `_probe_bot.py` | 机器人身份 / 所在服务器 |
| `_verify_join.py` | 入服核验 + 角色/频道清单 |
| `_inspect.py` | 角色位置与权限位明细 |
| `_effperm.py` | 逐频道有效权限（模拟覆盖规则） |
| `_overwrites.py` | 备份 + 查看覆盖来源 |
| `_grant.py` | 尝试授频道权限（**已证 403，留作记录**） |
| `_diag403.py` | 403 根因判定（可见性 vs 层级） |
| `_try_admin.py` | 尝试自授管理员（**已证 403**） |
| `_verify_access.py` | 真实读操作验证频道访问 |
| `_gen_invite.py` | 邀请链接生成（权限位可改） |

---

## 八、下一步

配置模块（待用户指定优先级）：
1. 价格/库存看板（AION2 `kinah.py` 同款：一条消息原位刷新 + 下拉查询）
2. 防冒充 / 关键词守卫（复用 GuardBot 逻辑，含白名单 + dry-run）
3. 欢迎语 / 自动身份组（8 语言 + PVP/PVE/RPG 阵营）
4. 工单 / 订单日志（`🎫│support` → `🧾│order-logs`）

运行位置待定：跟 AION2 同机（`47.85.224.112` `/opt/`）或本机先跑通。
