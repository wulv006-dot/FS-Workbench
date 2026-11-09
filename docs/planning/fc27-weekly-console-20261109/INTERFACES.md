# 周更接入与发布清单

## 已实现入口

原服务前缀 `/dashboard/analytics/campaigns/analytics/`：

| 入口 | 行为 |
|---|---|
| `weekly.html` | 运营台；原活动分析首页、商品编辑页均有入口 |
| `GET api/weekly` | 当前三页映射、校验、工作单、历史、审批、原操作摘要与Hermes状态 |
| `POST api/weekly` | 工作单与证据/审核记录；继承FS管理员、Origin与CSRF验证 |
| `GET api/weekly/recommend` | 持久候选历史、原operation_id及过期状态 |
| `POST api/weekly/recommend` | 显式准备/请求本期候选；固定模型gpt-6.1-sol、高推理；不发布 |
| `POST api/weekly/reconcile` | 按原operation_id查询异步宿主；不再次派发模型调用 |
| `GET api/weekly/run` | 周更委派配置及当前操作者最近20条运行摘要 |
| `GET api/weekly/run?operation_id=UUID` | 查询原运行/配置回执；必要时只读对账原模型及原center操作，不派发或应用 |
| `POST api/weekly/run` | configure、run、reconcile、resume；配置周日计划或执行同一草稿流水线，不发布 |

写入请求保留 UUID `operation_id`；同ID不同内容409，同ID同内容核原结果。周更记录请求的revision来自GET api/weekly；推荐请求的revision是当前活动中心revision，不能用周更账本revision代替。

`api/weekly`动作：create、update、review、approval、pause、retry、evidence、hermes。scope为publish/coupon_write/schedule_enable/rollback只描述待批准动作，不直接执行。页面显示的operationId是计划创建ID；真实执行/回执使用独立execution_operation_id，并保留关联关系，不混同。

## 当前接入合同与待验范围

### Hermes provider

`production-server`按请求创建provider闭包，将当前已验证会话转交现役8931内部推荐入口；Cookie不进入候选输入、文件或模型。宿主再次验证会话及actor，使用独立campaign任务身份和现有模型额度。宿主协议及共享调用链见HERMES-CONTRACT.md。实现与离线测试不证明真实Sol已部署可用。

本地provider消费 `prepareWeeklyRequest` 结果及超时AbortSignal，跨宿主只提交固定contract、operation_id和限定input；模型、high推理、instructions及schema由共享宿主控制。返回对象必须回显model、source_revision、sbc_update_id，并只引用输入对应page允许池内的product_key。SBC同时要求合法core_product_key，平台错配/可售未知/过期/来源缺失均带待核原因。

单次候选更新输入包括id、observed_at、可选expires_at、context与sources（HTTPS来源、title、observed_at），仍保留人工登记入口。另有用户指定的周日12:00（Asia/Shanghai）自动草稿流水线，采用现有宿主tick，不新建定时器或后台；首次安装默认禁用，生产启用待批准。读取最新sbcplayer、Popular前三及最新Player真实目录，由当前冻结规则生成候选；未知游戏到期时间保持null，不以目录缓存TTL冒充。推荐准备与身份匹配不等于SBC阵容规则已验证，不自动发社区消息。

调用前持久pending，operation_id/hash与输入内容按操作者去重，超时/中断保留unknown；不得换ID重放未知模型请求。持久保存经过限定的task/run/usage回执，显式reconcile只查询原ID。关闭辅助层不影响center、公开页面、已有计划与候选历史。

### 周日计划、手动执行与原ID恢复

管理端 `api/weekly/run` 转发现役8931的 `/internal/hermes/campaign-weekly`。POST请求体仅允许以下形状，operation_id为UUID v4：

| action | 请求体 | 结果 |
|---|---|---|
| configure | `{action:'configure',operation_id,revision,enabled}` | 返回configured、原operation_id、新revision、真实owner、enabled和schedule；revision取GET返回的config.revision |
| run | `{action:'run',operation_id}` | 以当前会话手动启动prepare→外部取证→模型→apply_draft，与自动计划使用同一流水线 |
| reconcile | `{action:'reconcile',operation_id}` | 只查原模型及inspect_operation；不重派模型、不保存草稿 |
| resume | `{action:'resume',operation_id}` | 当前会话显式恢复已有完成模型的原ID草稿应用；只在can_resume时可用，不重新计费调用模型 |

GET无operation_id返回 `{config,runs}`；config包含revision、owner、enabled、operation_id、固定schedule对象 `{weekday:6,hour:12,minute:0,timezone:'Asia/Shanghai'}`、scope和publication:false。runs仅返回当前owner摘要和安全结果，不返回冻结原始input、Cookie或凭据。GET带原ID也可读取configure不可变回执；配置请求超时须核原ID后再读最新config，历史enabled回执不会重新启用已撤销计划。

