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
