# A2 冻结群体调查：A 候选接口与验收

本包终点：一个 host 明确授权的站点或项目 scope，沿原事实库完成冻结群体摘要、稳定候选分页、必要单客投影、两冻结版本变化及显式检查点，返回 B2 可消费的最小证据引用。没有新增客户库、采集器、定时器、业务写入或模型客户端。

本包 A 唯一改动为三个新增文件：

- `source/a2_query_context.py`
- `tests/test_a2_query_context.py`
- 本文件。

基线为 main `71cb788e8fdffab3068b278045911c910a12f093`，包含已合并 B 路由包；不修改 B 路由代码或重新验收该包。既有 Service、Store、业务口径、IAM、controller、schema、插件及发布清单均未修改。后续 B2 消费者、集成 PR、CI 接线及独审由 Personal 主控负责。

## 当前 v4 读取（PR #1352）

目录的 `current_aggregate` 提供当前合同、可读部分和参数。新分析显式传 `contract_version=fs-users-v4`，可选 `summary`、`cohorts`、`stages`、`coverage`。宿主决定站点或单项目，模型传入 scope、game 或其他身份覆盖会被拒绝。FC 系列的授权聚合从 Hermes 用户数据工具读取；单客调查仍按宿主固定的站点或单项目。老客批次不是终生首购。返回 202 后在同一宿主上下文传原 `query_id` 和合同版本续查。

显式快照按其 `contract_version` 读回，旧消费者的 `state_basis`、旧指标和证据继续按旧合同解释。V4 快照重读计两次适配器直调；直接初查、续查计一次。下方示例和首包字段表为旧版本证据。

## 创建上下文

```python
from a2_query_context import context_factory

ctx = context_factory(
    service=existing_service,
    identity=authenticated_identity,             # host 提供，不能来自模型参数
    allowed_scope={"scope": "project", "scope_id": "1327"},
    validate=host_live_scope_validator,           # (identity, scope) -> 必须严格 True
    observation=None,                            # 对齐目标后由 host 注入，见下文
)
```

项目 1327 仅是合成代表例，不是新增生产授权。首包只接受原目录中实际存在的 `site` 或 `project`。没有有效 identity/scope/validator 时五方法返回 `status=unavailable`，不读事实源；已配置 scope 撤权、跨 scope 或原 Service 拒绝时抛 `PermissionError`。

上下文内部创建同一 Store/clock 的真实 Service，其 authorizer 是原 Service 授权与 host 当前 scope 的严格交集。原实例和原 authorizer 不变。原宽页面/admin 权限不会因此生成 global-dependent 快照。旧 `requires_global_scope` 快照无法在这个窄 scope 重放。catalog 目录可见性不授数据权；所有取数仍执行原 Service.permit。

## 五个方法

| 方法 | 参数及真实行为 |
| --- | --- |
| `catalog()` | 返回宿主范围、旧 policies/definitions、旧组及 `current_aggregate` 的 v4 部分与参数。`can_read_private` 是当前 scope 下的交集权限。 |
| `aggregate(query=None, section='summary', snapshot_id=None)` | query 与 snapshot_id 二选一。query 允许 start/end_exclusive/as_of/state_basis/policy_version/policy_mode/H；scope 由 host 固定，view 固定 summary。原 checked_query 决定日期与政策是否合法。section 支持 summary/coverage/trend/cohort/trajectories；不开放跨全局矩阵。 |
| `candidates(snapshot_id, group='known_pool', cursor=None, limit=50)` | limit 严格整数 1–200；group 可为 known_pool/entered_silent/high_value_entered_silent。沿原 members 稳定 opaque ID 顺序，不是价值排名。 |
| `timeline(snapshot_id, opaque_customer_id, cursor=None, limit=50)` | 沿原 detail，仅投影该客户字段及事件 at/kind/stage。没有 email/uid/订单号/自由文本/原 orders。分页和 cursor 同样受 scope/snapshot/customer 约束。 |
| `changes_due(baseline_snapshot_id, current_snapshot_id, observation_at, explicit_refs)` | 只消费同 scope 的两个冻结快照及 host 目标检查点。没有注册客户、自动回源、后台追踪或调度。具体时点合同见下文。 |

aggregate 新 query 沿原 Service 创建原格式冻结快照，不新增表或存储格式；原 source reader 行为不会因这个适配器自动变成永不回源。**本包测试只注入合成 Store 和无真实 source client 的 Service。** 已有 snapshot_id 重放不推进到更新版本。生产接入、原 reader 的可用性和真实权限另验。

