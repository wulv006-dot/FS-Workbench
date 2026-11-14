# FC27 内容聚合与真实足球赛事区

> **2026-11-15 执行基线：**用户指定 [FC27 Discord 内容驱动增长与转化项目方案](FC27-DISCORD-OPERATIONS-BASELINE.md) 为最终改造方案。本文件记录早期频道施工与技术回执；两者冲突时按新方案执行。公共同场观赛与讨论为主，球队身份只用于自选提醒和入口；Hermes 每日自动选题与排期属于待开发能力，不能写成已上线。

## 已核对的现场（2026-11-14）

- MMOEXP Official Club 的 Madden/CFB 区已有 `madden27-news`、`madden-chat` 和 `events`。新闻卡提供赛事日程/比分入口、赛前简报和赛后结果；聊天机器人提供私密问题与工具菜单。`events` 在本次检查时为空，不能把它当作已运行的预测系统。
- EA FC 27 现有 SBC、Evolutions、Objectives、Gallery Tiers、Store Packs 分频道。EasySBC 在各频道发内容卡，MMOEXP FC Assistant 按频道映射在五分钟静默窗口后发对应报价卡。
- FC Assistant 在正式群内看不到 EasySBC 卡片的正文、嵌入与附件。合并四类来源到同一频道后，不能靠现有消息事件可靠判断商品类别；频道本身是现有分类依据。
- 独立的 FC 聊天服务已在 187 运行；游戏聊天区仍由它承接，不再开启 content bot 的第二套聊天回复。
- 已由 Discord 桌面脚本创建 `📅・fc27-matchday`（1571043454136484082）、`🗣️・fc27-match-chat`（1571043570268242014）及 `🎒・fc27-obj-packs`（1571045541922611200）。赛事资讯及聚合频道对普通成员只读，FC Assistant 可发帖；聚合频道也允许 EasySBC 发帖。赛事讨论频道允许玩家交流。2026-11-14 现场读取赛事分类位置为 5。

## 玩家看到的结构

| 区域 | 频道 | 用途 |
| --- | --- | --- |
| FC27 游戏 | Welcome | 选球队，领取 FC27 + 球队身份，查看游戏与赛事导航 |
| FC27 游戏 | News | EA/MMOEXP FC27 游戏新闻，保留来源和去重 |
| FC27 游戏 | Coins、Players、SBC | 分别承接金币、球员、SBC 自助报价 |
| FC27 游戏 | OBJ & Packs | 汇集 Evolution、Objectives/Rush、Gallery 和 Store Packs 的 EasySBC 信息及 MMOEXP 私密报价 |
| FC27 游戏 | Chat | 游戏交流及现有 FC AI 聊天服务 |
| 足球赛事 | Matchday | 真实足球赛程、比分、球队资讯与焦点赛事卡；只读 |
| 足球赛事 | Match Chat | 比赛讨论、预测入口和赛后复盘；成员可发言 |
| 客服 | 现有工单/客服入口 | 订单、账号与售后问题继续走私密服务 |

旧的四个 EasySBC 单项频道在订阅迁移和报价验收前保留。验收后移出玩家主导航并取消自动发布，保留历史供管理员检索；`pack-pulls` 与 `squad-reviews` 的历史内容不删除，可改成 Chat 主题或继续作为活跃讨论区，依据近 30 天实际活跃度决定。

## OBJ & Packs 卡片合同

聚合频道公开放 EasySBC 内容卡和一张 MMOEXP 总入口卡，四个按钮分别为 Evolutions、Objectives/Boosting、Gallery Tiers、Store Packs。按钮查询使用现有 FS 只读报价 socket、商品目录和折后成交价；价格面板 `ephemeral`、按点击者隔离，3 分钟失效，刷新仍留在原类别。公开卡不展示具体个人价格。

EasySBC 订阅迁到新频道后，relay 仅信任其应用 ID、指定群和频道；所有连续更新按最后一条后的五分钟静默窗口合并成一张新的总入口卡，并保留十分钟冷却。它不保存玩家聊天正文。配置确认文字也可能触发一次收尾卡，因为当前应用拿不到消息内容；迁移时清理这类提示，后续不把系统提示当常规内容入口。

落地次序：先在测试群验证四按钮、报价/刷新/权限；再发布与线上聊天服务兼容的代码；最后把 EasySBC 的 Evo、OBJ/Rush、Gallery、Packs 订阅逐项改到新频道并核对真实发卡。旧四频道的订阅在确认新频道收卡后取消。SBC 仍单列，不改路由。

游戏身份选择后的私密导航也要同步更新 `game_picker.FC_GUIDE_GROUPS` 和线上 `game_picker` 配置中 FC 的 `channel_ids`：主入口保留 Welcome、News、Coins、Players、SBC、OBJ & Packs、Chat，新增 Matchday、Match Chat 和客服；旧四个单项来源频道在迁移后从导航名单移除。代码常量改动本身不会让未列入在线配置的频道出现。

## 足球赛事产品：Smart Score 为底座

