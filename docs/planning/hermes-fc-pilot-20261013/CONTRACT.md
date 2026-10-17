# FC 试点合同 v1（候选）

FS → task ledger → Hermes Runs API → FC只读工具 → 专用报告验证/存储。ChatGPT/老D继续主沟通；不经过飞书。没有业务写工具或对外通知。

## 数据与证据

最近完整自然周按 Asia/Shanghai 周一00:00至下周一00:00右开；2026-10-13应取10月5–11日，对照9月28–10月4日。任务标识绑定 owner、FC27、周区间、snapshot、模板、知识和预算版本；相同输入返回同一任务，变更快照产生新任务。

快照是同次分析的一致性输入，不是跨任务旧缓存。异步采集遵循现有日期刷新策略。每条证据至少携带来源、期间、as_of、范围、币种、capture_id、指标及覆盖缺口。当前代码只接受FC27/main Admin聚合和FC27/all-sites Order参考，跨站差异必须标注。现有FCDetails已支付口径与首页汇总不能凭数值相近混用；真实适配前固定 metric_definition_version 并纳入任务指纹。

Admin提供经营主指标；Order仅补参考利润率、估算利润及成本覆盖。估算利润=Admin销售额×Order参考利润率，Decimal保留两位；缺失为null，不补零，不要求逐笔完全对账。真实改价成本是另一合同，只允许核实发货类型，排除采购打款/空/未知；本试点不输出可执行改价成本。

## 工具白名单

| 语义工具 | 参数 | 输出 |
| --- | --- | --- |
| fc.get_metric_definitions | 无 | 口径/来源/估算边界 |
| fc.get_business_snapshot | snapshot_id, window | Admin聚合 |
| fc.get_order_reference | snapshot_id, window | Order参考、缺口 |
| fc.compare_periods | snapshot_id | 变化额/变化率和证据引用；基期0比例为null |
| fc.get_breakdown | snapshot_id, window, dimension | platform/product/bucket聚合，上限200行 |

window仅target/previous。真实MCP服务名拟fcro；固定Hermes源码生成工具名为 `mcp__fcro__fc_get_business_snapshot` 等，运行时发现必须恰好五项。工具返回不含订单号、客户身份、备注、Cookie或密钥。所有额外字段拒绝。运行时不加载默认shell/browser/file-write/memory/skills写工具；OS身份和文件权限也必须限制，提示词不是边界。

## 状态与恢复

创建QUEUED；持久写DISPATCH_UNKNOWN后才可POST /v1/runs，Idempotency-Key和session_id从owner/task哈希派生，客户端不能指定身份/模型/密钥。202回执校验run_UUID后绑定。未知提交不换key盲重试，重启需向固定Hermes持久幂等账本核对。

RUNNING → VALIDATING → SUCCEEDED/PARTIAL/FAILED。取消请求先CANCEL_REQUESTED，停止API返回stopping不代表线程停止；只有独立监督确认worker已停才CANCELLED。interrupted → NEEDS_RECONCILE，保留证据和provider未知状态，不自动重启计费。旧lease和旧version不可更新新任务。当前代码未实现人工核对后的恢复操作和进程监督，生产不得自动清除unknown。

## 模型代理和预算

在原有持密钥进程中增加限定FC任务/轮次代理，复用原provider_slot与model_calls账本；Hermes进程仅访问局部代理，不持Bailian密钥。模型和endpoint服务端固定为现有百炼DeepSeek。原报告validator与新工具对话协议分开，不改变旧调用。先实测非流式tools往返是否满足固定Hermes；如需流式，另实现受限SSE和usage归集，不伪造流式兼容。

每轮先持久预留输入/输出token、轮次和金额上界再请求，调用ID绑定task/run/turn/request_digest；已开始未知请求不可重发。结算记录provider request_id、prompt/completion/total tokens、价格版本、金额与证据；usage或价格未知则hold，不能按0释放预算。禁止新增第二个独立模型计费账本。

建议试点并发1、最多12轮/32000 tokens、普通工具30秒、分析600秒、只读瞬时失败最多2次；金额上限待确认。采集准备单独计时，尚未批准/启用这些生产参数。监督器须硬停止超时任务并验证实际无后续调用；现有离线事后计数不足以放行。

## 报告

数字卡片来自确定性核验值。1–3条发现需区分事实/假设，引用证据、备选解释和缺口；最多3条人工下一步行动。缺口不伪装成零/成功。初版自由文本不能自造数字；因果断言仍须人工评估。专用结果按owner隔离，不能覆盖每日顾问报告。业务执行效果不在只读试点内伪称完成。
