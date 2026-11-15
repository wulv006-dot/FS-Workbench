# Smart Score 测试群验收与 FC27 玩法边界（2026-11-14）

## 现场回执

测试群为 MMOEXP·D4 VIP，频道 `fc27-bot-test`。Smart Score 的直播订阅和竞猜仍只在测试群试用；Chat Assistant 的公开赛事话题路由已在测试后接通官方群。

| 功能 | 真实结果 |
| --- | --- |
| `/admin live-test` | 应用回复发送 9 条模拟推送；频道出现订阅开始、半场、下半场、黄牌、换人、两次进球、红牌和完场卡。样式清楚，但连续 9 条会刷屏。此命令是模拟，不能证明真实赛事实时延迟。 |
| `/live upcoming` | 默认返回跨地区的 10 场比赛，不适合作为 FC27 足球首页。`league` 输入 Premier League 时有多个同名选项；选择一项后返回未来指定时间无比赛，联赛消歧需要向开发者反馈。 |
| `/predict winner` | 选择 Manchester City vs Fulham 后，收到仅本人可见的主胜/平/客胜按钮卡；点击主胜后返回“胜负竞猜提交成功”。这验证了个人投票交互，但未验证赛后积分结算。 |
| `/admin auto-predict-list` | 测试群已有英超、西甲、德甲、法甲、意甲、欧冠、欧联、欧洲杯、世界杯 9 个联赛配置，模式 Both，开赛前 5 分钟锁定。配置存在不等于自然周期推送已验收。 |
| `/admin open-predict` | 对已核实的 11 月 24 日曼城 vs 那不勒斯欧冠赛事返回“Prediction event opened successfully”。目前只看到管理员私密回执，未看到公开竞猜卡，仍需核对玩家如何发现并进入投票。 |
| `/live subscriptions` | 23:00 测试频道显示无直播订阅，证明模拟命令没有留下持续订阅；23:27 才单独开启真实场次测试。 |
| `/admin live-watch` | 23:27 在测试频道订阅进行中的 Kosovo vs Israel；23:28 起收到真实公开事件，23:53 收到 0–0 完场卡并显示订阅自动结束。首条消息回放了此前事件，不能据此断言实时延迟；还需用进球发生时间与独立可信赛事实况逐项对照。 |
| FC Chat Assistant 联动 | 187 测试群灰度在 23:53 收到 Kosovo vs Israel **真实完场**后的复盘卡；随后 `/admin live-test` 模拟九条推送只引出半场和完场两张话题卡，黄牌、换人和连续进球没有重复刷卡。卡片提供 Smart Score 原消息、FC27 Players、Coins 三个跳转按钮；测试群的两个商品按钮暂指向测试频道，正式群上线时改成实际报价频道。 |
| Footy Live Bot `/today`、`/live` | 两个命令均显示“该应用程序未响应”；暂不作为正式赛事核心。 |

