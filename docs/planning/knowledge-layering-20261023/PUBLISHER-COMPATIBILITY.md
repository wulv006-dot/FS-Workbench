# 既有共享目录合同兼容修复

PR367合并后，真实发布前inspect在`unsafe daily source boundary`停止，生产替换0。精确只读定位仅`/var/lib/fs-hermes-fc`：UID0、GID9876、0750、真实目录无链接。三个运行载荷及全部不可变知识载荷与用户已确认清单一致，没有权限配置变化。

复用用户分析当前已部署publisher的精确父目录合同（`releases/fs-dashboard/user-analytics-20261022/deploy/release.py`），该任务负责人也确认当前合同和发布窗口。本scope仅接受上述一个目录的同一UID/GID/完整权限位；不扩大到profile或其他组，不接受组写、其他UID、特殊权限位。原目标白名单、root校验、哈希/CAS、空闲、准入fence、锁、备份与回滚保持，不chmod/chown，不改发布器底座或全局安全配置。

这是一处发布器兼容修复，批准的10个生产载荷、原manifest、change_id及release-id保持。原已批准源码快照和收尾账本留在隔离原工作区；小修在独立工作区提交PR/CI并记录其commit/SHA，再复用原操作发布，不把预检失败当未知生产写入。

离线测试覆盖精确父目录通过、其他目录/其他scope/错误UID/GID/组写及特殊权限拒绝；同模块24项测试继续通过。实际发布必须等待用户分析正在进行的模型验收结束并协调空闲窗口，不打断其请求或接管FC策略。
