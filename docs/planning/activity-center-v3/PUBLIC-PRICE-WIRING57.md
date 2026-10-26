# 公开参考价实际接线 57

2026-10-26。后续候选基于 PR494 已审 head `57e93126583da6572cb210c3b75e729a2bb2051b`；该PR已合并为 `0b4c5e2938aa287f5ef2aee764591aaf7ce89fa4`。提交前快进同步main `94939a6`，本模块没有并发差异或冲突。本次未部署，线上仍 RELEASE42；PR/最终CI及合并结果以交付包终态记录为准。

## 运行链路

1. 原管理 Node 进程启动时读取既有私有 `backend/policy.json` 的 `admin_reference_prices`。没有合法策略或没有已发布的匹配商品选择时，不调用Admin。公共HTTP请求不能指定模型触发Admin查询。
2. 私有 producer 复用 `backendRead(model_provider_read)` 和现有共享鉴权；固定站点266、游戏1327、类目9623、模型41217957、1000K，仅已核PS商品163329311。请求有界、单飞、失败限频。明确配置后按60–300秒周期检查缓存，观察仍有效时复用；TTL最大1小时。原始观察只留管理进程内存。
3. 输出独立 `CAMPAIGN_PUBLIC_RELEASE_DIR/admin-reference-prices.json` 安全缓存：只含已发布版本/配置hash、商品身份、选项、USD最小单位参考金额及到期时间。不是活动发布、不是订单报价，不携带Admin响应、鉴权、源状态或证据文件路径。
4. 公开 runtime 实际 `snapshotProvider` 路径读取安全缓存并投影；仅匹配已发布release/config_hash及已选商品。策略/版本变更、读取失败、缓存损坏或过期即失效，不回退到历史快照中的旧Admin价格。活动 `current.json`、草稿及审计历史不因刷新修改。
5. 管理界面原center读取/发布路径也接入同一provider的seed；不另造编辑器。公开服务没有Admin调用或新凭据权限。交易能力仍关闭，参考价不证明折扣码已经应用。

## 限定语义

- 本轮不再等待全站币种合同。仅为已有 US/USD PS1000K 证据准备可信策略和实际调用路径；Xbox/PC及其他模型不自动继承USD判断。
- 币种/来源策略必须由私有配置指定并带证据，不能由页面或运营草稿自行授权。当前没有写入生产策略。
- 默认服务器排序不能拿Admin按ID倒序查询冒充。无 `ordered_goods_ids` 与 `ordering_evidence` 时默认参考价不可用，精确选择仍可读对应有效价。
- `more.price`按可信策略视为当前档位总价，不再额外扣一次`more.discount`。当前主站已加载数据详见 [COINS-CONTRACT57](COINS-CONTRACT57.md)。若要推广到其它折扣/区域，需要技术确认Admin `more.price/more.discount` 与主站 `full_price/price_discount_format` 的对应规则；无需整站源码。

## 激活准备（非执行命令）

未来逐次发布范围应增加本轮6个运行/测试文件中的实际运行文件，并明确私有策略启用及安全缓存生成行为；不修改service权限、Nginx或商品数据。参考策略字段：schema_version、refresh_interval_ms、entries；每项包括category_id、model_ref、baseline_region、regional_adjustment、currency、minor_unit_scale、source_field、price_semantics、evidence_ref、max_age_ms、quantity_value、quantity_unit、verified_goods_ids。未获准的时效/证据不填；缺省策略产生blocked，不能以空样例冒充已配置。

## 验证与提交边界

新provider测试覆盖私有刷新→安全文件→真实本地HTTP公开config、缓存失效/重试限频、版本并发变化、无私密字段、原配置字节不变，以及实际页面选择函数消费。相关provider7、投影8、runtime14项通过，0skip；Coins纯合同及既有core14项通过。Q指出旧请求晚返回可能清掉新版本成功缓存，已前置generation检查并补竞态用例。都是隔离合成测试，不是生产Admin/真实结算验收。最终Q另行记录，不以本文件代替Q结论。

历史：远端 `git fetch origin main` 普通沙箱连接失败；升级执行一度被自动审批拒绝，确定未执行，理由仍按上一轮“仅规划禁止执行”解释。当时停止，没有换API/工具绕过。父端随后明确重申本轮Git同步及后续PR授权，基于该新阶段澄清对同动作重试一次成功，快进main保留其他owner修改。技术包同identity最终统一补合并与本轮终态，不反复上传半成品。

最终原Q复核：本轮已审范围无剩余代码阻断，迟到请求竞态反例定向复跑通过。其余相关测试复用上述结果，未扩大审查。POSIX权限检查分支尚未在Windows本机实际验证；需最终Linux CI。该结论只覆盖本地候选，不覆盖生产策略配置、部署或真实交易。
