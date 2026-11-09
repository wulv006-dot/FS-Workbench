# campaign_recommendation_v1

本轮新增已授权推荐消费者及周日12:00（Asia/Shanghai）草稿编排；不修改周报、管理台、普通聊天或pricing配置。用户后续确认自动加手动、允许Hermes使用本人身份及真实模型做页面商品更新测试。部署及真实模型草稿已验证，计划已按本次批准启用，见[真实验收](deploy/LIVE-ACCEPTANCE.md)；初始安装仍默认禁用，活动对外发布仍等批准，自然周期单独验收。

沿现役 `management-november-20261103/source/range_api.py` 的8931进程增加内部路由 `/internal/hermes/campaign-recommendations`，不新增端口、服务或凭据。POST接受 `{contract,operation_id,input}`；input为三页、FC27目录身份和本期SBC来源的限定投影。模型固定gpt-6.1-sol/high；浏览器不能选择模型、工具、actor或文件路径。GET仅按原operation_id查询，不派发。

Cookie仅由当前活动后台请求的私有闭包转发；共享宿主以原8895 `/verify?group=dashboard` 每次重新校验会话及admin，并精确匹配当前server actor。不把Cookie保存到数据库、模型上下文、回执或日志；过期/撤权不能返回推荐结果。

POST先在原admission锁下原子保存独立campaign命名空间的真实tasks行和请求映射，再使用原Hermes执行池。没有假昨天、报告或pricing身份；period为null，本机run明确为host单次模型任务，不写官方worker admission文件。原TaskStore方法、队列和FC validator不改。RUNNING/lease/run_id通过原active_model_tasks识别，启动恢复仅围栏本类型任务及其未知模型账本。

独立CampaignRecommendationScope仅允许固定结构化JSON输出，不授予业务工具。沿原Grants、Proxy、ModelGateway、general provider_slot、UnifiedBudget及模型数量限制记账，重试为0，provider deadline沿原1800秒。所有请求、任务、用量和UNKNOWN保留原ID；重复POST只查原记录。

POST异步返回202 pending；GET最终返回200 completed/result/receipt，已知未派发为unavailable/not_dispatched，可能已执行为unknown。模型失败不改变活动配置或自动任务。输出仅真实catalog key且绑定source revision/update ID；推荐不等于发布、可售核验或自然周期验收。

共享改动仅新宿主模块、原scope/provider分派及现役range路由。`openai_provider`仅在明确campaign参数下允许空工具；原native请求合同不放宽。strict schema全部字段required，非SBC核心为null，禁止空enum。源码与本地假provider测试不证明部署及真实调用。

## 自动与手动使用同一草稿流水线

新 `campaign_weekly.py` 在现役 `knowledge-layering-20261023/source/controller.py` 原5秒恢复循环中加独立tick，不新建后台、端口或定时器。默认禁用；人工配置须当前真实会话，owner由二次核验的actor产生，配置采用revision CAS及原operation_id去重。持久授权只含owner、active、grant_revision及操作回执，不存Cookie。每轮及研究前后、模型和草稿应用前，用类型化CampaignDelegation核对原宿主、当前授权revision/active和原authorizer；撤权立即阻止后续阶段。旧report scheduler固定owner及其执行时段不借用。

宿主路由 `/internal/hermes/campaign-weekly`：GET无query读取当前配置及当前owner最近20条流水线；GET `?operation_id=UUID`只查询/对账原模型和原草稿回执，不派发或应用。POST仅接受 `{action:'run'|'reconcile'|'resume',operation_id}` 或 `{action:'configure',operation_id,revision,enabled}`。configure超时可按原ID读取immutable配置回执，再读最新配置；不能以历史回执重启已撤销计划。恢复草稿应用是当前真实会话显式resume，复用原模型和原center操作ID，不重派模型。

周日当地12:00后原tick按due_day只提交一次；手动run走同一prepare→证据→模型→apply_draft流水线。Node CLI `/opt/fs-campaign-dashboard/analytics/weekly-cli.mjs` 只连接原管理进程root-only Unix socket，由原center唯一writer完成prepare、apply_draft和inspect_operation。冻结plan_ref/owner/源revision，apply只保存原center草稿，CAS/未知态沿原ID，不发布。Hermes辅助开关与周更授权分别核验；schedule.enabled不绕过辅助关闭。

选品规则为 `fc27_weekly_selection_v1`：Weekly Scout保留主站Popular默认推荐优先顺序，过滤普通Player后取前三；Player Trio从最新普通Player池选恰好3个不同模型。9个最新SBC核心各输出2个普通Player首选，合计18个全局不同球员，不由模型额外输出替代。应用层由这18人组成共享池，给每核心保存2首选＋其余16备选到原fc_layout.routes；首选稳定顺序决定默认槽位。输出必须属于对应page允许池，且普通版有当次PlayersType事实，不仅全catalog或按名字判断。源时间缺失明示ID排序依据，售价不证明可售，游戏实际SBC到期未知时为null。

