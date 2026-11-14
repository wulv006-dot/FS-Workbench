# FC27 真实足球赛事：数据源、社区玩法与游戏联动

状态：设计与来源核对完成；赛事 API 尚未接入、没有上线真实比分或预测。2026-11-14 核对的 MMOEXP Official Club 现有赛事频道为 `📅・fc27-matchday`（1571043454136484082）和 `🗣️・fc27-match-chat`（1571043570268242014）。Madden 的 `🏈events` 当前为空；可参考的实际内容在 `madden27-news`：菜单卡、每日简报与终场卡。FC Chat Assistant 线上独立服务已启用，当前每天 20:00 Asia/Shanghai 对测试和官方群的 **FC 游戏聊天频道**各推一条通用随机话题，尚未读取赛程或向赛事聊天频道发帖。

## 推荐的玩家流程

1. 在 FC27 Welcome 选球队；同时得到 FC27 + 球队身份。任何成员仍可公开阅读赛事，不强制选身份。
2. `📅・fc27-matchday` 每天保留一张“今日焦点赛”索引卡；点击 **My club** 私密显示所选球队接下来 7 天赛事，点击单场卡看完整信息。
3. 赛前独立卡提供本地时间、比赛来源、**Follow match**、**Predict 1X2**、**Discuss**、**FC27 players**。不自动 @ 47 个球队身份组；只有主动关注者接收提醒。
4. 比赛开始后编辑原卡更新比分、状态及关键事件；平常比分变化不另发新消息。进球、红牌等最多进入该场讨论串，避免公共频道刷屏。
5. `🗣️・fc27-match-chat` 是玩家讨论区。FC Chat Assistant 在赛前、半场、赛后发有来源的提问，并在非比赛日发一条球队/FC27 组合话题；机器人参与回复但不占满聊天。
6. 终场卡提供 **Vote MVP**、**See related FC27 players** 与 **View predictions**。球员入口仅链接已在 FS 球员模型库中确切映射的产品；实际价格仍由现有私密报价卡实时读取。

### 卡片示意（字段结构，非真实赛事实况）

> ⚽ **Real Madrid vs Man City** · Champions League
> 🕒 `<t:UNIX:F>` · 自动按玩家本机时区显示
> 📍 Scheduled / Live 67′ / Full Time · 比分随状态变化
> 🔎 Source: OpenLigaDB / ESPN · checked `<t:UNIX:R>`
> **My club**　**Follow**　**Predict**　**Discuss**　**FC27 players**

只在有来源的情况下填写比分、首发、进球者和比赛状态；缺失时省略或标为“Awaiting update”。不把真实比赛结果描述成 FC27 游戏活动、TOTW 确认名单或官方球员卡发行。

## 数据源选择

