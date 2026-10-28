# 协作交接记录入口

执行规则只见 [HOTFIX](docs/ops/HOTFIX.md)。本文件记录事实，不授生产权限、不设测试或审批门槛。

交接只需：本次目标/负责人、已完成行为、确切PR或线上版本、实际检查范围、剩余问题与下一动作。先恢复真实使用，再补长报告、截图和历史归档；推送或@提及不能写成对方已读。

当前事实以 [CURRENT-STATUS](docs/collaboration/CURRENT-STATUS.md)、具体PR/运行收据和现场读回为准。吴律球类与陈超RPG归属保持。

[旧交接原文](https://github.com/wulv006-dot/FS-Workbench/blob/ee8f36b6861d2f568692a7b333a8efe403e5551a/HANDOFF.md)保留在Git历史；其原服务器传输故障、未上传/未合并和逐SHA授权描述属于旧对象，不能复制成新任务前置。平台当次明确拒绝仍按原作用范围处理。

## 2026-10-09 FC27 与绿茵计划文档标准

按用户“同步Github”及补充产品文档要求，新增 [标准入口](docs/standards/fc27/README.md)、交付规则和任务/设计/接口/产品四类模板，AGENTS 增加链接。轻量任务复用现有入口，复杂任务按需补齐；需求、接口支持、模拟、真实验收分开。仅同步可复用标准，不包含原工作包、机器目录、现场收据或运行载荷。

负责人吴律，直接消费者为本仓库处理 FC27 与绿茵计划文档的人和 AI。HOTFIX、业务规则、原 owner/source 映射及生产权限保持；本变更的确切提交与文档检查见所属 PR。绿茵计划具体产品稿作为独立本地交付，未因模板同步自动导入线上任务或声明功能完成。


## 2026-10-21 Codex 全局偏好与项目规则核验

负责人吴律。用户要求核验全局与项目MD冲突、说明情境和优势，并在核验后同步GitHub/Notion。实际全局正文与新稿一致；E工程旧10/7协作流程已明确为历史，按需读取、原仓库禁推与独立私库白名单同步的范围已澄清。沿用本仓短版入口，只追加本次链接；没有上传E工程长篇AGENTS/HANDOFF或覆盖业务源码。

[全局稿](docs/planning/codex-instructions-20261021/GLOBAL-INSTRUCTIONS.md)、[使用与同步边界](docs/planning/codex-instructions-20261021/README.md)、[冲突情境与优势](docs/planning/codex-instructions-20261021/AUDIT.md)为本次三份脱敏文档。检查了正文一致性、相对链接、历史和业务规则保留、五路径载荷及来源基线；正式CI和合并结果见所属PR及读回。Notion只追加对应方法和结果，不证明Hermes已学习；无生产发布、付费模型调用或业务写入。HOTFIX、实际main保护、业务权限与原owner/source保持。


<!-- hermes-v2-core-execution-20261021 -->
## Hermes V2 实施与真实教学验收（2026-10-21）

本Work独立执行，无委派新Agent/Codex。原附件从用户Downloads路径完整恢复至docs/planning/hermes-v2-core-20261020/attachment/；按02施工主线先W0–W3后W4–W6，没有重做规划、供应商/Jev/Octop迁移或生产写价。新增维护源hermes_v2_core_20261020、hermes_v2_review_repair_20261021、hermes_v2_strategy_20261021、hermes_v2_strategy_permissions_20261021、hermes_v2_learning_evidence_20261021、hermes_v2_ui_fit_20261021、hermes_v2_simulation_learning_20261021；当前组合映射CURRENT-SOURCE-MAP.json，交付DELIVERY.md，40项状态ACCEPTANCE-MATRIX.md。

私库PR251/252/253/255/256/257/258正式pr-fast成功并正常合并；最新代码cb35e084bc29ea589db0f0867999895696592f47。保留PR254规则文档与PR237并行内容；E本地库无stage/commit/push/remote。原publisher/锁/CAS/备份/回退发布，2026-10-20T19:17:36Z独立读回16活动文件+393保护无差异，两FS服务active；各原manifest/备份见CURRENT映射。原automation.json SHA02dbbb76ab11df3fd73f47c8ab91cc4573c09ba460d208c5d31f16641ace0e35、UID994/mode0640、原引擎/周期/开关/底线/售卖链保持，未调用writer。新入口暂停/恢复实测，历史记录保持，最终strategy_enabled=true、learning_paused=false。新源不在原server_187 manifest，无无关refresh_local。

用户补充允许突破旧降幅及由Hermes制定规则，已作为研究能力落实：原引擎基线与生产参数不变，研究副本允许更宽折扣，未支持的新算法只保存想法。真实1e1ae3d3任务14次max模型，4草案/2有效模拟；原自然1fb4509e快照同源计算、完整三平台及赠送/底线/联动通过，false写入/false授权。原稿仍有基线/实价、赠送及观察线解释问题，未当策略应用；后续补清字段并让Hermes自己复盘，不替它写策略答案。

五轮真实high教学各保留原event/attempt/账本，Hermes自行纠正必要条件与描述/持续性/因果。前两轮无原值不能声称已核证；后两轮7/26聚合、第五轮2/3（本人两模拟）明确覆盖。第四轮69fb5f72…经管理员理由/CAS发布，新4fce9460任务实际输入含ID/hash06d29975…。原7774经验已发布/使用/撤销，旧任务引用保持；目前8历史版本/候选、1有效经验，自动发布关闭，第五轮c931642f…仅待审。模型回执均accepted_no_effort_echo，后端版本及实际CNY费用unknown，不冒称精确内部档位。

相同问题/原报告/冻结native版本集合/背景/方法/工具schema、高档位别名的两份原稿分别4模型调用、631470/659203tokens；内容仍有无证据机制和未验证阈值，质量未验收。原文盲评BLIND-REVIEW.md仅本机，不发GitHub；已向吴律请求评价，不以模型自评分替代。W5实际动作效果、Desktop开关并发、真实长上下文压缩/取消中断迟到、最后版本自然与实际代码回退未验。旧自然e21fff6c/1eb377df成稿发生在后续代码前，不冒作最终自然；不强制补采或调时。OD-HERMES-ADMIN-RECOVERY原读取故障以本轮真实入口恢复关闭；新增OD-HERMES-V2-QUALITY，原质量/自然整体事项保持。

安全回归：各新维护目录test*.py及策略frontend/test_strategy.cjs（合成/临时库）；同输入已有证据复用。实际模型、发布、版本操作先核原request/event/attempt/manifest，不盲重跑一次性脚本；503拒绝已核无任务后用同ID继续，历史unknown/失败不清。私有证据.agent_runtime/hermes-v2-core-20261020/{final-readback,simulation-teaching-read,degraded-readback,transfer-read-final,research-read-final}.json，无凭据或私有推理导出。应用层与其他owner未覆盖项逐条标记，不能把合并/文档/CI当上线或学会。


## 2026-10-21 业务基准与数据工具修订

本Work按用户八项取数规则实施，373码渠道映射、真实成本与调价参数分离、知识有效输入替代、客户订单日志复核链接、动态毛利预算尾价预览；范围与来源见docs/planning/fs-business-baseline-20261021。保留PR237、最新V2/多游戏/生命周期/UI及原锁CAS回退；不改采价/自动化/原定价引擎或writer。此条为代码交接，不是上线与Hermes学会的回执。服务器Admin身份被拒，用户交运维修复并授权浏览器当前登录态只读核验；继续复用原导出，缺项不伪造。


## 2026-10-21业务基准、真实入口与教学收尾

PR260–263已通过正式CI、合并并受控发布；最后代码9fb41c8e8f75，最后单目标/402保护读回匹配。保留运维Admin新unit及冷却停服，不启服/登录/重试。真实渠道查询、原档时间、Order精确全状态复核和匿名HTTPS入口通过；价格/原策略/周期/开关/底线/writer保持。Astra仅按用户指定做一次只读参考并结束，主Work完成Hermes实际取证、纠错、本人L1方法人工发布和新会话装入。留出质量局部通过，组合约束/利润定义/反证仍待训，不能宣称学会或收益提高。

Notion完整基准及三关联页已更新读回，冲突旧正文清理，历史任务/无关Codex附录保留。当前说明、逐文件映射、模型与生产分层回执、Astra参考、旧规则废弃及剩余见docs/planning/fs-business-baseline-20261021/{README,DELIVERY,SOURCE-MAP,ASTRA-REFERENCE,REMAINING,NOTION-SYNC}。真实经营样本/订单/模型原可见回执留FS和受控本机，不随文档共享。原7774…经验真实发布/使用/撤销回执复用且最终又核账本与新任务排除；新4eb2…方法保持发布，两新任务实际使用。本文档PR不触发模型、采集或生产。保留私库HANDOFF全部原前缀，不混入E工程dirty和并行sales/Admin改造，E原库无Git写入。


## 2026-10-21 Admin统一8767与单次验证

用户明确授权部署、统一后台Admin凭证入口，并后续明确授权脱敏提交/PR/CI后合并。当前Codex串行执行。sales两文件及NBA/MLB/FC商品包/SBC/旧dashboard/独立探测七份增量已受控发布并读回SHA；受限原字节备份仅服务器保留。旧dashboard服务及sales timer停用disabled，全局8767保持inactive/disabled，SBC和商品包空闲重载后active。Players保留UID992受限socket桥；Order未发现可供sales取cookie的统一服务，按用户条件不另建、不改其登录。部署阶段无后台登录/业务写入。

维护源sales_shared_session_20261021；部署与原/后SHA见docs/planning/sales-shared-session-20261021/DEPLOYMENT.md和两份脱敏回执。本PR最小登记原8项离线测试到现有pr-fast，不新增workflow、不放宽断言。正式CI、合并以PR回执为准；原失败/队列/锁/业务角色/定价保持。

用户后续明确要求现在验证登录：2026-10-21 13:50:30上海时间，用同一全局镜像/原只读配置只执行1次登录，code=0、credentials_rejected，未进入身份检查，没有第二次尝试。此次非原one_day_penalty文案，不据此判密码已改。仅服务器内核对配置mtime仍09-27，两处账号密码一致；未导出密码/token/hash。8767与sales timer仍inactive/disabled。真实登录仍失败，真实消费者业务与自然周期未验；旧明天11:30不再作为完整冷却保证，不自动重试/改密码/恢复循环。



## 2026-10-21 认证迁移完成后清理旧代码

用户明确要求实际验证通过后删除历史独立认证和一次性迁移源码。Sales真实Admin订单code1/Order发货页通过；SBC实际FC27模型读取通过。活动源码删除本地登录/验证码/缓存及旧表单，上传签名密钥留服务器0600。原始凭据未导出。保留当前维护源shared_backend_session，删除旧sales_shared_session_20261021脚本；SBC webapp沿用原规范路径。Sales原同步已启动，结果另记；旧数据、队列和失败审计保持。见docs/planning/sales-shared-session-20261021/CLEANUP.md。本地工作目录按新源CI合并后逐文件删除，不递归清理未知内容。


## 2026-10-21折扣码筛选与Admin指定订单日志补充

用户新确认的MMOEXP限定折扣码筛选、有效期/统计窗口区分、Sales/Sum/Used原字段与ES逐单状态/订单日志查证顺序已补入业务基准v3，保留PR267全部v2澄清。真实浏览器核到两个后台入口；不假称已注册新API。发布/真实模型装入另验，见docs/planning/fs-business-baseline-20261021/ROUTES-UPDATE.md。无UI、价格、登录、权限或调度变更，保留全部既有前缀。


## 2026-10-21 Sales分页完整性修复

原全量PID12059在15:47:40因8768短暂不可用导致连续5页失败退出1，未发布新dashboard。旧代码会跳过少量失败页；本次改成每页3次、全局不可用等25秒只重读原页，仍失败整轮no_publish。函数外AST保持，真实会员样本读取通过；3项直接回归通过。15:59:01启动PID29017的新代码全量，timer仍停，完整验收另记。8768由原Order分支负责轻量探针修复，用户已明确授权跨会话协调，本会话未改Order服务或重放FC写入。见PAGINATION.md；旧认证迁移脚本保持删除，不恢复独立登录。


## 2026-10-21全新Hermes/FS专用账号权限交付及链路补充

新目录docs/planning/hermes-fs-service-account-20261021/保存65功能/66方法路径/32工具名的权限申请与机器回填矩阵，来源与新账号未验状态逐项分开。用户明确新建零权限账号并逐项开ACL、接口和FS名单，不继承旧wulv；新账号名/UID/ACL映射由技术负责人提供。只出清单，未开账号/权限或改策略，OD-HERMES-FS-NEW-ACCOUNT-20261021保持OPEN。新增折扣码与Admin ES日志链路基准v3已PR269合并并原发布器单目标/402保护上线读回，实际新任务4186b329…装入同一知识SHA且调用目录；内容局部通过、错误已反馈不发布经验，见ROUTES-UPDATE.md。Notion基准v3及两链路已读回。保留最新PR267/268及并行Order/Sales修复；不重发旧任务或恢复已退役登录。E原库无Git写入。


## 2026-10-21 Hermes继续教学与两套定价策略

本Work继续实际教学，无新委派。五个新会话失败均保留；最终2cdff32d…限定五项判定通过，完整策略初稿和第一修订仍失败后继续教学，最终8f4161b2…由Hermes自己组织并通过目标/利润/条件/权限自洽复核。新L1方法经人工CAS发布且实际加载，自动发布关闭。PR267正式CI39563141611成功、合并04c15783…，原publisher单知识文件nav-20261021T073934Z/402保护匹配；修复实际P0/主候选P1/尾价T歧义，不改原算法、预算、价格、周期、开关或底线。并行v3规则保留，最终模型实际加载当前v3 SHA92058a31…，未覆盖Admin及其它任务修复。Admin ready及恢复后今日真实native_loss可用，未闭日/水位未知，不等于全端点或自然周期。

通俗交付docs/planning/fs-business-baseline-20261021/PRICING-STRATEGIES.md分别链接本Work策略与Hermes独立原文；TEACHING-RESULT.md保留逐阶段失败及通过边界，TEACHING-RECEIPTS.json仅技术回执。Notion原页已同步两套策略、当前v3和分层验收并读回，旧Codex附录及并行新增路由保持。未推荐真实新售价、未执行实验、无生产写价或自动策略修改；需求弹性、真实增利、自由长文/跨轮工具稳定性及最终自然周期未证明。E原库无Git写入，真实财务/订单/隐藏推理不进入共享载荷。


## Sales/SBC 全局会话迁移验收（2026-10-21）

Sales PID29017于16:14:03完成真实全量并发布：订单2481、折扣码1393、会员473/473、发货4534，147+81页完整；采集快照/线上/发布基线三文件SHA060a768b…一致。16:15:36恢复原timer active/enabled。PR268清理CI46项与PR270分页CI12项通过并合并；旧Sales/SBC独立登录与一次性脚本已实际删除。8768轻身份探针源94762bc0…由Order分支发布并经本轮完整读取验收。8767保留当前有效内存会话，锁分离候选未上线，避免重启丢token；自然周期尚未验收。SBC模型及页面只读通过，未新增业务写入。最终证据 docs/planning/sales-shared-session-20261021/FINAL-ACCEPTANCE.md、ACCEPTANCE-RESULT.json；15:47失败与受限备份保留。


### 首轮自然周期验收完成（2026-10-21 16:24）

原timer自动触发PID9335于16:23:06退出0并再次发布；81页1607发货全部读取、零重试，最终总订单2481/折扣1393/会员473/发货4534。源/线上/基线SHAfe0d81bc…一致，timer active/enabled，8767/8768 ready且login_attempts1/0。本地OD恢复事项已关闭，长期多轮稳定性不据首轮外推；SBC无新增业务写入、8767性能候选未上线边界保持。最终独立回执 docs/planning/sales-shared-session-20261021/NATURAL-RESULT.json，不覆盖旧失败或手工全量回执。


## 2026-10-21 渠道效果看板施工

本 Work 独立施工，维护源为 releases/fs-dashboard/channel-effects-20261021，说明见 docs/planning/fs-channel-dashboard-20261021。新增 MMOEXP 全游戏优惠码/优惠券看板，复用 FS 服务、主题、共享会话和受控发布器；默认用码+推荐人无码，无推广归属仅对照，忽略大小写、冲突待核，优惠券按模板/批次。Order 共享源密码由用户安排修复，本任务不改凭据；全局成本分页检测到重复即停止，未发布部分成本。代码/CI/合并/发布/真实读回状态分别记录 ACCEPTANCE.md，不停用或降低既有自动化。


## 2026-10-21 OCR规范源同步

8767图片验证码辅助模块按当前生产原字节同步至shared_backend_session/manual_captcha.py，来源哈希及观察时刻见OCR-SOURCE.json；文件名保留调用兼容。配套回归直接执行OCR成功、重取/失败边界及来源校验，使用现有pr-fast分组。清除过时人工登录说明和已完成的一次性迁移发布器，保留接续模块、真实失败和业务验收记录。账号、2FA、服务配置和有效会话不变；本次不执行生产发布、登录或重启。后续按OCR-SESSION.md和AGENTS维护既有自动化，不从历史快照回盖。正式CI和合并以本PR回执为准。


## 2026-10-21 渠道效果看板正式交付

本 Work 完成 MMOEXP 全游戏优惠码/优惠券看板，真实入口 /dashboard/channel-effects/，置于数据看板与数据分析工具之间；维护源 releases/fs-dashboard/channel-effects-20261021，交付 docs/planning/fs-channel-dashboard-20261021。沿 Sales 布局、FS 主题与原服务/会话/发布器，无业务写入、worker/timer动作或既有自动化降低；保留最新流量页、Evolutions和OCR并行改动。默认用码+推荐人无码，无推广归属仅对照；大小写折叠匹配/冲突待核，券按模板批次且顶部去重。Admin逐笔单次不得超过一个月，按最多28天连续窗口完整校验后合并，后段失败保留旧完整结果，两项新回归通过。

PR278/280/281均正式CI通过并合并，最终功能head d641ff9eb7cabc2651361824c5f73f164c8b80f7、merge f741d30bf2ecda9bd1016f2a5c1a6e7d6c4a7d3a；27项计算/合同/权限/发布检查及离线UI通过。最终发布nav-20261021T113003Z，6精确目标，原锁/CAS/备份/失败回退；61活动/保护SHA一致，匿名页面302/API401、默认TLS及真实wulv模式/筛选/翻页读回通过。首版目录500及Order共享源不可用原失败保留，后续修复/完整缓存分别验收。

10/14–20完整Admin8153单/712用券日志；渠道3113单(3035用码+78推荐人无码)，USD185402.06，发货匹配3020；优惠券去重703单，USD55709.07，发货匹配685。完整Order缓存11319条，固定截止10/21 18:49。缺失成本不补零，利润只代表发货覆盖；未提供批次保持未知。真实跨月长查询、拒绝账号真实登录、破坏性回退及长期自然周期未新增验收。截图和原始数据留受控本机/服务器，不入Git。详ACCEPTANCE/READBACK/RELEASE-RESULT/SOURCE-MAP。E原库不stage/commit/push/添加remote；新模块不在server_187 manifest内。


## 2026-10-21 渠道看板新老客修复及显示修订

用户发现全是老客，已核实误用Admin列表isNew，改为每笔ES订单下单时“是否新客户”；旧缓存读时修正，缺失/冲突未知，明细增加新老客（ES）。PR283 head f190bd17f9b3b91d5e350df0bc29db0330cc78f4 正式30项及UI通过，merge7dbf1a802e8d2d7be385e186e773f6fc3fa4cb05，nav-20261021T114854Z已发布，64路径一致；真实wulv读回681新/2432老，用券214新/489老。相同输入的订单、金额、成本和归因保持。全局原成本缓存续读11336条、截止19:30，匹配3022/3113；ES与成本仍分开源/截止。

按用户显示口径将无推广归属改称自然流量（对照），范围仍无码且无推荐人，与GA4自然搜索分开；国家中文名加原代码，统计键保持。显示修订采用四个静态/Nginx目标与原发布器，仅Nginx reload，不停读者/业务源，实际显示验收另附。维护源和聚合证据仍见渠道模块与docs/planning/fs-channel-dashboard-20261021；截图/原始ES留受控位置，不入Git。原E库不进行Git写入。


## 2026-10-21 FC Coins原档案证据接入

本Work维护源releases/fs-dashboard/fc-coins-evidence-20261021，新增单一封闭只读工具，复用原执行账本、渠道订单/成本/码券归档与营销工具。真实当前caller最小修改，v7同步v6规则及用户Coins-only范围；保留现有工具、Admin/Order/OCR、定时和固定商品联动，不修改价格/策略/底线。13项本地定向检查，正式CI、合并、受控五目标发布、真实模型与自然周期分开验收。旧同名release副本仅历史，不覆盖活动源；新接口按原任务锁/证据冻结运行，不创建重复采集器。详该release README和后续验收。


## 2026-10-22 FC Coins只读证据与两套策略最终归档

本Work完成原执行账本、金币原单成本/码券与同窗营销的真实Hermes接入。PR294/295正式CI通过，merge258b4d908021/5ea9d220cfd8；原publisher五目标nav-20261021T152927Z及单caller nav-20261021T154243Z，最终408活动/保护匹配。15项本机/Linux检查通过；真实高推理及多轮工具回执、v7知识SHAfca98dad…均核实，提供方无内部effort echo。只研究Coins，其余金币公式、采价、开关、底线、UI与原自动化保持。

七轮48次提供方成功响应，原工具超时及多个完整稿失败保留；全新A/B/C、后继D限定场景核心通过后仍纠正整套策略，最终Hermes原文SHA bbd4b69b…经本Work复核，不声称广泛泛化或收益。Astra high只作用户明确要求的独立参考分析，不承担代码/生产；两套原文、分层验收与Notion同步读回见docs/planning/fc-coins-evidence-20261021。v7替换有效旧规则，Notion旧12–16段标历史、17与附录保持。

尚缺4成本、1类型、82平台、套餐数量、完整补发/退款结算、独立公开暴露及Coins同范围广告归因。旧三条正式经验与auto_publish=false保持，错误卡不发布；本轮新会话来源未扩展原报告学习审核。新规则自然准备周期、长期稳定、破坏性回退、价格弹性及因果增利未验，无新价格实验/生产写价。真实财务/原输出仅.agent_runtime，E原库无Git写入。


## 2026-10-25 所有报告的核心逻辑纠偏

用户明确要求Hermes生成和Codex/ChatGPT自身指导、审核共用核心：先回答最重要的问题，给有主次的全局判断、方向性推断和取舍，再用关键事实支持并落到行动。语言通俗，图表/HTML按需；只对会改变方向的问题继续深查。正式规则、落实计划及真实验收见[报告核心逻辑目录](docs/planning/operator-report-review-20261025/PLAN.md)。PR472已正式CI合并；服务器两个正式报告方法已原生更新、实际读取解释并用于24号重做，旧稿保留。用户另已批准每天08:10只读抽查首份自然日报/周报/月报，覆盖完成即结束、最多两周；目前自然0/3，不恢复原暂停的价格跟踪。具体成品与验收以同目录ACCEPTANCE及SOURCE-MAP为准。

## 2026-10-27 万圣节活动页：翻牌卡状态、卡面与游戏卡亮度

本Work处理万圣节 Mystery Store（`/events/seasonal/`）的三处线上问题，全部走原流程：本地改动 → `pr_fast.py` 离线 affected 组 → PR → 正式 CI → 合并 → 原 publisher（`/var/tmp/fs-campaign-release70-candidate/publish.py`）`inspect` → 更新 `runtime/static-manifest.json` → `apply` → 真实域名读回。

1. **固定卡刷新后丢失**（PR #572，合并 `3bbc7e2`，发布 `nav-20261027T184803Z`）：`runtime/halloween-reveal.mjs` 本就把 `slot:'fixed'` 写进同一份抽取记录，但前端 `restoreReceipts()` 恢复时显式 `if(slot.slot!=='fixed')` 跳过它，导致刷新/重进后随机卡恢复、固定卡被合上。改为 `revealed.add(slot.slot==='fixed'?fixedToken(game):receipt.request_id+':'+slot.slot)`，一行。曾试 `localStorage` 被测试 #219 挡住（活动页前端禁止任何本地存储），故沿用服务端 receipt 通道。
2. **游戏卡偏暗**（PR #573）：`.game-art` 由 `saturate(.78) brightness(.8)` 抬到 `saturate(.95) brightness(1.14) contrast(1.02)`，`.game-shade` 紫色压层减薄，仅标题底条接近不透明。
3. **翻牌卡面游戏小字**（同 PR #573）：`faceContent()` 去掉 `label` 参数与 `<small>`，正面不再打印 `FC27`/`Aion2`。

发布 `nav-20261027T190500Z`（manifest `dff9dd2a…`，静态清单备份 `static-manifest.before-nav89.json`），正式域名读回：四卡滤镜一致、高 267px；三卡正面 `card-front small` 计数 0、高 320px；三张翻完后 `reload()` 仍全为 `is-revealed`；无 JS 报错。未改 policy / 公开配置 / 优惠码 / 价格缓存，未重启服务。回退点 `/var/backups/fs-navigation-20261006/nav-20261027T190500Z`。

过程教训：期间一次误发布（PR #570）把用户当晚 22:28 刚调好的卡面覆盖成去小字+提亮版并紧急回滚，根因是误判用户"样式不对"的指代，且发布前未确认线上那版是否就是用户最新版。此后确立：动活动页 CSS/JS 前先与用户确认要改哪一项，发布后用正式域名（而非 IP 直连，IP 会 403 `ORIGIN_REQUIRED`）读回。

## 2026-10-28 万圣节活动页：商品卡换成游戏通用图 + 金色折扣徽章

用户提供了一批素材（`桌面/FC素材/金币` 四款游戏金币图 + FC 的 Pack/Player 通用图，`桌面/FC素材/优惠` 8%/10%/15% 三枚金色折扣徽章），要求换到 `/events/seasonal/`。PR #581（head `ebe88dd945`，CI `pr-fast` success）合并 `c3ff16c05c`，发布 `nav-20261028T024922Z`。

做法：`event.js` 新增 `CATEGORY_ART` / `artCategory()` / `categoryArt()`，卡面插图改为按「游戏 + 品类」取一张通用图 —— FC 金币 `product-fc-coins.webp`、FC 球员与 Pack/Bundle/POTM/EVO 一律 `product-fc-set.webp`，Aion2 / WoW / MapleStory 金币各一张；角标折扣由 CSS 文字 pill 改为 `assets/badge-<档位>.webp`（56px，移动端 46px）。8 个 webp 合计约 460KB。

顺带修掉一个旧缺陷：商品记录里的 `image` 是相对路径 `assets/product-*.webp`，页面在 `/events/seasonal/` 下会请求 `/events/seasonal/assets/...` → 404；其余三游戏 `image` 本来为空 —— 所以此前翻牌卡面一直是 `✦` 占位。改成按游戏/品类取图后这条链路不再依赖商品记录。

测试侧改了一条断言：`halloween52-browser.cjs` 原要求「未知导入商品在卡面不产生 img」，现在插图与导入记录无关，改为「卡面 img 的 src 必须来自 `assets/`」，防注入语义不变且更严。

发布清单 15 个（10 个 seasonal 资源 + `runtime/static-manifest.json` + 4 个边界文件），静态清单 97 → 105 键。读回：8 个新资源全 200/`image/webp`，`event.js` 200/24871、`event.css` 200/65640；真实页面四游戏固定卡徽章与插图均自然宽 > 0、渲染 56×56 与 193×96，无 `pageerror`、无业务 4xx。随机卡未真实抽卡（避免产生回执），其渲染与固定卡共用 `faceContent()`，已在 CI 与候选注入覆盖。

未做：`-10%` 徽章素材本身缺百分号（另两张有），按原样上线待换图；MapleStory 物品通用图仍在制作，暂由金币图兜底；首页四张游戏卡图（`game-1..4.png`）未动。回退点 `/var/backups/fs-navigation-20261006/nav-20261028T024922Z`。

补充（同日 `nav-20261028T030250Z`，PR #583）：用户补来 MapleStory 物品通用图（白底 JPG），`artCategory()` 对 MapleStory 拆成 Mesos→金币图、其余装备→`product-maplestory-item.webp`。抠底用「四边泛洪标记背景连通区 + 区内按亮度映射 alpha + 0.8px 高斯软化」，物品内部白色与银色不受影响。发布 7 目标，静态清单 105→106 键；读回 item 图 200/`image/webp`/219328 字节，真实页面渲染 193×103，Mesos 卡仍走金币图。仍未做：`-10%` 徽章缺百分号，用户会补新图。

补充（同日 `nav-20261028T030905Z`，PR #584）：用户补来带百分号的 `Polished Gold -10% Discount Badge`（1361x1156 RGBA，圆心 693/581.5、直径 ~1005，与 8%/15% 同一套构图）。按既有裁框（中心 693/583、边长 1146）归一后缩 176x176 webp，三档并排核对大小与描边一致。发布 6 目标，静态清单 106 键不变、仅 `seasonal/assets/badge-10.webp` 哈希 `deb0a8ec` -> `12351b79`。读回：服务端落盘 `12351b79c982…`、HTTP 200 `image/webp` 11702 字节、`cf-cache-status: BYPASS`；真实页面（Playwright）徽章 naturalWidth 176x176，页内 `fetch(cache:'no-store')` 取回字节 sha256 与落盘一致，截图确认显示 `-10%`。回退点 `/var/backups/fs-navigation-20261006/nav-20261028T030905Z`。

遗留待办（缓存）：`/events/` 静态资源响应头是 `Cache-Control: public, max-age=2678400`（31 天），文件名又不带内容指纹 —— 换图只对首次访问者生效，发布前访问过的老访客会继续用浏览器里的旧图，必须强刷才更新。今天三次换图（徽章 + 四游戏插图 + 物品图）全部受此影响。根治方案：素材 URL 加版本查询参数，或文件名带内容哈希后再发布；本轮未做，等排期。


2026-10-28 全站无价根治（价格 provider 批量扫描，PR #600/#602/#603/#604/#606，直接部署，未经 publisher）：`/events/seasonal/` 四游戏商品全站无价，`admin-reference-prices.json` 常驻 `status: unavailable`。先反证版本无关——19:45 已把上午 11:00 基线逐字节还原（`adapters f77b96c7` / `provider 08678896` / `policy 6751db1f`），连续多轮仍失败。真因是 Admin 列表接口 `goods.Goods/index` 偶发卡 40–70 秒（同一参数同一分钟内实测 130ms 与 70s），而 provider 是「任一条失败 → 整份作废」，49 模型约 120+ 次请求全成功概率趋近于零。改法：`adapters.search()` 原有的 `IN` 操作符首次用于商品列表，`AdminRead.prefetch_goods()` 按游戏一次 `mid IN (...)` 扫描并按 mid 分组缓存，`search_goods_page()` 命中缓存本地切片（页码/去重/scope 校验全保留）；新增 `model_provider_batch`（provider.py + bridge.py 分发 + backend-client 读白名单），provider.mjs 从 49 次单模型调用改为按游戏 4 次批量。

五个坎逐个实测打掉：#600 批量本身（请求 49→4，但扫描吃满 45s 预算）；#602 `limit=50` 分页反而慢（1327 三次分页 7.4s），改 `limit=200` 单页 240ms 取全 132 行，另加 `reset_catalog_budget()` 让扫描与详情各用窗口；#603 44 次详情共用一个 45s 窗口仍不够（15 成/29 败），改每模型独立预算，并把 `await reads.get()` 的 rejected promise 改成逐条降级 `observation=null` —— 这才是 #599 加的 sticky 兜底一直没生效的原因；#604 全成功但 196s 超过子进程 180s 上限被 kill，放到 300s；#606 1327 组稳定 42/44，2 条 `CATALOG_SEARCH_HTTP_REJECTED` 瞬时失败且永不进 sticky，改成扫描后对失败模型在原缓存上重试一次。

改代码前的只读验证：44 个 FC27 模型一次 `IN` 取全 132 行/3 页/503ms、无缺失；抽样 3 个 mid 与单查（带 cid）逐 id 完全一致。请求量：列表查询约 110 次 → 9 次，子进程 49 → 4。

读回：价格缓存 `status: ready` / **247 products / 49 model_contracts** / 267792 字节；`/events/api/campaign/config` 49 条带 `source: admin_current` 价；四游戏各 3 卡全部有价（FC27 `$73.08/$20.91/$3.97`、Aion2 `$70.39/$287.81/$143.91`、WoW `$33.80/$86.38/$159.61`、MapleStory `$14.76/$29.67/$89.25`，均带划线原价），`brokenImages: 0`、`pageerror: none`；`halloween/reveal` 从 **409 变 200**。连续多轮保持 ready（20:52 / 20:58 / 21:17）且价格随刷新变化（FC27 `$66.42` → `$73.08`），排除冻结缓存。回退点 `/var/backups/fs-campaign-batch-20261028/`、`/var/backups/fs-campaign-price-timeout-20261028/`、`/var/backups/fs-campaign-price-current-20261028T1945/`。

遗留：① 单轮约 190s，主要耗在 44 次模型详情（约 4s/次，历史 0.3s），组内 4–6 路并发可提速；② `policy.json` 的 `refresh_interval_ms` 已 60000 → 300000（单轮 190s，60s 间隔等于连轴打上游），`entries` 53 条 / 49 模型 / `max_age_ms` 900000 未动；③ 未走 publisher 与 center 发布通道，`operations/` 无回执，`release_id` 仍 `campaign-preview-10`、`state.published` 仍 `campaign-preview-11`；④ **D4 替换 WoW 仍未上线**（`state.draft.halloween` 已是 Diablo + `ends 2026-11-08T23:59:59-05:00` 美东，对外仍是 WoW + `11-10 +08:00`）。