9核心/18人约束仅适用于输入携带该周更rules的流水线；未携带rules的既有手动推荐保持其原候选合同，不自动扩成9核心周更。规则标识沿用原版本字符串，不能仅据同名版本认定历史输入或回执已满足本轮新增数量与普通版规则。本轮修正处于代码及相关离线测试阶段，未部署；原已批准开启的周日计划保持，部署读回与新规则真实运行另行验收。

Trio取证复用 `campaign_evidence.collect_player_evidence`，懒加载现役 `/opt/fs-game-monitor-intelligence/discovery.py` 的DeepSeek.search/fetch，不调用其模型。最多6球员、有界社媒/垂类查询，正文姓名匹配才接纳真实URL、观察时间和内容SHA；来源/context带入空tools Sol input。partial或无资料不阻断草稿：保留coverage/gaps，允许metadata-only推断及空evidence_indices，标明provisional/review_required，不伪称社媒已核。共享模型只生成候选，最终Node仍按冻结源和页池核对。

原游戏情报周二/周五快照仍无campaign消费hook；本轮实现的是用户指定周日周期读取最新sbcplayer/Popular/Player，不宣称每个游戏内SBC事件即时触发。可核实范围以最新目录和证据覆盖为准；自然周日、长期授权撤销及外部来源稳定性仍待真实验收。

会话校验只证明调用者及权限；内部端点接收的目录仍为候选请求，不能据此声称真实目录/可售/当前版本已经核验。campaign调用方继续用冻结prepared真实key及revision核对回传，不从管理员输入扩出财务或写入工具。

## 发布、兼容与回退

共享源码→目标（发布载荷不含测试、账本或凭据）：

| 仓库源码 | 目标 |
| --- | --- |
| releases/fs-dashboard/hermes-v2-core-20261020/source/campaign_recommendations.py | /opt/fs-hermes-fc/campaign_recommendations.py |
| releases/fs-dashboard/hermes-v2-core-20261020/source/campaign_weekly.py | /opt/fs-hermes-fc/campaign_weekly.py |
| releases/fs-dashboard/hermes-v2-core-20261020/source/campaign_evidence.py | /opt/fs-hermes-fc/campaign_evidence.py |
| releases/fs-dashboard/hermes-v2-core-20261020/source/transport.py | /opt/fs-hermes-fc/transport.py |
| releases/fs-dashboard/hermes-v2-core-20261020/source/openai_provider.py | /opt/fs-hermes-fc/openai_provider.py |
| releases/fc-coins/fc-review-channel-20261026/source/fs_inprocess.py | /opt/fs-hermes-fc/fs_inprocess.py |
| releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py | /opt/fs-hermes-fc/proxy_gateway.py |
| releases/fs-dashboard/knowledge-layering-20261023/source/controller.py | /opt/fs-hermes-fc/controller.py |
| releases/fs-dashboard/management-november-20261103/source/range_api.py | /opt/fs-exact-range-20261001/range_api.py |
| releases/fs-dashboard/hermes-admin-recovery-20261020/source/fc_daily.py | /opt/fs-exact-range-20261001/fc_daily.py |

共10个共享文件。现役range由总控现场核实与management-november源码按行一致；controller与knowledge-layering源码字节一致，旧dashboard-refresh和hermes-conversation历史副本不进入载荷。campaign Node CLI/IPC及界面沿原campaign app发布闭包，见本任务总发布清单。

新增共享model_calls状态not_dispatched只用于本类型有明确网络未开始依据的调用；原not-started行、未知态和其他任务不得修改。统一预算及旧DailyReports计数均识别该状态。源码定位显示预算/日账本读取在原8931宿主；worker与FC pricing bridge使用原HTTP而非直接读账本，但发布前仍须核现场没有额外旧CLI/第二宿主。

依赖闭包须沿原publisher/admission锁协调安装，等待原模型/报告/native在途任务结束，不停FC每60分钟调度与writer。一起激活fs-business-range，验证reader版本及原入口；不因本任务重启官方Hermes worker。DB、tasks、usage、凭据和业务配置不进入回退包。

新状态一旦入账，不得整包回退到不识别该状态的旧reader。回退撤回campaign入口/消费者，同时保留proxy对not_dispatched的兼容读取及fc_daily排除未派发计数补丁；不删除或改写账本。若额外旧reader不能同窗升级，则不启用campaign消费，保护原P0链。
