# 原服务增量发布来源

本目录保存2026-11-09实际执行的最小构建/发布适配、精确源证明、差异与独立验收。当前结果见[ACCEPTANCE.md](ACCEPTANCE.md)；[RUNBOOK.md](RUNBOOK.md)是发布前操作说明，不能用其中“尚未发布”代替实际回执。

- `source-proof.json`固定合并提交`cb87b4901a81ffd313e06e4882a3b33918519ea2`、9个目标的现场before SHA/候选after SHA及各原维护源SHA。
- `review.diff`仅含本轮必要增量。完整现场before源码、业务SQLite备份、cookie、provider状态正文和客户订单不入本目录。
- `build.py`、`release.py`为实际脚本的逐字节留档；后者继续调用原`runtime_release.frozen`与原锁/CAS/journal/readiness，不是独立替代发布器。既有base/readiness的确切SHA见验收记录，源码仍在原维护路径。
- `delete_old_review.py`是用户明确要求删除唯一旧评审的维护脚本，不注册成业务工具或一般清理入口；其实际备份和回执留服务器私有目录。
- `test_overlay.py`依赖忽略目录中的现场before与精确overlay包，未纳入CI，不能在缺少这些私有现场输入时宣称CI覆盖。`test_delete_old_review.py`仅内置表结构并生成合成记录，独立纳入CI，不携带生产preview或业务数据。原业务模块及连接器的仓库CI另由主记录说明。

可复现的实际工作布局是`.agent_runtime/connector/original-service-release/`，包括`before/`、`increment-baseline.json`、`package-cb87b490-final/`等；build脚本按当时该目录层级定位仓库。不能直接从docs目录运行或缺少新鲜现场源时装配发布。重新发布必须重新核现场、恢复该明确布局或审阅适配路径，不能把历史before SHA当永久线上基线。

实际stage：`/opt/fs-release-stage/fs-connector-original-readonly-v2-20261109T051410Z`。发布与回退都由root串行执行；本子任务未执行Git操作。
