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

写入请求保留 UUID `operation_id`；同ID不同内容409，同ID同内容核原结果。周更记录请求的revision来自GET api/weekly；推荐请求的revision是当前活动中心revision，不能用周更账本revision代替。

`api/weekly`动作：create、update、review、approval、pause、retry、evidence、hermes。scope为publish/coupon_write/schedule_enable/rollback只描述待批准动作，不直接执行。页面显示的operationId是计划创建ID；真实执行/回执使用独立execution_operation_id，并保留关联关系，不混同。

## 后续真实接入

### Hermes provider

`makeWeeklyRecommendations({dir, contextProvider, enabledProvider, provider})`接受既有宿主提供的provider函数。当前production-server未传provider，明确返回unavailable。此状态不能记为真实Sol可用。

provider接收 `prepareWeeklyRequest` 的明确model、reasoning_effort、instructions、input、response_schema及超时AbortSignal；返回对象必须回显model、source_revision、sbc_update_id，并只引用输入目录内的product_key。SBC同时要求合法core_product_key，平台错配/可售未知/过期/来源缺失均带待核原因。

每期更新输入包括id、observed_at、可选expires_at、context与sources（HTTPS来源、title、observed_at）。宿主应从已授权游戏更新数据源构造输入；浏览器可人工登记。源码不自行抓取游戏更新、不自行启动定时、不自动发社区消息。推荐准备与身份匹配不等于SBC阵容规则已验证。

调用前持久pending，operation_id/hash与输入内容去重，超时/中断保留unknown；不得换ID重放未知模型请求。关闭辅助层不影响center、公开页面、已有计划与候选历史。

### 可信测试、发布与自然运行回执

`makeWeeklyStore().recordEvidence(record)`只供可信服务器适配器调用，未暴露为浏览器可自证的HTTP入口。record绑定周次/page_id、活动/商品/优惠revision、plan_operation_id、来源/reference、stage与result；部署证明还核当前发布release_id/config_hash，自然运行要求scheduled触发。原unknown后续核验须携带原execution_operation_id。

浏览器登记只生成reported，不能填写verified。测试通过、生产验证、部署读回、自然周期互不替代。历史check_snapshot保留创建时结果，当前checks注明current_center；审批保存历史并对三个版本检查失效。

### 效果追踪

复用现有活动组fc27-season2与原分析/优惠对账入口。当前不构造虚假单页收入或转换率。将来回流需将真实page_id、release/config版本、周次与operation关联；未证明的单页成交归因保持缺口。

## 本批待批准部署

仅新增六个管理端文件：weekly.html/js/css、weekly-store.mjs、weekly-hermes.mjs、weekly-recommendations.mjs；修改production-server.mjs接线及index.html/products.html入口。测试、文档与pr_fast不进入线上业务载荷。具体候选文件哈希见RELEASE-CANDIDATE.json。

2026-11-09只读核对：现有管理与公开运行服务active；production-server/index/products的线上哈希与main基线一致；weekly.html尚不存在。operations.html存在独立线上差异，本批不修改。

发布沿现有 `navigation/release_ui.py` 所用的活动管理增量发布路径，保留原锁/CAS/备份/回执，只激活 `fs-campaign-dashboard.service`，不重启公开结账 `fs-campaign-runtime.service`。不要直接运行通用publish.py的全服务restart。本文件是候选清单，不是已批准部署manifest；执行前必须刷新现场CAS并核原publisher输入。

人工批准仅运营台部署时，Hermes仍未连接真实provider、自然计划仍未启用、活动配置与优惠券保持原值。真实provider接入/测试、活动发布、券写、定时和回退分别按具体范围批准。回退保留center数据库、周次/推荐记录、原ID及所有运行账本。
