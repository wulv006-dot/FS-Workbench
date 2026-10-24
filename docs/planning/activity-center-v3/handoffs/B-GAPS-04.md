# B-GAPS-04 后端交接

任务 `FS-V3-G1-COMPLETE-GAPS-04`。PC-20260909OJLI，独立工作树 `campaign-gaps-b`，
分支 `codex/fs-campaign-v3-gaps-backend`，基线 `29ed99af85dc4aa7a302e63ae36c06e5da495369`。
只修改本分支 backend（不改 catalog.py / C 商品测试）及本交接；原 PR434/head/stage、旧 B 树、
控制树、管理前端和 production-server 均未修改。无 push、merge、发布、创建券、发放或支付。

## 已实现与真实证据

1. AdminRead 增加已由主控原 SSH 只读核实的 Coupon/edit、Discount/edit 详情；exact ID 必须回读匹配。
   `benefits_read` 按具体 site266 或全局0过滤、逐行验证，分别标 exact_site/global；其他站点或未知范围拒绝。
   全局行不因此自动可绑定或可编辑。列表成功不代表优惠当前有效。
2. 管理桥接优惠详情、title/brief 窄编辑、显式停用、原操作查询/对账。服务端私有对象政策控制准确 ID、
   site/game/goods、独占性、精确回读、停用/补偿及 status0 语义；默认无任何允许写对象。
   未确认的 add/status0 不会创建：原 DisabledCouponDraft.enabled 已硬设 false，直接调用 dispatch_once
   也拒绝。没有 grant/add/delete/支付路由。启用另需 enable_verified + activation_authorized，默认 false。
3. Native 编辑只发一次 POST `/admin/market.Coupon/edit`，payload 仅 `{id,title?,brief?}` 或 `{id,status}`。
   状态最小 patch 有公开前端 baTable field-change 合同；title/brief partial patch 仍需 exact object 的
   partial_edit_verified，不把通用表单源码当真实写验收。禁用 Sales Session.post_admin 的重试路径。
   保存前核 whole-row before_hash；HTTP200 不确认业务，必须原 ID 和目标字段/范围回读一致。
4. 原 SQLite OperationLedger 的去重、原请求冲突和 unknown 保留继续有效。前置明确拒绝持久化为
   rejected + dispatch_state:not_started；同 ID 不同请求不得证明原操作未派发，返回 unknown。
   本地 lookup 的 dispatched 是原子 claim 标志，不等于已发生 native POST，应使用 dispatch_state。
   原操作尚处 pending 的显式 reconcile 会原子 fence 为未派发拒绝；旧 worker 此后不能再 claim/发 POST。
   已 claim 的 unknown 只 GET 原对象读回；暂不存在的操作仍是未查到，不能据此换 ID 盲重放。
5. 实现真实 orders + coupon_logs 的关联读取、最多28天完整分页、private SQLite 归一事实/历史/绑定版本/
   成功窗口/失败记录/站点版本。订单号仅在读取/关联内存内使用，落库身份用 SHA；不存客户、自由备注、IP、
   原始响应或原始码。按已核 pay_status1 和日志 status1 关联；其他付款状态未知，退款2只有显式已核映射才分类。
   同订单多活动全局去重；折扣码按既有 strip+casefold 标准解析到准确 native ID，重码冲突不任取。
6. 增量窗口重跑替换本窗口事实，不重复累计；历史版本保存，不删除原付款审计。不可变 binding_version 冲突拒绝。
   扫描开始的站点 revision 在提交时 CAS；并发旧 capture 迟到会被拒绝，不覆盖新快照。失败保留成功事实/verified_at。
   latest_window_end 只表示最近读过的最大结束时刻，history_complete=false；没有已核更新时间游标。
   晚付款、旧订单退款需要重叠窗口和明确历史重扫，不声称全历史自动对账。scanned_windows/rescan_policy 明示边界。
