# 本机合成 GoalState 持久化合同

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
