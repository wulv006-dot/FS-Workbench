# 周更接入与发布清单

## 已实现入口

原服务前缀 `/dashboard/analytics/campaigns/analytics/`：

| 入口 | 行为 |
|---|---|
| `weekly.html` | 运营台；原活动分析首页、商品编辑页均有入口 |
| `GET api/weekly` | 当前三页映射、校验、工作单、历史、审批、原操作摘要与Hermes状态 |
| `POST api/weekly` | 工作单与证据/审核记录；继承FS管理员、Origin与CSRF验证 |
| `GET api/weekly/recommend` | 持久候选历史、原operation_id及过期状态 |
| `POST api/weekly/recommend` | 显式准备/请求本期候选；固定模型gpt-6.1-sol、高推理；不发布 |
| `POST api/weekly/reconcile` | 按原operation_id查询异步宿主；不再次派发模型调用 |

写入请求保留 UUID `operation_id`；同ID不同内容409，同ID同内容核原结果。周更记录请求的revision来自GET api/weekly；推荐请求的revision是当前活动中心revision，不能用周更账本revision代替。

`api/weekly`动作：create、update、review、approval、pause、retry、evidence、hermes。scope为publish/coupon_write/schedule_enable/rollback只描述待批准动作，不直接执行。页面显示的operationId是计划创建ID；真实执行/回执使用独立execution_operation_id，并保留关联关系，不混同。

## 后续真实接入

### Hermes provider

`production-server`按请求创建provider闭包，将当前已验证会话转交现役8931内部推荐入口；Cookie不进入候选输入、文件或模型。宿主再次验证会话及actor，使用独立campaign任务身份和现有模型额度。宿主协议及共享调用链见HERMES-CONTRACT.md。实现与离线测试不证明真实Sol已部署可用。

provider接收 `prepareWeeklyRequest` 的明确model、reasoning_effort、instructions、input、response_schema及超时AbortSignal；返回对象必须回显model、source_revision、sbc_update_id，并只引用输入目录内的product_key。SBC同时要求合法core_product_key，平台错配/可售未知/过期/来源缺失均带待核原因。

每期更新输入包括id、observed_at、可选expires_at、context与sources（HTTPS来源、title、observed_at）。按用户最终确认，由人工登记并触发；允许使用用户身份和真实模型验收商品更新，仍核实际会话。源码不自行抓取游戏更新、不自行启动定时、不自动发社区消息。推荐准备与身份匹配不等于SBC阵容规则已验证。

调用前持久pending，operation_id/hash与输入内容按操作者去重，超时/中断保留unknown；不得换ID重放未知模型请求。持久保存经过限定的task/run/usage回执，显式reconcile只查询原ID。关闭辅助层不影响center、公开页面、已有计划与候选历史。

### 可信测试、发布与自然运行回执

`makeWeeklyStore().recordEvidence(record)`只供可信服务器适配器调用，未暴露为浏览器可自证的HTTP入口。record绑定周次/page_id、活动/商品/优惠revision、plan_operation_id、来源/reference、stage与result；部署证明还核当前发布release_id/config_hash，自然运行要求scheduled触发。原unknown后续核验须携带原execution_operation_id。

浏览器登记只生成reported，不能填写verified。测试通过、生产验证、部署读回、自然周期互不替代。历史check_snapshot保留创建时结果，当前checks注明current_center；审批保存历史并对三个版本检查失效。

### 效果追踪

复用现有活动组fc27-season2与原分析/优惠对账入口。当前不构造虚假单页收入或转换率。将来回流需将真实page_id、release/config版本、周次与operation关联；未证明的单页成交归因保持缺口。

## 本批待批准部署

管理端新增weekly.html/js/css、weekly-store.mjs、weekly-hermes.mjs、weekly-recommendations.mjs、weekly-hermes-provider.mjs；修改production-server.mjs接线及index.html/products.html入口。共享Hermes增加campaign宿主模块、原scope/provider分派及现役range路由。测试、文档与pr_fast不进入线上业务载荷。具体候选文件哈希及共享源映射见RELEASE-CANDIDATE.json。

2026-11-09只读核对：现有管理与公开运行服务active；production-server/index/products的线上哈希与main基线一致；weekly.html尚不存在。operations.html存在独立线上差异，本批不修改。

管理端发布沿现有 `navigation/release_ui.py` 所用的活动管理增量发布路径，保留原锁/CAS/备份/回执，激活 `fs-campaign-dashboard.service`，不重启公开结账 `fs-campaign-runtime.service`。不要直接运行通用publish.py的全服务restart。共享宿主另沿其现役发布入口核对载荷与激活影响，保护现有模型任务及FC P0链路。本文件是候选清单，不是已批准部署manifest；执行前必须刷新现场CAS并核原publisher输入。

仅部署管理端而未部署共享宿主时，推荐明确不可用。管理端及共享宿主部署、真实模型测试、活动发布、券写、定时和回退分别按具体范围批准；本批未执行这些动作。回退保留center数据库、周次/推荐记录、原ID及所有运行账本。
