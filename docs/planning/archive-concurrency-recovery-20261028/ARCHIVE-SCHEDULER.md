# 全天归档有界接续候选

用户新授权覆盖原07:00硬停：归档继续运行，失败及时接续；明确错误停止该项并公开缺失；保留正常自动化、内存和负载边界。此稿与源码只为候选，未提交、未部署、未改变生产timer或状态。

## 已证根因

现场`archive_jobs.py`在入口、循环、scheduled分支有07硬停，timer只覆盖01–06。HTTP错误会丢失原错误类型，422可直接中断整轮；busy/denied按端口跳过其他profile，native catalog单次失败会直接返回。单项轮询90秒又可吃掉daily120秒预算，使排在前面的营销任务阻塞业务归档。响应体中断产生的IncompleteRead（及断开/无效状态行）原先还会逃出read_route，整轮提前退出、分项停留pending。

现有`scheduler-state.json`1840项中，1763 complete、34 pending、27 unavailable、16 busy。该旧状态没有精确reason；不能从旧generic unavailable猜测权限或响应内容。

## 最小变更

仅两份生产目标：

| 维护源 | 目标 | 现场before SHA256 | 候选LF SHA256 |
|---|---|---|---|
| nightly-pipeline-20261023/source/archive_jobs.py | /opt/fs-exact-range-20261001/archive_jobs.py | de24cb028101cfcd6a615dbb9f5fb7500c508a612ab75c380035fb516b9bbf22 | 4314cc81d39d1a14a7be31c26f5f8bb4c043a6b13dfd56488d12e54ace266416 |
| nightly-pipeline-20261023/deploy/fs-data-archive.timer | /etc/systemd/system/fs-data-archive.timer | b8cd36d4e513954d129e9d8ca1849d4937d6f5dca794d5804eaf909087cb7d75 | 99d9f2eee279cdccb2a19020d1b965ba35225bff2189e70e12d77b6bed4fa46d |

两目标均existing、owner0:0、mode0644；正式发布前仍需原publisher取新CAS，以上不替代现场重新prepare。

取消code的小时限制，timer全天每5分钟轻量tick，保留00:30触发。原00时daily480秒优先，其他小时daily120+history360秒不扩大；原oneshot/nonblocking scheduler.lock、Nice10、IO idle、TimeoutStart10min保持，不增加采集池。单路由观察最多10秒，剩余总预算更少时继续缩短，不拉长任何原超时。

read_route只将IncompleteRead、BadStatusLine（含RemoteDisconnected）等线路中断归为503，沿原分项backoff接续；不捕获一般HTTPException、磁盘OSError或编程ValueError。每个query每轮仅一次来源观察；原后台job继续执行，下一tick按同query接续。先轮到从未观察、最久未观察的due缺项，已complete的旧缓存复核放后；整轮预算耗尽不再从第一个营销项重头等待。一个失败不封同端口其他profile，也不因catalog错误提前结束其他family。

只在完整原归档验证通过时同步state complete。保留原cadence+query SHA键、requestedAt及pending attemptStartedAt；不换请求、另建数据库或队列。营销每日纠正仅首次发refresh，超时未知后的观察不再refresh；明确429/refreshDeferred表示该query未入队时，保留refreshPending，空闲后允许一次启动。该轮已启动后的pending继续复用原job/cache，防止refresh删除已完成槽重采。

## 消费状态合同

完整分项仍位于`/var/lib/fs-data-archive/scheduler-state.json`。新增family/cadence/lastObservedAt/correctionDay/refreshPending/reason/retryable/httpStatus；原query、requestedAt、attemptStartedAt、failures、retryAfter保持。

- complete：原完整证据核验或完整归档复用，failures清零。
- pending：原任务尚未完成，不把观察当失败，不重复启动。
- busy/unavailable：锁繁忙、502/timeout等瞬态沿原300秒指数退避到4小时；不设置永久次数上限，来源恢复后仍能自动接续。
- failed且retryable=false：明确权限/参数/schema错误停止该项，保留安全原因，不无限请求。修正权限/来源后需要明确复核；其他正常入口若已生成同合同完整归档，会被原缓存检查识别并同步complete，不手改旧状态伪称成功。

`job-status.json`保留at/daily/history/cleanup。daily/history新增missingCount、unobservedCount、terminalCount、repeatedFailureCount、missing前64项及stateFile；完整所有缺项在stateFile。missing项含query/family/status/reason/retryable/failures/retryAfter。消费者可按自身范围明确缺失，不等待整轮完成；连续失败数量保持可见，供原告警/任务机制使用。job-status是整轮结束快照，进行中需读原scheduler-state，不能把该文件旧时间当成数据齐备。

## 保持与验证

已核三份daily_archive：exact-range当前3d64968f…、Hermes/marketing兼容631cc57c…均已一年retention且无07门槛，本轮不修改这三份。三月自动补采范围、项目2026-09-01起点、当日600秒、已封账策略、原完整性检查和按需查询能力保持；不新增大补采、模型、价格操作或夜间并发。

新增28项archive定向检查（含pending重置旧terminal标记、HTTP响应体IncompleteRead后其他query仍完成回归）；服务器临时目录无网络执行26/26通过，包含真实Linux原scheduler锁非阻塞/不可重入及systemd calendar表达式验证。Windows新增28项（1项Linux专属skip）及既有13项nightly通过；dashboard130项通过（2项平台skip）；compat archive34项通过。正式CI已注册test_archive_jobs，待root统一提交后执行。所有服务仍未发布/重启；今晚自然周期和真实失败恢复尚未验收。

只读取证：`p1_archive_retry_baseline_evidence.jsonl`。服务器隔离自检：`p1_archive_retry_linux_selftest_evidence.jsonl`。两文件位于本次admin-recovery运行证据目录，不含凭据或客户内容。
