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

### PR721限定验收与合并（2026-11-01）

Business实例codex-business／gpt-6.1-sol high在平台独立工作树复查完整head `065ab1d54e544220632ff54412402a835ae5935c`、base2f4251a4起止一致，原P2解决、无新发现。独立在内存重装旧实现复现冲突；当前host18和额外重建host/回执键序变化后同proposal稳定性通过。沿observe/lookup/submit、撤权、终态迟到、原ID和admission检查无回退，A四路径仍固定2247724c。实际新LinuxCI41244422090对应此head/base，Ubuntu22.04/Python3.9.18，A53/相关21/Core158均零skip，新两项已加载；不再将修复版记为Linux待验。

Personal合并前再次核完整SHA/base、必要CI success及mergeable，按已有用户授权正常merge `8f604875455845679c181000e382fe8c04725ba2`；本机ff后与reviewed head树完全一致，已停止PR721监听。本包终点是本机真实SQLite持久化/admission与独立合成任务账本的故障恢复合同，至此限定验收完成。没有生产DB/TaskStore/worker/模型/调度动作，生产源仍501f90bf。真实scope/fact/receipt来源与原运行桥接、阶段2整体和知识收尾旧错误均未提升为已验。

下一步不重写存储：A先限定只读定位原独立TaskStore create/reserve_dispatch/lease/observe与现行FC3 conversation_service的实际接口、spec字段来源、原ID与receipt映射及锁序，不再重复scope审计、不运行生产或获取凭据；明确最小新增适配路径后再登记单一修改者。现行FC3 _dispatch还写ConversationStore.bind_task、mint/grants、book/knowledge和runtime POST，不能直接塞进goal admission或据callback测试说已接通。B继续负责事实复合版本/最小handoff/原ID回执消费的真实接口对齐；A维护任务底座及宿主装配。没有可信细粒度scope仍unavailable，不为接线把页面/admin或合成授权当新生产授权。

## 冻结证据驱动的持久待执行队列包（2026-11-01）

A限定只读确认：原pilot.TaskStore.create只有FC27/fc_operations_diagnosis及五字段spec指纹，没有goal原request_id/full handoff映射。现行FC3的spec来源含实际book/knowledge及昨天日期，_dispatch又写会话DB并调用runtime POST，不能直接入goal admission或构造假spec。worker只有run_id GET，没有按goal request_id只读lookup。活动controller/fs_evidence与本地候选未匹配，仍未知；本包不扩查生产、不覆盖旧源。

本包终点明确为：真实本机A2冻结摘要→B复合事实版本/最小引用→已验GoalHost→原独立任务DB的私有持久reservation/outbox→原ID lookup及验真。queued只表示outbox预留，task_id/lease/run_id未绑定仍null，不能称原TaskStore任务或worker已启动；本包不做无法证明的generic执行类型或真实spec绑定，不用假任务追求通过。

唯一A路径登记：新增`hermes-conversation-20261018/source/conversation_goal_tasks.py`、`tests/test_conversation_goal_tasks.py`，原`tests/test_conversation_store.py`仅load_tests，模块`CONVERSATION-GOALS.md`补合同。在已配置且核存在的原独立任务SQLite中建模块私有goal-request/outbox命名空间；不改pilot/TaskStore现有表、FC lane、controller/HTTP/runtime/publisher/IAM或公共迁移。不用模糊路径新建空任务DB来证明not_found。A确认后施工，Personal不并改。

唯一B路径登记：新增`hermes-v2-core-20261020/source/b2_goal_facts.py`、`test_b2_goal_facts.py`、原Core加载，并在原B `b2_goal_state.plan_step`与`b2_goal_host.step`增加可选server-only evidence参数，使已核冻结摘要引用与prepared同一次CAS保存。B消费原A2 source/summary.lifecycle_policy，不重写A授权/查询/存储；停止/未决原任务先处理，未知scope或fact版本无源读取或派发。只保存原us_/ua_/scope/query/cutoff/coverage/missing等最小引用，不把摘要正文或客户表塞进目标。

队列适配冻结submit(binding,handoff)/lookup(binding)/verify_receipt(receipt,binding)，server固定owner/cid/当前authorize及期望原账本路径；原ID按权威owner命名空间去重，完整binding+handoff指纹同事务，重复同内容查原回执、同ID异内容拒绝。not_found仅为已配置/同owner+scope授权的此outbox无row，不证明worker从未收到请求；库缺失/错路径/拒权/IO不能变成not_found。没有合法task/spec/run来源，不提供伪造running/completed入口。锁序保持goal DB admission→独立task DB短事务，禁止任务DB锁内反向调用goal或ConversationService。

验收使用真实temp Store/Goals、原TaskStore的独立SQLite及真实A2 Service冻结重放，零模型/业务API/生产：指纹冲突/并发/重连/丢回执、wrong/missing ledger、scope撤权、queued不冒running、paused/stopped/pending零A2读取、同snapshot稳定/版本缺失或scope错配不派发、partial旧截止及真实lifecycle policy保留、源异常不补0。现行host grant、合法generic执行类型/spec、原worker及生产装配仍是明确缺口，A2真实scope保持unavailable。仍一个Personal整包PR、最新SHA Business独审/必要CI后合并，不按方法拆PR。

### 实际outbox与冻结事实候选

A固定`66b1289729cc8cd6a2e9da13c0c3d973ce1c445a`、base8f604875已正常合入，四路径与登记一致。`ConversationGoalTasks`强制host expected_path匹配原tasks.path现存绝对规范路径，以mode=rw打开并逐次核原schema/非partial完整唯一索引、文件身份及私有ledger_id。模块只创建/写私有outbox与身份表，不经TaskStore.db自动建替代库；缺库/漂移/损坏/IO不返回not_found。完整binding+原始B1 handoff按owner/request_id事务去重，重复同payload返原queued，未知scope/撤权literal True拒绝；receipt精确三字段，不新增task_id/lease/run_id，私有row这三项始终NULL，无running/completed或record入口。

A真实temp测试原会话入口75项（新outbox22）零skip证据复用；最后收紧partial unique index后新22项单独重验通过。覆盖原已有合成FC任务保留、tasks/schema不改、路径竞态不造空库、授权/指纹/并发、reservation独立提交及锁序。B不改A底座，固定候选四路径比对另核；Linux按最新PR CI验证，不据Windows3.9 AST称Linux执行。

