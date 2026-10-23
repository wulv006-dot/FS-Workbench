# Madden 六小时、浏览器隔离与空闲释放

本轮共享资源边界及FC后台隔离也已上线，最终状态与风险见[完整交付](DELIVERY.md)。下面保留Madden首先上线时的具体证据；后续正式代码CI为24项，见SOURCE-MAP。

2026-10-23，北京时间22:02—22:05上线及只读验收。用户指定每6小时；后台与竞品隔离沿原全局身份，不建立独立登录。维护源 `madden_browser_isolation_20261023/`；精确文件前后值见 SOURCE-MAP.json。

- 原240分钟已改360分钟，配置19→20，pricing_revision仍7；ON/auto、PS/XBOX/PC、30%最低毛利、成本基准和汇率/利润参数保持。按原18:47:45工单时间顺延，下一轮 **2026-10-24 00:47:45 北京时间**，没有保存后立即派单。
- 原入口每工单创建带init、2 GiB内存边界及原时限的临时容器。后台session单独启动Chrome，申请原Order共享身份；竞品fresh context仍只连接竞品Chrome。任务退出后关闭临时Chrome/容器，原5秒调度循环有30秒空闲回收检查，不增加采价调度。
- 原Madden竞品容器保持身份、镜像、profile及端口，按需启动、退出后停止；限额3 GiB、关闭Docker自动常驻重启。原PID1仍是Chrome，没有将其宣称为已安装init；整容器每工单退出后释放进程树，防止跨轮积累。原552个僵尸的父进程21690下现为0，竞品容器停止、临时执行器0个。
- 发现原宿主启动脚本缺失、旧容器依靠已挂载inode运行。停止前从原容器恢复同字节文件，SHA `12fca545…679341`；元数据启动/CDP/停止验证通过，profile未删除、未重新登录。
- 真实原CLI `--snapshot-out` 只读验收：exit0，后台4行（21590/21592/21594/21596），login=false；执行器退出无残留、竞品保持停止。Order ready/login_attempts0，Admin ready且原login_attempts2保持。本次0竞品采集、0模型、0写价。
- 原18:47失败工单 `763694ac-4861-4da2-99bb-2e756228c60e` 及原operation ID保留，未重放；没有未完成审计。新的6小时配置只是恢复之后原自然调度，不将旧失败改写为成功。

正式CI：[PR413](https://github.com/wulv006-dot/FS-Workbench/pull/413)，head `5e660cdf85a676eacdb172e09400d46cfc3fb437`，PR fast run39965910783成功，18项、0失败/错误/skip。7个原定价/写入/恢复/调度业务函数文本哈希保持。早期CI因Python3.14与3.9的AST字段差异失败，改为对原基线函数文本的版本无关比较，未改业务函数或降低断言。

生产沿原house publisher atomic、两个全局锁、逐文件CAS、备份及同一发布ID。暂存归档首次因夹入本机pyc被白名单拒绝、尚未修改服务；重新生成仅六份生产文件后才发布。配置首次缺原CSRF头明确403，经只读确认revision19未变化后补原校验头；不是未知写入重放。PR尚未合并。

待验：00:47后的原自然采集/报价/实际写入或no-change结果、每工单峰值及连续日夜。只读快照成功不等于真实写价通过；当前health里重启后内存元信息p2pah_session仍unknown，不能冒称自然采成本成功。外站IGGM缺源仍单列，未在本次强行补采。用户已明确保持FC/RPG跟踪暂停、后续手动验收，未恢复或新建定时跟踪。

手动验收仅查看原任务及回执：原 `Invoke-Server187.ps1` 读取8792 `/api/madden/cloud/automation`、`/health`、`evidence/jobs/`、`browser-runtime.json`，核同job/operation ID、退出状态、原审计/读回与清缓存；查看竞品容器停止且madden-job-*无残留。不要点击采集、重放失败/UNKNOWN或为验收重新登录。

共享Hermes/Admin/经营查询边界、RPG单工单资源、FC四条后台隔离后续均已实施，详DELIVERY；各原自然周期和长期容量仍待手动验收。
