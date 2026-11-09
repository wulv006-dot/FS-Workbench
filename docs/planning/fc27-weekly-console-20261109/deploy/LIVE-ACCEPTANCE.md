# 真实入口验收与计划启用 — 2026-11-09

运营台已部署，真实 Sol 已生成三页草稿并沿原活动中心保存、读回 revision 17；随后按用户批准启用周日12:00 Asia/Shanghai计划。活动公开发布、优惠券写入及自然周更不属于本次已验证结果。

## 最终结果

- 入口：`/dashboard/analytics/campaigns/analytics/weekly.html`，真实FS管理员会话。
- 草稿 operationId：`f9c3a00c-0837-41ee-ad32-a2fe531fbc14`，原center revision 16→17，原保存回执及当前数据一致。
- 模型回执确认 `gpt-6.1-sol`，requested/echo effort均high；输入4410、输出2986、合计7396 tokens。provider_response_id见脱敏回执；实际后端版本unknown，不将模型元数据扩称底层版本证明。金额没有账单/核准费率证据，不估计计费。
- Weekly Scout为原Popular顺序44921285、44921275、44921269；Trio为最新Player池45496989、45492791、45492789。
- SBC核心45525985、45505721、45505719，每个均2首选＋2备选。各候选三平台身份映射及源goods覆盖检查通过。
- 已发布配置/发布元数据、其他活动页、各页优惠引用、万圣节配置和三页文案哈希均未改变。身份验证通过不代表新商品的实际报价和结账已验证。

精确16项检查及商品映射见 [草稿读回](live-draft-acceptance.json)，模型用量见 [Sol回执](live-sol-receipt.json)。两次之前的尝试分别保留未派发与校验失败状态，见[恢复记录](RECOVERY.md)；未清记录或重放UNKNOWN。

## 计划

2026-11-09T06:46:46.435240Z，真实管理员在运营台启用计划；配置revision 1，operationId `88540366-c0d6-4df1-afc0-0c3d4d56da7f`。UI与持久配置、原配置回执均读回enabled=true，scope仅prepare_model_apply_center_draft，publication=false。见[计划回执](live-schedule-receipt.json)。

下次预期为2026-11-15周日12:00（UTC+8，04:00 UTC）。当前周一不补跑；调度按上海周日12点后当天一次处理，周日中午后启用/恢复会处理当天，跨日不补跑。启用后的读回仅有3次manual，无scheduled记录，**自然周期尚未运行**。沿原controller五秒恢复循环调用隔离campaign.tick，没有新增服务或定时器。

## 版本与验证

PR930/CI1800为初始41目标部署，PR934/CI1801为curl兼容修复；PR936/CI1805为模型SBC数量约束修复，merge `c0eb262b5382763e28a561b0b304cb9fa59277e4`。最终单文件发布 `nav-20261109T064500Z`，实际推荐源码SHA `9a70af59a9459956f6e4db363cc7966d7313cf0583e8cd3460d73a261be5073a`独立读回一致；原活动管理、公开运行和共享range服务active。

最终相关核心349项、专项43项通过，单目标发布护栏3项、只读验收工具2项、原请求恢复5项通过；初始跨平台/浏览器证据沿用ACCEPTANCE.md。生产没有回滚演练，不拿护栏测试当真实回滚证明。

## 保留缺口

本轮外部资料2条、9项覆盖缺口，社媒不足，草稿仍需内容复查。最新排序来自原模型ID倒序，目录未提供创建时间；游戏SBC实际到期及配队要求仍待核实。新商品实际售价/规格、优惠码、跨域购物车与成交追踪尚未生产验收；原发布和优惠券写入仍须人工批准。没有发送社区消息或执行订单/支付。
