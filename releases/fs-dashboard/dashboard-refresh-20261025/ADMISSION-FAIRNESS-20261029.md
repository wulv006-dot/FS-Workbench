# 查询持续进入时，给原发布器留下可用窗口

本次只做候选、测试和 PR；没有部署，没有停止任何生产任务。PR641 已合并的三个用户分析文件仍未发布，原批准继续有效，但不包含本候选的额外运行时变更。

## 用户会看到什么

原问题不是某一笔查询死锁：原成本任务结束后，新实际毛利查询继续从 nginx 入口进入，发布器反复抢不到共享准入。

候选让发布开始等待后，新任务暂缓；已有任务继续完成。原有可用缓存仍可读，新采集沿原 API 返回 deferred/busy 和重试信息。后台成本、财务公式、原任务 ID、UNKNOWN、缓存期限和数据保留规则不变。

不能直接把所有新取数一起挡住：已开始的 Hermes 原生任务还可能跨进程调用 Range 取数。两步收口避免出现“发布等 Hermes，Hermes 又等取数”的循环：

1. 拒绝新的 Hermes 提交/原生会话，旧会话仍能调用 Range。
2. 旧会话结束后，拒绝新的 Range 采集，再等已经开始的采集结束。
3. 取得原 admission 排他锁后，才进入原来的 source-idle、CAS、备份、停止 Range、替换、回滚和恢复流程。

排空共用一个最多 3600 秒的预算，超时退出并释放本次锁，不强停任务，不把失败当发布成功。这个预算覆盖不了所有可能的超长任务，不能承诺几分钟必能发布。Controller 已持久化的 PREPARING/RUNNING/UNKNOWN 等任务仍由原任务门槛拒绝，不自动取消、重试或改状态。

## 具体改动与边界

| 现役维护源 | 作用/运行位置 |
| --- | --- |
| `cache-archive-retention-20261025/source/cache_retention.py` | 公共准入，宿主 `/opt/fs-hermes-fc/cache_retention.py`；原生通过既有 `/fs-source` 挂载读取同一源 |
| `knowledge-layering-20261023/source/controller.py` | 沿原 `admission_guard` 返回 bool busy；现役 conversation_service 继续复用它 |
| `hermes-server-unify-20261022/fs_native_entry.py` | 保持整轮 admission 资格，经现有原生镜像构建入口更新 `/opt/hermes/fs_native_entry.py` |
| `dashboard-refresh-20261025/deploy/concurrent_release.py` | 修改原发布适配器，不增加第二发布器，原 apply 函数和 CAS/journal/rollback 保留 |

新增两个空的稳定私有锁 inode：共享数据目录下 `publication.lock`、`reader-entry.lock`。宿主目录为 `/var/lib/fs-hermes-fc/fs`，原生使用既有 `/fs` 挂载；不新增容器挂载或账号权限。文件保留，锁资格随 FD 关闭或进程退出由内核释放，不以文件存在表示“正在维护”，不删除或换锁 inode。

`publication.lock`：会话入场时短持 SH，发布持 EX；`reader-entry.lock`：会话全程持 SH，普通采集只在取得 admission 前短持 SH，发布在旧会话结束后持 EX。业务期间仍保留原 admission SH。同线程同 PID/dev/inode 的已入场重入复用资格，普通读取不能借此升级绕过新的会话门禁，fork 子进程不继承内存资格。

外部 inspect 只打开已存在的原全局锁和排队锁，有界等待，不创建文件或控制服务；apply 内部复用已有资格，不重复打开同 inode 抢自己的 EX。缺少新锁的旧现场保持原非阻塞检查行为。等待超时且本发布未暂停/停止单元时，不恢复外部人员改变的单元状态。

## 测试与部署审核点

真实 Linux 临时目录已验证旧会话跨进程取数、新任务拒绝、普通采集排空、同线程重入/升级、fork 资格隔离、总预算、非 busy 错误不重试、body 失败不重放、进程退出放行、双发布者互斥、缺锁检查不创建、正常 CentOS 锁目录别名和恶意链接拒绝。测试没有生产导入、数据写入、模型调用或服务操作；正式 CI 另以对应 head 回执为准。

首次升级有实际限制：已经加载的旧进程不识别新协议。不能仅放入新文件或复制新发布器，就声称当前旧进程已解决插队；也不能绕过“先获 admission 才能停 Range”。首次需安排并核实旧任务已收尾的受控窗口。不能在旧原生进程仍运行时，只升级宿主读取端就开启新排空协议。

额外生产动作需单独批准：核实当前宿主/原生镜像和维护源，按既有 publisher 维护精确两个宿主源；沿既有原生镜像流程从当前运行基底构建并核源，更新原生入口和原 pinned image 引用，按原单元生命周期加载两端协议；核两把新共享锁的同 inode/0600、原 admission inode、缓存和任务账本保护。宿主 Range 和原生单元的受控加载、原生镜像/单元目标不在 PR641 三文件旧批准内。当前不执行这些动作。

回退使用各原 publisher 的原 journal、源码备份、前一 pinned image 和单元前态；先确认没有本次排空/写入在途，再协调回到一致旧协议。保留数据、任务/UNKNOWN、两把空锁和原 admission inode，不靠删除锁“解锁”。
