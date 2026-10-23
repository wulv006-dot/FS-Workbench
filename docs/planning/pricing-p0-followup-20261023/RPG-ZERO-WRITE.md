# RPG 零改动缓存回执修复候选

2026-10-23：已于18:52:14沿原publisher/空闲锁/执行锁上线，本地及服务器隔离 Linux 各40项通过；原自然物品轮待验。确切源、基线和生成结果见 [`SOURCE-MAP.json`](../../../rpg_zero_write_recovery_20261023/SOURCE-MAP.json)。

## 原 ID 证据与根因

`J20261023163848` 于 16:38:55—16:39:08 完成，`J20261023173949` 于 17:39:52—17:40:04 完成，均单次。原日志均明确已是目标价、跳过写入，随后重新读取全部目标并复核通过。两份同 ID 执行阶段均 finished=true/write_attempts=0；原结果 confirmed、ok=0、fail=0、mismatch=[]。这两次没有新写价，不需要为本轮变化清缓存。

物品执行器仅有实际成功写入时清缓存，却将原 clearcache_wanted=true 意图和 clearcache_ok=null 写入结果，漏掉 noop/实际必要性。原监控只看意图和未确认值，误报 cache_unconfirmed。金币零改动分支已有独立处理，不能由此清除其他原单的 UNKNOWN/partial 或真实缓存失败。

原 result SHA：163848 为 `1b673e55bd9241cc5a0aeac17465645ad748ce76a99c6d3e7c674d3df21bb6fb`；173949 为 `e320fc4e4c65f4e023eea1cc878e5016790b87d7822915fe590361246dd7c829`。原 DB、outbox、告警和原失败保留。

## 最小修复范围

物品生产者仅增加结果元信息：noop、clearcache_required、clearcache_reason。零改动且全目标复核通过时实际必要性为 false，原因 not_required_no_price_change；原 wanted 意图保持，cache_ok 仍为 null，绝不将其写成缓存成功。原真实写入、清缓存、查询、报价公式和退出状态保持。

共享监控读取原 kind 与同 ID execution phase。仅 done/confirmed、两个结果 ID 与 phase ID 一致、finished=true、phase/result 写次数及 ok/fail 均为严格整数零、mismatch 为原空列表、jobs/目标列表非空且无矛盾 noop/cache_required/cache_ok 时，才承认无需缓存。只移除该 ID 原 cache_failed/cache_unconfirmed；UNKNOWN/partial、缺阶段、错身份、布尔假零及其他未解决问题不豁免。实际数据库只读回归仅移除上述两 ID，其他未解决状态完全不变。

同一 probe 关联修复 FC planned_verified：新增 idle_release 须精确匹配本次 event/container/StartedAt，并核验当前事件后的完成时间；旧 startup 证明须有本次真实读回和时间。旧 planned 标记每轮重算，不能继承 14:30 验收来替 17:15 新事件背书。旧 Python 不直接接受 Docker 纳秒时间，比较时有界截到微秒，身份字符串仍逐字核对。

## 发布及验收边界

现场 p2pah SHA 由 a566 漂移为 12d99 后，又于 18:46:40 变为 3ade。前次 cmd_writegold 变化；后次新增只读 cmd_readgold 及 main 命令分派，物品 cmd_write/读取入口保持。来源尚不能仅凭原 WorkBuddy claim 或 mtime 归属。原 12d99 候选原样保留于 archive；主发布者要求继续保护全部并行改动，最新生成器对 3ade 全文件和原 cmd_write 双重 CAS，并校验所有无关 AST 不变。最新实际生成结果为 1992ef596c26da63973a786200c45733ea66fdc98b45d99256184fd0d1c8958e，40 项本地/Linux 再过。不以旧整文件覆盖。完整原执行器含历史敏感配置，仅在服务器临时生成，不纳入共享归档。

沿原业务空闲/全部写锁、原 srv_exec.lock 和原备份发布器串行发布。不得杀运行工单、补缓存或重放价格；无需重启 Admin/Order/Chrome。probe 仅在原 state 锁窗口更新，通知沿原触发与去重。发布后核原两 ID 只读分类，再等下一原自然物品轮读回新元信息及告警状态，不能将 40 项隔离测试称为自然验收。