7. 金额候选仅 `pay_money_format2[1]` + currency_code，且必须 `[0]` 同币种。必须服务端
   money_verified、money_verification_ref、currency_scales 才输出金额；不以 amount/USD、格式化 pay_money、
   折扣金额代替实收。金额未核则 null；缺失金额不能作为部分和冒充全量。行分摊和退款事实未核一直 null。

主控只读证据（本地 task/inputs，未把真实业务行发给模型）：

- `gap-schema-evidence-04.json`：2026-10-24 10:28:03Z，site266 coupon82、discount760，两个实际详情 GET 成功；
  昨日订单1128，pay_status1=1101、2=27；用券日志99，status1=99、关联99个订单。
- `gap-public-field-sources-04.json`：MemberCouponLog 公开源 `index-56cf6d42.js`
  SHA `3331e54d6542c4a1cc182b1693006d9563ce20ec0634a1b16ab6e79ba51139c7`，status0未支付/1已支付。
  Currency 公开源只含 code/sign/rate/status，不证明精度。第一次 TLS 错误和第二次正常证书校验读取记录由主控保留。
- `gap-money-evidence-04.json`：最多100条样本、8币种。pay_money/format 都非纯十进制；format2[1]100条可解析且
  format2[0]100条同 currency_code；amount 仅43条与原币支付数字相等。这是结构/关系证据，不单独证明金额口径。
- `gap-analysis-evidence-04.json`：主控 10:50:10–10:50:18Z 原 SSH exit0 的**候选源码内存执行**，
  SQLite `:memory:`，无远端 DB/配置/安装或实际写入；readback_consistent=true。
  1128源订单、1101付款观察、99券日志，满足订单有效付款后的关联仅94；项目绑定0、未绑定1101、totals/activities空，
  退款 null，history_complete=false，binding/money/payment/time warnings 保留。
  该回执没有最终 Git commit/source-module SHA，不能将它说成最终提交已部署或已做同 SHA 生产验收。
  候选后续改动由本地定向测试覆盖，最终提交号与集成版本由主控记录。

`probe_schema.py` 和 `probe_money_shape.py` 仅供主控只读探针，不放生产安装 allowlist；输出字段类型、数字枚举频次、
条数、ISO币种、解析率/相等计数及 SHA，不输出订单号、客户、金额原值或原始码。Python `-B` 可避免导入缓存文件。

## 固定管理桥合同

沿用一个 JSON stdin / stdout envelope，所有新动作仍在原 FS 登录/角色/Origin/CSRF 边界后。
读写动作接线、UI、publisher allowlist 由主控负责。桥不接受 policy/config/path 参数。

| action | 必需输入 | 安全响应 |
|---|---|---|
| benefit_detail | site_id266,kind coupon/discount,native_id | native_id/kind/before_hash/白名单fields/editability；无原始码或嵌套后台对象 |
| benefit_edit | site/kind coupon/native_id/operation_id/before_hash/changes title或brief | 稳定原ID、state、payload_hash、dispatch_state、结果ref/reason |
| benefit_toggle | 同上，enabled必须bool | 同上；关闭与启用分别门禁，不收任意 status patch |
| operation_lookup | site/operation_id | 只查原账本；不回原 payload |
| operation_reconcile | site/operation_id | 未派发原子 fence 或已派发原 ID 读回；无 POST |
| analysis_reconcile | site/from/to，`YYYY-MM-DD HH:mm:ss`、最多28天 | 实际读/关联后安全聚合与capture SHA；没有任意财务映射输入 |
| analysis_summary | site,activity_id可选 | 已保存范围的安全聚合，不读取/返回原始订单 |
| catalog_mapping_read | site266,reference_key可选 | 延迟调用C read_reference_mapping；仅服务器固定产物路径 |

