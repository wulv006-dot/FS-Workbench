# MMOEXP Start Here 多游戏入口

用户要求保留全群其他游戏入口，同时为 FC27 提供清晰引流。发布目标为官方群 `1041923524601851914` 的新频道 `1568693175877501192`（`👋▸start-here`），不是旧 `welcome` 消息流。

## 消息设计

一条消息包含两张嵌入卡：

1. **Welcome to MMOEXP / Choose your game**：全群中性简介。
2. **Your FUT club starts here.**：MMOEXP FC27 品牌横幅，三行介绍每日更新、私密实时报价、球队身份与提醒。

按钮分三行：Enter FC27 Club；Diablo IV / Path of Exile / GTA；Madden / NFL / MLB / ARC Raiders。所有按钮是 Discord 频道链接，无自动身份组分配、无个人信息收集、无艾特。

| 按钮 | 已核实目标频道 |
| --- | --- |
| Enter FC27 Club | `1568663362567413820` FC welcome |
| Diablo IV | `1232493719412801556` d4-chat |
| Path of Exile | `1305793388599054400` poe-chat |
| GTA | `1470604129834500261` gta-news |
| Madden / NFL | `1518795532598907041` nfl-chat |
| MLB | `1395564367713665054` mlb-chat |
| ARC Raiders | `1453656593081303133` arc-faq |

上述目的频道已通过 REST 核对 `@everyone` 可见且没有 View Channel deny；不保证用户无需其他角色便能发言。D4、POE、NFL、MLB chat 的 `@everyone` Send Messages 为 false，所以文案仅引导“进入”，不承诺新人直接聊天。未改这些目的频道的权限。

## 发布与维护

脚本 `ops/publish_fc_gateway.py` 默认仅输出 payload；`--apply` 才发布。校验准确 guild、频道 ID 和 `start-here` 名称。只有该机器人创建的消息能被后续更新。

服务器 marker：`/opt/mmoexp-fc-community/var/general-fc-gateway.json`。首次发送前持久化 sending，成功保存 message ID。未知回执不自动重发；已有 published 记录则原位编辑。marker 若属于另一个频道须先人工核对，不向新频道盲目重发。回读确认两张 embed 的标题、机器人作者和全部按钮 URL。

## 正式发布回执

2026-11-08 已完成本地编译检查、服务器 dry-run，并在总控通过 UI 保存权限后 GET 核对：

- `@everyone` 明确允许 View Channel / Read Message History；禁止 Send Messages、创建公开／私密 thread、thread 内发言、Use External Apps。
- 自有机器人角色仅显式允许 Send Messages、Embed Links、Attach Files、Read Message History；明确禁止频道管理、角色／权限管理、Webhook、邀请、消息管理、Mention Everyone、thread 管理／创建／发言、External Apps、置顶。频道继承 `@everyone` 的可见权限。
- 频道没有分类 parent。未修改六个其他游戏目标频道的权限。

随后执行一次 `--apply`，消息 **`1568694128445759571`** 发布成功，REST 回读验证作者、两张 embed 标题及全部七个频道链接一致。

正式入口：[MMOEXP Start Here](https://discord.com/channels/1041923524601851914/1568693175877501192/1568694128445759571)。本条无艾特、无用户订阅或自动身份分配；FC 用户继续点击 Enter FC27 Club 到专区选择球队和提醒。

随后通过 Discord 原生新手教程设置，将 Start Here 加入默认频道。预览总频道数从 42 变为 43，仅新增此频道；保存后未保存提示消失。其余默认游戏频道和配置保留，自有品牌面板作为主要引导入口。
