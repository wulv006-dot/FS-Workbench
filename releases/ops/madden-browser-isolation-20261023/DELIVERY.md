# 本轮资源与后台隔离交付

2026-10-23，北京时间22:20—22:32完成增量发布及只读核验；原业务/真实变价自然验收分开。没有为观察调用模型或写价。

| 范围 | 已落实 | 验收边界 |
|---|---|---|
| Madden | 240→360分钟，00:47:45下轮；552旧僵尸清零；竞品按需启动/空闲停止3GiB，执行器2GiB+init、原时限 | 原CLI只读后台4行、元数据启动/停止、worker退出通过；自然采价/实际写价及长期待手动 |
| Hermes桌面 | 当前Docker及systemd创建命令7GiB | 原4.83GiB峰留余量；本次不重启，原ID/StartedAt保持，当前内核限额读回 |
| Admin共享会话 | 当前Docker及systemd创建命令3GiB | 原约1.57GiB峰留余量；不重启、不重登录，ready且原login_attempts2保持 |
| 经营区间查询 | systemctl持久MemoryLimit2GiB | 原约1GiB峰留余量，原PID20173保持，内核实际限制读回 |
| RPG临时执行器 | srv_exec.py两条原Docker启动命令增加init、memory2GiB/memory-swap2GiB | 原执行器短时空闲维护后active；原ID/阶段/UNKNOWN/分类保持，未触发新RPG工单；新工单实际峰值待手动 |
| FC后台 | 原成本、预览、写价、恢复四个执行容器2GiB+init；分别启动独立Chrome、原共享Order身份，结束关闭；tmpfs64→256MiB | 只读价格页快照3预期ID/登录有效、实际Docker2GiB/init/移除通过；正式成本入口主动验收被审批拒绝，真实业务留原自然轮 |

限额为边界，不是预留；各上限可以相加超过主机15.25GiB，不能据此承诺所有业务同时顶峰不会OOM。未加CPU限制、未降低现有业务并发或关闭既有能力。RPG新工单及整夜并发的峰值尚未实测，不将本次空闲读回当长期容量验收。

FC修改发生于既有临时业务容器内部：竞品Chrome不再承载上述四条后台链路，8768身份浏览器继续保留唯一会话。新helper统一`open_backend/close_backend`，原全球身份错误直接报错，关闭owned浏览器；不启用独立登录或默默回退到竞品Chrome。成本/预览/写价/恢复原业务源码除浏览器连接和关闭绑定外逐字节保持，shell除init/资源/helper挂载/临时目录预算外原参数保持。生成器运行于服务器，原FC/RPG完整源码没有重新导出。

FC第一次只读快照在启动Chrome时失败：只读根目录令Chrome crashpad默认HOME不可写，SIGTRAP，临时容器已退出并移除、无业务写入。已将Chrome HOME/XDG目录设在原/tmp tmpfs；新正式CI与第二次真实只读快照通过。失败回执保留，不把首轮失败写成成功。原FC container/StartedAt保持；22:32原生浏览器CDP：1 owned idle、0商品页/Worker、0附加页面/新world；原monitor issues空，Order ready/login0。

三次发布均复用原house publisher atomic、全局锁、备份及CAS。RPG使用原DB短时事务保留队列，空闲/无dispatched才维护，保留原执行器锁；FC使用原queue/retry/writer/preview/cost锁，无未完成写入及在途任务才原位发布，FC服务无需重启。原发布回执与SHA见SOURCE-MAP；备份留在服务器，不导出凭据、单位完整内容或业务数据库。

当前正式CI代码head `dbfc0faeddc66d49320ab9aa195cbab8982b5704`、tree `da65e939473318d0a75e1bb5ba7cc036eea8f569`，run39970061028，Python3.9.18，24项/0失败/0错误/0skip；PR413未合并。后续文档归档head另记SOURCE-MAP，不覆盖活动代码CI证据。

21:14原事务自然轮补齐：21:23:01 exit0，snapshot `20261023T132301Z-4a523080d8bd6d48` / SHA `52e64c…2000`，17个required primary全部available且labelsVerified，runner退出无残留。该轮21:14—21:19曾出现间歇Order不可用，当前已恢复；未证实根因，不把服务退出成功当整个窗口健康。活动watch含120秒默认防抖、覆盖环境未核，不能因无群消息直接认定告警投递坏。

手动验收：本对话原跟踪按用户明确要求保持暂停，没有新建通知或定时采集。下一FC原自然轮约23:10后（原调度实际派单为准），Madden为10月24日00:47:45；RPG等原变化决策派单。核原job/operation ID、cost/source-complete、no-change或真实写价/读回/清缓存、phase finished、worker退出和OOM/限额；UNKNOWN/部分写入只对账，不重放。至少12个原轮及日夜覆盖仍OPEN。

自动审批拒绝两类动作：生产FC/RPG源码及片段外传（已改用哈希/布尔元信息、既有本机精确源及服务器端补丁）；主动调用生产成本采集入口（未执行，已改为后台只读快照）。没有改通道、伪装同一被拒动作或扩大登录/采集权限。用户日后手动自然验收；本轮不另请求这项采集授权。