Smart Score 负责真实比赛查询、直播事件、胜负/比分竞猜、球员赛后评分和群内积分榜。MMOEXP FC Assistant 负责 Welcome 球队身份、FC27 商品私密报价、赛事导航、运营活动和奖励领取；FC27 Chat Assistant 负责赛前话题、半场讨论和赛后复盘。三者共同服务同一赛事专区，不复制 Smart Score 的赛程数据采集。测试回执和当前限制见 [SMART-SCORE-PILOT-20261114.md](SMART-SCORE-PILOT-20261114.md)。

2026-11-15 首个接入已经落地：Chat Assistant 识别指定频道的 Smart Score 公开比分卡，在 Match Chat 发低频赛事讨论卡，附原卡和 FC Assistant 的 Players/Coins 私密报价入口；官方群 Match Chat 已有一张欢迎导航卡。赛事个人预测、积分或优惠券尚未接通，不能把 Smart Score 的私密回执当作 MMOEXP 可读事件。

| 时间 | 公开内容 | 玩家互动 | FC27 关联 |
| --- | --- | --- | --- |
| 赛前 24 小时 | Matchday 只读频道发布一场焦点赛事导览；Smart Score 开竞猜 | 私密预测、按球队身份进入讨论 | 曼城等已选球队玩家看到对应入口；给出 FC27 球员/阵容话题 |
| 开赛前 1 小时 | Chat Assistant 发首发或看点话题，引用已核实的信息 | 预测截止提醒、赛前投票 | 与 FC27 球员卡、SBC 或游戏阵容玩法关联 |
| 比赛中 | Smart Score 在 Matchday 推关键事件；优先开球、进球、红牌、半场、完场 | Match Chat 讨论，半场观点、进球后 MVP 投票 | MMOEXP Assistant 只在适当节点发一张相关游戏入口卡，防止促销刷屏 |
| 赛后到次日 | Smart Score 赛果、球员评分、积分榜；Chat Assistant 发复盘问题 | 玩家评分、晒阵容、下一场选题 | 玩家主动点击后再进入 Players/Coins/OBJ&Packs 私密报价 |

首期聚焦已支持的英超、欧冠、西甲、德甲、法甲，以及 Welcome 热门球队。默认不批量 @ 球队身份组；球员可主动订阅或通过私密导航进入赛事。Matchday 对玩家只读，Match Chat 可发言。Smart Score 的 `live-watch` 按真实比赛配置；测试群没有持续订阅，正式群也尚未启用。优先利用其原生 `auto-predict` 和积分榜设置，避免每日人工发命令。赛事节奏与游戏内容由 FS 可配置焦点球队、赛事、卡片模板和频率。

### 自定义玩法与奖励

第一阶段用 Smart Score 原生竞猜与球员评分，MMOEXP 只发赛事导览、游戏关联话题和链接。第二阶段加自有“比赛日任务”：预测前展示球队历史、赛后晒 FC27 阵容、参与 MVP 讨论、邀请好友进入公开赛事页；活动参与与任务奖励由自有机器人记录。优惠券和积分兑换须有玩家身份、每场次数、库存/预算、幂等发放和撤销回执，且不以购买为参加条件。

Smart Score 的个人预测回执是仅本人可见的，当前没有验证到可供 MMOEXP 读取的用户级 API 或导出。不能把 Smart Score 的私密预测当作自动发券的依据；若官方提供可用集成接口，再直接对接。否则奖励活动使用自有机器人独立投票账本，赛果由可核实的 Smart Score 公开完场卡加人工异常复核结算。不要让普通账号脚本替代应用接口长期批量执行命令。

### 自动化与防刷屏

FS 控制台维护焦点赛事、球队、话题模板、消息节奏、奖励上限和开关；Smart Score 继续在自己的应用命令中管理直播订阅、预测联赛与积分规则。MMOEXP Assistant 可监听指定赛事频道里 Smart Score 的公开事件卡，验证应用 ID、频道和内容结构后触发一次 Chat 话题。按 `match_id + event_type + minute + team` 去重，关键节点至少保留冷却；卡片无法辨认时只保留 Smart Score 原消息，不猜比赛结果。若要由 FS 自动下达 Smart Score 管理命令，先向应用开发者确认正式 API/集成方式，不能假定一个 Discord Bot 可以调用另一个 Bot 的 slash command。

### 验收与发布

测试群已验证模拟事件和一名玩家的私密胜负投票；`open-predict` 管理命令成功但公开发现入口未验收。下一次真实比赛要量测从进球实际时间到 Discord 消息时间的延迟，并检查重复/漏发、订阅取消、截止锁定、结算与积分榜。之后在正式 Matchday 开启一场焦点赛，Match Chat 发一轮赛前/半场/赛后话题，核对 Welcome 选球队的导航和公开频道权限。真实奖励、自动发券和积分兑换另按 FS 接口验收。

OBJ & Packs 聚合仍按前述合同验收：普通成员可见但不能发消息；EasySBC 和 FC Assistant 可发；四类按钮只给点击者显示折后报价。SBC 独立频道不受赛事改造影响。
