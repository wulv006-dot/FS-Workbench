# FC27 欢迎与提醒偏好上线记录

2026-11-08，用户授权执行频道入口优化，并明确保留热门俱乐部直接按钮。本记录仅覆盖欢迎卡与提醒偏好模块，不将其他协作者正在进行的频道排序、EasySBC 提醒绑定或总群引流算为已完成。

## 已上线

- 主欢迎卡：Latest news / Daily content / Check prices / Join FC27。FC27 基础身份可独立领取，不强制选球队。
- 热门俱乐部卡：Man City、Real Madrid、Barcelona、Bayern、PSG 直接按钮；More clubs 私密展开原有两组完整 47 支球队。
- 原第三条球队消息改成 Set alerts 入口；用户私密选择 SBC、Evolutions、Objectives & Rush、News、Giveaways，也可全部关闭。
- 原 3 条欢迎消息 ID 保留；旧球队按钮处理器继续注册。角色仍只修改配置中的零权限身份组。

## 验证证据

- 本地与 187 隔离环境各通过 38 项相关测试：onboarding、club、integration、content、alert。
- 测试群预览消息：`1568690604739788912`（主卡）、`1568690606253940807`（热门球队）。预览控件全部禁用，未向测试用户分配正式群角色。
- 正式欢迎频道 `1568663362567413820` 的消息原位更新，并经 REST 读取核对机器人作者、标题及控件数量：
  - 主卡 `1568666884289732751`，4 个入口。
  - 热门球队 `1568666885321400411`，6 个入口。
  - 提醒偏好 `1568666886558982145`，1 个入口。
- 社区服务新 PID `24563`，ready 文件 connected=true、test_guild_present=true 且 PID 一致。
- `mmoexp-fc-community`、`bot-console`、`mmoexp-fc-quotes` 均 active；仅重启社区服务。
- 本记录不声称已通过真人账号端到端点击。真人点击与 EasySBC 角色绑定由总控另行验收。

## 提醒身份组

| 用途 | 名称 | ID |
| --- | --- | --- |
| SBC | FC27 Alerts · SBC | 1568690687694606446 |
| 进化 | FC27 Alerts · Evolutions | 1568690688789319746 |
| OBJ / Rush | FC27 Alerts · Objectives & Rush | 1568690690160988353 |
| 新闻 | FC27 Alerts · News | 1568690690903244832 |
| 抽奖 | FC27 Alerts · Giveaways | 1568690692769714397 |

初次创建时全部角色 permissions=0、hoist=false、mentionable=false、managed=false，排序严格低于自有机器人。随后实际 EasySBC `/alerts-subscribe` 明确要求 Mention All 权限或角色可提及，因此只将这五个通知角色改为 **mentionable=true**，未授予 EasySBC Mention Everyone，也未改变任一角色权限位。

这是全服务器的角色属性：管理员／运营在其他可发言频道也可提及；普通玩家在其他允许发言的频道同样可能提及这些角色，并非只限 staff。资讯频道保持只读，玩家不能在那里发消息。若出现跨频道滥用，应由现有管理或 AutoMod 规则处理；此次未新增全群权限或自动封禁规则。

变更脚本 `ops/enable_alert_mentions.py` 限定以上五个 ID 和准确名称，先检查零权限、非 managed／hoist，备份后逐个 PATCH 并 GET 回读。前值备份 `/opt/mmoexp-fc-news-stage-20261108-core/community-ux/alert-mentions-before.json`，结果 `alert-mentions-result.json`。没有向任何玩家自动订阅，没有发送实际提醒。仅创建与管理偏好不代表 EasySBC 已开始艾特这些身份组；其订阅绑定是单独配置步骤。普通新闻继续安静发布。

## 发布范围与恢复

- Stage：`/opt/mmoexp-fc-news-stage-20261108-core/community-ux`。
- 备份：`/opt/mmoexp-fc-community/backups/community-ux-1794075406`。
- 更新文件：`club_panel.py`、`content_bot.py`；新增 `onboarding_panel.py`、`alert_panel.py`。
- 配置只增加 `alert_preferences`，允许 FC welcome、7 个资讯／报价频道及总 welcome 触发提醒偏好。未修改其他配置键、新闻数据库、报价记录或欢迎消息 marker。
- Stage `channels-before.json` 记录上述频道元数据；本发布脚本未更改频道权限。
- 发布脚本：`ops/deploy_community_ux.py`，先校验生产和候选 SHA256、备份，再原子替换；失败自动恢复文件与配置并重启原服务。成功回执存在时拒绝重复部署。
- 如需人工回退，先确认文件未被后续发布改动，恢复备份里的两个原文件与 config，移除本次新增的两个模块，再重启社区服务。消息将在旧 setup 中恢复；不要删除新角色或已存在的用户偏好作为隐式回退动作。

本地回执：`var/community-ux-deployment-20261108.json`、`var/community-ux-preview-20261108.json`。详细发布哈希以 deployment 回执为准。

## 总控后续真实入口验收

同日，使用已登录 Discord 账号完成 Set alerts → 选择 SBC → Save，收到保存成功回执；随后 All off 收到关闭成功回执。More clubs → English football clubs 正常展开 25 个球队按钮，交互面板仅本人可见。

EasySBC 的 SBC、Evolutions、Objectives、Rush 提醒已分别绑定对应通知身份组，Objectives 与 Rush 共用同一角色。绑定成功不等于已观察到下一次自然内容更新。普通新闻继续静默发布；News 和 Giveaways 角色供运营对重点内容手动提醒，不将全部新闻或报价卡自动重复艾特。
