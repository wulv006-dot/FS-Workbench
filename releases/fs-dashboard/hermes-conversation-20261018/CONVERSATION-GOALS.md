# 本机合成 GoalState 持久化合同

前两包的持久化/outbox 合同与证据保留如下；2026-11-01 材料执行装配候选见本文末节。当前生产仍501f，本轮尚未部署或运行真实模型。

本模块为 B 的 `b2_goal_state_v1` 最小状态提供真实 SQLite load/CAS 和 admission；没有 HTTP、会话服务、生产 scope、模型、定时器或运行入口接线。生产仍为既有 501f 材料版，不能据本模块测试称目标系统已上线。

## 路径与归属

- A：`source/conversation_goals.py`、`tests/test_conversation_goals.py`、本说明，以及原 `tests/test_conversation_store.py` 的 `load_tests` 两行加载。
- B：GoalState 业务转移、host 派发/查询/回执验证与对应测试。A 不改这些消费者。
- 原 `ConversationStore`、公共表/迁移文件、HTTP/controller/runtime/publisher/IAM、CI 驱动均未修改。本包由 Personal 统一集成 PR，A 不另开 PR。

## 存储与授权

`ConversationGoals(store, owner, cid, authorize)` 使用原 `ConversationStore.db()` 和同一个 `conversations.db`。构造时先核原 `_owned`，仅创建本模块独占的 `conversation_goals_v1` 与 `conversation_goal_mutations_v1` 私有表；不修改原会话/turn/event/artifact/action 表。

每次 load/CAS/admission 均在 `BEGIN IMMEDIATE` 下先核 `_owned(owner,cid)`。已有 goal 随后以持久化的原 `scope_ref` 调用 `authorize(owner,scope_ref) is True`，再解析/返回缓存。创建用新 state 的 scope 校验；后续 owner/cid/goal/scope 不可改绑。无 callable 或当前授权不是字面 `True` 则拒绝。尚不存在的 goal 返回 `None`，没有 scope 或资料可供访问；该返回不授予创建/查询权限。这里的合成 validator 不是生产 grant，真实细粒度来源仍未证明、不可用。

goal_id、mutation_id 在本模块各自全 DB 命名空间唯一，跨 owner/cid/goal 不能挪用。owner/goal_id/mutation_id 为 1–256 字符非空文本且无 ASCII 控制字符，不要求 UUID。任务 request_id 和 CAS mutation_id 是不同标识，host 应提供稳定、唯一的 mutation ID。

state 使用规范 UTF-8 JSON（排序键、紧凑分隔符、无 NaN），最多 32768 bytes。接受版本 `b2_goal_state_v1` 的原完整顶层字段，以及原 work 和 B1 六字段 evidence 引用，不允许添加 rows/orders/events 等正文结构。目标摘要/约束/引用值仍须 host/B 保证最小化；本模块不是任意字符串的隐私清洗器。B 负责时点、业务转移、回执语义校验，A 不重新实现 B 算法。

原 JSON、SHA256 及绑定字段一起核对；损坏的 JSON/结构/版本/绑定/校验和拒绝读取和覆盖，不自动修复或初始化空目标。摘要用于发现损坏，不替代 DB 权限或构成抗恶意管理员篡改证明。

## API

```python
goals = ConversationGoals(store, owner, cid, authorize)
current = goals.load_goal(goal_id)  # state 的独立 JSON 副本，或 None
receipt = goals.cas_goal(
    goal_id, expected_revision=0, mutation_id='create-goal-unique-id', state=initial_state)
```

创建要求 `expected_revision=0`、`state.revision=1`；更新要求当前 revision 等于 expected，且新 state.revision=expected+1。revision 是独立目标版本，既不是 TaskStore.version、源数据 revision，也不是 turn 状态。有效 revision 上限是 SQLite 有符号 64 位整数上限。

成功回执的形状：

```json
{"applied":true,"replayed":false,"goal_id":"goal-1","revision":1,
 "state":{"说明":"此处实际返回完整原 state，不是此占位对象"},
 "mutation_id":"create-goal-unique-id"}
```

mutation 完整指纹包括 owner/cid/goal/expected_revision/mutation_id/完整 state。相同 mutation ID 与相同指纹返回原操作回执，只有 `replayed=true`；同 ID 异内容拒绝。键插入顺序不构成不同内容。原目标已推进到 rev3 时，rev1 操作重放仍返回 rev1 回执，不更新当前值；需要最新值须重新 `load_goal`。

