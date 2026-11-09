# 发布证据索引 — 2026-11-09

- 当前执行合同：[周更规则](../WEEKLY-RULES.md)、[接口](../INTERFACES.md)、[Hermes合同](../HERMES-CONTRACT.md)。
- 当前修正：[selection-corrections/ACCEPTANCE.md](selection-corrections/ACCEPTANCE.md)，尚待部署及真实验收。
- 本页以下初始41目标、curl-fix、cardinality-fix、RECOVERY及LIVE-ACCEPTANCE均为历史操作证据，不作为当前选品或自动执行指令；归档release脚本与curl-recovery审计工具保留用于原ID核对和获批恢复，不由周更调度加载。

## 初始已批准发布（历史证据）

用户批准PR930合并部署，真实Sol三页草稿验收通过后启用周日12:00（UTC+8）计划。活动发布、优惠券写入和社区消息不在本次自动执行范围。

- 合并提交：2a9eab3d847208e174adb8f056ab1f2ccc68101c；候选源cf0fb973ad9e15b6376e482f4c5dcf3715f73e68。
- 正式CI：42570130912 / PR fast 1800通过。此前1798首轮因Python下载HTTP504失败，重试通过；随后按更新main重新组合并通过1800，不绕过检查。
- 发布ID：nav-20261109T060138Z。
- 备份及原journal：/var/backups/fs-navigation-20261006/nav-20261109T060138Z。
- 远端stage：/opt/fs-release-stage/fc27-weekly-20261109/combined-release-stage。
- manifest SHA：8ebdef376027bd362a1e26da5b6a4d88e7e104e90102ac9b9c15ad6bc082c2e3。
- launcher SHA：750f2b9641e3e93f6789b358c6c0fb3ee3946b1a56170e1e6ba6cb5579456356。

41个目标为批准的40个源码文件和公开运行必需的static-manifest.json。派生清单保留原110项，只更新8项静态资源hash；before=3561daaf59a52d931d125f71b5f81f85e3b4c4a5cf715796f29fd0e21a5bc2ae，after=bc828dc60a9edb19b42805e9e5e1deb8a68d5a6a17e277eead42b68b123b752d。候选必须从Git原字节导出，不能用Windows工作树CRLF替换。

release.py只适配现役release_ui_finish.publisher，未复制发布器。保留原目标验证、CAS、备份、journal、双发布锁，并组合原HermesAdmissionFence和model_release_lock。部署前在途任务计数均0；激活仅fs-campaign-dashboard、fs-campaign-runtime、fs-business-range。没有重启官方Hermes worker/FC服务，没有业务timer动作。

原inspect确认sourceCAS/protectedCAS通过；apply返回applied-awaiting-actual-http-role-acceptance。其后独立读回40/40源码hash一致；四个相关服务active、UNIX周更socket存在；原真实FS管理员浏览器成功打开运营台。公开8949运行服务三页和共享tracker均HTTP200，三页引用共享tracker。部署状态不是活动发布或自然周更证明。

如遇未知结果，先读上述原journal/manifest及目标hash，不换release ID或重放apply。回退仍需具体批准；已产生not_dispatched后保留兼容账本读者，不整包回旧代码或改写DB。本目录不含凭据、生产DB或模型prompt。
