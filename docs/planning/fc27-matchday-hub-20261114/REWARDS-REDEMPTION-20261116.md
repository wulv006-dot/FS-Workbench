# FC27 竞猜与优惠券兑换：三段接线

状态：2026-11-16 已完成可独立测试的**站内积分兑换账本**；尚未接入玩家入口、站内竞猜结算或真实自动发券。不能把 UnifyFootball 的 PP 宣传为现可兑换 MMOEXP 优惠券。

网站会员身份和本人券包的具体接线要求见 [网站会员身份接线合同](SITE-MEMBER-REWARD-INTERFACE-20261116.md)。

## 现场事实与边界

- UnifyFootball 已在官方群自然结算过一次竞猜，并在服务器 Top Predictors 榜单显示 2 PP；该公开卡的文字仅有用户名和分数，未提供该行稳定的 Discord 用户 ID、兑换扣分接口或服务端领奖回执。官网介绍了竞猜、积分榜和可选的 Predictor 身份组，**没有公开承诺可供第三方核验与扣减 PP 的接口**：[UnifyPredictions](https://unifyfootball-web.com/features/server/fixture-predictions)、[排行榜](https://unifyfootball-web.com/features/general/global-leaderboards)。不能靠截图、用户名匹配或 Discord 身份组当作现金券资格。
- UnifyFootball 的 [UnifyCompetitions 文档](https://unifyfootball-web.com/features/member/unify-competitions)对**非平台代币奖励**提示联系其团队；这说明有合作询问入口，但只针对赛事杯赛的说明，**不能推定竞猜 PP 已有外部核验、扣分或优惠券接口**。优先向团队确认竞猜 PP 是否支持官方合作接线，不另造第二套竞猜体验。
- [Discord Developer Policy 第 16 条](https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy)限制将 Discord API Data 用于福利资格判断，第 20 条禁止挖掘/抓取 Discord 服务中的数据。因此不解析 Unify 消息、积分榜、玩家身份组或私密竞猜回复来发 MMOEXP 券。Unify PP 继续承担**群内竞猜、排行和身份荣誉**；现金优惠由玩家自愿参加的 MMOEXP 站内活动独立核算。
- 187 当前 HMAC 身份可 `GET /admin/market.Coupon/edit?id=1385`，回执业务码 1、站点 266、FC27 游戏 1327；亦有 `market/couponGrant/import`，但没有 `market/coupon/add`。所以**后台网页预建券模板 + 187 按已验证会员定向发放**可避开自动建券权限。1385 是总量 1、已做单邮箱测试的券，不能当正式奖池。自动创建模板以后再接。
- 现有 `opt/mmoexp-lucky-loot/coupon.cjs` 已封装券详情校验、`CouponGrant/import` 与 `jobStatus` 对账；复用其业务合同，未授权的新服务不能把玩家自报邮箱直接当作本人身份。

## 1. 积分怎么核实

首选保持玩家在 UnifyFootball 内竞猜。需由对方确认是否可提供**经授权的服务端兑奖证明**：不可变的获奖事件 ID、稳定的玩家标识、所属服务器和比赛、已最终结算的 PP、撤销或改判状态，以及重复调用时的幂等语义；如果按累计 PP 兑换，还须有原子扣减或预留并确认接口。MMOEXP 只接受对方服务端签名或双方约定的受控调用，不接受用户截图、公开榜单、机器人消息或客户端提交的分数。合作条款还需明确该奖励用途与数据共享范围。确认之前，不把 Unify PP 计入可兑券余额。

若对方没有可用合作接线，而业务仍要现金券兑换，才评估独立的 **MMOEXP Match Picks**：玩家从公开赛事卡自愿进入 MMOEXP 站内页面，使用网站登录；网站按会员 ID 接收开赛前的预测，锁定截止时间，依据独立、获准用于活动结算的赛果源核实赛果。每条预测用固定 `site:<settlement-id>`，只在赛果最终确认后入分。改判或争议先冻结相关兑换。这个备用方案会有第二套竞猜入口，启用前需单独决定玩家体验。

备用站内积分明确命名 **MMOEXP Match Points**；它与 Unify PP 不是同一余额。若合作接线成立，先确定用“单次获奖事件领一次券”还是“累计 PP 消耗兑换”作为官方规则，两者需要不同的防重复证明，不能把累积排行榜分数直接当可消费余额。

## 2. 兑换后怎么防重复

新模块 `opt/mmoexp-fc-community/match_rewards.py` 使用 SQLite 事务保存站内结算证据、券奖项和领取记录。`credit_site_points` 只给**内部站内结算服务**调用，不暴露 HTTP/Discord 写入口。`claim` 在同一 `BEGIN IMMEDIATE` 事务中检查积分余额、券份数、同会员同奖项的一次领取，再占用积分和名额；并发点击只有一个领取记录。固定 `claim_id` 与 `FC27R_…` 批次号跨重启不变。

券模板 ID、积分成本、份数及券详情指纹启用后不可悄悄改动。`coupon_snapshot_fingerprint` 覆盖与现有 Lucky Loot 券适配一致的金额、门槛、范围、日期和限领字段；发券前再次读详情并比较券快照。运营暂停时不能开始新的发放。状态为 `reserved → sending → pending/confirmed/unknown`。`sending` 或 `unknown` **绝不自动第二次 POST**；异步任务只按原 `job_id` 查询。只有明确尚未提交的 `reserved` 可撤销并释放积分与名额；曾提交但回执不明需按原批次人工对账。玩家可查询原领取状态，重复点击返回同一条记录。

该模块目前是**未接入运行服务的基础模块**：没有后台配置页、网站登录/预测入口，也没有生产发券动作。其账本与单人发券适配器已在本机 Python 3.9 和 187 独立暂存目录使用部署环境的 Python/SQLite 验证；适配器通过 `reward_coupon_bridge.cjs` 复用现有 Lucky Loot 的券详情、发放及原任务对账合同，187 的只读券详情链路已读回测试券 `1385`，未再次发券。隔离验证不代表生产接线与真实发券验收。

## 3. 券怎么发到本人

站内认证层提供当前**已核实 MMOEXP 会员 ID 与绑定邮箱**，发放服务只用该会员记录中的邮箱，不接受 Discord 弹窗或玩家随意输入的目标邮箱。运营先在 Admin 网页建立并启用适用 FC27 的定向券模板，配置金额、门槛、期限、商品范围、总量和预算；FS 读回详情快照后才启用相应兑换档位。

兑换时先持久化 `sending` 和固定批次号，再通过 187 现有 HMAC 代理一次性调用 `POST /admin/market.CouponGrant/import`，每批仅一个已核实邮箱。同步成功记录会员券 ID；异步返回 `job_id` 则只轮询原任务；超时/未知停止重试并由运营核对原批次。玩家在 MMOEXP **本人券包**看到券与适用条款，Discord 公共频道只显示活动入口，不展示邮箱、券号或个人领取结果。可选的 Discord 私密状态卡要等会员安全绑定接通后再做。

内部 `match_rewards_delivery.py` 已实现上述单笔状态流：网站会员提供方必须返回站点 `266`、匹配会员 ID、已验证邮箱及可用账号；发券前读回 FC27 券详情并核对指纹；两笔并发只能抢到一次 `sending`；回执不明时冻结，异步对账只查原 `job_id`。会员提供方**尚未接入真实网站接口**，故该代码不被任何线上入口调用，也没有启用自动发券。

## 接下来的接线与验收

1. 先与 UnifyFootball 确认上述服务端合作能力、奖励用途授权和事件/余额语义。若不可用，再决定是否建设站内独立竞猜及独立赛果结算；不能以 Unify 的 Discord 消息作为现金券判定输入。没有可信积分来源时只保留群内 PP 与榜单。
2. MMOEXP 网站侧给出可用的**本人登录/已验证邮箱**接口；目前 Admin `user/member` 搜索只说明邮箱存在，不证明提供邮箱的 Discord 玩家拥有该账户。没有这个接口，不开启自助发券。
3. 在 FS FC27 独立控制台接奖项配置、暂停、预算与对账；复用现有券发放适配，连接本账本的固定批次与状态。先在测试账户用**新建的小额测试券**验证一次发放、本人券包、重复点击、未知回执和超额拦截，再考虑正式群公布兑换入口。旧券 1385 不复用。

生产启用条件：本人身份、积分来源、赛果、券条款、预算及实际 Admin 回执各有可核验记录。缺任何一项时页面只展示非现金群内积分玩法，不宣称已可兑换优惠券。
