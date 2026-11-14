# FC27 内容聚合与真实足球赛事区

## 已核对的现场（2026-11-14）

- MMOEXP Official Club 的 Madden/CFB 区已有 `madden27-news`、`madden-chat` 和 `events`。新闻卡提供赛事日程/比分入口、赛前简报和赛后结果；聊天机器人提供私密问题与工具菜单。`events` 在本次检查时为空，不能把它当作已运行的预测系统。
- EA FC 27 现有 SBC、Evolutions、Objectives、Gallery Tiers、Store Packs 分频道。EasySBC 在各频道发内容卡，MMOEXP FC Assistant 按频道映射在五分钟静默窗口后发对应报价卡。
- FC Assistant 在正式群内看不到 EasySBC 卡片的正文、嵌入与附件。合并四类来源到同一频道后，不能靠现有消息事件可靠判断商品类别；频道本身是现有分类依据。
- 独立的 FC 聊天服务已在 187 运行；游戏聊天区仍由它承接，不再开启 content bot 的第二套聊天回复。
- 已由 Discord 桌面脚本创建 `📅・fc27-matchday`（1571043454136484082）、`🗣️・fc27-match-chat`（1571043570268242014）及 `🎒・fc27-obj-packs`（1571045541922611200）。赛事资讯及聚合频道对普通成员只读，FC Assistant 可发帖；聚合频道也允许 EasySBC 发帖。赛事讨论频道允许玩家交流。新赛事分类当前仍在服务器列表末尾，需要在桌面客户端完成排序。

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

## 足球赛事产品

### 内容与球队身份

首期只做英超、欧冠、西甲、德甲、法甲及高热度杯赛中与已配置球队身份有关的比赛。球队身份由现有 Welcome 选择产生，不强制领取身份才能看赛事。球员选曼城、皇马、巴萨、拜仁或巴黎后，赛事卡突出该队下一场比赛；其余球队由“更多球队”入口选择。频道公开卡显示对阵、赛事、开赛时间（Discord `<t:UNIX:f>`，按玩家客户端时区显示）、数据来源、状态和操作按钮。若数据源缺失或比分未核实，显示“待核对”，不臆造结果。

免费试点数据源候选为 football-data.org：官方文档列有比赛、球队、赛事和积分榜接口；免费档提供 12 项赛事、赛程与延时比分，每分钟 10 次请求。实时比分及扩充赛事覆盖需要另评估授权和费用。球队徽标不直接抓取复用，先用自有品牌元素、文字或已获许可素材。[API 文档](https://www.football-data.org/documentation/api) · [覆盖范围](https://www.football-data.org/coverage) · [套餐](https://www.football-data.org/pricing)

发布节奏：每日一次“今日/明日焦点赛”，每场赛前 24 小时可发一次独立卡，开赛后只编辑原卡的状态/比分，终场校验后更新结果；同一比赛 ID、版本和发布时间窗口去重，避免刷屏。球队相关提醒只给主动订阅的成员；默认不批量 @球队身份组。可把重点场次作为 Discord 原生“预定活动”承接看球提醒。[Discord Scheduled Events 说明](https://support.discord.com/hc/en-us/articles/4409494125719-Scheduled-Events)

### 预测与奖励

第一版做免费 1X2（主胜/平/客胜）预测。公开比赛卡显示当前选票分布和“预测”按钮；用户点击后在仅本人可见面板确认，回执也仅本人可见。每人每场一票，可在截止前修改；截止取权威数据源的开赛时间，开赛后锁定。终场结果要经过数据源再次读取和纠错窗口，结果未知则延迟结算。存储最少量的 Discord 用户 ID、比赛 ID、选项、时间戳和处理状态，避免存聊天内容。

优惠券不在首版自动发放。先核对 FS/Admin 现有优惠券签发与核销接口、限领规则、库存、重复账号防护和人工纠错路径；通过后按独立幂等键 `fixture_id:user_id:campaign_id` 发放。奖励只用于免费娱乐活动，不要求购买或充值参加，不提供现金兑换。运营可在 FS 控制台挑选焦点赛、奖品和预算上限，发布前预览卡面，赛后看参与、正确率、领取和实际使用。

## 技术边界与验收

- 新 `matchday` 模块应与现有 FC Assistant 同应用身份集成，独立数据库与调度，不能重开一个使用相同 Discord token 的重复消息监听进程。独立 DSH 聊天机器人仅服务 Chat，不接手赛事结算。
- 数据接入分 `provider -> normalized fixture -> public card -> prediction ledger -> verified result -> reward outbox`。比分与赛程保留来源、抓取时间和原始赛事 ID；球队映射使用供应商 team ID，不靠模糊名称直接结算。
- 测试群先验收：球队身份与赛程匹配、用户本机时区、公开阅读与私密预测、截止锁定、重复点击、结果更正、数据源故障、无优惠券接口时不发券。正式群用一场模拟赛事先发卡和投票，不立即发奖励。
- 聚合频道验收：普通成员可见但不能发消息；EasySBC 和 FC Assistant 可发；四类按钮都能拿到正确 FS 折后报价、跳转站内对应商品，外人无法打开他人的面板；EasySBC 一批多条后仅推一张总入口卡；SBC 独立频道继续正常工作。

## 待完成的发布动作

当前 FS `origin/main` 与 187 在线 `content_bot.py` 有明显差异，线上包含 DSH 新聊天服务接线。`quote_panel.py`、`quote_relay.py` 只有文件字节差异、未见源码行差异。上线聚合代码前必须把在线聊天改动合入候选、在隔离环境验证并按现有 publisher 备份发布；不能直接用 Git 版本覆盖在线 `content_bot.py`。EasySBC 四类订阅和原频道迁移应在新入口真实可用后进行。
