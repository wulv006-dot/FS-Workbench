# UnifyFootball 竞猜奖励合作核对单

状态：2026-11-16 已获用户授权，通过 UnifyFootball 官网 `/contact` 的 Feature Wanted 表单发送；网页 `POST /api/contact` 返回 HTTP 200、`success: true`、`Your message has been sent!`。表单未给工单号。**等待对方回复，不能视作已提供接口或同意外部奖励。**

MMOEXP Official Club（服务器 `1041923524601851914`）已使用 UnifyPredictions 和 Top Predictors。希望用户继续在 UnifyFootball 内竞猜，在玩家自愿兑换时由 MMOEXP 向本人网站账户发放 FC27 小额优惠券。官网的 [UnifyPredictions](https://unifyfootball-web.com/features/server/fixture-predictions) 和 [排行榜](https://unifyfootball-web.com/features/general/global-leaderboards)介绍了 PP 与榜单，但未列出外部兑奖接口；[UnifyCompetitions](https://unifyfootball-web.com/features/member/unify-competitions)建议非平台代币奖励联系团队。

需要对方确认五点，优先询问其可直接承接的方案：

1. **官方玩法**：是否能由 UnifyFootball 原生管理单场竞猜奖品或累计 PP 兑换外部优惠券？若有现成的自定义奖励、赞助奖品或 Premium 配置，请给出配置入口、费用、数据流与谁实际发券。
2. **资格证明**：若 MMOEXP 发券，能否在用户主动兑换时提供服务端可验证的、不可重复的获奖/结算事件 ID，稳定玩家标识、服务器 ID、比赛/玩法、最终分数和改判状态？是否支持签名回调或受控服务端查询？不要从 Discord 公共榜单解析。
3. **消费语义**：累计 PP 兑换时，能否原子预留或扣减相应 PP，失败时撤销，重复请求只返回同一结果？如果 PP 仅用于排名，请明确只能按单次已结算事件发奖，不能宣传为“花 PP 换券”。
4. **授权与隐私**：是否允许把上述最小字段用于 MMOEXP 优惠券资格？玩家如何明确同意并把 Unify 玩家与本人 MMOEXP 账户绑定？双方保留与删除数据的边界是什么？
5. **测试与结算**：是否提供测试服务器/测试事件、重放和改判样例、速率限制、接口稳定性及技术联系人？

若对方只提供“获奖名单”或榜单截图，无法核实稳定身份和防重，不能接自动发券。若提供单次获奖证明但无 PP 扣减，做**每个证明事件至多一次的奖品领取**；若还提供原子扣减，才做累计 PP 兑换。无论哪种，MMOEXP 侧都需再次核实本人网站会员和已验证邮箱，使用固定批次向 Admin 发券，未知回执不重发。

本次联系只提交 MMOEXP Official Club 的服务器 ID、需求与回邮地址；未提交机器人密钥、玩家名单或群内消息。收到答复后先核对接口和数据使用范围，再决定接线方式，不因提交成功重复发同一请求。
