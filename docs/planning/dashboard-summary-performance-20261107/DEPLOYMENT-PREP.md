# 2026-11-07 连接恢复与发布准备

## 已完成

- 使用项目现有专用运维入口成功连接 183 和 187；沿用严格主机验证，没有使用用户排除的备用身份，没有修改白名单、凭据或 SSH 设置。
- 183 Python 3.11.2 独立临时目录验证：汇总快路径 2、归档 17、刷新 10、直接 Admin 5，共 34 项通过。首次测试包漏带 archive_jobs.py 导致归档 2 项错误，补齐同版本依赖后只重跑归档，17 项全部通过。未安装依赖、开放端口、修改业务服务。
- PR #896，代码提交 7309593bc0914bf7cd9fc6a0d9ac9e32a2f28803，正式 CI run 42374360327 成功；未合并、未部署。
- 187 实际运行 Python 3.9.18，fs-business-range.service 为 active。live_summary、daily_archive、summary_bridge 与当前修复基线逐字匹配；三份经营 JS 和三份看板 shell 亦匹配。
- 归档目录只读检查：2026-10-08 至 11-06，18 个主要 profile 的 native 和 summary 均有 30 个自然日目录记录；部分新增游戏 summary 只有 11-01 至 11-06 的 6 天记录。日期记录存在不证明每种网站/分类合同均完整。
- 抽查 MMOEXP、FC27、MLB26、NBA2K27、NFL27、RS 的该整段区间对象，均 status=available、现行 v2 合同；前五种对象的 Admin/Order/Shipping 均 available，RS 为 Admin/Order。对象读取、解压、JSON 解析实测 0.56–2.64ms，仅为服务器文件读取样本，不是冷读基准或页面端到端耗时。FC27/MLB/all-site、MMOEXP main/all-site 已存在单独范围对象；不将未查范围推定为命中。

## 准备好的具体发布范围

本地载荷 `.qa/summary-performance/payload/`，清单 `.qa/summary-performance/payload-plan.json`，applied=false。

1. 七份静态 JS（经营三入口、看板外壳三入口、实际首页外壳）发布至独立版本目录 summary-performance-20261107-7309593bc091。
2. 当前导航配置只替换对应七个精确 alias，保留其余路径。
3. 更新 /opt/fs-exact-range-20261001/live_summary.py；沿现有 publisher、锁、基线校验、备份及恢复流程发布，范围服务需要受控重启，Nginx 需配置检查及重载。
4. 实际首页 37fe 与仓库 UI 模板有历史差异，载荷从生产只读副本精确移植本次三处改动，保留其余代码；语法及本地浏览器昨日查询、Admin 显示、Order 缺失状态通过。
5. 发布后验收昨日首页、全局与 FC/其他游戏 30 天核心卡、细分不借总数、旧值保留、当前明细及权限状态；记录真实耗时和版本。

不修改归档库、订单数据、定价、采集定时、权限或 RPG 服务。沿 HOTFIX 的具体清单确认要求，本次生产切换仍待用户确认；尚未执行 publisher 生产预检、合并、服务维护、部署或上线页面验收。发布前须再次校验现场版本，变化则重算差异。

证据：本地 `.qa/summary-performance/live-scoped.txt`、payload-plan.json、test_live_home.cjs；PR https://github.com/wulv006-dot/FS-Workbench/pull/896 。历史 REVIEW 中连接阻塞与待 CI 段落以本记录为后续更新。
