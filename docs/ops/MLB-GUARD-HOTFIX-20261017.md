# MLB 上架安全修复 2026-10-17

## 范围与负责人
老D负责恢复 MLB 已审批模式、停用开关、当前执行报告及静态目录边界。用户已要求处理 MLB；RPG 由陈超负责，已在 PR201 评论同步。基线：34ccceaba755f9b8ede754bc06738d96a38d465e。只改 MLB 与既有 pr-fast 的直接测试接线，不改业务报价、凭据、角色或生产配置。

## 改动
- 批准前重新检查服务 enabled、脚本及凭据是否存在；dry_run 和 confirm 必须与冻结快照一致，缺失/变化拒绝，不自动执行。卡片指纹同时与快照及状态校验。
- 每次执行使用独立 invocation_id 和输入/报告路径，保留旧报告作为核对证据，启动失败不读旧成功报告。超时、非零退出、空/畸形报告不能报告成功，不重试真实写入。
- 静态 handler 重新接回现有 safe_static_path，拒绝邻接前缀目录及符号链接。
- 新增离线行为回归接入 ops-modules；修复既有端到端脚本的源目录/静态依赖/报告路径适配。

## 云端验证
- 11 个新行为测试在修复版通过，0 skipped；在原始代码上失败（14 个子断言失败、1 error），证明覆盖真实回归。
- 既有 OpsModuleContracts 9/9 通过；同 pr-fast 隔离运行新测试 11/11 通过。
- 本地临时 HTTP hub + 合成 writer 的旧端到端测试：后端 48 项通过，8 项前端文本断言失败。原始后端与修复后端均为相同 48/8，原因是仓库 var/www/mlb-online/index.html 缺该套测试期望的新审批 UI。未放宽断言、不声称完整端到端通过、不拿仓库旧页面覆盖线上页面。
- 测试仅临时目录/回环 HTTP/合成数据与 fake writer，无真实后台访问或商品写入。

## 发布状态与停止条件
未部署、未独立读取生产版本，不能认定线上风险已解除。当前另有服务器安全恢复讨论，旧环境不能默认可信。上线须先由既有发布通道确认可信目标、活动源、并发任务/写卡进程、待审批次及来源哈希；保留 DB、队列、快照、配置、账本和历史报告，不重放未知或成功写入。
部署文件仅 mlb_server.py、mlb_writeback.py，且目标已有同版本 static_path.py；运行目录历史为 /opt/mlb-online，实际以现场服务启动路径为准。发布前备份这两个活动文件并记录哈希；应用必须在无在途写卡进程的维护窗口重启，避免重复/中断业务写入。配置和凭据不入包。
验收先检查目标代码哈希/健康与既有只读任务状态，真实上架不用于故障复现；审批拒绝场景由隔离测试覆盖。自然业务效果需另行记录。若路径/模式/现场版本不一致停止部署。
回退只恢复本次两个代码文件（经安全复核）；保留所有业务状态及 invocation 报告，不恢复已知有漏洞的旧代码作为长期方案。

## 文件 SHA-256
- opt/mlb-online/mlb_server.py: bbe63c6488bfc4c0c470760ef4c931d1a37b44793a2750189987ef1792c6a3ac
- opt/mlb-online/mlb_writeback.py: b186fd38548f7829697715cb95347c355fff02aaaf533d31e013f74157efcd4c
- opt/mlb-online/test_writeback_guards.py: 2e737b73355c3f0e97b855ad6d1bccb9a54d1da8908036bf45fc3b196f856cf2
- opt/mlb-online/_selftest/tests/verify_writeback_e2e.py: 72fa89dbaa8c0e10aec5bedce98b13e63f76ad433a3aacc92c8e3566a968137f
- tools/pr_fast.py: a927627ab0b98ab5e317eb127dfee926459c5f41f2321090d836e3336a9a7f15