B新增`b2_goal_facts.py`的`FrozenGoalFacts(host,resolve_scope,context_for)`及实际组合测试。server解析opaque scope_ref到精确site/project，未配置则unavailable且零context/源读取；context身份/范围不能换用。只读原catalog和显式snapshot aggregate(summary)，校对source与summary七项原版本、scope/query/us_/ua_/reference、实际冻结lifecycle_policy及保守query/state/weekly截止；不按snapshot_id或当前时间补版本。捕获时间只校验不来自未来，不用它推进业务截止或制造新fact版本；复合摘要含原版本/query/coverage/watermark/实际policy。

已有上一摘要时，从其原snapshot重放必要baseline并核实际policy/身份/scope/contract及期间基础可比，缺原源返回unavailable，不靠hash或当前表重建。当前与baseline的原引用、partial/旧cutoff/missing保留，同snapshot原有缺项并集；只精简重复aggregate摘要，原页链/其它证据引用保留，仍受32KiB约束。summary不冒候选/时间线全集，不新增高价值金额排名、流失概率或经营写入。

原B plan_step与GoalHost.step加可选server-only evidence；新事实引用与prepared同一次CAS保存，非伪completed回执，不改v1状态schema。读取期间goal revision改变即拒绝过时提议；新事实CAS/admission通过A2原授权∩host范围继续校验，读后撤权不存/不排队。paused/stopped/pending在源读取前处理，pending只对原ID核队列，不返未经source重核的私有state/evidence缓存。原GoalState/host API默认参数兼容，UNKNOWN/replayed和已验证not_found不补发。

Personal原Core最终177项全部通过、0失败/0skip，新增facts18项已实际加载（4元数据、14真实A2/GoalStore/原任务DB outbox组合）；新增kernel1项覆盖prepared/evidence原子保存、pending忽略覆盖及future拒绝。首次组合16项通过，补同snapshot缺项及pending缓存边界后完整177重验。使用真实合成SQLite/Service冻结重放及原TaskStore temp DB，原tasks行数仍0；全程无SyntheticTaskLedger替代此新组合、无真实模型/业务API。Windows沿用A2已明示2026 UTC+08及私有temp mode夹具，真实POSIX/最新SHA独审与LinuxCI待完成。queued只计持久待执行，不计原TaskStore任务、worker启动或阶段2上线；生产仍501f。

本包以base8f604875执行原knowledge_closeout plan，仍既有91项/30 error、native_plugin_exact_registration_delta_required、exit1，未扩修或放宽旧知识publisher，不称知识/Notion完成。原pr-fast/外网/Popen围栏未改；6条B Python路径3.9 AST与diff通过，A四路径与固定66b12897无差异。实际源扫描量/生产费用仍unknown，不因冻结摘要小而推断后端少扫或新模型账单。

### PR722限定验收与合并（2026-11-01）

Business Sol High平台独立worktree核完整head `24bc4d6b786849b0de8db58b178c853bc6b6454e`、base8f604875起止不变，实际12路径，无可复现功能/权限/数据丢失问题；A四路径与66b12897一致。独立A22/B18/kernel16/host18及补充3项源异常/admission撤权/保守cutoff均零skip。新LinuxCI41247844832实际绑定此head/base，Ubuntu22.04/Python3.9.18会话75/相关21/Core177全部通过，新增测试已加载。

Personal合并前复核最新版本/CI success/无冲突，按已有授权正常merge `d279086292f514002adadf801468e077dc7f3a1a`；本机ff核merge树与reviewed head完全一致，已停止PR722监听。至此限定本机「冻结事实→prepared同CAS→独立DB私有outbox→原IDlookup/验真」通过。queued仍非原TaskStore执行任务/worker；没有生产goal DB/真实模型/调度或新scope授权动作，生产继续501f，阶段2整体未完成，旧知识收尾错误保留。

下一工作转入真实运行装配，不再增加替代执行层：A唯一现场执行者先沿既有合法SSH作三份已知未匹配活动文件的限定只读元信息核对（controller.py/fs_evidence.py/range_api.py）；只返回哈希/大小、必要类/函数签名及调用/导入名称、可比函数AST指纹，不导出源码正文/常量值、不导入执行这些模块、不读配置/凭据/DB、不调用业务或模型API。既有批量源码复制拒绝仍独立有效，元信息不能等价绕为源码下载；工具拒绝即停止原样回报。若信息不足，列必要读取的最小具体范围与用途交用户，不把未知活动装配伪称匹配，不覆盖旧源。B据实际接口对齐合法goal执行类型/spec/原ID只读恢复及scope来源；真实grant缺证据继续unavailable。

### 活动源码在既有Git中的精确定位（2026-11-01）

A在原独立工作树正常ff main d279086292f514002adadf801468e077dc7f3a1a后，以既有合法SSH只读核三份指定文件；逐目录/目标O_NOFOLLOW、regular及稳定fstat检查，AST前重核SHA，无源码正文/常量值导出、SCP、模块导入、服务或DB/API操作。当前controller为59487 bytes、SHA256 `75c1b1f6b6af47fe00465e8b4dd0e9628ed17dbd85be0b1988145dbf41dc8e28`；另外两份如下，均与501f原保护记录一致。这里只证明当前磁盘文件，不证明进程已加载或当前健康。

Personal随后只读本地Git原始LF字节，找到两份完整精确匹配；旧“未找到Git源”的结论由以下证据收窄，而非恢复旧候选覆盖现场：

| 活动文件 | d2790862中的Git路径 | bytes / SHA256 | Git blob |
|---|---|---|---|
| /opt/fs-hermes-fc/fs_evidence.py | releases/fs-dashboard/fc-coins-workflow-20261022/source/fs_evidence.py | 27713 / 08ea0d4a85b605c0665aed11f6bda56ff15b51dcfe8b1c53dd90a80a6d101d29 | e995458b378c51ea6908119357ef29c842b8849a |
| /opt/fs-exact-range-20261001/range_api.py | releases/fs-dashboard/dashboard-refresh-20261025/source/range_api.py | 25525 / 12008f7fc6a21a01b2daf5d911905356c4aab238d10925e09069029f4f047b7f | b7f024715816fd788d4e7c921f2c747d6fb92562 |