| 来源 | 可用范围与当前核验 | 用途与结论 |
| --- | --- | --- |
| [API-Football 官方文档](https://www.api-football.com/documentation_v3)、[套餐](https://www.api-football.com/pricing)、[2026 免费赛季说明](https://www.api-football.com/news/post/how-to-get-all-data-from-a-league-with-api-football) | 赛程、`fixtures?live=all`、比赛事件、球队与积分；免费档 100 次/日，但 2026 年仅开放 2022–2024 等旧赛季 | **当前赛季直播首选候选**：免费账号只能验证旧赛季接口与卡片流程；当前赛季要由用户确认账号可用套餐，官方 Pro 页面标价 $19/月、7,500 次/日。上线前逐联赛核对赛事、事件覆盖。凭据只存服务端。 |
| [football-data.org 官方 API](https://docs.football-data.org/general/v4/match.html)、[覆盖](https://www.football-data.org/coverage)、[套餐](https://www.football-data.org/pricing) | 免费 12 项赛事，赛程/积分榜，比分有延迟；€12/月档仅直播比分，€29/月 Free + Deep Data 档才列明进球者、红黄牌与首发 | 适合赛程与延时结果的备选。仅比分直播可考虑 €12 档；关键事件卡要确认 €29 档与目标赛事覆盖。跨源赛事 ID 不能按球队名字直接合并。 |
| ESPN 的网页 JSON 端点 | 2026-11-14 验证当前赛季英超、西甲、德甲、法甲及欧冠赛程、比分和进球字段。用户确认已取得 ESPN 负责人免费使用授权，书面函件预计周一补充 | 作为 **OpenLigaDB 备用源** 开发适配器。187 已启用每 6 小时隔离只读采集，首次服务运行成功；尚未接 Discord 发布。自定义请求标识触发 403，去掉后返回 200，详见[试验记录](ESPN-TRIAL-20261114.md)。 |
| [OpenLigaDB API](https://api.openligadb.de/index.html)、[使用条款](https://www.openligadb.de/en/terms-of-use)、[数据许可](https://www.openligadb.de/en/license) | 无需注册或付费，ODbL 允许商业使用且需署名。2026-11-14 实测 2026/27 英超 `pl`、西甲 `la1`、德甲 `bl1`、欧冠 `ucl` 有赛程和部分进球数据；无同季法甲。数据由社区录入，可能延迟、缺漏或更正 | **主源**。先做只读测试和逐场覆盖验证；直播卡明示来源与核对时间。关键事件须经过稳定窗口，不把它用于自动发券结算。 |
| [SportScore API](https://sportscore.com/developers/)、[使用条款](https://sportscore.com/developers/terms/) | 无需 key，API 返回比赛比分与 `incidents`；免费层要求可见的 `Powered by SportScore` 链接，条款列明“早期商业项目”，大型既有 MMOEXP 项目是否符合须先获提供方确认 | 可作为法甲及更广赛事的候选；未获适用范围确认前不接正式群。 |
| [TheSportsDB 官方 API](https://www.thesportsdb.com/API.php)、[条款](https://www.thesportsdb.com/docs_terms_of_use.php) | 免费 v1 适合开发与基础赛程；2 分钟比分在付费层；素材另有版权要求 | 可用于无凭据原型验证；不把免费层承诺为实时方案。 |

免费 API-Football 账号用于旧赛季重放、字段校验与联调，**不用于当前赛季直播承诺**。生产实时比赛按实际套餐、联赛覆盖和事件可用性定预算：仅在精选比赛窗口每约 1 分钟查询直播总览，关键事件详情按状态变化查询；读取剩余额度并自适应退避。比赛卡始终展示最后核对时间。付费订阅须由用户自行决定，不由机器人擅自升级。

球队徽标、球员照片、赛事图像不因 API 可读便自动取得再分发权。首版使用 MMOEXP 自有视觉、文字简称、现有经授权的球队身份图标和来源链接。[football-data.org 条款](https://www.football-data.org/client/register)明确提醒队徽等图像版权另属权利人。

## 值得借鉴的产品与代码

| 案例 | 借鉴点 | 复用边界 |
| --- | --- | --- |
| 我们自己的 Madden 27 News / MMOEXP 🏈Club | 导航菜单、日简报、赛事结果卡与商品入口分层；赛事资讯放 News，而 `🏈events` 尚为空 | 参考交互信息层级；FC 游戏新闻与真实足球赛事仍分两个频道。 |
| [Scoring Returns Bot](https://github.com/BernKing/Scoring-Returns-Bot) | 进球、VAR、红黄牌、半场、终场状态机；支持多场跟踪 | MIT 可研究实现片段，但依赖/外部 API 与我们现有 discord.py 服务需独立评估。 |
| [RadarBot](https://github.com/ericperinn/RadarBot/blob/main/README.md) | 球队自动补全、赛前提醒、终场提醒，以及 `(subscription, match, kind)` 去重 | 当前未核实许可证，只借鉴行为；我们已由 Welcome 身份确定球队，无需玩家重复输入 `/follow`。 |
| [TyperBot](https://github.com/adrunkhuman/TyperBot) | 预测截止、赛季积分榜、管理面板与赛事讨论串 | MIT 可研究数据结构；我们首版用按钮私密投票，不把预测公开刷屏。 |
| [matchday-bot](https://github.com/thiagoloumart/matchday-bot) | 随比赛阶段变化的“球迷口吻”、晨报和故障时提醒运营 | 借鉴文案和节奏；其 ESPN 接入是非官方路径，许可证未核实，不直接复制代码。 |
| [Discord Scheduled Events](https://support.discord.com/hc/en-us/articles/4409494125719-Scheduled-Events) | 焦点赛事可有原生“感兴趣/提醒”入口 | 只给人工/运营选中的重点赛创建，避免批量活动刷版面。 |

## FC27 游戏联动：把内容变成互动，而不是硬促单

### 1. 真实比赛 × 我的 FC27 球员

- `My club` 读取已选球队身份；球队到数据供应商 Team ID 用显式维护表，支持赛季变更。
- `FC27 players` 根据球队 ID → FS 球员模型库的明确映射，展示相关 FC27 球员卡、版本、标签与 **现有私密实时报价入口**。没有商品映射就只显示赛事信息，不按同名球员猜测商品。
- “本场你会选谁进 FC27 阵容？”等讨论题允许链接到球员比较与精选名单。真实比赛表现和游戏卡数值只作为讨论主题，不宣称会自动加点或发新卡。

### 2. 俱乐部对抗与轻预测

- 重点赛提前 24 小时开 1X2 免费预测；球迷点击后仅本人可见地提交或修改，开赛锁定。公开卡只展示总票数/分布；显示球队身份的支持率，但不暴露具体玩家预测。
- 赛后生成“本周球迷判断榜”和连胜徽章，先用纯积分。优惠券必须另接 FS 现有发券/核销规则、每人限领、结果更正与预算上限；上线前不能承诺奖励。
- 可做 “Club Clash” 周榜：不同球队身份的预测准确率与参与度。低样本门槛下不排名，避免一票 100% 抢榜。

### 3. 内容驱动的游戏挑战

- 赛前：`Build the XI`——球迷讨论用相关球队球员组成 FC27 阵容，按钮跳 `Players` 与 `Squad reviews`。
- 半场：`Manager's move`——换人/阵型投票，进入 Match Chat 讨论串。无可用事件数据时只问主观战术问题。
- 赛后：`Fan MVP`——非官方球迷票选；由运营挑一个匹配的 FS 球员商品做精选展示，不以票选结果自动改价。
- 有明确 EA 游戏新闻关联时才增加“本周 FC27 内容”链接；赛事直播卡不直接挂金币购买按钮。游戏商品入口放私密面板，维持内容优先。

## FC Chat Assistant 改造点

线上独立 `mmoexp-fc-chat.service` 运行 `chat_service.py`。`chat_schedule.py` 当前从通用随机话题池挑选一句；配置的 `topic_channels` 仅容两个频道，实际指向测试与官方群 FC 游戏聊天，各在 20:00 Asia/Shanghai 发帖。赛事频道未配置，现有服务不能不改代码就单独使用“赛前/半场/赛后”话题。

在**同一个 Chat Assistant 进程**新增 `match_topics` 配置，不再开第二个同令牌登录：

- `channel_id=1571043570268242014`；独立启用开关、每日最多 1 条常规话题与每场最多 3 条赛程触发话题；运营可手动暂停。
- 来源为赛事模块已验证的 fixture 快照：赛前 24 小时问胜负看法，半场问战术，终场问 MVP/FC27 阵容。只引用带 `fixture_id`、来源、抓取时间的事实；AI 可重写语气，不可编造比分、首发或伤停。无快照则用无事实依赖的话题模板或跳过。
- 贴子在 Match Chat，赛况卡留在只读 Matchday。机器人只在被 @、玩家回复或已配置关键词时继续对话；不对每条玩家聊天自动插话。
- 每个 `(fixture_id, phase, channel_id)` 只发一次，重启后可恢复；临近多场比赛只选一场最热门焦点赛，其他场次留在索引卡里。

## 技术与发布分层

```text
许可允许的赛事 API → 187 独立只读采集器 → fixture 快照/外部 ID/核对时间
  → FC Assistant：Matchday 索引卡、每场一张可编辑卡、私密按钮与预测账本
  → FC Chat Assistant：只读消费快照，在 Match Chat 发阶段话题并回答玩家
  → FS FC27 控制台：赛事源/球队映射/比赛精选/话题开关/预测活动/发布记录
```

187 负责调度和 Discord 发送；183 只在已有隔离采集能力与共享锁规则下作为可选只读备援。两台机器不同时向同一 Discord 卡写入。按供应商 fixture ID、比赛阶段、消息 ID 建发布账本；卡片编辑失败重试但不盲目新发。运营后台允许手动挑场、预览、暂停、纠错，显示 API 额度与上次成功抓取。所有消息用 Discord 时间戳让玩家看到本机时区。

## 施工顺序与真实验收

1. 本地已用 OpenLigaDB 与 ESPN 两个适配器验证赛程、比分和事件字段，9 项单元测试通过；187 已启用 ESPN 隔离定时采集及标准化快照，尚未接 Discord 发布器。主备映射和书面授权范围仍需核对。
2. 在 D4 VIP 测试群发“明日焦点赛”、一张模拟进行中赛事卡和一条 Match Chat 话题，验收按钮私密性、时间本地化、编辑原卡、数据断流和内容错配。
3. 正式群先只开赛程与终场卡，连续运行一轮真实比赛后再启用近实时状态更新；最后开放免费的 1X2 预测。优惠券接口与规则另行确认后上线。
4. 验收不仅看发送成功，还要核对真实比赛 ID、来源时间、Club 身份映射、重复消息数、Chat Assistant 每日话题数、用户按钮成功率与来源更新间隔。

**真实比分功能仍未上线**；两条频道和现有入口只是基础承载面。OpenLigaDB 无需用户申请 API。ESPN 的合作授权函及可能存在的正式 Partner API 文档待周一核对；在此之前只做隔离采集试验，不向正式群发布 ESPN 赛况。