回执可从 [Smart Score 模拟直播](https://discord.com/channels/1565922092518613064/1568260661010497627/1571175904368136384)、[个人预测](https://discord.com/channels/1565922092518613064/1568260661010497627/1571177058565103668)、[真实完场与复盘卡](https://discord.com/channels/1565922092518613064/1568260661010497627/1571191367626006812)、[模拟半场话题](https://discord.com/channels/1565922092518613064/1568260661010497627/1571191405957877782) 与 [模拟完场话题](https://discord.com/channels/1565922092518613064/1568260661010497627/1571191428061732936) 复查。

## Smart Score 路线的分工

- Smart Score 承接赛事查询、焦点场次提醒、1X2/比分竞猜、球员赛后评分和群内积分榜。先配置一场真实焦点赛，在测试群观察开赛到终场全过程，再迁到正式赛事频道。
- MMOEXP FC Assistant 继续负责 Welcome 球队身份、FC27 游戏资讯、Coins/Player/SBC/OBJ&Packs 报价、商城链接、FC Chat 与客服入口。赛事卡可把球队身份对应的赛程和 Smart Score 命令入口并排展示。
- 用户自定义的“选曼城身份后看曼城赛事”“比赛进球后发 FC27 球员互动卡”“预测正确后发优惠券”不能假设 Smart Score 会自动回传用户级数据。公开消息可触发频道级话题；领取优惠券必须有明确的结果/玩家身份/幂等与防重复证据。未找到 Smart Score 对外 API 或导出合同之前，先用自有 bot 单独记录自有活动，或与 Smart Score 开发者确认集成接口。
- 赛事推送保持只读资讯频道；比赛讨论在 `fc27-match-chat`。实时事件默认只推开球、进球、红牌、半场、完场；黄牌和换人可关闭，避免刷屏。实际命令和设置以应用当前 UI 为准。

## 当前安全阈值与下一轮验收

用户已决定改用 Smart Score 作为赛事底座。自建 OpenLigaDB／ESPN 的 183 采集和 187 发布服务已停用并删除，错误测试卡已从测试频道删除；对应源代码从本任务 PR 撤除。保留该失败回执作为数据质量经验，不再部署第二条赛事采集链。

测试群的真实订阅已经验收到公开事件和自动结束；真实事件延迟、热门焦点赛的投票截止/结算/积分榜尚未验收。官方 `fc27-matchday` 已确认可调用 Smart Score，但尚无直播订阅。优惠券联动须等 Smart Score 的用户级结果接口或独立自有投票账本方案确认。

FC Chat Assistant 的 `matchday_engagement` 只认 Smart Score 应用 ID `1496068397757366273`、指定群与频道、近期公开消息；比分和关键事件无法辨认时不发话题；同场至少 15 分钟冷却，完场可额外发一次，持续记录消息高水位。它没有复制赛事数据、读取玩家私密预测或自动发券。测试时先因订阅确认卡内含 “Half Time” 误触发，后通过“必须有比分”过滤；又按真实卡片中的反引号比分修复解析。最终版本已移除诊断日志，模块 SHA-256 为 `aae0174da257669c12a2d4a4d2bc99578f7edeb1573a772b75a2058003c6c7bf`。

187 已接通官方群路由：只读 `fc27-matchday`（1571043454136484082）为 Smart Score 公开事件源，`fc27-match-chat`（1571043570268242014）收讨论卡，按钮分别进入正式 `fc27-players` 与 `fc27-coins`。Chat Assistant 的官方聊天路由已包含 Match Chat；匹配到赛事事件后会把经过核实的简短比分/话题放入本频道对话历史，AI 不应凭空补赛况。0:01 在真实 Match Chat 成功发布并读回了一张 [Matchday Lounge 导航卡](https://discord.com/channels/1041923524601851914/1571043570268242014/1571193402907824179)，证明该 bot 可以在频道发卡。更新备份 `/opt/mmoexp-fc-community/backups/smartscore-official-1794671863` 与 `/opt/mmoexp-fc-community/backups/smartscore-intro-1794672095`，服务运行中。

官方 Smart Score 尚未配置持续 `live-watch`，因此尚无真实官方事件到达 → Chat Assistant 话题的完整回执；官方 `/chat` 入口也尚未从玩家视角验收。下个焦点赛需补充这两项，再量测自然进球延迟、竞猜结算和积分榜。现阶段 FC Assistant 的正式 Players/Coins 卡已承接私密报价，赛事卡仅提供跳转，不会公开价格。

官网公开了功能、支持群、隐私和条款入口，未列出 GitHub 或源码下载；按官网域名和应用 ID 搜索 GitHub 也未找到对应仓库。其关联 [FanRate 页面](https://fanrate.zingup.club/) 将预测模型描述为专有模型。Discord 应用安装不提供服务端源码，因此只有开发方提供源码许可、私有部署或正式 API 后，才能评估直接改造 Smart Score；当前采用保留其品牌的外围集成。

Smart Score 官方入口：[Discord 应用页](https://discord.com/discovery/applications/1496068397757366273) · [官网](https://smart-score-bot.zingup.club/)。