Windows工作区CRLF的大小/hash不同，不能据此否定Git LF匹配。range_api.py:277-281已可从合法Git读取：原HERMES的root/run_root/source_root为`/var/lib/fs-hermes-fc/fs`、`/run/fs-hermes-fc`、`/opt/fs-hermes-fc`；现有ConversationService复用HERMES，store根为`/var/lib/fs-hermes-fc/fs/conversations`。GET/POST会话及analytics入口传递正常宿主`X-Auth-User`。这些静态接点不证明上游细粒度site/project grant，fc_daily.admin也不作为该证明。

为比较远端Python3.9与本地3.14的有界函数AST，Personal去除3.9没有的空type_params字段，再用`ast.dump(include_attributes=False, show_empty=True)`保留3.9的空字段表达。由此Core controller.__init__:97/get_job:251分别与远端完整指纹`7baa4d624b545ee76bd1cb7f0f47d63c1635eb1964da06b4869e24804ead4882`、`020e1801e31719a461ccc5d9fbba03df8f356a5201b01b1b76e375b06f53a2fd`相等；knowledge-layering-20261023/source/controller.py的_submit_report:441与`3e21966641bf24fc7ed750aaab0c9b966677d8afc3ac6e4e5c25757a958d269d`相等。所匹配构造函数的原TaskStore路径为self.root/'tasks.sqlite3'；仍使用现有对象，不另构造带恢复/线程/DDL副作用的HermesService。函数结构匹配不保证其它全局符号/整模块行为相同，controller整文件和execute仍未匹配，不覆盖或复用其执行分支。

原计划A类45行片段的生产读取/导出已不必要，未向用户索取该许可、未执行等价导出；此前批量SCP拒绝仍有效。已把两份精确Git源、blob和函数指纹交A，只读本地收敛真实执行包接口，不重复SSH核查或旧测试。候选方向为用户显式选择且同owner/cid授权的材料目标短任务，不从页面admin推A2 scope；必须先确定合法执行类型及真实spec/预算来源、task/lease/run持久映射、单次POST/UNKNOWN原ID对账、锁序与停止/恢复合同，再登记实际A/B路径实现。此处是接口待定项，没有新增通用goal执行、模型请求、调度或生产发布；B主线是执行意图/证据与最小handoff，A主线是原任务账本/生命周期/HTTP/runtime装配，独占归属保持。

### 真实材料短任务执行包登记（2026-11-01）

A本地只读合同已回收，冻结首个合法类型`conversation_materials_v1`：仅正常FS身份在原会话显式选择的最多10份材料及明确读/确定性修订意图。材料grant来自该服务端选择记录和逐调用文件/任务/goal授权，不能转成site/project业务grant；A2真实scope仍unavailable。只由显式动作创建/执行/停止短任务，不加定时/自动触发，不造human turn。验收终点是原task/lease及一次官方Runs提交、三工具真实分页/修订、鉴权字节下载和派生版本显式再选择；UNKNOWN、停止、撤权、重启/迟到和FC原链回归在同包验收，不以queued代替执行。

原TaskStore.create/FC validate_spec/FC validator和未知controller.execute不改。A在原tasks DB的独占材料映射事务中，按明确FS/materials命名空间创建真实tasks行并持久映射完整binding/intent/outbox receipt；原outbox_v1仅reservation，不回填其NULL任务列。新类型period=null表示材料无业务期间；snapshot_id来自材料manifest内容hash；template_version来自B实际静态提示内容；knowledge_version来自本次文件规则/操作/最小handoff的实际冻结上下文；budget_policy_id取原general gateway真实有效policy。此特殊validator只适用于新类型，原FC五字段要求不放宽，不填昨天/假FC capture或教材版本。原额度、到额停止、DeepSeek及usage账本保持，材料transport retry=0，不增加费用授权。

| 本包实际路径（相对仓库） | 唯一修改者 / 范围 |
|---|---|
| releases/fs-dashboard/hermes-v2-core-20261020/source/material_execution.py、新test_material_execution.py；source/conversation_file_tools.py、source/material_evidence.py及test_conversation_file_tools.py、test_material_evidence.py；test_core.py | Personal B：显式意图/材料manifest/实际最小上下文及工具/证据作用域；原turn默认行为兼容 |
| releases/fs-dashboard/hermes-conversation-20261018/source/conversation_material_runs.py、新tests/test_conversation_material_runs.py；source/conversation_file_bindings.py及tests/test_conversation_file_loop.py、test_conversation_store.py；source/conversation_http.py及deploy/test_http.py | Business A：真实task/lease/run映射、execution-bound文件上下文、原ID恢复/停止、HTTP及原入口测试加载 |
| releases/fc-coins/fc-pricing-v3-20261026/source/conversation_http.py及对应tests/test_runtime_contracts.py | Business A：保留现行FC接点的材料HTTP适配 |
| releases/fs-dashboard/dashboard-refresh-20261025/source/range_api.py | Business A：仅向现有HERMES/CONVERSATION注入新服务；原身份来源不变 |
| releases/fc-coins/fc-review-channel-20261026/source/hermes_worker.py、proxy_gateway.py、fs_inprocess.py及tests/test_channel.py | Business A：materials可信类型、仅三文件工具schema/调用隔离、原官方持久记录只读resolver；B不并改 |
| releases/fc-coins/fc-pricing-v2-20261022/source/runs_contract.py及原tests/test_pricing_v2.py（仅受影响合同） | Business A：材料session及状态/恢复协议；旧FC合同保持 |
| releases/fs-dashboard/hermes-conversation-20261018/frontend/conversation.js、index.html、conversation.css、test_materials_ui.cjs、test_materials_browser.py及entry/test_data_handoff.cjs | Business A：必要显式选择/状态/产物/停止UI，复用令牌和原入口，不另建界面风格 |
| releases/fs-dashboard/hermes-conversation-20261018/deploy/runtime_prepare.py、runtime_release.py、test_runtime_materials.py；CONVERSATION-GOALS.md、DEPLOYMENT-ACCEPTANCE.md | Business A：最终固定载荷/现行501f installed proof增量/原publisher与本模块交付；不复用旧stage |
| tools/pr_fast.py；本工作包及唯一主文件 | Personal主控：仅必要原CI接线/全局记录 |

