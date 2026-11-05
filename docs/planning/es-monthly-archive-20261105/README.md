# ES 月复核与重复归档清理

## 业务规则

日常只补新完整日。每周复核本月及前两个月：已经结束的月份按完整自然月；本月只到该次复核开始时的昨日，不能称已封账。复核跨日仍优先发布新日数据。新完整归档与最新日发布都成功后，才清理已证明冗余的旧日导出及旧月重复版本。失败保留旧正式数据，不增加每月多版备份。

## 现有链路与改动

- `es_order_structure.server_bundle_after(query, fresh_after, cycle_id)` 是调度内部入口；Hermes/API 公共查询仍不接受任意 force。周期 ID 与 fresh_after 在重试中不变。
- 它复用原 `_server_bundle` attempt/回执机制，周期成功永久复用，结果未知保留原 attempt 不重导。`api_dataset(capture_context=...)` 直接走原单次 export_bundle，绕过 server_bundle 与 export_dataset 两层旧档复用。未完整下载/解析的月文件不会发布新 manifest。
- 原始文件仍以 SHA 命名，同内容不复制。新 manifest 含周期身份，原固定 manifest 不被覆盖；每个新文件先写临时文件、fsync，再原子替换。完整月可直接服务日/周子区间，不因日期不精确相等而再生成导出。
- `user_customer_types.ensure_period(..., fresh_after=None, cycle_id=None)` 保持旧调用兼容；月复核调用明确 `daily=False`。`manifest_inventory` 只选择实际需要的完整覆盖及未被承接的日片，避免每次发布固定全部历史导出。
- `compact_after_publication(store, expected_publication_id, apply=False)` 生成计划；传其 `plan_sha256` 后 apply。实际清理由已有发布/作业锁串行，原 archive_access 保护文件集合，不新增定时器或框架。

## 哪些依赖必须保留

1. 当前发布记录的固定 manifest、SHA 与其工作簿。
2. 未解决 ES attempt 对应范围；原请求仍须对账。
3. 所有仍存在 manifest 引用的原始文件；同 SHA 被正式月共用时不能删除。
4. Store 的 orders、identities、revisions、snapshots、snapshot_members。revisions 是历史冻结结果重放所需的事实变化，不是重复备份。

旧用户 snapshot 的 recipe 已内嵌实际使用的新老客标记；它通过 Store/revisions 重放，不需重新打开旧 XLSX。FS/Hermes 的已有报告/来源快照保存投影结果。当前新查询依赖 publication pin，读取 publication 至消费 flags 期间持原 archive 锁，完成后才做 Store 分析；snapshot_id 直接读取不加该锁。渠道看板 names→customer_types 也在同锁内读，避免与清理交错。

## 清理白名单与边界

仅处理指定私有 archive 根内、64 位 SHA 命名的 manifest/xlsx。旧文件必须由当前已发布的完整月范围承接，且不在当前 publication/其他明确文件引用/在途范围内。按去重后的 `(订单号, 产品类型, 游戏)` 记录数核承接；同单缺子行、唯一订单未覆盖、解析不完整均保护，不要求金额/退款状态与旧版完全相等，以容纳正常修订。

不按年龄扫描删除未知孤儿、临时文件或根外路径。所有符号链接、路径越界和 hash 不符拒绝；引用读取不完整只给保护原因。清理先删已解除引用的旧 manifest，再删确实无任何剩余 manifest 引用的 raw，避免仍可选中的 manifest 指向被删文件。

进度只写一份 `.compaction.receipt`（故意不使用 `.json` 扩展，避免旧 manifest glob 将其误读为业务导出）。中断后先核原 plan；若次日发布已改变引用，新 dry-run 从原 receipt 保留的剩余目标重新核验，标记 `resume_from`，不会把新日文件塞进旧计划。未知孤儿仍不删。无候选是正常成功。

## 验证与上线边界

新增测试覆盖 fresh 两层复用、同周期成功/unknown 不重导、固定 manifest 不覆盖、完整月读日片、缺子行与唯一订单保护、同 SHA 保留、路径/符号链接拒绝、原 plan 中断恢复、次日日更后续清理、渠道真实读取、pinned identity 发布、无 raw 的旧 snapshot 重放和短锁释放。

源码候选及隔离测试不等于生产清理。生产目标为 `/opt/fs-hermes-fc/es_order_structure.py`、`user_customer_types.py`、`user_query.py`、`channel_source.py`；调度线另外管理 weekly/jobs/UI。`user_query` 的 main 含尚未发布的其他能力，生产只应应用本轮短锁及状态字段差分，不整文件覆盖。`user_customer_types` 的主线新增身份方法也须与本轮实际部署的 weekly/Store 合同配套，不据 Git 合并推定已经上线。
