# Smart Score 每日赛程卡桌面触发

## 运行链路

1. 187 的 `fc27-matchday-scout.timer` 每日 18:00（服务器本地时间）运行 Hermes，最多提名两场，也可以零场；结果写入 `/opt/mmoexp-fc-community/var/matchday-scout-latest.json`。
2. Windows 登录会话中的 `smartscore_upcoming_cdp.mjs` 在 18:05 只读取得这份提名。它通过已登录的 Discord 桌面界面，以频道管理员身份对 Smart Score 执行 `/live upcoming within_hours:48 team:<主队>`，每支主队最多执行一次。
3. Smart Score 自己在 `fc27-matchday` 发公开赛程卡。现有 `matchday_scout_bridge.py` 只在球队、日期与提名相符时把卡片加入 FC Assistant 赛事计划。空提名不会触发命令。

源脚本：`opt/mmoexp-fc-community/ops/smartscore_upcoming_cdp.mjs`。它依赖本机 `D:/Deepseek Harness/discord-cdp` 已有的 CDP 客户端；不会读取 Discord 用户令牌或直接调用用户私有 API。运行时必须保持 Discord 桌面应用已登录、CDP 端口可用、187 SSH 可用。脚本会检查频道、已有草稿、命令和回执；无法确认发出结果时记录 `unknown` 并停止，不自动重发。每场比赛以日期和双方球队去重。它可能短暂切换桌面 Discord 频道，结束后恢复。

## 测试回执（2026-11-15）

- D4 VIP `fc27-bot-test`：带 48 小时范围的 Germany 查询由 Smart Score 返回 [Germany vs Netherlands 卡](https://discord.com/channels/1565922092518613064/1568260661010497627/1571344936085880933)。未填 48 小时的早期试验返回 `No upcoming matches`，证明时间范围不可省略。
- Spain 的测试卡为 [Spain vs England](https://discord.com/channels/1565922092518613064/1568260661010497627/1571344116741312554)。首版回执识别曾误选历史消息，现已增加发送时间、当前管理员与 Smart Score 双身份检查。
- 正式 `fc27-matchday` 已有 Spain 和 Germany 的 Smart Score 卡及 FC Assistant 讨论卡，因此未为验证重复发布同一比赛。首次自动触发从 2026-11-16 18:05 北京时间起。

## 本机运行与维护

Windows 计划任务名 `MMOEXP FC27 Smart Score Upcoming`，以当前已登录的 Administrator 交互会话运行。运行源为此脚本在 `D:/Deepseek Harness/discord-cdp/` 的部署副本。更新 Git 源脚本后须重新同步该副本；先在 D4 VIP 测试，再替换生产副本。计划任务的标准输出、错误输出应由启动包装器保存到本机 `state` 目录，不保存玩家消息正文。

手动只读预演：`node smartscore_upcoming_cdp.mjs --target official`。手动执行：`node smartscore_upcoming_cdp.mjs --target official --send --navigate`。测试群执行时将 `official` 改为 `test`。本机 `state/smartscore-upcoming-official.json` 是去重与未知结果记录；出现 `unknown` 时先按频道和消息 ID 核对，不删除状态盲重发。

此路径是基于管理员账号的桌面 UI 自动化，依赖 Discord 界面稳定和登录态。它与 Discord 公布的自动化用户账号政策存在账号风险；如 Smart Score 提供官方机器人接口或定时发布能力，应优先迁移到该能力。桌面未登录、CDP 不可用或 187 提名过期时任务停止，赛事频道继续保留 Smart Score 原生卡与现有 FC Assistant 卡。
