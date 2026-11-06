# FC 上线准备：仅 range 受控停读

#862 已合并为 `ff51fc4c6e503ed381a7bfdb80b9ad0fdf108b47`。载荷版本仍为 `fc-dashboard-20261106-405be66dd0e0`，业务源码不改；本补充只增加原 CAS 发布器的写前维护包装与隔离测试。生产 apply、restart、nginx reload、正式知识和 Notion 发布尚未执行或获本次执行授权。PR 描述不修改。

## 范围与停读语义

入口改用 `deploy/fc_maintenance.py`，其 `load_base()` 调用已有 `fc_dashboard_release.load_base()`，再包裹既有 admission/guards/rollback 钩子。保留原十二目标、冻结发布底座 SHA、CAS、原始备份、journal、锁及失败回滚。不改 `range_api.py` 或任何 unit 定义，不暂停 timer、P0 改价、API、worker 或采集。

实际过程是在原 admission 文件锁和数据库保留期间，仅停止 `fs-business-range.service`；确认无待执行 systemd Job、inactive、MainPID/ControlPID 都为零、原控制组及所有子组为空，才允许首个文件替换。每次替换前重复确认；回滚恢复第一个文件前再次停读。原字节尚未修改时失败，尝试恢复原服务；修改/回滚未确认时保持停读，不能悄悄重开不确定代码。原发布器负责重启、健康和 nginx 校验/加载，最后再次健康验证。

这是**取消在途只读请求的维护中断**，不是等待所有任务自然完成。生产 systemd 为 `KillMode=control-group`、`TimeoutStopUSec=1min 30s`、`SendSIGKILL=yes`；用户确认范围须明确允许 range 单元内尚未结束的读取被取消，最长可能经历该系统默认停止超时。业务写入和 P0 单元不属于控制范围。停读期间相应查询可能暂时失败，需要页面重试。

## 只读现场与隔离证据

2026-11-06 06:58 UTC 只调用候选维护器 `remember()` 与 `healthy()`：现网 Python 3.9.18、range PID18742、active/running、无 Job、Triggers/TriggeredBy 为空，控制组 `/sys/fs/cgroup/systemd/system.slice/fs-business-range.service` 已确认；没有执行 stop/start。P0 `fc-pricing-v3.service`、`fc27-cloud-api.service`、`fc27-cloud-worker.service` 均 active，PID24231/24218/24224，其原生依赖中无 range。这里不把系统依赖检查当成所有应用级依赖已证明。

06:49–06:54 UTC 重新读取的三个既有 FC 模块、range、原 JS、壳、CSS、导航哈希与先前基线一致；新静态资产和新 `fc_dashboard.py` 均不存在。导航实际 mode 为0600，原发布 journal 保留其 beforeMode；不能误改成0644。range SHA 为 `2b10d7bb1ef3dce886247163163552466103ed189fc377a29b66e62a53c7846b`；导航 before SHA 为 `c5733fbd88d63005ecc7c3ce350acddb91ce6fe4a2af2a1712075843602ffffe`。

183 Linux 临时目录执行17项测试全部通过：真实 flock、SQLite admission、冻结 CAS、实际原子替换与 journal；systemd/HTTP 为模拟。覆盖首写前停读、残留子进程、待执行 stop Job、停止失败无写、原状恢复、成功 apply、写中失败、重启失败自动回滚、显式回滚、回滚 CAS 漂移与自动回滚失败保持停读。隔离包 SHA256 `edbf2ce42303af77583a0a2e8e4d5eb6bac98ea7c8f7b59eaa78f12c83800daa`。这些测试不冒充生产停止、恢复或真实页面验收。

## 执行前确认

必须使用同一份精确 manifest：七个静态资产、四个 FC Python 模块和一份导航配置；导航只替换三个 JS、三个壳及三条 CSS alias。候选完整 SHA 见 SOURCE-MAP，执行前重新读回全部 before SHA、元数据、保护项和 runtime 状态，任何漂移即重新核实，不重放旧清单。`maintenanceBefore` 仅列 range 原状（active/enabled/control-group/yes/1min30s，Triggers/TriggeredBy 为空），不列其他可变控制对象。

建议窗口为 **2026-11-06 15:15–15:25 Asia/Shanghai（07:15–07:25 UTC）**，未预约或执行。用户须确认具体窗口、仅 range 维护中断与取消在途只读查询、独占 service 控制（期间不并发 start/restart range）、十二目标和既有 nginx reload/范围重启。窗口过期就重新提出，不自动顺延或停服。没有自动触发器的现场证据不阻止管理员手工同时启动；因此独占维护控制是明确前置。

备份和回滚继续使用 `/var/backups/fs-navigation-20261006/<唯一 nav-YYYYMMDDTHHMMSSZ>`，原 approved manifest SHA 和 journal。显式 rollback 使用相同维护包装及原批准 SHA，支持 reader 已因失败保持 inactive 的恢复入口，先停读确认后恢复原文件；CAS 漂移或回滚失败保留现场、维持 range 停读并报告未知，不盲目重放或覆盖他人数据。未生成可直接执行的 approved manifest，也没有实际 release ID。

发布后验收应分别记录：十二目标及保护项 SHA/模式读回、range/P0 状态和自然运行、nginx/本地健康、三个真实入口及角色权限、分类筛选与刷新返回、图表与导出一致、未知和缺金额提示，以及已核实发货统计与订单组毛利。生产新页面、完整历史与全部平台覆盖仍待真实验收；正式知识/Notion 不属于本次执行范围。
