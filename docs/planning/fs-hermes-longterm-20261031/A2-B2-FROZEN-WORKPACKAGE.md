# A2/B2冻结调查与显式追踪工作包

沿唯一主方案阶段2，不新增路线。用户现阶段保留DeepSeek，候选模型仅验证；本包没有模型/业务API、生产认证或部署动作，也不宣称完整用户运营闭环已上线。

## 终点、基线与唯一维护者

一个host授权scope内，用原冻结群体摘要、候选分页与最小单客时间线，对两个事实版本和明确检查点给出可追溯付款观察、缺项与下一步，再交B1最小引用。没有新客户库、采集器、目标持久化或调度器，不恢复legacy due_reports。一个最终集成PR，包内修复留同PR，最新完整head由Business Sol High独立worktree审查、必要CI通过后按授权普通合并。

主控开工fetch/ff main=71cb788e8fdffab3068b278045911c910a12f093，干净；该基线PR709的reviewed head cbc2799b41d0f44b70d44dba415f3ca32897688e已独审通过，CI41214989116/41215336533成功，默认DeepSeek/候选验证包代码已合并、未运行时装配。随后正常merge A候选7ee41c0a506b75f04d933e8a4aa101c148a81a78，仅三文件，不读取A未提交目录。

| 路径（releases/fs-dashboard/下，除另标） | 本包唯一维护者 |
|---|---|
| user-analytics-20261022/source/a2_query_context.py、tests/test_a2_query_context.py、A2-QUERY-CONTEXT.md | Business A，固定候选7ee41c0a；B不并改 |
| hermes-v2-core-20261020/source/b2_frozen_investigation.py、新test_b2_frozen_investigation.py及test_core.py加载 | Personal B |
| tools/pr_fast.py | Personal唯一维护：仅原user-analytics units列表追加test_a2_query_context，A已明确不并改 |
| 本工作包、唯一主文件 | Personal主控 |

controller、公共schema、迁移、插件、IAM、原查询/DB、采集/调度、原DeepSeek和发布清单保持各自原归属，本包未修改。

## A接口与真实边界

完整合同沿A2-QUERY-CONTEXT.md及固定源。context_factory(service,identity,allowed_scope,validate,observation)创建同Store/clock的Service受控实例，authorizer为原授权与host当前scope严格True交集，不能从页面/admin宽授权继承global；每次源查询仍经原permit。无有效scope返回unavailable且不读源，撤权及旧global-dependent快照拒绝。身份/scope/观察计划由host注入，不是模型参数。

catalog/aggregate/candidates/timeline/changes_due复用原us_/ua_、事实版本、覆盖及周截止。候选按opaque ID稳定排序，不是净价值排名；时间线仅投影必要字段。first_paid只在源证明可信历史Day0时verified；期间首笔/观察首见不冒充历史首购。候选与时间线complete只表示单次请求从头覆盖，末页next_cursor=null本身不是全量证据。

changes_due只读两个冻结版本，检查显式host时点，不注册追踪或自动回源。scope/identity/实际lifecycle policy等不兼容返回incomparable；cutoff不足、partial或退款更正不补0。具体源码可复用不代表真实生产scope、更新游标或活动装配已验。

## B实际消费者