`applied=true` 表示该操作曾持久化，**不是再次派发许可**。host 只有 fresh 成功（`replayed=false`）才可进入其派发流程；不能凭重放回执重复执行。修改目标与插入 mutation 在一个事务中提交，任一步 SQL/提交前异常均回滚两者。提交结果丢失用原 mutation ID、原 expected_revision、原完整 state 查回，不改 ID 重试新操作。

典型拒绝：`goal_revision_conflict`、`goal_mutation_conflict`、`goal_scope_conflict`、`goal_state_damaged`、`goal_mutation_damaged`；不存在/跨绑定目标为 `LookupError`，撤权为 `PermissionError`。SQLite/文件/提交异常保留原异常，host 不得据此推断操作一定未提交。

## 入队围栏

```python
# 仅 fresh CAS winner，且 B 已验证原任务账本 not_found 后：
with goals.admission(goal_id, expected_revision=prepared_revision,
                     request_id=original_request_id) as prepared:
    receipt = dispatcher.submit(binding=binding, handoff=handoff)
# 退出后才 load/CAS 回执，不在 admission 内嵌套目标写入。
```

admission 在原 DB 锁下重新核 owner、原 scope、精确 revision、active、work.prepared 和原 request_id，yield 独立副本，直到退出持有锁。它不写 goal/任务，也不证明调用方是 fresh winner；B 仍负责 fresh 判定、原 ID lookup、intent 指纹、verified receipt 和原账本幂等。

dispatcher.submit 在此期间只能在其**独立原任务账本**原子 reserve/入队，不得等待 provider、调用模型或用另一连接写同一个 conversation DB。pause/stop/其他 CAS 与此预留串行：pause 抢先则 admission 拒绝；预留抢先则 pause 等到退出，已有任务不因此取消。异常释放原锁、goal 不留半写；外部任务预留不属于本 DB 事务，若预留后异常，必须查原 request_id 对账，不能声称外部任务已回滚或重试派发。

admission 不是跨 DB 分布式事务，也不锁外部 IAM 政策；保证的是本事务中逐调用授权和目标变更/预留的序列化。真实身份/当前 scope 来源及任务账本验证的接入仍是后续宿主责任。

## 本地检查与证据层级

原 runner 命令：

```text
python -B -c "from tools.pr_fast import units; units('releases/fs-dashboard/hermes-conversation-20261018/tests',['test_conversation_store','test_conversation_service','test_worker_admission','test_lazy_evidence'])"
```

当前本机 Python 3.14：53 项、0 failure/error/skip，其中新 goal 21 项由原 store.load_tests 实际加载；无需改 tools/pr_fast.py。早期不含 admission 的 16 项直接入口曾通过。加入 admission 后首次完整入口因新夹具 `sqlite3.connect` 的事务上下文不关闭连接，清理时报 WinError32；已用标准库 closing 显式关闭夹具连接，修后上述 53 项通过，未改生产存储或放宽 runner 外网/外部进程围栏。

新测试用真实 temp SQLite/原 ConversationStore，覆盖并发 CAS 与同 ID 竞争、重连、两版本/旧回执、跨 owner/cid/goal/mutation、严格 True/撤权不返缓存、旧版/超限/损坏拒写、mutation 插入故障和提交前故障原子回滚，以及 pause 抢先、预留期间 pause 阻塞、失败释放锁、非 prepared/错误 ID 拒绝。独立临时任务 SQLite 仅作本地 admission 预留夹具，不冒真实任务/worker。

待验：B 固定候选的实际 host/dispatcher 组合、Linux/CI、独立最新 SHA 源码审查。无真实 A2 scope、客户/API、模型、认证文件、生产 DB、调度或部署取证；未取消真实任务、未改变生产 501f。

## 独立原任务 DB 的持久 outbox

后续 A 模块为 `source/conversation_goal_tasks.py`，测试为 `tests/test_conversation_goal_tasks.py`，由原 store.load_tests 再加两行加载。原 `pilot.TaskStore`、任务/spec 表、FC lane、已有 GoalState 存储及共享接线未改。本包只登记待执行 intent，不生成缺乏真实来源的 FC27 spec、任务、lease 或 run。