analysis 形状：status=ready/partial/blocked；coverage 包含 source_orders、paid_observations、
refunded_observations（未核为null）、coupon_log_rows、associated_paid_observations、bound_paid_orders、
unbound_paid_orders、unresolved_orders、successful_runs、window_from/to、latest_window_end、history_complete。
totals 为按 currency/scale 分桶的 paid_orders/associated_paid_minor/activity_paid_minor/refund_minor/net_minor；
activities 为同样字段加 activity_id 的 flat 数组。原币种或精度未核可为null，金额不补零。
group 绑定直接保留原 activity_id，不用访问事件猜 page_id，不另伪造 group_id。
其他字段 warnings、verified_at、scope、scanned_windows、rescan_policy 明示来源范围和历史边界。

服务器根：`CAMPAIGN_BACKEND_STATE_DIR`，默认 `/var/lib/fs-campaign-dashboard/backend`。
该根的 `policy.json` 是服务器私有配置，`operations.sqlite3` 和 `analysis.sqlite3` 不在发布/代码回退文件中。
policy 的 coupon_objects 以准确 ID 为键，包含 site_id/game_id/goods_id 和上述 proof flags；无配置即无写能力。
policy.analysis["266"] 配置实际已核 time/money contract 与完整历史 bindings，不能由浏览器提交。
catalog 产物默认 `backend/catalog-mapping.json`，只可用服务器 `CAMPAIGN_CATALOG_MAPPING_PATH` 覆盖；不改C文件。

## 尚未完成，不能签收为完整 G1

- 尚无经授权核实的本项目独占原生测试对象、status0 保存和准确 ID 停用/补偿实写证据。因此真实 edit/toggle 仍门禁，
  未实施必要经营优惠参数（门槛/折扣/范围/期限等）的编辑，也没有原生优惠生产启用验收；这些是本方工作/对象决策，
  不能统一称主站缺接口。本次只实现 title/brief + 受控启停合同，不把它说成完整优惠运营能力。
- 本项目真实 native benefit + immutable version/time bindings 尚未配置。94/99通用用券订单均不能当本活动成交。
- 原币实收、时区和精度还需服务器已核配置；退款稳定事件/行分摊还需继续查既有 Admin/Order，不声明字段不存在。
  已知订单存在 promotion_id / seckill_promotion_id，两字段业务语义尚未核，不以其名称自动认作本活动，也不扩建秒杀。
- 无更新时间/退款稳定ID接口验收，当前仅明确 paytime 窗口重扫；无自动调度/额外导出或新登录。真实持久服务接线、
  安全对象实写与原 ID 读回、187保存/发布及生产部署均待主控/授权步骤。G2权威报价、购物车、真实付款仍未接通。
- PR434 首次 merge 自动审批拒绝已确认未执行；本分支不重试或绕过该拒绝，不改变原候选状态。

本地验证入口：`python -m unittest discover -s tests`（backend目录），兼容现有 pr-fast unittest dispatcher，
无外部子进程或网络。新测试覆盖原生写门禁、single dispatch/unknown、preflight fence、请求冲突、准确范围、
真实关联语义、无绑定不归因、币种/缺失、重复重跑、失败保留快照、并发旧扫描、晚付款/历史重扫、版本冲突、
多活动去重、码大小写冲突、探针脱敏及服务器固定路径。最终运行数及 commit 见B回执。

## Q P1：对象级 pending/unknown 互斥修复

操作 ID 去重之外，账本现将 `(site_id,kind,native_id)` 与操作在同一 `BEGIN IMMEDIATE` 事务中关联并占用。
该对象存在 pending/unknown 时，新 ID 不入队、不派发，返回 object_busy=true、原 operation_id、
requested_operation_id、recovery_operation_id（及历史多占用时 recovery_operation_ids），供 UI 恢复原操作。
原状态可能 pending/not_started，但 object_busy 回执不是新 ID 的未派发终态证书，不能自动换 ID 重发。
占用由持久操作状态判定，只有可信 confirmed/rejected 或原子未派发 fence 提交后释放；unknown 无超时解锁。
旧 schema 的在途对象会在事务内补关联；若历史已有多个 unknown，全部原 ID 保留，未全部终结前拒绝新派发。
新增跨连接、重启、不同 ID 并发、Q 超时但原对象未变化复现及 fence/升级测试；未修改分析或生产对象。