## 回执与分页

四个查询方法的通用外层为：

```text
status                         原源状态；不可比时为 incomparable
source.snapshot_id/evidence_id  原 us_/ua_，不创建第二套证据账本
source.query                   原冻结日期、scope、policy 与 state_basis
source.data_version/captured_at/scope_version/identity_version/policy_version
source.coverage/source_watermark/weekly_update/weekly_cutoff/observation_date
evidence_ref                   scope + snapshot_id + evidence_id + 本次方法/筛选/原cursor/limit
missing_fields                 purchase_cost/net_contribution/complete_refund_change_cursor
load                           service_calls/returned_rows/source_rows_scanned/elapsed_ms/
                               response_bytes_before_size_field
```

`service_calls` 仅是适配器直接调用数，不是 Admin 请求数。`source_rows_scanned='unknown'`：源 Service 可能重放原快照、扫描事实或重建私有记录，返回一页不证明后台只扫描一页。响应字节是本地 JSON 编码量，名称注明不包含 size 字段自身，不冒充网络计费。聚合的 returned_rows 为 not_applicable。

候选返回 rows/total/returned/next_cursor/complete，coverage_scope=selected_group_query；时间线返回 customer/events/total/returned/offset/next_cursor/complete，scope=selected_customer_timeline。`complete` **只表示本次调用是否从头覆盖该查询**：从第二页到末尾也为 false；`next_cursor=null` 仅代表没有后页。B2 必须保留游标链/已读页才能判断穷尽，不能用最后一页或前 N 当全集。

cursor 是带 scope/snapshot/method/group 或 customer 绑定的纯定位符，不是秘密或凭据；每次仍重做权限和原快照校验。跨快照/跨组/跨客户、坏格式及超界 cursor 拒绝，不退回第一页。原高金额组额外返回源 `selection_basis=value_segment`；它是源已覆盖销售额的筛选规则，不是净价值或净贡献排名。

### 真实合成运行结果（节选）

示例是本机测试 Store 的两个虚构客户，ID 每次重建可能不同；不是生产数据。

```python
summary = ctx.aggregate({
    "start": "2026-10-01", "end_exclusive": "2026-10-25",
    "state_basis": "period_end",
})
sid = summary["source"]["snapshot_id"]
page = ctx.candidates(sid, group="known_pool", limit=1)
next_page = ctx.candidates(sid, group="known_pool", cursor=page["next_cursor"], limit=1)
detail = ctx.timeline(sid, page["rows"][0]["opaque_customer_id"], limit=1)
```

运行中的 summary 返回 available，known_pool.value=2（customers），data_version="1"，weekly_cutoff=null；captured_at="2026-10-31T12:00:00+08:00"。截面日期仍由 query 决定，capture 时间不替代业务截止。

候选第一页返回 total=2、returned=1、complete=false、next_cursor 为不透明字符串。某条真实投影为：

```json
{
  "opaque_customer_id": "c_01cda5cfbae24ccf8ad63c17d0ffd395",
  "first_paid": {"at":"2026-10-02T00:00:00+08:00","basis":"verified_historical_first_purchase","complete":true,"missing":false},
  "observed_first": {"at":"2026-10-02T00:00:00+08:00","basis":"covered_history_first_seen","complete":false,"missing":false},
  "last_paid": {"at":"2026-10-20T00:00:00+08:00","basis":"last_effective_purchase_in_source_scope","complete":true,"missing":false},
  "purchases": {"period_orders":2,"covered_history_orders":2,"period_amount_orders":2,"covered_history_amount_orders":2,"period_amount_complete":true,"covered_history_amount_complete":true,"period_sales_usd":"20.50","covered_history_sales_usd":"20.50"},
  "amount_unit":"USD",
  "amount_basis":"whole_order_sales_not_net_contribution",
  "stage":"recent",
  "identity_reliability":{"complete":true,"missing_identity_orders":0},
  "refund_review":{"status":"requires_review","coverage":"only_reenumerated_payment_windows"}
}
```

只有原 first_verified、历史锚点和覆盖/身份证明同时足够，才给 verified first_paid。period_cohort 首笔或 earliest_observed 始终不充当可信历史 Day0。缺金额时对应 sales_usd=null，原 amount_orders/amount_complete 保留；不以缺失采购成本计算净贡献。