本登记先送A确认可见后，A才改共享路径。若需要表外源/公共schema/迁移或其它运行接点，先报具体依赖再登记，不能默默扩改。首包不调用广域build_book或通用经营工具；worker toolset、proxy最前置拒绝和provider/preflight schemas三层均须仅三文件工具，不靠book末端拒绝掩盖strategy分支。

B固定接口为`freeze_execution(*,binding,handoff,selection_revision,files,operation,deadline_at,now)`，只消费A已核的服务端身份/完整B binding、原B1 handoff和真实metadata，产出固定manifest/snapshot、完整payload指纹、实际input/system_prompt和模板/上下文版本，不授文件权限、不写库/发请求。operation为read或指定file_id/edits/format的revise；后者使用按原request与完整操作确定的revision_request_id。A须在工具调用前核操作精确匹配；下一任务不能隐式继承产物。B helper新scope仅host参数`material_execution_files`，默认turn_bound_files不变，模型schema无scope字段；新scope拒绝非文件工具、不preparing读取catalog，coverage仍只表示本执行实际页链，非业务新鲜度或目标完成。

原Runs单次POST前持久attempt/session/key/body hash，全部DB锁释放后网络；任何不确定结果保留原ID，不重POST。已只读核[固定官方Runs源码](https://raw.githubusercontent.com/NousResearch/hermes-agent/71d34bad1045610252eda02ee79549436896e784/gateway/platforms/api_server_runs.py)和[幂等存储源码](https://raw.githubusercontent.com/NousResearch/hermes-agent/71d34bad1045610252eda02ee79549436896e784/gateway/platforms/api_server_run_idempotency.py)：原请求按认证命名空间/key/完整body指纹持久预留run；store.lookup虽不reserve但会清理过期记录，不能冒纯只读。A应在现有受认证adapter内从同一官方持久账本只读核原scope/key/fingerprint/session并返回最小run状态；不新建替代执行账本、不读其它会话正文，不用404宣称从未执行。官方版本/当前镜像是否一致需正常固定依赖核验；未证或账本不可用则真实POST不可启用。丢202后必须实际找回原run且POST计数1；重启无法安全恢复book/grant则围栏/停止原run，不重发。CAS/admission与独立reservation/网络不作跨DB原子承诺，锁序仍goal→tasks，禁止反向回调。

此登记授权继续本机实现/相关测试/统一集成PR；沿原用户授权和最新SHA独审/CI处理合并。当前未执行新部署、真实scope/模型或业务操作；A同包固定候选和无模型故障组合准备好后再核最终发布清单与必要真实验证，费用缺值保持unknown。独立审查仍唯一Business Sol High delegate，未完成不合并。

#### B实际候选与A接入合同

A已真实回复登记a2512c72完整可见、共享单一维护者已知，开始本机实现。Personal B新增material_execution.py及17项test_material_execution.py，并在原Core入口加载；helper增加host-only材料作用域。无新执行器/模型client/文件算法或存储替代层，不改A文件。实际API：

- `prepare_materials(*,owner,cid,scope_ref,selection_revision,files,operation,now)`先从A已核metadata/明确操作得到manifest、snapshot_id和fact_version，供原GoalHost.step使用；不需伪binding/hand-off/task。版本含owner/cid、scope、选择revision、完整文件版本/到期、操作和实际静态提示模板，不因读回时间改变；它表示材料身份，不是A2复合业务版本或业务截止。
- `freeze_execution(*,binding,handoff,selection_revision,files,operation,deadline_at,now)`冻结原exact6字段B binding及exact7字段B1 handoff（task_id须原request_id）。只保留文件file_id/sha256/parent_id/version/size/expires_at，不复制正文/路径/URL。操作是read或明确选定输入的精确cell edits/format；后者产出按原request+完整操作确定的`revision_request_id`。返回kind/binding/handoff/selection_revision/manifest/operation/deadline_at/snapshot_id/fact_version/template_version/knowledge_version/system_prompt/input/payload_sha256，A持久化完整payload并比较，不能只比较logical binding digest或在后续revision重建原handoff。
- `validate_execution(execution,*,now=None)`重建完整冻结数据并精确比较，返回深拷贝。无now仅验完整性，专供到期后的状态对账/停止，不授派发权限；派发/工具须传实际带时区当前时间，截止或文件到期拒绝。`operation_guard(execution,name,arguments,*,now)`必须有真实当前时间，精确匹配修订的原ID/file/format/cells，read拒绝revision，非文件工具拒绝；成功仅literal True。选中/派生membership、owner/goal/task/lease、磁盘hash及真实receipt仍由A逐调用核，不由B hash代替授权。
- A调用`attach_conversation_file_tools(book,context,scope='material_execution_files',operation_guard=lambda name,args: operation_guard(fixed,name,args,now=host_clock()))`；新scope必须提供可调用guard且返回字面True，最前拒绝非文件工具。file_prompt/tool_schemas的同名scope仅host关键字参数，不进入模型schema。默认turn_bound_files的原prompt/schema/透传语义保持，原coverage算法复用、每新book独立，unknown产物原样返回且不自动再调A。

B最终原pr_fast.units Core入口194项、零failure/error/skip；新增17项已加载，含真实freeze→guard→原helper调用链，原文件/coverage/HTTP/provider/goal回归通过。四条B Python路径通过3.9 AST，实际本机3.14；沿用原A2明确Windows UTC+08/temp mode夹具，不称Linux执行。knowledge_closeout plan(base d279)仍原知识层30 errors/exit1，保持未完成。A完整运行链、真实官方只读resolver/当前版本证明、LinuxCI和独立最新SHA审查未完成；生产仍501f，未作新模型/部署/业务操作。待A完整固定候选正常合入后，只对真实组合及受影响合同验收，仍一个Personal集成PR。

#### 官方字节定位与实际上下文proof补充

A已在B fixed4e4c5659上本机施工，回交真实原TaskStore/lease/单次attempt映射、execution-bound文件与SELECT-only resolver初版4项真实temp DB通过；完整候选/HTTP/UI/三层隔离仍在实现，此局部证据不记整包通过。A的基础receipt沿原exact binding/status/receipt_ref，仅completed附最小evidence/completed_actions，兼容GoalHost；原outbox仍只queued，不能回填其NULL任务字段。ref须回指持久映射版本与实际task/lease/run/完整execution hash、官方最小状态、实际页覆盖/产物及proof，不能仅凭模型正文或hash当执行来源。

在既有现场权限下，Personal明确限定A只核当前worker容器/实际image的WorkingDir和三份明确官方.py元信息。A回报当前容器fdb100cedd9b2c05dedfb7880282cd1105e322e3315e3585d72d149d8f01c96a Running=true、实际image8251bc53…3544，两个WorkingDir均/opt/hermes。目录/目标O_NOFOLLOW、regular及stable fstat检查通过，以下实际字节全部匹配A按固定commit71d34bad1045610252eda02ee79549436896e784公开raw下载的源码缓存；未输出正文/读取Env、profile/config/DB/日志/凭据，未新建/启动容器或改服务，旧批量SCP拒绝未重试：

| /opt/hermes/gateway/platforms/下 | bytes | SHA256 |
|---|---|---|
| api_server.py | 256424 | 6a7e6fb0a0d5ea25ddc47d36a64e2c0bc50ded331d49e1c4521d801ca7189043 |
| api_server_runs.py | 68296 | 8a7fcfd56183c32a14b41c7c43ce36b21b37bf49f2ed035dafe48899c0e8cbe7 |
| api_server_run_idempotency.py | 10755 | 56f7762addc5e610569fd613729f1f0b3d5e99e4b76f56d9cfa509dfeb51636c |

raw行号与web索引会移动，使用完整字节hash及原指纹/SQL语义，不沿用旧web行号当证明。这消除当前磁盘SDK字节未知，不等于模块加载、新resolver功能或新包生产验收。

B按同包依赖补`build_context_proof(execution,*,session_id,run_id,actual_system_prompt,actual_input,actual_tool_names,native_memory_skipped)`与`verify_context_proof(execution,proof,*,session_id,run_id)`。A必须从实际agent已组装提示、实际官方已接收input（或已核官方完整body fingerprint对应input）、真实enabled三工具和实际memory/context/background关闭标志取值，不能把expected模板冒actual。构造器检查冻结提示确实包含、输入精确相同、仅原三工具及字面True，产出实际完整系统提示hash、输入/声明提示hash、payload/snapshot/模板/上下文版本、session/run和工具集的最小proof，不持久原文。核验器重核原执行/版本/session/run/工具和严格布尔；proof本身不认证worker或替代A原账本/task/lease/官方来源验真，不授新执行权。完整性核验支持到期后对账，真实工具仍须活动时间/权限检查。

MaterialEvidence增加host-only scope，原turn默认标签/算法不变；执行scope内层明确this_execution_observed_pages，B1 source=material_execution_files，缺项始终含business_data_not_read和long_term_goal_not_assessed，as_of仍真实工具读回时间，非业务日期。读任务可在明确局部范围完成并保留未读缺项，不能由一页成功推全workbook或目标达成；产物还须A读取实际metadata/hash/版本关系与字节。新增4项proof/标签边界与原相关测试合计40项零failure/error/skip通过，随后原Core最终198项全部通过、零skip。4条受影响Python路径3.9 AST/diff通过；知识plan仍既有错误/exit1，未扩修。完整A组合、最新LinuxCI/独审和真实运行仍待完成。

#### A完整候选集成与主控核心复核

正常ff合入A固定51af0a424e7e1155073e58f7cc3df64dfe1291ed（main仍d279），实际21条A路径符合登记；B目录相对42b6df09逐字节无差异。原TaskStore真实行/私有映射/单attempt与原session/key/body绑定、execution-bound上下文、仅SELECT原官方账本、三层file-only/零transport retry、结果文本与最小receipt分离均已进入候选。原HTTP沿正常owner/cid，显式read_scope首次冻结进新材料目标/handoff；不同原ID选择推进selection_revision，默认全workbook或明确局部区间分别验收。原outbox列不回填、FC create/spec/未知controller不改。

A同固定输入的本机证据复用：原store入口83（含新材料20）、deploy22、channel12零skip，Node原入口及本地Chromium/loopback下载通过，15Python路径3.9 AST及diff通过。Personal独立新材料20与当前组合Core198均零failure/error/skip，亲看4张candidate-only浅暗/展开/390图（A临时截图目录fs-materials-ui-szads3wx）；不视为生产视觉、真实SDK或模型通过。

主控核心复核发现两项同包待修，已交唯一A处理，未提前派独审/合并：一是MaterialService._parts未串行runtime cache首次创建，真实temp DB加同步点可使同owner/cid两调用取得不同实例，后写缓存挤掉在用实例，后续reconcile会误按重启路径停止原任务；二是UI修订把选中file_id排序取首个，和“第一份勾选文件”的人类含义不一致，会静默修改另一已选文件。要求A补短缓存锁及并发回归，UI明确单份/目标文件选择与反序ID事件回归。保持一个集成草稿，待更新完整SHA的相关检查、LinuxCI及Business独审再作合并判断。当前生产仍501f，未pack/upload/apply或运行模型。

### PR723派审版本收敛

正常merge A修复固定501239c434ae6931cf44b19980b51c828fafac3f，无冲突，仍同一个PR723；9条差异仅属A已登记路径，B目录相对42b6df09无差异。runtime独立RLock只覆盖cache取建并返回锁内局部引用，DB/授权构造、执行与网络在锁外。修订前端单选及事件处理双重拒绝多选，并显示真实目标名；读取多选和后端显式目标能力不收窄。A在内存装回旧51af后两个新增回归实际失败，修复后通过，未修改跟踪旧源。

Personal沿原pr_fast.units独立运行新增并发2项零failure/error/skip，原Node入口真实DOM/fetch含两种勾选顺序及逆序ID回归通过；查看新candidate-only深色展开图，目标文件名已可见。复用未变输入的材料20/Core198、A原83/deploy22/channel12及Chromium证据，不宣称本轮全部重跑。原知识收尾失败状态保持，生产501f未变。当前两项主控P2已收口，冻结最新完整集成SHA交唯一Business Sol High独立worktree审核心；LinuxCI/独审返回前仍draft、不合并、不部署。真实SDK/模型/费用、生产停止/第二身份/A2scope/200%与生产视觉未验。

### PR723代码验收合并与发布交接

Business独立工作树t3-67218b89在起止均核head d5f0df0c02d87993e8d676b45fde9c277b2bcdd0/base d279086292f514002adadf801468e077dc7f3a1a、origin/clean一致，审阅28路径核心，无新的可复现问题；独立材料22/Core198/deploy22及Node零failure/error/skip，两项主控P2的新旧对照成立。执行平台codex-business、gpt-6.1-sol High，未启动其它Agent/改GitHub内容。GitHub机器人另一次自动审查未能完成，仅摘要提示、无具体代码意见，不冒称其通过、不重复触发。

CI41258739182首轮在APT浏览器依赖准备停滞至10分钟上限取消，实际测试未开始；同SHA原job重跑成功。PR转正式触发仓库原ready_for_review CI41260030720，GitHub曾以required pr-fast in progress拒绝正常merge（405）；等待该轮成功后才继续，未绕保护/改依赖或检查范围。两轮成功日志均绑定上述完整head/base，Ubuntu22.04/Python3.9.18实际会话97/Core198/deploy22/channel12零失败零skip，新增并发/原ID丢202和Node入口实际加载。

Personal复核最新head/base/必要检查/无冲突及无未解决具体意见后，按用户既有授权正常merge PR723，提交5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f；本机fetch/ff并核merge树与reviewed head完全一致、工作区干净，已停止PR723监听。至此只完成代码/本地合成与Linux验收，不代表新包上线或阶段2整体完成；旧知识收尾错误仍未完成。生产仍按最后有效记录501f90bf，真实SDK启动恢复、DeepSeek/费用、生产running stop/第二身份/A2scope/200%及新部署视觉未验。

下一步交唯一A沿既有Hermes发布测试授权，以最终main merge SHA新Git LF pack、新现场baseline/stage/manifest/备份，核501f精确installed proof与24目标/46保护/8新增，沿原publisher inspect/锁/CAS/准入与UNKNOWN围栏。先做实际固定SDK无模型装配/三工具/上下文proof检查，避免把agent夹具当实际运行；依赖或保护不符即保留原版本并报具体阻塞。符合原发布条件和正常工具审核后继续原apply与读回，不复用旧失败stage、不扩IAM/业务写/新预算。真实认证、少量合成材料任务/停止及浅暗/移动/键盘验收仍须取得实际证据，遵守当前浏览器工具边界；工具或正常登录途径不可用就如实留未验，不伪造身份、会话或视觉通过。Personal审核A实际回执后再推进主方案。

### 5f99现场准备与锁忙回执

A在原分支干净ff最终main5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f后新Git LF pack，payload SHA256 `041ccf76093a0f337fbb75ef90a09ae91d5d004f56cdade2a98d330c92c48310`，stage `/var/tmp/fs-materials-5f99-20261101T013900Z/stage`，manifest SHA256 `4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881`。24目标/46保护/8新增及501f原proof/Git通过原inspect source/protected CAS；19个目标实际改变，Nginx字节不变。尚非安装成功。

A零模型检查使用实际固定容器的原venv、原FS挂载配置/opt/pilot和真实官方AIAgent/registry，三文件工具、1048576上下文、实际skip/memory属性及15字段proof兼容，socket全阻断且0网络尝试。隔离合成输入、session_db=None，没有正式APIServerAdapter/HTTP admission，故只记真实SDK构造通过，不记accepted input或正式执行回执。初次系统Python缺dotenv、其后probe误用host路径产生meta tools/null context均按probe设置错误保留，改用真实venv/mount通过；未安装依赖或改配置/权限，不冒生产故障。三官方文件hash继续匹配pin。

仅一次apply（原release ID nav-20261101T013519Z）在原live_lock取得collector.lock时errno11中止，持锁pid18397/python3、unit fs-transaction-collect.service。未进入Hermes准入/provider围栏、备份/journal或目标写入；24当前仍全部before、46保护匹配、8模块仍缺失，无backup/journal。worker/range/nginx仍active且原PID10943/11083/31780、容器/StartedAt未变，range health200/ok、匿名worker401。原publisher源码锁/写入顺序与此回执一致，分类为写前正常锁忙，不能记已部署或已有UNKNOWN写入。

已交A沿原授权等待采集自然释放，不取消任务/抢锁或改服务timer。释放后重核原发布ID无backup/journal、全部before/保护/原image/状态/quiescent；在原1小时fresh窗口及输入全相同时可按原ID有据续试原publisher。过期或输入漂移则用同固定Git载荷重新prepare新现场baseline/stage/manifest并保留锁忙回执，不改时间或跳CAS；若已有journal先对账不盲重apply。当前生产仍501f，真实认证/模型/停止/新部署视觉未开始，不把SDK构造当这些验收。

### 5f99软件实际发布成功（后续真实使用待验）

A于2026-11-01T01:41:35Z只读确认collector自然inactive/dead、MainPID0、无锁持有者，未干预采集。按原ID nav-20261101T013519Z重核backup/journal不存在、24before/46保护及owner/mode全等、8缺失、原image/服务与baseline fresh，再次原inspect通过后才有据续试。原apply成功为applied-awaiting-actual-http-role-acceptance，source固定5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f，payload041ccf76093a0f337fbb75ef90a09ae91d5d004f56cdade2a98d330c92c48310，manifest4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881，均未换包。

真实备份为/var/backups/fs-navigation-20261006/nav-20261101T013519Z，成功journal SHA256 `3f6d474d37716610de334f14b9b7a699f879aae170471c065f5007c47e3ab93d`，备份manifest与approved字节相同。A于01:44:15Z逐项读回24afterSHA/owner/mode匹配、46保护SHA/owner/mode未变；新容器9c0225c7ea03f676c10ff9f1b2181fa0c5dda8f472f6e6834ea616ba015b5db7，沿原image8251bc53…3544、Running=true、StartedAt2026-11-01T01:42:47.848543281Z。worker/range/nginx PID1434/1616/31780均active，range200/ok、匿名worker401。经原MaterialRuntime._rpc内部身份通道GET capabilities，fs_materials三字段verified_pin/readonly_original_lookup/single_post均True，不读取输出凭据；该内部结果不替代正常FS用户角色。

因此当前生产软件源由501f推进到5f99，先前锁忙记录只保留历史。零模型实际SDK构造证据复用，无正式accepted输入、真实模型/费用/停止、正常FS角色或新部署视觉已验声明。Personal核到本机既有browser-act 1.4.2及完整core技能，存在FS专用浏览器与A自有会话；未创建/操作浏览器或转移认证。A沿既有正常登录、当前允许的非preview通道继续少量合成材料/真实proof与下载、fresh浅暗/移动/键盘取证，Personal不操作A会话，回收实际结果后再作最终审核。没有新账号/配置/预算/依赖安装；未取得真实证据的项目保持待验。

### 5f99真实材料入口404阻塞

A自有BrowserAct会话的正常认证及会话列表200；新建专用合成cid `fa7ea40c42bc4833bdff3788f1d733f9`，上传合成CSV 201，2061 bytes、SHA256 `31f3057e1b6b72cb930b65fbfd10bd362e4a3e599803c5d5f11af692a76cadd3`，file_id `55b55801892a3d83c3fc699f98da4a8a`。显式勾选后正常UI仅一次POST材料request `material_da2c98dcd8d3464fb4db5f065f0ea110`返回404 application/json。UI保留原ID unknown与恢复入口；故障注入discarded=false，未丢弃成功202，不能记丢202恢复验收通过。A停止后续模型任务与重POST，没有R2/R3。正常FS登录/创建/上传已有真实证据，但材料执行与整体功能验收阻塞。

A限定该合成请求的任务DB元信息检查发现selections/material_runs/goal_outbox三个私有表尚不存在，未取得task/run回执；此信息和404不足以单独证明永未接收或零费用，费用继续unknown。软件24/46及服务稳定结论保持，不临时改生产、不清理原请求或UNKNOWN。

Personal本地读已发布Git源码确认两个HTTP适配均包含materials分支；实际range_api先把/opt/fs-hermes-fc置于sys.path首位，再按同名导入conversation_http，而publisher HTTP目标位于/opt/fs-exact-range-20261001。因此存在旧同名模块遮蔽的待核假设，尚非已证根因。已交唯一A核实际导入文件/code filename/hash和materials分支元信息、区分路由404与内部LookupError，不导生产源码正文或扩大数据查询。若证实缺口，由A修最小装配接点并补真实目录优先级/旧同名模块存在的回归；Personal不并改A源。必要完整后续候选仍须最新SHA独审、CI及正常合并，publisher必须核当前5f99成功manifest/journal与实际before，不能重放旧stage或继续沿501f未安装假设。

#### 有界因果收口与后续诊断包

Personal独立读取共享Temp的browser-material-r1-audit.json及material-r1-early-db-metadata.json，确认一条完整合成payload、原request与file/SHA、discarded=false，未取得task/run回执。普通会话detail/files同正常浏览器身份200；先前材料GET已经发生，可能初始化私有表，故停止此探针。02:08:29Z已知conversation DB的该synthetic行存在、已知tasks DB三namespace仍缺失，只是后时点mode=ro事实，未测运行对象实际DB位置，不外推从未执行或零费用。A已关闭自建BrowserAct会话，用户原页未动。

8931实际监听为range MainPID1616；其启动argv指向已部署range_api，文件25729 bytes、SHA256 584cb74985b7f44f8e9d85ac1a4e9681de62af65133fb62b5b65095af94d83f3。独立fresh进程按现场目录顺序选择range HTTP，文件SHA256 3d5f245da179f0a3cb7abbad2fcbf6aa3bbe749f7090c5bd188d8aca11de90cd且含materials，但不证明运行中服务内存。现有回执not_found不能区分未命中与LookupError；不以ptrace/信号/临时patch/重启取内存，不按shadowing假设先修。当前结论仍为根因未知、真实材料验收阻塞。

已交唯一A一个完整后续包：在现有HTTP/range与发布封装登记范围内，加入正常原鉴权和同owner/cid约束的GET runtime-diagnostics窄入口，读取已存在DB须mode=ro/SELECT，不调用_parts或构造Goal/queue/ledger。只返回实际适配器/code来源、已加载code指纹与当前磁盘hash分列、材料服务绑定及store/tasks对象预期路径匹配布尔值、固定路由能力版本；不输出身份/凭据/环境/正文/任意DB行，不加入匿名health。材料404仅加固定阶段枚举，权限与原状态码保持，不回异常文本。目标是0模型、0材料提交、0私有表初始化即可区分当前装配及早期归属失败；不另造通用诊断服务或凭猜测修改导入。

A独占两份conversation_http.py、range_api.py的必要接点、材料相关测试、原runtime_prepare/runtime_release/test_runtime_materials及模块交付记录；B/helper/主方案/CI驱动不并改。检查覆盖真实临时DB的诊断无写入、同owner/跨owner/撤权、同名模块与早期owned错误分层；复用未变范围证据。发布适配以当前5f99成功manifest4057435d与journal3f6d474d钉住24已安装目标/46保护，8模块已存在，保留原publisher与所有围栏，不复用501f缺失假设或旧stage。候选经最新SHA独审/CI/合并后才新prepare发布。重启会改变进程内存，即使问题消失也不能倒推旧根因；原材料request继续保留，不盲重POST或创建后续付费任务。

#### 诊断包固定候选集成

A最终固定候选b3efed2e0c6acceed08334ee599e2d13fe6f003d已正常merge到Personal分支，A十路径与候选完全一致；当前main仍5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f。没有B/Core/UI/controller/SDK/CI驱动或冻结publisher差异。runtime-diagnostics从正常原鉴权/owner进入，只读实际对象DB；range单独承接该GET以观察原import绑定的handler，不替换普通handler或改变sys.path。加载code的marshal指纹与磁盘SHA分列，不作跨解释器或Git源指纹等值声明。材料404保持原状态与error，仅固定source/stage；submit_owned须实际_queue和_owned code对象均在异常链中，非仅函数名相同。原请求与discarded=false、费用unknown继续保留。

Personal集成后原runner诊断7项全过、零skip；Windows工作目录deploy23出现既有CRLF相关2error/1fail，未改冻结代码或测试。仅相关模块Git archive LF字节复核时22项通过、旧HTTP一项WinError10054；该失败用例独立复跑通过。故不称本机完整23一次全绿，Linux最新SHA整组结果待CI。A自身相关FileTests10、诊断7/deploy23及identity末次单用例证据依输入分层复用。diff check通过，测试/生产/模型/浏览器未混同；旧知识closeout失败保持。下一步唯一Personal草稿PR，Business独立worktree按最新完整head/base审整个12路径（A十路径加主控两份记录），必要CI通过前不合并、不交现场部署。

#### PR724已合并，交A发布诊断入口

Business在独立worktree t3-5b304c2f审查head d63024ff4d13f8747539d6eae98ed1f127ef8f4c/base5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f，起止GitHub版本不变、origin/clean正确，12路径无可触发且有实际影响的问题；原runner独立诊断7/runtime发布13/HTTP-release10均零失败零skip，发布23分两次执行。执行设置codex-business/gpt-6.1-sol High，未启动其它Agent/生产操作/发布GitHub意见。

首轮LinuxCI41265633376成功，转正式触发仓库原required CI41265895674；期间虽收到旧轮通过通知，Personal复核新轮仍在运行后没有合并。待新轮job124728506754完成success，实际日志绑定相同head/base、Ubuntu22.04/Python3.9.18，Core198、conversation104含新诊断7、deploy23全部零失败零skip，才按用户既有授权正常merge。GitHub机器人自动审查未完成，仅摘要无具体代码问题，不重复触发或冒称机器人通过，也未绕仓库保护。

PR724正常合并提交f79e29f0d5921b103a218c5e6ed967a754858b9c；Personal本机fetch/ff、merge树与reviewed head git diff空、工作区干净，已停止PR监听。代码验收完成不代表诊断已上线或原404恢复，现场最后有效软件仍5f99。已向唯一A交最终merge SHA，沿已审--materials-diagnostics/--followup新Git LF pack、新fresh baseline/stage/manifest/backup，钉5f99成功proof，24现存/46保护/NEW空，仅两HTTP目标改变、原8模块保留、原围栏下只重载range；回收全部after/mode/root与保护及实际进程/image读回。

现场先用正常FS身份对原synthetic cid做runtime-diagnostics GET并核白名单/表计数不变，0材料POST/0模型，不用原materials detail/result当纯读。原request保持posts=1/discarded=false/费用unknown；真实诊断结果回主控后再决定下一接点修复或有据恢复，不开R2/R3、不换ID绕UNKNOWN，不以新进程结果倒推旧根因。新诊断发布、原请求执行、费用/停止/视觉/A2scope仍待验；旧知识收尾失败保留。

#### f79软件发布与真实正常角色诊断已核收

A最终f79e29f0d5921b103a218c5e6ed967a754858b9c新Git LF包descriptor95589f43b26ec4ed48afdc7e150af6c7a522383cc3aff7fbb3573d8d66832412，stage /var/tmp/fs-materials-diagnostics-f79e29f0-20261101T024200Z/stage；baseline02:43:02Z、manifest25cd452cfb25790502cab7a7561187f04da5af6e2096baf9a71fabb11ad199ee，真实5f99 installed proof/inspect通过后一次apply成功。backup /var/backups/fs-navigation-20261006/nav-20261101T024500Z，journal534a813b17ea54422131403075156ec82fa2696959c575211e29cee3c0c6cdab，status仍applied-awaiting-actual-http-role-acceptance。

Personal实际读取共享Temp FS-Hermes-Diagnostics-f79e29f0-20261101T024200Z/receipt-index.json与八份限定收据，index SHA256 1d40e02f6f1d2c7d6a5fca040a1cdcac451027058612f40a4b5c1d8617ee134a及八文件大小/SHA均匹配。独立git show最终f79 LF逐项重算24目标候选SHA与收据current/manifest全等（Nginx按已钉原字节SHA），46保护hash/mode/root前后一致；实际改变恰两HTTP目标，22未变目标inode/mtime一致，container前后相等。range PID1616变18220，worker1434/nginx31780不变；原container9c0225c7…b5db7/image8251bc53…3544/StartedAt01:42:47.848543281Z保持，health200/匿名worker401。此为独立核收A真实现场metadata，不冒Personal亲自SSH或重新部署。

正常已有FS认证下02:46:10.623Z原cid/runtime-diagnostics GET200、无redirect、适配器头materials_runtime_diagnostics_v1。实际module_path/code_filename均/opt/fs-exact-range-20261001/conversation_http.py，loaded code c48a9563baf14869acd2e68811fbf4448086ee52a9c0072458af01cee46be742与disk97f8d6982beeba363885bc9fb4f354b4907dc6f492a40d545ef2f5af652a82a4分列；materials分支/服务与store/tasks绑定/期望路径六布尔true。匿名credentials:omit GET401 HTML、无适配器头，未读正文。前02:45:58与后02:46:33两库databases元信息完整相等，原cid1行/turn0、goal/mutation/outbox/identity/selections/material_runs尚不存在、tasks总数346不变。仅2GET/0POST/0模型，A自建BrowserAct session已关闭、用户原页未动。

当前可标f79软件发布及正常角色受控诊断通过；不标旧404根因、材料功能或费用通过。A记录af2648d4fd8d08b19436ef761d04995a24b828c1仅部署附录26行已普通merge，运行字节与最终f79不变，不重pack/部署/旧测试。随后交A仅一次原request的materials状态GET作有状态恢复准备：明确允许已审私有表初始化，非纯读；不能插入selection/goal/mutation/outbox/materialrun/task意图行或start/reconcile/stop/recover/模型。限定原cid/request、正常原owner、无query、无result/其它ID，前后只读计数核未产生任务，回收固定stage/adapter和原ID状态。若当前lookup查无仍不外推旧费用0或任意官方run不存在，真实schema/授权错误即保留原ID回报；暂不恢复POST或开R2/R3。此为主控核收后的明确下一步边界，不自动重试UNKNOWN。