- page_chain消费实际A分页回执，绑定scope/snapshot/版本/查询与cursor，检查总量、返回数、稳定候选顺序、重复/缺页和时间线offset；只有从头沿完整链读到total才声明enumeration_complete。host给每条链page_budget，预算结束返回partial及next_cursor，不丢弃已核局部观察；从末尾单独重放永不称全集。
- investigate重放两个明确冻结snapshot，读取host显式选择的必要客户（最多200，与A观察计划一致），消费changes_due并调用原b2_customer_followup.assess。不把原聚合、授权、分页源或生命周期算法另实现一套。
- source_as_of取query.as_of/state_data_through/weekly_cutoff最小，observation_at为host检查点，now为host当前评估时点，三者分开；来源不能来自未来，capture时间不能推进业务截止。两snapshot原引用和版本均保留。
- 结果保留source付款观察（未到期/需刷新/有新付款/到期未见新付款/需更正复核），同时保留B2因退款/身份/历史缺口的needs_evidence。已有局部事实可指导下一步调查，不因此称流失概率、净贡献或干预收益。选项含no_intervention和只读investigate_evidence；没有触达/发券/改价写入。
- 原request_id保留，unknown/pending/unavailable不自动重试或换快照；已读页最小引用保留。撤权抛PermissionError，不返回之前私有结果。停止目标在读catalog前返回。
- 最终结果不包含205名候选正文或时间线明细。B1 evidence使用原scope/us_/ua_/query/cursor和来源版本，首末页引用+页链摘要及明确覆盖/缺项；不建第二套证据账本，引用仍须A鉴权，源保留不足不靠hash冒充可回源。
- load记录实际context方法调用次数和本地JSON响应字节，source_rows_scanned仍unknown；不把小返回体等同后台少扫描、网络账单或模型费用。

## 本地验证与未验项

Personal已独立运行A2 18项合成测试，以及B2组合16项；原pr_fast.units Core入口124项通过、0失败/0skip，包含B1/DeepSeek、B2、材料与HTTP回归。组合使用真实合成SQLite Store/Service/A2上下文、B消费者和原B1 handoff，无真实模型/业务API。覆盖205候选、完整/中断/重复/末页链、来源版本变更、scope错配、必要时间线、旧截止、迟到退款/末购回退、不可比快照、撤权、unknown原ID与已读引用、停止零读取；也验证partial历史中晚于保守截止的付款降级缺项，不作为未来事实或让整个调查崩溃。handoff不含邮箱/订单/整客正文。pr-fast --selfcheck及diff check通过，A三文件与固定候选无差异。

Windows本地缺tzdata和POSIX mode支持：复用A测试对2026固定UTC+08导入及仅私有temp根mode位夹具，SQL/Service授权/覆盖/投影真实运行；不安装依赖、不改生产时区或权限。Linux实际时区/FS权限、原user-analytics旧套件及新CI接线效果仍待最终PR CI，不能据本地逻辑通过称Linux或生产验收。

未完成：模型工具schemas/真实worker/会话接线、真实数据与细粒度生产授权、目标持久化/真正变化或到期调度、价值/风险方法与干预比较、真实模型选择/费用负载、部署及阶段2整体验收。本包再次运行knowledge_closeout.py plan（base71cb788e），仍原91项中30项native_plugin_exact_registration_delta_required字节错误，未通过收尾；不改无关publisher、不放宽校验，不声称知识或Notion发布完成。

## PR711独审与project-only修复

Business Sol High独立worktree核阅12acaea91245e0620621b6edfb954ea89ab8a9d4/base71cb788e，实际9路径，发现1项P2：合法原project:1327单独授权可以aggregate/candidates，却因原Service.catalog要求至少site权限而拒绝目录，整条B调查失败。其余限定核心范围无可复现越权/UNKNOWN重放；Linux CI41218728471的Ubuntu22.04/Python3.9.18已实际Core124及user-analytics253通过、0skip，不再把该固定head标Linux待验。

A原施工聊天已确认，仅本次catalog小修临时将a2_query_context.py交Personal唯一修改、A不并改，长期归属不变。B先补project-only整条调查回归并复现user_scope_denied，再沿已核当前scope构造原静态目录字段投影，保留definitions/policies/weekly状态，不修改原Service/IAM、不增加site/global授权。项目目录sites为空、仅当前project；can_read_private仍为当前scope的原授权与host校验交集，返回字段深拷贝不修改原配置。修复继续原PR711，新完整head待重新独审及必要CI，不继承旧结论。

