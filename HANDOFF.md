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


## 2026-10-21 Admin 人工恢复及旧认证废弃

用户授权临时wulv账号及人工验证码恢复Admin，并明确旧独立登录入口废弃。8767于14:55:44单次登录后ready，下一轮仍ready且login_attempts=1；sales/NBA/MLB/商品包/SBC/Players共享桥真实身份读取通过。保留当前2FA源并改人工验证码收件箱；SBC当前版本重接8767，旧dashboard daemon已屏蔽，probe废弃；8767自启恢复。ops无排队后恢复，旧失败保留。sales定时器因Order会话未验继续停用。具体SHA/操作ID/备份/测试和重启限制见docs/planning/sales-shared-session-20261021/MANUAL-RECOVERY.md；不包含任何凭据或原始生产源码。


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
