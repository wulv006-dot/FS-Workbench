# 归档缺项的消费合同与候选（P2）

2026-10-29，候选未提交/未部署；root统一审阅、提交和正式CI。共用分支`codex/archive-concurrency-recovery-20261028`，禁止切分支覆盖并行工作。

## 已证问题与最小修复

活动`/opt/fs-hermes-fc/nightly.py`对应`nightly-reschedule-20261025/source/nightly.py`，生产SHA `f40a21733d8c34d691783c2edb29b46e45dc9ad95f428da494e6255d6a70ce01`。原readiness已经按02:00 fallback允许缺项出报，但之后仍因`source_preparation.thread.is_alive()`直接return。准备线程未结束会继续阻挡所有夜间报告，原fallback失效。

候选仅把此额外return改为`nightly_preparation_still_running`缺口提示并继续原submit路径。原报告时间、请求ID、数据库串行、UNKNOWN对账、截止、权限和模型预算不变；没有新增报告或补采。

活动`nightly_data.py`生产SHA `2022b046aabc635bb24e651f7ad72bafabe862e47c53efe10fa9cc8daa419e01`；活动`source_snapshots.py`生产SHA `8ed6cf276c619b3b56821fee1d65fc83cc2d183fb6eb6e1774563aab0b80fd92`，均已逐字核对维护Git blob。后者当前维护于`cache-archive-retention-20261025/source/`，不从旧nightly包覆盖。

## 沿原分项账本只读透传

复用P1原`/var/lib/fs-data-archive/scheduler-state.json`，不等待整轮job-status写完。`archive_status(query)`按profile、相交业务日期及显式站点/区服/类目过滤，只暴露逐项query/family/cadence/status/reason/retryable/failures/retryAfter/lastObservedAt。摘要含观察数、缺项数、明确failed且retryable=false的终止数，最多内联16条并保留原stateFile入口。

- 观察缺失/文件不可读时missingCount保持未知，不填0；`coverage_complete`始终未知，不能把“目前没记录缺口”当成完整区间证明。
- `blocks_publication=false`，该辅助状态不覆盖已读取数据的available/complete、收入或人数口径。
- 非完整native-statistics回复带独立`archive_status`；原状态与缺项数值原样保留，不伪造零，不把部分回复重新保存为完整归档。
- 完整同合同归档照常直接返回，真实零值仍可用；不因辅助归档/备份分项失败丢弃已有完整数据。
- 报告问题上下文及prepared_brief都保留缺项/原因/重试或终止证据；不发新冷采、不靠新补采成功作为原报告准入条件。
- 原45秒准备轮询预算与单次读取超时保持。SnapshotStore全局锁包网络的第二问题由P3独立处理，本候选未改get_live锁段，不能据本次门禁修复宣称所有网络等待已解决。

本次未发现足以另改经营公式的“missing直接填0”实际路径，因此不改变任何财务/客户分母。用户数据同步与其备份是独立组件：backup_requires_reconciliation不能推出已complete的用户数据不可用。

运行中的待观察pending不能仅因旧retryable=false就算terminal；P2终止计数需status=failed且retryable=false。P1已收到进入pending时重置旧reason/retry字段的关联建议，状态源码由P1负责。

## 当前实际夜间元数据（只读，未创建任务）

- `/var/lib/fs-hermes-fc/fs/nightly-schedule.json` enabled=true，原daily01:40、management02:10；02:00是缺项fallback，不是另一个报告job。周一weekly02:40、management_weekly03:25，月初monthly04:10。
- 07:49不接收新夜间报告、07:50保存终态是报告原截止，和本轮取消的归档07:00硬停分开，不擅改报告周期。
- 今日预期原request `night_daily_20261029` → `7f2fe70c20d6126c77f1972bca878af7`；management → `318e14ce1906d530b47d97d1058946d9`。按原哈希推得，检查时尚未创建；10/28同规则已对照真实历史ID验证。
- native cron记忆审阅06:00原ID `6e6c882ed49d`；下次2026-10-28T22:00Z=29日06:00BJT。周六04:45维护原ID `6534331b5100` 保持。
- FC02:20实际入口为`/opt/fc27-cloud-browser/fc_pricing_v3/daily.py:15 due_date`、`scheduler.py:315 tick`。本次闭账日2026-10-28的原确定性daily request为`833911c9-2345-5562-9e76-3bad69d92be1`；本检查不创建任务、不调用模型或采集。root cron未列该项不代表入口缺失。shadow service最近10/28 02:20:24CST failed属于历史，不能当作今晚新增故障。

## 验证与边界

22项nightly-reschedule、27项cache-archive-retention本地通过，含准备线程活跃仍按原ID提交报告、pending/terminal范围隔离、未知不填0、完整零值归档不降级、部分回复不写完整档案。正式CI由root统一提交后运行，当前未冒称已通过。

原数据指令只同步一年保留/三月新增逐笔与自动补采约束，以及全天轻tick/分项缺失消费，不截短既有原生汇总或UI日期能力。源码/实际部署/模型自然消费分别验收。

实际元数据证据位于root runtime目录：`p2-nightly-metadata-evidence.jsonl`、`p2-internal-0220-source-evidence.jsonl`。教材9actual loader已独立完成17SHA/67保护与原13默认条目；dashboard条目只证明可显式加载，未擅加默认路由。