修复后本地原Core125项（组合17）及A2原18项通过、0skip。新增组合回归以严格project-only原authorizer跑目录→完整B调查，断言没有site/global授予、原对象/配置不变、撤权仍拒绝；原weekly publication缺失及scope交集用例继续通过。新head的Linux全组CI及独立复查仍待完成，旧head Linux253通过不直接覆盖此次目录修复。

## 材料限定验收后的阶段2续接包（2026-11-01）

生产源501f90bf的材料主闭环及已测UI范围已经Personal最终验收，细节与未验项见RUNTIME-DEPLOYMENT-ACCEPTANCE.md；这不提升A2生产scope或阶段2整体状态。

本包终点是可由既有host持有/CAS的最小目标状态及短任务续接合同，并明确真实scope接入缺口。B独占新增`releases/fs-dashboard/hermes-v2-core-20261020/source/b2_goal_state.py`、`test_b2_goal_state.py`及原`test_core.py`加载；复用B1 handoff和B2冻结调查引用，不重造A查询、存储、客户库、调度或模型客户端。目标需显式用户意图，状态不自动给普通问题建目标；事实版本变化或明确检查点才提议下一短任务，先CAS保留原request_id再由host执行。prepared/queued/running/provider_returned/unknown都必须核原任务，不因新事实换ID重发；一次任务完成不等于长期目标达成。最小证据与缺项保留，不存全量用户、订单或聊天正文。

A本包先只读核`user_runtime/user_query/a2_query_context/user_http`及必要非敏感现行记录中的真实身份/site/project scope逐调用来源、原会话/任务/跟踪状态及CAS接点；不改IAM/权限、controller/schema/迁移/生产配置，不查真实客户/业务API、不读凭据/认证文件。不把页面/admin权限、目录可见性或FC URL白名单当数据scope；找不到可信来源就继续unavailable。A底座保持A独占，共享新接线精确登记后再做，当前无授权两端并改。

验收：合成内存host/CAS、真实B1 handoff及B2最小引用，覆盖变化/到期/未到期、原ID复核/UNKNOWN不重放、撤权不返缓存、revision冲突、终态/迟到回执、缺项和旧cutoff不推目标完成、无原始用户正文的续接。零模型/业务API；真实持久化/会话接线/自动调度/生产细粒度scope不以本地内核通过认定。整包准备好后由Personal统一PR，Business Sol High独审最新完整SHA及必要CI；本轮不为文档重部署。

### B实际交付与宿主责任

`create_goal`仅显式目标且host `authorize(owner,scope_ref) is True`时构造32KiB以内JSON；普通问题不自动建目标。`plan_step(state,expected_revision,now,fact_version,request_id,authorize)`返回`expected_revision/state/action/request_id/handoff`。`dispatch_after_cas`只是提议：host必须先以原revision原子保存prepared，成功后才能派发原request_id。两个本地提议都计算成功不代表两个CAS成功；相应对抗测试只有一个可保存。所有函数均深拷贝，不自行存盘或调用模型。

prepared/queued/running/provider_returned/unknown返回reconcile_original，不因新事实或到期换ID；即使CAS后派发前崩溃，也须沿原ID查询对账，不能凭无回执重发。`record_receipt`只接host已核验当前原request_id及receipt_ref/status，terminal精确重放幂等、冲突或迟到旧任务拒绝；provider_returned仍pending。completed仅指短任务回执，不自动宣布目标实现。证据严格复用B2/B1六字段及action receipt refs，原as_of/coverage/missing不因本次完成时间推进，原始investigate rows/events不入state。`configure_goal`仅host显式pause/stop/检查点，保留未决原任务，stop不冒供应商或计费已停。撤权在返回缓存前拒绝；A2源解析仍另逐调用鉴权。

fact_version是host核验scope/identity/policy/contract/lifecycle policy及冻结snapshot/data版本后的复合定位符，不是模型参数、当前时间或单独snapshot_id。内核不自行证明这些来源；未知/不兼容版本不得由host合成有效版本调用派发。该包的复合版本由合成夹具注入；真实data映射未验仍unavailable。跨历史request_id唯一性及任务receipt真实性继续由host原账本负责，当前state只保留一个未决/最近任务，不建第二套执行账本。

