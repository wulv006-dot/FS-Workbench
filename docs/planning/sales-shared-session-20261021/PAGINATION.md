# Sales 全局会话抖动与分页完整性

2026-10-21。原Sales全量任务15:33:22开始，15:47:40在Order次段第40–44页连续global_order_unavailable后退出1，没有推出新dashboard。Order随后又ready；分支已确认裸发货页健康探针超时及notready缓存使有效会话短暂不可用，轻量探针由该分支负责。

复核还发现旧采集器会跳过1–4个失败页，成功一页又清失败计数。这不能证明分页完整。本补丁只替换fetch_deliveries_range，其余函数与全局设置AST保持一致：每页最多3次，global_order_unavailable等待25秒覆盖原20秒健康缓存；其他读取异常等待2/4秒；只有读到当前页才前进，最终失败立即整轮退出no_publish。没有密码登录、重放业务写入或本地会话回退。

源 `/opt/sales-dashboard/collector/fetch_all.py`：输入SHA256 `40b10656b8ece6521de3211fbaddc99ce3daaa2fce0a61e4b7488af372edcb91`，输出 `28f71b37cea11406cf66cf6e1fa9483d243aec072916e88a105924672c7df396`。备份与单次回执 `/var/backups/fs-sales-pagination-20261021-v1/`，沿现有全局发布锁、空闲检查及逐文件CAS/原子替换；实际3.9解释器编译通过。

3项直接执行当前源函数的测试通过：短暂失败只重读同页且不重复记录；持续失败不前进也不返回部分列表；首分页同样有界重试。Admin会员接口真实读取1个样本通过，只记录成功与数量，未导出用户资料。

15:59:01启动一次新代码全量复跑（原systemd服务、PID29017）；该启动回执不等于完整发布。原失败保留，timer在真实作业和发布读回前保持disabled。最终结果单独写入验收回执，不改写此阶段事实。