该客户时间线第一请求返回 total=3、returned=1、complete=false，events 第一条为 `{at: '2026-10-02T00:00:00+08:00', kind: 'first_purchase', stage: 'recent'}`，后页沿 next_cursor 读取。没有原 orders 或邮箱。

## 两版本与显式检查点

时点只能来自 host 已确认的测试目标，示例：

```python
observation = {
    "observation_at": "2026-10-29T00:00:00+08:00",
    "checks": {cid: {
        "recheck_at": "2026-10-28T00:00:00+08:00",
        # 可另给 expected_next_purchase_at；不是由本模块推导流失阈值
    }},
}
ctx = context_factory(service, identity, allowed_scope, validate, observation)
result = ctx.changes_due(
    baseline_snapshot_id=old_sid, current_snapshot_id=new_sid,
    observation_at=observation["observation_at"],
    explicit_refs=[{"opaque_customer_id": cid, "snapshot_id": old_sid}],
)
```

observation_at 必须与 host 计划为同一时点；所有时间都要明确时区。explicit_refs 最多 200 个去重 ID，必须在 host checks 中且引用两个输入 snapshot 之一。check 字段只允许 recheck_at/expected_next_purchase_at；各自到期标志均返回，最早显式检查点驱动是否需要检查。没有计划返回 unavailable，不创建调度器。

两个快照的 scope/identity/policy/contract 版本、实际 lifecycle_policy、state_basis/start/policy_mode/H 必须可比；同名政策但实际阈值不同也返回 incomparable。逆序 as_of 不比较。某客户不在两份快照中均可找到时为 requires_review，不把不存在补成 0。

实际 cutoff 取冻结 query.as_of、state_data_through 和已发布 weekly cutoff 中最早值；必须覆盖 observation_at，且源期段/身份覆盖足够，才可能给到期无新购买观察。源捕获时间不会推进 cutoff。状态可为 not_due、refresh_required、insufficient_evidence、due_with_new_purchase、due_no_new_purchase_observed 或 requires_review。计数下降/末购回退按更正复核，不能当作经营增益。

上述合成结果：旧 cutoff=10月25日用于10月29日检查，返回 refresh_required；新冻结 cutoff=10月30日且无新有效购买，则返回 due_no_new_purchase_observed、changed_fields=[]、freshness=sufficient。迟到退款更正保留旧快照并返回 changed_fields 和 review_required，不推退款原因、净价值或干预收益。

B1 最小交接直接保留 evidence_ref，以及必要的 source 版本/cutoff/coverage；候选具体 ID 再附所用页引用。此引用不保存表格正文、不授回源权限，也不能把观察时间叫业务日期。

## 验证、CI 精确接线与未验项

```text
python -m unittest discover -s releases/fs-dashboard/user-analytics-20261022/tests -p test_a2_query_context.py -v
```

本机 18 项通过：真实临时 SQLite Store/Service（recipe-v1），覆盖 205 候选穷尽及中断/重复/跨查询游标、权限交集/撤权/旧 global 快照、最小单客投影与历史首付、金额缺失、两版本迟到更正、同版本标签阈值变化、身份口径不兼容、partial/旧截止/无周发布、显式时点/尚未到期及无新单。没有真实业务/模型 API、真实数据或凭据访问。

Windows 本机缺 tzdata、不能实际表达旧 Store 的 POSIX mode 校验：测试仅对明确的 2026 年日期使用固定 UTC+08 导入夹具，仅对本次临时私有目录的 Path.stat 模拟 mode 位；没有改变文件权限、真实授权校验器、SQLite、快照重放或投影算法。Linux 环境不使用这两个适配。**Linux 实际时区、文件权限及既有 user-analytics 套件仍待 CI。** 没有安装依赖/WSL/容器。语法编译和 diff 检查通过，不据此替代运行验收。

现有 `tools/pr_fast.py` 的 `group == 'user-analytics'` 使用显式 units 列表，尚无新模块；建议 Personal 唯一维护者仅在该列表追加 `test_a2_query_context`，复用原分组/运行器，不新增 workflow 或依赖。A 没有修改这个共享文件。

后续 B2 消费者、组合模型脚本/证据交接、正式 CI 与 Business Sol High 独立审查、真实生产 scope/数据覆盖/源 reader 与部署均未验收。候选只经原分支提交给 Personal，等待同包联调；不另开零散 PR，不把本地模拟称为全套 A2/阶段2完成。
