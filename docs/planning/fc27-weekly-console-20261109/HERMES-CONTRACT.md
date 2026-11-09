# campaign_recommendation_v1

本轮新增已授权只读推荐消费者；不修改周报、管理台、普通聊天或pricing配置。用户后续确认手动触发、允许Hermes使用本人身份及真实模型做页面商品更新测试；当前尚未部署或付费调用，不启定时。实际模型及草稿测试沿真实FS会话，活动对外发布仍等批准。

沿现役 `management-november-20261103/source/range_api.py` 的8931进程增加内部路由 `/internal/hermes/campaign-recommendations`，不新增端口、服务或凭据。POST接受 `{contract,operation_id,input}`；input为三页、FC27目录身份和本期SBC来源的限定投影。模型固定gpt-6.1-sol/high；浏览器不能选择模型、工具、actor或文件路径。GET仅按原operation_id查询，不派发。

Cookie仅由当前活动后台请求的私有闭包转发；共享宿主以原8895 `/verify?group=dashboard` 每次重新校验会话及admin，并精确匹配当前server actor。不把Cookie保存到数据库、模型上下文、回执或日志；过期/撤权不能返回推荐结果。

POST先在原admission锁下原子保存独立campaign命名空间的真实tasks行和请求映射，再使用原Hermes执行池。没有假昨天、报告或pricing身份；period为null，本机run明确为host单次模型任务，不写官方worker admission文件。原TaskStore方法、队列和FC validator不改。RUNNING/lease/run_id通过原active_model_tasks识别，启动恢复仅围栏本类型任务及其未知模型账本。

独立CampaignRecommendationScope仅允许固定结构化JSON输出，不授予业务工具。沿原Grants、Proxy、ModelGateway、general provider_slot、UnifiedBudget及模型数量限制记账，重试为0，provider deadline沿原1800秒。所有请求、任务、用量和UNKNOWN保留原ID；重复POST只查原记录。

POST异步返回202 pending；GET最终返回200 completed/result/receipt，已知未派发为unavailable/not_dispatched，可能已执行为unknown。模型失败不改变活动配置或自动任务。输出仅真实catalog key且绑定source revision/update ID；推荐不等于发布、可售核验或自然周期验收。

共享改动仅新宿主模块、原scope/provider分派及现役range路由。`openai_provider`仅在明确campaign参数下允许空工具；原native请求合同不放宽。strict schema全部字段required，非SBC核心为null，禁止空enum。源码与本地假provider测试不证明部署及真实调用。

## 手动触发与未实施的自动能力

用户最终选择手动触发。当前代码具备当前用户会话提交SBC update后异步推荐、原ID查询和候选校验；没有实现无人值守的SBC逐期检测及自动派发，该能力不属于本次实施终点。现役游戏情报入口为 `ui-system/modules/game-monitor/backend/discovery.py` 的run_once/main，在现有周二/周五任务中原子发布带version、event_id、source_sha256的快照；没有campaign消费hook，通用事件合同没有SBC完整目录/逐期身份。

后续可在该任务成功发布后消费FC事件，以快照version及事件/原文SHA去重，不新定时。仍须确认SBC逐期权威来源与更新范围，接入限定campaign作用域的可信调度grant。现有人工session不能冒充长期调度身份，不能固定账号或持久Cookie。这个自动触发代码缺口与“代码已写但尚未批准启用/自然周期未验”不同，当前不能宣称自动周更完成。

会话校验只证明调用者及权限；内部端点接收的目录仍为候选请求，不能据此声称真实目录/可售/当前版本已经核验。campaign调用方继续用冻结prepared真实key及revision核对回传，不从管理员输入扩出财务或写入工具。

## 发布、兼容与回退

来源目标：hermes-v2-core/source/{campaign_recommendations,transport,openai_provider}.py、fc-review-channel/source/{fs_inprocess,proxy_gateway}.py → `/opt/fs-hermes-fc/`同名；management-november/source/range_api.py、hermes-admin-recovery/source/fc_daily.py → `/opt/fs-exact-range-20261001/`同名。共7个共享文件。现役range由总控现场核实与management-november源码按行一致，旧dashboard-refresh不进入载荷。

新增共享model_calls状态not_dispatched只用于本类型有明确网络未开始依据的调用；原not-started行、未知态和其他任务不得修改。统一预算及旧DailyReports计数均识别该状态。源码定位显示预算/日账本读取在原8931宿主；worker与FC pricing bridge使用原HTTP而非直接读账本，但发布前仍须核现场没有额外旧CLI/第二宿主。

依赖闭包须沿原publisher/admission锁协调安装，等待原模型/报告/native在途任务结束，不停FC每60分钟调度与writer。一起激活fs-business-range，验证reader版本及原入口；不因本任务重启官方Hermes worker。DB、tasks、usage、凭据和业务配置不进入回退包。

新状态一旦入账，不得整包回退到不识别该状态的旧reader。回退撤回campaign入口/消费者，同时保留proxy对not_dispatched的兼容读取及fc_daily排除未派发计数补丁；不删除或改写账本。若额外旧reader不能同窗升级，则不启用campaign消费，保护原P0链。
