# 客单追踪本轮来源与增量合同

2026-11-09；本地实现及只读现场核验，未提交、未部署、未生成真实报告。

当前维护源为`releases/fs-dashboard/hermes-customer-lifecycle-20261019/source/`，原README和deploy/release_scope明确目标为`/opt/fs-hermes-fc/`。20261018的SOURCE-MAP/CURRENT-SOURCE-MAP是历史首发与后续覆盖记录，不能据其旧SHA覆盖当前服务。

## 固定只读合同

原`GET /dashboard/fs-home/advisor.json`增加固定`mode=hermes&structure=customer_tracking&stored_only=1`分支：

- `view=candidates&day=YYYY-MM-DD`，沿原日期验证与Store.candidates。
- `view=detail&id=<32位小写hex>`，沿原Store.detail。

`tracking_readonly.stored_get(controller,user,params)`前后复核原AdminService._admin，复制当前Store/AdminService引用，仅替换此次查询的数据库上下文为SQLite `mode=ro`和`PRAGMA query_only=ON`；不构造Store，不迁移库，不调用轮询、observe、客户端查询或队列。保持原HTTP管理员可读范围，不误套tool_read专属owner限制。返回原业务结果加`stored_only=true/refreshed=false`；候选date改为原HTTP使用的day。pending/failed/unavailable、空完整扫描与缺少扫描保持区别。

`fs_mcp_connector.tracking.project(value,view)`支持config/candidates/tracked/detail/request，固定业务字段投影，保留原覆盖、分页和刷新标记。按用户本轮明确授权保留email、UID、原order_no、buyer_id及原订单金额/明细；只去凭据，未知形状明确报错。依赖仅连接器redaction及原export脱凭据正则，无动态加载历史域模块，无金额计算复制。

## 撤销旧模型身份禁令

用户本轮要求在原admin/private/owner/session和对象权限内可以返回客户身份及订单明细，并删除旧限制本身。当前及20261018消费源的tool_read改用customer_snapshot，保留原paid聚合同时返回经过原Store规范化的email/UID/订单明细；anonymous_snapshot仍可独立按需使用。原owner检查、历史刷新、日常自动化和业务公式不变。

手动池报告及旧报告prompt提供email/UID和原tracking_id/customer_ref详情查询引用；原订单号与完整明细仍可通过获准detail/tool_read查询，不将所有原始行或无界原单号索引重复塞入报告证据。1000条正常长度原单号的回归保持原聚合完整和报告容量。原12000字符对话边界、16000字符存储边界、幂等、CAS和UNKNOWN处理保持；bind_report仅移除“出现邮箱就拒绝”的旧规则。旧customer_reports不会因此恢复已退役自动报告，cohort普通用户权限亦不改变。

README、原learning/CUSTOMER-METHOD和PHASE2-HANDOFF已更新本次授权。`knowledge/reviewed/<sha>/.../APPLICATIONS.md`内旧句保留哈希历史，本轮明确不再作为现行规则。若原published route仍选择含旧句的reviewed版本，须沿原知识/技能发布器生成新reviewed版本和索引SHA，绑定原允许的modules/entry_ids，再更新对应route/published catalog并读回；不得原地改不可变目录或将Git候选标成线上知识。实际原选择器也支持approved_current；当前线上选择必须现场核验，仓库无对应生产reviewed-skills索引，不能从目录存在推断活跃引用。知识closeout由主代理统一执行。

## 现役漂移与发布边界

只读现场文件SHA256：

| 现役目标 | 2026-11-09 SHA256 |
|---|---|
| `/opt/fs-hermes-fc/tracking_controller.py` | `aca0112a5e0e66ad37cb579d143048bece12c324b1107b6a85a07b092c81ba0a` |
| `/opt/fs-hermes-fc/customer_tracking.py` | `dd705535ce72f1b879a530c30323f827e6a951e8d850d9ee3f3a9da1184584ef` |
| `/opt/fs-hermes-fc/tracking_tool.py` | `c030922096ba66c33cebf1638fc1dfa560ab79e3a5927155b59d919a722d4be9` |
| `/opt/fs-hermes-fc/pool_reports.py` | `51fef33b1ebe26f16a4dba59667988b3e71f979706487d0b80707a52a4d3b52a` |
| `/opt/fs-hermes-fc/research.py` | `db872850d2aa183c120476277e6976821d285045404b6ee71abb379f973d8bdc` |

现场尚无stored_only或customer_snapshot，research工具描述仍强制匿名。Store.db/config/candidates、AdminService._admin/get与本地当前源的方法原文SHA一致；Store.detail有漂移：现场没有本地新增buyer_identity_evidence字段，但其现役实现仍仅SELECT，读取原身份、历史覆盖、milestones和orders。

需变更方法的现场原文SHA256（AST source segment，UTF8/LF，不含装饰器）：

| 文件/方法 | SHA256 |
|---|---|
| customer_tracking.Store.bind_report | `7dfa19590470c7d22cafdf1f31d17a80c3fb292c6c9a1f4152d8e3272ac5ac07` |
| tracking_controller.TrackingController.tool_read | `34626a9e1131cde8c4f194d845f67e31da0431b7cd617cf7f340d3e3f9aa868c` |
| tracking_controller.TrackingController.get | `afedbc0daaf21609bf47cf18eb96ba134441080b9861b910d38bbb7d6207ce01` |
| tracking_tool.anonymous_snapshot | `746c9f9311df2f7bec12ae8d524e31b65024d6519cd8d948ed293d3a9f01ab27` |
| pool_reports.pool_evidence | `4aef2abea324d7b53da1750f2fa5cc44b3025c8224dfb0a2586175648881c572` |
| customer_reports.report_prompt | `d2d76d48edcf62a0d0d2c8d19252115feab8120244ebd318b541e0b6d33bfa7e` |
| research.tool_schemas | `9ac8f497e204b691123ca796066dce38ac2262c4641fb742dcad98b502e0edd7` |

最小发布应从这些现场版本装配：controller只加stored_only分支和customer_snapshot调用；tool只新增customer_snapshot及必要import；Store只移除bind_report邮箱拒绝；pool只增加获准身份和详情引用说明；research只更新客户追踪工具描述，不覆盖cohort规则；旧报告prompt按当前是否仍消费核定最小增量，不启用退役调度。原prepare_release/release_bridge/release_scope已补tracking_readonly闭包，新增目标`/opt/fs-hermes-fc/tracking_readonly.py`。必须重新生成本次精确manifest、核现场CAS与原空闲/备份/回退，不能重放历史整包或把本地customer_tracking/research全文覆盖线上。

现场检查脚本在忽略目录`.agent_runtime/connector/inspect_tracking_source.py`、`compare_tracking_methods.py`、`inspect_tracking_detail.py`、`inspect_tracking_authorization.py`、`inspect_tracking_change_methods.py`；仅输出结构/函数名/哈希，不导出客户数据。