```python
outbox = ConversationGoalTasks(tasks, owner, cid, authorize,
                               expected_path=host_verified_tasks_path)
missing = outbox.lookup(binding=binding)
outbox.verify_receipt(missing, binding)  # 当前权威账本重查；不是信任 verified 标志
# 只有 B 核定 fresh CAS winner、verified not_found 且进入原 admission 后：
queued = outbox.submit(binding=binding, handoff=original_b1_handoff)
```

构造参数 `tasks` 是已经合法注入的原独立 TaskStore；不构造 HermesService/controller、不调用其 db/get/create/reserve_dispatch。`expected_path` 必填且为 host 配置的绝对路径，与 tasks.path 的现有规范路径匹配。用 `mode=rw` 连接避免缺失路径竞态下新建空库；连接前后及提交前核文件设备/inode 身份，核原 tasks 列、主键及完整 owner/fingerprint、run_id 唯一索引。数据库不存在、路径变化、原 schema 不合、SQLite I/O/格式错误均抛 OSError，不能成为 not_found。

模块在这个既有 DB 内独占 `conversation_goal_outbox_v1`、`conversation_goal_outbox_identity_v1`。首次初始化私有两表及随机 ledger_id 在同一事务；只缺一表视为损坏，不自动重建。现有实例逐次核两表结构、ledger_id 和文件身份；不修改原 tasks 表或其记录。ledger_id 是非敏感命名空间，不是权限。路径/schema/文件身份是当前已配置账本的检查，不是对任意备份未回退、恶意删库或篡改的证明；host 必须保护并保留原 DB，不能换空库消除 UNKNOWN。

binding 精确为 owner/cid/goal_id/scope_ref/request_id/intent_sha256 六字段；owner/cid 固定在服务端，须由合法会话宿主确认，不是模型参数。每次先核调用绑定和当前 `authorize(owner,scope_ref) is True`，DB 事务结束后再核一次才返回；authorize 不在任务 DB 锁内调用，避免反向 goal 锁序。验证器必须是宿主的权限检查，不是执行/回源入口。没有真实 grant 的既有结论保持 unavailable。

handoff 精确为原 B1 的 task_id/revision/goal/constraints/evidence/completed_actions/next_step，task_id 必须等于原 request_id；原 evidence 六字段引用保留，正常 UTF-8 JSON（含 B1 默认空格）不超过 32768 bytes。不能新增 orders/rows/模型正文等结构；引用/摘要字符串仍须 B/host 最小化。本模块只校验字段、类型及大小，不把存储的 scope_ref 或 evidence 引用变成读取授权。

原子指纹覆盖**完整 binding＋原始 handoff**，不只覆盖 stable logical intent digest。按 `(owner,request_id)` 唯一；同 owner 跨 cid/goal/scope/digest 拒绝，同 ID 改 handoff 的 evidence/revision/next_step 等也拒绝。重复同完整内容返回同一个 queued 回执，不新增行；其它 owner 的同名 ID 独立隔离，不回传其数据。没有 running/completed 的 record 接口。

回执始终精确为三字段：

```text
{binding: 原六字段副本, status: "queued" | "not_found", receipt_ref: 稳定 ledger/intent 绑定引用}
```

queued 只表示该 outbox reservation 已提交，绝不表示原 TaskStore task、worker 或模型接受。私有记录的 task_id/lease/run_id 始终 NULL；不把这些字段添加到 B 的三字段回执，不伪造成功。回执引用绑定 ledger_id、binding 和完整 payload 指纹、版本 v1；不返回原 handoff 正文。verify_receipt 重新查同原账本并精确比对全部回执，不能把其它库、旧 not_found、假 running/completed、额外正文或修改 ref 当已验证。not_found 仅指当前授权下此 outbox 没有该 owner/request_id 行，不证明运行时从未收到请求；旧 prepared/UNKNOWN 即使 verified not_found 也不能补发。

BEGIN IMMEDIATE 下保留原事务提交/异常回滚/关闭语义。锁序是 goal admission→独立任务 DB 短事务→退出任务事务→退出 admission；任务事务无反向会话 DB、网络、grant、provider 等待或模型调用。submit 提交后回执丢失、admission 退出失败或权限随后变化时，原 reservation 可能已存在；恢复只查原 ID，不能据异常换 ID/重派。goal DB 的回滚不回滚独立 outbox。

