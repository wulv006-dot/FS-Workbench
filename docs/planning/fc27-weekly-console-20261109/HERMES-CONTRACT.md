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

选品规则为 `fc27_weekly_selection_v1`：Weekly Scout保留主站Popular默认推荐优先顺序，过滤普通Player后取前三；Player Trio从主站当前有效Newest标签的完整普通Player候选池选恰好3个不同模型，结合可取得的外部市场、社媒与垂类热度证据及模型判断，不机械取model ID最新前三或仅前六候选。Newest标签及候选顺序不等于热门排名；外部市场热度不等于我方销量。9个最新SBC核心各输出2个普通Player首选，合计18个全局不同球员，不由模型额外输出替代。应用层由这18人组成共享池，给每核心保存2首选＋其余16备选到原fc_layout.routes；首选稳定顺序决定默认槽位。输出必须属于对应page允许池，且普通版有当次PlayersType事实，不仅全catalog或按名字判断。源时间缺失明示ID排序依据，售价不证明可售，游戏实际SBC到期未知时为null。

所有新AI生成统一使用上述规则：手动run与周日计划走同一流水线，共享宿主拒绝缺少当前rules的新请求，输出固定24行；旧的独立SBC推荐表单及无rules新派发入口退出执行路径。人工商品编辑器的配置自由不构成AI生成例外。共享宿主先按owner及原operation_id核对请求hash：历史同ID同hash只返回原回执，变更请求冲突；GET/原ID对账继续保留，不重跑历史input、不改历史任务状态。规则标识沿用原版本字符串，不能仅据同名版本认定历史输入或回执已满足本轮新增数量与普通版规则。本轮统一入口修正处于代码及相关离线测试阶段，未部署；原已批准开启的周日计划保持，部署读回与新规则真实运行另行验收。

当前campaign模型请求只加载本模块server-owned PROMPT与经校验的冻结input，tools为空；未加载旧报告技能、旧系列配队提示或历史手动推荐模板。实际执行链为controller tick／手动run→campaign_weekly→weekly CLI当前prepare→完整Newest候选取证→campaign_recommendations→原center唯一writer。研究查询按真实搜索合同分组，不截取6个Trio候选；SBC最新核心的ID排序及Newest候选遍历顺序也不替代模型热门判断。历史脚本、回执及发布清单仅作对应版本证据，不重新接入当前自动路径。

Trio取证复用 `campaign_evidence.collect_player_evidence`，懒加载现役 `/opt/fs-game-monitor-intelligence/discovery.py` 的DeepSeek.search/fetch，不调用其模型。完整Newest普通候选传入（本轮31名，沿原模型投影上限300）；按现役Search最多128字符的真实合同动态分组，保留完整球员姓名OR、FC27限定及market/meta词，每查询一个允许站点。先交替社媒/垂类查询每组，再以余量补另一类别；保持最多12次Search、8次Fetch、180秒原总预算。姓名过长、分组超过查询预算或资料不足明确记录缺口，不截断姓名伪称全覆盖。正文姓名与FC27赛季匹配才接纳真实URL、观察时间和内容SHA；不能以Search摘要当已读原文，不能据组查询宣称31人均有市场证据。来源/context带入空tools Sol input，原文上下文有界。partial或无资料不阻断草稿：保留coverage/gaps，允许metadata-only模型判断及空evidence_indices，标明provisional/review_required，不虚构价格、交易量或热门排名，不伪称我方销量或社媒已核。共享模型只生成候选，最终Node仍按冻结源和页池核对。

原游戏情报周二/周五快照仍无campaign消费hook；本轮实现的是用户指定周日周期读取最新sbcplayer、Popular和Newest标签池，不宣称每个游戏内SBC事件即时触发。可核实范围以当次目录和证据覆盖为准；Newest新口径的代码/隔离测试与部署、真实模型验收分别记录，自然周日、长期授权撤销及外部来源稳定性仍待真实验收。

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

## 三页实价与共用码的现役来源

价格、数量、平台/区服和原生加购规格由原Admin只读观察、native_catalog/model-options及native_checkout提供，完整商品身份匹配后展示参考价；购买需有效原生绑定并在原站重新核价。周更模型只选商品，不生成金额、折扣或结账参数。原operation_id的交易审批清单是候选，不自动安装生产策略。

三页共用FCSCOUT10/6049，限定FC27顶级Items2；新草稿继承统一benefit_refs和现役私有策略。旧分页面码仅作受限兼容，不是未来生成模板。当前部署、实价、购物车正例/金币反例和原ID回执见[正式交易验收](deploy/commerce/ACCEPTANCE.md)。


## 当前已选固定组合的共享刷新（2026-11-09）

用户本轮选择先同步Trio现有4个固定Player Bundle到三页。范围来自每次prepare读取的FS `effective_fc_layout.bundles`，而不是硬编码四个模型、全部Packs类目或模型自行推荐。Node从已存 `fc_models` 取model_id，旧卡则从center目录取精确PS goods_id；原 `weekly_selection` 只接收这批最多8个 `bundle_refs`，核实真实goods→model、site266/game1327/Bundle类目，并记录当前在架/排除与三平台身份观察。人工改选改变下一轮输入；旧已冻结plan与原ID回执保持可核对，不重写历史请求。

Bundle不进入24行Sol选品结果。apply在同一center CAS草稿内更新组合范围及三页相同的平台keys/`bundle`角色；公开投影分别消费各页范围，SBC不再借Trio的活跃状态。原商业prepare为三页生成同组合的真实报价/原生binding提案，code仍FCSCOUT10、Discount6049，仅FC27 Items。旧游戏/万圣节策略保留；是否安装与发布仍由现有明确确认端点决定。公开Bundle沿原独立审阅及原生加购动作，参考报价或仅模型身份不足时购买保持不可用。