原pr_fast.units直接15项、原Core入口140项全部通过，0失败/0skip；组合用真实合成SQLite Store/Service/A2 context→B2 investigate partial→B1 handoff→本goal state，缺页/原冻结cutoff保持。首次新组合测试以`email`子串误匹配原合法identity policy版本名而失败，已将断言改为禁止真实email/orders/events/rows字段，数据算法未变；最终上述两入口通过。原runner外网/Popen阻断不变。Windows组合沿用已有固定2026 UTC+08和私有temp mode夹具，不代表新Linux或生产验收；LinuxCI/独审须核最新完整SHA。

本包按原统一入口再次执行`python -B tools/knowledge_closeout.py plan --base 501f90bf16fe114e70fcb05833cb1b2cf478e54c`，仍为既有91项/30 error、`native_plugin_exact_registration_delta_required`，exit1。未改无关知识publisher或放宽字节检查，不称知识收尾/Notion同步完成；此记录不增加生产发布或新模型调用。

### A限定只读核查结论（固定55c4bbd5，未改底座）

身份候选沿`fc-pricing-v3-20261026/source/conversation_http.py::handle`宿主user/authorized及`opt/auth-portal/auth_portal.py::_do_verify`正常session传递，后者未证明为当前活动装配。`user-analytics-20261022/source/user_runtime.py::authorize`重读RBAC，但仅页面访问/admin私有门，不检query.scope/scope_id；`opt/auth-portal/fc_read_scope.py::allowed_fc_read`仅URL/GET白名单。均不能作为细粒度数据scope。旧SOURCE-MAP的range_api与501f保护metadata哈希不符，不能把旧映射称当前实现；未读认证文件或请求生产数据。

现成A2 factory/五方法可消费，`guard`逐调用strict True，真实Service授权与host scope取交集；无可信identity+scope+validator时unavailable且service_calls=0。Goal关联字段由host envelope持有，不能混入A observation：原observation仅显式带时区observation_at及checks的recheck_at/可选expected_next_purchase_at，最多200必要客户，partial/旧cutoff/更正不推目标完成。paused/stopped、过期、旧revision及撤权须在任何catalog/源读取前拦截。

`hermes-fc-pilot-20261013/pilot.py::TaskStore.change/reserve_dispatch/bind_run/observe`提供原owner/version、DISPATCH_UNKNOWN/lease围栏；ConversationStore的turn/action围栏和文件绑定可复用为执行边界，**都不是通用GoalState load/CAS**。tracking save_config有scan_jobs副作用、tool_read可能poll历史且该源仍有8767，不能恢复为纯只读到期工具；snapshot.meta.revision是源版本，不是goal revision。真实宿主缺口精确为：①当前可信identity+scope_ref→精确scope逐调用validator；②独立goal revision/request指纹的load/CAS和崩溃一致性；③CAS后沿原ID派发、receipt验证/unknown对账接点。A后续持久化如需扩既有DB或私有记录，须先登记准确文件及唯一维护者，本包没有建表/sidecar/迁移/共享controller接线或生产动作。

复查前fetch发现main已为cc33dbcb0023559192c409141963bc93eebfe1c5（其他活动分析PR710，改动路径与本包不重叠），已在保存P2修复后正常merge，无冲突；新组合基线Core125再次通过。最终PR仍仅本包9路径相对新main的差异，不重审/重写对方活动模块。独审新head/base及CI按此最新组合重新核对。

## PR720验收及下一最小宿主包