本机原 runner：新增首轮 21 项直接入口通过；补 ledger 身份/路径漂移后，新模块 22 项由原 store.load_tests 实际加载，原四模块会话入口合计 75 项通过、零 failure/error/skip。使用真实临时 TaskStore/ConversationStore/Goals，覆盖并发单 reservation、完整指纹冲突、重连/丢回执、错/缺库及 stat→open 删除竞态不建库、schema/命名空间/数据损坏、跨 owner/cid/goal/scope、strict True/撤权、原 tasks 零新增/零改动、pause 与 admission 串行、原 goal 事务失败不抹已提交 outbox。未运行 B 旧套件；B 冻结事实候选组合、Linux/CI 和最新 SHA 独审另验。真实 generic spec/任务执行/worker/host grant 未接，生产仍501f，无生产或模型动作。

## 2026-11-01 材料短任务执行装配候选（尚未部署）

本轮 A 新增 `source/conversation_material_runs.py` / `tests/test_conversation_material_runs.py`，消费 B 固定 `42b6df09cfc0ccbe0743231c79b96cec5edf8bb1`。原 controller、TaskStore.create/FC validate_spec、公共迁移和 B 源均不修改；不是另一套执行器。原私有 outbox 的 queued/NULL task_id/lease/run_id 合同保持，实际任务另由本模块私有映射关联。

- `MaterialService(HERMES, CONVERSATION)` 只接现有实例。正常入口身份、原会话 owner/cid、用户显式文件选择形成材料 capability，不产生经营/A2 scope。
- `POST /api/hermes/conversations/{cid}/materials` 精确必选 `client_request_id,goal,file_ids,operation`；可选 `read_scope={file_id,sheet,offset,limit}`。文件必须来自原选择；sheet/offset 为非负严格 int，limit 为 1..200 严格 int，bool 拒绝。只用真实解析结果核 sheet/EOF，offset 超过末尾拒绝。
- 每个新显式选择在同一原任务 DB 短事务中分配该 owner/cid 下递增 selection_revision，原 ID 的完整请求 SHA、metadata、时间和版本先持久，再 prepare/freeze/CAS/outbox。范围规范 JSON 在首次 CAS 前进入服务端新材料目标/原 handoff 的 constraints，参与 logical intent 和完整 payload 指纹；不是后续临时拼入。原 ID 换范围/文件/操作拒绝；重试只读原选择。
- `GET .../materials/{request_id}` 返回真实 task/run 状态、B 合并覆盖、实际派生文件 metadata/proof、`cost_microcny:null`、`goal_achieved:false`。`POST .../{request_id}/stop` 先 B stop CAS，撤销现有 grant 并停止原 run；不宣称提供方计算或计费停止。
- `GET .../{request_id}/result` 是单独的 owner/cid 鉴权答案通道，仅访问映射中已知 run 的原官方 GET 状态端点，再核 run/session 与授权，最多返回 64 KiB UTF-8 文本。此端点可能触发官方状态 hydration，不称纯只读账本对账。原 UNKNOWN resolver 不返回正文；答案不进 GoalState、receipt 或 ref，UI 沿 textContent 安全文本渲染，不把模型 URL 变成下载卡。

实际 TaskStore 五字段来源：period=null（该任务类型不伪造 FC 周期）；snapshot_id 为真实文件 metadata 的冻结快照；template_version 为 B 实际冻结模板；knowledge_version 为冻结 system/input 的组合版本；budget_policy_id 从原 direct_provider.POLICY_ID 取，并与实际 general gateway policy 再核。项目/类型指纹为 FS/conversation_materials_v1，未调用 FC create 或未知 execute。

原 outbox reservation 与材料 mapping/真实 task 写入均发生在短 tasksDB 事务；锁序保持 conversation goal admission→tasksDB→退出两锁。mint/POST/provider 不在 admission 中执行。实际派发另在同 conversationDB 锁下核当前 active/原 request/精确 revision、真实字节和元数据后，原子 CAS attempted=1 与真实 task DISPATCH_UNKNOWN/lease。随后只有一次 POST。session、key、官方 body 指纹和完整原 execution 持久绑定，丢 202 或任何不确定边界不重 POST。