内部异步接收返回202/pending，管理端转发以200携带相同业务status；完成结果含operation_id、publication:false、draft原保存回执、模型receipt及evidence_coverage。运行可为pending、completed、disabled、unavailable、failed、unknown或awaiting_apply；awaiting_apply/can_resume表示模型已完成、草稿尚需显式恢复。已知未派发为unavailable/not_dispatched，已知合同/CAS拒绝为failed；通信中断或可能已经保存保留unknown，先查原ID。GET对账不会盲重播，过时查询用CAS防止覆盖并发已完成结果。未找到原回执不能证明原操作从未发生。

configure和手动动作沿原管理员、Origin/CSRF及当前会话；共享宿主再次校验真实actor。自动计划只保存由该会话创建的类型化用户委派，含owner、active及grant_revision，不保存Cookie，不固定账号、不借report/pricing身份。每轮及研究前后、模型/应用前核当前authorizer和授权版本；关闭或修改委派使旧授权失效。周日12:00后按due_day只提交一次；Hermes辅助开关另行核验，schedule.enabled不能绕过辅助关闭。

原宿主恢复循环独立调用周更tick，初始化、账本损坏或执行异常只使周更入口不可用/记录固定诊断，不中断原报告、情报、定价或其他range入口。原模型预算、lease、general provider_slot及UNKNOWN合同继续使用；新任务无发布、优惠券或财务工具。

### 真实来源与单writer草稿桥

Trio外部资料复用现役discovery的search/fetch，最多6名球员，有界检索社媒和垂类来源。仅接纳实际取回且正文姓名匹配的资料，保存真实URL、观察时间、内容SHA及coverage；partial/unavailable明确显示缺口。证据不足仍可据真实产品元数据生成provisional、review_required草稿，允许空引用并说明未经外部核实，不能伪称完成社媒研究。Scout严格保留真实Popular前三顺序；Trio恰好3个不同模型；每个最新SBC core按稳定顺序生成2首选及最多8替代。

宿主通过固定Node CLI调用 `/run/fs-campaign-weekly/operations.sock`，目录0700、socket0600；无新TCP端口或凭据。CLI只作客户端，prepare、apply_draft、inspect_operation在原活动管理进程内调用同一个center实例，保持单writer及原CAS。prepare持久冻结原operation_id/owner/plan_ref、真实源revision和选品池；apply仅接受该计划的推荐及实际证据来源，保存原center草稿；inspect只查原操作回执。CLI或socket失败不转到第二个写入进程，保留原ID核验。草稿完成不是活动发布。

### 可信测试、发布与自然运行回执

`makeWeeklyStore().recordEvidence(record)`只供可信服务器适配器调用，未暴露为浏览器可自证的HTTP入口。record绑定周次/page_id、活动/商品/优惠revision、plan_operation_id、来源/reference、stage与result；部署证明还核当前发布release_id/config_hash，自然运行要求scheduled触发。原unknown后续核验须携带原execution_operation_id。

浏览器登记只生成reported，不能填写verified。测试通过、生产验证、部署读回、自然周期互不替代。历史check_snapshot保留创建时结果，当前checks注明current_center；审批保存历史并对三个版本检查失效。

### 效果追踪

复用现有活动组fc27-season2与原分析/优惠对账入口。当前不构造虚假单页收入或转换率。将来回流需将真实page_id、release/config版本、周次与operation关联；未证明的单页成交归因保持缺口。

## 本批待批准部署

管理端包括weekly.html/js/css、周更账本/推荐provider、weekly-run-client、weekly-pipeline、weekly-native-candidates、weekly-bridge及weekly-cli，修改production-server、原center与商品入口。共享Hermes包括推荐、周更委派和取证模块、原scope/provider分派、现役range路由及controller独立tick。公开消费者也在本批范围：原index、三页HTML、activity-content.js、activity.js、runtime/presentation.mjs，以及共享追踪seasonal/activity-analytics.js和相应分析store接收契约，须与管理端数据合同一起激活；不能仅部署运营台。测试、文档与pr_fast不进入线上业务载荷。具体候选文件哈希与共享源映射以刷新后的RELEASE-CANDIDATE.json及HERMES-CONTRACT.md为准。

2026-11-09只读核对：现有管理与公开运行服务active；production-server/index/products的线上哈希与main基线一致；weekly.html尚不存在。operations.html存在独立线上差异，本批不修改。

发布沿原活动增量发布能力，保留原锁/CAS/备份/回执；管理进程和UNIX桥需激活 `fs-campaign-dashboard.service`，公开消费者/共享tracker及runtime模块亦需在 `fs-campaign-runtime.service` 实际生效。是否需重启/重新加载按本次准确依赖闭包和现役publisher确认，不能以“绝不重启public runtime”遗漏新增消费者，也不直接套用全服务restart。共享宿主另沿其现役发布入口协调激活，保护既有模型在途任务及FC P0链路；账本新状态兼容与回退约束见HERMES-CONTRACT.md。本文件是候选接口清单，不是已批准部署manifest；执行前必须刷新现场CAS并核原publisher输入。

仅部署管理端而未部署共享宿主时，推荐明确不可用。生产部署、计划启用及对外发布待具体批准；用户已授权的真实模型/草稿测试仍须实际回执，不能据源码或离线测试宣称完成。本接口文档更新不执行部署、启用、模型调用、活动发布或券写。回退保留center数据库、周次/推荐记录、原ID及所有运行账本。
