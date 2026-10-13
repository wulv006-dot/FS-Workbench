# Hermes FS 接线候选与放行范围

本轮继续原任务及草稿 PR108。独立代码 `hermes_fc_pilot_20261013/` 对应私库 `releases/fs-dashboard/hermes-fc-pilot-20261013/`；只在此目录开发，不覆盖历史发布冻结源。部署映射见其中 `release-targets.json`：34 个目标，两份共享活动源码的最小兼容改动、专用只读运行目录、systemd 单位及 drop-in、独立页面。现有入口和 timer 不切换。

FS 原进程持有现有百炼 key、provider_slot、model_calls。Hermes 只持短期任务令牌，14 个受限工具复用 Admin 明细/原生统计、Order 参考利润、既存报告和诊断读取，不允许任意 URL、SQL、shell、业务写入或消息。统计目录不代表每个菜单字段都已经接通；以 ADMIN-CAPABILITY-ENTRY.md 和每次证据的实际来源/范围为准。

任务默认调查/定价 max，日报/KPI high；参数显式 enable_thinking=true 和 reasoning_effort。思考模式每次输出空间 16384 tokens，旧消费者维持 6000；没有新增累计 token、轮数、总时长或低金额试点配额。原请求边界、服务锁、费用估算和未知处理保持。原始 reasoning_content 私下跨工具轮传递，不在报告/UI 展示，也不重复计算 completion 中的思考成本。

取消先撤令牌，Run 202 和 stop ACK 不代表工作停止；接收过程的 run_id 仍必须绑定，等官方终态及原代理 in-flight=0 才结束。FS 重启将未决请求标 NEEDS_RECONCILE，不盲重放模型或新 Run。每个所有者仅能读取自己的任务/证据；既存公共日报与本人的 Hermes 历史分别标来源，旧建议未确认执行不能当作效果归因。

固定官方 v0.21.7/71d34bad 镜像已独立构建，Python3.14.7 / SQLite3.53.4；生产宿主 Python3.9 不升级。隔离进程 UID/GID9876 无登录/无 sudo/无 Docker 管理，只允许 loopback8940/8941；配置和上下文只读，个人运行档案/结果专用目录可写。已有镜像精确 ID 进入发布合同，不允许运行时拉取新镜像。

已批准的身份创建是发布前置步骤，不由Hermes unit自行扩权：最终CI/合并及SHA读回后，维护者在受控stage执行 `python3 provision_identity.py inspect`；确认无UID/GID/名称碰撞后，执行 `python3 provision_identity.py apply --approved-fc-readonly-identity`，只创建9876无登录、无附加组、不创建home，不提供sudo/docker管理权限。已有不同身份拒绝并保留，脚本重复调用仅校验。然后才调用原publisher；身份/网络真实读回另验。

补充读取按查询固定首次可用结果，pending可完成后再固定；报告Admin捕获ID仅作为analysis_anchor_id。原生Admin/Order的独立source_snapshot_id、实际读取时间及原sourceDataAsOf保留，不把后读来源假称为同一个后台缓存时点。同查询不跨刷新换数，也不恢复旧全页缓存或新增重复采集。

沿用当前导航发布者、原导航/共享前端/collector/model 锁，精确 CAS、备份、原子替换及回滚；新增 scope 只允许映射的 34 个目标。受保护 boss、fc_deep_model、daily/detail/source/permissions、经营首页等需重新实际读 SHA。最终 CI、合并、发布和读回依次完成，不能把候选或页面显示当作真实接通。

截至本次记录，101 项本机合成测试通过；官方 high 工具往返 CI38429960931 已通过。新版 high/max 与第二用户轮仍须最终正式 CI。真实百炼、真实 FC 周调查、真实浏览器与业务质量均未验。任何失败显示“分析未完成”；默认入口替换仍以用户看到真实成品并认可为条件。原 Library 文件 Windows 物化缺口保持，派生背景明确标 provenance。