Business Sol High独立工作树审查精确head `349460cc019bc00c45b1b93cdeec0a4974ca8a87`、base `501f90bf16fe114e70fcb05833cb1b2cf478e54c`起止未变，限定七路径无未解决问题；独立新15/Core140和实际Ubuntu22.04/Python3.9.18 CI41241979255的Core140均零skip通过。Personal合并前核同head/base、CI成功及无冲突，按已有用户授权正常merge `2f4251a4b1fe8b0be33e727d6d97a8acd6773a6a`；本机ff并核merge树与reviewed head完全一致，取消PR720监听。纯合同验收通过，未部署B goal state；生产仍501f90bf，真实scope/GoalState存储/派发接线仍未提升为已验。

下一包终点是本机合成环境的持久化goal load/CAS→原ID短任务提议/派发→回执/UNKNOWN恢复，零真实模型/业务API。A独占拟新增`hermes-conversation-20261018/source/conversation_goals.py`、`tests/test_conversation_goals.py`以及原`tests/test_conversation_store.py`的load_tests接线；A可在该独立模块维护既有ConversationStore DB内唯一私有goal命名空间及mutation指纹表，与原DB锁序列化，不改现有公共表、公共schema/migration文件或另建客户库。不把原TaskStore.change当任意goal CAS。具体SQL/连接/崩溃一致性由A实现并回交；无生产DB操作。

B独占拟新增`hermes-v2-core-20261020/source/b2_goal_host.py`、`test_b2_goal_host.py`和原`test_core.py`加载，消费A持久化接口与原b2_goal_state，不重造A底座。共享controller/HTTP/runtime/publisher/公共schema/迁移均暂不动，tools/pr_fast仍Personal唯一维护；测试优先沿两条既有入口。A确认收到归属后才实现上述A路径，Personal不并改。

接口目标：host固定owner/cid/goal_id，load_goal与cas_goal(expected_revision,mutation_id,state)逐调用原会话owner及当前scope校验；create expected_revision=0、后续state.revision=expected+1。CAS mutation_id绑定完整指纹，同ID同内容返回原操作收据并明确replayed，不再触发执行；同ID异内容拒绝，revision冲突不覆盖。任务request_id与CAS mutation_id不同，核prepared保存后才单次派发；prepared重放、派发后进程崩溃、回执丢失、unknown必须原ID查询/对账，不因not_found直接换ID重发。A不为本包合成真实授权；缺可信identity/scope/fact复合版本则无源查询、无真实派发。先冻结小接口/回执语义再组合，最终仍一份完整集成PR及独立最新SHA审查/CI，不按函数拆PR。

### 实际A候选及B宿主适配

A固定`2247724c7d517b7c84f5b58ecd09551714401bee`、base2f4251a4已正常合入，实际四路径与前述登记相同（交付文档为模块`CONVERSATION-GOALS.md`），不改原公共表或ConversationStore/service/HTTP/controller/runtime/publisher/IAM。新模块在原db事务内维护conversation_goals_v1及conversation_goal_mutations_v1，目标/回执同事务提交；全DB goal及mutation绑定、32KiB完整v1状态、原scope严格True、原始操作重放与存储checksum按A文档实现。A原入口53项（goal21）零失败/零skip证据复用，包含实际temp SQLite并发、事务故障、重连/旧回执/跨owner等；新增admission夹具曾因连接未close导致WinError32清理失败，A以closing修正后完整通过，未放宽生产逻辑。

单纯prepared CAS后再load不能封住pause与reserve竞态，因此已与A明确追加同文件同DB的`admission(goal_id,expected_revision,request_id)`。它持BEGIN IMMEDIATE至退出，先owner/原scope再核active/精确revision/prepared/原ID，yield deepcopy而不暴露连接、不写目标或任务；B只在内预留**独立任务账本**，不能嵌套写conversation DB、等待provider或业务操作。任务预留与pause由锁序列化；外部预留成功后admission异常不代表任务库回滚，保留原ID对账。该接点A独占实现，B不改表或事务。

