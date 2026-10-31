# DeepSeek主办与候选模型验证工作包

沿唯一主方案阶段2/B1，不另建路线。用户最新确认：模型先测试验证，待相关API额度与配置就绪后才正式切换；现阶段相关模型工作沿DeepSeek。代码合并授权不增加真实模型调用、费用、部署或业务写入权限。

## 基线、归属与终点

原Personal分支t3/550049c1，开工fetch/ff main为56204866386376e148f5fc04626b0edf474b50f8，工作区干净。该基线含PR708，最终reviewed head cc16343739bcb69783023b38afe0994b7a5849b4已由Business Sol High独立worktree复查通过，原元数据损坏P2已闭环，必要CI41211850822成功；无生产部署。

Personal B独占hermes-v2-core-20261020/source/b1_model_routing.py、test_b1_model_routing.py、新test_b1_runtime_policy.py及test_core.py加载，主控维护本目录正式主文件/本包记录。A保持会话、查询、HTTP、存储和文件底座独占，本包不改共享controller/schema/迁移/发布清单、原direct_provider或生产配置。一个完整PR交付“当前模型选择策略＋单次原客户端执行契约＋无调用候选验证＋本地验收”，不是模型切换或运行时装配交付。

## 实际行为

- select_model默认mode=deepseek_only，普通/复杂任务都先按原通道授权、输入/工具能力和available过滤，仅DeepSeek可执行选择；只有OpenAI候选可用时返回unavailable，不静默改派。图片等能力不足仍说明不支持，不假装DeepSeek能替代未核能力。
- host可显式给contract_validation，在保留权限/能力过滤后比较候选，invocation_allowed=false。即使候选为DeepSeek也不调用客户端；该模式是本地验证，不授予正式启用，也不自动补齐额度/配置/实测。
- run_deepseek_task消费受信host的request_id、任务、能力和工具列表，根据真实request.tools判工具需求；模型名必须与选择一致。只委托原注入DeepSeek客户端一次，request/tools/deadline保留，任务ID/候选策略不混进原生payload；client_invoked只表示注入函数调用，不代表网络或模型已执行。
- 返回原provider_result及本任务request_id，保留原提供方回执；未标任务整体完成。传输异常unknown不含私有异常文本，不自动重试/换供应商；同ID的后续恢复/对账由既有host处理，本函数不实现任务持久化或分布式去重。
- 原DeepSeekAdapter/OpenAIAdapter和最小handoff保留。OpenAI仍是原文本离线子集，不支持工具/图片/多轮完整Agent；真正扩展和正式启用另验，不借validation mode绕过。

## 验收与依赖

原B1及新执行策略直接25项通过，原pr_fast.units Core入口108项通过、0失败/0skip（含原DeepSeek及材料/HTTP回归）。新测试含默认复杂任务保留DeepSeek、候选可用但不启用、无授权/工具/图片能力缺口、验证模式零调用、model不一致拒绝、参数/截止/原ID不变、unknown单次与异常脱敏、配置/截止失败不冒充完成；还通过真实原direct_provider.prepare_request/request_model与mock _open检查native max/effort/thinking/tools/stream及回执，未读凭据、未发外部网络请求。CI/独审结果待固定head后补，不用模拟冒充真实API验收。

A已完成A2本机只读核对：可复用user-analytics的Service.catalog/query/members/detail/private_snapshot及冻结us_/ua_引用；现有页面/admin权限不等于任意员工细粒度scope。后续独立A包应注入服务端身份与明确scope，最小投影/分页，零真实业务请求；B2定义筛选/价值/到期，不重写A事实与查询。tracking旧源端口描述不代表当前活动状态，直API已有改造记录，不能恢复8767或legacy due_reports。

主控已向A发出下一完整A2包接口对齐：A唯一维护新增user-analytics-20261022/source/a2_query_context.py及tests/test_a2_query_context.py和模块说明，不改既有DB/采集/调度/controller/公共schema/IAM/插件/发布清单；factory提供catalog/aggregate/candidates/timeline/changes_due。可信host注入明确identity/scope和逐调用校验，缺有效scope则unavailable。先以known_pool穷尽覆盖及原entered_silent做合成案例，limit<=200；可信历史Day0与期间首笔/观察首见分开，显式检查点超出冻结截止则补证，不假报到期仍未复购。B2后续消费该上下文，A完整候选由Personal正常merge后一个最终集成PR，不与本独立B路由包混淆；未取得实际A实现/测试/提交前不计交付。

未验：host会话实际调用本入口、真实模型/账号额度/配置、生产装配/认证/部署、完整B2动态追踪。本包再次运行knowledge_closeout.py plan --base 56204866，仍为原91项中30项native_plugin_exact_registration_delta_required错误，未生成成功收尾，不修改无关publisher或放宽校验。