官方 pin `71d34bad1045610252eda02ee79549436896e784` 的三文件磁盘 hash 已按获准有限元信息核实；完整值见部署附录。worker 每次材料 POST/能力检查再次核 pin 与官方 store.durable，未证即 unavailable。materials resolver 在原 adapter 正常认证/profile scope 下，对同官方库 `mode=ro + query_only` 仅 SELECT，核 key/full fingerprint/session；不调用会 prune 的 lookup/reserve，不重 POST。missing/过期=unknown，stale owner=interrupted，只读投影不改官方库。

worker/模型代理/vendor preflight 三层都仅启用原三个文件工具；材料分支最先拒绝非文件工具/strategy 绕行，禁止 steer 改冻结意图。复用原 general provider/预算/到额停止，材料 transport_retries=0；原 FC lane 和旧工具集合保持。actual context proof 来自实际 agent system、已接收原 POST input、agent.tools、memory/context/background 禁用状态，不能由 expected 文本自证。

ExecutionBoundFiles 没有伪造 human turn。每次工具核正常权限、goal/task/lease/run/当前状态、deadline、文件选择/生成 membership、sha/size/parent/version/expiry；修订只允许冻结 cells/格式/确定性 revision_request_id。产物由真实 ConversationFiles 读回，成功前再核内容。默认 read 必须所有选中 workbook 完整；显式范围仅要求真实末尾裁剪后的请求区间无 missing_ranges，空表/EOF 也需真实零行读回。复用 B MaterialEvidence 合并覆盖，持久化每文件最新合并摘要/最小 refs 而非正文或无限页日志；未读 sheet/文件保留缺项。短任务完成不是业务全量、实时数据或长期目标完成。

启动恢复只有限扫描本模块映射并核 task 完整指纹；未尝试 queued 取消，已尝试仅查原 ID/停止原 run，不重建活 book/重发。撤权围栏只取消已验原任务，不返回私有缓存，不创建 grant。损坏映射不拿未知 task ID 去取消 FC 任务。UNKNOWN/原账本/DB 不清除。

检查入口：原 store.load_tests 新增本模块，现有 Node entry/test_data_handoff.cjs 实际加载 DOM/fetch 场景；原 channel 与 deploy/test_runtime_materials 入口复用，无 CI driver/workflow 改动。新增材料模块 20 项本地原 runner 通过：真实 temp TaskStore/Goals/files、localhost 接收后丢202、单 POST、分页/范围/多文件/EOF、原 ID 冲突、真实 agent 构造方法的 SDK 夹具 proof、三层工具边界/零 retry、鉴权答案/停止/重启。协议服务器、agent 与 provider 仍是明确的本地夹具；没有真实 SDK 进程或模型运行通过声明。原 publisher 12 项、原 HTTP/release 10 项、channel12、Node 和本地 Chromium 亦通过；最终集成 Linux/新 SHA 独审由 Personal 进行。

未验：生产安装/真实 SDK 启动及持久恢复、真实 DeepSeek/账单、生产 running stop/第二身份/真实 A2 scope、实际浏览器 200% 缩放和生产视觉。当前生产保持501f；本次没有新模型、业务 API、SSH 或部署操作（先前获准三 SDK 文件元信息证据单列保留）。

### PR723 集成前 P2 收口（2026-11-01）

MaterialService 只在 runtime cache 的 check/create 短边界持有独立 RLock；原会话/Goal/任务 DB 构造和鉴权均在该锁外，网络及执行也不在锁内。同 owner/cid 的并发首次请求取得同一实例，live book 不会因另一个首次请求覆盖缓存而误被当作重启围栏。新增两项真实 temp Store/TaskStore 并发回归通过；只在 constructor 插入 Barrier 同步点，不替换 DB/Goals。旧51af `_parts` 仅内存回退时两项均实际构造2个 runtime并失败，修复版只构造1个，带live状态继续reconcile且不POST stop。原20项及主控Core198证据复用，未重跑旧输入整组。

UI 修订只允许显式单选，显示“修改目标：<真实文件名>”；多选时按钮禁用且事件处理器再次拒绝，无隐藏 file_id 排序目标。读任务的多选及后端显式 operation.file_id 合同保持。新增真实DOM/fetch事件覆盖列表/勾选顺序与ID反序、两种勾选顺序、多选零提交、取消另一份后只提交明确保留的目标。原Node入口通过；Chromium入口增加真实目标文字断言并通过。长目标名称沿当前布局换行，不增后台业务门禁。
