# 材料分析文件工具工作包

本包沿唯一长期主方案阶段1/2推进，一个最终集成草稿PR，由Personal创建维护。包内修复持续更新原PR；相关测试、接口对齐和交付条件齐备再转正式，一次汇总。A不另开PR，不按函数或单次进度拆包。当前基线09c4809d43efd68271631070e0895dbf45e227c2（PR704/705/706均已合并），无部署或真实模型/业务写入授权。

## 终点与验收范围

本地真实合成CSV/XLSX字节上传→显式绑定turn→模拟Hermes工具循环经原task/lease及A上下文权限调用目录/分页读取/有限修改→不可变版本产物→原鉴权下载→新turn显式绑定产物继续修改。完整读取声明须有覆盖；越权、撤权、取消/终态、过期、重复/变更request_id及unknown保持原身份。mock worker只验证接线，不算真实模型任务；没有前台或生产验收不得宣称已上线/首条真实材料任务完成。

不把任意代码计算、全站配额、定时清理、公开联网、A2用户查询或真实模型测试塞成本包前置；这些原缺口仍保留，不标A1整体通过。本包聚焦有明确来源的有限表格修订与导出，不新增后台采集器、凭据、数据库迁移或发布器。

## 单一维护者与已确认接口

用户已转交A明确认领与确认：

| 路径 | 唯一修改者 |
|---|---|
| releases/fs-dashboard/hermes-conversation-20261018/source/conversation_files.py、conversation_http.py、conversation_store.py、新conversation_file_bindings.py及A对应tests/交付文档 | Business A |
| releases/fs-dashboard/hermes-v2-core-20261020/source/conversation_service.py接点 | Business A |
| releases/fs-dashboard/hermes-v2-core-20261020/source/conversation_file_tools.py、test_conversation_file_tools.py、test_core.py测试加载及本包集成证据 | Personal B |
| releases/fs-dashboard/hermes-v2-strategy-20261021/source/runs_contract.py | Personal B |
| releases/fs-dashboard/hermes-v2-strategy-20261021/source/proxy_gateway.py及releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py | Personal B |
| 唯一主文件及本工作包记录 | Personal主控 |

runs_contract来源沿STRATEGY-SOURCE-MAP；21版proxy为它的既有消费者，26版proxy为后续渠道修复候选，release_adapter声明相同runtime目标。两者必须同样追加工具schema并在无turn上下文时拒绝文件调用。旧core/pilot历史proxy不改。当前生产活动源码仅据仓库记录，未现场验证；不能将这些候选路径声称为已部署。worker无需修改，既有代码动态读取同一schemas/WIRE_TOOLS；新模块在未来发布载荷的装配另验，本包不修改发布清单。

A接口：context_factory(store, owner, cid, turn_id, authorized)返回服务端闭包，每次catalog/read_table/revise重新核authorizer、owner、turn状态queued/running及过期；仅显式绑定输入与同turn派生产物。submit可选file_ids去重排序最多10，幂等摘要包含集合；sidecar沿原DB锁，无公共schema迁移。

B接口：attach_conversation_file_tools(book, context)；file_prompt(context=None)为静态字符串，不调用catalog或提前读取preparing turn。三个工具为fc.list_conversation_files、fc.read_conversation_file、fc.revise_conversation_file，wire沿mcp__fcro__前缀。模型参数没有身份/cid/turn/URL/path。读取必须带file_id/sheet/offset/limit（limit<=200）；修改带file_id/edits/format/request_id，只委托一次，不自动重试。

A读取回执保留sheets/sha256/complete/truncated/next_offset及coverage，scope=selected_sheet的complete不等于workbook完整。B深拷贝原回执并加material_role=untrusted_data，不把整表再次register进ResearchBook证据数据库。产物沿原metadata及鉴权download_url，无公开访问或token链接。

## 实际进度与证据

- B消费者/代理实际源码契约11项通过；原Core入口合计83项通过；原渠道修复12项通过，未调用模型/API。
- strategy本机Windows套件24项未通过（2fail、22error），错误涉及simulation_engine_changed及旧JS/发布目标原始字节；相关文件未改。尚未据此声称基线同失败或Linux通过。新源码schema/allowlist一致性另有直接测试；保持原门禁，组合LF/Linux检查仍需取得实际结果。
- A报告独立26项、deploy10项、Core72项通过；已准备组合test_conversation_file_loop.py，待B候选合入A分支运行，主控此时尚未独立验收。
- A与B已通过现有两条线程直接交接，未新建Agent/线程。A完整候选提交后由Personal正常merge入同包，再做组合验收，最终一个集成草稿。
- 原知识收尾Windows字节失败保留；本包按规则准备候选与测试，不声称已知识发布/生产装入或Notion同步。