B实际新增`source/b2_goal_host.py`、`test_b2_goal_host.py`及原Core加载，消费真实A模块与原b2_goal_state。`GoalHost`仅server注入已绑定goals/owner/cid/authorize/dispatcher/verify_receipt，公开create/configure/step/observe。只有本次fresh CAS（replayed严格False）、原账本已验证not_found、live admission三条件都满足才单次submit；旧prepared、未知、lookup缺失或CAS回执不明都不能补发。CAS/submit/lookup/admission退出的传输异常只返回受限unknown/原ID对账状态，不回传异常文本；PermissionError仍拒绝，不误归为传输未知。回执CAS在退出admission后执行，避免同DB嵌套锁。

dispatcher冻结`lookup(*,binding)`及`submit(*,binding,handoff)`，submit只能按原ID原子reserve/入队；回执严格为`{binding,status,receipt_ref,evidence?,completed_actions?}`，仅completed能带后两项，not_found也须host `verify_receipt(receipt,binding) is True`查询原账本。binding为owner/cid/goal_id/scope_ref/request_id/intent_sha256；摘要固定逻辑身份、objective/constraints及work.fact_version/checkpoint，排除进度revision和可更新证据，保证completed后的原回执仍可核验。它不是访问授权或全payload hash；任务账本**另外**须对完整binding+原始handoff做原子指纹校验。模型正文、原始客户表/工具结果、未核verified标志不能变成执行回执。

新增B组合最终16项由原Core入口实际加载，与原套件合计156项全部通过、0失败/0skip。组合使用真实A Store/Goals和独立SQLite **SyntheticTaskLedger测试夹具**，没有真实TaskStore/worker客户端；覆盖prepared提交后丢回执而not_found仍不派发、外部任务已提交而submit/admission退出丢回执、receipt CAS提交后丢回执、真实A重放CAS不算fresh、pause抢先拒绝、暂停停止零lookup、停止后原取消push、partial原cutoff/缺页保留、旧任务迟到/六项binding漂移/假成功拒绝、unknown及provider_returned保持原ID、撤权和strict True。该夹具验证跨两个本地DB的故障合同，不声称原生产TaskStore/lease装配、真实授权/事实版本、模型、A2数据、调度或生产DB已验。运行入口/真实授权来源继续为后续明确接点；生产保持501f。

本包knowledge_closeout plan以base2f4251a4运行，仍原91项30 error/native_plugin_exact_registration_delta_required、exit1，未放宽/扩修，知识/Notion收尾保持未完成。主控核A四路径与固定2247724c完全相同，Python3.9语法及diff检查通过；CI驱动与外网/Popen禁令未改。

### PR721独审P2：同回执跨revision的恢复冲突

Business Sol High独审head `ae18056d2291f78b4c7679c3425069aac498be49`、base2f4251a4起止未变；旧head实际LinuxCI41243810785的A53/相关组21/Core156零skip通过，但审查独立复现一项P2：B仅按外部receipt内容生成mutation ID，A的mutation指纹还绑定expected_revision/完整state，所以queued→running→unknown后原账本恢复同一running回执会抛goal_mutation_conflict，重建host仍不能恢复。旧CI绿不能取消该阻断，暂不合并。

Personal先新增真实A SQLite回归，原实现确实复现同一异常；修复仅B `_save_receipt`以expected_revision、完整新state及receipt共同生成确定性CAS操作ID，不把外部回执身份当每次CAS操作身份。不同revision的合法恢复各有操作ID，同一proposal/回执重试仍稳定。A原mutation指纹/事务/admission不变，没有放宽校验或换任务request_id。

修后原runner B host18项全部通过、0失败/0skip：新增两轮running→unknown→同一running恢复及重建host、submit总数仍1；另测同一CAS操作在写前丢回执后原ID查回，mutation ID保持确定。原回执CAS提交后丢回执、prepared/replayed不重派等16边界继续通过。旧head独审/CI证据只覆盖其版本；新完整head须Business独立复查及必要CI，不把本地18项冒Linux/Core新全组验收。A四路径/冻结publisher/运行入口/权限/生产均不改。
