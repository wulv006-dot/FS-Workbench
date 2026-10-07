# FC v4.1：本地实现已冻结，可审；DO NOT DEPLOY

源码 manifest SHA256：`206efa4613ae3b12f5fdfd7df04cfee85f1a50b861ebdd985c0233ce14872398`。运行 artifact 闭包为 source 内 23 文件＋manifest，共 24 文件。Git/QA 候选输入另有精确白名单，不含 private-runtime-not-for-git。

新 diff 定向测试 57 项：48 pass、0 fail/error、9 Linux 原生 skip。Windows Python 3.14 的模型/线程结果不是 POSIX、真实服务 uid/gid 或目标 Python 3.9.18 验收；已补目标 3.9 语法解析。原 guard/reconcile 与原 v3 全 14 文件和 manifest 原字节保持；旧 76 未重跑。releaseReady=false。

## 实际写者与临界区

| 写者 | 入口与临界区 |
|---|---|
| API | collect、preview、recalculate、execute、restore_preview、restore 六入口统一 Handler.enqueue。execute/restore 的 queue＋jobs 去重和创建同锁，保留 already_submitted/202 合同；busy 返回 503、retryable、本次 accepted=false。 |
| Worker claim | 同锁内选取、读取/校验、invalid 归档、持久登记 running、fsync jobs、unlink queue、fsync queue。若 running 已存在却 queue 仍在，保留两者并报 needs_reconcile，不重放。 |
| Worker follow-up | 启动补发、正常完成补发和 busy 后轮询恢复均在同锁内重读 durable parent/current policy、确定性 UUID 去重、创建 queue、保存 parent。保留 durable intent；不在锁外用旧 parent 覆盖新字段。内部 _locked 函数只从已持锁路径调用，无 locked=True 绕过接口。 |
| Worker startup | running→interrupted 扫描也在同锁内；只处理原有 running，不改本案 failed 原记录。 |
| Timer | due/retry_due 检查与发布仍保留原 policy/retry guards，并采用相同 mutex。冲突返回 retry_blocked，不改策略/nextRun。 |
| Reconcile | 原有 tick inode 与 price-writer 锁覆盖两轮证明、CAS、最终 job publication、unknown 结果判定。任何 queue 非 JSON/invalid 遗留都中止，不能用忽略这些记录制造“空队列”。 |

**选择的是复用现有最外层 automation-tick inode，没有创建第二个 queue 锁或新权限。** API 以只读 FD 对 root 既有 0644 inode flock；每次/每线程独立 FD，拒绝替换、symlink/hardlink，缺失 fail-closed。统一约束是 common inode 最先取得；worker 释放它后才 handle/启动业务子进程。既有 timer 为 tick→coin policy→retry business locks，reconcile 为 tick→price→短暂 coin/player policy locks；所有嵌套 flock 都 NB，失败退出，无持 price/config 再阻塞等待 tick 的路径。没有把独立复核建议的“新增最内层 queue 锁”冒充已经采用或验收的设计。

读取和 OFF 保存不拿队列锁。两个现有 policy 锁只在 metadata publish 内短持，checkpoint/CAS/rename 同处其间；竞争则恢复中止，OFF 保存继续，绝不改回 ON。此处要求现场提供两 policy 锁的真实 inode/owner/mode 绑定，DRAFT 为空，不能 apply。

## 导入与运行绑定

批准的控制端以内存中精确审核过的 launch.py 字节 `python -I -S -B -c` 启动。直接从 mutable file 启动被拒绝。外部 source-manifest/binding SHA 是授权边界；不靠候选自报“我验证自己”。全部 artifact 条目与哈希、绑定结构/原身份/CAS/锁元数据、宿主解释器均在首个候选执行前验证。

宿主 12 APP 源码一并无执行读取并校验稳定 FD/hash，核对与候选 app artifact 相同，再由 sealed-memory loader 执行。probe 先验证解释器和 13 模块闭包，再 import；固定镜像的不可变 stdlib/site packages 是第三方依赖边界。不加入 live APP sys.path。__file__/spec.origin 是 verified-memory；provenance 明示原验证 path/SHA 与 sealed loader，未伪造真实文件加载。

原 scope 原字节保存在 private-runtime-not-for-git，v4 binding 为显式 DRAFT_NOT_APPROVED，保留原 ID/CAS/lock 绑定；新 3 source hash 是拟部署值，原 source inode 还需现场更新。新 artifact 路径及 policy-lock/进程证据同样未批准，不能把 DRAFT 当现场状态。

上线前必须核真实 API health v4 marker＋PID/start、worker 新鲜 heartbeat marker＋PID/start、timer read-only --queue-protocol 与实际 unit/source。runner 保持 PID 连续性和实际 worker heartbeat 检查。磁盘 SHA、Git main 或这个候选中的 API.monitor_view 都不能证明驻留进程已采用协议。

## 限制与下一步

独立 review、此精确新输入的 Linux 原生 QA、真实服务 uid/gid/进程采用证明、完整新 runtime binding、受控 source 部署/重启窗口、独立 metadata/readback 与自然终态均未完成。原 v3 已被用户合入仍然 unsafe；未 revert、未动其冻结 bytes、未 resolve 旧四项 P1。v4 源码/绑定分离不意味着已经清除当前 Git HEAD/历史中旧 v3 runtime scope；该治理处理须根在线程协调的新修复 PR 中明确决定，不能声称已关闭。

最新父线程报告的 main 为 412ae06854524b126c6b2d5a28d6921f01b2f821，仅作协作背景；不是本候选已基于它提交，未来 Git 前仍需 fresh base。Git＋生产窗口现属利润任务，本任务未写 Git/生产、未触发任何 workflow。仅本轮已授权只读巡检有 SSH 读取。

## v4.1 唯一修订：FC-V4-ADOPT-01

保留 v4 冻结33输入；本版只改 launch/runner 接收侧、binding合同说明和定向测试。所有 APP、safe loader、queue/storage/guard 字节与冻结 v4 相同。独立 v4 review 已静态闭合原四P1及锁临界区；本版请求只复审唯一实际采用回执P1，不宣告该P1已验收。

真实驻留 API GET /health 回执必须有采集来源/时间、HTTP200、marker、PID/start，拒绝候选函数来源及 reconcile 自身PID。timer 必须有有效 unit/ExecStart、fragment/drop-in身份、同 source/interpreter SHA，以及按该命令实际 read-only --queue-protocol 得到的回执。各回执300秒有效，launch 首次候选exec前与 runner 每次context均校验。批准控制端独立采集并批准精确私有 binding SHA，源码不采集/制造回执；实际取不到就fail closed。现无任何真实receipt，不进入Git。原 worker15秒真实heartbeat及PID连续性不变。

新增17项只针对采用接收边界：缺失、旧服务配新磁盘、旧unit配新脚本、marker/身份/出处/命令不符、陈旧回执及重复context失效。Windows57项为48pass、9native skip；不是native QA。没有生产/Git窗口，没有部署、重启、现场恢复、工作流触发或旧76重跑。
